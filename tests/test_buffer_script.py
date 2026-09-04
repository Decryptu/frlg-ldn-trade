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
    buffer_script, host_mystery_gift, mg_script, mg_server, stamp_rally,
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
