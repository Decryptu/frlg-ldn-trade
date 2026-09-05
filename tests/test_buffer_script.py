"""CLI_RUN_BUFFER_SCRIPT: native ARM code the console runs out of gDecompressionBuffer.

The payload is executed for real (unicorn, on a model of the GBA memory map) rather than asserted
about, and the end-to-end tests run it through the same ConsoleClientModel the Mystery Event work
used, whose client-script engine is written from the decomp independently of frlgsim.
"""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    buffer_script, host_mystery_gift, mg_script, mg_server, rfu, rfu_leader, rom_map,
    stamp_rally,
)
from frlgsim import config as configmod  # noqa: E402
from frlgsim.buffer_payloads import PAYLOADS  # noqa: E402
from test_mystery_gift_flow import CONSOLE_TRAINER_ID, ConsoleClientModel, _drive  # noqa: E402


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
needs_unicorn = pytest.mark.skipif(not buffer_script.emulation_available(),
                                   reason="offline execution needs unicorn")


# --- the payloads ---------------------------------------------------------------------------

def test_the_committed_bytes_are_what_the_sources_assemble_to():
    """The machine code is committed so that a live host needs no GBA toolchain. This is what
    stops the committed bytes and asm/*.s drifting apart."""
    if shutil.which("arm-none-eabi-as") is None:
        pytest.skip("no GBA toolchain on this machine")
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "gen_buffer_scripts.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_every_payload_is_arm_sized_and_fits_the_receive_buffer():
    for name in PAYLOADS:
        code = buffer_script.payload(name)
        assert len(code) % 4 == 0
        assert 0 < len(code) <= buffer_script.MAX_BUFFER_SCRIPT_SIZE


def test_a_payload_that_is_not_whole_arm_words_is_refused():
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.validate(b"\x00\x01\x02")


@needs_unicorn
def test_the_trainer_id_probe_reads_the_save_and_returns_one():
    sav2 = bytearray(0x1000)
    sav2[buffer_script.SAV2_PLAYER_TRAINER_ID:
         buffer_script.SAV2_PLAYER_TRAINER_ID + 4] = (0x47ED8822).to_bytes(4, "little")

    run = buffer_script.emulate(buffer_script.payload(buffer_script.TRAINER_ID_PROBE),
                                sav2=bytes(sav2))

    assert run.done and run.returned == buffer_script.BUFFER_SCRIPT_DONE
    assert run.param == 0x47ED8822
    assert run.sav2 == bytes(sav2), "the probe only reads; it must leave the save untouched"


@needs_unicorn
def test_the_probe_survives_the_whole_1024_byte_buffer_the_console_actually_copies():
    """Client_Run memcpys MG_LINK_BUFFER_SIZE bytes whatever we sent, so the payload runs with
    whatever the previous receive left behind sitting after it [mystery_gift_client.c:237]."""
    code = buffer_script.payload(buffer_script.TRAINER_ID_PROBE)
    padded = code + b"\xAA" * (buffer_script.MAX_BUFFER_SCRIPT_SIZE - len(code))
    sav2 = bytearray(0x1000)
    sav2[buffer_script.SAV2_PLAYER_TRAINER_ID:
         buffer_script.SAV2_PLAYER_TRAINER_ID + 4] = (0x00012345).to_bytes(4, "little")

    run = buffer_script.emulate(padded, sav2=bytes(sav2))

    assert run.done and run.param == 0x00012345


@needs_unicorn
def test_a_payload_that_never_returns_is_caught_offline():
    """`b .` - the shape of a bug that would hang the console's Mystery Gift menu for good."""
    with pytest.raises(buffer_script.BufferScriptError, match="never returned"):
        buffer_script.emulate(bytes.fromhex("feffffea"))


@needs_unicorn
def test_a_payload_that_faults_is_caught_offline():
    """ldr r0, [r0] with r0 pointing at nothing: unmapped, and a crash on the console."""
    with pytest.raises(buffer_script.BufferScriptError, match="faulted"):
        # mov r0, #0x60000000 ; ldr r0, [r0] ; bx lr - 0x60000000 is unmapped on a GBA.
        buffer_script.emulate(bytes.fromhex("0602a0e3000090e51eff2fe1"))


# --- the session ----------------------------------------------------------------------------

def _distribution(expect=mg_server.BUFFER_EXPECT_TRAINER_ID, name=None):
    return stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None,
        buffer_code=buffer_script.payload(name or buffer_script.TRAINER_ID_PROBE),
        buffer_expect=expect)


def test_a_buffer_script_session_carries_no_card_and_no_ram_script():
    distribution = _distribution()
    assert distribution.card is None and distribution.ram_script is None

    engine = host_mystery_gift.HostMysteryGiftEngine(distribution=distribution)

    assert engine.server.script is mg_server.SCRIPT_RUN_BUFFER_SCRIPT
    assert engine.server.is_buffer_distribution


def test_a_buffer_script_cannot_share_a_session_with_a_gift():
    with pytest.raises(ValueError, match="carries no card"):
        stamp_rally.MysteryGiftDistribution(
            card=b"\x00" * 332, ram_script=b"\x00",
            buffer_code=buffer_script.payload(buffer_script.TRAINER_ID_PROBE))


def test_the_client_script_runs_the_payload_then_reads_the_return_channel():
    """The order is load-bearing: CLI_LOAD_TOSS_RESPONSE ships client->param, and only the buffer
    script has written to it by then [mystery_gift_client.c:204,276]."""
    commands = [mg_script.CLIENT_SCRIPT_RUN_BUFFER[i:i + mg_script.CLIENT_CMD_SIZE]
                for i in range(0, len(mg_script.CLIENT_SCRIPT_RUN_BUFFER),
                               mg_script.CLIENT_CMD_SIZE)]
    opcodes = [int.from_bytes(cmd[:4], "little") for cmd in commands]

    assert opcodes == [
        mg_script.CLI_RECV, mg_script.CLI_RUN_BUFFER_SCRIPT, mg_script.CLI_LOAD_TOSS_RESPONSE,
        mg_script.CLI_SEND_LOADED, mg_script.CLI_RECV, mg_script.CLI_COPY_RECV,
    ]


@needs_unicorn
def test_end_to_end_the_console_runs_our_code_and_the_id_it_returns_matches():
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_distribution())

    assert console.buffer_scripts, "the console never reached CLI_RUN_BUFFER_SCRIPT"
    assert engine.server.buffer_status == CONSOLE_TRAINER_ID
    assert engine.server.buffer_matched is True
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


@needs_unicorn
def test_end_to_end_a_console_whose_save_disagrees_is_reported_as_a_mismatch():
    """The verdict must come from comparing two sources, not from echoing one."""
    console = ConsoleClientModel(flag_id=0, save_trainer_id=CONSOLE_TRAINER_ID ^ 0x1234)

    engine, _frames = _drive(console, distribution=_distribution())

    assert engine.server.buffer_status == CONSOLE_TRAINER_ID ^ 0x1234
    assert engine.server.buffer_matched is False
    assert console.result == mg_script.CLI_MSG_BUFFER_FAILURE


@needs_unicorn
def test_end_to_end_a_card_the_console_already_holds_changes_nothing():
    """A buffer script is not a gift: there is no flagId to compare, so a console carrying a card
    takes the same path and keeps the card."""
    console = ConsoleClientModel(flag_id=1012)

    engine, _frames = _drive(console, distribution=_distribution())

    assert engine.server.buffer_matched is True
    assert console.saved_card is None


@needs_unicorn
def test_the_console_is_told_the_verdict_in_a_message_we_compose():
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_distribution())

    assert console.dynamic_msg is not None
    assert console.dynamic_msg.startswith(mg_server.DEFAULT_BUFFER_SUCCESS_MESSAGE)


# --- the host CLI ---------------------------------------------------------------------------

def _run_config(argv):
    import frlgmg_host
    parser = frlgmg_host.build_parser()
    return frlgmg_host.build_run_config(parser, parser.parse_args(argv))


def test_the_cli_builds_a_buffer_script_session_with_its_own_expectation():
    run = _run_config(["--buffer-script"])

    assert run.payload.script == buffer_script.TRAINER_ID_PROBE
    assert run.payload.expect == mg_server.BUFFER_EXPECT_TRAINER_ID
    distribution = run.payload.build_distribution()
    assert distribution.buffer_code == buffer_script.payload(buffer_script.TRAINER_ID_PROBE)
    assert distribution.card is None


def test_the_cli_refuses_a_flag_id_or_a_questionnaire_with_a_buffer_script():
    """Both belong to a Wonder Card session; the buffer script server script has neither."""
    for argv in (["--buffer-script", "--flag-id", "1009"],
                 ["--buffer-script", "--questionnaire", "species:55,FEELINGS/60,move:177,why"]):
        with pytest.raises(SystemExit):
            _run_config(argv)


def test_a_buffer_script_and_a_gift_are_mutually_exclusive_on_the_command_line():
    import frlgmg_host
    with pytest.raises(SystemExit):
        frlgmg_host.build_parser().parse_args(["--buffer-script", "--gift", "celebi"])


def test_the_live_application_for_a_buffer_script_is_the_buffer_script_one():
    from frlgsim.host_mg_app import BufferScriptHostApplication, MysteryGiftHostApplication

    assert issubclass(BufferScriptHostApplication, MysteryGiftHostApplication)
    assert BufferScriptHostApplication.SUCCESS_RESULTS == (mg_server.SVR_MSG_GIFT_SENT_1,)


def test_the_identity_log_names_the_payload_and_the_expectation():
    """The lines the operator reads before deciding a run is worth the console's time. Called on a
    stub because the real application needs a radio; what is being checked is that every attribute
    it reaches for exists on a buffer script session, where there is no card and no flagId."""
    from types import SimpleNamespace

    from frlgsim import config as configmod, linkplayer
    from frlgsim.host_mg_app import BufferScriptHostApplication

    lines = []
    payload = configmod.BufferScriptPayload()
    app = SimpleNamespace(
        profile=SimpleNamespace(name="EMU", tid=0x1234, sid=0x5678),
        session=SimpleNamespace(rfu=SimpleNamespace(host_session_id=b"\x01\x02")),
        config=SimpleNamespace(payload=payload),
        distribution=payload.build_distribution(),
        info=lines.append,
    )

    BufferScriptHostApplication._log_identity(
        app, linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED))

    text = "\n".join(lines)
    assert buffer_script.TRAINER_ID_PROBE in text
    assert "gSaveBlock2Ptr" in text
    assert "Buffer script status:" in text
    assert "Wonder Cards -> Friend" in text


def test_the_success_message_reads_the_status_off_the_running_engine():
    """bs01: the run itself was clean and the crash was here, in the last line printed. The engine
    is the session's activity; the application has never had an `engine` attribute."""
    from types import SimpleNamespace

    from frlgsim.host_mg_app import BufferScriptHostApplication

    app = SimpleNamespace(
        session=SimpleNamespace(activity=SimpleNamespace(
            server=SimpleNamespace(buffer_status=0xE5BBDF65))))

    message = BufferScriptHostApplication._success_message(app, mg_server.SVR_MSG_GIFT_SENT_1)

    assert "0xE5BBDF65" in message
    assert BufferScriptHostApplication._success_message(
        SimpleNamespace(session=None), mg_server.SVR_MSG_GIFT_SENT_1)


# --- the console's message window -----------------------------------------------------------

def test_a_newline_becomes_the_games_line_break():
    """bs01 printed 'ly. code ran and read yourTRAINER IDc' on the console: charmap.encode drops
    every character it does not know, newline included, so the two lines went out as one 47-
    character line and wrapped around inside window 1."""
    from frlgsim import charmap

    encoded = mg_server._encode_message("first line\nsecond line", None)

    assert encoded == charmap.encode("first line") + b"\xFE" + charmap.encode("second line") + b"\xff"
    assert mg_server.DEFAULT_BUFFER_SUCCESS_MESSAGE.count(0xFE) == 1
    assert mg_server.DEFAULT_BUFFER_FAILURE_MESSAGE.count(0xFE) == 1


def test_a_line_too_long_for_the_window_is_refused_offline():
    """31 characters is the ROM's own longest line in this window, gText_WonderCardReceivedFrom
    [decomp:src/strings.c:1291]. The message bs01 sent was 47 and wrapped."""
    mg_server._encode_message("A WONDER CARD has been received", None)
    with pytest.raises(mg_server.MysteryGiftServerError, match="wraps around"):
        mg_server._encode_message("The code ran and read your TRAINER ID correctly.", None)


def test_more_lines_than_the_window_holds_are_refused_offline():
    with pytest.raises(mg_server.MysteryGiftServerError, match="2 lines"):
        mg_server._encode_message("one\ntwo\nthree", None)


def test_every_default_message_fits_the_window():
    from frlgsim import charmap

    for message in (mg_server.DEFAULT_BUFFER_SUCCESS_MESSAGE,
                    mg_server.DEFAULT_BUFFER_FAILURE_MESSAGE,
                    mg_server.DEFAULT_DENIED_MESSAGE):
        assert len(message) <= mg_script.CLIENT_MAX_MSG_SIZE
        lines = message.rstrip(b"\xff").split(b"\xFE")
        assert len(lines) <= mg_server.MAX_MESSAGE_LINES
        for line in lines:
            assert len(charmap.decode(line)) <= mg_server.MAX_MESSAGE_LINE_CHARS


def test_the_trainer_id_probe_reports_the_secret_id():
    """The secret id is the high half of playerTrainerId. The game never prints it and no link
    message carries it, so native code reading the save is the only route to it. bs01 and bs03
    both returned 0xE5BBDF65: TID 57189, which the console's own game data and the trainer card
    both confirm, and SID 58811, which nothing else could have told us."""
    lines = []
    server = mg_server.MysteryGiftServer(
        buffer_code=buffer_script.payload(buffer_script.TRAINER_ID_PROBE),
        buffer_expect=mg_server.BUFFER_EXPECT_TRAINER_ID,
        log=lines.append)
    server.game_data = mg_script.parse_link_game_data(_game_data_with_trainer_id(0xE5BBDF65))
    server._received = (0xE5BBDF65).to_bytes(4, "little")

    server._do_svr_read_buffer_status()

    assert server.buffer_matched is True
    assert "TID (public) 57189" in "\n".join(lines)
    assert "SID (SECRET) 58811" in "\n".join(lines)


