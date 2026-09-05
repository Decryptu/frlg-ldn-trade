"""NATIVE CODE IN THE OVERWORLD: a RAM script that stages a THUMB stub and `callnative`s it.

The stub is EXECUTED here, not asserted about - unicorn on a model of the GBA memory map, the same
rule asm/*.s lives under - and what its answer is checked against is `rng_countdown`, the model
that predicted seven fields of a mon the console built from a state it chose for itself
(mev11/bs58). Two independent things agreeing, rather than one restating the other.
"""

import os
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import lcg, native_script, rng_countdown, rng_script, rom_map  # noqa: E402
from frlgsim.field_stubs import STUBS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import unicorn  # noqa: F401
    _HAVE_UNICORN = True
except ImportError:
    _HAVE_UNICORN = False
needs_unicorn = pytest.mark.skipif(not _HAVE_UNICORN,
                                   reason="offline execution needs unicorn")

# The console's own, read off it: trainer-id-probe (bs04) returned 0xE5BBDF65, and the player's
# trainer card shows 57189 = 0xDF65. Not chosen here.
CONSOLE_TID = 0xDF65
CONSOLE_SID = 0xE5BB
_SAV2 = 0x02030000


def _run(state, *, cap=1 << 18):
    """The stub, run on a memory model that carries a SaveBlock2 it has to find for itself."""
    save = bytearray(0x10)
    save[0x0A:0x0C] = CONSOLE_TID.to_bytes(2, "little")
    save[0x0C:0x0E] = CONSOLE_SID.to_bytes(2, "little")
    code = native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                              sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=cap)
    return native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: int(state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    })


# --- the commands, against the decomp's own table -----------------------------------------------

def test_the_opcodes_are_the_ones_in_the_script_command_table():
    """[decomp:data/script_cmd_table.inc]. A wrong opcode here is a wrong command on the console."""
    assert native_script.SCR_CALLNATIVE == 0x23
    assert native_script.SCR_SETPTR == 0x11
    assert native_script.SCR_SETWILDBATTLE == 0xB6
    assert native_script.SCR_DOWILDBATTLE == 0xB7


def test_callnative_sets_bit_zero_because_the_stubs_are_thumb():
    """`callnative` calls through a function pointer, so bit 0 chooses the instruction set. A
    word-aligned address would enter ARM state and run the same bytes as garbage."""
    assert native_script.callnative_at(0x0201C000) == bytes.fromhex("2301c00102")
    assert native_script.callnative_at(0x0201C000, thumb=False)[1] == 0x00
    with pytest.raises(native_script.NativeScriptError):
        native_script.callnative_at(0x0201C001)         # the caller passes the address, not the bit


def test_staging_is_six_script_bytes_per_payload_byte():
    staged = native_script.stage(b"\xAA\xBB", 0x0201C000)
    assert len(staged) == 2 * native_script.SETPTR_SIZE
    assert staged[:6] == rng_script.setptr(0xAA, 0x0201C000)
    assert staged[6:] == rng_script.setptr(0xBB, 0x0201C001)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stage(b"")


def test_the_budget_is_computed_from_the_two_sizes_and_not_written_down():
    plan = native_script.budget(72, other=7)
    assert plan["staged_bytes"] == 72 * 6
    assert plan["total"] == 72 * 6 + native_script.CALLNATIVE_SIZE + 7
    assert plan["limit"] == rng_script.MAX_RAM_SCRIPT_SIZE == 995
    assert plan["fits"] and plan["max_code_size"] == (995 - 5 - 7) // 6


def test_a_stub_too_big_to_stage_is_refused_offline(monkeypatch):
    """995 bytes of RAM script at six a byte is ~163 bytes of code, and this is the only budget
    that binds. It has to fail HERE and not in the middle of the player's game."""
    assert not native_script.budget(200)["fits"]
    oversized = dict(STUBS)
    code, digest, symbols = oversized["shiny-seek"]
    oversized["shiny-seek"] = (code + b"\x00" * 128, digest, symbols)
    monkeypatch.setattr(native_script, "STUBS", oversized)
    with pytest.raises(native_script.NativeScriptError, match="will not fit"):
        native_script.build_shiny_hunt_script(132, 50)


# --- the stub's parameters ----------------------------------------------------------------------

def test_the_pool_offsets_come_from_the_assembler():
    """A parameter that moves in the .s must be a KeyError here, never a silently wrong word."""
    _code, _digest, symbols = STUBS["shiny-seek"]
    assert {"p_rng", "p_mult", "p_add", "p_sav2ptr", "p_cap"} <= set(symbols)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stub("shiny-seek", nonesuch=1)
    with pytest.raises(native_script.NativeScriptError):
        native_script.stub("no-such-stub")


