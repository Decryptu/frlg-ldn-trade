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
    assert lines[3].startswith("  setvar 0x8000")
    assert lines[4].startswith("  goto 0x020370B4")
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
                             + rng_script.battle_and_exit(132, 50))


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


def test_the_battle_never_starts_from_inside_the_save_block():
    """mev18, and it is the sharpest rule this project has about RAM scripts.

    `CB2_InitBattle` and `InitOverworldBgs` both call `MoveSaveBlocks_ResetHeap`
    [decomp:src/battle_main.c:614, src/overworld.c:1337], which re-rolls gSaveBlock1's address by
    a multiple of 4 in 0..124 [SAVEBLOCK_MOVE_RANGE, src/load_save.c:75]. The engine holds the RAM
    script by a POINTER INTO THAT BLOCK, so after a battle it resumes at an address the script no
    longer occupies - `releaseall` + `end` written after dowildbattle are simply not there. mev11's
    stray second battle, mev15/mev16 walking away clean and mev18 freezing the overworld dead are
    all the same mechanism landing in different places.

    So no builder may leave `dowildbattle` in the body: the battle is started from
    gSpecialVar_0x8000, which does not move, and the `end` the engine returns to sits beside it."""
    cases = ((native_script.build_shiny_hunt_script(132, 50), 132, 50),
             (native_script.build_mon_hunt_script(129, 5), 129, 5),
             (rng_script.build_wild_battle_script(0xC0DE, 132, 50), 132, 50))
    for script, species, level in cases:
        # The tail, byte for byte: setwildbattle, the two bytes of the trampoline, and the jump
        # out of the save block. 0xB7 still occurs in the body as DATA - it is half of the word
        # setvar writes - so the check is on the command stream and not on the bytes.
        assert script.endswith(rng_script.battle_and_exit(species, level))
        assert script.endswith(bytes([rng_script.SCR_GOTO])
                               + rng_script.TRAMPOLINE_ADDRESS.to_bytes(4, "little"))
    assert rng_script.TRAMPOLINE_WORD == (native_script.SCR_DOWILDBATTLE
                                          | (rng_script.SCR_END << 8))
    # Read back as commands rather than as bytes: nothing in a body IS a dowildbattle.
    for script, _species, _level in cases[:2]:
        lines = native_script.describe(script)
        # The only mention left is inside the setvar's annotation, which is the trampoline itself.
        assert not any(line.strip().startswith("dowildbattle") for line in lines), lines
        assert "UNKNOWN" not in "".join(lines)


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


# --- mon-seek: the whole mon, not just the shine -------------------------------------------------

