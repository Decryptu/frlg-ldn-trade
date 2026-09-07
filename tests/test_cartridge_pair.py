"""Pairing the two cartridges' copies of one window, and the delta map that comes out of it.

lg169 made this measurement without naming it: a POINTER dumped off both consoles is a delta point
at wherever it points. `tools/frlg/cartridge_pair.py` reads both kinds out of a window held on both
cartridges - the literal-pool words, which sessions 40 and 41 paired by hand, and the `bl` targets,
which nothing had. A `bl` is a RELATIVE call, so the same instruction resolves to a different
address on each cartridge and the pair is two measurements rather than one plus an assumed delta.

WHAT SAYS THE PAIRING IS REAL: every site pairs, and the deltas come out quantised. 734 of 734 and
834 of 834 across the two 16 KB pairs, four delta values each, no outliers. The first version of the
tool computed the LeafGreen offsets off the FireRed base and answered with 64 deltas, none repeated -
which is what a misplaced window looks like and why the count is checked.

TWO INDEPENDENT CONFIRMATIONS, from runs that knew nothing about this: the pairing puts LeafGreen's
`AddBagItem` at 0x0809DA44, which is where lg189 measured it, and `Random` at 0x080486B0, which is
where lg162 did.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

from pokeldn.frlg.rom import leafgreen_twins, rom_map  # noqa: E402
from cartridge_pair import (boundaries, candidate_pairs, paired_calls,          # noqa: E402
                            paired_literals, segments)

ROM_START, ROM_END = 0x08000000, 0x0A000000


def bl(site, target):
    """-> the four bytes of `bl target` at `site`, which is what bl_targets reads back."""
    offset = target - (site + 4)
    hi = 0xF000 | ((offset >> 12) & 0x7FF)
    lo = 0xF800 | ((offset >> 1) & 0x7FF)
    return hi.to_bytes(2, "little") + lo.to_bytes(2, "little")


def window(base, calls):
    """-> a little code window with `bl`s in it: {offset: target}."""
    data = bytearray(b"\x00\x20" * 32)                 # mov r0, #0 as filler
    for offset, target in calls.items():
        data[offset:offset + 4] = bl(base + offset, target)
    return bytes(data)


# --- the pairing --------------------------------------------------------------------------------

def test_the_same_call_on_both_cartridges_is_two_measurements():
    # The instruction is identical; what differs is where it lands, and that difference IS the delta
    # at the target. Here one call does not move and one moves by -0x2C.
    firered = ("bs", "firered", 0x08081CC8, window(0x08081CC8, {8: 0x0800053C, 16: 0x08083910}))
    leafgreen = ("lg", "leafgreen", 0x08081C9C, window(0x08081C9C, {8: 0x0800053C,
                                                                    16: 0x08083910 - 0x2C}))
    assert paired_calls(firered, leafgreen) == [(0x0800053C, 0x0800053C),
                                                (0x08083910, 0x08083910 - 0x2C)]


def test_a_window_is_paired_by_code_offset_not_by_base():
    # The LeafGreen run is aimed at the twin of the FireRed window, so offset N is offset N whatever
    # the bases are. Reading the LeafGreen sites off the FireRed base shifts every pair by the code
    # delta and invents deltas - it is what 64 unrepeated values looked like.
    calls = {4: 0x08040000, 12: 0x08090000}
    firered = ("bs", "firered", 0x08081CC8, window(0x08081CC8, calls))
    leafgreen = ("lg", "leafgreen", 0x08081C9C,
                 window(0x08081C9C, {offset: target for offset, target in calls.items()}))
    assert [theirs - ours for ours, theirs in paired_calls(firered, leafgreen)] == [0, 0]


def test_a_pool_word_is_counted_once_however_many_instructions_read_it():
    # Two instructions over the same word are one measurement, not two.
    # `ldr r0, [pc, #4]` at offsets 0 and 2 both resolve to the word at offset 8: THUMB rounds the
    # PC down to a word before adding the immediate, which is why the two encodings are the same.
    reads = bytes.fromhex("0148") + bytes.fromhex("0148") + b"\x00\x00\x00\x00"
    body = reads + (0x083BEE74).to_bytes(4, "little")
    theirs = reads + (0x083BEE74 - 0x1C4).to_bytes(4, "little")
    firered = ("bs", "firered", 0x08081CC8, body)
    leafgreen = ("lg", "leafgreen", 0x08081C9C, theirs)
    assert paired_literals(firered, leafgreen) == [(0x083BEE74, 0x083BEE74 - 0x1C4)]


def test_two_windows_are_only_a_pair_when_they_hold_the_same_code():
    same = window(0x08081CC8, {8: 0x0800053C})
    everything = [("bs", "firered", 0x08081CC8, same),
                  ("lg", "leafgreen", 0x08081C9C, same),
                  ("lgx", "leafgreen", 0x08000000, b"\xFF" * len(same))]
    found = [(fr, lg) for fr, lg, _delta, _alike in candidate_pairs(everything)]
    assert found == [("bs", "lg")]


def test_a_boundary_is_the_span_between_two_segments_in_rom_order():
    # Ordered by where they sit, NOT by delta: the low segments step -0x2C, -0x28, -0x24, -0x20, so
    # reading a less divergent segment as a mistake is how a boundary lands in the wrong place.
    spans = segments([(0x08000000, 0x08000000), (0x0807AF04, 0x0807AF04),
                      (0x0807E068, 0x0807E068 - 0x2C), (0x080D4404, 0x080D4404 - 0x2C)])
    assert boundaries(spans) == [(0x0, -0x2C, 0x0807AF04, 0x0807E068)]


# --- what it measured ---------------------------------------------------------------------------

def test_the_pairing_puts_leafgreen_where_two_runs_of_its_own_had_measured_it():
    # Neither run knew about this method: lg189 needled AddBagItem and lg162 read Random out of a
    # literal pool, and the paired call sites land on both.
    assert leafgreen_twins.TWINS[0x0809DA70] == rom_map.LEAFGREEN_ADD_BAG_ITEM
    assert leafgreen_twins.TWINS[0x080486B0] == rom_map.LEAFGREEN["Random"][0]


def test_every_twin_agrees_with_the_segment_it_falls_in():
    # 738 measured pairs against seven segments measured from other directions. A twin inside a
    # segment whose delta is known must show that delta; one inside a BOUNDARY is where the map has
    # nothing to say, and those are the points that narrow it.
    inside, checked = 0, 0
    for ours, theirs in leafgreen_twins.TWINS.items():
        for low, high, delta, _evidence in rom_map.LEAFGREEN_DELTA_SEGMENTS:
            if low <= (ours & ~1) <= high:
                checked += 1
                assert theirs - ours == delta, f"0x{ours:08X} -> 0x{theirs:08X}"
                inside += 1
    assert inside > 700 and checked == inside


def test_no_twin_falls_inside_a_boundary_that_is_still_recorded_as_unknown():
    # The segment map was moved to the last point that agrees with it; anything left in a boundary
    # would mean a measurement the map is ignoring.
    for ours, theirs in leafgreen_twins.TWINS.items():
        for _from, _to, low, high in [(b[0], b[1], b[2], b[3])
                                      for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES]:
            assert not (low < (ours & ~1) < high), f"0x{ours:08X} -> 0x{theirs:08X} is in a gap"


def test_a_twin_answers_exactly_and_an_unmeasured_address_falls_back_to_the_guess():
    assert leafgreen_twins.leafgreen(0x0809DA70) == rom_map.LEAFGREEN_ADD_BAG_ITEM
    assert leafgreen_twins.leafgreen(0x0809DA71) == rom_map.LEAFGREEN_ADD_BAG_ITEM | 1
    # Not measured, but inside a segment: the delta answers.
    assert leafgreen_twins.leafgreen(0x08000010) == 0x08000010
    # Not measured and inside a boundary: refuse rather than interpolate.
    with pytest.raises(ValueError):
        leafgreen_twins.leafgreen(rom_map.LEAFGREEN_DELTA_BOUNDARIES[0][2] + 0x10)


def test_the_twins_are_rom_addresses():
    assert leafgreen_twins.TWIN_COUNT >= 700
    assert all(ROM_START <= ours < ROM_END and ROM_START <= theirs < ROM_END
               for ours, theirs in leafgreen_twins.TWINS.items())


def test_a_leafgreen_view_of_a_table_is_moved_to_where_leafgreen_keeps_it():
    """Every table this project holds was read off FireRed. Reading a LeafGreen dump against those
    addresses is coherent in the delta-0 region and quietly wrong above it - the entry, the body and
    the names all have to move. An entry inside a BOUNDARY has no measured address on the other
    cartridge and is dropped rather than read at a guess."""
    from rom_functions import deduplicate, known_names, on_leafgreen, tables
    entries = deduplicate(tables()["specials"])
    moved, names = on_leafgreen(entries, known_names())
    # Session 48: EVERY special moves now. The boundaries used to be kilobytes wide and swallowed
    # entries; measured to between 31 and 644 bytes, not one of the 272 falls inside one.
    assert len(moved) == len(entries)
    with pytest.raises(ValueError, match="gap between measured segments"):
        rom_map.leafgreen_guess(0x08148100)               # inside the -0x28 -> -0x24 divergence
    by_label = dict(moved)
    # Below the split the two cartridges agree, and above it the entry moves by its own delta.
    assert by_label["CalculatePlayerPartyCount [131]"] == 0x08044338
    assert by_label["HealPlayerParty [0]"] == 0x080A3A64 - 0x2C
    assert names[rom_map.LEAFGREEN_ADD_BAG_ITEM] == "AddBagItem"
