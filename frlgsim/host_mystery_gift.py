"""Leader-side FRLG Mystery Gift engine (the distributor's activity FSM).

Same integration contract as :class:`frlgsim.host_trade.HostTradeEngine` - the
RFU/Reliable/Pia stack below it is unchanged and already proven by the trade
host::

    engine.feed_child_slot(rfu_leader.child_cmd)   # each new child UNI row
    parent_words = engine.tick()                   # once per VBlank, into row 0

The activity above that stack is much smaller than a trade.  After the shared
LinkPlayer exchange the console has ``gReceivedRemoteLinkPlayers`` set, runs one
``SetLinkStandbyCallback`` barrier [union_room.c:2391] and creates its Mystery
Gift client [mystery_gift_menu.c:1231].  From that point the console executes
only the scripts we push, so the whole flow is
:class:`frlgsim.mg_server.MysteryGiftServer` driving block sends.

Block pacing is the one genuinely delicate part.  ``SEND_BLOCK_INIT`` is
*ignored* unless the receiver's slot is ``RECV_STATE_READY``
[link_rfu_2.c:1146], and the console only returns to READY when its
``MGL_ResetReceived`` consumes the previous block.  Nothing on the wire reports
that, and the sender's own flow control does not help: ``MGL_Send`` gates on
``MGL_HasReceived(sendPlayerId)``, which for the parent is slot 0, and
``Rfu_SetBlockReceivedFlag`` [link_rfu_2.c:1044] sets the parent's *own* flag
immediately - the four-VBlank ``numBlocksReceived`` countdown [link_rfu_2.c:1220]
applies only to blocks arriving *from a child*.  So a native parent paces blocks
roughly one frame apart and simply relies on the console keeping up.
:attr:`MysteryGiftTiming.inter_block_gap_frames` buys a much larger margin than
that, because losing this race does not corrupt data - it strands the console
waiting for a block that was dropped without an error.
"""

from collections import Counter, deque
from dataclasses import dataclass

from . import block, linkplayer, mg_link, rfu, trade
from .mg_server import SVR_MSG_CARD_SENT, MysteryGiftServer

MG_LINK_PLAYER = "MG_LINK_PLAYER"
MG_START = "MG_START"
MG_GIFT = "MG_GIFT"
MG_CLOSE = "MG_CLOSE"
MG_DONE = "MG_DONE"

HOST_NAME_PAD = linkplayer.HOST_NAME_PAD

# How often to report what a stalled bring-up is still waiting for. A console
# that goes quiet here gives no other clue, and its own RFU timeout fires within
# a few seconds, so the report has to be frequent enough to land twice first.
STATUS_REPORT_FRAMES = 120


@dataclass(frozen=True)
class MysteryGiftTiming:
    """Frame counts owned by the Mystery Gift leader."""

    # Keep a startup barrier echo visible across several child polls, exactly as
    # the trade leader does for the same LinkPlayer-exchange barrier.
    startup_standby_echo_frames: int = 4
    # Quiet child polls after the standby barrier before the first gift message.
    # The console is freeing the group list, running SetLinkStandbyCallback and
    # only then reaching MysteryGiftClient_Create [mystery_gift_menu.c:1231]. A
    # block that lands early is buffered harmlessly, but the *second* block of
    # that message would be dropped, so wait for the console to settle first.
    client_ready_idle_frames: int = 120
    # Idle VBlanks between the blocks of one MysteryGiftLink message. Measured
    # against the console model in tests/test_mystery_gift_flow.py: the console
    # may take up to this + 1 frames to consume a block with nothing dropped,
    # and up to this + 4 before the transfer fails outright (the block sender's
    # four SEND_BLOCK_INIT resends can still arm a console that was late). A
    # native parent gives the console far less - about one frame plus its own
    # three INIT resends - so this is generous by design, and cheap. Raise it
    # first if a live run stalls part-way through a message; that is the symptom
    # of losing this race.
    inter_block_gap_frames: int = 12
    # How many consecutive polls each SEND_PLAYER_IDS burst occupies.
    #
    # Native RfuPrepareSendBuffer leaves gSendCmd holding SEND_PLAYER_IDS until
    # the next link task overwrites it [Task_PlayerExchange case 1/101,
    # link_rfu_2.c:1832], so the console sees it across many polls. Emitting it
    # for a single VBlank loses the race: the console misses it, GetMultiplayerId
    # stays 0 (visible as owner 0x80 instead of 0x81 on its blocks) and
    # Task_PlayerExchange parks at case 2 waiting on gRfu.playerCount forever.
    player_ids_repeat_frames: int = 8
    # Re-emit READY_CLOSE_LINK on this cadence while closing.
    close_retry_frames: int = 60
    # Stay on the air after the console asks to close, so its Rfu_LinkClose and
    # post-gift save complete before the LDN network disappears.
    post_client_close_grace_frames: int = 5 * 60