def _mon_run(state, criteria, *, cap=None, tid=CONSOLE_TID, sid=CONSOLE_SID,
             instruction_limit=1 << 26):
    save = bytearray(0x10)
    save[0x0A:0x0C] = tid.to_bytes(2, "little")
    save[0x0C:0x0E] = sid.to_bytes(2, "little")
    code = native_script.stub(
        "mon-seek", rng=rom_map.GRNG_VALUE, sav2ptr=rom_map.GSAVEBLOCK2PTR,
        cap=native_script.cap_for(criteria) if cap is None else cap,
        nature=criteria.nature_mask, ivmin=criteria.iv_word)
    result = native_script.emulate(code, memory={
        rom_map.GRNG_VALUE: int(state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    }, instruction_limit=instruction_limit)
    return (int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little"),
            result["instructions"])


def _accepts(mon, criteria):
    """The criteria read against `rng_countdown`'s mon, which is written from the other side."""
    return (mon["shiny"]
            and (not criteria.natures or mon["nature"] in criteria.natures)
            and all(iv >= floor for iv, floor in zip(mon["ivs"], criteria.iv_minimums)))


def test_the_packed_words_are_what_the_stub_reads():
    """p_nature is a bit per nature and p_ivmin six 5-bit floors PLUS the terminator the loop
    counts with: without bit 30 the IV loop in asm/field/mon-seek.s never ends, and a stub that
    never ends is a frozen overworld."""
    criteria = native_script.MonCriteria(natures=(0, 24), iv_minimums=(1, 2, 3, 4, 5, 6))
    assert criteria.nature_mask == (1 << 0) | (1 << 24)
    assert native_script.MonCriteria().nature_mask == native_script.ANY_NATURE == (1 << 25) - 1
    word = criteria.iv_word
    assert word & (1 << native_script.IV_TERMINATOR_BIT)
    assert [(word >> (5 * i)) & 31 for i in range(6)] == [1, 2, 3, 4, 5, 6]
    assert native_script.MonCriteria().iv_word == 1 << native_script.IV_TERMINATOR_BIT


def test_the_criteria_are_checked_before_a_console_ever_sees_them():
    for bad in ({"natures": (25,)}, {"natures": (-1,)}, {"iv_minimums": (0, 0, 0, 0, 0, 32)},
                {"iv_minimums": (0, 0, 0)}):
        with pytest.raises(native_script.NativeScriptError):
            native_script.MonCriteria(**bad)


def test_natures_and_iv_floors_are_parsed_by_the_names_the_game_uses():
    assert native_script.parse_natures("adamant, Jolly") == (3, 13)
    assert native_script.parse_natures("3 13") == (3, 13)
    assert native_script.parse_natures(None) == ()
    assert native_script.parse_iv_minimums(["speed=31", "atk>=20"]) == (0, 20, 0, 31, 0, 0)
    for bad in (["nonesuch=1"], ["speed=32"], ["speed=x"]):
        with pytest.raises(native_script.NativeScriptError):
            native_script.parse_iv_minimums(bad)
    with pytest.raises(native_script.NativeScriptError):
        native_script.parse_natures("brisk")


def test_the_iv_names_are_in_the_order_the_rom_draws_them():
    """NOT the order a summary screen shows. `rng_countdown._mon_from` unpacks the two IV draws in
    this order [decomp:src/pokemon.c:1836], and a floor named `speed` that landed on SPATK would
    be invisible in every offline check that did not compare the two lists."""
    assert native_script.IV_FIELDS == ("hp", "attack", "defense",
                                       "speed", "sp_attack", "sp_defense")


def test_what_a_criterion_costs_is_arithmetic_and_not_a_guess():
    plain = native_script.MonCriteria()
    assert plain.probability == pytest.approx(native_script.SHINY_ODDS / 65536)
    nature = native_script.MonCriteria(natures=(3,))
    assert nature.probability == pytest.approx(plain.probability / 25)
    floored = native_script.MonCriteria(iv_minimums=(0, 0, 0, 16, 0, 0))
    assert floored.probability == pytest.approx(plain.probability / 2)
    # The cap is the one that finds a state SEARCH_CONFIDENCE of the time, and nothing else.
    cap = native_script.cap_for(nature)
    assert native_script.search_cost(nature, cap)["found_within_cap"] >= 0.99
    assert native_script.search_cost(nature, cap - 1)["found_within_cap"] < 0.99


def test_a_search_that_would_freeze_the_overworld_too_long_is_refused():
    """A criterion never slows an iteration down, it multiplies how many are needed - so the cap
    is what bounds the freeze, and the freeze is what the player sees."""
    greedy = native_script.MonCriteria(natures=(3,), iv_minimums=(0, 31, 0, 31, 0, 0))
    with pytest.raises(native_script.NativeScriptError, match="ceiling"):
        native_script.build_mon_hunt_script(132, 50, criteria=greedy)
    # Raising the ceiling is a decision, so it is an argument: the same criteria then build.
    script = native_script.build_mon_hunt_script(132, 50, criteria=greedy,
                                                 max_freeze_frames=10 ** 9, cap=1 << 24)
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_the_mon_hunt_script_stages_calls_and_then_battles_like_the_shiny_one():
    script = native_script.build_mon_hunt_script(132, 50)
    lines = native_script.describe(script)
    assert "UNKNOWN" not in "".join(lines)
    assert lines[0].startswith("  setptr x160")
    assert lines[1] == "  callnative 0x0201C001 (THUMB)"
    assert lines[2].startswith("  setwildbattle species 132 Lv50")
    assert lines[-1].startswith("  goto 0x020370B4")
    assert len(script) <= rng_script.MAX_RAM_SCRIPT_SIZE


def test_the_bigger_stub_still_fits_the_only_budget_that_binds():
    """160 bytes of the 163 a 995-byte RAM script allows. The margin is three bytes, so this is
    the test that fails first when the stub grows."""
    code = native_script.stub("mon-seek")
    plan = native_script.budget(len(code), other=9)
    assert plan["fits"] and plan["spare"] >= 0
    _raw, _digest, symbols = STUBS["mon-seek"]
    assert {"p_rng", "p_mult", "p_add", "p_sav2ptr", "p_cap",
            "p_nature", "p_ivmin"} <= set(symbols)


@needs_unicorn
@pytest.mark.parametrize("state", [0x52E6B438, 0xF2A74DE4, 0x269E0D37, 0x6513270E])
@pytest.mark.parametrize("criteria", [
    native_script.MonCriteria(),
    native_script.MonCriteria(natures=(3,)),
    native_script.MonCriteria(natures=(3, 13), iv_minimums=(0, 0, 0, 20, 0, 0)),
    native_script.MonCriteria(iv_minimums=(24, 0, 0, 0, 0, 0)),
], ids=["shiny", "nature", "two-natures-and-speed", "hp-floor"])
def test_the_stub_lands_on_the_first_state_that_satisfies_everything_asked_for(state, criteria):
    """Two independent statements, and the second is the one that catches a filter that is merely
    LOOSE: the state it lands on passes, AND no state between here and there does. A nature test
    that always said yes would pass the first half of this and fail the second."""
    landed, _instructions = _mon_run(state, criteria)
    assert _accepts(rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID), criteria)
    walked = lcg.distance(state, landed)
    assert walked < native_script.cap_for(criteria)
    current = state
    for _ in range(walked):
        assert not _accepts(rng_countdown._mon_from(current, CONSOLE_TID, CONSOLE_SID), criteria)
        current = lcg.advance(current, 1)
    assert current == landed


