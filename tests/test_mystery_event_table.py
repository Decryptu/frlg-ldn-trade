"""Locating gMysteryEventScriptCmdTable, the one table this project has only ever read from the
decomp.

The Mystery Event VM has its own 17-command interpreter [docs/frlg_rom.md]. Every opcode in it
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

from pokeldn.frlg.rom import buffer_script, rom_map  # noqa: E402

MYSTERY_EVENT_CMD_COUNT = 17            # [decomp:data/mystery_event_script_cmd_table.s]
MYSTERY_EVENT_TABLE_BYTES = MYSTERY_EVENT_CMD_COUNT * 4

# struct ScriptContext: stackDepth/mode/comparisonResult, pad, nativePtr, scriptPtr, stack[20],
# cmdTable, cmdTableEnd, data[4] [decomp:include/script.h].
CTX_CMD_TABLE = 0x5C
CTX_CMD_TABLE_END = 0x60

# Where the answer has to fall if it is real. script_data opens at gScriptCmdTable and the mystery
# event table is its LAST member [ld_script_rev10.ld:318-328], so the table sits above every event
# script we have read and below .rodata, which starts below gSpeciesInfo.
ANSWER_LOW = 0x081AB569                 # the last command of gStdScripts[8], read
ANSWER_HIGH = 0x0824CDC0 - MYSTERY_EVENT_TABLE_BYTES     # gSpeciesInfo


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
    gScriptCmdTable - an address a run already measured. A scan that cannot find that on the console
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
    this project already made: A run read a script at the low end, a run the species table above the
    high end. Anything outside is a coincidence in EWRAM, not the table."""
    assert ANSWER_LOW > rom_map.G_STD_SCRIPTS
    assert ANSWER_HIGH > ANSWER_LOW
    assert ANSWER_HIGH - ANSWER_LOW < 0x00200000, "the bracket is under 2 MB wide"


# --- and then it was measured: A run found it, a run read it ---------------------------------------

def test_the_table_was_found_where_the_bracket_said_it_had_to_be():
    """one hit in all 256 KB of EWRAM, no false positives. The scan's value is the table."""
    assert rom_map.G_MYSTERY_EVENT_CMD_TABLE == 0x081DE144
    assert ANSWER_LOW < rom_map.G_MYSTERY_EVENT_CMD_TABLE < ANSWER_HIGH
    assert rom_map.S_MYSTERY_EVENT_SCRIPT_CONTEXT + CTX_CMD_TABLE == 0x0203AA94


def test_the_seventeen_entries_are_seventeen_functions():
    """A run read the table. Every entry odd (THUMB), every one distinct, every one inside .text,
    and all of them within about a kilobyte of each other - one object file's worth of functions.
    Seventeen coincidences would not do that."""
    addresses = [address for _name, address in rom_map.MYSTERY_EVENT_HANDLERS]
    assert len(addresses) == MYSTERY_EVENT_CMD_COUNT
    assert len(set(addresses)) == MYSTERY_EVENT_CMD_COUNT
    assert all(address & 1 for address in addresses), "a ScrCmdFunc pointer is THUMB"
    assert all(0x08000000 < address < rom_map.G_SCRIPT_CMD_TABLE for address in addresses)
    assert max(addresses) - min(addresses) < 0x800


def test_the_table_order_is_the_vms_own_opcode_order():
    """The names in rom_map are the decomp's table order; mystery_event.OPCODE_NAMES was written
    from the VM's behaviour on the console, run by run. They have to agree entry for entry."""
    from pokeldn.frlg.rom import mystery_event
    assert [name for name, _address in rom_map.MYSTERY_EVENT_HANDLERS] == [
        mystery_event.OPCODE_NAMES[opcode] for opcode in range(MYSTERY_EVENT_CMD_COUNT)]


def test_the_end_of_the_table_is_the_end_of_script_data():
    """`mystery_event_script_cmd_table.o(script_data)` is the LAST member of script_data and
    lib_text follows it [ld_script_rev10.ld:318-330]. A run read 0x4C41B510 at that address -
    `push {r4, lr}` - which is a THUMB prologue, so lib_text starts exactly there."""
    assert rom_map.SCRIPT_DATA_END == 0x081DE188
    assert rom_map.LIB_TEXT_START == rom_map.SCRIPT_DATA_END
    assert rom_map.SCRIPT_DATA_END == (rom_map.G_MYSTERY_EVENT_CMD_TABLE
                                       + 4 * MYSTERY_EVENT_CMD_COUNT)
    # and script_data has to contain everything already measured inside it
    for address in (rom_map.G_SCRIPT_CMD_TABLE, rom_map.G_SPECIALS, rom_map.G_STD_SCRIPTS):
        assert rom_map.G_SCRIPT_CMD_TABLE <= address < rom_map.SCRIPT_DATA_END


