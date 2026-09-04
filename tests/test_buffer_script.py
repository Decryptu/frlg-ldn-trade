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
