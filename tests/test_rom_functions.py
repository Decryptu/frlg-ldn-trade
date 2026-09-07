"""Reading THUMB bodies out of a dump: where a function ends, what it calls, what it points at.

bs84's method - a handler is an entry point and the worker behind it is what is worth calling - as
a module, so that any of the four function tables this project has read off a cartridge can be
interpreted from the same 1 KB window. The fixtures are console bytes, not the decomp's.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import rom_map, scrcmd, scrcmd_names, special_names, thumb  # noqa: E402
from pokeldn.frlg.text import charmap  # noqa: E402

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


def test_the_high_leafgreen_segment_reaches_down_to_the_m4a_tables():
    """bs117/lg190. The -0x12D8 segment used to start at 0x086003E0; five paired literal-pool words
    from the same m4a window on each console carried it down to 0x0847DCF8, which is a 3.5x
    narrowing of the last big gap for two runs."""
    low, high, delta, _evidence = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS
                                   if seg[2] == -0x12D8][0]
    # Session 48 carried the low end down 138 KB further, from a direction the m4a pools knew
    # nothing about: bs129/lg195 read -0x12D8 at four paired blocks, two of them 884 of 884 bytes.
    assert (low, high) == (0x0845F000, 0x086803FC)
    for firered, leafgreen in ((0x0847DCF8, 0x0847CA20), (0x0847DDAC, 0x0847CAD4),
                               (0x0847DF10, 0x0847CC38), (0x0849758C, 0x084962B4),
                               (0x084975BC, 0x084962E4)):
        assert leafgreen - firered == delta
        assert rom_map.leafgreen_guess(firered) == leafgreen


def test_the_two_sound_tables_are_four_music_players_apart():
    """What proves the pair's alignment without a second run: struct MusicPlayer is 12 bytes and
    music_player_table.inc has four of them, so gSongTable must sit exactly 0x30 above gMPlayTable
    on BOTH cartridges. It does."""
    assert rom_map.G_SONG_TABLE - rom_map.G_MPLAY_TABLE == 4 * 12
    assert (rom_map.leafgreen_guess(rom_map.G_SONG_TABLE)
            - rom_map.leafgreen_guess(rom_map.G_MPLAY_TABLE)) == 4 * 12


def test_the_gap_that_is_left_is_the_one_the_boundary_table_names():
    """A boundary that has been bracketed is not a boundary that has been found. The remaining span
    is where -0x1C4 becomes -0x12D8, and `leafgreen_guess` must still REFUSE inside it rather than
    interpolate."""
    # Session 48 split this boundary in two: there is a -0x124C segment in the middle of it, which
    # is the same lesson -0x20 taught in session 42. What is left is the span either side of it.
    boundary = [b for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES if b[:2] == (-0x1C4, -0x124C)][0]
    _from, _to, low, high = boundary[:4]
    assert (low, high) == (0x0843AFFF, 0x08442800)
    for inside in (low + 1, (low + high) // 2, high - 1):
        try:
            rom_map.leafgreen_guess(inside)
        except ValueError:
            continue
        raise AssertionError(f"0x{inside:08X} is in a gap and must not be guessed at")


def test_stop_script_and_script_context_stop_are_two_different_functions():
    """Named wrong until bs121. 0x0806D0EC is ScrCmd_end's one call and the decomp gives that as
    StopScript(ctx) [src/script.c:76]; ScriptContext_Stop(void) [:360] is a different function, and
    it is 0x0806D418 - what ScrCmd_waitstate calls and nothing else does. The declaration order
    agrees with the addresses, which is the check that costs no run."""
    assert rom_map.STOP_SCRIPT == 0x0806D0EC
    assert rom_map.SCRIPT_CONTEXT_STOP == 0x0806D418
    assert rom_map.STOP_SCRIPT < rom_map.SCRIPT_CONTEXT_STOP, "script.c:76 comes before script.c:360"


def test_the_field_command_table_is_closed():
    """213 handlers, and after bs121 every one of their bodies has been read off the cartridge.
    The table itself was dumped at bs82; this is the code behind it."""
    assert len(scrcmd_names.HANDLERS) == 214      # 214 opcodes, two of them the same ScrCmd_nop
    assert len(set(scrcmd_names.HANDLERS)) == 213


def test_the_workers_bs121_named_match_how_many_commands_call_them():
    """The caller COUNT is the check. `Compare` has to be reached by exactly the eight compare_*
    commands the decomp declares - a worker named off one caller is a guess."""
    compares = [name for name in scrcmd_names.COMMANDS if name.startswith("compare_")]
    assert len(compares) == 8
    assert rom_map.COMPARE == 0x0806DCCC
    assert rom_map.STRING_COPY == 0x0800C894
    assert rom_map.HIDE_FIELD_MESSAGE_BOX == 0x0806CDE4
    assert rom_map.SCRIPT_MOVEMENT_START == 0x0809AE54


def test_the_easy_chat_segment_reaches_out_both_ways_after_bs120_lg191():
    """One needle moves one end. 27 paired literal-pool words moved BOTH: the -0x1C4 segment was
    0x083DE528..0x083E3700, 21 KB, and 0x083BEE74..0x0841463E after bs120/lg191. Session 48's
    paired scattered blocks moved both ends again, to a boundary either side rather than a pool."""
    low, high, delta, _e = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS if seg[2] == -0x1C4][0]
    assert (low, high) == (0x083B8000, 0x0843AFFF)
    assert rom_map.leafgreen_guess(0x083BEE74) == 0x083BEE74 - 0x1C4
    assert rom_map.leafgreen_guess(0x0841463E) == 0x0841463E - 0x1C4
    # The control that rode along: 0x082370FC is inside the measured -0x24 segment, and lg191 read
    # it back at -0x24. A run that answered otherwise there was answering about the wrong console.
    assert rom_map.leafgreen_guess(0x082370FC) == 0x082370FC - 0x24


def test_no_boundary_is_wider_than_the_evidence_that_brackets_it():
    """Every gap must still be REFUSED end to end - narrowing a segment without moving the boundary
    beside it would leave leafgreen_guess quietly interpolating across a boundary."""
    for _before, _after, low, high, _evidence in rom_map.LEAFGREEN_DELTA_BOUNDARIES:
        for inside in (low + 1, (low + high) // 2, high - 1):
            try:
                rom_map.leafgreen_guess(inside)
            except ValueError:
                continue
            raise AssertionError(f"0x{inside:08X} is inside a boundary and was guessed at")


def test_there_is_a_minus_0x20_segment_between_the_species_table_and_easy_chat():
    """bs121/lg192. Nobody had seen it, and it is WHY 0x0824CDFC..0x083BEE74 looked like one 1.5 MB
    gap: the delta does not go -0x24 straight to -0x1C4, it sits at -0x20 for 1256 KB on the way.
    Two points that far apart at one delta is a segment; one point is lg167's mistake."""
    low, high, delta, _e = [seg for seg in rom_map.LEAFGREEN_DELTA_SEGMENTS if seg[2] == -0x20][0]
    assert (low, high) == (0x08251DAD, 0x083B7B47)
    assert high - low > 1024 * 1024, "one point pretending to be a segment"
    assert rom_map.leafgreen_guess(0x08265950) == 0x08265950 - 0x20
    assert rom_map.leafgreen_guess(0x0839F83C) == 0x0839F83C - 0x20
    # The ends session 48 measured, 31 bytes and one block wide respectively.
    assert rom_map.leafgreen_guess(0x08251DAD) == 0x08251DAD - 0x20
    assert rom_map.leafgreen_guess(0x083B7B47) == 0x083B7B47 - 0x20
    # Both controls came out of the SAME pairing, on either side of the new segment.
    assert rom_map.leafgreen_guess(0x0823E514) == 0x0823E514 - 0x24
    assert rom_map.leafgreen_guess(0x083D6BDC) == 0x083D6BDC - 0x1C4


def test_the_four_low_segments_step_by_exactly_four_bytes():
    """CORROBORATION for -0x20, from a direction bs121/lg192 knew nothing about. The deltas do NOT
    simply grow along the link order - the four low segments are -0x2C, -0x28, -0x24 and -0x20,
    each four bytes LESS divergent than the one below it. -0x20 continues that run exactly, which
    is not what a pairing read at the wrong offset produces."""
    low = [d for _lo, _hi, d, _e in rom_map.LEAFGREEN_DELTA_SEGMENTS if -0x2C <= d < 0]
    assert low == [-0x2C, -0x28, -0x24, -0x20]
    assert all(b - a == 4 for a, b in zip(low, low[1:]))


def test_the_segments_are_in_address_order_and_never_overlap():
    """Two segments claiming the same address means one of them is measured wrong, and
    leafgreen_guess would answer with whichever came first."""
    bounds = [(lo, hi) for lo, hi, _d, _e in rom_map.LEAFGREEN_DELTA_SEGMENTS]
    assert bounds == sorted(bounds), "segments must be in address order"
    for (_lo, hi), (nlo, _nhi) in zip(bounds, bounds[1:]):
        assert hi < nlo, "two segments overlap: one of them is measured wrong"