DEFAULT_MYSTERY_GIFT_TIMING = MysteryGiftTiming()


class HostMysteryGiftEngine:
    """Transport-independent, single-child FRLG Mystery Gift distributor."""

    def __init__(self, card, ram_script, *, link_player=None, trust_pia=True,
                 timing=None, log=lambda *a: None):
        self.lp = link_player or linkplayer.LinkPlayer(
            name="EMU", version=linkplayer.VERSION_FIRE_RED)
        self.trust_pia = trust_pia
        self.timing = timing if timing is not None else DEFAULT_MYSTERY_GIFT_TIMING
        self.log = log
        self.info = getattr(log, "info", log)
        self.server = MysteryGiftServer(card, ram_script, log=log)

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
        self._blocks = deque()          # queued (bytes, label) SendBlock transfers
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
        self._recv_blocks = deque()     # completed child blocks awaiting a recv action
        self._message_label = None

        self._link_player_block = linkplayer.build_block(
            self.lp, name_pad=HOST_NAME_PAD).ljust(200, b"\x00")
        # The Switch is the RFU child. It creates Task_PlayerExchange directly
        # from RFUSTATE_CHILD_JOINED [link_rfu_2.c:459-473], so begin with the
        # parent half of that task immediately.  Do not borrow the native
        # distributor UI's 120-frame delay: that delay belongs to the *parent*
        # Task_SendMysteryGift, not this receiver.
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
        """Expose the id table long enough to observe the child's slot-one id.

        ``SEND_PLAYER_IDS`` is idempotent in ``RfuHandleReceiveCommand``.  In
        contrast, ``SEND_BLOCK_REQ`` begins a transfer, so only this harmless
        command may be repeated while we wait for an observable child state.
        """
        for _ in range(self.timing.player_ids_repeat_frames):
            self._queue_words(rfu.send_player_ids_words(), label)

    def _begin_link_player_exchange(self):
        """Run the parent-owned opening of ``Task_PlayerExchange`` once.

        The parent task sends player ids, then emits exactly one block request
        [link_rfu_2.c:1813-1854].  A repeated request can start a second child
        send after the first has completed, so the next observable transition is
        a *completed valid* child LinkPlayer block, not a retry timer.
        """
        self._queue_player_ids()
        self._expected = "link_player"
        self._link_player_requests += 1
        self._link_phase = "wait_child_block"
        self._queue_words(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE),
                          "BLOCK_REQ:link_player")
        self.trace.append(("link_player_request", self._link_player_requests))
        self.info("Sent player ids and one LinkPlayer block request; waiting for the console block.")

    # --- host application surface ------------------------------------------------------------
    @property
    def close_confirmed(self):
        """Whether the console has asked to close the RFU link."""
        return self._close_confirmed

    @property
    def established(self):
        return self.child_link_player is not None

    @property
    def result(self):
        """The server result message id once the flow finished, else ``None``."""
        return self.server.result

    def mark_disconnect_sent(self):
        if not self.disconnect_requested:
            raise RuntimeError("disconnect sent before the close-link handshake")
        self.done = True
        self._set_state(MG_DONE)

    # --- internals ---------------------------------------------------------------------------
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

    # --- the gift conversation ---------------------------------------------------------------
    def _begin_gift(self):
        self._set_state(MG_GIFT)
        self.info("Link established; starting the Mystery Gift conversation.")
        self._pump_server()

    def _pump_server(self):
        """Publish the server's next action onto the wire, repeatedly if needed."""
        while self.state == MG_GIFT:
            action = self.server.run()
            kind = action[0]
            if kind == "send":
                if self._blocks or self._sender is not None:
                    return                      # the previous message is still going out
                self._queue_message(*action[1:])
                return
            if kind == "recv":
                ident = action[1]
                if not self._receiver.active:
                    self._receiver.expect(ident)
                    self.trace.append(("expect", ident))
                if not self._drain_recv_blocks():
                    return
                continue                        # the message was already buffered
            if kind == "done":
                self._finish_gift(action[1])
                return

    def _queue_message(self, ident, payload, size):
        blocks = mg_link.build_message(ident, payload, size)
        self._message_label = f"ident{ident}"
        for index, data in enumerate(blocks):
            self._queue_block(data, f"{self._message_label}:{index}")
        self.trace.append(("send_message", ident, len(blocks)))
        # One line per logical MysteryGiftLink message is a useful live
        # milestone; per-fragment detail remains in ``trace``/JSONL.
        self.info(f"[mg] sending ident {ident} as {len(blocks)} block(s)")

    def _drain_recv_blocks(self):
        """Feed buffered child blocks to the receiver. True once a message completed."""
        while self._recv_blocks and self._receiver.active:
            payload = self._receiver.feed_block(self._recv_blocks.popleft())
            if payload is None:
                continue
            ident = self._receiver.ident
            self.trace.append(("recv_message", ident, len(payload)))
            self.info(f"[mg] received ident {ident} ({len(payload)} bytes)")
            self.server.on_received(ident, payload)
            return True
        return False

    def _finish_gift(self, message_id):
        self.gift_sent = self.server.result == SVR_MSG_CARD_SENT
        self.trace.append(("gift_complete", message_id))
        self._begin_close()

    def _begin_close(self):
        """Answer the console's post-gift Rfu_SetCloseLinkCallback [mystery_gift_menu.c:1248].

        Both sides must expose READY_CLOSE_LINK before ``IsLinkRfuTaskFinished``
        releases the console into its save, so ours goes out immediately rather
        than after the first retry interval.
        """
        self._set_state(MG_CLOSE)
        self._queue_close_words()
        self._close_retry_wait = self.timing.close_retry_frames

    def _queue_close_words(self):
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")

    # --- child traffic ------------------------------------------------------------------------
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
        # First sighting of each child opcode. Without this a stall is invisible:
        # the console goes quiet and there is nothing to say whether it never
        # answered, answered something unexpected, or stopped part-way.
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
            # The owner byte is mpId | 0x80, and mpId comes from our
            # SEND_PLAYER_IDS via LoadLinkPlayerIds [link_rfu_2.c:1058]. A
            # console still reporting 0 has not processed it and is parked in
            # Task_PlayerExchange case 2.
            mp_id = (rec.get("owner_raw") or 0) & 0x7F
            if mp_id != self._child_mp_id:
                self._child_mp_id = mp_id
                self.info(f"Console reports multiplayer id {mp_id}"
                          + ("." if mp_id == 1 else
                             " - repeating only the id table, not the block request."))
            if self.state == MG_LINK_PLAYER and mp_id != 1:
                # This repeat is harmless: SEND_PLAYER_IDS only updates the
                # child's player count/id.  Do not repeat SEND_BLOCK_REQ here;
                # it can start a second transfer after the first completes.
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
                # SEND_BLOCK_REQ makes the child ship gBlockSendBuffer verbatim
                # [link_rfu_2.c:232], but LocalLinkPlayerToBlock only fills that
                # buffer in Task_PlayerExchange case 0 [link_rfu_2.c:1828]. Ask
                # too early and it sends whatever was left there - not an error
                # to abort on, just a request that arrived before the console
                # was ready.
                self._reject_link_player("invalid GameFreak magic", data)
                return
            self.child_link_player = parsed
            self._expected = None
            self._link_player_seen = True
            self._link_phase = "send_host_block"
            self.trace.append(("link_player_child_block_valid", count))
            # A valid child block proves that Task_PlayerExchange case 0 has
            # already filled the child's gBlockSendBuffer.  This is the safe
            # signal to send ours; an INIT alone can predate case 0's reset.
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
        # Mirror the barrier for several polls: native gSendCmd stays current
        # until the next link task overwrites it, and a one-VBlank pulse can be
        # missed entirely by the console's resend loop.
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.exit_standby_words(count), f"STANDBY:{count}")
        self._exit_count = max(self._exit_count, count + 1)
        if self.state == MG_LINK_PLAYER and self._link_player_seen:
            if self._host_link_player_complete:
                self._complete_link_player_barrier(count)
            else:
                # The child may stop emitting this semantic event after it sees
                # our echo, so retain it until our last fragment has left.  This
                # is a latch, not a synthetic standby/retry.
                self._pending_standby_count = count
                self.trace.append(("link_player_standby_latched", count,
                                   self._link_phase))
        elif self.state == MG_LINK_PLAYER:
            # Mirror it for the child, but do not treat a premature standby as
            # proof that our block reached Task_PlayerExchange case 4.
            self.trace.append(("link_player_standby_early", count, self._link_phase))

    def _complete_link_player_barrier(self, count):
        """Enter the post-exchange standby exactly once, including a latched event."""
        if self.state != MG_LINK_PLAYER:
            return
        # union_room.c:2391 runs exactly one SetLinkStandbyCallback round
        # between gReceivedRemoteLinkPlayers and the Mystery Gift client.
        self._pending_standby_count = None
        self._set_state(MG_START)
        self._standby_seen = True
        self._idle_run = 0
        self.trace.append(("link_player_barrier_complete", count))

    def _on_child_close(self, count):
        self._exit_count = max(self._exit_count, count)
        if self.state in (MG_LINK_PLAYER, MG_START, MG_GIFT):
            # The console gave up or finished ahead of us; follow it out.
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

    # --- per-VBlank output --------------------------------------------------------------------
    def tick(self):
        """Advance one VBlank and return the parent's seven-word gSendCmd."""
        self._parent_polls += 1
        if self.state in (MG_LINK_PLAYER, MG_START):
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
            self._sender = block.BlockSender(data, owner=0, trust_pia=self.trust_pia)
            self.trace.append(("send_block", label, len(data)))

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
        """Record a stale/malformed first response without restarting its send."""
        self.rejected_link_players += 1
        self.trace.append(("link_player_rejected", reason))
        self._expected = None
        self._link_phase = "invalid_child_block"
        self.info(f"Console's LinkPlayer block was not usable ({reason}); not re-requesting "
                  f"because a duplicate BLOCK_REQ can restart a completed send. "
                  f"First bytes: {bytes(data[:16]).hex()}")
        self._rx = block.RecvBlock()

    def _report_status(self, rfu_leader=None):
        """Say what the bring-up is still waiting on.

        The console's half of Task_PlayerExchange needs three things: our
        player ids (visible as its multiplayer id), our LinkPlayer block, and
        its own block echoed back in row 1 of our UNI table.  RFULeader queues
        every normalized child command and drains one echo per parent poll, so
        the frame counts and opcode totals show whether that queue is still
        making progress without printing every VBlank.
        """
        ops = ", ".join(
            f"{rfu.RFUCMD_NAMES.get(op, hex(op))}x{count}"
            for op, count in sorted(self._child_op_counts.items(),
                                    key=lambda kv: -kv[1])) or "none"
        self.info(
            f"Waiting in {self.state}: our block sent {self._our_blocks_sent}x, "
            f"console block {'received' if self._link_player_seen else 'NOT received'}, "
            f"console mpId {self._child_mp_id}, "
            f"child frames {self._child_frames} ({self._child_idles} idle) "
            f"vs parent polls {self._parent_polls}, "
            f"opcodes seen: {ops}")

    def _record_link_player_outbound(self, words):
        """Keep an exact, low-noise record of the host LinkPlayer wire order."""
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