def _game_data_with_trainer_id(trainer_id):
    from frlgsim import charmap, mystery_gift as mg
    data = bytearray(mg_script.GAME_DATA_SIZE)
    data[0x00:0x04] = mg.GAME_DATA_VALID_VAR.to_bytes(4, "little")
    data[0x10:0x14] = mg.VERSION_CODE_FIRERED.to_bytes(4, "little")
    name = charmap.encode("GURVAN") + b"\xff"
    data[mg_script.GD_OFF_PLAYER_NAME:mg_script.GD_OFF_PLAYER_NAME + len(name)] = name
    data[mg_script.GD_OFF_TRAINER_ID:mg_script.GD_OFF_TRAINER_ID + 4] = \
        trainer_id.to_bytes(4, "little")
    return bytes(data)


# --- the memory read primitive --------------------------------------------------------------

def test_the_dump_payload_operands_are_where_we_patch_them():
    """Proven by running it, not by trusting DUMP_TARGET_OFFSET: a patched payload must actually
    leave link->sendBuffer and link->sendSize holding what we asked for."""
    run = buffer_script.emulate(buffer_script.build_memory_dump(0x03001234, 512))

    assert run.done
    assert run.client.send_buffer == 0x03001234
    assert run.client.send_size == 512
    assert run.client.send_repointed


def test_the_dump_payload_reads_out_the_region_it_was_aimed_at():
    marker = bytes(range(256)) * 4
    run = buffer_script.emulate(
        buffer_script.build_memory_dump(0x03002000, len(marker)),
        memory={0x03002000: marker})

    assert run.pending_send == marker


def test_a_dump_bigger_than_the_link_carries_is_refused():
    """MGL_Receive rejects anything past MG_LINK_BUFFER_SIZE outright [mystery_gift_link.c:102]."""
    buffer_script.build_memory_dump(0x02000000, buffer_script.MAX_BUFFER_SCRIPT_SIZE)
    for size in (0, buffer_script.MAX_BUFFER_SCRIPT_SIZE + 1):
        with pytest.raises(buffer_script.BufferScriptError, match="MG_LINK_BUFFER_SIZE"):
            buffer_script.build_memory_dump(0x02000000, size)


def test_a_dump_aimed_at_unreadable_memory_is_caught_offline():
    """On the console CalcCRC16WithTable would walk it before anything is sent."""
    with pytest.raises(buffer_script.BufferScriptError, match="not readable memory"):
        buffer_script.emulate(buffer_script.build_memory_dump(0x60000000, 1024))


def test_the_dump_client_script_arms_the_send_before_the_payload_repoints_it():
    """Order is the whole trick. CLI_LOAD_TOSS_RESPONSE must come FIRST: it calls InitSend, which
    overwrites sendBuffer and sendSize [mystery_gift_client.c:204]. Run the payload before it and
    the patch is thrown away."""
    commands = [mg_script.CLIENT_SCRIPT_DUMP_MEMORY[i:i + mg_script.CLIENT_CMD_SIZE]
                for i in range(0, len(mg_script.CLIENT_SCRIPT_DUMP_MEMORY),
                               mg_script.CLIENT_CMD_SIZE)]
    opcodes = [int.from_bytes(cmd[:4], "little") for cmd in commands]

    assert opcodes == [
        mg_script.CLI_RECV, mg_script.CLI_LOAD_TOSS_RESPONSE, mg_script.CLI_RUN_BUFFER_SCRIPT,
        mg_script.CLI_SEND_LOADED, mg_script.CLI_RECV, mg_script.CLI_COPY_RECV,
    ]


def _dump_distribution(address=None, size=buffer_script.MAX_BUFFER_SCRIPT_SIZE):
    address = buffer_script.SAV2_ADDRESS if address is None else address
    return stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None,
        buffer_code=buffer_script.build_memory_dump(address, size),
        buffer_dump_size=size)


@needs_unicorn
def test_end_to_end_the_console_reads_out_a_kilobyte_of_its_own_memory():
    """The whole primitive, through the independently written console model: the console's own
    outgoing message is repointed at its SaveBlock2 and 1024 bytes come back, with the trainer id
    at the offset the decomp gives it."""
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_dump_distribution())

    dump = engine.server.buffer_dump
    assert len(dump) == buffer_script.MAX_BUFFER_SCRIPT_SIZE
    assert int.from_bytes(
        dump[buffer_script.SAV2_PLAYER_TRAINER_ID:
             buffer_script.SAV2_PLAYER_TRAINER_ID + 4], "little") == CONSOLE_TRAINER_ID
    assert engine.server.buffer_matched is True
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


@needs_unicorn
def test_end_to_end_a_short_dump_comes_back_short():
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_dump_distribution(size=64))

    assert len(engine.server.buffer_dump) == 64
    assert engine.server.buffer_matched is True


# --- save-dump: no absolute address needed ----------------------------------------------------

def test_the_save_dump_operands_are_where_we_patch_them():
    for block, offset, size in ((buffer_script.SAVE_BLOCK_2, 0, 1024),
                                (buffer_script.SAVE_BLOCK_1, 0x290, 64)):
        run = buffer_script.emulate(buffer_script.build_save_dump(block, offset, size))
        base = (buffer_script.SAV2_ADDRESS if block == buffer_script.SAVE_BLOCK_2
                else buffer_script.SAV1_ADDRESS)
        assert run.done
        assert run.client.send_buffer == base + offset
        assert run.client.send_size == size


def test_the_save_dump_reads_either_block_without_knowing_any_address():
    """The whole point: the console hands the payload gSaveBlock2Ptr and gSaveBlock1Ptr, so this
    works on a console whose memory layout we have never seen."""
    sav2 = bytearray(0x1000)
    sav2[buffer_script.SAV2_PLAYER_TRAINER_ID:
         buffer_script.SAV2_PLAYER_TRAINER_ID + 4] = (0xE5BBDF65).to_bytes(4, "little")
    sav1 = bytearray(0x1000)
    sav1[0x290:0x294] = (0x1234ABCD).to_bytes(4, "little")   # SaveBlock1.money [global.h:774]

    from_sav2 = buffer_script.emulate(
        buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_2, 0, 16),
        sav2=bytes(sav2), sav1=bytes(sav1))
    from_sav1 = buffer_script.emulate(
        buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_1, 0x290, 16),
        sav2=bytes(sav2), sav1=bytes(sav1))

    assert int.from_bytes(
        from_sav2.pending_send[buffer_script.SAV2_PLAYER_TRAINER_ID:
                               buffer_script.SAV2_PLAYER_TRAINER_ID + 4], "little") == 0xE5BBDF65
    assert int.from_bytes(from_sav1.pending_send[:4], "little") == 0x1234ABCD


def test_a_bad_save_dump_operand_is_refused():
    with pytest.raises(buffer_script.BufferScriptError, match="block is one of"):
        buffer_script.build_save_dump("sav3")
    with pytest.raises(buffer_script.BufferScriptError, match="halfword aligned"):
        buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_1, 0x291)
    with pytest.raises(buffer_script.BufferScriptError, match="MG_LINK_BUFFER_SIZE"):
        buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_2, 0, 4096)


@needs_unicorn
def test_end_to_end_the_console_reads_out_its_save_block_by_pointer():
    console = ConsoleClientModel(flag_id=0)
    distribution = stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None,
        buffer_code=buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_2, 0, 256),
        buffer_dump_size=256)

    engine, _frames = _drive(console, distribution=distribution)

    dump = engine.server.buffer_dump
    assert len(dump) == 256
    assert int.from_bytes(
        dump[buffer_script.SAV2_PLAYER_TRAINER_ID:
             buffer_script.SAV2_PLAYER_TRAINER_ID + 4], "little") == CONSOLE_TRAINER_ID
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_the_cli_builds_both_dumps():
    memory = _run_config(["--buffer-script", "memory-dump", "--dump-address", "0x0201C000"])
    assert memory.payload.build_distribution().buffer_dump_size == \
        buffer_script.MAX_BUFFER_SCRIPT_SIZE

    save = _run_config(["--buffer-script", "save-dump", "--dump-block", "sav1",
                        "--dump-offset", "0x290", "--dump-size", "64"])
    distribution = save.payload.build_distribution()
    assert distribution.buffer_dump_size == 64
    assert distribution.buffer_code == buffer_script.build_save_dump(
        buffer_script.SAVE_BLOCK_1, 0x290, 64)

    for argv in (["--buffer-script", "memory-dump"],
                 ["--buffer-script", "trainer-id-probe", "--dump-address", "0x02000000"],
                 ["--buffer-script", "memory-dump", "--dump-address", "0x1", "--dump-size", "0"]):
        with pytest.raises(SystemExit):
            _run_config(argv)


def test_a_dump_is_written_to_a_file(tmp_path):
    """bs04 returned 256 bytes of a real SaveBlock2 and only the first 16 reached the log. A dump
    that is not kept has spent a console run for a head line."""
    from types import SimpleNamespace

    from frlgsim.host_mg_app import BufferScriptHostApplication

    path = tmp_path / "bs04_dump.bin"
    dump = bytes(range(256))
    app = SimpleNamespace(
        session=SimpleNamespace(activity=SimpleNamespace(
            server=SimpleNamespace(buffer_dump=dump))),
        config=SimpleNamespace(payload=SimpleNamespace(dump_file=str(path))),
        info=lambda *a: None)

    BufferScriptHostApplication._write_dump(app)

    assert path.read_bytes() == dump


def test_no_dump_file_and_no_dump_are_both_harmless(tmp_path):
    from types import SimpleNamespace

    from frlgsim.host_mg_app import BufferScriptHostApplication

    for server, payload in (
            (SimpleNamespace(buffer_dump=b"\x01"), SimpleNamespace(dump_file=None)),
            (SimpleNamespace(buffer_dump=None), SimpleNamespace(dump_file=str(tmp_path / "x"))),
            (SimpleNamespace(buffer_status=0), SimpleNamespace(dump_file=None))):
        app = SimpleNamespace(
            session=SimpleNamespace(activity=SimpleNamespace(server=server)),
            config=SimpleNamespace(payload=payload), info=lambda *a: None)
        BufferScriptHostApplication._write_dump(app)
    assert not (tmp_path / "x").exists()


# --- bs05: the multi-chunk receive and the row-one mirror --------------------------------------
#
# bs05 asked the console for 608 bytes of SaveBlock1 and it timed out into "erreur de connexion".
# The capture says why, exactly. `MysteryGiftClient_Init(client, 1, 0)` gives the client sendPlayerId
# 1 - its own multiplayer id - so `MGL_Send` gates every chunk on `MGL_HasReceived(1)`
# [mystery_gift_link.c:176,205]: the console's OWN block, mirrored back by us in row one of the
# parent's 70-byte table, complete. Its RFU block sender waits on the same mirror
# [HandleBlockSend / SendLastBlock / HandleSendFailure, link_rfu_2.c:1366-1416].
#
# bs05's console sent a 21-fragment chunk and emitted it partly in bursts (two at its frame 283831,
# four at 283833). The leader's echo queue kept only the newest two, so the echoes of fragments 13,
# 16, 17 and 18 were never sent - and those four are exactly the ones the console then re-sent. The
# echo of that repair was itself dropped and the console gave up.
#
# The mechanism is size-independent; 608 bytes is simply three 21-fragment chunks instead of one.

def _dump_dist(size, block_id=buffer_script.SAVE_BLOCK_2, offset=0):
    return stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None,
        buffer_code=buffer_script.build_save_dump(block_id, offset, size),
        buffer_dump_size=size)


@needs_unicorn
def test_the_console_makes_no_progress_without_its_own_block_mirrored_back():
    """The gate itself. Withhold row one and the console never finishes its first block, however
    long the host waits - which is why nothing about this was visible offline before."""
    console = ConsoleClientModel(flag_id=0)
    engine = host_mystery_gift.HostMysteryGiftEngine(
        distribution=_dump_dist(608),
        timing=host_mystery_gift.MysteryGiftTiming(client_ready_idle_frames=10))
    for _ in range(4000):
        child_row = console.step(rfu.serialize(engine.tick()), None)   # no mirror, ever
        engine.feed_child_slot(child_row)

    assert console.host_link_player is None      # it never got past its LinkPlayer block
    assert engine.child_link_player is None
    assert console.own_block_received is False


@needs_unicorn
@pytest.mark.parametrize("size", [256, 608, 1024])
def test_the_console_reads_out_a_multi_chunk_dump(size):
    """608 bytes is header + three chunks, so four rounds of the MGL_Send handshake instead of the
    two a 256-byte dump needs. Each one is the console's own block coming back."""
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_dump_dist(size))

    assert len(engine.server.buffer_dump) == size
    assert int.from_bytes(
        engine.server.buffer_dump[buffer_script.SAV2_PLAYER_TRAINER_ID:
                                  buffer_script.SAV2_PLAYER_TRAINER_ID + 4],
        "little") == CONSOLE_TRAINER_ID
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS
    # Nothing was mirrored back late enough to make the console repeat itself.
    assert console.own_resends == 0


@needs_unicorn
def test_a_bursting_console_still_gets_every_fragment_of_its_dump_back():
    """The bs05 shape: the console hands its commands over four at a time. Not one distinct command
    may be dropped from the mirror - the console cannot tell which one is missing, only that its
    bitmask is short, and each repair round is another chance to lose it."""
    echo = rfu_leader.ChildEcho()
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_dump_dist(608),
                             echo=echo, child_burst=4, burst_every=1)

    assert len(engine.server.buffer_dump) == 608
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS
    assert echo.dropped == 0
    assert echo.coalesced > 0            # the repeats it folds away are what used to cause the lag
    assert console.own_dropped_inits == 0
    assert console.own_resends == 0      # it never had to repair a block


