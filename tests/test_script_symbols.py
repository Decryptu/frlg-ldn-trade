"""Naming a script's operands, and following one to what it reaches.

The disassembler turns console bytes into commands; this is the layer that turns their operands
back into meaning - the var, the flag, the special, the comparison - and then chases every goto and
call to say which addresses a future `memory-dump` should aim at.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import buffer_script, scrcmd, symbol_names  # noqa: E402
from tests.test_script_cmd_table import TRAINER_BATTLE_BASE, TRAINER_BATTLE_BYTES  # noqa: E402

# gStdScripts as read off the console, ten pointers [decomp:data/event_scripts.s].
STD_SCRIPT_POINTERS = (0x081A8E49, 0x081A8F81, 0x081A7624, 0x081A762F, 0x081A7639,
                       0x081A7641, 0x081A780A, 0x081A8F3A, 0x081AB501, 0x081A764B)


def test_the_var_bounds_are_the_ones_the_save_writer_already_enforces():
    """`sav1_var_offset` was written against GetVarPointer months before this table existed
    [decomp:src/event_data.c:186]; the generated bounds have to be the same two numbers."""
    assert symbol_names.VARS_START == 0x4000
    assert symbol_names.VARS_END == 0x40FF
    assert symbol_names.SPECIAL_VARS_START == 0x8000
    assert symbol_names.SPECIAL_VARS_END == 0x8014
    assert buffer_script.sav1_var_offset(symbol_names.VARS_START) == buffer_script.SAV1_VARS


def test_the_altering_cave_var_lands_on_the_offset_measured_on_hardware():
    """The generated name table and a hardware measurement, meeting. Two runs read the Altering
    Cave counter at SaveBlock1 + 0x1048 and watched it move; the decomp calls that var
    VAR_ALTERING_CAVE_WILD_SET, and the two only agree if the id is right."""
    altering = [value for value, name in symbol_names.VARS.items()
                if name == "VAR_ALTERING_CAVE_WILD_SET"]
    assert altering == [0x4024]
    assert buffer_script.sav1_var_offset(0x4024) == 0x1048


def test_the_names_agree_with_the_constants_this_project_wrote_by_hand():
    """scrcmd.py's own constants were transcribed from the decomp one at a time. A generated table
    that disagreed with them would be wrong about something that has run on hardware."""
    assert symbol_names.VARS[scrcmd.VAR_RESULT] == "VAR_RESULT"
    assert symbol_names.VARS[scrcmd.VAR_STARTER_MON] == "VAR_STARTER_MON"


def test_an_operand_is_a_variable_exactly_at_vars_start():
    """VarGet returns the number unchanged below VARS_START and reads the variable at or above it
    [decomp:src/event_data.c:235], so this boundary is the whole rule."""
    assert not symbol_names.is_var(0x3FFF)
    assert symbol_names.is_var(0x4000)
    assert symbol_names.is_var(0x800D)
    assert symbol_names.var_name(0x0005) == "0x0005"      # a literal stays a literal
    assert symbol_names.var_name(0x800D) == "VAR_RESULT"


def test_a_define_with_no_value_does_not_swallow_the_next_one():
    """The include guard is `#define GUARD_CONSTANTS_VARS_H` with nothing after it, and VARS_START
    is the next define in the file. Matching the value with `\\s` instead of `[ \\t]` lets it cross
    the newline and eat that line, which is how VARS_START went missing the first time."""
    assert symbol_names.VARS_START == 0x4000
    assert len(symbol_names.VARS) == 274
    assert len(symbol_names.FLAGS) + len(symbol_names.FLAGS_ALIASES) == 1470


def test_the_system_flags_resolve_through_the_header_they_are_built_on():
    """The FLAG_SYS_* block is `SYS_FLAGS + n`, and SYS_FLAGS is built on MAX_TRAINERS_COUNT from
    opponents.h. 188 flags were missing until that header was read with flags.h."""
    named = {name: value for value, name in symbol_names.FLAGS.items()}
    assert named["FLAG_SYS_POKEDEX_GET"] == 0x829
    assert named["FLAG_SYS_NATIONAL_DEX"] == 0x840


def test_the_console_s_trainer_script_reads_with_the_decomps_own_names():
    """The same bytes as test_script_cmd_table, with the operands named. Every name here is one the
    decomp writes on that line [data/scripts/trainer_battle.inc:8]."""
    lines = scrcmd.disassemble(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6, symbols=True)
    text = [line.split("  ", 3)[3] for line in lines]
    assert text[2] == "applymovement 0x800F (VAR_LAST_TALKED), 0x081A77B0"
    assert text[4] == "specialvar 0x800D (VAR_RESULT), 0x0036 (Script_HasTrainerBeenFought)"
    assert text[5] == "compare_var_to_value 0x800D (VAR_RESULT), 0x0000"
    assert text[6].startswith("goto_if 0x05 (!=)")          # the decomp writes goto_if_ne
    assert text[7] == "special 0x0038 (PlayTrainerEncounterMusic)"


def test_the_condition_byte_is_the_decomps_row_order():
    """sScriptConditionTable is <, =, >, <=, >=, != [decomp:src/scrcmd.c:65], which is where
    scrcmd's own COMPARE_EQ and COMPARE_NE came from."""
    assert scrcmd.CONDITIONS[scrcmd.COMPARE_EQ] == "="
    assert scrcmd.CONDITIONS[scrcmd.COMPARE_NE] == "!="


