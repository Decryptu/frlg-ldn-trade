"""Offline tests for the Mystery Gift distributor: framing, scripts, server, engine.

The centrepiece is :class:`ConsoleClientModel` - a model of the Switch side built
from the decomp rather than from our own encoders, so the end-to-end test is a
real check and not a tautology. It models the three things that can strand a
live console:

* ``RfuHandleReceiveCommand``'s block gate - ``SEND_BLOCK_INIT`` is ignored
  unless the slot is ``RECV_STATE_READY`` [link_rfu_2.c:1146], and the slot only
  returns to READY when ``MGL_ResetReceived`` runs. A dropped INIT is counted and
  asserted to be zero, because on hardware it is a silent hang.
* ``MGL_Receive``'s header/chunk stepping, ident check and final CRC.
* ``MysteryGiftClient_Run``'s one-command-per-frame script execution out of a
  buffer we filled.

Run standalone (no pytest needed):   python tests/test_mystery_gift_flow.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    block, charmap, host_mystery_gift, linkplayer, mg_link, mg_script, mg_server, rfu,
    trade, wonder_card,
)
from frlgsim import mystery_gift as mg  # noqa: E402


# --- MysteryGiftLink framing ------------------------------------------------------------------
def test_message_header_layout_and_crc_cover_the_padded_buffer():
    payload = b"\x11\x22\x33"
    blocks = mg_link.build_message(mg.MG_LINKID_CARD, payload, size=8)
    ident, crc, size = mg_link.parse_header(blocks[0])
    assert (ident, size) == (mg.MG_LINKID_CARD, 8)
    # The CRC is over the declared size including zero padding, not the prefix.
    assert crc == mg.crc16(payload.ljust(8, b"\x00"))
    assert crc != mg.crc16(payload)


def test_size_zero_expands_to_the_full_buffer():
    """InitSend(size=0) means MG_LINK_BUFFER_SIZE [mystery_gift_link.c:55], which is
    how the RAM script and READY_END travel."""
    blocks = mg_link.build_message(mg.MG_LINKID_RAM_SCRIPT, b"\x6a\x5a", size=0)
    _ident, _crc, size = mg_link.parse_header(blocks[0])
    assert size == mg.MG_LINK_BUFFER_SIZE == 1024
    assert len(blocks) == 1 + 5                      # header + 252*4 + 16
    assert [len(b) for b in blocks[1:]] == [252, 252, 252, 252, 16]


def test_chunking_matches_mgl_send_walk():
    """MGL_Send sends 252 while >252 remain and the remainder otherwise, so an
    exact multiple ends on a full chunk with no trailing empty block."""
    assert [len(c) for c in mg_link.chunk_payload(b"\x00" * 252)] == [252]
    assert [len(c) for c in mg_link.chunk_payload(b"\x00" * 504)] == [252, 252]
    assert [len(c) for c in mg_link.chunk_payload(b"\x00" * 332)] == [252, 80]


def test_receiver_round_trips_every_ident_we_send():
    for ident, payload, size in (
            (mg.MG_LINKID_CLIENT_SCRIPT, mg_script.CLIENT_SCRIPT_SAVE_CARD, None),
            (mg.MG_LINKID_CARD, wonder_card.build_default_gift()[0], None),
            (mg.MG_LINKID_RAM_SCRIPT, wonder_card.build_default_gift()[1], 0),
            (mg.MG_LINKID_READY_END, b"", 0)):
        blocks = mg_link.build_message(ident, payload, size)
        receiver = mg_link.MysteryGiftLinkReceiver()
        receiver.expect(ident)
        out = [receiver.feed_block(b) for b in blocks]
        assert out[:-1] == [None] * (len(blocks) - 1)
        assert out[-1].startswith(bytes(payload))
        assert not receiver.active


def test_receiver_tolerates_fragment_padded_blocks():
    """RFU delivers blocks padded to a multiple of the 12-byte fragment size."""
    payload = bytes(range(100))
    blocks = mg_link.build_message(mg.MG_LINKID_CARD, payload)
    padded = [b.ljust(block.frag_count(len(b)) * block.FRAG_BYTES, b"\x00") for b in blocks]
    receiver = mg_link.MysteryGiftLinkReceiver()
    receiver.expect(mg.MG_LINKID_CARD)
    assert receiver.feed_block(padded[0]) is None
    assert receiver.feed_block(padded[1]) == payload


def test_receiver_faults_exactly_where_the_console_calls_fatal_error():
    good = mg_link.build_message(mg.MG_LINKID_CARD, b"abcd")

    receiver = mg_link.MysteryGiftLinkReceiver()
    receiver.expect(mg.MG_LINKID_NEWS)                       # wrong ident
    try:
        receiver.feed_block(good[0])
    except mg_link.MysteryGiftLinkError:
        pass
    else:
        raise AssertionError("ident mismatch must fault")

    receiver = mg_link.MysteryGiftLinkReceiver()
    receiver.expect(mg.MG_LINKID_CARD)                       # size > buffer
    try:
        receiver.feed_block(mg_link.build_header(mg.MG_LINKID_CARD, 0, 0x401))
    except mg_link.MysteryGiftLinkError:
        pass
    else:
        raise AssertionError("oversized message must fault")

    receiver = mg_link.MysteryGiftLinkReceiver()
    receiver.expect(mg.MG_LINKID_CARD)                       # corrupt payload
    receiver.feed_block(good[0])
    try:
        receiver.feed_block(b"\x00" * 4)
    except mg_link.MysteryGiftLinkError:
        pass
    else:
        raise AssertionError("CRC mismatch must fault")


# --- client scripts + link game data -----------------------------------------------------------
def test_client_scripts_match_the_decomp_arrays():
    """Byte-for-byte against src/mystery_gift_scripts.c, 8 bytes per command."""
    assert mg_script.CLIENT_SCRIPT_INIT == mg_script.client_script(
        (mg_script.CLI_RECV, mg.MG_LINKID_CLIENT_SCRIPT), mg_script.CLI_COPY_RECV)
    assert len(mg_script.CLIENT_SCRIPT_SEND_GAME_DATA) == 4 * mg_script.CLIENT_CMD_SIZE
    assert len(mg_script.CLIENT_SCRIPT_SAVE_CARD) == 6 * mg_script.CLIENT_CMD_SIZE
    # sClientScript_SaveCard: RECV CARD, SAVE_CARD, RECV RAM_SCRIPT, SAVE_RAM_SCRIPT,
    # SEND_READY_END, RETURN CLI_MSG_CARD_RECEIVED [mystery_gift_scripts.c:42].
    words = [int.from_bytes(mg_script.CLIENT_SCRIPT_SAVE_CARD[i:i + 4], "little")
             for i in range(0, len(mg_script.CLIENT_SCRIPT_SAVE_CARD), 4)]
    assert words == [
        mg_script.CLI_RECV, mg.MG_LINKID_CARD,
        mg_script.CLI_SAVE_CARD, 0,
        mg_script.CLI_RECV, mg.MG_LINKID_RAM_SCRIPT,
        mg_script.CLI_SAVE_RAM_SCRIPT, 0,
        mg_script.CLI_SEND_READY_END, 0,
        mg_script.CLI_RETURN, mg_script.CLI_MSG_CARD_RECEIVED,
    ]


def test_every_client_script_terminates_execution():
    """CopyRecvScript copies the whole 1024-byte buffer, so a script that runs off
    its own end would execute stale bytes from the previous message."""
    stoppers = (mg_script.CLI_RETURN, mg_script.CLI_COPY_RECV,
                mg_script.CLI_COPY_RECV_IF, mg_script.CLI_COPY_RECV_IF_N)
    for name in dir(mg_script):
        if not name.startswith("CLIENT_SCRIPT_"):
            continue
        script = getattr(mg_script, name)
        last = int.from_bytes(script[-mg_script.CLIENT_CMD_SIZE:][:4], "little")
        assert last in stoppers, f"{name} ends with instruction {last}"


def _game_data(flag_id=0, version_code=mg.VERSION_CODE_FIRERED, magic=mg.GAME_DATA_VALID_VAR):
    """Build what MysteryGift_LoadLinkGameData [mystery_gift.c:337] would produce."""
    data = bytearray(mg_script.GAME_DATA_SIZE)
    data[0x00:0x04] = magic.to_bytes(4, "little")
    data[0x04:0x06] = (1).to_bytes(2, "little")
    data[0x08:0x0C] = (1).to_bytes(4, "little")
    data[0x0C:0x0E] = (1).to_bytes(2, "little")
    data[0x10:0x14] = version_code.to_bytes(4, "little")
    data[0x14:0x16] = flag_id.to_bytes(2, "little")
    data[0x43:0x4A] = b"\xbf\xc7\xcf\xff\xff\xff\xff"        # "EMU" + terminator
    data[0x4A:0x4E] = (0x47ED8822).to_bytes(4, "little")
    return bytes(data)


def test_link_game_data_offsets_and_validation():
    parsed = mg_script.parse_link_game_data(_game_data(flag_id=1003))
    assert parsed.magic == mg.GAME_DATA_VALID_VAR
    assert parsed.flag_id == 1003 and parsed.has_card
    assert parsed.version_code == mg.VERSION_CODE_FIRERED
    assert parsed.version_name == "FireRed"
    assert parsed.player_name == "EMU"
    assert parsed.trainer_id & 0xFFFF == 0x8822
    assert mg_script.validate_link_game_data(parsed)


def test_link_game_data_rejects_what_the_console_rejects():
    """Exactly the five checks in MysteryGift_ValidateLinkGameData [mystery_gift.c:373]."""
    assert not mg_script.validate_link_game_data(
        mg_script.parse_link_game_data(_game_data(magic=0x102)))
    assert not mg_script.validate_link_game_data(
        mg_script.parse_link_game_data(_game_data(version_code=0x10)))   # low nibble zero
    for offset in (0x04, 0x08, 0x0C):
        data = bytearray(_game_data())
        data[offset] = 2                                     # even -> fails the & 1 test
        assert not mg_script.validate_link_game_data(
            mg_script.parse_link_game_data(bytes(data)))


def test_compare_card_flags():
    assert mg_script.compare_card_flags(1003, mg_script.parse_link_game_data(
        _game_data(flag_id=0))) == mg_script.HAS_NO_CARD
    assert mg_script.compare_card_flags(1003, mg_script.parse_link_game_data(
        _game_data(flag_id=1003))) == mg_script.HAS_SAME_CARD
    assert mg_script.compare_card_flags(1003, mg_script.parse_link_game_data(
        _game_data(flag_id=1001))) == mg_script.HAS_DIFF_CARD


# --- server script branches ---------------------------------------------------------------------
def _run_server(game_data, toss_response=None):
    """Drive MysteryGiftServer through one conversation, returning (idents, result)."""
    card, script = wonder_card.build_default_gift()
    server = mg_server.MysteryGiftServer(card, script)
    sent = []
    for _ in range(32):
        action = server.run()
        if action[0] == "done":
            return sent, action[1]
        if action[0] == "send":
            sent.append(action[1])
            server.on_sent()
        else:
            ident = action[1]
            if ident == mg.MG_LINKID_GAME_DATA:
                server.on_received(ident, game_data)
            elif ident == mg.MG_LINKID_RESPONSE:
                server.on_received(ident, toss_response.to_bytes(4, "little"))
            else:
                server.on_received(ident, b"\x00" * 1024)
    raise AssertionError("server script did not terminate")


def test_server_sends_the_card_when_the_console_has_none():
    sent, result = _run_server(_game_data(flag_id=0))
    assert result == mg_server.SVR_MSG_CARD_SENT
    assert sent == [mg.MG_LINKID_CLIENT_SCRIPT,     # SendGameData
                    mg.MG_LINKID_CLIENT_SCRIPT,     # SaveCard
                    mg.MG_LINKID_CARD,
                    mg.MG_LINKID_RAM_SCRIPT]


def test_server_declines_when_the_console_already_holds_this_card():
    _sent, result = _run_server(_game_data(flag_id=1003))
    assert result == mg_server.SVR_MSG_HAS_CARD


def test_server_prompts_to_toss_a_different_card_and_honours_both_answers():
    sent, result = _run_server(_game_data(flag_id=1001), toss_response=0)   # FALSE = tossed
    assert result == mg_server.SVR_MSG_CARD_SENT
    assert mg.MG_LINKID_CARD in sent
    sent, result = _run_server(_game_data(flag_id=1001), toss_response=1)   # TRUE = kept
    assert result == mg_server.SVR_MSG_CLIENT_CANCELED
    assert mg.MG_LINKID_CARD not in sent


def test_server_refuses_invalid_game_data():
    _sent, result = _run_server(_game_data(magic=0))
    assert result == mg_server.SVR_MSG_CANT_SEND_GIFT_1


# --- console model ------------------------------------------------------------------------------
class ConsoleClientModel:
    """The Switch side: RFU block receive gate + MysteryGiftLink + client script engine."""

    RECV_READY, RECV_RECEIVING, RECV_FINISHED = 0, 1, 2

    def __init__(self, *, flag_id=0, toss_answer=0, echo_delay=4, consume_latency=2):
        self.lp = linkplayer.LinkPlayer(name="ASH", version=linkplayer.VERSION_FIRE_RED,
                                        player_id=1)
        self.toss_answer = toss_answer
        self.echo_delay = echo_delay
        # Frames between a block completing in the RFU receive callback and
        # MGL_Receive getting around to consuming it. The exact interleaving of
        # RfuHandleReceiveCommand and the client task within one frame is not
        # worth pinning down: the host's margin must survive either order, so the
        # model charges a small latency instead of assuming the best case.
        self.consume_latency = consume_latency
        self._received_age = 0
        self.game_data = _game_data(flag_id=flag_id)

        # RFU receive slot for the parent (player 0).
        self.recv_state = self.RECV_READY
        self.recv_count = 0
        self.recv_flags = 0
        self.recv_buf = bytearray()
        self.block_received = False
        self.redundant_inits = 0        # benign: HandleBlockSend re-sends INIT by design
        self.dropped_inits = 0          # fatal: previous block not consumed yet
        self.dropped_fragments = 0

        # Link-establishment phase.
        self.phase = "wait_req"
        self.host_link_player = None
        self.standby_sent = False
        self.standby_echoed = False

        # Mystery Gift client [mystery_gift_client.c].
        self.script = mg_script.CLIENT_SCRIPT_INIT
        self.cmdidx = 0
        self.func = "idle"
        self.param = 0
        self.recv_buffer = bytearray(mg.MG_LINK_BUFFER_SIZE)
        self.link_recv = mg_link.MysteryGiftLinkReceiver()
        self.saved_card = None
        self.saved_ram_script = None
        self.dynamic_msg = None
        self.result = None
        self.messages_received = []

        self._send_blocks = []
        self._sender = None
        self._send_wait = 0
        self._pending_send = None

    # --- RFU receive side ----------------------------------------------------------------------
    def _feed_parent_row(self, row):
        rec = rfu.parse_slot(row)
        if rec is None:
            return None
        op = rec["op"]
        if op == rfu.SEND_BLOCK_INIT:
            if self.recv_state == self.RECV_READY:
                self.recv_count = rec["count"]
                self.recv_flags = 0
                self.recv_buf = bytearray(self.recv_count * block.FRAG_BYTES)
                self.recv_state = self.RECV_RECEIVING
                self.block_received = False
            elif self.recv_state == self.RECV_RECEIVING:
                # Expected: HandleBlockSend re-sends SEND_BLOCK_INIT for several
                # frames [link_rfu_2.c:1370] and the receiver ignores the repeats.
                self.redundant_inits += 1
            else:
                # RECV_FINISHED: the previous block has not been consumed, so
                # this INIT is silently discarded and the console then waits
                # forever for fragments that are never re-sent.
                self.dropped_inits += 1
        elif op == rfu.SEND_BLOCK:
            if self.recv_state == self.RECV_RECEIVING:
                index = rec["index"]
                self.recv_flags |= 1 << index
                self.recv_buf[index * block.FRAG_BYTES:
                              (index + 1) * block.FRAG_BYTES] = rec["frag"]
                if self.recv_flags == block.all_received_mask(self.recv_count):
                    self.recv_state = self.RECV_FINISHED
                    self.block_received = True
                    self._received_age = 0
            else:
                self.dropped_fragments += 1
        return rec

    @property
    def _consumable(self):
        return self.block_received and self._received_age >= self.consume_latency

    def _reset_received(self):
        self.block_received = False
        self.recv_state = self.RECV_READY

    # --- per-VBlank ----------------------------------------------------------------------------
    def step(self, parent_row):
        rec = self._feed_parent_row(parent_row)
        if self.block_received:
            self._received_age += 1
        if self.phase != "gift":
            return self._step_link(rec)
        return self._step_gift()

    def _step_link(self, rec):
        if rec is not None and rec["op"] == rfu.SEND_BLOCK_REQ and self.phase == "wait_req":
            # Both sides Rfu_InitBlockSend their 200-byte LinkPlayerBlock.
            self.phase = "exchange"
            self._sender = block.BlockSender(
                linkplayer.build_block(self.lp).ljust(200, b"\x00"), owner=1, trust_pia=True)
        if self._consumable and self.host_link_player is None:
            parsed, ok = linkplayer.parse_block(bytes(self.recv_buf))
            assert ok, "host LinkPlayer block failed the GameFreak magic check"
            self.host_link_player = parsed
            self._reset_received()
        if self._sender is not None and not self._sender.done:
            return rfu.serialize(self._sender.tick(None))
        self._sender = None
        if self.host_link_player is not None and not self.standby_sent:
            # union_room.c:2391 SetLinkStandbyCallback, once.
            self.standby_sent = True
            return rfu.serialize(rfu.exit_standby_words(0))
        if rec is not None and rec["op"] == rfu.READY_EXIT_STANDBY and self.standby_sent:
            self.standby_echoed = True
            self.phase = "gift"          # mystery_gift_menu.c:1231 MysteryGiftClient_Create
        return rfu.idle_slot()

    def _step_gift(self):
        if self.func == "idle":
            self.func = "run"
        if self.func == "recv":
            return self._step_recv()
        if self.func == "send":
            return self._step_send()
        if self.func == "run":
            self._run_one_command()
        return rfu.idle_slot()

    def _step_recv(self):
        if self._consumable:
            payload = self.link_recv.feed_block(bytes(self.recv_buf))
            self._reset_received()
            if payload is not None:
                self.recv_buffer[:len(payload)] = payload
                self.messages_received.append((self.link_recv.ident, payload))
                self.func = "run"
        return rfu.idle_slot()

    def _step_send(self):
        if self._send_wait > 0:
            self._send_wait -= 1
            return rfu.idle_slot()
        if self._sender is None:
            if not self._send_blocks:
                self.func = "run"
                return rfu.idle_slot()
            self._sender = block.BlockSender(
                self._send_blocks.pop(0), owner=1, trust_pia=True)
        words = self._sender.tick(None)
        if self._sender.done:
            self._sender = None
            # MGL_Send waits for its own block to come back through the parent's
            # row-1 echo before starting the next one.
            self._send_wait = self.echo_delay
        return rfu.serialize(words)

    def _begin_send(self, ident, payload, size):
        self._send_blocks = mg_link.build_message(ident, payload, size)
        self.func = "send"

    def _run_one_command(self):
        offset = self.cmdidx * mg_script.CLIENT_CMD_SIZE
        instr = int.from_bytes(self.script[offset:offset + 4], "little")
        param = int.from_bytes(self.script[offset + 4:offset + 8], "little")
        self.cmdidx += 1
        if instr == mg_script.CLI_NONE:
            return
        if instr == mg_script.CLI_RECV:
            self.link_recv.expect(param)
            self.func = "recv"
        elif instr == mg_script.CLI_COPY_RECV:
            self.script = bytes(self.recv_buffer)
            self.cmdidx = 0
        elif instr == mg_script.CLI_LOAD_GAME_DATA:
            self._pending_send = (mg.MG_LINKID_GAME_DATA, self.game_data,
                                 len(self.game_data))
        elif instr == mg_script.CLI_SEND_LOADED:
            self._begin_send(*self._pending_send)
        elif instr == mg_script.CLI_SAVE_CARD:
            self.saved_card = bytes(self.recv_buffer[:332])
        elif instr == mg_script.CLI_SAVE_RAM_SCRIPT:
            # InitRamScript_NoObjectEvent clamps to script[995] [src/script.c:577].
            self.saved_ram_script = bytes(self.recv_buffer[:995])
        elif instr == mg_script.CLI_COPY_MSG:
            # memcpy(client->msg, client->recvBuffer, CLIENT_MAX_MSG_SIZE)
            # [mystery_gift_client.c] - a fixed 64 bytes regardless of the
            # message's declared size; the text is EOS-terminated.
            self.dynamic_msg = bytes(self.recv_buffer[:mg_script.CLIENT_MAX_MSG_SIZE])
        elif instr == mg_script.CLI_ASK_TOSS:
            self.param = self.toss_answer
        elif instr == mg_script.CLI_LOAD_TOSS_RESPONSE:
            self._pending_send = (mg.MG_LINKID_RESPONSE,
                                 self.param.to_bytes(4, "little"), 4)
        elif instr == mg_script.CLI_SEND_READY_END:
            self._begin_send(mg.MG_LINKID_READY_END, b"", 0)
        elif instr == mg_script.CLI_RETURN:
            self.result = param
            self.func = "done"
        else:
            raise AssertionError(f"console model has no case for instruction {instr}")


def _drive(console, *, max_frames=4000, card=None, ram_script=None, timing=None,
           require_completion=True):
    """Run the engine against the console model until both sides are finished."""
    if card is None:
        card, ram_script = wonder_card.build_default_gift()
    if timing is None:
        timing = host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10)
    engine = host_mystery_gift.HostMysteryGiftEngine(
        card, ram_script,
        link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED),
        timing=timing)
    close_rows = 0
    for frame in range(max_frames):
        parent_row = rfu.serialize(engine.tick())
        child_row = console.step(parent_row)
        if console.func == "done" and close_rows < 4:
            # Rfu_SetCloseLinkCallback [mystery_gift_menu.c:1248].
            child_row = rfu.serialize(rfu.close_link_words(1))
            close_rows += 1
        engine.feed_child_slot(child_row)
        if engine.disconnect_requested:
            engine.mark_disconnect_sent()
            return engine, frame
    if require_completion:
        raise AssertionError(
            f"flow did not finish: engine={engine.state} console={console.func} "
            f"result={console.result}")
    return engine, None


def test_end_to_end_gift_reaches_a_console_with_no_card():
    card, ram_script = wonder_card.build_default_gift()
    console = ConsoleClientModel(flag_id=0)
    engine, _frames = _drive(console, card=card, ram_script=ram_script)

    assert console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert engine.result == mg_server.SVR_MSG_CARD_SENT and engine.gift_sent
    assert engine.state == host_mystery_gift.MG_DONE and engine.done
    # The console saved exactly the bytes we authored.
    assert console.saved_card == card
    assert console.saved_ram_script.startswith(ram_script)
    assert console.saved_ram_script[len(ram_script):] == b"\x00" * (995 - len(ram_script))
    # Both sides agree on the identity exchange that preceded the gift.
    assert engine.child_link_player.name == "ASH"
    assert console.host_link_player.name == "EMU"


def test_end_to_end_never_drops_a_block_init():
    """The pacing check: an INIT that arrives before the console consumed the
    previous block is discarded, and the transfer then hangs with no error."""
    console = ConsoleClientModel(flag_id=0)
    _drive(console)
    assert console.dropped_inits == 0
    assert console.dropped_fragments == 0
    # The console must still be seeing the native INIT resends; if it were not,
    # this test would be passing for the wrong reason.
    assert console.redundant_inits > 0


def test_inter_block_gap_is_what_prevents_the_drop():
    """Give the console a slow consume and remove the gap: the transfer dies.

    This is the regression guard for :attr:`MysteryGiftTiming.inter_block_gap_frames`
    - without it there is nothing in the protocol that stops us overrunning the
    console, because the receiver never acknowledges a block.
    """
    slow = ConsoleClientModel(flag_id=0, consume_latency=6)
    _drive(slow)                                        # default gap absorbs it
    assert slow.dropped_inits == 0 and slow.result == mg_script.CLI_MSG_CARD_RECEIVED

    starved = ConsoleClientModel(flag_id=0, consume_latency=6)
    engine, finished = _drive(
        starved, max_frames=1500, require_completion=False,
        timing=host_mystery_gift.MysteryGiftTiming(
            client_ready_idle_frames=10, inter_block_gap_frames=0))
    assert starved.dropped_inits > 0
    assert finished is None and starved.result is None
    assert engine.result is None


def test_pacing_budget_is_what_the_timing_docstring_claims():
    """Lock the measured margin so a change to the gap or to the block sender's
    INIT resend count cannot silently shrink it."""
    gap = host_mystery_gift.DEFAULT_MYSTERY_GIFT_TIMING.inter_block_gap_frames

    def survives(latency):
        console = ConsoleClientModel(flag_id=0, consume_latency=latency)
        _drive(console, max_frames=6000, require_completion=False)
        return console.result == mg_script.CLI_MSG_CARD_RECEIVED, console.dropped_inits

    lossless, dropped = survives(gap + 1)
    assert lossless and dropped == 0, "clean margin should be the gap plus one frame"
    completed, dropped = survives(gap + 4)
    assert completed and dropped > 0, "INIT resends should still rescue a late console"
    completed, _dropped = survives(gap + 5)
    assert not completed, "past the budget the transfer must fail, not silently pass"


def test_end_to_end_message_sequence_matches_the_native_card_flow():
    console = ConsoleClientModel(flag_id=0)
    _drive(console)
    assert [ident for ident, _payload in console.messages_received] == [
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SendGameData
        mg.MG_LINKID_CLIENT_SCRIPT,     # sClientScript_SaveCard
        mg.MG_LINKID_CARD,
        mg.MG_LINKID_RAM_SCRIPT,
    ]


def test_end_to_end_console_holding_a_different_card_is_asked_to_toss():
    console = ConsoleClientModel(flag_id=1001, toss_answer=0)      # FALSE = tossed
    engine, _frames = _drive(console)
    assert engine.result == mg_server.SVR_MSG_CARD_SENT
    assert console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert console.saved_card is not None

    console = ConsoleClientModel(flag_id=1001, toss_answer=1)      # TRUE = kept
    engine, _frames = _drive(console)
    assert engine.result == mg_server.SVR_MSG_CLIENT_CANCELED
    # The *card* cancel path is gServerScript_ClientCanceledCard
    # [union_room_message.c:569], which pushes a live message and ends in
    # CLI_MSG_BUFFER_FAILURE - not the News path's CLI_MSG_COMM_CANCELED.
    assert console.result == mg_script.CLI_MSG_BUFFER_FAILURE
    assert console.saved_card is None
    assert console.dynamic_msg is not None
    assert console.dynamic_msg.startswith(mg_script.TEXT_CANCELED_READING_CARD)
    assert charmap.decode(console.dynamic_msg) == "Canceled reading the Card."


def test_end_to_end_console_already_holding_this_card_is_told_so():
    console = ConsoleClientModel(flag_id=1003)                      # our card's flagId
    engine, _frames = _drive(console)
    assert engine.result == mg_server.SVR_MSG_HAS_CARD
    assert console.result == mg_script.CLI_MSG_HAD_CARD
    assert console.saved_card is None


def _new_link_player_engine():
    card, ram_script = wonder_card.build_default_gift()
    return host_mystery_gift.HostMysteryGiftEngine(card, ram_script)


def _drain_link_player_opening(engine):
    """Drive exactly the parent task's ID announcement and one block request."""
    repeat = engine.timing.player_ids_repeat_frames
    for _ in range(repeat):
        assert engine.tick() == list(rfu.send_player_ids_words())
    assert engine.tick() == list(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE))