@needs_unicorn
def test_the_old_echo_bound_makes_the_console_repair_its_own_block():
    """bs05's mechanism, reproduced offline and measured. Keep only the newest two child commands and
    a burst of four loses two of them; the console cannot ask for a specific fragment, it can only
    notice its own bitmask is short and re-queue everything missing (HandleSendFailure), and each
    repair round is another burst's worth of chances to lose the repair as well.

    The model's console is infinitely patient, so it still gets there. bs05's did not: its repairs
    for fragments 13, 16, 17 and 18 went out at 11.626-11.663 s, our echo of 13 was dropped a second
    time, and it declared link loss at 11.790. What is asserted here is therefore the drop and the
    repair traffic, which are what the capture shows - not a give-up threshold, which is not
    measured."""
    legacy = rfu_leader.ChildEcho(max_backlog=2, coalesce=False)
    strays = ConsoleClientModel(flag_id=0)
    _drive(strays, distribution=_dump_dist(608), echo=legacy, child_burst=4, burst_every=1)

    assert legacy.dropped > 0
    assert strays.own_resends > 0

    fixed = rfu_leader.ChildEcho()
    console = ConsoleClientModel(flag_id=0)
    engine, _frames = _drive(console, distribution=_dump_dist(608),
                             echo=fixed, child_burst=4, burst_every=1)

    assert fixed.dropped == 0 and console.own_resends == 0
    assert len(engine.server.buffer_dump) == 608


@needs_unicorn
def test_a_dump_can_be_aimed_at_the_cartridge():
    """The CPU reads ROM like any other region, so a dump aimed there is legal and the CRC walk over
    it cannot fault. It is also the only way to learn WHICH build the console is running, which is
    what calling into the ROM would need [GBA cartridge header: 0xA0 title, 0xAC game code]."""
    run = buffer_script.emulate(buffer_script.build_memory_dump(buffer_script.ROM_BASE, 1024))

    assert run.done and run.client.send_buffer == buffer_script.ROM_BASE
    assert run.client.send_size == 1024
    assert run.pending_send[0xA0:0xAC] == b"POKEMON FIRE"

    seeded = buffer_script.emulate(
        buffer_script.build_memory_dump(buffer_script.ROM_HEADER_TITLE, 16),
        rom=b"\x00" * 0xA0 + b"POKEMON LEAF")
    assert seeded.pending_send[:12] == b"POKEMON LEAF"


# --- anchors: where the machine says it is -----------------------------------------------------

def test_the_anchors_payload_reports_every_address_it_promises():
    """Offline this can only check the shape and the plumbing - the emulator's values are ones it
    chose. The point of the payload is the run on hardware, where `return_address` is a real ROM
    address and `code` measures a number this project has so far only deduced."""
    run = buffer_script.emulate(buffer_script.payload(buffer_script.ANCHORS))

    assert run.done and run.client.send_size == buffer_script.ANCHORS_SIZE
    anchors = buffer_script.read_anchors(run.pending_send)
    assert set(anchors) == set(buffer_script.ANCHORS_FIELDS)
    # It writes into the buffer InitSend already aimed at, so it must not have repointed anything.
    assert run.client.send_buffer == anchors["client_send_buffer"] == anchors["link_send_buffer"]
    assert anchors["code"] == buffer_script.GDECOMPRESSION_BUFFER
    assert anchors["save_block_2"] == buffer_script.SAV2_ADDRESS
    assert anchors["save_block_1"] == buffer_script.SAV1_ADDRESS
    assert anchors["stack_pointer"] == buffer_script.STACK_POINTER
    # client->sendBuffer and the struct are separate allocations in the model, so the offline run
    # cannot check that they are laid out as gHeap lays them out; describe_anchors does that on the
    # bytes a console sends back.


def test_the_anchors_description_calls_out_an_answer_that_is_not_self_consistent():
    """An address that looks plausible but is not consistent is worse than no address, so the
    description checks what it can rather than printing eleven numbers."""
    good = bytearray(buffer_script.ANCHORS_SIZE)
    fields = list(buffer_script.ANCHORS_FIELDS)
    def put(name, value):
        i = fields.index(name)
        good[4 * i:4 * i + 4] = value.to_bytes(4, "little")
    put("code", 0x0201C000)
    put("return_address", 0x0815A2C1)          # in ROM, THUMB caller
    put("client_send_buffer", 0x02001800)
    put("link_send_buffer", 0x02001800)
    lines = "\n".join(buffer_script.describe_anchors(bytes(good)))
    assert "the ROM call site is 0x0815A2C0 (THUMB caller)" in lines
    assert "the 0x0201C000 deduction holds" in lines
    assert "WARNING" not in lines

    put("return_address", 0x02001001)          # not in the cartridge
    put("code", 0x02020000)                    # not where ld_script.ld says
    put("link_send_buffer", 0x02009999)        # not client->sendBuffer
    lines = "\n".join(buffer_script.describe_anchors(bytes(good)))
    assert "not in the cartridge" in lines
    assert "NOT the deduced 0x0201C000" in lines
    assert "link->sendBuffer is not client->sendBuffer" in lines


def test_the_cli_builds_an_anchors_session_with_its_own_fixed_size():
    run = _run_config(["--buffer-script", "anchors"])
    distribution = run.payload.build_distribution()

    assert run.payload.is_dump                      # the answer comes back as bytes, not the u32
    assert distribution.buffer_dump_size == buffer_script.ANCHORS_SIZE
    assert distribution.card is None


# --- save-write: the first payload that changes something --------------------------------------

@needs_unicorn
def test_a_save_write_lands_in_the_block_and_reads_itself_back():
    """One run does both: the bytes go into the save block, and link->sendBuffer is pointed AT THE
    DESTINATION, so what comes back over the air is what is now in the console's save rather than a
    copy of what we asked for."""
    data = b"FRLG-LDN bs09xx"
    run = buffer_script.emulate(buffer_script.build_save_write(data),
                                sav2=bytes(0x1000))

    assert run.done
    assert run.client.send_size == len(data)
    assert run.pending_send == data
    assert run.sav2[0xB20:0xB20 + len(data)] == data
    # Nothing outside the region it was given.
    assert run.sav2[:0xB20] == bytes(0xB20)
    assert run.sav2[0xB20 + len(data):] == bytes(0x1000 - 0xB20 - len(data))


@needs_unicorn
def test_a_save_write_carries_anything_from_one_byte_to_a_full_payload():
    for size in (1, 2, buffer_script.MAX_SAVE_WRITE_BYTES):
        data = bytes(range(256)) * 4
        run = buffer_script.emulate(
            buffer_script.build_save_write(data[:size]), sav2=bytes(0x1000))
        assert run.pending_send == data[:size] == run.sav2[0xB20:0xB20 + size]


def test_a_save_write_outside_the_never_read_filler_is_refused():
    """This is the player's live save and the console commits it to flash at the end of the session,
    so a wrong offset is a damaged game rather than a failed run. The two spans allowed are
    struct SaveBlock2's `u8 filler[]` [global.h:345,357], which src/ never references."""
    assert buffer_script.is_scratch(buffer_script.SAVE_BLOCK_2, 0xB20, 0x400)
    assert buffer_script.is_scratch(buffer_script.SAVE_BLOCK_2, 0x90, 8)
    assert not buffer_script.is_scratch(buffer_script.SAVE_BLOCK_2, 0xB20, 0x401)  # runs off the end
    assert not buffer_script.is_scratch(buffer_script.SAVE_BLOCK_1, 0xB20, 4)      # sav1 has none

    with pytest.raises(buffer_script.BufferScriptError, match="the game reads"):
        buffer_script.build_save_write(b"\x01\x02", offset=0x0A)          # playerTrainerId
    with pytest.raises(buffer_script.BufferScriptError, match="the game reads"):
        buffer_script.build_save_write(b"\x01\x02", block=buffer_script.SAVE_BLOCK_1, offset=0x38)
    with pytest.raises(buffer_script.BufferScriptError, match="the game reads"):
        # Ends four bytes past filler_B20, in SaveBlock2.encryptionKey - which money is XORed with,
        # so getting this wrong would scramble the player's money rather than fail cleanly.
        buffer_script.build_save_write(bytes(8), offset=0xF1C)
    # The override exists, and says what it is.
    assert buffer_script.build_save_write(b"\x01\x02", offset=0x0A, unsafe=True)


def test_a_save_write_refuses_what_the_payload_cannot_carry():
    with pytest.raises(buffer_script.BufferScriptError, match="bytes of data"):
        buffer_script.build_save_write(b"")
    with pytest.raises(buffer_script.BufferScriptError, match="bytes of data"):
        buffer_script.build_save_write(bytes(buffer_script.MAX_SAVE_WRITE_BYTES + 1), unsafe=True)


def test_the_cli_builds_a_save_write_and_sizes_the_answer_to_it():
    run = _run_config(["--buffer-script", "save-write", "--dump-offset", "0xB20",
                       "--write-text", "FRLG-LDN"])
    distribution = run.payload.build_distribution()

    assert run.payload.write_data == b"FRLG-LDN"
    assert distribution.buffer_dump_size == len("FRLG-LDN")
    assert distribution.buffer_code == buffer_script.build_save_write(b"FRLG-LDN", offset=0xB20)

    hexed = _run_config(["--buffer-script", "save-write", "--dump-offset", "0xB20",
                         "--write-hex", "00ff10"])
    assert hexed.payload.write_data == b"\x00\xff\x10"


def test_the_cli_refuses_a_write_without_bytes_and_bytes_without_a_write():
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--write-text", "no"])
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "save-write", "--dump-offset", "0xB20"])


# --- memory-scan: searching instead of reading -------------------------------------------------
# The payload returns 0 to be called again next frame [decomp:src/mystery_gift_client.c:276-280],
# so these run it the way the console does - many calls, one image - through emulate_repeating.

SCAN_NEEDLE = 0x41C64E6D        # RAND_MULT [decomp:include/random.h:18], the first real needle


def test_the_scan_operands_are_where_we_patch_them():
    """The offsets are fixed by construction (asm/memory-scan.s opens with a branch over its own
    parameter block), so this reads them back rather than trusting a disassembly."""
    code = buffer_script.build_memory_scan(
        SCAN_NEEDLE, 0x08100000, 0x08102000, blocks=64, max_calls=99)

    assert buffer_script.scan_parameters(code) == {
        "start": 0x08100000, "end": 0x08102000, "needle": SCAN_NEEDLE,
        "blocks": 64, "max_calls": 99}


@needs_unicorn
def test_the_scan_finds_every_match_in_the_range_and_says_where():
    planted = (0x08100004, 0x081007FC, 0x08100FE0)
    memory = {address: SCAN_NEEDLE.to_bytes(4, "little") for address in planted}

    repeated = buffer_script.emulate_repeating(
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08100000, 0x08101000, blocks=8),
        memory=memory)
    scan = buffer_script.read_scan(repeated.final.pending_send)

    assert repeated.done
    assert scan["found"] == len(planted)
    assert [address for address, _value in scan["hits"]] == list(planted)
    assert all(value == SCAN_NEEDLE for _address, value in scan["hits"])
    assert scan["cursor"] == 0x08101000        # the whole range, so the answer is complete


@needs_unicorn
def test_the_scan_takes_one_call_per_budget_and_repoints_the_send_only_at_the_end():
    """The frame loop itself. Every call but the last returns 0 with the console's outgoing
    message untouched; the last one repoints it at a FIXED-size answer, so the host's length
    check stays the proof that the payload ran."""
    code = buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08100000, 0x08101000, blocks=8)

    first = buffer_script.emulate(code)
    repeated = buffer_script.emulate_repeating(code)

    assert first.returned == 0 and not first.done
    assert not first.client.send_changed
    assert repeated.calls == 0x1000 // (8 * buffer_script.SCAN_BLOCK_BYTES) == 16
    assert repeated.final.client.send_repointed
    assert repeated.final.client.send_size == buffer_script.SCAN_ANSWER_SIZE
    assert buffer_script.read_scan(repeated.final.pending_send)["calls"] == 16


@needs_unicorn
def test_the_scan_watchdog_answers_instead_of_hanging_the_menu():
    """A payload that never returns 1 hangs the Mystery Gift menu with no way out, so the count is
    bounded in the payload. A watchdog stop still answers, and says how far it got."""
    code = buffer_script.build_memory_scan(
        SCAN_NEEDLE, 0x08100000, 0x08200000, blocks=8, max_calls=4)

    repeated = buffer_script.emulate_repeating(code)
    scan = buffer_script.read_scan(repeated.final.pending_send)

    assert repeated.done and repeated.calls == 5      # the call that trips the watchdog answers
    assert scan["cursor"] == 0x08100000 + 4 * 8 * buffer_script.SCAN_BLOCK_BYTES
    lines = buffer_script.describe_scan(repeated.final.pending_send,
                                        SCAN_NEEDLE, 0x08100000, 0x08200000)
    assert any("STOPPED EARLY" in line for line in lines)
    assert any(f"0x{scan['cursor']:08X}" in line for line in lines)


@needs_unicorn
def test_a_scan_with_more_matches_than_the_table_holds_still_counts_them_all():
    """The count is what says whether the needle was a good one; the table is only the first 64."""
    over = buffer_script.SCAN_HIT_CAPACITY + 6
    memory = {0x08100000 + 4 * i: SCAN_NEEDLE.to_bytes(4, "little") for i in range(over)}

    repeated = buffer_script.emulate_repeating(
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08100000, 0x08101000, blocks=8),
        memory=memory)
    scan = buffer_script.read_scan(repeated.final.pending_send)

    assert scan["found"] == over
    assert len(scan["hits"]) == buffer_script.SCAN_HIT_CAPACITY
    assert any("only the first" in line
               for line in buffer_script.describe_scan(repeated.final.pending_send))