def test_the_vms_workers_were_read_by_position():
    """A run dumped 16 of the 17 handlers and the bl targets name themselves against the decomp's
    call order. Both dead opcodes - setrecordmixinggift and enableresetrtc - make exactly one call,
    to the same address, which is SetIncompatible: that is what makes them dead
    [decomp:src/mystery_event_script.c], and it is the shape the dump actually came back with."""
    assert rom_map.ME_SET_INCOMPATIBLE == 0x080DE330
    assert rom_map.ME_CHECK_COMPATIBILITY < rom_map.ME_SET_INCOMPATIBLE
    # the two statics sit BELOW the handlers, which is where a C file's helpers go
    assert rom_map.ME_SET_INCOMPATIBLE < min(
        address & ~1 for _name, address in rom_map.MYSTERY_EVENT_HANDLERS)


def test_memcpy_lands_inside_lib_text_and_checks_the_boundary():
    """addtrainer is `ScriptReadWord; memcpy; ValidateEReaderTrainer; StringExpandPlaceholders`
    [decomp:src/mystery_event_script.c], so its second call is memcpy - which comes from libgcc and
    lives in lib_text. It has to be above the boundary a run found by reading a THUMB prologue, and
    nothing about that reading knew anything about this handler."""
    assert rom_map.MEMCPY > rom_map.LIB_TEXT_START
    assert rom_map.STRING_EXPAND_PLACEHOLDERS < rom_map.G_SCRIPT_CMD_TABLE   # ordinary .text
    assert rom_map.INIT_RAM_SCRIPT < rom_map.G_SCRIPT_CMD_TABLE


def test_the_last_handler_is_bounded_by_its_own_epilogue():
    """MEScrCmd_crc is the LAST entry, so nothing after it stops a reader walking to the end of the
    dump - it first came back with 25 bl targets where the decomp gives it four. The trap is that
    this ROM is agbcc-built and does not end a THUMB function with `pop {..., pc}`: crc ends
    `pop {r4,r5,r6}; pop {r1}; bx r1` (BC70 BC02 4708). CalcCRC16 is the only worker it has."""
    assert rom_map.CALC_CRC16 == 0x080489A0
    assert rom_map.CALC_CRC16 < rom_map.G_SCRIPT_CMD_TABLE


def test_varset_was_reachable_only_through_the_vm():
    """No ScrCmd body calls VarSet - `setvar`'s worker is GetVarPointer and a store through what it
    returns, which is why call-chain grew its `prev` mechanism. The Mystery Event VM
    does call it: setenigmaberry ends `VarSet(VAR_ENIGMA_BERRY_AVAILABLE, 1)`.

    The check is the layout. event_data.c declares GetVarPointer, VarGet, VarSet in that order, and
    the gap between VarGet and VarSet is 0x1C - the whole of VarGet's body, which is one call, one
    null test and one load [decomp:src/event_data.c:235]."""
    assert rom_map.GET_VAR_POINTER < rom_map.VAR_GET < rom_map.VAR_SET
    assert rom_map.VAR_SET - rom_map.VAR_GET == 0x1C
    assert rom_map.callable_function("VarSet") == rom_map.VAR_SET | 1, "a call needs the THUMB bit"


def test_every_worker_read_off_the_vm_is_a_rom_address():
    for name in ("STRING_COPY_N", "STRING_COMPARE", "SET_ENIGMA_BERRY", "ITEM_IS_MAIL",
                 "GIVE_MAIL_TO_MON2", "COMPACT_PARTY_SLOTS", "GET_SET_POKEDEX_FLAG",
                 "SPECIES_TO_NATIONAL_POKEDEX_NUM", "CALC_CRC16", "VAR_SET"):
        address = getattr(rom_map, name)
        assert 0x08000000 < address < rom_map.G_SCRIPT_CMD_TABLE, f"{name} is not in .text"
        assert address % 2 == 0, f"{name} is stored even; the THUMB bit goes on at the call"
