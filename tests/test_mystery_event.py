"""The Mystery Event VM: the assembler, the chain rule that makes it usable without ``checkcompat``,
and the return channel it opens back from the console.

The end-to-end tests drive the ConsoleClientModel from tests/test_mystery_gift_flow.py, whose
Mystery Event interpreter is written from the decomp rather than from ``frlgsim.mystery_event``, so
agreement between the two is evidence and not a tautology.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    ereader_trainer, gift_registry, host_mystery_gift, mg_script, mg_server, mystery_event,
    stamp_rally, wonder_card_events, wonder_news,
)
from test_mystery_gift_flow import ConsoleClientModel, _drive  # noqa: E402


# --- the assembler --------------------------------------------------------------------------

def test_reproduces_the_hardware_proven_stamp_activation_shape():
    """The stamp rally's activation script has been landing on both French consoles since session
    22. Assembling the same runscript/end pair must produce the same six bytes of code and put the
    embedded field script at the same offset."""
    proven = stamp_rally.build_stamp_activation_script(
        stamp_rally.VAR_MYSTERY_GIFT_1, install=False)
    embedded = proven[6:]

    script = mystery_event.MysteryEventScript()
    blob = script.blob(embedded, align=1)
    script.runscript(blob).end()

    assert script.assemble() == proven
    assert blob.offset == 6
    assert mystery_event.describe(proven) == "runscript 6; end"


def test_pointer_operands_are_offsets_into_our_own_buffer():
    """data[1] is 0 without checkcompat, so an operand of N means N bytes from the start of what we
    sent [decomp:src/mystery_event_script.c:52]."""
    script = mystery_event.MysteryEventScript()
    mon = script.blob(b"\xAA" * mystery_event.POKEMON_SIZE)
    script.givepokemon(mon).end()
    built = script.assemble()

    (opcode, name, operands), _end = mystery_event.decode(built)
    assert name == "givepokemon"
    assert operands[0] == mon.offset
    assert built[mon.offset:mon.offset + 4] == b"\xAA" * 4


def test_blobs_are_placed_after_the_code_and_aligned():
    script = mystery_event.MysteryEventScript()
    first = script.blob(b"\x01\x02\x03")            # 3 bytes: the next blob must still land on 4
    second = script.blob(b"\x04")
    script.runscript(first).setmsg(0xFF, second).end()
    built = script.assemble()

    assert first.offset % 4 == 0 and second.offset % 4 == 0
    assert first.offset >= 10                        # past runscript(5) + setmsg(6) + end(1)
    assert built[first.offset:first.offset + 3] == b"\x01\x02\x03"
    assert built[second.offset] == 4


def test_a_script_must_end_in_a_terminal_command():
    script = mystery_event.MysteryEventScript()
    script.givenationaldex()
    with pytest.raises(mystery_event.MysteryEventError, match="terminal"):
        script.assemble()


def test_nothing_may_follow_a_terminal_command():
    script = mystery_event.MysteryEventScript()
    script.end()
    with pytest.raises(mystery_event.MysteryEventError, match="never run"):
        script.givenationaldex()


def test_checkcompat_is_the_one_command_execution_can_resume_after():
    script = mystery_event.MysteryEventScript()
    script.checkcompat(0, 1, 1, 1, 1)
    script.givenationaldex().end()                   # allowed: checkcompat sets data[3]
    assert mystery_event.describe(script.assemble()).startswith("checkcompat")


def test_ribbon_index_is_capped_at_the_last_real_entry():
    """GiveGiftRibbonToParty accepts index < 11 but sGiftRibbonsMonDataIds has seven entries; 7..10
    SetMonData a field id read from uninitialised stack [decomp:src/pokemon_size_record.c:193]."""
    script = mystery_event.MysteryEventScript()
    script.giveribbon(6, 1)
    with pytest.raises(mystery_event.MysteryEventError):
        script.giveribbon(7, 1)


def test_a_script_larger_than_the_receive_buffer_is_refused():
    script = mystery_event.MysteryEventScript()
    script.runscript(script.blob(b"\x00" * mystery_event.MAX_SCRIPT_SIZE)).end()
    with pytest.raises(mystery_event.MysteryEventError, match="receive buffer"):
        script.assemble()


def test_decode_stops_where_the_console_would_stop():
    script = mystery_event.MysteryEventScript()
    script.givenationaldex().end()
    built = script.assemble() + b"\x09\x09\x09"      # stale bytes after the end
    assert mystery_event.describe(built) == "givenationaldex; end"


def test_calc_helpers_match_the_decomp():
    assert mystery_event.calc_byte_array_sum(b"\x01\x02\xFF") == 0x102
    assert mystery_event.calc_crc16(b"") == (~0x1121) & 0xFFFF


# --- the runner -----------------------------------------------------------------------------

def test_the_chain_runs_every_command_up_to_the_first_yield():
    script = mystery_event.MysteryEventScript()
    script.givenationaldex().addrareword(3).giveribbon(0, 5).setstatus(99).end()
    result = mystery_event.run(script.assemble())

    assert result.ran == 5 and result.stopped_at == "end"
    assert result.status == 99
    assert [effect[0] for effect in result.effects] == [
        "givenationaldex", "addrareword", "giveribbon"]


def test_a_dead_opcode_stops_the_chain_and_reports_incompatible():
    """setrecordmixinggift and enableresetrtc both call SetIncompatible and return TRUE with
    data[3] cleared [decomp:src/mystery_event_script.c:227]."""
    built = bytes([mystery_event.ME_SETRECORDMIXINGGIFT, mystery_event.ME_GIVENATIONALDEX,
                   mystery_event.ME_END])
    result = mystery_event.run(built)
    assert result.status == mystery_event.STATUS_INCOMPATIBLE
    assert result.effect("givenationaldex") is None


def test_givepokemon_reports_a_full_party_instead_of_overwriting_one():
    script = mystery_event.MysteryEventScript()
    script.givepokemon(script.blob(b"\x11" * (mystery_event.POKEMON_SIZE
                                              + mystery_event.MAIL_SIZE))).end()
    built = script.assemble()

    assert mystery_event.run(built, party_count=5).status == mystery_event.STATUS_SUCCESS
    assert mystery_event.run(built, party_count=6).status == mystery_event.STATUS_INCOMPATIBLE


def test_checksum_leaves_a_matching_status_alone_and_flags_a_mismatch():
    script = mystery_event.MysteryEventScript()
    probe = script.blob(b"PROBE")
    script.setstatus(42).checksum(probe)
    assert mystery_event.run(script.assemble()).status == 42

    corrupted = bytearray(script.assemble())
    corrupted[probe.offset] ^= 0xFF
    assert mystery_event.run(bytes(corrupted)).status == mystery_event.STATUS_FAILED


def test_the_enigma_berry_tail_falls_outside_the_receive_buffer():
    """struct ReceivedEnigmaBerry puts itemEffect 1302 bytes in, past the console's 1024-byte
    buffer, so only the 28-byte Berry2 can be set from this link [decomp:src/berry.c:944]."""
    blob = mystery_event.build_enigma_berry_blob(b"\x01" * 28)
    assert len(blob) == mystery_event.ENIGMA_BERRY_ITEM_EFFECT_OFFSET + 20
    assert len(blob) > mystery_event.MAX_SCRIPT_SIZE

    script = mystery_event.MysteryEventScript()
    script.setenigmaberry(script.blob(b"\x01" * 28)).end()
    result = mystery_event.run(script.assemble())
    assert result.effect("read_past_buffer") is not None


# --- the wired-up gift ----------------------------------------------------------------------

def test_the_probe_script_is_what_the_registry_ships():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-probe")
    assert distribution.has_mevent
    assert mystery_event.describe(distribution.mevent) == (
        "givenationaldex; setstatus 42; checksum 1026, 16, 31")
    result = mystery_event.run(distribution.mevent)
    assert result.status == wonder_card_events.MEVENT_PROBE_STATUS
    assert result.effect("givenationaldex") is not None


def test_the_client_script_runs_the_event_and_then_ships_its_status_back():
    """CLI_RUN_MEVENT_SCRIPT leaves ctx->data[2] in client->param and CLI_LOAD_TOSS_RESPONSE loads
    exactly client->param, so these three in this order are the return channel."""
    commands = [
        int.from_bytes(mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT[i:i + 4], "little")
        for i in range(0, len(mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT), 8)]
    run_at = commands.index(mg_script.CLI_RUN_MEVENT_SCRIPT)
    assert commands[run_at + 1] == mg_script.CLI_LOAD_TOSS_RESPONSE
    assert commands[run_at + 2] == mg_script.CLI_SEND_LOADED


def test_a_server_refuses_a_script_the_console_would_run_off_the_end_of():
    card, ram_script = _probe_card()
    with pytest.raises(mg_server.MysteryGiftServerError, match="terminal"):
        mg_server.MysteryGiftServer(
            card, ram_script, mevent=bytes([mystery_event.ME_GIVENATIONALDEX]))


def test_a_mystery_event_cannot_share_a_session_with_news_or_a_trainer():
    script = mystery_event.MysteryEventScript()
    script.end()
    built = script.assemble()
    with pytest.raises(ValueError, match="Wonder News cannot carry"):
        stamp_rally.MysteryGiftDistribution(
            None, None, news=wonder_news.build_news(wonder_news.DEFAULT_NEWS), mevent=built)
    card, ram_script = _probe_card()
    with pytest.raises(ValueError, match="cannot share a session"):
        stamp_rally.MysteryGiftDistribution(
            card, ram_script, trainer=ereader_trainer.build("red"), mevent=built)


def _probe_card():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-probe")
    return distribution.card, distribution.ram_script


# --- end to end against the console model ---------------------------------------------------

def test_end_to_end_a_console_with_no_card_takes_the_card_and_runs_the_event():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-probe")
    console = ConsoleClientModel(flag_id=0)
    engine, _frames = _drive(console, distribution=distribution)

    assert console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert engine.result == mg_server.SVR_MSG_CARD_SENT and engine.gift_sent
    assert engine.state == host_mystery_gift.MG_DONE
    assert console.saved_card == distribution.card
    # The console ran our bytecode ...
    assert console.national_dex is True
    assert console.activation_scripts and console.activation_scripts[0][:len(distribution.mevent)] \
        == distribution.mevent
    # ... and the status it left came back to us over MG_LINKID_RESPONSE.
    assert engine.server.mevent_status == wonder_card_events.MEVENT_PROBE_STATUS


def test_end_to_end_a_console_holding_the_same_card_runs_the_event_alone():
    """HAS_SAME_CARD sends no card and no delivery script, so re-running an event costs the player
    nothing and prompts for nothing."""
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-probe")
    console = ConsoleClientModel(flag_id=wonder_card_events.MEVENT_PROBE_FLAG_ID)
    engine, _frames = _drive(console, distribution=distribution)

    assert engine.result == mg_server.SVR_MSG_CARD_SENT
    assert console.saved_card is None
    assert console.national_dex is True
    assert engine.server.mevent_status == wonder_card_events.MEVENT_PROBE_STATUS


def test_end_to_end_a_console_holding_another_card_is_asked_before_anything_runs():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-probe")
    console = ConsoleClientModel(flag_id=1005)
    console.toss_answer = 1                          # the player keeps the card they have
    engine, _frames = _drive(console, distribution=distribution)

    assert engine.result == mg_server.SVR_MSG_CLIENT_CANCELED
    assert console.national_dex is False
    assert engine.server.mevent_status is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