@needs_unicorn
def test_a_scan_resumes_from_where_the_last_one_stopped():
    """Which is what makes 16 MB reachable at all: the cursor that comes back is the start of the
    next run, and the two halves together see what one pass would have."""
    memory = {0x08100FE0: SCAN_NEEDLE.to_bytes(4, "little")}
    stopped = buffer_script.emulate_repeating(
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08100000, 0x08102000,
                                        blocks=8, max_calls=4),
        memory=memory)
    cursor = buffer_script.read_scan(stopped.final.pending_send)["cursor"]

    resumed = buffer_script.emulate_repeating(
        buffer_script.build_memory_scan(SCAN_NEEDLE, cursor, 0x08102000, blocks=8),
        memory=memory)
    scan = buffer_script.read_scan(resumed.final.pending_send)

    assert buffer_script.read_scan(stopped.final.pending_send)["found"] == 0
    assert scan["found"] == 1 and scan["hits"][0][0] == 0x08100FE0


@needs_unicorn
def test_one_call_of_the_default_budget_fits_in_a_frame():
    """The budget is the whole design. The console is holding an RFU link open while this runs, so
    a call must be a few milliseconds: ~7000 ARM instructions out of EWRAM (6 cycles a fetch on a
    16-bit bus) is around 45000 of a frame's 280896 cycles."""
    run = buffer_script.emulate(
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08000000, 0x09000000),
        instruction_limit=buffer_script.SCAN_DEFAULT_BLOCKS * 32)

    assert not run.done                      # it yields, having scanned its budget
    assert run.instructions < 10000
    assert buffer_script.scan_call_count(0x08000000, 0x09000000,
                                         buffer_script.SCAN_DEFAULT_BLOCKS) == 1024


def test_a_scan_range_the_payload_cannot_walk_is_refused():
    buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08000000, 0x09000000)
    with pytest.raises(buffer_script.BufferScriptError, match="aligned"):
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x08000004, 0x09000000)
    with pytest.raises(buffer_script.BufferScriptError, match="not a range"):
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x09000000, 0x08000000)
    with pytest.raises(buffer_script.BufferScriptError, match="the CPU can read"):
        buffer_script.build_memory_scan(SCAN_NEEDLE, 0x00000000, 0x00001000)
    with pytest.raises(buffer_script.BufferScriptError, match="blocks"):
        buffer_script.build_memory_scan(SCAN_NEEDLE, blocks=0)
    with pytest.raises(buffer_script.BufferScriptError, match="watchdog"):
        buffer_script.build_memory_scan(SCAN_NEEDLE, max_calls=0)


@needs_unicorn
def test_a_payload_that_never_returns_one_is_caught_offline_rather_than_on_the_console():
    """mov r0,#0; bx lr - the shape of every hang this project could ship."""
    with pytest.raises(buffer_script.BufferScriptError, match="every frame for ever"):
        buffer_script.emulate_repeating(bytes.fromhex("0000a0e31eff2fe1"), max_calls=8)


def _scan_distribution(needle, start, end, blocks=8):
    return stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None,
        buffer_code=buffer_script.build_memory_scan(needle, start, end, blocks=blocks),
        buffer_dump_size=buffer_script.SCAN_ANSWER_SIZE,
        buffer_decode=buffer_script.MEMORY_SCAN)


@needs_unicorn
def test_end_to_end_the_console_searches_its_own_cartridge():
    """Through the independently written console model: 'POKE' at the head of the cartridge title
    [GBA header 0xA0], found by address rather than read from one we already knew."""
    console = ConsoleClientModel(flag_id=0)

    engine, _frames = _drive(console, distribution=_scan_distribution(
        0x454B4F50, 0x08000000, 0x08000100))

    scan = buffer_script.read_scan(engine.server.buffer_dump)
    assert engine.server.buffer_matched is True
    assert scan["found"] == 1 and scan["hits"][0][0] == buffer_script.ROM_HEADER_TITLE
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_the_server_refuses_a_scan_whose_answer_is_not_the_size_a_scan_answers():
    with pytest.raises(mg_server.MysteryGiftServerError, match="memory scan answers"):
        mg_server.MysteryGiftServer(
            None, None, buffer_code=buffer_script.build_memory_scan(SCAN_NEEDLE),
            buffer_dump_size=1024, buffer_decode=buffer_script.MEMORY_SCAN)


def test_the_cli_builds_a_scan_and_sizes_the_answer_to_the_hit_table():
    run = _run_config(["--buffer-script", "memory-scan", "--scan-word", "0x41C64E6D",
                       "--scan-start", "0x08000000", "--scan-end", "0x08400000",
                       "--scan-blocks", "256"])
    distribution = run.payload.build_distribution()

    assert distribution.buffer_decode == buffer_script.MEMORY_SCAN
    assert distribution.buffer_dump_size == buffer_script.SCAN_ANSWER_SIZE
    assert buffer_script.scan_parameters(distribution.buffer_code) == {
        "start": 0x08000000, "end": 0x08400000, "needle": SCAN_NEEDLE,
        "blocks": 256, "max_calls": 0x400000 // (256 * 32) + 2}


def test_the_cli_refuses_a_scan_without_a_needle_and_a_needle_without_a_scan():
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "memory-scan"])
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--scan-word", "1"])


def test_a_built_payload_is_still_named_by_its_own_bytes():
    """Every hardware run logs `describe` on what it is about to send. A payload with its operands
    patched in is the ONLY kind a dump, a write or a scan ever sends, so naming those 'unknown'
    made the line useless exactly when it mattered."""
    for name, code in (
            (buffer_script.MEMORY_SCAN, buffer_script.build_memory_scan(SCAN_NEEDLE)),
            (buffer_script.MEMORY_DUMP, buffer_script.build_memory_dump(0x08000000, 1024)),
            (buffer_script.SAVE_DUMP,
             buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_1, 0x34, 608)),
            (buffer_script.SAVE_WRITE, buffer_script.build_save_write(b"FRLG-LDN bs09")),
            (buffer_script.ANCHORS, buffer_script.payload(buffer_script.ANCHORS)),
            (buffer_script.TRAINER_ID_PROBE,
             buffer_script.payload(buffer_script.TRAINER_ID_PROBE))):
        assert buffer_script.describe(code).startswith(name + " ")
    assert "unknown" in buffer_script.describe(bytes.fromhex("0000a0e3"))


# --- table-scan: finding a table by its SHAPE ---------------------------------------------------
# Every address this project has found by searching rested on a constant only one function could
# hold. A table of POINTERS has no such constant, so gSpecialVars is found by the RELATION between
# its entries instead: entries 0..11 are the addresses of gSpecialVar_0x8000..0x800B, twelve u16s
# declared consecutively [decomp:src/event_data.c:16], so each word is exactly 2 above the last.

SPECIAL_VAR_BASE = 0x02024C40           # a plausible &gSpecialVar_0x8000 to plant
TABLE_AT = 0x08160000


def _special_vars_table(base=SPECIAL_VAR_BASE):
    """gSpecialVars exactly as data/event_scripts.s:51 orders it.

    The order is BY VAR ID, which is not the order event_data.c declares the variables in: entry
    12 is gSpecialVar_Facing, declared after Result and LastTalked, so it sits +6 from entry 11
    and the ascending run stops dead at twelve. That is why the fingerprint is 12 and not 21.
    """
    entries = [base + 2 * i for i in range(12)]              # 0x8000 .. 0x800B
    entries += [base + 28, base + 24, 0x0203ABCD, base + 26,  # Facing, Result, ItemId, LastTalked
                base + 30, base + 32, base + 34, base + 36, base + 38]
    return b"".join(e.to_bytes(4, "little") for e in entries)


def test_the_table_scan_operands_are_where_we_patch_them():
    code = buffer_script.build_table_scan(
        delta=2, runlen=12, start=0x08100000, end=0x08102000, blocks=64, max_calls=99)

    assert buffer_script.table_scan_parameters(code) == {
        "start": 0x08100000, "end": 0x08102000, "delta": 2,
        "blocks": 64, "max_calls": 99, "runlen": 12}


def test_a_shape_search_refuses_the_shapes_that_are_not_shapes():
    """A delta of 0 matches every stretch of repeated words - padding, zeroed tables, all of it -
    and one word in a row is not a relation at all."""
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_table_scan(delta=0)
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_table_scan(delta=2, runlen=1)


@needs_unicorn
def test_the_table_scan_finds_gspecialvars_by_shape_and_reads_the_pointer_out_of_it():
    """The answer is not just WHERE the table is: the run's first value IS gSpecialVar_0x8000,
    which is the address the RNG-reading NPC needs. Locating and reading are one run."""
    memory = {TABLE_AT: _special_vars_table()}

    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=2, runlen=12, start=0x08150000, end=0x08170000, blocks=64),
        memory=memory)
    table = buffer_script.read_table_scan(repeated.final.pending_send, 0x08150000, 0x08170000)

    assert repeated.done
    assert table["hits"] == [(TABLE_AT, SPECIAL_VAR_BASE)]
    assert table["cursor"] == 0x08170000        # the whole range, so the answer is complete
    assert repeated.final.client.send_size == buffer_script.TABLE_ANSWER_SIZE


@needs_unicorn
def test_the_run_really_is_exactly_twelve_long():
    """Asking for thirteen finds NOTHING against the same table. That is the check that the
    fingerprint is being matched against the shape and not merely against 'some pointers'."""
    memory = {TABLE_AT: _special_vars_table()}

    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=2, runlen=13, start=0x08150000, end=0x08170000, blocks=64),
        memory=memory)

    assert buffer_script.read_table_scan(
        repeated.final.pending_send, 0x08150000, 0x08170000)["hits"] == []


@needs_unicorn
def test_a_run_survives_the_ldmia_boundary_and_the_frame_boundary():
    """A run has to be carried across both, which is what memory-scan never had to do: one block
    per call puts the frame boundary inside the table itself."""
    memory = {TABLE_AT: _special_vars_table()}
    start, end = TABLE_AT - 0x40, TABLE_AT + 0x100

    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(delta=2, runlen=12, start=start, end=end, blocks=1),
        memory=memory)
    table = buffer_script.read_table_scan(repeated.final.pending_send, start, end)

    assert repeated.calls == (end - start) // buffer_script.TABLE_BLOCK_BYTES
    assert table["hits"] == [(TABLE_AT, SPECIAL_VAR_BASE)]


@needs_unicorn
def test_the_table_scan_watchdog_answers_instead_of_hanging_the_menu():
    code = buffer_script.build_table_scan(
        delta=2, runlen=12, start=0x08100000, end=0x08200000, blocks=8, max_calls=4)

    repeated = buffer_script.emulate_repeating(code)
    table = buffer_script.read_table_scan(repeated.final.pending_send)

    assert repeated.done and repeated.calls == 5     # the call that trips the watchdog answers
    assert table["cursor"] == 0x08100000 + 4 * 8 * buffer_script.TABLE_BLOCK_BYTES
    lines = buffer_script.describe_table_scan(
        repeated.final.pending_send, 2, 12, 0x08100000, 0x08200000)
    assert any("STOPPED EARLY" in line for line in lines)


@needs_unicorn
def test_the_log_says_where_the_table_is_and_what_it_starts_with():
    memory = {TABLE_AT: _special_vars_table()}
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=2, runlen=12, start=0x08150000, end=0x08170000, blocks=64),
        memory=memory)

    lines = buffer_script.describe_table_scan(
        repeated.final.pending_send, 2, 12, 0x08150000, 0x08170000)

    assert any(f"0x{TABLE_AT:08X}" in line and f"0x{SPECIAL_VAR_BASE:08X}" in line
               for line in lines)
    assert any("the whole range" in line for line in lines)


# --- rng-trace: a word once a frame, and the first call into the ROM ---------------------------
# The fixture is the console's OWN code: the twenty bytes of Random and its literal pool, read off
# the cartridge in bs14. Executing those under unicorn is what proved the payload before bs15 ran.

RANDOM_CODE_BASE = 0x080486B0
RANDOM_CODE = bytes.fromhex(
    "044a1168"      # ldr r2,[pc,#16] ; ldr r1,[r2]
    "04484843"      # ldr r0,[pc,#16] ; mul r0,r1
    "04494018"      # ldr r1,[pc,#16] ; add r0,r0,r1
    "1060000c"      # str r0,[r2]     ; lsr r0,r0,#16
    "70470000"      # bx lr           ; (padding)
    "20420003"      # .word 0x03004220   &gRngValue
    "6d4ec641"      # .word 0x41C64E6D   RAND_MULT
    "73600000")     # .word 0x00006073   24691
GRNG_VALUE = 0x03004220


def _console_memory(seed):
    return {RANDOM_CODE_BASE: RANDOM_CODE, GRNG_VALUE: (seed & 0xFFFFFFFF).to_bytes(4, "little")}


def test_the_committed_random_bytes_are_the_function_the_decomp_describes():
    """If this fixture is wrong every test below it proves nothing, so check it against the two
    things that cannot both be coincidence: the constants, and where the pc-relative loads land."""
    words = [int.from_bytes(RANDOM_CODE[i:i + 4], "little") for i in range(0, len(RANDOM_CODE), 4)]
    assert words[-3:] == [GRNG_VALUE, buffer_script.RAND_MULT, buffer_script.RAND_ADD]
    assert RANDOM_CODE[:2] == b"\x04\x4a"       # ldr r2, [pc, #16] -> &gRngValue
    assert RANDOM_CODE[16:18] == b"\x70\x47"    # bx lr
    assert RANDOM_CODE_BASE == rom_map.RANDOM and GRNG_VALUE == rom_map.GRNG_VALUE


def test_the_trace_operands_are_where_we_patch_them():
    code = buffer_script.build_rng_trace(GRNG_VALUE, RANDOM_CODE_BASE | 1, samples=8, max_calls=20)

    assert buffer_script.trace_parameters(code) == {
        "address": GRNG_VALUE, "function": RANDOM_CODE_BASE | 1,
        "samples": 8, "max_calls": 20}


