#!/usr/bin/env python3
"""Full-stack validation of the Mystery Gift distributor over a lossy radio.

tests/test_mystery_gift_flow.py drives :class:`ConsoleClientModel` against the
gift engine in perfect lockstep - one parent row in, one child row out, nothing
in between.  That proves the activity, but it says nothing about the two layers
the live host actually runs on::

    HostReliableSession -> RFULeader -> HostMysteryGiftEngine

This test reuses that same console model and wraps it in the Pia Reliable +
emulator C/A/K/T/D + RFU NI machinery taken from
:class:`tests.test_host_end_to_end.ScriptedFireRedChild`.  Between the two peers
sits a radio that drops, duplicates, reorders and delays Reliable DATA in both
directions, throughout the run rather than only during the handshake.  The
model shares the production MysteryGiftLink codec, so the ID16/ID17 handoff also
has a separate native-shaped byte fixture below; the full-stack model alone is
not independent conformance evidence for that codec.

The property under test is narrow and load-bearing.  ``SEND_BLOCK_INIT`` is
ignored unless the receiver's slot is ``RECV_STATE_READY`` [link_rfu_2.c:1146]
and nothing on the wire acknowledges a block, so the whole transfer rests on the
sender's pacing (:attr:`MysteryGiftTiming.inter_block_gap_frames`).  A radio that
stalls one fragment for a retransmit and then delivers a burst is exactly the
thing that could eat that margin.  It must not: Reliable has to hide loss,
duplication and reordering from RFU so the console still sees one clean,
in-order, deduplicated row stream and never drops an INIT.

Still an offline protocol model: Pia encryption/addressing, kernel Wi-Fi timing
and Nintendo's exact implementation quirks need a live Switch.

Run standalone (no pytest needed):   python tests/test_mystery_gift_end_to_end.py
"""

from collections import defaultdict, deque
from dataclasses import dataclass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    beacon, gbaframe, host_mystery_gift, linkplayer, mg_script, mg_server, ni,
    mg_link, reliable, rfu, wonder_card,
)
from frlgsim import mystery_gift as mg  # noqa: E402
from frlgsim.host_session import HostSession  # noqa: E402
from frlgsim.rfu_leader import DISCONNECTED  # noqa: E402
from tests.test_mystery_gift_flow import ConsoleClientModel  # noqa: E402

# The console model's identity, so both halves of the link agree.  Its
# LinkPlayer is named "ASH" and its MysteryGift_LoadLinkGameData image carries
# trainer id 0x47ED8822 [mystery_gift.c:337], whose public half is 0x8822.
CHILD_NAME = "ASH"
CHILD_TRAINER_ID = 0x8822
CHILD_VERSION_LOW = 4                       # gGameVersion: 4 = FireRed [include/constants/game_version.h]
HOST_NAME = "EMU"


def _native_crc16(data):
    """A local transcription of ``CalcCRC16WithTable``'s reflected algorithm.

    This intentionally does not call :func:`mystery_gift.crc16`: the point of
    the fixture below is to check the production ``mg_link`` sender against a
    separately written, source-shaped representation of
    ``mystery_gift_link.c``.
    """
    crc = 0x1121
    for byte in bytes(data):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return (~crc) & 0xFFFF


def _native_mgl_blocks(ident, payload, size):
    """Direct model of ``MysteryGiftLink_InitSend``/``MGL_Send``.

    It is deliberately small and test-local: header then payload chunks, with
    native ``size == 0`` expansion and a CRC over the padded declared buffer.
    Do not replace it with ``mg_link.build_message``; it is the independent
    stage-5 oracle for the first CLIENT_SCRIPT/GAME_DATA transaction and the
    later full-buffer messages.
    """
    if size == 0:
        size = 0x400  # MG_LINK_BUFFER_SIZE in mystery_gift_link.c:55-58.
    payload = bytes(payload)
    assert 0 < size <= 0x400 and len(payload) <= size
    buf = payload.ljust(size, b"\x00")
    header = (int(ident).to_bytes(2, "little")
              + _native_crc16(buf).to_bytes(2, "little")
              + size.to_bytes(2, "little"))
    chunks = [buf[offset:offset + 252] for offset in range(0, size, 252)]
    return [header] + chunks