def _send_child_link_player(engine, payload, *, owner=1):
    engine.feed_child_slot(rfu.serialize(rfu.init_words(trade.COUNT_PARTY, owner=owner)))
    sender = block.BlockSender(payload, owner=owner, trust_pia=True)
    while not sender.done:
        engine.feed_child_slot(rfu.serialize(sender.tick(None)))


def test_link_player_opening_is_immediate_and_block_request_is_one_shot():
    """The Switch child creates Task_PlayerExchange directly from CHILD_JOINED.

    The former 150-frame quiet period was copied from the native distributor's
    *parent* UI task.  Parent Task_PlayerExchange sends one request, and another
    one can restart the child after its first transfer has completed.
    """
    engine = _new_link_player_engine()
    _drain_link_player_opening(engine)
    assert engine._link_player_requests == 1
    assert engine._link_phase == "wait_child_block"

    requests = 1
    for _ in range(400):
        words = engine.tick()
        if list(words) == list(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE)):
            requests += 1
        engine.feed_child_slot(rfu.idle_slot())
    assert requests == 1
    assert engine._our_blocks_sent == 0
    assert engine.state == host_mystery_gift.MG_LINK_PLAYER


def test_link_player_block_is_sent_only_after_a_completed_valid_child_block():
    engine = _new_link_player_engine()
    _drain_link_player_opening(engine)

    # An INIT only proves the child has begun a transfer.  It is not sufficient
    # to send our block because case 0 may still reset the receive flags.
    engine.feed_child_slot(rfu.serialize(rfu.init_words(trade.COUNT_PARTY, owner=1)))
    assert not engine._host_link_player_queued
    assert not engine._host_link_player_complete
    assert all((engine.tick()[0] & rfu.RFUCMD_MASK)
               not in (rfu.SEND_BLOCK_INIT, rfu.SEND_BLOCK)
               for _ in range(10))

    payload = linkplayer.build_block(
        linkplayer.LinkPlayer(name="ASH", player_id=1)).ljust(200, b"\x00")
    sender = block.BlockSender(payload, owner=1, trust_pia=True)
    while not sender.done:
        engine.feed_child_slot(rfu.serialize(sender.tick(None)))
    assert engine.child_link_player.name == "ASH"
    assert engine._host_link_player_queued
    assert not engine._host_link_player_complete

    # The host emission is inspectable without turning the live log into a
    # per-frame dump: four INIT frames then every 200-byte fragment in order.
    for _ in range(64):
        engine.tick()
        if engine._host_link_player_complete:
            break
    assert engine._host_link_player_complete
    assert engine._link_phase == "wait_standby"
    assert engine._link_player_outbound == [
        *(("INIT", trade.COUNT_PARTY, 0x80),) * 4,
        *(("BLOCK", index) for index in range(trade.COUNT_PARTY)),
    ]
    trace_names = [entry[0] for entry in engine.trace]
    assert trace_names.index("link_player_child_block_valid") < \
        trace_names.index("link_player_host_block_queued") < \
        trace_names.index("link_player_host_block_complete")

    engine.feed_child_slot(rfu.serialize(rfu.exit_standby_words(0)))
    assert engine.state == host_mystery_gift.MG_START