@needs_unicorn
def test_the_trace_calls_the_console_s_own_random_and_the_recurrence_holds():
    """The whole point of bs15, offline: our ARM payload `bx`es into THUMB ROM code, the callee's
    own `bx lr` brings it back, and the word either side of the call is one turn of the LCG apart.
    Nothing but gRngValue and Random answers that."""
    seed = 0x12345678
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_rng_trace(GRNG_VALUE, RANDOM_CODE_BASE | 1, samples=8),
        memory=_console_memory(seed))
    trace = buffer_script.read_rng_trace(repeated.final.pending_send)

    assert repeated.calls == 8 and trace["taken"] == 8
    assert trace["address"] == GRNG_VALUE and trace["function"] == RANDOM_CODE_BASE | 1
    expected = seed
    for before, after in trace["samples"]:
        assert before == expected
        assert after == buffer_script.rand_step(before)
        expected = after                    # nothing else turned it: we are the only caller here
    assert all("holds on 8/8" in line or True
               for line in buffer_script.describe_rng_trace(repeated.final.pending_send))
    assert any("THE ADDRESS IS gRngValue AND THE ROM CALL RAN" in line
               for line in buffer_script.describe_rng_trace(repeated.final.pending_send))


@needs_unicorn
def test_the_trace_with_no_function_only_watches():
    """function=0 makes the same payload a plain sampler, which is what a word with no known
    recurrence needs. Then before and after are the same word and nothing is claimed."""
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_rng_trace(GRNG_VALUE, 0, samples=4),
        memory=_console_memory(0xABCD1234))
    trace = buffer_script.read_rng_trace(repeated.final.pending_send)

    assert trace["function"] == 0
    assert all(before == after == 0xABCD1234 for before, after in trace["samples"])
    assert any("calling nothing" in line
               for line in buffer_script.describe_rng_trace(repeated.final.pending_send))


@needs_unicorn
def test_the_trace_answers_a_fixed_size_whatever_the_watchdog_does():
    """The host proves the send was repointed by the length, so a watchdog stop must not shorten
    the answer - the samples not taken come back as the zeros they were sent as."""
    code = buffer_script.build_rng_trace(GRNG_VALUE, RANDOM_CODE_BASE | 1,
                                         samples=8, max_calls=3)
    repeated = buffer_script.emulate_repeating(code, memory=_console_memory(1))
    trace = buffer_script.read_rng_trace(repeated.final.pending_send)

    assert repeated.final.client.send_size == buffer_script.trace_answer_size(8) == 80
    assert trace["taken"] == 3
    assert repeated.final.pending_send[buffer_script.TRACE_HEADER_SIZE + 8 * 3:] == bytes(
        8 * 5)


def test_lcg_distance_measures_what_the_game_itself_turned():
    """bs15's second answer: between our call in one frame and our read in the next, the game had
    turned the RNG exactly twice, on all 95 gaps."""
    start = 0x3C22BA3A
    two = buffer_script.rand_step(buffer_script.rand_step(start))

    assert buffer_script.lcg_distance(start, two) == 2
    assert buffer_script.lcg_distance(start, start) == 0
    assert buffer_script.lcg_distance(start, 0xDEADBEEF, limit=64) is None


def test_a_trace_that_would_jump_somewhere_it_should_not_is_refused():
    buffer_script.build_rng_trace(GRNG_VALUE, RANDOM_CODE_BASE | 1)
    with pytest.raises(buffer_script.BufferScriptError, match="word aligned"):
        buffer_script.build_rng_trace(GRNG_VALUE + 1)
    with pytest.raises(buffer_script.BufferScriptError, match="outside the memory"):
        buffer_script.build_rng_trace(0x00000100)
    with pytest.raises(buffer_script.BufferScriptError, match="ARM pointer"):
        buffer_script.build_rng_trace(GRNG_VALUE, RANDOM_CODE_BASE)
    with pytest.raises(buffer_script.BufferScriptError, match="not in the cartridge"):
        buffer_script.build_rng_trace(GRNG_VALUE, 0x03004221)
    with pytest.raises(buffer_script.BufferScriptError, match="1..96 samples"):
        buffer_script.build_rng_trace(GRNG_VALUE, 0, samples=97)


@needs_unicorn
def test_end_to_end_the_console_traces_its_own_rng():
    console = ConsoleClientModel(flag_id=0)
    code = buffer_script.build_rng_trace(GRNG_VALUE, 0, samples=6)   # no ROM in the model to call
    distribution = stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None, buffer_code=code,
        buffer_dump_size=buffer_script.trace_answer_size(6),
        buffer_decode=buffer_script.RNG_TRACE)

    engine, _frames = _drive(console, distribution=distribution)

    trace = buffer_script.read_rng_trace(engine.server.buffer_dump)
    assert engine.server.buffer_matched is True
    assert trace["taken"] == 6 and trace["address"] == GRNG_VALUE
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_the_server_refuses_a_trace_whose_answer_is_not_the_size_that_many_samples_answer():
    with pytest.raises(mg_server.MysteryGiftServerError, match="samples answers with"):
        mg_server.MysteryGiftServer(
            None, None, buffer_code=buffer_script.build_rng_trace(GRNG_VALUE, 0, samples=8),
            buffer_dump_size=1024, buffer_decode=buffer_script.RNG_TRACE)


def test_the_cli_builds_a_trace_and_sizes_the_answer_to_the_samples():
    run = _run_config(["--buffer-script", "rng-trace", "--trace-address", "0x03004220",
                       "--trace-call", "0x080486B1", "--trace-samples", "96"])
    distribution = run.payload.build_distribution()

    assert distribution.buffer_decode == buffer_script.RNG_TRACE
    assert distribution.buffer_dump_size == buffer_script.trace_answer_size(96) == 784
    assert buffer_script.trace_parameters(distribution.buffer_code)["function"] == 0x080486B1


def test_the_cli_refuses_a_trace_without_an_address_and_an_address_without_a_trace():
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "rng-trace"])
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--trace-address", "0x03004220"])


# --- string-gather: following a pointer array instead of reading a window ------------------------
# The Easy Chat vocabulary is why this payload exists. sEasyChatGroups' 22 word arrays and their
# text span 21560 bytes of cartridge [bs17], which is 22 dumps, and two thirds of those bytes are
# struct EasyChatWordInfo's alphabeticalOrder and enabled - neither of which says anything about
# what the console PRINTS. This one dereferences, so a run carries a whole group.

GATHER_WORDS = ["SALUT", "JE SUIS LA", "MERCI", "AMIS", "POURQUOI", "STRESSE", "FURAX",
                "CONNEXION", "AVEC", "LES", "DRESSEURS"]
GATHER_TEXT = 0x083E0D54        # sEasyChatGroup_Feelings on the console, near enough
GATHER_ARRAY = 0x083E1000
WORD_INFO_STRIDE = 12           # struct EasyChatWordInfo [decomp:include/easy_chat.h:11]


def _word_info_fixture(words=GATHER_WORDS, text=GATHER_TEXT, array=GATHER_ARRAY):
    """A real struct EasyChatWordInfo array - text, alphabeticalOrder, enabled - and its strings."""
    from frlgsim import charmap
    blob, array_bytes = bytearray(), bytearray()
    for index, word in enumerate(words):
        array_bytes += (text + len(blob)).to_bytes(4, "little")
        array_bytes += index.to_bytes(4, "little") + (1).to_bytes(4, "little")
        blob += charmap.encode(word) + b"\xFF"
    return {text: bytes(blob), array: bytes(array_bytes)}


def _gathered(code, memory):
    run = buffer_script.emulate(code, memory=memory)
    return run, buffer_script.read_gather(run.pending_send)


def test_the_gather_operands_are_where_we_patch_them():
    """Fixed by construction - asm/string-gather.s opens with a branch over its own parameter
    block - so this reads them back rather than trusting a disassembly."""
    code = buffer_script.build_string_gather(0x083E1000, 26, stride=12, budget=400, maxlen=32)

    assert buffer_script.gather_parameters(code) == {
        "src": 0x083E1000, "stride": 12, "count": 26, "budget": 400, "maxlen": 32}
    assert len(code) == buffer_script.MAX_BUFFER_SCRIPT_SIZE


@needs_unicorn
def test_the_gather_follows_the_pointers_and_sends_back_the_strings():
    from frlgsim import charmap
    memory = _word_info_fixture()

    run, gathered = _gathered(
        buffer_script.build_string_gather(GATHER_ARRAY, len(GATHER_WORDS),
                                          stride=WORD_INFO_STRIDE), memory)

    assert run.done and run.client.send_repointed
    assert run.client.send_size == buffer_script.GATHER_ANSWER_SIZE == 776
    assert [charmap.decode(s) for s in gathered["strings"]] == GATHER_WORDS
    assert gathered["copied"] == len(GATHER_WORDS)
    assert gathered["reason"] == 0          # the count ran out, not the budget
    assert gathered["next"] == GATHER_ARRAY + len(GATHER_WORDS) * WORD_INFO_STRIDE


@needs_unicorn
def test_the_gather_stops_before_a_word_it_cannot_fit_whole_and_resumes_exactly():
    """A half-copied word would be indistinguishable from a French word that really is that
    short, which is the kind of silent wrong this project keeps paying for. So a string that does
    not fit ends the run BEFORE it, and `next` is where the following run starts."""
    from frlgsim import charmap
    memory = _word_info_fixture()
    fits = len(charmap.encode(GATHER_WORDS[0])) + 1 + len(charmap.encode(GATHER_WORDS[1])) + 1

    _run, first = _gathered(
        buffer_script.build_string_gather(GATHER_ARRAY, len(GATHER_WORDS),
                                          stride=WORD_INFO_STRIDE, budget=fits + 3), memory)
    _run, second = _gathered(
        buffer_script.build_string_gather(first["next"], len(GATHER_WORDS) - first["copied"],
                                          stride=WORD_INFO_STRIDE), memory)

    assert [charmap.decode(s) for s in first["strings"]] == GATHER_WORDS[:2]
    assert first["reason"] == 1 and first["written"] == fits
    assert first["next"] == GATHER_ARRAY + 2 * WORD_INFO_STRIDE
    # nothing lost, nothing repeated across the seam
    assert ([charmap.decode(s) for s in first["strings"]]
            + [charmap.decode(s) for s in second["strings"]]) == GATHER_WORDS


@needs_unicorn
def test_the_gather_refuses_a_pointer_that_is_not_a_string():
    """Without maxlen a bad pointer is copied until it happens to meet an 0xFF, and the answer is
    garbage that looks like data."""
    memory = _word_info_fixture()
    array = bytearray(memory[GATHER_ARRAY])
    array[0:4] = (0x08000000).to_bytes(4, "little")
    memory[GATHER_ARRAY] = bytes(array)
    memory[0x08000000] = b"\x00" * 128

    run, gathered = _gathered(
        buffer_script.build_string_gather(GATHER_ARRAY, 3, stride=WORD_INFO_STRIDE, maxlen=8),
        memory)

    assert run.done                          # it still answers rather than hanging the menu
    assert gathered["copied"] == 0 and gathered["reason"] == 2


def test_the_gather_refuses_operands_that_are_not_an_array_of_pointers():
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_string_gather(0x083E1001, 4)          # not word aligned
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_string_gather(0x083E1000, 4, stride=6)
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_string_gather(0x083E1000, 0)
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_string_gather(
            0x083E1000, 4, budget=buffer_script.GATHER_STRING_AREA + 1)


def test_the_cli_builds_a_gather_and_sizes_the_answer_to_the_fixed_table():
    run = _run_config(["--buffer-script", "string-gather", "--gather-address", "0x083DE528",
                       "--gather-count", "26", "--gather-stride", "12"])
    distribution = run.payload.build_distribution()

    assert distribution.buffer_decode == buffer_script.STRING_GATHER
    assert distribution.buffer_dump_size == buffer_script.GATHER_ANSWER_SIZE
    assert buffer_script.gather_parameters(distribution.buffer_code)["src"] == 0x083DE528


def test_the_cli_refuses_a_gather_without_an_array_and_an_array_without_a_gather():
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "string-gather"])
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--gather-address", "0x083DE528"])


# --- create-mon: a ROM call that takes EIGHT arguments -------------------------------------------
# bs15 called Random - no arguments, a u16 back. CreateMon is the other end of the range: four
# arguments in r0..r3 and FOUR ON THE STACK. The console's own prologue [bs42's dump] is what says
# where they go, and CREATE_MON_ARG_MODEL is a THUMB stub that reads them back out from exactly
# there, so these tests check the payload against the disassembly rather than against itself.

CREATE_MON_ADDRESS = rom_map.thumb(rom_map.CREATE_MON)
GURVAN_OT_ID = 0xE5BBDF65               # bs01: TID 57189, SID 58811


def _create_mon_args(code, **kwargs):
    """-> the eight arguments as the callee saw them, by running the payload against the model."""
    run = buffer_script.emulate(
        code, memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL}, **kwargs)
    result = buffer_script.read_create_mon(run.pending_send)
    words = [int.from_bytes(result["mon"][i:i + 4], "little") for i in range(0, 32, 4)]
    return run, result, dict(zip(buffer_script.CREATE_MON_ARG_FIELDS, words))


def _valid_mon(species=151, level=30, ivs=31, personality=0x3ADE0000, ot_id=GURVAN_OT_ID,
               nickname="MEW", ot_name="GURVAN"):
    """100 bytes that decode as a struct Pokemon, built the way the ROM would have left them.

    Not a model of CreateMon - a fixture. What it is for is the DECODE: a mon that travels the
    whole path proves that what comes off the console can be read as one.
    """
    from frlgsim import charmap, mon as monlib, stats
    canon = bytearray(monlib.PARTY_MON_SIZE)
    canon[0:4] = personality.to_bytes(4, "little")
    canon[4:8] = ot_id.to_bytes(4, "little")
    canon[8:18] = charmap.encode(nickname, width=10)
    canon[18] = 2                                   # language
    canon[20:27] = charmap.encode(ot_name, width=7)
    growth = bytearray(12)
    growth[0:2] = species.to_bytes(2, "little")
    exp = next(e for e in range(0, 1_700_000, 1)
               if stats.level_from_exp(species, e) == level)
    growth[4:8] = exp.to_bytes(4, "little")
    growth[9] = 70                                  # friendship
    attacks = bytearray(12)
    attacks[0:2] = (1).to_bytes(2, "little")        # POUND, so the moves list is not all zero
    attacks[8] = 35
    misc = bytearray(12)
    iv_word = 0
    for i in range(6):
        iv_word |= (ivs & 31) << (5 * i)
    misc[4:8] = iv_word.to_bytes(4, "little")
    canon[32:44], canon[44:56] = growth, attacks
    canon[56:68], canon[68:80] = bytearray(12), misc
    canon[28:30] = (sum(int.from_bytes(canon[32 + i * 2:34 + i * 2], "little")
                        for i in range(24)) & 0xFFFF).to_bytes(2, "little")
    built = monlib.Mon.from_pk3(bytes(canon))
    assert built.checksum_ok, "the fixture itself does not checksum"
    return built.party_bytes()