@dataclass
class _AirPacket:
    due: int
    order: int
    direction: str
    wire: bytes


class ImpairedRadio:
    """A deterministic bidirectional datagram link with steady-state impairment.

    The trade harness impairs a hand-picked pair of connect-phase sequence ids.
    A gift is hundreds of parent VBlanks of back-to-back block traffic and the
    failure this test hunts lives *inside* those transfers, so the rule here is
    periodic: the first transmission of every ``drop_every``-th DATA sequence is
    dropped and every ``duplicate_every``-th is duplicated, with different phase
    per direction so both peers lose frames.  Retransmissions are recognized by
    direction+seq and always delivered.  An alternating 1/4 ms delay makes later
    DATA overtake earlier DATA continuously.

    Reliable control ACKs are never dropped: the point is DATA recovery, not
    randomized test duration.
    """

    def __init__(self, *, drop_every=31, duplicate_every=17):
        self.pending = []
        self._order = 0
        self.drop_every = drop_every
        self.duplicate_every = duplicate_every
        self.attempts = defaultdict(int)
        self.dropped = []
        self.duplicated = []
        self.reordered = 0
        self.delivered = 0
        self.data_frames = defaultdict(int)
        self.control_frames = defaultdict(int)
        self.initialized = []

    def _drop_phase(self, direction):
        return 0 if direction == "host" else 7

    def send(self, direction, emission, now):
        wire = emission.serialize()
        frame = reliable.parse_reliable(wire)
        is_data = bool(frame.flagsA & 0x01)
        key = (direction, frame.seq)
        self.attempts[key] += 1
        attempt = self.attempts[key]
        if is_data:
            self.data_frames[direction] += 1
        else:
            self.control_frames[direction] += 1
        if frame.flagsA & 0x08:                 # Initialized: the stream-opening frame
            self.initialized.append((direction, frame.seq, frame.payload))

        if (is_data and attempt == 1
                and frame.seq % self.drop_every == self._drop_phase(direction)):
            self.dropped.append(key)
            return

        delay = 1 if not is_data or (frame.seq & 1) else 4
        if is_data and any(p.direction == direction and p.due > now + delay
                           for p in self.pending):
            self.reordered += 1             # this frame will overtake one already queued
        self._enqueue(direction, wire, now + delay)
        if (is_data and attempt == 1
                and frame.seq % self.duplicate_every == 0):
            self.duplicated.append(key)
            self._enqueue(direction, wire, now + delay + 1)

    def _enqueue(self, direction, wire, due):
        self._order += 1
        self.pending.append(_AirPacket(due, self._order, direction, wire))

    def deliver(self, now):
        ready = [p for p in self.pending if p.due <= now]
        self.pending = [p for p in self.pending if p.due > now]
        ready.sort(key=lambda p: (p.due, p.order))
        self.delivered += len(ready)
        return ready


