"""Reading THUMB bodies out of a dump: where a function ends, what it calls, what it points at.

bs84's method - a handler is an entry point and the worker behind it is what is worth calling - as
a module, so that any of the four function tables this project has read off a cartridge can be
interpreted from the same 1 KB window. The fixtures are console bytes, not the decomp's.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import charmap, rom_map, scrcmd, scrcmd_names, special_names, thumb  # noqa: E402

# ScrCmd_special and the literal pool immediately after it, as bs92 dumped it. The two words in the
# pool ARE gSpecials and gSpecialsEnd: this is the run that located the table.
SPECIAL_BASE = 0x0806D7EC
SPECIAL_BYTES = bytes.fromhex(
    "00b5fff7fbfc0004800b054941180548814202d2086874f10ffd002002bc0847"
    "fc391608ec40160830b5041c"
)

# MEScrCmd_crc and the prologue of whatever follows it, as bs112 dumped it. The epilogue here is
# `pop {r4,r5,r6}; pop {r1}; bx r1` - agbcc's, not `pop {..., pc}`.
CRC_BASE = 0x080DE830
CRC_BYTES = bytes.fromhex(
    "70b5061c8ef7e4fc051c301c8ef7e0fc041cb06e241a706e2418301c8ef7d8fc"
    "011cb06e091a706e0918091b201c6af79ff80004000c854203d0002030670120"
    "f066012070bc02bc08470000f0b5474680b4061c0c1c15062d0e"
)

# The string Std_ObtainItem points at, off the French cartridge (bs107): a placeholder, then '!'.
OBTAINED_TEXT = bytes.fromhex("c9d6e8d9e2e9f000fd03ab")


def test_the_literal_pool_of_scrcmd_special_is_where_gspecials_came_from():
    """bs92 read the table's address out of this function's pool by eye. The reader has to get the
    same two words, because the difference between them - 444 * 4 - is what proved the length."""
    values = [value for _site, _pool, value
              in thumb.pc_literals(SPECIAL_BYTES, SPECIAL_BASE, SPECIAL_BASE,
                                   SPECIAL_BASE + len(SPECIAL_BYTES))]
    assert values == [rom_map.G_SPECIALS, rom_map.G_SPECIALS_END]
    assert rom_map.G_SPECIALS_END - rom_map.G_SPECIALS == len(special_names.SPECIALS) * 4


def test_scrcmd_special_calls_the_argument_reader_and_then_the_table():
    """Every ScrCmd body is `VarGet(ScriptReadHalfword(ctx))` per argument and then one call. This
    one reads a halfword and then `bx`es through the table, so ScriptReadHalfword is the check that
    the window is decoded at the right offset."""
    targets = [target for _site, target
               in thumb.bl_targets(SPECIAL_BYTES, SPECIAL_BASE, SPECIAL_BASE,
                                   SPECIAL_BASE + len(SPECIAL_BYTES))]
    assert rom_map.SCRIPT_READ_HALFWORD in targets


def test_a_function_ends_on_the_agbcc_epilogue_not_only_on_pop_pc():
    """THE TRAP. This ROM is agbcc-built and ends a THUMB function `pop {r4,r5,r6}; pop {r1};
    bx r1`. A reader looking only for 0xBDxx walks into the next function, which is how crc first
    came back with 25 `bl` targets instead of four."""
    limit = CRC_BASE + len(CRC_BYTES)
    end = thumb.function_end(CRC_BYTES, CRC_BASE, CRC_BASE, limit)
    assert end < limit, "the epilogue was not found: bx Rn is not being treated as a return"
    # It ends after `bx r1`, before the padding and the next function's `push {r4-r7, lr}`.
    assert CRC_BYTES[end - CRC_BASE - 2:end - CRC_BASE] == bytes.fromhex("0847")
    assert end - CRC_BASE == 74


def test_the_crc_handler_makes_the_four_calls_the_decomp_gives_it():
    """The whole point of the boundary: bounded to its own body, crc reads its three words and
    calls CalcCRC16 once. Unbounded it swallowed the next function and came back with 25."""
    end = thumb.function_end(CRC_BYTES, CRC_BASE, CRC_BASE, CRC_BASE + len(CRC_BYTES))
    targets = [t for _s, t in thumb.bl_targets(CRC_BYTES, CRC_BASE, CRC_BASE, end)]
    assert targets == [rom_map.SCRIPT_READ_WORD] * 3 + [rom_map.CALC_CRC16]


def test_every_table_entry_is_an_even_cartridge_address_the_thumb_bit_is_added_back():
    """The dumps came back as odd THUMB pointers and the tables keep them stripped, so a body can be
    read at the address directly; `rom_map.thumb` is what puts the bit back for a `bx`. An entry
    that is odd HERE would mean the two conventions had been mixed, and every body read one byte
    late is a different function."""
    for table in (rom_map.SPECIAL_ADDRESSES, scrcmd_names.HANDLERS):
        for address in table:
            assert not address & 1, f"0x{address:08X} still carries the THUMB bit"
            assert 0x08000000 <= address < 0x08800000
            assert rom_map.thumb(address) == address | 1


def test_a_message_string_keeps_its_placeholders():
    """`decode` is for a name and turns a control code into '.'. A string a script points at is
    dialogue: the first one read off this console was 'Obtenu: {STR_VAR_2}!' and the placeholder is
    most of what it says."""
    assert charmap.decode_message(OBTAINED_TEXT) == "Obtenu: {STR_VAR_2}!"
    assert charmap.decode(OBTAINED_TEXT) == "Obtenu: .Â!"


def test_read_string_refuses_a_string_whose_end_the_dump_does_not_hold():
    """A truncated string is the one case where the missing part is the part worth reading, so it
    comes back None and stays on the list of addresses to dump rather than printing a half."""
    memory = scrcmd.Memory([(0x081A79F0, OBTAINED_TEXT)])
    assert scrcmd.read_string(memory, 0x081A79F0) is None
    whole = scrcmd.Memory([(0x081A79F0, OBTAINED_TEXT + b"\xff")])
    assert scrcmd.read_string(whole, 0x081A79F0) == "Obtenu: {STR_VAR_2}!"


def test_data_pointers_reports_what_a_script_points_at_and_the_dump_holds():
    """`follow` answers with what is MISSING, because that is what a run is spent on. This is the
    other half: a text operand already inside a dump is a string to print, not an address to want."""
    # `msgbox <0x081A79F0>, 4` then `end` - the shape of Std_ObtainItem's message.
    script = bytes.fromhex("67f0791a08") + bytes([0x04]) + bytes.fromhex("02")
    memory = scrcmd.Memory([(0x081A7600, script), (0x081A79F0, OBTAINED_TEXT + b"\xff")])
    reached, referenced = scrcmd.follow(memory, 0x081A7600)
    assert referenced == {}, "the string is held, so nothing should be wanted"
    held = scrcmd.data_pointers(memory, reached)
    assert 0x081A79F0 in held
    assert scrcmd.read_string(memory, 0x081A79F0) == "Obtenu: {STR_VAR_2}!"


# --- what bs113 and bs114 read off the cartridge ------------------------------------------------

def test_null_field_special_is_a_two_byte_bx_lr():
    """171 of the 444 indices point here. bs93's alignment argument was that they must all come
    back with ONE address; bs113 read the function and it does nothing at all."""
    assert rom_map.NULL_FIELD_SPECIAL == 0x080CE8DC
    assert rom_map.SPECIAL_ADDRESSES.count(rom_map.NULL_FIELD_SPECIAL) == 171
    body = bytes.fromhex("7047")     # bx lr
    end = thumb.function_end(body, rom_map.NULL_FIELD_SPECIAL, rom_map.NULL_FIELD_SPECIAL,
                             rom_map.NULL_FIELD_SPECIAL + len(body))
    assert thumb.is_return(int.from_bytes(body, "little"))
    assert end == rom_map.NULL_FIELD_SPECIAL + 2


def test_get_battle_outcome_is_one_load_of_the_global_it_is_named_for():
    """`ldr r0, [pc, #4]; ldrb r0, [r0]; bx lr` and a pool word. The pool word is gBattleOutcome,
    which is how a one-line special names a global with no search."""
    base = 0x080CE268
    body = bytes.fromhex("0148007870470000") + rom_map.GBATTLE_OUTCOME.to_bytes(4, "little")
    literals = thumb.pc_literals(body, base, base, base + len(body))
    assert [value for _site, _pool, value in literals] == [rom_map.GBATTLE_OUTCOME]


def test_the_special_var_sequence_is_the_one_shakescreen_reads():
    """G_SPECIAL_VAR_0X8000 was measured and the rest of the sequence was left UNCONFIRMED because
    event_data.c's declaration order is not the table's. ShakeScreen takes four arguments and loads
    four consecutive halfwords, which settles the spacing without another run."""
    assert rom_map.G_SPECIAL_VAR_0X8004 == 0x020370BC
    reads = [rom_map.G_SPECIAL_VAR_0X8004, rom_map.G_SPECIAL_VAR_0X8005,
             rom_map.G_SPECIAL_VAR_0X8006, rom_map.G_SPECIAL_VAR_0X8007]
    assert reads == [0x020370BC, 0x020370BE, 0x020370C0, 0x020370C2]
    assert all(b - a == 2 for a, b in zip(reads, reads[1:])), "a var id is two bytes"


def test_the_specials_table_names_its_own_entries():
    """ShowDiploma and ShowTownMap both call QuestLog_CutRecording, which IS special 392 - the same
    self-confirmation DoDiveWarp gave between the script-command and specials tables. A table that
    names its own entry cannot have been placed by the decomp alone."""
    quest_log_cut_recording = 0x08115E58
    assert rom_map.SPECIAL_ADDRESSES[392] == quest_log_cut_recording
    assert special_names.SPECIALS[392] == "QuestLog_CutRecording"


def test_get_lead_mon_index_is_the_body_four_lead_mon_specials_share():
    """Named by its calls, not its position: CalculatePlayerPartyCount and then GetMonData twice is
    the decomp's GetLeadMonIndex command for command, and CalculatePlayerPartyCount is itself
    special 131."""
    assert rom_map.GET_LEAD_MON_INDEX == 0x080CE818
    assert rom_map.SPECIAL_ADDRESSES[131] == rom_map.CALCULATE_PLAYER_PARTY_COUNT
    for index in (230, 292, 293, 294):
        assert special_names.SPECIALS[index] in (
            "GetLeadMonFriendship", "LeadMonHasEffortRibbon",
            "GiveLeadMonEffortRibbon", "AreLeadMonEVsMaxedOut")