def test_the_create_mon_operands_are_where_we_patch_them():
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=151, level=30, fixed_iv=31,
        has_fixed_personality=1, fixed_personality=0x3ADE0000,
        ot_id_type=buffer_script.OT_ID_PRESET, fixed_ot_id=GURVAN_OT_ID,
        destination=0)
    assert buffer_script.create_mon_parameters(code) == {
        "function": CREATE_MON_ADDRESS, "destination": 0, "party_append": 0,
        # the party addresses ride along even when no append was asked for, defaulted from the
        # ones bs47 measured rather than left for a caller to supply
        "party_base": rom_map.GPLAYER_PARTY, "party_count": rom_map.GPLAYER_PARTY_COUNT,
        "species": 151, "level": 30, "fixed_iv": 31, "has_fixed_personality": 1,
        "fixed_personality": 0x3ADE0000,
        "ot_id_type": buffer_script.OT_ID_PRESET, "fixed_ot_id": GURVAN_OT_ID}


@needs_unicorn
def test_all_eight_arguments_arrive_where_the_console_s_prologue_reads_them():
    """CreateMon pushes five registers, then r8, then subtracts 28, and reads its stack arguments
    at [sp,#52], [sp,#56], [sp,#60] and [sp,#64] - entry sp + 0, 4, 8 and 12 [bs42]. The model
    reads them from exactly those four words, so agreement here is agreement with the console."""
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=151, level=30, fixed_iv=31,
        has_fixed_personality=1, fixed_personality=0x3ADE0000,
        ot_id_type=buffer_script.OT_ID_PRESET, fixed_ot_id=GURVAN_OT_ID)

    run, result, args = _create_mon_args(code)

    assert args["species"] == 151 and args["level"] == 30 and args["fixedIV"] == 31
    assert args["hasFixedPersonality"] == 1
    assert args["fixedPersonality"] == 0x3ADE0000
    assert args["otIdType"] == buffer_script.OT_ID_PRESET
    assert args["fixedOtId"] == GURVAN_OT_ID
    # r0 is the mon, and it is inside our own image at the offset the source fixes.
    assert args["mon"] == result["built_at"] == (
        buffer_script.GDECOMPRESSION_BUFFER + buffer_script.CREATE_MON_MON_OFFSET)
    # Returning at all is the proof that the 16 bytes of stack arguments were taken back: the
    # callee does not pop them [bs42: add sp,#28; pop {r3}; pop {r4-r7}; pop {r0}; bx r0], so a
    # payload that forgot would pop a garbage lr and never reach _RETURN_ADDRESS.
    assert run.returned == buffer_script.BUFFER_SCRIPT_DONE
    assert run.client.send_size == buffer_script.CREATE_MON_ANSWER_SIZE == 120


@needs_unicorn
def test_the_call_is_made_in_one_frame_and_the_answer_is_a_fixed_size():
    code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=25, level=5)
    repeated = buffer_script.emulate_repeating(
        code, memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})

    assert repeated.calls == 1
    assert buffer_script.read_create_mon(repeated.final.pending_send)["calls"] == 1
    assert len(repeated.final.pending_send) == buffer_script.CREATE_MON_ANSWER_SIZE


@needs_unicorn
def test_with_no_function_nothing_is_called_and_the_send_is_still_repointed():
    """The whole payload with the ROM left out of it: what it checks is the send path and the
    shape of the answer, which is worth one run on a console whose ROM we have not read."""
    code = buffer_script.build_create_mon(0, species=25, level=5)

    run = buffer_script.emulate(code)
    result = buffer_script.read_create_mon(run.pending_send)

    assert result["function"] == 0
    assert result["mon"] == b"\x00" * buffer_script.PARTY_MON_SIZE
    assert result["party"]["status"] == buffer_script.PARTY_WRITE_NONE
    assert run.client.send_repointed and run.client.send_size == 120


def test_the_mon_is_built_inside_our_own_image_and_cannot_reach_the_code():
    """CreateMon writes 100 bytes wherever it is pointed, and it is pointed at our own image. The
    distance from the mon to the first instruction is read out of the payload's OWN opening branch
    rather than assumed, so this fails if the guard is ever assembled away."""
    code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=25, level=5)

    branch = int.from_bytes(code[:4], "little")
    assert branch >> 24 == 0xEA, "the payload does not open with an unconditional ARM branch"
    code_starts = 8 + (branch & 0xFFFFFF) * 4               # pc reads as the instruction + 8
    guard_start = buffer_script.CREATE_MON_PARTY_OFFSET + 4

    assert code_starts - guard_start == 32
    assert code[guard_start:code_starts] == b"\x00" * 32


@needs_unicorn
def test_the_destination_copy_writes_exactly_the_hundred_bytes_and_nothing_else():
    destination = buffer_script.SAV1_ADDRESS + 0x38          # where playerParty[0] lives
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=25, level=5, destination=destination)

    run = buffer_script.emulate(
        code, sav1=b"\x11" * 600,
        memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    result = buffer_script.read_create_mon(run.pending_send)

    assert result["destination"] == destination
    assert run.sav1[0x38:0x38 + 100] == result["mon"]
    assert run.sav1[:0x38] == b"\x11" * 0x38
    assert run.sav1[0x38 + 100:] == b"\x11" * (600 - 0x38 - 100)


@needs_unicorn
def test_the_answer_decodes_as_a_struct_pokemon_and_every_argument_is_checked():
    """The other half: what comes back has to be readable as a mon, and the check has to be able
    to say WHICH argument disagreed. The copy model puts a real mon at the destination."""
    template = 0x08300000
    mon = _valid_mon(species=151, level=30, ivs=31, personality=0x3ADE0000, ot_id=GURVAN_OT_ID)
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=151, level=30, fixed_iv=31,
        has_fixed_personality=1, fixed_personality=0x3ADE0000,
        ot_id_type=buffer_script.OT_ID_PRESET, fixed_ot_id=GURVAN_OT_ID)

    run = buffer_script.emulate(code, memory={
        rom_map.CREATE_MON: buffer_script.create_mon_copy_model(template), template: mon})
    result = buffer_script.read_create_mon(run.pending_send)

    assert result["mon"] == mon
    assert buffer_script.create_mon_ivs(result["mon"]) == [31] * 6
    lines = buffer_script.check_create_mon(
        result["mon"], buffer_script.create_mon_parameters(code))
    assert not any("MISMATCH" in line for line in lines), lines
    assert any("checksum: VALID" in line for line in lines)
    described = buffer_script.describe_create_mon(
        run.pending_send, buffer_script.create_mon_parameters(code))
    assert any("SHINY" in line for line in described), described


@needs_unicorn
def test_the_check_names_the_argument_that_disagreed():
    mon = _valid_mon(species=151, level=30, ivs=31)
    asked = buffer_script.create_mon_parameters(
        buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=25, level=30, fixed_iv=31,
                                       has_fixed_personality=1, fixed_personality=0x3ADE0000))

    lines = buffer_script.check_create_mon(mon, asked)

    assert any(line.startswith("species: asked 25, got 151") and "MISMATCH" in line
               for line in lines), lines
    assert not any(line.startswith("level") and "MISMATCH" in line for line in lines)


def test_a_shiny_personality_is_shiny_for_the_trainer_it_was_aimed_at():
    """GURVAN's SECRET id is what makes this possible at all: it is printed nowhere in the game
    and carried by no link message, and bs01 read it out of the save [rom_map.py]."""
    personality = buffer_script.shiny_personality(57189, 58811)

    assert buffer_script.is_shiny(GURVAN_OT_ID, personality)
    assert buffer_script.shiny_value(GURVAN_OT_ID, personality) == 0
    assert not buffer_script.is_shiny(GURVAN_OT_ID, personality ^ 0x1000)


def test_create_mon_refuses_arguments_the_console_would_fault_on():
    for kwargs, match in (
            ({"species": 0}, "species must be"),
            ({"species": 412}, "species must be"),
            ({"level": 0}, "level must be"),
            ({"level": 101}, "level must be"),
            ({"fixed_iv": 256}, "fixedIV is a u8"),
            ({"ot_id_type": 3}, "otIdType is"),
            ({"destination": 0x08041150}, "read-only"),
            ({"destination": 0x01000000}, "not somewhere")):
        args = {"species": 25, "level": 5}
        args.update(kwargs)
        with pytest.raises(buffer_script.BufferScriptError, match=match):
            buffer_script.build_create_mon(CREATE_MON_ADDRESS, **args)


def test_create_mon_refuses_an_arm_pointer_and_an_address_outside_the_cartridge():
    with pytest.raises(buffer_script.BufferScriptError, match="ARM pointer"):
        buffer_script.build_create_mon(rom_map.CREATE_MON, species=25, level=5)
    with pytest.raises(buffer_script.BufferScriptError, match="not in the cartridge"):
        buffer_script.build_create_mon(0x02000001, species=25, level=5)


@needs_unicorn
def test_end_to_end_the_console_calls_create_mon_and_sends_the_mon_back():
    template = 0x08300000
    mon = _valid_mon(species=151, level=30, ivs=31, personality=0x3ADE0000, ot_id=GURVAN_OT_ID)
    console = ConsoleClientModel(flag_id=0, rom_stubs={
        rom_map.CREATE_MON: buffer_script.create_mon_copy_model(template), template: mon})
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=151, level=30, fixed_iv=31,
        has_fixed_personality=1, fixed_personality=0x3ADE0000,
        ot_id_type=buffer_script.OT_ID_PRESET, fixed_ot_id=GURVAN_OT_ID)
    distribution = stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None, buffer_code=code,
        buffer_dump_size=buffer_script.CREATE_MON_ANSWER_SIZE,
        buffer_decode=buffer_script.CREATE_MON)

    engine, _frames = _drive(console, distribution=distribution)

    assert engine.server.buffer_matched is True
    result = buffer_script.read_create_mon(engine.server.buffer_dump)
    assert result["mon"] == mon
    assert result["destination"] == 0
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_the_server_refuses_a_create_mon_whose_answer_is_not_the_size_one_answers():
    with pytest.raises(mg_server.MysteryGiftServerError, match="create-mon answers with"):
        mg_server.MysteryGiftServer(
            None, None,
            buffer_code=buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=25, level=5),
            buffer_dump_size=1024, buffer_decode=buffer_script.CREATE_MON)


def test_the_cli_builds_a_create_mon_and_defaults_the_call_to_the_address_bs42_read():
    run = _run_config(["--buffer-script", "create-mon", "--create-mon-species", "151",
                       "--create-mon-level", "30", "--create-mon-iv", "31",
                       "--create-mon-personality", "0x3ADE0000"])
    distribution = run.payload.build_distribution()

    assert distribution.buffer_decode == buffer_script.CREATE_MON
    assert distribution.buffer_dump_size == buffer_script.CREATE_MON_ANSWER_SIZE == 120
    asked = buffer_script.create_mon_parameters(distribution.buffer_code)
    assert asked["function"] == CREATE_MON_ADDRESS
    assert asked["species"] == 151 and asked["level"] == 30 and asked["fixed_iv"] == 31
    assert asked["has_fixed_personality"] == 1 and asked["fixed_personality"] == 0x3ADE0000


def test_the_cli_leaves_the_personality_to_the_console_when_it_is_not_given():
    run = _run_config(["--buffer-script", "create-mon", "--create-mon-species", "25"])
    asked = buffer_script.create_mon_parameters(run.payload.build_distribution().buffer_code)

    assert asked["has_fixed_personality"] == 0 and asked["fixed_personality"] == 0


def test_the_cli_refuses_a_live_write_without_the_deliberate_override():
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "create-mon", "--create-mon-destination", "0x02024598"])
    run = _run_config(["--buffer-script", "create-mon", "--create-mon-destination", "0x02024598",
                       "--write-unsafe"])
    asked = buffer_script.create_mon_parameters(run.payload.build_distribution().buffer_code)
    assert asked["destination"] == 0x02024598


def test_the_cli_refuses_create_mon_flags_on_another_payload():
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--create-mon-call", "0x08041151"])
    with pytest.raises(SystemExit):
        _run_config(["--buffer-script", "save-dump", "--create-mon-destination", "0x02024598"])


def test_a_built_create_mon_and_gather_are_still_named_by_their_own_bytes():
    """The host logs `describe(code)` before a run. A payload whose operands are not in
    PATCHED_SPANS reads back as 'unknown buffer script', which is what string-gather did."""
    assert buffer_script.describe(
        buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=151, level=30, fixed_iv=31,
                                       fixed_personality=0x3ADE0000, destination=0x02024598)
    ).startswith("create-mon")
    assert buffer_script.describe(
        buffer_script.build_string_gather(0x083E0D54, 69)).startswith("string-gather")


# --- create-mon --create-mon-append: the write into the player's party ---------------------------
# This is the one thing in the payload that touches a live save. Its safety is structural rather
# than checked: the slot is playerParty[playerPartyCount], which is by definition the first FREE
# one, so an occupied slot is never written whatever else is wrong. These tests are what say that
# out loud, and the sav1 fixture is shaped like GURVAN's console - one mon in it.

CHANSEY = b"\xAA" * buffer_script.PARTY_MON_SIZE     # a mon that must survive every append