class ScriptedMysteryGiftConsole:
    """The Switch peer: :class:`ConsoleClientModel` behind Reliable + RFU.

    The transport half (Reliable stream, ``C``/``A`` connect, ``K`` acks, the NI
    game-data handshake, UNI framing) is the proven trade child.  The activity
    half is delegated wholesale to the imported console model: every parent UNI
    poll that Reliable delivers is handed to ``step`` and the 14-byte row it
    returns is the console's next gSendCmd.

    That one-row-in/one-row-out coupling is the console's VBlank: on hardware a
    parent poll and the child's reply are the same interrupt.  Because Reliable
    delivers each parent poll exactly once and in order, the model sees the same
    row sequence it would over a perfect link - proving that is the test.
    """

    def __init__(self, console, *, close_rows=4):
        self.console = console
        self.rel = reliable.HostReliableSession(ack_period_ms=5,
                                                rto_bootstrap_ms=20)
        self.connect_id = b"\x80\x84"
        self.ni_send = None
        self.ni_recv = ni.NIReceiver()
        self.ts = 1
        self.k_seq = 1
        self.accept_seen = False
        self.disconnect_seen = False
        self.parent_rows = 0
        self.ni_frames_in = 0
        self.ni_frames_out = 0
        self.uni_frames_in = 0
        self.uni_frames_out = 0
        self.close_rows_sent = 0
        self._close_rows = close_rows
        self._out_rows = deque()
        self._gba_pending = []

    def start(self, now):
        """Open the joiner stream with metadata, followed by RFU C."""
        return [
            self.rel.open(reliable.METADATA_FRAME, now),
            self.rel.send(gbaframe.build_connect(self.connect_id), now),
        ]

    # --- inbound ------------------------------------------------------------------------------
    def receive(self, wire, now):
        for delivery in self.rel.receive(wire, now):
            rec = gbaframe.parse_in(delivery.payload)
            if rec is None:
                continue
            if rec["type"] == "A":
                assert rec["connect_id"] == self.connect_id
                self.accept_seen = True
                # gRfuGameData.activity = ACTIVITY_WONDER_CARD, so the leader sees
                # the same activity it advertised [union_room.c SetHostRfuGameData].
                self.ni_send = ni.NISender(ni.build_game_data(
                    CHILD_VERSION_LOW, CHILD_TRAINER_ID, CHILD_NAME,
                    activity=beacon.ACTIVITY_WONDER_CARD))
            elif rec["type"] == "T":
                self.k_seq += 1
                self._queue_gba(gbaframe.build_k(self.k_seq, 1, rec["ts"]), now)
                if rec.get("ni") is not None:
                    self.ni_frames_in += 1
                    ack = self.ni_recv.on_host_ni(rec["ni"])
                    if ack is not None:
                        self._queue_gba(gbaframe.wrap_t(ack, self.ts), now)
                        self.ts += 1
                elif rec.get("slots"):
                    self.uni_frames_in += 1
                    self.parent_rows += 1
                    # Row 0 of the parent's gRecvCmds echo table is its own
                    # gSendCmd [ReadAllPlayerRecvCmds, link_rfu_2.c:743].
                    rows = dict(rec["slots"])
                    self._out_rows.append(self._console_row(rows[0]))
            elif rec["type"] == gbaframe.TYPE_D:
                self.disconnect_seen = True

    def _console_row(self, parent_row):
        row = self.console.step(parent_row)
        if self.console.func == "done" and self.close_rows_sent < self._close_rows:
            # The client task is finished, so the menu hands the link to
            # Rfu_SetCloseLinkCallback [mystery_gift_menu.c:1248] and the console
            # advertises READY_CLOSE_LINK instead of its own idle rows.
            self.close_rows_sent += 1
            row = rfu.serialize(rfu.close_link_words(1))
        return row

    # --- outbound -----------------------------------------------------------------------------
    def _queue_gba(self, frame, now):
        # advance() owns the radio; receive() only parks immediate replies here.
        self._gba_pending.append((bytes(frame), now))

    def advance(self, now):
        if self.disconnect_seen:
            pass
        elif self.ni_send is not None and not self.ni_send.done:
            slot = self.ni_send.next_slot()
            self.ni_frames_out += 1
            self._gba_pending.append((gbaframe.wrap_t(slot, self.ts), now))
            self.ts += 1
        else:
            # One UNI reply per parent poll consumed, so a radio stall followed
            # by a burst does not silently rate-limit the console.
            while self._out_rows:
                row = self._out_rows.popleft()
                self._gba_pending.append(
                    (gbaframe.wrap_t(rfu.uni_slot(row), self.ts), now))
                self.ts += 1
                self.uni_frames_out += 1
        pending, self._gba_pending = self._gba_pending, []
        out = [self.rel.send(frame, stamped) for frame, stamped in pending]
        return out + self.rel.poll(now)


