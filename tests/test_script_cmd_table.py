"""gScriptCmdTable: the address derived from gSpecialVars, and the reader for a dump of it."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map, scrcmd, scrcmd_args, scrcmd_names  # noqa: E402


def test_the_table_is_the_decomps_length():
    """214 entries [decomp:data/script_cmd_table.inc]."""
    assert scrcmd_names.SCRIPT_CMD_COUNT == 214
    assert scrcmd_names.SCRIPT_CMD_TABLE_SIZE == 856


def test_the_address_is_derived_from_the_measured_gspecialvars():
    """script_data opens with the table and gSpecialVars follows it [ld_script_rev10.ld:318]; bs57
    measured gSpecialVars, so the table costs no run of its own."""
    assert rom_map.G_SCRIPT_CMD_TABLE == 0x08163650
    assert rom_map.G_SPECIAL_VARS - rom_map.G_SCRIPT_CMD_TABLE == \
        scrcmd_names.SCRIPT_CMD_TABLE_SIZE


def test_the_index_is_the_opcode_this_project_already_emits():
    """A cross-check against the opcodes the composers write: if the generated order were wrong,
    these would not line up [frlgsim/scrcmd.py]."""
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


# --- the measured table, bs82 -------------------------------------------------------------------

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


# --- the workers behind the handlers, bs84 ------------------------------------------------------

def test_the_worker_addresses_sit_inside_the_dumped_rom():
    for name in ("ADD_BAG_ITEM", "REMOVE_BAG_ITEM", "CHECK_BAG_HAS_SPACE", "CHECK_BAG_HAS_ITEM",
                 "ADD_PC_ITEM", "FLAG_SET", "FLAG_CLEAR", "FLAG_GET", "INCREMENT_GAME_STAT",
                 "VAR_GET", "GET_VAR_POINTER", "SCRIPT_READ_HALFWORD"):
        value = getattr(rom_map, name)
        assert 0x08000000 <= value < 0x08400000, name
        assert value % 2 == 0, f"{name} is stored without the thumb bit"


def test_the_extraction_lands_on_an_address_measured_independently():
    """ScrCmd_random's third call is Random, found at bs13 from its own literal pool. This is the
    check that the bs84 extraction is aligned, not the item addresses themselves."""
    assert rom_map.RANDOM == 0x080486B0


def test_the_flag_helpers_are_three_consecutive_functions():
    """FlagSet, FlagClear and FlagGet are written in that order [decomp:src/event_data.c], and the
    handlers called them in that order, so the addresses must ascend."""
    assert rom_map.FLAG_SET < rom_map.FLAG_CLEAR < rom_map.FLAG_GET


def test_calling_add_bag_item_needs_the_thumb_bit():
    """--call-address takes the value a bx needs; every entry here is stored without it."""
    assert rom_map.thumb(rom_map.ADD_BAG_ITEM) == 0x0809DA71


# --- reading a script the console holds, bs97/bs98 ------------------------------------------------
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
