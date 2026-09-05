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