class LeaderStack:
    """The distributor under test, composed exactly as the live host composes it."""

    def __init__(self, engine):
        self.session = HostSession(
            engine=engine,
            reliable_kwargs={"ack_period_ms": 5, "rto_bootstrap_ms": 20},
            rfu_kwargs={"host_session_id": b"\xb7\xf1"})
        self.rel = self.session.reliable
        self.rfu = self.session.rfu
        self.engine = self.session.activity
        self.events = []

    def receive(self, wire, now):
        self.events.extend(self.session.receive_reliable(wire, now))

    def advance(self, now):
        return self.session.tick(now)


@dataclass
class _Run:
    host: LeaderStack
    child: ScriptedMysteryGiftConsole
    console: ConsoleClientModel
    engine: host_mystery_gift.HostMysteryGiftEngine
    radio: ImpairedRadio
    card: bytes
    ram_script: bytes
    elapsed: int


def _run_full_stack(*, console=None, timing=None, radio=None, max_ms=6000,
                    require_completion=True):
    """Drive the whole leader stack against the console model over the radio."""
    card, ram_script = wonder_card.build_default_gift()
    if console is None:
        console = ConsoleClientModel(flag_id=0)
    if timing is None:
        # Only the console-ready idle window is shortened, purely for test
        # duration.  inter_block_gap_frames keeps its shipped value: it is the
        # thing under test.
        timing = host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10)
    engine = host_mystery_gift.HostMysteryGiftEngine(
        card, ram_script,
        link_player=linkplayer.LinkPlayer(name=HOST_NAME,
                                          version=linkplayer.VERSION_FIRE_RED),
        timing=timing)
    host = LeaderStack(engine)
    child = ScriptedMysteryGiftConsole(console)
    radio = radio if radio is not None else ImpairedRadio()

    for emission in child.start(0):
        radio.send("child", emission, 0)

    for now in range(max_ms):
        for packet in radio.deliver(now):
            if packet.direction == "child":
                host.receive(packet.wire, now)
            else:
                child.receive(packet.wire, now)

        for emission in host.advance(now):
            radio.send("host", emission, now)
        for emission in child.advance(now):
            radio.send("child", emission, now)

        if (engine.done and child.disconnect_seen
                and host.rel.inflight == child.rel.inflight == 0
                and not radio.pending):
            return _Run(host, child, console, engine, radio, card, ram_script, now)

    if require_completion:
        raise AssertionError(
            f"gift full stack timed out: t={max_ms} engine={engine.state} "
            f"rfu={host.rfu.state} console={console.func} "
            f"result={console.result} dropped_inits={console.dropped_inits} "
            f"pending={len(radio.pending)} "
            f"inflight={host.rel.inflight}/{child.rel.inflight}")
    return _Run(host, child, console, engine, radio, card, ram_script, None)


_CACHED_RUN = []


def _gift_run():
    """One shared happy-path run; the assertions below inspect it from different angles."""
    if not _CACHED_RUN:
        _CACHED_RUN.append(_run_full_stack())
    return _CACHED_RUN[0]


