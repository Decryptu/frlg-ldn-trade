"""gScriptCmdTable: the address derived from gSpecialVars, and the reader for a dump of it."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map, scrcmd, scrcmd_names  # noqa: E402


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
