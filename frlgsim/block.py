"""RFU block transfer: the ACK-gated CHILD send sub-FSM and the receive reassembler [link_rfu_2.c:1333-1421,
1015-1042, 1125-1231]. Receive is idempotent and order-independent; send re-sends every stage until the host's
reflection (IN owner=0x81, fed into peer 1) acks it."""

import math

from . import rfu

FRAG_BYTES = 12


def frag_count(nbytes):
    return max(1, math.ceil(nbytes / FRAG_BYTES))


def all_received_mask(count):
    return (1 << count) - 1


class RecvBlock:
    """Fragment writes are idempotent; a same-size INIT resend mid-block keeps accumulated fragments."""

    def __init__(self):
        self.count = 0
        self.owner = None
        self.flags = 0
        self.buf = bytearray()
        self.receiving = False
        self.done = False
        self.last_index = -1
        self.epochs = 0

    def on_init(self, count, owner):
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
        d = self.data()
        self.receiving = False
        self.done = False
        self.flags = 0
        return d


class BlockReceiver:
    def __init__(self, max_peers=5):
        self.peers = [RecvBlock() for _ in range(max_peers)]
        self.last_req = None
        self.last_cmd = {}

    def feed_frame(self, unwrapped):
        """Returns (completed, reqs): completed = [(mpId, count, data)] for blocks finished on this frame,
        reqs = [reqtype] for SEND_BLOCK_REQ slots (the host pulling a block)."""
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


INIT, STREAM, HOLD, DONE = "init", "stream", "hold", "done"


class BlockSender:
    """tick(ack) -> the 7-int gSendCmd for this VBlank. `ack` is the peer-1 RecvBlock (the host's reflection of
    our block); None runs purely on the resend watchdog (offline)."""

    # HOLD repeats until the host confirms; idle between re-sends so a parent that is already behind is not buried.
    HOLD_RESEND_GAP = 6
    # 0 = unpaced. Shared with the HOST and Mystery Gift senders, whose offline tests assert a fragment per
    # tick; only the JOINER sets it.
    STREAM_GAP = 0

    def __init__(self, data, owner=1, watchdog_init=4, watchdog_hold=6, trust_pia=False,
                 stream_gap=None, stream_repeat=1):
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
        # The console silently drops ~40% of our datagrams and does not retry; an incomplete LinkPlayerBlock
        # fails both magic strcmps -> CB2_LinkError [decomp:src/link.c:1629]. Repeating each fragment is the
        # bounded middle between send-once and re-send-until-confirmed.
        self.stream_repeat = max(1, int(stream_repeat))
        self._frag_sends = 0            # repeats emitted for the current fragment
        self._rr = 0                    # round-robin cursor for re-queueing missing frags
        self.watchdog_init = watchdog_init
        self.watchdog_hold = watchdog_hold
        # trust_pia: send each fragment once and rely on Pia's reliable layer; the decomp re-send loop
        # (faithful to the Switch, built for the lossy raw RFU) floods the high-RTT bridge. Default OFF.
        self.trust_pia = trust_pia

    @property
    def done(self):
        return self.state == DONE

    def _chunk(self, index):
        return self.data[index * FRAG_BYTES:index * FRAG_BYTES + FRAG_BYTES]

    def _init_acked(self, ack):
        return ack is not None and ack.receiving and ack.count == self.count

    def tick(self, ack=None, peer_sending=False):
        """peer_sending: hold at INIT while the peer's own block is mid-transfer, so transfers never overlap."""
        if self.state == DONE:
            return [0] * 7

        if self.state == INIT:
            # Hold SILENTLY: an INIT on every poll while the console streams its own block kills it.
            if peer_sending:
                return [0] * 7
            self._init_sends += 1
            # HandleBlockSend (CHILD) [link_rfu_2.c:1366-1382]: re-send SEND_BLOCK_INIT until the host echoes it.
            # The watchdog applies live too: the parent transmits only when it has something to send, so once
            # it waits for OUR block the echo may never come. Pia delivers the INIT in order ahead of the
            # fragments, so arming on the watchdog is safe.
            armed = self._init_acked(ack) or self._init_sends > self.watchdog_init
            if armed:
                self.state = STREAM
                self.index = 0
            else:
                return rfu.init_words(self.count, self.owner)

        if self.state == STREAM:
            if self._stream_gap < self.STREAM_GAP and self.index > 0:
                self._stream_gap += 1
                return [0] * 7
            self._stream_gap = 0
            idx = self.index
            words = rfu.send_block_words(idx, self._chunk(idx))
            self._frag_sends += 1
            if self._frag_sends < self.stream_repeat:
                return words
            self._frag_sends = 0
            if idx >= self.count - 1:
                # trust_pia: DONE here (the FSM advances on RECEIVING the host's block [trade.c:1454-1546]);
                # faithful: HOLD the last fragment and re-send the missing.
                self.state = DONE if self.trust_pia else HOLD
                self._hold_sends = 0
            else:
                self.index += 1
            return words

        if self.state == HOLD:
            last = self.count - 1
            if self._hold_gap < self.HOLD_RESEND_GAP and self._hold_sends:
                self._hold_gap += 1
                if not (ack is not None and ack.last_index == last and ack.flags == all_received_mask(self.count)):
                    return [0] * 7
            self._hold_gap = 0
            self._hold_sends += 1
            full = all_received_mask(self.count)
            # SendLastBlock (CHILD) [link_rfu_2.c:1398-1416]: re-send the last fragment; once the host acks its
            # index, DONE if it has all, else re-send the missing (HandleSendFailure). No give-up on the live
            # path: an early DONE leaves the host a fragment short -> it never requests mail (3/3 deadlock).
            # watchdog_hold is the offline backstop only.
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
