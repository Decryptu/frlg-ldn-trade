"""Locating gMysteryEventScriptCmdTable, the one table this project has only ever read from the
decomp.

The Mystery Event VM has its own 17-command interpreter [docs/mystery_event.md]. Every opcode in it
has been RUN on the console, but the table itself has never been located: it carries no constant to
search for, and its 17 entries are unrelated function addresses, so `table-scan`'s arithmetic-run
fingerprint does not match it either.

What does match is where the table's ADDRESS is kept. `InitMysteryEventScript` calls
`InitScriptContext(ctx, gMysteryEventScriptCmdTable, gMysteryEventScriptCmdTableEnd)`
[decomp:src/mystery_event_script.c:52], `struct ScriptContext` stores those two as ADJACENT words
at +0x5C and +0x60 [decomp:include/script.h], and the context is
`EWRAM_DATA static struct ScriptContext sMysteryEventScriptContext` - so once a Mystery Event script
has run, the pair sits in EWRAM for the rest of the boot.

Two adjacent words exactly 68 apart is a `table-scan` with `--table-delta 0x44 --table-runlen 2`,
and the scan answers with the run's first VALUE, which is the table address itself. Locating and
reading are one run, the same way gSpecialVars was.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import buffer_script, rom_map  # noqa: E402

MYSTERY_EVENT_CMD_COUNT = 17            # [decomp:data/mystery_event_script_cmd_table.s]
MYSTERY_EVENT_TABLE_BYTES = MYSTERY_EVENT_CMD_COUNT * 4

# struct ScriptContext: stackDepth/mode/comparisonResult, pad, nativePtr, scriptPtr, stack[20],
# cmdTable, cmdTableEnd, data[4] [decomp:include/script.h].
CTX_CMD_TABLE = 0x5C
CTX_CMD_TABLE_END = 0x60

# Where the answer has to fall if it is real. script_data opens at gScriptCmdTable and the mystery
# event table is its LAST member [ld_script_rev10.ld:318-328], so the table sits above every event
# script we have read and below .rodata, which starts below gSpeciesInfo (bs39).
ANSWER_LOW = 0x081AB569                 # the last command of gStdScripts[8], read at bs108
ANSWER_HIGH = 0x0824CDC0 - MYSTERY_EVENT_TABLE_BYTES     # gSpeciesInfo, bs39


def _context(cmd_table):
    """A struct ScriptContext as InitScriptContext leaves it, as bytes."""
    context = bytearray(116)
    context[CTX_CMD_TABLE:CTX_CMD_TABLE + 4] = cmd_table.to_bytes(4, "little")
    context[CTX_CMD_TABLE_END:CTX_CMD_TABLE_END + 4] = (
        cmd_table + MYSTERY_EVENT_TABLE_BYTES).to_bytes(4, "little")
    return bytes(context)


def test_the_two_pointers_are_adjacent_and_exactly_the_table_apart():
    """The whole method rests on this: 17 entries of 4 bytes, and the second word is the first plus
    that. Either number wrong and the scan is looking for a shape that is not there."""
    assert MYSTERY_EVENT_TABLE_BYTES == 0x44
    assert CTX_CMD_TABLE_END - CTX_CMD_TABLE == 4


def test_the_scan_finds_the_context_and_reads_the_table_address_out_of_it():
    """The payload, run offline against a context planted where one would be. The hit's ADDRESS is
    the context, and the hit's VALUE is gMysteryEventScriptCmdTable."""
    context_at, table_at = 0x0203A000, 0x08215A40
    low, high = context_at - 0x40, context_at + 0x200
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=MYSTERY_EVENT_TABLE_BYTES, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: _context(table_at)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)

    assert repeated.done
    assert answer["hits"] == [(context_at + CTX_CMD_TABLE, table_at)]


def test_a_context_that_never_ran_a_script_answers_nothing():
    """`sMysteryEventScriptContext` is zero until a Mystery Event script runs, and 0 and 0 are not
    68 apart. So the run has to FOLLOW a mystery-event gift in the same boot - which is the one
    thing that can make this run uninformative, and it is worth knowing before it is spent."""
    context_at = 0x0203A000
    low, high = context_at - 0x40, context_at + 0x200
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=MYSTERY_EVENT_TABLE_BYTES, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: bytes(116)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)
    assert answer["hits"] == []


def test_the_field_script_context_is_the_control_and_its_answer_is_already_known():
    """The same shape with delta 856 finds the FIELD script context instead, whose cmdTable is
    gScriptCmdTable - an address bs82 already measured. A scan that cannot find that on the console
    is not measuring what it thinks, and it costs one ordinary run to check."""
    assert rom_map.G_SCRIPT_CMD_TABLE == 0x08163650
    field_table_bytes = 214 * 4
    assert field_table_bytes == 0x358
    context_at = 0x0201F000
    low, high = context_at - 0x40, context_at + 0x200
    context = bytearray(116)
    context[CTX_CMD_TABLE:CTX_CMD_TABLE + 4] = rom_map.G_SCRIPT_CMD_TABLE.to_bytes(4, "little")
    context[CTX_CMD_TABLE_END:CTX_CMD_TABLE_END + 4] = (
        rom_map.G_SCRIPT_CMD_TABLE + field_table_bytes).to_bytes(4, "little")
    repeated = buffer_script.emulate_repeating(
        buffer_script.build_table_scan(
            delta=field_table_bytes, runlen=2, start=low, end=high, blocks=64),
        memory={context_at: bytes(context)})
    answer = buffer_script.read_table_scan(repeated.final.pending_send, low, high)
    assert answer["hits"] == [(context_at + CTX_CMD_TABLE, rom_map.G_SCRIPT_CMD_TABLE)]


def test_the_bracket_a_real_answer_has_to_fall_in():
    """A hit is only credible inside script_data, and both ends of that bracket are measurements
    this project already made: bs108 read a script at the low end, bs39 the species table above the
    high end. Anything outside is a coincidence in EWRAM, not the table."""
    assert ANSWER_LOW > rom_map.G_STD_SCRIPTS
    assert ANSWER_HIGH > ANSWER_LOW
    assert ANSWER_HIGH - ANSWER_LOW < 0x00200000, "the bracket is under 2 MB wide"