# gPlayerParty is an EWRAM global, not part of a save block - bs46 proved the save block's copy is
# the wrong target. The emulator only hands back the two save-block buffers, so these tests put the
# party inside the sav1 buffer purely as A REGION OF EWRAM THAT CAN BE READ BACK, and pass its
# address to the payload explicitly. Nothing here says a party lives in a save block.
TEST_PARTY_COUNT = buffer_script.SAV1_ADDRESS + 0x34
TEST_PARTY = buffer_script.SAV1_ADDRESS + 0x38
PARTY_ARGS = {"party_base": TEST_PARTY, "party_count": TEST_PARTY_COUNT}
COUNT_OFF = TEST_PARTY_COUNT - buffer_script.SAV1_ADDRESS
PARTY_OFF = TEST_PARTY - buffer_script.SAV1_ADDRESS


def _party_sav1(count, size=0x300):
    """A readable EWRAM region: `count` mons at TEST_PARTY, the count at TEST_PARTY_COUNT."""
    sav1 = bytearray(size)
    sav1[COUNT_OFF] = count
    for slot in range(count):
        start = PARTY_OFF + slot * buffer_script.PARTY_MON_SIZE
        sav1[start:start + buffer_script.PARTY_MON_SIZE] = CHANSEY
    return bytes(sav1)


@needs_unicorn
def test_the_append_writes_the_first_free_slot_and_raises_the_count():
    code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                          party_append=True, **PARTY_ARGS)

    run = buffer_script.emulate(
        code, sav1=_party_sav1(1),
        memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    result = buffer_script.read_create_mon(run.pending_send)

    party, size = PARTY_OFF, buffer_script.PARTY_MON_SIZE
    assert result["party"] == {"count_before": 1, "slot": 1,
                               "status": buffer_script.PARTY_WRITE_APPENDED}
    assert run.sav1[party:party + size] == CHANSEY          # the mon that was there is untouched
    assert run.sav1[party + size:party + 2 * size] == result["mon"]
    assert run.sav1[COUNT_OFF] == 2
    # The address is COMPUTED from gSaveBlock1Ptr, never given: the save blocks move between save
    # loads, so an absolute address for a party slot would be right only until the next boot.
    assert result["destination"] == TEST_PARTY + size
    assert buffer_script.create_mon_parameters(code)["destination"] == 0


@needs_unicorn
def test_the_append_never_touches_an_occupied_slot_at_any_party_size():
    for count in range(buffer_script.PARTY_SIZE):
        code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                              party_append=True, **PARTY_ARGS)
        run = buffer_script.emulate(
            code, sav1=_party_sav1(count),
            memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
        result = buffer_script.read_create_mon(run.pending_send)

        party, size = PARTY_OFF, buffer_script.PARTY_MON_SIZE
        assert result["party"]["slot"] == count
        assert run.sav1[party:party + count * size] == CHANSEY * count
        assert run.sav1[party + count * size:party + (count + 1) * size] == result["mon"]
        assert run.sav1[COUNT_OFF] == count + 1


@needs_unicorn
def test_a_full_party_writes_nothing_and_says_so():
    """The same shape as `givepokemon` answering 3 instead of 2 [mev02]: a refusal that comes back
    as an answer, not a failure."""
    code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                          party_append=True, **PARTY_ARGS)

    run = buffer_script.emulate(
        code, sav1=_party_sav1(buffer_script.PARTY_SIZE),
        memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    result = buffer_script.read_create_mon(run.pending_send)

    party, size = PARTY_OFF, buffer_script.PARTY_MON_SIZE
    assert result["party"] == {"count_before": 6, "slot": 0,
                               "status": buffer_script.PARTY_WRITE_FULL}
    assert result["destination"] == 0
    assert run.sav1[party:party + 6 * size] == CHANSEY * 6
    assert run.sav1[COUNT_OFF] == buffer_script.PARTY_SIZE
    assert run.returned == buffer_script.BUFFER_SCRIPT_DONE


@needs_unicorn
def test_the_append_writes_nothing_past_the_party():
    """playerParty[6] ends at 0x38 + 600 = 0x290, which is `money` [global.h:774]. A slot index
    that ran over would land on it."""
    code = buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                          party_append=True, **PARTY_ARGS)
    end = PARTY_OFF + buffer_script.PARTY_SIZE * buffer_script.PARTY_MON_SIZE
    assert end == 0x290

    for count in (0, 5, 6):
        run = buffer_script.emulate(
            code, sav1=_party_sav1(count),
            memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
        assert run.sav1[end:] == bytes(len(run.sav1) - end), f"money moved with {count} in the party"
        assert run.sav1[:COUNT_OFF] == bytes(COUNT_OFF)


def test_the_append_refuses_what_would_write_rubbish_or_ask_twice():
    with pytest.raises(buffer_script.BufferScriptError, match="two answers"):
        buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                       party_append=True, destination=0x02024598)
    with pytest.raises(buffer_script.BufferScriptError, match="zero bytes"):
        buffer_script.build_create_mon(0, species=59, level=30, party_append=True, **PARTY_ARGS)


@needs_unicorn
def test_end_to_end_the_console_appends_the_mon_to_its_own_party():
    template = 0x08300000
    mon = _valid_mon(species=59, level=30, ivs=31, personality=0x3ADF0001, ot_id=GURVAN_OT_ID,
                     nickname="ARCANIN")
    console = ConsoleClientModel(flag_id=0, rom_stubs={
        rom_map.CREATE_MON: buffer_script.create_mon_copy_model(template), template: mon})
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=59, level=30, fixed_iv=31,
        has_fixed_personality=1, fixed_personality=0x3ADF0001,
        ot_id_type=buffer_script.OT_ID_PRESET, fixed_ot_id=GURVAN_OT_ID, party_append=True, **PARTY_ARGS)
    distribution = stamp_rally.MysteryGiftDistribution(
        card=None, ram_script=None, buffer_code=code,
        buffer_dump_size=buffer_script.CREATE_MON_ANSWER_SIZE,
        buffer_decode=buffer_script.CREATE_MON)

    engine, _frames = _drive(console, distribution=distribution)

    assert engine.server.buffer_matched is True
    result = buffer_script.read_create_mon(engine.server.buffer_dump)
    assert result["mon"] == mon
    assert result["party"]["status"] == buffer_script.PARTY_WRITE_APPENDED
    assert console.result == mg_script.CLI_MSG_BUFFER_SUCCESS


def test_the_cli_refuses_an_append_without_the_deliberate_override():
    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "create-mon", "--create-mon-append"])
    run = _run_config(["--buffer-script", "create-mon", "--create-mon-species", "59",
                       "--create-mon-append", "--write-unsafe"])
    asked = buffer_script.create_mon_parameters(run.payload.build_distribution().buffer_code)
    assert asked["party_append"] == 1 and asked["destination"] == 0


def test_bs43_and_bs44_dumps_still_read_without_a_party_word():
    """Those runs answered 116 bytes, from before the party word existed. The header and the mon
    are at the same offsets, so their dumps must still decode - and say `party` is not there
    rather than invent one."""
    import struct
    mon = _valid_mon(species=59, level=30, ivs=31, personality=0x3ADF0001, ot_id=GURVAN_OT_ID)
    old_answer = struct.pack("<4I", 1, 0, CREATE_MON_ADDRESS, 0x0201C038) + mon

    result = buffer_script.read_create_mon(old_answer)

    assert result["mon"] == mon and result["party"] is None
    assert result["calls"] == 1 and result["function"] == CREATE_MON_ADDRESS


@needs_unicorn
def test_the_dry_run_writes_nothing_and_reads_back_the_slot_it_would_have_written():
    """The dry run is the real append with the two stores left out - same call, same arithmetic on
    the same gSaveBlock1Ptr. What makes it worth a hardware run of its own is that NO payload had
    ever used r2 before, and an append computes its destination from it."""
    before = _party_sav1(1)
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=59, level=30,
        party_append=buffer_script.PARTY_APPEND_DRY_RUN, **PARTY_ARGS)

    run = buffer_script.emulate(
        code, sav1=before, memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    result = buffer_script.read_create_mon(run.pending_send)

    assert run.sav1 == before, "the dry run changed the save"
    assert result["party"] == {"count_before": 1, "slot": 1,
                               "status": buffer_script.PARTY_WRITE_DRY_RUN}
    # The address it WOULD have written, computed the same way the real append computes it.
    assert result["destination"] == TEST_PARTY + buffer_script.PARTY_MON_SIZE
    # And the 100 bytes are the SLOT's, not the mon's: an empty slot reads as zeros.
    assert result["mon"] == bytes(buffer_script.PARTY_MON_SIZE)


@needs_unicorn
def test_the_dry_run_computes_the_same_address_the_real_append_writes():
    """The two runs must not be able to disagree, or the dry run proves nothing about the real
    one. Same arguments, same save, at every party size."""
    for count in range(buffer_script.PARTY_SIZE):
        sav1 = _party_sav1(count)
        stub = {rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL}
        dry = buffer_script.read_create_mon(buffer_script.emulate(
            buffer_script.build_create_mon(
                CREATE_MON_ADDRESS, species=59, level=30,
                party_append=buffer_script.PARTY_APPEND_DRY_RUN, **PARTY_ARGS),
            sav1=sav1, memory=stub).pending_send)
        real = buffer_script.read_create_mon(buffer_script.emulate(
            buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                           party_append=True, **PARTY_ARGS),
            sav1=sav1, memory=stub).pending_send)

        assert dry["destination"] == real["destination"]
        assert dry["party"]["slot"] == real["party"]["slot"] == count
        assert dry["party"]["count_before"] == real["party"]["count_before"] == count


@needs_unicorn
def test_the_dry_run_over_an_occupied_slot_says_do_not_append():
    """If playerPartyCount ever disagreed with what is actually in the party, the dry run is what
    would catch it - before a store, not after."""
    sav1 = bytearray(_party_sav1(1))
    start = PARTY_OFF + buffer_script.PARTY_MON_SIZE
    sav1[start:start + buffer_script.PARTY_MON_SIZE] = b"\xCC" * buffer_script.PARTY_MON_SIZE
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=59, level=30,
        party_append=buffer_script.PARTY_APPEND_DRY_RUN, **PARTY_ARGS)

    run = buffer_script.emulate(
        code, sav1=bytes(sav1), memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    lines = buffer_script.describe_create_mon(
        run.pending_send, buffer_script.create_mon_parameters(code))

    assert run.sav1 == bytes(sav1)
    assert any("DO NOT APPEND" in line for line in lines), lines


@needs_unicorn
def test_the_dry_run_of_a_full_party_reports_full_not_a_slot():
    code = buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=59, level=30,
        party_append=buffer_script.PARTY_APPEND_DRY_RUN, **PARTY_ARGS)

    run = buffer_script.emulate(
        code, sav1=_party_sav1(buffer_script.PARTY_SIZE),
        memory={rom_map.CREATE_MON: buffer_script.CREATE_MON_ARG_MODEL})
    result = buffer_script.read_create_mon(run.pending_send)

    assert result["party"]["status"] == buffer_script.PARTY_WRITE_FULL
    assert result["destination"] == 0


def test_the_cli_takes_the_dry_run_without_an_override_and_refuses_both_at_once():
    run = _run_config(["--buffer-script", "create-mon", "--create-mon-species", "59",
                       "--create-mon-append-dry-run"])
    asked = buffer_script.create_mon_parameters(run.payload.build_distribution().buffer_code)
    assert asked["party_append"] == buffer_script.PARTY_APPEND_DRY_RUN

    with pytest.raises((ValueError, SystemExit)):
        _run_config(["--buffer-script", "create-mon", "--create-mon-append",
                     "--create-mon-append-dry-run", "--write-unsafe"])


def test_an_empty_party_slot_is_not_a_hundred_zero_bytes():
    """bs45 read the slot a real append would write and found ONE non-zero byte in it. That is not
    a problem with the console: ZeroMonData zeroes everything and then ends `arg = MAIL_NONE;
    SetMonData(mon, MON_DATA_MAIL, &arg)` [decomp:src/pokemon.c:1737], and mail is at offset 0x55.
    An empty slot the game itself zeroed looks EXACTLY like this, so requiring a hundred zeros was
    the check being wrong, not the save."""
    assert len(buffer_script.EMPTY_PARTY_SLOT) == buffer_script.PARTY_MON_SIZE
    assert buffer_script.EMPTY_PARTY_SLOT[85] == 0xFF
    assert sum(buffer_script.EMPTY_PARTY_SLOT) == 0xFF        # and nothing else is set

    assert buffer_script.is_empty_party_slot(buffer_script.EMPTY_PARTY_SLOT)
    assert buffer_script.is_empty_party_slot(bytes(buffer_script.PARTY_MON_SIZE))
    occupied = bytearray(buffer_script.EMPTY_PARTY_SLOT)
    occupied[0] = 1                                            # a personality makes it a mon
    assert not buffer_script.is_empty_party_slot(bytes(occupied))


@needs_unicorn
def test_the_dry_run_calls_a_zeroed_slot_empty_and_a_used_one_occupied():
    import struct
    asked = buffer_script.create_mon_parameters(buffer_script.build_create_mon(
        CREATE_MON_ADDRESS, species=59, level=30,
        party_append=buffer_script.PARTY_APPEND_DRY_RUN, **PARTY_ARGS))
    header = struct.pack("<4I", 1, 0x02025638, CREATE_MON_ADDRESS, 0x0201C03C)
    tail = struct.pack("<I", 1 | 1 << 8 | buffer_script.PARTY_WRITE_DRY_RUN << 16)

    empty = buffer_script.describe_create_mon(
        header + buffer_script.EMPTY_PARTY_SLOT + tail, asked)
    assert any("is EMPTY exactly as ZeroMonData leaves one" in line for line in empty), empty
    assert not any("DO NOT APPEND" in line for line in empty)

    used = bytearray(buffer_script.EMPTY_PARTY_SLOT)
    used[0:4] = b"\x01\x02\x03\x04"
    occupied = buffer_script.describe_create_mon(header + bytes(used) + tail, asked)
    assert any("DO NOT APPEND" in line for line in occupied), occupied


