"""Leader-side FRLG Mystery Gift engine; same feed_child_slot()/tick() contract as HostTradeEngine.
The console ignores SEND_BLOCK_INIT unless its slot is RECV_STATE_READY [decomp:src/link_rfu_2.c:1146]
and nothing on the wire reports that, so blocks must be paced (inter_block_gap_frames)."""

from collections import Counter, deque
from dataclasses import dataclass

from . import block, linkplayer, mg_link, mystery_gift, rfu, trade
from .mg_server import SVR_MSG_CARD_SENT, SVR_MSG_STAMP_SENT, MysteryGiftServer

MG_LINK_PLAYER = "MG_LINK_PLAYER"
MG_START = "MG_START"
MG_GIFT = "MG_GIFT"
MG_CLOSE = "MG_CLOSE"
MG_DONE = "MG_DONE"

HOST_NAME_PAD = linkplayer.HOST_NAME_PAD

# The console's own RFU timeout fires within a few seconds of it going quiet; report twice before that.
STATUS_REPORT_FRAMES = 120


@dataclass(frozen=True)
class MysteryGiftTiming:
    startup_standby_echo_frames: int = 4
    # The console reaches MysteryGiftClient_Create [decomp:src/mystery_gift_menu.c:1231] only after its
    # standby round; the second block of a message sent before then is dropped.
    client_ready_idle_frames: int = 20
    # The console silently drops a block that arrives before it consumed the previous one; raise this
    # first if a live run stalls part-way through a message.
    inter_block_gap_frames: int = 36
    # The console misses a single-VBlank SEND_PLAYER_IDS and then parks in Task_PlayerExchange case 2
    # with multiplayer id 0 [decomp:src/link_rfu_2.c:1832].
    player_ids_repeat_frames: int = 8
    block_repeat: int = 2
    # The MG client never reflects gift blocks, so a lost RAM-script fragment cannot be identified
    # for resend; redundancy on first send is the only lever.
    ram_script_block_repeat: int = 3
    close_retry_frames: int = 60
    # The console's Rfu_LinkClose and post-gift save must finish before the LDN network disappears.
    post_client_close_grace_frames: int = 5 * 60


DEFAULT_MYSTERY_GIFT_TIMING = MysteryGiftTiming()