def test_patching_writes_the_word_where_the_symbol_says():
    code = native_script.stub("shiny-seek", rng=0x03004220, sav2ptr=0x0300422C, cap=99)
    _raw, _digest, symbols = STUBS["shiny-seek"]
    for key, value in (("rng", 0x03004220), ("sav2ptr", 0x0300422C), ("cap", 99)):
        offset = symbols[f"p_{key}"]
        assert int.from_bytes(code[offset:offset + 4], "little") == value
    # The constants the stub does NOT take as parameters are the LCG's own, and they are the
    # decomp's [include/random.h].
    assert int.from_bytes(code[symbols["p_mult"]:symbols["p_mult"] + 4], "little") == lcg.RAND_MULT
    assert int.from_bytes(code[symbols["p_add"]:symbols["p_add"] + 4], "little") == lcg.RAND_ADD


def test_the_committed_stub_bytes_are_what_the_source_assembles_to():
    if shutil.which("arm-none-eabi-as") is None:
        pytest.skip("no GBA toolchain")
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "gen_field_stubs.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- the script -----------------------------------------------------------------------------

def test_the_hunt_script_stages_calls_and_then_battles_in_that_order():
    script = native_script.build_shiny_hunt_script(132, 50)
    lines = native_script.describe(script)
    assert "UNKNOWN" not in "".join(lines)
    assert lines[0].startswith("  setptr x80")
    assert lines[1] == "  callnative 0x0201C001 (THUMB)"
    assert lines[2].startswith("  setwildbattle species 132 Lv50")
    assert lines[3].startswith("  dowildbattle")
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_nothing_between_the_call_and_the_generation_can_yield():
    """The whole point. `setptr` and `callnative` return FALSE and `setwildbattle` returns FALSE
    [decomp:src/scrcmd.c], so the field engine runs the lot in ONE frame and the state the stub
    leaves is the state CreateScriptedWildMon consumes. Anything that yields between them - a
    playse/waitse, a message - would let the per-frame consumer turn the RNG and break it."""
    script = native_script.build_shiny_hunt_script(132, 50)
    code_size = len(native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                                       sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=1 << 18))
    call = code_size * native_script.SETPTR_SIZE          # the staged run ends, callnative begins
    assert script[call] == native_script.SCR_CALLNATIVE
    # Everything from the call to the generation, byte for byte. No room for anything that yields.
    assert script[call:] == (native_script.callnative_at(native_script.SCRATCH)
                             + bytes([native_script.SCR_SETWILDBATTLE]) + (132).to_bytes(2, "little")
                             + bytes([50]) + (0).to_bytes(2, "little")
                             + bytes([native_script.SCR_DOWILDBATTLE]) + rng_script.BATTLE_TAIL)


def test_the_species_and_level_are_checked_before_a_console_ever_sees_them():
    for bad in ({"species": 0}, {"species": 999}, {"level": 0}, {"level": 200}, {"cap": 0}):
        kwargs = {"species": 132, "level": 50, **bad}
        with pytest.raises(native_script.NativeScriptError):
            native_script.build_shiny_hunt_script(**kwargs)
    with pytest.raises(native_script.NativeScriptError):
        native_script.build_shiny_hunt_script(132, 50, item=0x10000)


# --- the stub, executed ---------------------------------------------------------------------

@needs_unicorn
@pytest.mark.parametrize("state", [
    0x52E6B438, 0xF2A74DE4, 0x269E0D37, 0x6513270E, 0xA6A3A450, 0x0C5C7FD0,
    0x128B2F33, 0xD23F0824, 0x892F902B, 0x1818E811, 0x5D9DC9F8, 0x9531985D,
])
def test_the_stub_lands_on_a_state_whose_encounter_is_shiny(state):
    """The stub searches; `rng_countdown` - validated on hardware by mev11/bs58 - says what the
    console would build from what it found. The two are written from different directions."""
    landed = int.from_bytes(_run(state)["memory"][rom_map.GRNG_VALUE], "little")
    mon = rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"], f"0x{state:08X} -> 0x{landed:08X} is not shiny"
    assert mon["shiny_value"] < native_script.SHINY_ODDS
    # It only ever moves FORWARD along the orbit, and not far: 1 state in 8192 is shiny.
    assert lcg.distance(state, landed) < 1 << 17