def test_a_special_index_and_a_std_index_are_told_apart_by_width():
    """Both macros call the operand `function`. ScrCmd_special reads a u16 into gSpecials, and
    ScrCmd_callstd a u8 into gStdScripts, so the width is what says which table."""
    assert scrcmd.name_operand(0x25, 0, 2, 0x38) == "PlayTrainerEncounterMusic"
    assert scrcmd.name_operand(0x09, 0, 1, 0x38) == "gStdScripts[56]"


def test_a_trainerbattle_type_is_named():
    assert scrcmd.name_operand(0x5C, 0, 1, 0) == "SINGLE"
    assert scrcmd.name_operand(0x5C, 0, 1, 6) == "CONTINUE_SCRIPT_DOUBLE"


def test_following_a_script_names_what_the_dump_stops_short_of():
    """The fixture is 266 bytes of trainer_battle.inc, and the file carries on past it. Following
    the jumps says exactly which labels are missing - and every one of the five is a label the
    decomp names, which is the check on the walk itself:

        0x081A77A3  EventScript_EndQuestLogRematch     two goto_ifs reach it
        0x081A77A5  EventScript_RevealTrainer          two calls
        0x081A77B0  Movement_RevealTrainer             DATA, the applymovement operand
        0x081A77B2  EventScript_DoTrainerBattle        two gotos
        0x081A7805  EventScript_EndQuestLogBattle      one goto_if
    """
    reached, referenced = scrcmd.follow(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6)
    assert len(reached) == 7
    assert set(referenced) == {0x081A77A3, 0x081A77A5, 0x081A77B0, 0x081A77B2, 0x081A7805}
    kinds = {address: sorted({kind for kind, _source in reasons})
             for address, reasons in referenced.items()}
    assert kinds[0x081A77B2] == ["goto"]
    assert kinds[0x081A77A5] == ["call"]
    assert kinds[0x081A77B0] == ["movements"], "movement data is pointed at, never executed"


def test_a_data_pointer_is_reported_but_never_followed():
    """Movement_RevealTrainer is a movement list, not a script. Following it would disassemble
    movement bytes as commands and print nonsense with confidence."""
    reached, referenced = scrcmd.follow(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6)
    assert 0x081A77B0 in referenced and 0x081A77B0 not in reached


def test_an_entry_point_the_dump_does_not_hold_is_what_to_dump_next():
    """Pointed at gStdScripts with only the trainer region in hand, every one of the ten pointers
    is an address we want and do not have - which is the report, not a failure."""
    reached, referenced = scrcmd.follow(
        TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, STD_SCRIPT_POINTERS)
    assert reached == {}
    assert set(referenced) == set(STD_SCRIPT_POINTERS)
    assert all(kind == "entry point"
               for reasons in referenced.values() for kind, _source in reasons)


def test_the_plan_puts_the_window_that_catches_the_most_first():
    """Five of the ten standard scripts share the 1 KB window at 0x081A7400, and a run that catches
    five costs exactly what one that catches a single script does."""
    _reached, referenced = scrcmd.follow(
        TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, STD_SCRIPT_POINTERS)
    plan = scrcmd.dump_plan(referenced)
    assert plan[0].startswith("  --dump-address 0x081A7400 --dump-size 1024   5 addresses")
    assert len(plan) == 4
    covered = sum(int(line.split("size 1024   ")[1].split()[0]) for line in plan)
    assert covered == len(STD_SCRIPT_POINTERS), "every wanted address has to appear in the plan"


def test_two_dumps_that_touch_become_one_region():
    """A block that straddles the join between two dumps has to disassemble, so overlapping and
    adjacent segments merge rather than sitting side by side."""
    memory = scrcmd.Memory([(0x08000000, b"\x00" * 16), (0x08000010, b"\x11" * 16)])
    assert len(memory.segments) == 1 and len(memory) == 32
    overlapping = scrcmd.Memory([(0x08000000, b"\x00" * 16), (0x08000008, b"\x11" * 16)])
    assert len(overlapping.segments) == 1 and len(overlapping) == 24
    apart = scrcmd.Memory([(0x08000000, b"\x00" * 16), (0x08000020, b"\x11" * 16)])
    assert len(apart.segments) == 2
    assert 0x08000000 in apart and 0x08000018 not in apart


def test_a_script_split_across_two_dumps_still_walks():
    """The real fixture cut in half and handed over as two separate runs. Every block still reads,
    which is the point of holding all the dumps at once: a script does not care which run caught
    the block it jumps to."""
    half = len(TRAINER_BATTLE_BYTES) // 2
    memory = scrcmd.Memory([
        (TRAINER_BATTLE_BASE, TRAINER_BATTLE_BYTES[:half]),
        (TRAINER_BATTLE_BASE + half, TRAINER_BATTLE_BYTES[half:])])
    reached, referenced = scrcmd.follow(memory, 0x081A76A6)
    whole, _ = scrcmd.follow(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6)
    assert reached == whole
    assert set(referenced) == {0x081A77A3, 0x081A77A5, 0x081A77B0, 0x081A77B2, 0x081A7805}


def test_a_dump_that_ends_mid_command_says_so():
    """A command with a known shape whose operands run off the end means the DUMP is short, not
    that the bytes are not a script. Reading `no shape here` for that sends you looking for a bug
    in the table - it happened, on the last command of one run."""
    truncated = bytes([0x0F, 0x00, 0x11, 0x22])          # loadword wants 1 + 4, four bytes given
    assert scrcmd.shape(truncated, 0, 0) is None
    assert "truncated" in scrcmd.disassemble(truncated, 0, 0)[-1]
    assert "no shape here" in scrcmd.disassemble(bytes([0xD5]), 0, 0)[-1]