def test_early_link_player_standby_is_latched_until_the_host_block_finishes():
    """The child is allowed to send its one standby before our last fragment.

    We still echo it immediately, so it may not be sent again.  The event must
    therefore be latched rather than ignored while the host block is in flight.
    """
    engine = _new_link_player_engine()
    _drain_link_player_opening(engine)
    _send_child_link_player(
        engine,
        linkplayer.build_block(
            linkplayer.LinkPlayer(name="ASH", player_id=1)).ljust(200, b"\x00"))

    # Four INITs plus fragments 0-15: leave fragment 16 unsent.
    for _ in range(20):
        engine.tick()
    assert not engine._host_link_player_complete
    engine.feed_child_slot(rfu.serialize(rfu.exit_standby_words(7)))
    assert engine.state == host_mystery_gift.MG_LINK_PLAYER
    assert engine._pending_standby_count == 7

    # Do not send another child standby.  The queued echo delays the final
    # fragment, but completion must promote the already-latched event.
    for _ in range(16):
        engine.tick()
        if engine.state == host_mystery_gift.MG_START:
            break
    assert engine._host_link_player_complete
    assert engine.state == host_mystery_gift.MG_START
    assert engine._pending_standby_count is None
    assert ("link_player_barrier_complete", 7) in engine.trace