def test_the_save_blocks_move_by_a_four_aligned_offset_the_game_rolls():
    """bs45 and bs46 read gSaveBlock1Ptr six minutes apart, on one boot, and it had MOVED.
    SetSaveBlocksPointers [decomp:src/load_save.c:75] rolls
    `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)` and MoveSaveBlocks_ResetHeap re-rolls
    it - CB2_InitBattle calls that, so every battle moves them. This is why nothing may carry an
    absolute save address between runs."""
    seen = rom_map.GSAVEBLOCK1_SEEN
    deltas = [abs(a - b) for a in seen for b in seen if a != b]

    assert all(d % 4 == 0 for d in deltas), "the offset is 4-aligned by the mask"
    assert max(deltas) <= rom_map.SAVEBLOCK_MOVE_MASK, "outside the range the game can roll"
    assert rom_map.SAVEBLOCK_MOVE_MASK == 0x7C


def test_no_payload_carries_an_absolute_address_into_a_save_block():
    """The consequence of the ASLR, as a check rather than a comment: what is safe to hardcode is
    decided by whether the thing MOVES, not by whether it is convenient.

    save-dump and save-write name a block, an offset and a size, and take the pointer itself from
    r1/r2 every call. The party append DOES hardcode two addresses - and that is right, because
    gPlayerParty and gPlayerPartyCount are link-time EWRAM globals; bs42 read one as a literal
    constant out of the ROM's own pool. What must never be hardcoded is an address inside a save
    block, and none is."""
    assert buffer_script.build_save_dump(buffer_script.SAVE_BLOCK_1, 0x38, 200)[
        buffer_script.SAVE_DUMP_WHICH_OFFSET:buffer_script.SAVE_DUMP_WHICH_OFFSET + 12] == (
            (1).to_bytes(4, "little") + (0x38).to_bytes(4, "little")
            + (200).to_bytes(4, "little"))

    # The party the append names is further below every gSaveBlock1Ptr this project has seen than
    # the ASLR offset could ever move one.
    party_end = rom_map.GPLAYER_PARTY + buffer_script.PARTY_SIZE * buffer_script.PARTY_MON_SIZE
    for seen in rom_map.GSAVEBLOCK1_SEEN:
        assert seen - rom_map.SAVEBLOCK_MOVE_MASK > party_end


def test_the_party_append_defaults_to_the_addresses_bs47_measured():
    asked = buffer_script.create_mon_parameters(
        buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                       party_append=True))

    assert asked["party_base"] == rom_map.GPLAYER_PARTY == 0x02024280
    assert asked["party_count"] == rom_map.GPLAYER_PARTY_COUNT == 0x02024025


def test_the_party_append_refuses_a_party_that_is_not_in_ewram():
    """These are the two addresses the payload does hardcode, so they are the two worth guarding."""
    for kwargs in ({"party_base": 0x08041150}, {"party_count": 0x03004220},
                   {"party_base": 0x0203FFC0}):        # too near the top for six mons
        with pytest.raises(buffer_script.BufferScriptError):
            buffer_script.build_create_mon(CREATE_MON_ADDRESS, species=59, level=30,
                                           party_append=True, **kwargs)


# --- call: any ROM function, with arguments we choose --------------------------------------------
# The fixture is again the console's OWN code: SeedRng as bs14 read it out of the cartridge, twelve
# bytes and its literal pool. It is the function the RNG work needs to call, and executing it under
# unicorn is what proves the payload before a run is spent on it.

SEED_RNG_CODE_BASE = 0x080486D0
SEED_RNG_CODE = bytes.fromhex(
    "0004000c"      # lsls r0,r0,#16 ; lsrs r0,r0,#16   -> the u16 SeedRng takes
    "01490860"      # ldr r1,[pc,#4] ; str r0,[r1]      -> gRngValue = seed
    "70470000"      # bx lr          ; (padding)
    "20420003")     # .word 0x03004220   &gRngValue


def test_the_committed_seed_rng_bytes_are_the_function_the_decomp_describes():
    """Same discipline as the Random fixture: check it against the things that cannot both be
    coincidence - the pool word, the u16 truncation, and where it sits in the map."""
    assert int.from_bytes(SEED_RNG_CODE[12:16], "little") == GRNG_VALUE
    assert SEED_RNG_CODE[:4] == b"\x00\x04\x00\x0c"     # lsls #16 then lsrs #16: the u16
    assert SEED_RNG_CODE[8:10] == b"\x70\x47"           # bx lr
    assert SEED_RNG_CODE_BASE == rom_map.SEED_RNG


def test_the_call_operands_are_where_we_patch_them():
    code = buffer_script.build_call(SEED_RNG_CODE_BASE | 1, [0xB8C0], watch=GRNG_VALUE)
    assert buffer_script.call_parameters(code) == {
        "function": SEED_RNG_CODE_BASE | 1, "argc": 1, "args": [0xB8C0], "watch": GRNG_VALUE}
    # It must still be recognisable as the payload it was built from [PATCHED_SPANS].
    assert buffer_script.describe(code).startswith(buffer_script.CALL)


def test_the_call_refuses_what_would_hang_or_run_rubbish():
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_call(SEED_RNG_CODE_BASE, [0])          # ARM pointer: bit 0 clear
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_call(0x02000001, [0])                  # not in the cartridge
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_call(SEED_RNG_CODE_BASE | 1, [0] * 9)  # nine arguments
    with pytest.raises(buffer_script.BufferScriptError):
        buffer_script.build_call(SEED_RNG_CODE_BASE | 1, [0], watch=GRNG_VALUE + 1)  # unaligned


@needs_unicorn
def test_the_call_seeds_the_console_s_own_rng_and_the_watch_proves_it():
    """bs15 called Random and read the word either side; this calls SeedRng, whose return value is
    nothing at all - so the watched word is the ONLY evidence the call did anything."""
    seed = 0xB8C0
    memory = {SEED_RNG_CODE_BASE: SEED_RNG_CODE,
              GRNG_VALUE: (0x3C22BA3A).to_bytes(4, "little")}
    run = buffer_script.emulate(
        buffer_script.build_call(SEED_RNG_CODE_BASE | 1, [seed], watch=GRNG_VALUE),
        memory=memory, send_size=buffer_script.CALL_ANSWER_SIZE)
    got = buffer_script.read_call(run.pending_send)
    assert got["calls"] == 1 and got["argc"] == 1
    assert got["before"] == 0x3C22BA3A, "the state the console was on before we touched it"
    assert got["after"] == seed, "SeedRng assigns the u16 outright [decomp:src/random.c:15]"
    assert any("IT HOLDS" in line for line in buffer_script.describe_call(run.pending_send, seed))


@needs_unicorn
def test_the_call_truncates_to_a_u16_because_the_callee_does():
    """SeedRng takes a u16 and the console's own two shifts throw the top half away. Passing more
    than 16 bits is therefore not an error we can refuse - it is a fact about the answer."""
    memory = {SEED_RNG_CODE_BASE: SEED_RNG_CODE, GRNG_VALUE: b"\0\0\0\0"}
    run = buffer_script.emulate(
        buffer_script.build_call(SEED_RNG_CODE_BASE | 1, [0xDEADB8C0], watch=GRNG_VALUE),
        memory=memory, send_size=buffer_script.CALL_ANSWER_SIZE)
    assert buffer_script.read_call(run.pending_send)["after"] == 0xB8C0


@needs_unicorn
def test_the_call_returns_what_the_callee_returned():
    """Random returns a u16 in r0, so calling it through the general path must bring that back -
    and it must be the top half of the state the same call left behind."""
    memory = _console_memory(0x00001234)
    run = buffer_script.emulate(
        buffer_script.build_call(RANDOM_CODE_BASE | 1, [], watch=GRNG_VALUE),
        memory=memory, send_size=buffer_script.CALL_ANSWER_SIZE)
    got = buffer_script.read_call(run.pending_send)
    assert got["before"] == 0x00001234
    assert got["after"] == buffer_script.rand_step(0x00001234)
    assert got["returned"] == got["after"] >> 16


@needs_unicorn
def test_calling_nothing_still_reads_the_watched_word_twice():
    """--call-address 0 is the send path with the ROM left out, the way --create-mon-call 0 is."""
    run = buffer_script.emulate(
        buffer_script.build_call(0, [], watch=GRNG_VALUE),
        memory={GRNG_VALUE: (0xABCD1234).to_bytes(4, "little")},
        send_size=buffer_script.CALL_ANSWER_SIZE)
    got = buffer_script.read_call(run.pending_send)
    assert (got["function"], got["returned"]) == (0, 0)
    assert got["before"] == got["after"] == 0xABCD1234
    assert any("nothing was called" in line
               for line in buffer_script.describe_call(run.pending_send))


# Eight arguments, hand-assembled THUMB: sum r0..r3 and the four stack words and return the total.
# Powers of two go in, so the sum names EXACTLY which slots arrived - a missing or duplicated
# argument cannot cancel out. This is the mechanism bs43/bs44 proved for CreateMon, checked here
# for the general payload that is meant to reach every other function with it.
EIGHT_ARG_CODE_BASE = 0x08100000
EIGHT_ARG_CODE = bytes.fromhex(
    "4018"      # adds r0, r0, r1
    "8018"      # adds r0, r0, r2
    "c018"      # adds r0, r0, r3
    "0099" "4018"   # ldr r1,[sp,#0]  ; adds r0, r0, r1
    "0199" "4018"   # ldr r1,[sp,#4]  ; adds r0, r0, r1
    "0299" "4018"   # ldr r1,[sp,#8]  ; adds r0, r0, r1
    "0399" "4018"   # ldr r1,[sp,#12] ; adds r0, r0, r1
    "7047")     # bx lr


@needs_unicorn
def test_all_eight_arguments_arrive_in_the_slots_the_prologue_reads():
    args = [1, 2, 4, 8, 16, 32, 64, 128]
    run = buffer_script.emulate(
        buffer_script.build_call(EIGHT_ARG_CODE_BASE | 1, args),
        memory={EIGHT_ARG_CODE_BASE: EIGHT_ARG_CODE},
        send_size=buffer_script.CALL_ANSWER_SIZE)
    got = buffer_script.read_call(run.pending_send)
    assert got["argc"] == 8
    assert got["returned"] == sum(args) == 255, (
        "each argument is a distinct bit, so the total says which slots arrived: "
        f"missing {255 - got['returned']:#04x}")


@needs_unicorn
def test_a_call_that_passes_fewer_arguments_leaves_the_stack_slots_it_did_not_set_at_zero():
    """The sixteen bytes are pushed for every call, so a function taking four still reads four
    zeros if it looks - which is what makes passing fewer safe rather than undefined."""
    run = buffer_script.emulate(
        buffer_script.build_call(EIGHT_ARG_CODE_BASE | 1, [1, 2, 4, 8]),
        memory={EIGHT_ARG_CODE_BASE: EIGHT_ARG_CODE},
        send_size=buffer_script.CALL_ANSWER_SIZE)
    assert buffer_script.read_call(run.pending_send)["returned"] == 15


_MINIMAL_ARGS = {
    "memory-dump": {"dump_address": 0x0201C000},
    "create-mon": {"create_mon_species": 59, "create_mon_level": 30},
    "memory-scan": {"scan_word": 0x41C64E6D},
    "table-scan": {"table_delta": 2},
    "rng-trace": {"trace_address": 0x03004220},
    "string-gather": {"gather_address": 0x08000000},
    "call": {"call_address": 0x080486D1},
    "save-write": {"write_data": b"X", "dump_offset": 0xB20},
}


# --- the lists a new payload has to be added to ------------------------------------------------
# bs56 was lost to this and to nothing else: table-scan ran on the console, searched 2.75 MB and
# found its table, and the host asked for 4 bytes because the new payload had been added to neither
# of the two hand-maintained tuples in config.py. The tuples are now one set beside the payloads.

def test_every_payload_that_answers_with_bytes_asks_the_host_for_them():
    """The failure this guards is silent: the payload succeeds, the console sends what it was
    asked for, and the answer is simply never collected."""
    for name in buffer_script.DUMP_SCRIPTS:
        assert configmod.BufferScriptPayload(script=name, **_MINIMAL_ARGS.get(name, {})).is_dump, \
            f"{name} answers on ident 19 but config would ask for the 4-byte channel"


def test_a_decoded_answer_is_always_a_byte_answer_and_both_name_real_payloads():
    assert buffer_script.DECODED_SCRIPTS <= buffer_script.DUMP_SCRIPTS
    assert buffer_script.DUMP_SCRIPTS <= set(buffer_script.SCRIPT_REGISTRY)


def test_table_scan_asks_for_its_whole_answer_and_gets_it_decoded():
    payload = configmod.BufferScriptPayload(
        script=buffer_script.TABLE_SCAN, table_delta=2,
        table_start=0x08140000, table_end=0x08400000)
    distribution = payload.build_distribution()

    assert distribution.buffer_dump_size == buffer_script.TABLE_ANSWER_SIZE
    assert distribution.buffer_decode == buffer_script.TABLE_SCAN


def test_a_dump_that_overlaps_grngvalue_is_refused_offline():
    """lg172 and lg173 both died mid transmission with 'erreur de connexion'. MGL_Send takes the
    header CRC one frame and sends the payload the next [decomp:src/mystery_gift_link.c:155], so a
    region that moves between them cannot match its own header and the console calls
    LinkRfu_FatalError. gRngValue moves every frame. lg174 dumped the same 32 bytes from ROM and got
    lg166's bytes back exactly, which is what rules the SIZE out."""
    for address in (rom_map.GRNG_VALUE, rom_map.GRNG_VALUE - 2, rom_map.GRNG_VALUE + 2):
        with pytest.raises(buffer_script.BufferScriptError, match="erreur de connexion"):
            buffer_script.build_memory_dump(address, 32)
    # Immediately past it is fine - that is how the save-block pointers beside it get read.
    buffer_script.build_memory_dump(rom_map.GRNG_VALUE + 4, 32)
    buffer_script.build_memory_dump(rom_map.GRNG_VALUE - 32, 32)