@needs_unicorn
@pytest.mark.parametrize("index", range(6))
def test_a_floor_lands_on_the_stat_it_names(index):
    """The two IV draws are packed into one 30-bit word for the loop, 15 bits from each, and the
    seam is between DEF and SPEED. A floor that landed one field over would still produce a shiny,
    which is why the check is per stat and against the model rather than against the packing."""
    floors = [0] * 6
    floors[index] = 24
    criteria = native_script.MonCriteria(iv_minimums=tuple(floors))
    landed, _instructions = _mon_run(0x52E6B438, criteria)
    mon = rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID)
    assert mon["shiny"] and mon["ivs"][index] >= 24


@needs_unicorn
def test_the_iteration_cost_the_host_quotes_is_the_one_unicorn_counts():
    """`INSTRUCTIONS_PER_ITERATION` is what every freeze estimate rests on. Measure it instead of
    trusting it: two states, and the count divided by the distance walked."""
    criteria = native_script.MonCriteria()
    for state in (0x52E6B438, 0x6513270E):
        landed, instructions = _mon_run(state, criteria)
        per_iteration = instructions / lcg.distance(state, landed)
        assert per_iteration == pytest.approx(native_script.INSTRUCTIONS_PER_ITERATION, abs=0.5)


@needs_unicorn
def test_the_trainer_id_still_comes_off_the_console_when_the_criteria_are_richer():
    criteria = native_script.MonCriteria(natures=(3, 13))
    ours, _ = _mon_run(0x52E6B438, criteria)
    theirs, _ = _mon_run(0x52E6B438, criteria, tid=0x1234, sid=0x5678)
    assert ours != theirs
    assert _accepts(rng_countdown._mon_from(theirs, 0x1234, 0x5678), criteria)
    assert not rng_countdown._mon_from(theirs, CONSOLE_TID, CONSOLE_SID)["shiny"]


@needs_unicorn
def test_the_richer_stub_also_leaves_the_rng_alone_when_the_cap_runs_out():
    state = 0x12345678
    landed, _instructions = _mon_run(state, native_script.MonCriteria(natures=(3,)), cap=4)
    assert landed == state


def test_the_hunt_card_carries_the_criteria_it_says_it_does():
    """The registry's definition is built with the defaults at import; a host given criteria on
    the command line composes another card rather than mutating that one."""
    from frlgsim import wonder_card_events as w
    default = w.RNG_MON_HUNT_GIFT.mevent
    assert len(default) <= 0x400                     # the console's receive buffer
    other = w.build_rng_mon_hunt_gift(native_script.MonCriteria(natures=(0,))).mevent
    assert other != default and len(other) == len(default)
    assert w.RNG_MON_HUNT_GIFT.card.default_flag_id == w.RNG_MON_HUNT_FLAG_ID
    # The two words the stub reads are the only difference between the two cards.
    differing = [i for i, (a, b) in enumerate(zip(default, other)) if a != b]
    assert 0 < len(differing) <= 4 * native_script.SETPTR_SIZE


@needs_unicorn
def test_the_bytes_the_console_will_actually_be_sent_search_for_what_the_card_says():
    """THE WHOLE CHAIN, from the card down to the CPU, and starting from the bytes that go on the
    air rather than from what we meant to build. The Mystery Event VM is run [mystery_event.run],
    its `initramscript` payload is the field script the console would store, the `setptr` run in it
    is read back into the bytes it stages, and THOSE are what unicorn executes. bs56's family of
    bug - a path that only the live host takes - has no room left here."""
    from frlgsim import mystery_event, wonder_card_events as w

    effects = mystery_event.run(w.RNG_MON_HUNT_GIFT.mevent).effects
    kind, _group, _num, _object, field_script = effects[0]
    assert kind == "initramscript"

    staged, index = bytearray(), 0
    while index < len(field_script) and field_script[index] == native_script.SCR_SETPTR:
        address = int.from_bytes(field_script[index + 2:index + 6], "little")
        assert address == native_script.SCRATCH + len(staged), "the staging must be contiguous"
        staged.append(field_script[index + 1])
        index += native_script.SETPTR_SIZE
    assert field_script[index:index + native_script.CALLNATIVE_SIZE] == \
        native_script.callnative_at(native_script.SCRATCH)

    save = bytearray(0x10)
    save[0x0A:0x0C] = CONSOLE_TID.to_bytes(2, "little")
    save[0x0C:0x0E] = CONSOLE_SID.to_bytes(2, "little")
    state = 0x52E6B438
    result = native_script.emulate(bytes(staged), memory={
        rom_map.GRNG_VALUE: state.to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: _SAV2.to_bytes(4, "little"),
        _SAV2: bytes(save),
    }, instruction_limit=1 << 26)
    landed = int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little")
    assert _accepts(rng_countdown._mon_from(landed, CONSOLE_TID, CONSOLE_SID),
                    w.RNG_MON_HUNT_CRITERIA)