@needs_unicorn
def test_the_trainer_id_is_read_off_the_console_and_actually_used():
    """The stub dereferences gSaveBlock2Ptr rather than being handed an id, so the same bytes work
    on either console. This is the test that would catch it reading and then ignoring: a different
    trainer id must send the search somewhere else, and each answer must be shiny for ITS OWN pair
    and not for the other."""
    state = 0x52E6B438
    other_tid, other_sid = 0x1234, 0x5678
    save = bytearray(0x10)
    save[0x0A:0x0C] = other_tid.to_bytes(2, "little")
    save[0x0C:0x0E] = other_sid.to_bytes(2, "little")
    code = native_script.stub("shiny-seek", rng=rom_map.GRNG_VALUE,
                              sav2ptr=rom_map.GSAVEBLOCK2PTR, cap=1 << 18)
    result = native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: state.to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    })
    theirs = int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little")
    ours = int.from_bytes(_run(state)["memory"][rom_map.GRNG_VALUE], "little")
    assert theirs != ours
    assert rng_countdown._mon_from(theirs, other_tid, other_sid)["shiny"]
    assert not rng_countdown._mon_from(theirs, CONSOLE_TID, CONSOLE_SID)["shiny"]
    assert rng_countdown._mon_from(ours, CONSOLE_TID, CONSOLE_SID)["shiny"]


@needs_unicorn
def test_the_stub_leaves_the_rng_untouched_when_the_cap_runs_out():
    """A bounded search that fails must change NOTHING - the player gets an ordinary encounter,
    which is a miss and not a broken game."""
    state = 0x12345678
    assert not rng_countdown._mon_from(state, CONSOLE_TID, CONSOLE_SID)["shiny"]
    result = _run(state, cap=4)
    assert int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little") == state


@needs_unicorn
def test_the_stub_returns_and_the_run_says_how_long_it_blocked_for():
    """There is no menu to back out of in the overworld, so a stub that does not return is a frozen
    game. `emulate` refuses one instead of returning a result."""
    result = _run(0x52E6B438)
    assert result["instructions"] > 0
    # An estimate from the GBA's clock, not a hardware measurement - see the module.
    assert native_script.frames_for(result["instructions"]) < 60


@needs_unicorn
def test_a_stub_that_never_returns_is_refused_rather_than_run():
    forever = bytes.fromhex("fee7")                      # b .   (Thumb, branch to itself)
    with pytest.raises(native_script.NativeScriptError):
        native_script.emulate(forever, instruction_limit=1000)


def test_the_script_does_not_fall_off_the_end_after_the_battle():
    """mev11's unexplained second wild battle. `StartScriptedWildBattle` sets savedCallback to
    CB2_EndScriptedWildBattle, which ends in CB2_ReturnToFieldContinueScriptPlayMapMusic
    [decomp:src/overworld.c:1670] - CONTINUE SCRIPT - so the field engine RESUMES at the byte after
    dowildbattle. Nothing there means opcode 0x00 (nop) through the rest of the 995-byte body and
    then off the end into SaveBlock1, executing the player's save as bytecode. 0xB6/0xB7 occur in
    save data like any other bytes, which is a second wild battle out of nowhere."""
    for script in (native_script.build_shiny_hunt_script(132, 50),
                   rng_script.build_wild_battle_script(0xC0DE, 132, 50)):
        assert script[-3:] == bytes([native_script.SCR_DOWILDBATTLE,
                                     native_script.SCR_RELEASEALL, rng_script.SCR_END])


# --- the three untried Mystery Event opcodes, in one card ----------------------------------------

def test_the_opcode_sweep_runs_all_three_and_the_order_is_the_experiment():
    """ONE status comes back and `setstatus` writes the same field every opcode writes
    (ctx->data[2]) [decomp:src/mystery_event_script.c], so the last thing to run decides the answer.
    Markers go AFTER each opcode; setenigmaberry goes last because its own status tells success
    (2) from failure (1)."""
    from frlgsim import mystery_event, wonder_card_events as w
    script = w.MEVENT_SWEEP_GIFT.mevent
    result = mystery_event.run(script)
    assert result.status == mystery_event.STATUS_SUCCESS
    kinds = [effect[0] for effect in result.effects]
    assert kinds.index("addrareword") < kinds.index("addtrainer") < kinds.index("setenigmaberry")


def test_the_sweep_berry_validates_and_keeps_the_cartridge_own_description_pointers():
    """IsEnigmaBerryValid needs stageDuration and maxYield nonzero [decomp:src/berry.c:984]; the
    checksum is recomputed by SetEnigmaBerry, so we do not have to produce one. The two ROM pointers
    are NOT invented - bs59 read them out of gSaveBlock1Ptr->enigmaBerry. They live in the save for
    ever and the Berry Pouch dereferences them to print the description."""
    from frlgsim import wonder_card_events as w
    berry = w.build_sweep_berry()
    assert len(berry) == 28
    assert berry[10] != 0 and berry[20] != 0, "maxYield and stageDuration decide validity"
    assert int.from_bytes(berry[12:16], "little") == w.MEVENT_SWEEP_BERRY_DESC1
    assert int.from_bytes(berry[16:20], "little") == w.MEVENT_SWEEP_BERRY_DESC2