def test_player_id_repair_never_repeats_the_destructive_block_request():
    engine = _new_link_player_engine()
    _drain_link_player_opening(engine)
    engine.feed_child_slot(rfu.serialize(rfu.init_words(trade.COUNT_PARTY, owner=0)))
    assert engine._child_mp_id == 0

    repair = engine.timing.player_ids_repeat_frames
    for _ in range(repair):
        assert engine.tick() == list(rfu.send_player_ids_words())
    assert all(engine.tick() != list(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE))
               for _ in range(100))
    assert engine._link_player_requests == 1


def test_stale_link_player_block_stops_without_restarting_the_child_transfer():
    """A stale buffer is diagnostically useful, but not safe to overwrite.

    A second SEND_BLOCK_REQ is not a recovery primitive: once the first callback
    is clear it starts a new send while Task_PlayerExchange waits at case 4.
    Keep the link alive and report the exact failure instead of creating that
    ambiguous second transfer.
    """
    engine = _new_link_player_engine()
    _drain_link_player_opening(engine)
    _send_child_link_player(engine, b"\xdd" * 200)
    assert engine.rejected_link_players == 1
    assert engine.child_link_player is None
    assert engine._link_phase == "invalid_child_block"

    for _ in range(300):
        words = engine.tick()
        assert (words[0] & rfu.RFUCMD_MASK) not in (rfu.SEND_BLOCK_REQ,
                                                     rfu.SEND_BLOCK_INIT,
                                                     rfu.SEND_BLOCK)
        engine.feed_child_slot(rfu.idle_slot())
    assert engine._link_player_requests == 1


# --- standalone runner --------------------------------------------------------------------------
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