class HostMysteryGiftEngine:
    def __init__(self, card=None, ram_script=None, *, distribution=None,
                 link_player=None, trust_pia=True, timing=None,
                 log=lambda *a: None):
        self.lp = link_player or linkplayer.LinkPlayer(
            name="EMU", version=linkplayer.VERSION_FIRE_RED)
        self.trust_pia = trust_pia
        self.timing = timing if timing is not None else DEFAULT_MYSTERY_GIFT_TIMING
        self.log = log
        self.info = getattr(log, "info", log)
        if distribution is not None:
            if card is not None or ram_script is not None:
                raise ValueError("pass either distribution or card/ram_script")
            card, ram_script = distribution.card, distribution.ram_script
            server_extras = {
                "stamp": distribution.stamp,
                "activation_script": distribution.activation_script,
                "install_activation_script": distribution.install_activation_script,
            }
        else:
            if card is None or ram_script is None:
                raise ValueError("card and ram_script are required")
            server_extras = {}
        self.server = MysteryGiftServer(
            card, ram_script, log=log, **server_extras)

        self.state = MG_LINK_PLAYER
        self.state_history = [self.state]
        self.child_link_player = None
        self.done = False
        self.disconnect_requested = False
        self.gift_sent = False
        self.rejected_link_players = 0
        self.trace = []

        self._rx = block.RecvBlock()
        self._words = deque()
        self._blocks = deque()
        self._sender = None
        self._gap = 0
        self._expected = None
        self._link_player_seen = False
        self._standby_seen = False
        self._pending_standby_count = None
        self._idle_run = 0
        self._exit_count = 0
        self._close_confirmed = False
        self._close_grace_wait = None
        self._close_retry_wait = None

        self._receiver = mg_link.MysteryGiftLinkReceiver()
        self._recv_blocks = deque()
        self._message_label = None

        self._link_player_block = linkplayer.build_block(
            self.lp, name_pad=HOST_NAME_PAD).ljust(200, b"\x00")
        # The child console creates Task_PlayerExchange directly from RFUSTATE_CHILD_JOINED
        # [decomp:src/link_rfu_2.c:459]; do not add the native distributor's 120-frame delay.
        self._link_phase = "send_player_ids"
        self._link_player_requests = 0
        self._host_link_player_queued = False
        self._host_link_player_complete = False
        self._link_player_outbound = []
        self._child_ops = set()
        self._child_mp_id = None
        self._our_blocks_sent = 0
        self._child_frames = 0
        self._child_idles = 0
        self._child_op_counts = Counter()
        self._parent_polls = 0
        self._status_countdown = STATUS_REPORT_FRAMES
        self._begin_link_player_exchange()

    def _queue_player_ids(self, label="SEND_PLAYER_IDS"):
        """SEND_PLAYER_IDS is idempotent on the console; SEND_BLOCK_REQ is not, so only this may be repeated."""
        for _ in range(self.timing.player_ids_repeat_frames):
            self._queue_words(rfu.send_player_ids_words(), label)

    def _begin_link_player_exchange(self):
        """Exactly one SEND_BLOCK_REQ [decomp:src/link_rfu_2.c:1813]; a repeat can start a second child send."""
        self._queue_player_ids()
        self._expected = "link_player"
        self._link_player_requests += 1
        self._link_phase = "wait_child_block"
        self._queue_words(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE),
                          "BLOCK_REQ:link_player")
        self.trace.append(("link_player_request", self._link_player_requests))
        self.info("Sent player ids and one LinkPlayer block request; waiting for the console block.")

    @property
    def close_confirmed(self):
        return self._close_confirmed

    @property
    def established(self):
        return self.child_link_player is not None

    @property
    def result(self):
        return self.server.result

    def mark_disconnect_sent(self):
        if not self.disconnect_requested:
            raise RuntimeError("disconnect sent before the close-link handshake")
        self.done = True
        self._set_state(MG_DONE)

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_history.append(state)
            self.trace.append(("state", state))
            self.log(f"host mystery gift: -> {state}")

    def _queue_words(self, words, label):
        self._words.append(list(words))
        self.trace.append(("queue", label))

    def _queue_block(self, data, label):
        self._blocks.append((bytes(data), label))
        self.trace.append(("queue_block", label, len(data)))

    def _begin_gift(self):
        self._set_state(MG_GIFT)
        self.info("Link established; starting the Mystery Gift conversation.")
        self._pump_server()

    def _pump_server(self):
        while self.state == MG_GIFT:
            action = self.server.run()
            kind = action[0]
            if kind == "send":
                if self._blocks or self._sender is not None:
                    return
                self._queue_message(*action[1:])
                return
            if kind == "recv":
                ident = action[1]
                if not self._receiver.active:
                    self._receiver.expect(ident)
                    self.trace.append(("expect", ident))
                if not self._drain_recv_blocks():
                    return
                continue
            if kind == "done":
                self._finish_gift(action[1])
                return

    def _queue_message(self, ident, payload, size):
        blocks = mg_link.build_message(ident, payload, size)
        self._message_label = f"ident{ident}"
        for index, data in enumerate(blocks):
            self._queue_block(data, f"{self._message_label}:{index}")
        self.trace.append(("send_message", ident, len(blocks)))
        self.info(f"[mg] sending ident {ident} as {len(blocks)} block(s)")

    def _drain_recv_blocks(self):
        while self._recv_blocks and self._receiver.active:
            block = self._recv_blocks.popleft()
            try:
                payload = self._receiver.feed_block(block)
            except mg_link.MysteryGiftLinkError as exc:
                # A console retransmit of the previous message surfaces here as a stale header; drop it
                # and re-arm the same ident rather than raising (the console re-sends what we await).
                want = self._receiver.expected_ident
                self.trace.append(("recv_resync", want, str(exc)))
                self.info(f"[mg] ignoring a stale/duplicate child block while awaiting ident "
                          f"{want} ({exc}); re-arming.")
                self._receiver.expect(want)
                continue
            if payload is None:
                continue
            ident = self._receiver.ident
            self.trace.append(("recv_message", ident, len(payload)))
            self.info(f"[mg] received ident {ident} ({len(payload)} bytes)")
            self.server.on_received(ident, payload)
            return True
        return False

    def _finish_gift(self, message_id):
        self.gift_sent = self.server.result in (SVR_MSG_CARD_SENT, SVR_MSG_STAMP_SENT)
        self.trace.append(("gift_complete", message_id))
        self._begin_close()

    def _begin_close(self):
        """Both sides must expose READY_CLOSE_LINK before IsLinkRfuTaskFinished releases the console
        into its save [decomp:src/mystery_gift_menu.c:1248], so ours goes out immediately."""
        self._set_state(MG_CLOSE)
        self._queue_close_words()
        self._close_retry_wait = self.timing.close_retry_frames

    def _queue_close_words(self):
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")

    def feed_child_slot(self, slot):
        """Consume one child gSendCmd row (14 bytes, rolling tag permitted)."""
        self._child_frames += 1
        if bytes(slot) == rfu.idle_slot():
            self._child_idles += 1
            self._on_child_idle()
            return
        self._idle_run = 0
        rec = rfu.parse_slot(slot)
        if rec is None:
            return
        op = rec["op"]
        self._child_op_counts[op] += 1
        if op not in self._child_ops:
            self._child_ops.add(op)
            detail = ""
            if op == rfu.SEND_BLOCK_INIT:
                detail = f" count={rec.get('count')} owner=0x{rec.get('owner_raw', 0):02x}"
            elif op in (rfu.READY_EXIT_STANDBY, rfu.READY_CLOSE_LINK):
                detail = f" count={rec.get('count')}"
            self.info(f"Console sent its first {rec['name']}{detail} "
                      f"(host state {self.state}).")
        if op == rfu.SEND_BLOCK_INIT:
            # owner byte = mpId | 0x80; mpId 0 means the console has not processed SEND_PLAYER_IDS
            # [decomp:src/link_rfu_2.c:1058] and is parked in Task_PlayerExchange case 2.
            mp_id = (rec.get("owner_raw") or 0) & 0x7F
            if mp_id != self._child_mp_id:
                self._child_mp_id = mp_id
                self.info(f"Console reports multiplayer id {mp_id}"
                          + ("." if mp_id == 1 else
                             " - repeating only the id table, not the block request."))
            if self.state == MG_LINK_PLAYER and mp_id != 1:
                # Do not repeat SEND_BLOCK_REQ here; it can start a second transfer after the first completes.
                self._queue_player_ids("SEND_PLAYER_IDS:repair")
            self._rx.on_init(rec["count"], rec.get("owner_raw"))
        elif op == rfu.SEND_BLOCK:
            was_done = self._rx.done
            self._rx.on_block(rec["index"], rec["frag"])
            if self._rx.done and not was_done:
                data, count = self._rx.data(), self._rx.count
                self._rx.consume()
                self._on_child_block(count, data)
        elif op == rfu.READY_EXIT_STANDBY:
            self._on_child_standby(rec.get("count", 0))
        elif op == rfu.READY_CLOSE_LINK:
            self._on_child_close(rec.get("count", 0))

    def _on_child_idle(self):
        self._idle_run += 1
        if (self.state == MG_START and self._standby_seen
                and self._idle_run >= self.timing.client_ready_idle_frames):
            self._begin_gift()

    def _on_child_block(self, count, data):
        self.trace.append(("child_block", self._expected, count))
        if self.state == MG_LINK_PLAYER and self._expected == "link_player":
            if count != trade.COUNT_PARTY:
                self._reject_link_player(f"block count {count}, expected "
                                         f"{trade.COUNT_PARTY}", data)
                return
            parsed, ok = linkplayer.parse_block(data)
            if not ok:
                # The child ships gBlockSendBuffer verbatim [decomp:src/link_rfu_2.c:232]; asked before
                # Task_PlayerExchange case 0 fills it, it sends stale bytes. Not fatal.
                self._reject_link_player("invalid GameFreak magic", data)
                return
            self.child_link_player = parsed
            self._expected = None
            self._link_player_seen = True
            self._link_phase = "send_host_block"
            self.trace.append(("link_player_child_block_valid", count))
            # Only a valid child block proves case 0 ran; an INIT alone can predate its buffer reset.
            self._host_link_player_queued = True
            self._queue_block(self._link_player_block, "host:link_player")
            self.trace.append(("link_player_host_block_queued", count))
            self.info(f"Console identified as {parsed.name!r}; its LinkPlayer block is complete. "
                      "Sending the host block now.")
            return
        if self.state == MG_GIFT:
            self._recv_blocks.append(data)
            if self._drain_recv_blocks():
                self._pump_server()
            return
        self.trace.append(("unexpected_child_block", count))

    def _on_child_standby(self, count):
        # A one-VBlank echo can be missed entirely by the console's resend loop.
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.exit_standby_words(count), f"STANDBY:{count}")
        self._exit_count = max(self._exit_count, count + 1)
        if self.state == MG_LINK_PLAYER and self._link_player_seen:
            if self._host_link_player_complete:
                self._complete_link_player_barrier(count)
            else:
                # Latch: the child may stop emitting standby once it sees our echo.
                self._pending_standby_count = count
                self.trace.append(("link_player_standby_latched", count,
                                   self._link_phase))
        elif self.state == MG_LINK_PLAYER:
            # A premature standby is not proof that our block reached Task_PlayerExchange case 4.
            self.trace.append(("link_player_standby_early", count, self._link_phase))

    def _complete_link_player_barrier(self, count):
        if self.state != MG_LINK_PLAYER:
            return
        # Exactly one SetLinkStandbyCallback round precedes the Mystery Gift client [decomp:src/union_room.c:2391].
        self._pending_standby_count = None
        self._set_state(MG_START)
        self._standby_seen = True
        self._idle_run = 0
        self.trace.append(("link_player_barrier_complete", count))

    def _on_child_close(self, count):
        self._exit_count = max(self._exit_count, count)
        if self.state in (MG_LINK_PLAYER, MG_START, MG_GIFT):
            self.trace.append(("child_close_early", self.state))
            self._begin_close()
        if self.state != MG_CLOSE:
            return
        if not self._close_confirmed:
            self._close_confirmed = True
            self._close_grace_wait = self.timing.post_client_close_grace_frames
            self.trace.append(("child_close_confirmed", count))
            self.info("Console finished the gift and asked to close the link; "
                      "holding the network open while it saves.")

    def tick(self):
        """One VBlank; returns the parent's seven-word gSendCmd row."""
        self._parent_polls += 1
        if self.state in (MG_LINK_PLAYER, MG_START, MG_GIFT):
            self._status_countdown -= 1
            if self._status_countdown <= 0:
                self._status_countdown = STATUS_REPORT_FRAMES
                self._report_status()
        if self.state == MG_CLOSE and not self.disconnect_requested:
            self._tick_close()

        if self._words:
            return self._words.popleft()

        if self._gap > 0:
            self._gap -= 1
            return [0] * 7

        if self._sender is None and self._blocks:
            data, label = self._blocks.popleft()
            repeat = self.timing.block_repeat
            if label.startswith(f"ident{mystery_gift.MG_LINKID_RAM_SCRIPT}:"):
                repeat = max(repeat, self.timing.ram_script_block_repeat)
            self._sender = block.BlockSender(data, owner=0, trust_pia=self.trust_pia,
                                             stream_repeat=repeat)
            self.trace.append(("send_block", label, len(data), repeat))

        if self._sender is not None:
            words = self._sender.tick(None)
            if self.state == MG_LINK_PLAYER and self._host_link_player_queued:
                self._record_link_player_outbound(words)
            if self._sender.done:
                if self.state == MG_LINK_PLAYER:
                    self._our_blocks_sent += 1
                    self._host_link_player_complete = True
                    self._link_phase = "wait_standby"
                    self.trace.append(("link_player_host_block_complete",
                                       tuple(self._link_player_outbound)))
                    self.info("Host LinkPlayer block complete: "
                              f"{self._format_link_player_outbound()}.")
                    if self._pending_standby_count is not None:
                        self._complete_link_player_barrier(
                            self._pending_standby_count)
                self._sender = None
                self._gap = self.timing.inter_block_gap_frames
                if not self._blocks and self.state == MG_GIFT:
                    self.server.on_sent()
                    self._pump_server()
            return words
        return [0] * 7

    def _reject_link_player(self, reason, data):
        self.rejected_link_players += 1
        self.trace.append(("link_player_rejected", reason))
        self._expected = None
        self._link_phase = "invalid_child_block"
        self.info(f"Console's LinkPlayer block was not usable ({reason}); not re-requesting "
                  f"because a duplicate BLOCK_REQ can restart a completed send. "
                  f"First bytes: {bytes(data[:16]).hex()}")
        self._rx = block.RecvBlock()

    def _report_status(self, rfu_leader=None):
        ops = ", ".join(
            f"{rfu.RFUCMD_NAMES.get(op, hex(op))}x{count}"
            for op, count in sorted(self._child_op_counts.items(),
                                    key=lambda kv: -kv[1])) or "none"
        self.info(
            f"Waiting in {self.state}: our block sent {self._our_blocks_sent}x, "
            f"console block {'received' if self._link_player_seen else 'NOT received'}, "
            f"console mpId {self._child_mp_id}, "
            f"child frames {self._child_frames} ({self._child_idles} idle, "
            f"current idle run {self._idle_run}/"
            f"{self.timing.client_ready_idle_frames}) "
            f"vs parent polls {self._parent_polls}, "
            f"opcodes seen: {ops}" + self._gift_status_detail())

    def _gift_status_detail(self):
        if self.state != MG_GIFT:
            return ""
        pending = len(self._blocks) + (1 if self._sender is not None else 0)
        action = self.server.action
        expecting = action[1] if action is not None and action[0] == "recv" else None
        return (f"; gift: last message {self._message_label or 'none'}, "
                f"{pending} block(s) still outbound, "
                f"expecting ident {expecting if expecting is not None else 'nothing (sending)'}, "
                f"{len(self._recv_blocks)} child block(s) buffered")

    def _record_link_player_outbound(self, words):
        rec = rfu.parse_slot(rfu.serialize(words))
        if rec is None:
            return
        if rec["op"] == rfu.SEND_BLOCK_INIT:
            item = ("INIT", rec["count"], rec.get("owner_raw"))
        elif rec["op"] == rfu.SEND_BLOCK:
            item = ("BLOCK", rec["index"])
        else:
            return
        self._link_player_outbound.append(item)
        self.trace.append(("link_player_tx",) + item)

    def _format_link_player_outbound(self):
        inits = sum(1 for item in self._link_player_outbound if item[0] == "INIT")
        fragments = [item[1] for item in self._link_player_outbound if item[0] == "BLOCK"]
        if fragments == list(range(trade.COUNT_PARTY)):
            fragment_text = f"fragments 0-{trade.COUNT_PARTY - 1}"
        else:
            fragment_text = f"fragment indexes {fragments}"
        return f"{inits} INIT frame(s), {fragment_text}"

    def _tick_close(self):
        if self._close_grace_wait is not None:
            self._close_grace_wait -= 1
            if self._close_grace_wait <= 0:
                self._close_grace_wait = None
                self.disconnect_requested = True
                self.trace.append(("close_grace_complete",))
                self.info("Post-gift grace period complete; closing the RFU session.")
                return
        self._close_retry_wait -= 1
        if self._close_retry_wait <= 0:
            self._queue_close_words()
            self._close_retry_wait = self.timing.close_retry_frames