# --- independent MysteryGiftLink stage-5 fixture ----------------------------------------------
def test_native_shaped_mgl_fixture_covers_the_stage_5_id16_id17_handoff():
    """Check the first post-LinkPlayer exchange without sharing the sender codec.

    ``Task_PlayerExchange`` case 6 only makes the menu construct
    ``MysteryGiftClient``.  Its initial script waits for ID16, whose native
    ``sClientScript_SendGameData`` is 32 bytes; that script then returns a
    96-byte ID17 ``MysteryGiftLinkGameData``.  These exact blocks must be right
    before a live run can attribute a failure to anything after stage 5.

    Include the later message shapes here as cheap regression coverage of the
    same framing code.  The fixture is source-shaped, not a round-trip through
    the production sender.
    """
    card, ram_script = wonder_card.build_default_gift()
    game_data = ConsoleClientModel(flag_id=0).game_data
    cases = (
        (mg.MG_LINKID_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SEND_GAME_DATA,
         len(mg_script.CLIENT_SCRIPT_SEND_GAME_DATA)),
        (mg.MG_LINKID_GAME_DATA, game_data, len(game_data)),
        (mg.MG_LINKID_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD,
         len(mg_script.CLIENT_SCRIPT_SAVE_CARD)),
        (mg.MG_LINKID_CARD, card, len(card)),
        (mg.MG_LINKID_RAM_SCRIPT, ram_script, 0),
        (mg.MG_LINKID_READY_END, b"", 0),
    )
    assert len(mg_script.CLIENT_SCRIPT_SEND_GAME_DATA) == 32
    assert len(game_data) == mg_script.GAME_DATA_SIZE == 96

    for ident, payload, size in cases:
        native = _native_mgl_blocks(ident, payload, size)
        assert mg_link.build_message(ident, payload, size) == native

        # The production receive state machine must also accept the blocks the
        # independent native-shaped sender produced, including 1024-byte
        # size-zero messages and RFU-fragment padding on every completed block.
        receiver = mg_link.MysteryGiftLinkReceiver()
        receiver.expect(ident)
        padded = [block.ljust(((len(block) + 11) // 12) * 12, b"\x00")
                  for block in native]
        result = None
        for complete_block in padded:
            result = receiver.feed_block(complete_block)
        declared_size = 0x400 if size == 0 else size
        assert result == bytes(payload).ljust(declared_size, b"\x00")


# --- the gift itself ------------------------------------------------------------------------
def test_wonder_card_reaches_the_console_through_loss_duplication_and_reordering():
    run = _gift_run()

    assert run.console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert run.engine.result == mg_server.SVR_MSG_CARD_SENT and run.engine.gift_sent
    # The console saved exactly the bytes we authored, after hundreds of VBlanks
    # of block traffic across an impaired link.
    assert run.console.saved_card == run.card
    assert run.console.saved_ram_script.startswith(run.ram_script)
    assert run.console.saved_ram_script[len(run.ram_script):] == b"\x00" * (
        995 - len(run.ram_script))
    assert [ident for ident, _payload in run.console.messages_received] == [
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SendGameData
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SaveCard
        mg.MG_LINKID_CARD,
        mg.MG_LINKID_RAM_SCRIPT,
    ]


def test_the_shared_link_bring_up_completes_below_the_gift():
    """Everything under the activity is the hardware-proven trade bring-up."""
    run = _gift_run()

    assert run.host.rel.local_opened and run.host.rel.peer_opened
    assert run.child.rel.local_opened and run.child.rel.peer_opened
    assert ("child", 0xFFF0, reliable.METADATA_FRAME) in run.radio.initialized
    assert any(direction == "host" and seq == 0xFFF0
               and gbaframe.parse_in(payload)["type"] == "A"
               for direction, seq, payload in run.radio.initialized)
    assert "connect" in run.host.events and run.child.accept_seen
    assert run.host.rfu.child_game_data is not None and run.child.ni_recv.complete
    assert run.host.rfu.child_trainer_id == CHILD_TRAINER_ID
    assert run.child.ni_frames_in > 0 and run.child.ni_frames_out > 0

    # The LinkPlayer exchange that precedes MysteryGiftClient_Create.
    assert run.engine.child_link_player.name == CHILD_NAME
    assert run.console.host_link_player.name == HOST_NAME
    assert run.console.standby_sent and run.console.standby_echoed


def test_reliable_hides_every_impairment_from_the_rfu_block_pacing():
    """The real point.  SEND_BLOCK_INIT is dropped on the floor unless the
    receive slot is RECV_STATE_READY [link_rfu_2.c:1146], and nothing on the wire
    acknowledges a block - so a retransmit-induced burst that outran the
    console's MGL_ResetReceived would strand it with no error at all.
    """
    run = _gift_run()

    # The radio really did misbehave, in both directions, while blocks were flowing.
    assert [d for d, _seq in run.radio.dropped if d == "host"]
    assert [d for d, _seq in run.radio.dropped if d == "child"]
    assert run.radio.duplicated and run.radio.reordered > 0
    assert all(run.radio.attempts[key] >= 2 for key in run.radio.dropped)

    assert run.console.dropped_inits == 0
    assert run.console.dropped_fragments == 0
    # If the native INIT resends [link_rfu_2.c:1370] were not reaching the
    # console at all, dropped_inits would be zero for the wrong reason.
    assert run.console.redundant_inits > 0

    # Reliable delivered every parent poll exactly once and in order: the console
    # model saw the same row stream a perfect link would have given it, despite
    # dozens of dropped and duplicated DATA frames in the middle of the blocks.
    assert run.child.parent_rows == run.host.rfu.uni_out > 0
    # The other direction is a bound, not an equality: the leader leaves UNI the
    # moment it emits D [RFULeader.disconnect_frame], so the last few console
    # rows still in flight are refused by design.
    assert 0 < run.host.rfu.uni_in <= run.child.uni_frames_out
    # Both console->leader messages of the conversation arrived intact anyway.
    assert run.engine.server.messages_received == 2      # GAME_DATA, READY_END


def test_the_gap_is_still_what_prevents_the_drop_over_the_impaired_radio():
    """Negative control, so the assertions above cannot pass vacuously.

    Same stack, same radio, a console that consumes blocks slowly and a leader
    whose inter-block gap has been removed: the transfer must die exactly where
    the offline test says it does.
    """
    starved = ConsoleClientModel(flag_id=0, consume_latency=6)
    run = _run_full_stack(
        console=starved, max_ms=2500, require_completion=False,
        timing=host_mystery_gift.MysteryGiftTiming(
            client_ready_idle_frames=10, inter_block_gap_frames=0))
    assert starved.dropped_inits > 0
    assert run.elapsed is None and starved.result is None
    assert run.engine.result is None

    # ... and the shipped gap absorbs that same slow console over the same radio.
    slow = ConsoleClientModel(flag_id=0, consume_latency=6)
    slow_run = _run_full_stack(console=slow)
    assert slow.dropped_inits == 0
    assert slow.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert slow_run.engine.result == mg_server.SVR_MSG_CARD_SENT


def test_close_and_disconnect_handshake_finishes_the_session():
    run = _gift_run()

    assert run.child.close_rows_sent > 0 and run.engine.close_confirmed
    assert run.host.session.close_poll_sent and run.host.session.disconnect_sent
    assert run.child.disconnect_seen
    assert run.engine.state == host_mystery_gift.MG_DONE and run.engine.done
    assert run.engine.state_history == [
        host_mystery_gift.MG_LINK_PLAYER, host_mystery_gift.MG_START,
        host_mystery_gift.MG_GIFT, host_mystery_gift.MG_CLOSE,
        host_mystery_gift.MG_DONE]
    assert run.host.rfu.state == DISCONNECTED
    assert run.host.rel.inflight == run.child.rel.inflight == 0
    # One parent poll per millisecond is the clean-link floor, so this bounds
    # what loss recovery cost: retransmission must not stretch a gift handout.
    assert run.elapsed < run.host.rfu.uni_out * 1.5


# --- standalone runner ----------------------------------------------------------------------
def _run():
    tests = sorted((n, f) for n, f in globals().items()
                   if n.startswith("test_") and callable(f))
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
        else:
            print(f"ok    {name}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
