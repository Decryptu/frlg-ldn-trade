"""RFU block transfer - the ACK-gated CHILD send sub-FSM + the receive reassembler.

Loss tolerance is first-class here (the wire is lossy and the capture is full of resends):
  * RECEIVE: fragment writes are idempotent and order-independent (a bitmask of received
    indices); duplicate/reordered/retransmitted fragments converge to the same block; an INIT
    resend of the SAME (count,owner) does NOT wipe progress.
  * SEND: every stage RESENDS until the host's wire-observable reflection (IN owner=0x81, fed
    into peer-1) acks it - INIT until echoed, then stream, then HOLD the last fragment and
    re-queue ONLY the still-missing fragments (HandleSendFailure) until receivedFlags is full.
    A resend-count watchdog advances if the reflection stalls (so it never hangs offline).

Ports Rfu_InitBlockSend / SendNextBlock / SendLastBlock / HandleSendFailure
[link_rfu_2.c:1333-1421, 1015-1042] and RfuHandleReceiveCommand [link_rfu_2.c:1125-1231].
"""

import math

from . import rfu

FRAG_BYTES = 12


def frag_count(nbytes):
    return max(1, math.ceil(nbytes / FRAG_BYTES))


def all_received_mask(count):
    return (1 << count) - 1


# ---------------------------------------------------------------------------
# Receive side
# ---------------------------------------------------------------------------
class RecvBlock:
    """Reassembly state for one peer (mpId). Idempotent + retransmit/reorder tolerant."""

    def __init__(self):
        self.count = 0
        self.owner = None
        self.flags = 0
        self.buf = bytearray()
        self.receiving = False
        self.done = False
        self.last_index = -1            # raw low byte of last SEND_BLOCK = gate (1)
        self.epochs = 0

    def on_init(self, count, owner):
        # New epoch only when size changes or we're not mid-block; a same-size INIT resend
        # mid-transfer is treated as idempotent (keeps accumulated fragments).
        if (not self.receiving) or self.done or count != self.count:
            self.count = count
            self.owner = owner
            self.flags = 0
            self.buf = bytearray(count * FRAG_BYTES)
            self.receiving = True
            self.done = False
            self.last_index = -1
            self.epochs += 1

    def on_block(self, index, frag12):
        if not self.receiving or not (0 <= index < self.count):
            return
        self.last_index = index
        self.flags |= (1 << index)
        self.buf[index * FRAG_BYTES:index * FRAG_BYTES + FRAG_BYTES] = bytes(frag12[:FRAG_BYTES])
        if self.flags == all_received_mask(self.count):
            self.done = True

    def data(self):
        return bytes(self.buf)

    def consume(self):
        """Return the completed block and arm for the next epoch (mirrors ResetBlockReceivedFlag)."""
        d = self.data()
        self.receiving = False
        self.done = False
        self.flags = 0
        return d


class BlockReceiver:
    """Dispatches the positional IN slots of a frame to per-peer reassemblers and surfaces
    completed blocks + the latest LINKCMD/REQ the host sent."""

    def __init__(self, max_peers=5):
        self.peers = [RecvBlock() for _ in range(max_peers)]
        self.last_req = None            # most recent IN SEND_BLOCK_REQ reqtype
        self.last_cmd = {}              # mpId -> last parsed slot dict

    def feed_frame(self, unwrapped):
        """unwrapped = gbaframe.parse_in(...) of an IN host frame. Returns (completed, reqs) where
        completed = [(mpId, count, data), ...] for blocks that finished on this frame, and
        reqs = [reqtype, ...] for SEND_BLOCK_REQ slots seen (host pulling a block)."""
        completed, reqs = [], []
        if not unwrapped:
            return completed, reqs
        for mpid, slot in unwrapped.get("positional", []):
            d = rfu.parse_slot(slot)
            if d is None:
                continue
            self.last_cmd[mpid] = d
            peer = self.peers[mpid] if mpid < len(self.peers) else None
            if d["op"] == rfu.SEND_BLOCK_REQ:
                self.last_req = d["reqtype"]
                reqs.append(d["reqtype"])
            elif peer is None:
                continue
            elif d["op"] == rfu.SEND_BLOCK_INIT:
                peer.on_init(d["count"], d.get("owner_raw"))
            elif d["op"] == rfu.SEND_BLOCK:
                was_done = peer.done
                peer.on_block(d["index"], d["frag"])
                if peer.done and not was_done:
                    completed.append((mpid, peer.count, peer.data()))
        return completed, reqs


