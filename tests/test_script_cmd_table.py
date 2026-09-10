"""gScriptCmdTable: the address derived from gSpecialVars, and the reader for a dump of it."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import rom_map, scrcmd, scrcmd_args, scrcmd_names  # noqa: E402


def test_the_table_is_the_decomps_length():
    """214 entries [decomp:data/script_cmd_table.inc]."""
    assert scrcmd_names.SCRIPT_CMD_COUNT == 214
    assert scrcmd_names.SCRIPT_CMD_TABLE_SIZE == 856


def test_the_address_is_derived_from_the_measured_gspecialvars():
    """script_data opens with the table and gSpecialVars follows it [ld_script_rev10.ld:318]; it is
    measured gSpecialVars, so the table costs no run of its own."""
    assert rom_map.G_SCRIPT_CMD_TABLE == 0x08163650
    assert rom_map.G_SPECIAL_VARS - rom_map.G_SCRIPT_CMD_TABLE == \
        scrcmd_names.SCRIPT_CMD_TABLE_SIZE


def test_the_index_is_the_opcode_this_project_already_emits():
    """A cross-check against the opcodes the composers write: if the generated order were wrong,
    these would not line up [pokeldn/frlg/rom/scrcmd.py]."""
    assert scrcmd_names.COMMANDS[scrcmd.OP_END] == "end"
    assert scrcmd_names.COMMANDS[scrcmd.OP_ADDVAR] == "addvar"
    assert scrcmd_names.COMMANDS[scrcmd.OP_SETVAR] == "setvar"
    assert scrcmd_names.COMMANDS[scrcmd.OP_SPECIAL] == "special"
    assert scrcmd_names.COMMANDS[scrcmd.OP_CALLSTD] == "callstd"
    assert scrcmd_names.COMMANDS[scrcmd.OP_SETFLAG] == "setflag"


def test_a_dump_reads_back_as_named_thumb_pointers():
    entries = scrcmd_names.read_table(
        b"".join((0x08041151).to_bytes(4, "little") for _ in range(214)),
        rom_map.G_SCRIPT_CMD_TABLE)
    assert len(entries) == 214
    assert entries[2] == (2, "end", 0x08041150, True)
    assert len(scrcmd_names.plausible(entries)) == 214


def test_a_table_read_at_the_wrong_address_fails_the_shape_test():
    """Every entry is a THUMB ROM pointer; EWRAM words and cleared bits are not."""
    entries = scrcmd_names.read_table(bytes(856), rom_map.G_SCRIPT_CMD_TABLE)
    assert scrcmd_names.plausible(entries) == []
    entries = scrcmd_names.read_table(
        b"".join((0x02024281).to_bytes(4, "little") for _ in range(214)),
        rom_map.G_SCRIPT_CMD_TABLE)
    assert scrcmd_names.plausible(entries) == []


# --- the measured table -------------------------------------------------------------------

def test_every_measured_handler_is_a_rom_address():
    assert len(scrcmd_names.HANDLERS) == 214
    assert all(0x0806D000 <= a < 0x08071000 for a in scrcmd_names.HANDLERS)
    assert all(a % 2 == 0 for a in scrcmd_names.HANDLERS), "the thumb bit is stripped"


def test_the_only_shared_handler_is_the_pair_the_decomp_names_nop():
    """This is the alignment proof, not a curiosity: ScrCmd_nop sits at opcode 0 and opcode 213
    with ScrCmd_nop1 distinct between them, so a table read off by one entry cannot reproduce it."""
    shared = [i for i, a in enumerate(scrcmd_names.HANDLERS)
              if scrcmd_names.HANDLERS.count(a) > 1]
    assert shared == [0, 213]
    assert scrcmd_names.COMMANDS[0] == scrcmd_names.COMMANDS[213] == "nop"
    assert scrcmd_names.HANDLERS[1] != scrcmd_names.HANDLERS[0]


def test_a_handler_is_reachable_by_name():
    assert scrcmd_names.handler("additem") == 0x0806DED0
    assert scrcmd_names.handler("callnative") == 0x0806D854
    assert scrcmd_names.handler("nop") == scrcmd_names.HANDLERS[0]


# --- the workers behind the handlers ------------------------------------------------------

def test_the_worker_addresses_sit_inside_the_dumped_rom():
    for name in ("ADD_BAG_ITEM", "REMOVE_BAG_ITEM", "CHECK_BAG_HAS_SPACE", "CHECK_BAG_HAS_ITEM",
                 "ADD_PC_ITEM", "FLAG_SET", "FLAG_CLEAR", "FLAG_GET", "INCREMENT_GAME_STAT",
                 "VAR_GET", "GET_VAR_POINTER", "SCRIPT_READ_HALFWORD"):
        value = getattr(rom_map, name)
        assert 0x08000000 <= value < 0x08400000, name
        assert value % 2 == 0, f"{name} is stored without the thumb bit"


def test_the_extraction_lands_on_an_address_measured_independently():
    """ScrCmd_random's third call is Random, found independently from its own literal pool. This is the
    check that the extraction is aligned, not the item addresses themselves."""
    assert rom_map.RANDOM == 0x080486B0


def test_the_flag_helpers_are_three_consecutive_functions():
    """FlagSet, FlagClear and FlagGet are written in that order [decomp:src/event_data.c], and the
    handlers called them in that order, so the addresses must ascend."""
    assert rom_map.FLAG_SET < rom_map.FLAG_CLEAR < rom_map.FLAG_GET


def test_calling_add_bag_item_needs_the_thumb_bit():
    """--call-address takes the value a bx needs; every entry here is stored without it."""
    assert rom_map.thumb(rom_map.ADD_BAG_ITEM) == 0x0809DA71


# --- reading a script the console holds ------------------------------------------------
# 42 bytes read off the console at 0x081A7624, where gStdScripts points: five standard scripts laid
# out back to back. They are the fixture because they are the one place a script's boundaries are
# known independently - data/scripts/std_msgbox.inc says what each one is, and gStdScripts says
# where each one starts, so a wrong opcode table or a wrong operand width desynchronises visibly.
STD_MSGBOX_BASE = 0x081A7624
STD_MSGBOX_BYTES = bytes.fromhex(
    "6a5a6700000000666d6c03"      # Std_MsgboxNPC     0x081A7624
    "696700000000666d6b03"        # Std_MsgboxSign    0x081A762F
    "6700000000666d03"            # Std_MsgboxDefault 0x081A7639
    "6700000000666e140803"        # Std_MsgboxYesNo   0x081A7641
    "c70321")                     # Std_ReceivedItem  0x081A764B, its first two commands


def test_the_console_s_own_standard_script_disassembles_as_the_decomp_wrote_it():
    lines = scrcmd.disassemble(STD_MSGBOX_BYTES, STD_MSGBOX_BASE, STD_MSGBOX_BASE)
    got = [line.split(None, 2)[2].split()[0] for line in lines]

    assert got == ["lock", "faceplayer", "message", "waitmessage", "waitbuttonpress",
                   "release", "return"], "data/scripts/std_msgbox.inc, command for command"


def test_each_standard_script_ends_exactly_where_the_next_one_begins():
    """The real check on the operand widths. gStdScripts gives five entry points; the disassembly
    of each one has to stop on `return` at the byte before the next. A width that is wrong by one
    anywhere cannot land on all five."""
    entries = (0x081A7624, 0x081A762F, 0x081A7639, 0x081A7641, 0x081A764B)
    for start, next_start in zip(entries, entries[1:]):
        lines = scrcmd.disassemble(STD_MSGBOX_BYTES, STD_MSGBOX_BASE, start)
        assert lines[-1].split()[1] == "03", f"the script at 0x{start:08X} does not end on `return`"
        last = int(lines[-1].split()[0], 16)
        assert last + 1 == next_start, (
            f"0x{start:08X} runs to 0x{last:08X}, but the next entry point is 0x{next_start:08X}")


def test_a_pointer_that_is_not_a_script_is_not_mistaken_for_one():
    assert scrcmd.looks_like_a_script(STD_MSGBOX_BYTES, STD_MSGBOX_BASE, STD_MSGBOX_BASE)
    # THUMB function prologues (push {r4, lr}; adds r4, r0, #0) are what the OTHER tables hold.
    assert not scrcmd.looks_like_a_script(
        bytes.fromhex("10b5041c") * 4, STD_MSGBOX_BASE, STD_MSGBOX_BASE)


def test_every_command_the_project_emits_has_a_shape():
    """scrcmd.py's OP_* constants are the commands this host actually writes into a RAM script; a
    command with no fixed shape cannot be disassembled, so it must not be one of ours."""
    ours = [value for name, value in vars(scrcmd).items()
            if name.startswith("OP_") and isinstance(value, int)]
    assert ours
    for opcode in ours:
        assert opcode in scrcmd_args.ARGS, f"{scrcmd_names.COMMANDS[opcode]} has no operand shape"


# 0x081A7699..0x081A77A3 of the French FireRed cartridge, read off the console (a 1 KB
# memory-dump at 0x081A7600). It is data/scripts/trainer_battle.inc: seven labels, four runs that
# each end on `end`, and the region every trainer on every map goes through.
TRAINER_BATTLE_BASE = 0x081A7699
TRAINER_BATTLE_BYTES = bytes.fromhex(
    "6a2538002537002705b2771a086a5a4f0f80b077"
    "1a08510000260d803600210d8000000605cd761a"
    "08253800253a0105b2771a085e6a5a04a5771a08"
    "260d803600210d800000060505771a08253d0021"
    "0d8000000605fe761a08253800253a0105b2771a"
    "08253500666d6c025e4f0f80b0771a0851000025"
    "3800258701210d800200060105781a085d5e04a5"
    "771a08260d803a00210d80000006015a771a0825"
    "3800253a01253400666d258701210d8002000601"
    "a3771a08258801253b00276b025e260d803a0021"
    "0d80000006019b771a08253d00210d8000000605"
    "9c771a08253800253a01253400666d258701210d"
    "8002000601a3771a08258801253b00276b025e25"
    "3500666d6c02")


def names_at(start):
    return [line.split(None, 2)[2].split()[0]
            for line in scrcmd.disassemble(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, start)]


def test_the_console_s_own_trainer_script_disassembles_as_the_decomp_wrote_it():
    """EventScript_TryDoNormalTrainerBattle [decomp:data/scripts/trainer_battle.inc:8], command for
    command. This is the shape the old flattened operand table could not read: it measured
    `applymovement` at 14 bytes instead of 7, swallowed the `waitmovement` and the `specialvar`
    behind it, and every byte after that was noise."""
    assert names_at(0x081A76A6) == [
        "lock", "faceplayer", "applymovement", "waitmovement", "specialvar",
        "compare_var_to_value", "goto_if", "special", "special", "goto"]


def test_the_operands_of_that_script_are_the_decomps_own_arguments():
    """VAR_LAST_TALKED and Movement_RevealTrainer, then `waitmovement 0`. A width wrong by one
    anywhere above these would put a different number here."""
    lines = scrcmd.disassemble(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6)
    assert lines[2].split("  ", 3)[3] == "applymovement 0x800F, 0x081A77B0"   # VAR_LAST_TALKED
    assert lines[3].split("  ", 3)[3] == "waitmovement 0x0000"
    assert lines[4].split("  ", 3)[3] == "specialvar 0x800D, 0x0036"          # VAR_RESULT


def test_each_trainer_script_ends_exactly_where_the_next_one_begins():
    """The same end-to-start check as the standard scripts, over a region that actually uses the
    commands the widths were wrong for. Seven runs, no gap and no overlap, and every boundary is a
    label the decomp names [data/scripts/trainer_battle.inc]. A width wrong by one anywhere above
    cannot land on all seven."""
    entries = (0x081A7699,      # EventScript_DoTrainerBattleFromApproach
               0x081A76A6,      # EventScript_TryDoNormalTrainerBattle
               0x081A76CD,      # EventScript_NoTrainerBattle, EventScript_TryDoDoubleTrainerBattle
               0x081A76FE,      # EventScript_NotEnoughMonsForDoubleBattle
               0x081A7705,      # EventScript_NoDoubleTrainerBattle, ..., TryDoRematchBattle
               0x081A775A,      # EventScript_NoRematchBattle, TryDoDoubleRematchBattle
               0x081A779B,      # EventScript_NoDoubleRematchBattle, NotEnoughMonsForDoubleRematch
               0x081A77A3)      # EventScript_EndQuestLogRematch, where the dumped region ends
    for start, next_start in zip(entries, entries[1:]):
        lines = scrcmd.disassemble(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, start)
        last = int(lines[-1].split()[0], 16)
        assert int(lines[-1].split()[1], 16) in scrcmd.TERMINATORS, (
            f"the run at 0x{start:08X} does not end on a terminator")
        assert last + scrcmd.shape(
            TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, last - TRAINER_BATTLE_BASE)[2] == next_start


def test_a_goto_ends_the_run_because_control_never_falls_through_it():
    """The decomp puts EventScript_NoTrainerBattle immediately behind the `goto` that ends
    EventScript_TryDoNormalTrainerBattle [trainer_battle.inc:17], so a walk that carried on through
    the goto would run two labels together and never find the boundary."""
    lines = scrcmd.disassemble(TRAINER_BATTLE_BYTES, TRAINER_BATTLE_BASE, 0x081A76A6)
    assert lines[-1].split()[2] == "goto"
    assert scrcmd.OP_GOTO in scrcmd.TERMINATORS


def test_the_flattened_shapes_cannot_come_back():
    """Eleven macros in event.inc have conditional bodies, and reading one as a flat list of
    directives concatenates every branch. These are the lengths the decomp's macros actually
    give [asm/macros/event.inc]; each was wrong before the generator walked the branches."""
    lengths = {opcode: 1 + sum(widths) for opcode, widths in scrcmd_args.ARGS.items()}
    assert lengths[0x4F] == 7      # applymovement: localId, movements
    assert lengths[0x51] == 3      # waitmovement: localId
    assert lengths[0x53] == 3      # removeobject
    assert lengths[0x55] == 3      # addobject
    assert lengths[0x39] == 8      # warp: map group, map num, warpId, x, y - through `formatwarp`
    assert lengths[0x80] == 4      # bufferitemname: the stringvar byte, then the item
    assert lengths[0x58] == 5      # showobjectat: localId then the two `map` bytes


def test_the_at_variants_exist_at_all():
    """`.ifb \\map` picks between two opcodes, and only the first was read before, so the four
    commands that carry an explicit map were missing from the table entirely."""
    for opcode, name in ((0x50, "applymovementat"), (0x52, "waitmovementat"),
                         (0x54, "removeobjectat"), (0x56, "addobjectat")):
        assert opcode in scrcmd_args.ARGS, name
        assert scrcmd_args.ARGS[opcode][-2:] == (1, 1), f"{name} must end with the two map bytes"


def test_trainerbattle_is_the_one_command_with_a_tail_that_varies():
    """Ten types, one to four pointers each [asm/macros/event.inc, .macro trainerbattle]. The head
    is type, trainer, localId; the type is what picks the tail."""
    assert set(scrcmd_args.VARIABLE) == {0x5C}
    shape = scrcmd_args.VARIABLE[0x5C]
    assert shape["head"] == (1, 2, 2) and shape["select"] == 0
    assert set(shape["tails"]) == set(range(10))
    assert shape["tails"][0] == (4, 4)          # TRAINER_BATTLE_SINGLE: intro, lose
    assert shape["tails"][3] == (4,)            # SINGLE_NO_INTRO_TEXT: lose only
    assert shape["tails"][6] == (4, 4, 4, 4)    # CONTINUE_SCRIPT_DOUBLE: three texts, one script


def test_a_trainerbattle_is_measured_from_its_type_byte():
    """6 bytes of head and then the type's own pointers, so the command after it is found."""
    for battle_type, length in ((0, 14), (3, 10), (6, 22)):
        blob = bytes([0x5C, battle_type]) + b"\x00" * (length - 2) + b"\x02"
        assert scrcmd.shape(blob, 0, 0)[2] == length
        assert scrcmd.disassemble(blob, 0, 0)[-1].split()[2] == "end"


def test_a_type_the_decomp_does_not_define_is_not_a_trainerbattle():
    """Type 10 has no branch in the macro, so the length is unknown and the walk stops rather than
    guessing one - a guessed length turns every byte after it into noise."""
    assert scrcmd.shape(bytes([0x5C, 10]) + b"\x00" * 20, 0, 0) is None
    assert not scrcmd.looks_like_a_script(bytes([0x5C, 10]) + b"\x00" * 20, 0, 0)


def test_every_command_but_the_decomps_second_nop_can_be_measured():
    """213 of the 214. 0xD5 is the second `nop` and event.inc defines no macro for it."""
    measurable = set(scrcmd_args.ARGS) | set(scrcmd_args.VARIABLE)
    missing = set(range(scrcmd_names.SCRIPT_CMD_COUNT)) - measurable
    assert missing == {0xD5}, sorted(hex(opcode) for opcode in missing)