# ---------------------------------------------------------------------------
# Send side (CHILD, ACK-gated) - one block at a time
# ---------------------------------------------------------------------------
INIT, STREAM, HOLD, DONE = "init", "stream", "hold", "done"


class BlockSender:
    """ACK-gated child block send. tick(ack) -> the 7-int gSendCmd for this VBlank (idle when
    waiting/done). `ack` is the peer-1 RecvBlock (the host's reflection of our block); pass None
    to run purely on the resend watchdog (offline)."""

    # HOLD re-send pacing: emit one re-send, then idle this many ticks. HOLD is the UNBOUNDED part of
    # a block send - it repeats until the host's reflection confirms - and the host consumes our slots
    # far slower than we can offer them. Measured (j41): our 9 card fragments were all on the wire by
    # 13.59s, yet the host's echo of our slot had only reached index 5 by 15.13s while we pushed
    # fragment 8 at ~7-25/s; it then stopped transmitting entirely. Idling between re-sends keeps the
    # guarantee (we still repeat until confirmed) without burying a parent that is already behind.
    HOLD_RESEND_GAP = 6
    # Idle ticks between consecutive STREAM fragments. Matching the parent's POLL rate is not enough:
    # a long run of back-to-back non-idle slots is what kills the console, even when every slot is
    # credit-paced and the tag sequence is provably clean (scratchpad/tagcheck.py: 0 breaks).
    # Measured, three times, always the same shape - it acknowledges the first one or two slots of the
    # burst and then stops transmitting entirely:
    #     j34  17 LinkPlayer fragments fast -> echoed 0 then 9, died
    #     j45   9 card fragments at ~40/s   -> died mid-burst
    #     j46   9 card fragments at ~40/s   -> echoed 0 and 1, died
    # Meanwhile the console streams ITS OWN 9-fragment card at ~6/s in the same runs and it always
    # lands. So pace ours to the same order: one fragment per STREAM_GAP+1 ticks (~10/s), which puts a
    # 9-fragment card on the wire in ~1s and a 17-fragment block in ~1.7s.
    # Default 0 = unpaced. This class is shared with the HOST and Mystery Gift senders, which drive
    # their own cadence and whose offline tests assert a fragment per tick; only the JOINER sets it.
    STREAM_GAP = 0

    def __init__(self, data, owner=1, watchdog_init=4, watchdog_hold=6, trust_pia=False,
                 stream_gap=None):
        self.data = bytes(data)
        self.count = frag_count(len(self.data))
        self.owner = owner
        self.state = INIT
        self.index = 0
        self._init_sends = 0
        self._hold_sends = 0
        self._hold_gap = 0               # ticks idled since the last HOLD re-send (HOLD_RESEND_GAP)
        self._stream_gap = 0             # ticks idled since the last STREAM fragment (STREAM_GAP)
        if stream_gap is not None:
            self.STREAM_GAP = int(stream_gap)
        self._rr = 0                    # round-robin cursor for re-queueing missing frags
        self.watchdog_init = watchdog_init
        self.watchdog_hold = watchdog_hold
        # trust_pia: send each fragment exactly ONCE (fire-and-forget) instead of the decomp's
        # re-send-until-the-host-confirms loop. The decomp loop is FAITHFUL to the Switch (its
        # HandleBlockSend/SendNextBlock/SendLastBlock/HandleSendFailure have ZERO REVISION branches -
        # a real Switch re-sends identically), but it exists for the GBA's LOSSY raw RFU adapter. Over
        # our high-RTT bridge the emulator tunnels through Pia's RELIABLE layer, so Pia already delivers
        # (+retransmits) every fragment; the emulator re-send is then pure REDUNDANCY that floods Pia
        # (verified: 335 reliable frames generated for a 17-fragment block; Pia delivered 327, the host
        # RFU faulted on the redundant torrent). On a real Switch-to-Switch LDN the host confirms in one
        # quick round-trip so the loop never accumulates; only our bridge's latency turns it into a flood.
        # Hence this is a BRIDGE adaptation, not a "more faithful" reading - default OFF, the live tool
        # turns it ON.
        self.trust_pia = trust_pia

    @property
    def done(self):
        return self.state == DONE

    def _chunk(self, index):
        return self.data[index * FRAG_BYTES:index * FRAG_BYTES + FRAG_BYTES]

    def _init_acked(self, ack):
        return ack is not None and ack.receiving and ack.count == self.count

    def tick(self, ack=None, peer_sending=False):
        """`peer_sending` = the PEER has a block of its own mid-transfer. While that is true we hold
        at INIT instead of streaming, so the two block transfers never overlap."""
        if self.state == DONE:
            return [0] * 7

        if self.state == INIT:
            # Holding for the peer's in-flight block: be SILENT, not chatty. Returning INIT here put a
            # non-idle slot (and a rolling-tag increment) on every single poll while the console was
            # streaming its own card - measured j54, seven INITs into its fragments 4..7, and it
            # stopped at 7 of 9. A native child has nothing to say until its own send starts. The
            # watchdog is not charged while we wait, so the hold costs the sender nothing.
            if peer_sending:
                return [0] * 7
            self._init_sends += 1
            # HandleBlockSend (CHILD) [link_rfu_2.c:1366-1382]: re-send SEND_BLOCK_INIT every frame UNTIL the
            # host echoes a SEND_BLOCK_INIT (its recvBlock is armed) -> STREAM. FAITHFUL: no give-up on the
            # live path (the host WILL echo; Pia delivers our INIT and its echo). Streaming before the host
            # armed its recvBlock drops fragments. watchdog_init is ONLY the offline (no-reflection) backstop.
            #   trust_pia: don't wait for the round-trip echo. Pia delivers our INIT RELIABLY and IN-ORDER
            #   (the host always processes it before the fragments that follow), so a watchdog_init-frame
            #   bound is enough to arm the host; waiting for the echo just costs a round-trip per block.
            # The watchdog applies WITH a reflection channel too. Waiting only on the echo assumes the
            # host keeps talking, and it does not: the console's parent transmits only when it has
            # something of its own to send, so once it is waiting for OUR block it goes completely quiet
            # (host_t=0/s) and the echo we are gating on can never arrive. Measured on hardware (j32,
            # trainer-card round): our card's SEND_BLOCK_INIT count=9 owner=0x81 re-sent ~40 times over
            # 14s, not one fragment ever streamed, host silent from its own last fragment onward, then
            # 'erreur de connexion'. Pia delivers the INIT reliably and IN ORDER ahead of the fragments,
            # so arming on the watchdog is safe; the faithful HOLD/re-send path below still recovers any
            # fragment the host missed. (This is the INIT gate only - fragment re-sending stays faithful,
            # which is what --trust-pia changes and what measurably crawled when it was on.)
            armed = self._init_acked(ack) or self._init_sends > self.watchdog_init
            # NEVER stream into the peer's own in-flight block. The host side of this codebase already
            # records the mirror of this bug: "Both sides sent their LinkPlayer blocks simultaneously
            # ... the native parent sends only the request at case 3, then waits at case 4 on
            # AreAllPlayersFinishedReceiving()", fixed by deferring its block until a valid child block
            # landed. The joiner had no such guard. Measured (j43 vs j45, same code, same barrier):
            # j43 was still re-sending INIT at ~3/s while the console streamed its trainer card, so the
            # transfers happened to serialise and it reached the trade room; j45's INIT armed on the
            # watchdog and streamed fragments 1..8 straight into the console's own 0..5, and it died.
            # Holding at INIT is safe - INIT re-sends are idempotent and the host re-arms on the same
            # (count, owner). (The peer_sending hold itself is handled above, silently.)
            if armed:
                self.state = STREAM
                self.index = 0
            else:
                return rfu.init_words(self.count, self.owner)
            # fall through to stream this same tick once INIT is acked

        if self.state == STREAM:
            # Pace consecutive fragments (STREAM_GAP). Idling here delays a fragment; it never skips
            # one, and never advances self.index.
            if self._stream_gap < self.STREAM_GAP and self.index > 0:
                self._stream_gap += 1
                return [0] * 7
            self._stream_gap = 0
            idx = self.index
            words = rfu.send_block_words(idx, self._chunk(idx))
            if idx >= self.count - 1:
                # trust_pia: FIRE-AND-FORGET. Pia has each fragment queued + will deliver/retransmit it, and
                # the trade FSM advances on RECEIVING the host's block (GetBlockReceivedStatus()==3
                # [trade.c:1454-1546]), NOT on our send completing - so we DONE here, skipping the redundant
                # HOLD re-send that floods the bridge. Faithful: HOLD the last fragment + re-send the missing.
                self.state = DONE if self.trust_pia else HOLD
                self._hold_sends = 0
            else:
                self.index += 1
            return words

        if self.state == HOLD:
            last = self.count - 1
            # Pace the repeats (HOLD_RESEND_GAP). Completion still comes only from the host's
            # reflection below, so idling here delays a re-send but never skips the confirmation.
            if self._hold_gap < self.HOLD_RESEND_GAP and self._hold_sends:
                self._hold_gap += 1
                if not (ack is not None and ack.last_index == last and ack.flags == all_received_mask(self.count)):
                    return [0] * 7
            self._hold_gap = 0
            self._hold_sends += 1
            full = all_received_mask(self.count)
            # SendLastBlock (CHILD) [link_rfu_2.c:1398-1416], FAITHFUL: re-send the LAST fragment every frame;
            # when the host acks the last index (ack.last_index == count-1, = gRecvCmds[mpId][0]==count-1):
            #   - it has ALL (receivedFlags == sAllBlocksReceived) -> DONE.
            #   - else HandleSendFailure -> re-send the still-missing fragments until it does.
            # CONFIRM-DRIVEN, no DONE-and-proceed watchdog on the live path: we KEEP sending until the host
            # confirms (Pia delivers our fragments + the host's ack, so it WILL confirm). The old unconditional
            # watchdog DONE'd after 6 and left the host one fragment short -> it never requested mail = the 3/3
            # DEADLOCK; the even-older missing-round-robin re-streamed forever -> flood. The real game confirms
            # or the link's own 10s timeout errors. watchdog_hold is ONLY the offline (no-reflection) backstop.
            if ack is not None:
                if ack.last_index == last:
                    if ack.flags == full:
                        self.state = DONE
                        return [0] * 7
                    missing = self._missing(ack)
                    if missing:
                        self._rr = (self._rr + 1) % len(missing)
                        idx = missing[self._rr]
                        return rfu.send_block_words(idx, self._chunk(idx))
            elif self._hold_sends > self.watchdog_hold:
                self.state = DONE          # offline (no host reflection) backstop only
                return [0] * 7
            return rfu.send_block_words(last, self._chunk(last))

        return [0] * 7

    def _missing(self, ack):
        if ack is None or ack.count != self.count:
            return []
        return [i for i in range(self.count) if not (ack.flags >> i) & 1]
