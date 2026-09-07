"""The English rev10 build's reading of our French addresses, and the control that licenses it.

Nothing here needs the build: `pokeldn/frlg/rom/english_names.py` is generated and committed, and
these are the checks that say what it is allowed to claim. `tools/frlg/english_build.py` and
`docs/frlg_english_build.md` carry the method.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.frlg.rom import english_names, rom_map, worker_names  # noqa: E402

ROM_START, ROM_END = 0x08000000, 0x0A000000


def test_it_agrees_with_every_name_the_console_itself_proved():
    """THE CONTROL, and the only reason this table is allowed to exist. `worker_names` is a reading
    of the console: a body dumped off the cartridge calling what the decomp says that function
    calls, in that order. The English build reaches the same addresses a completely different way -
    a byte-identical build of the ENGLISH release of the same revision, placed by content. Where
    both speak they must not disagree once, and they do not."""
    agreed = 0
    for address, ours in worker_names.WORKERS.items():
        theirs = english_names.name(address)
        if theirs is None:
            continue
        agreed += 1
        assert theirs == ours or theirs.lstrip("_") == ours.lstrip("_"), \
            f"0x{address:08X}: we measured {ours}, the English build reads {theirs}"
    assert agreed > 200, "the control is only worth something if it covers most of the table"


def test_the_offsets_are_measured_spans_and_do_not_overlap():
    """An offset run is a claim about a REGION: French + offset = English, everywhere between its
    ends. Two overlapping runs would be two claims about one address, and an unsorted table would
    make `offset()` answer with whichever came first rather than the one that covers the address."""
    previous = None
    for low, high, _offset, points in english_names.OFFSETS:
        assert ROM_START <= low <= high < ROM_END
        assert points >= 2, "one point is a coincidence, not a run"
        if previous is not None:
            assert low > previous, f"0x{low:08X} overlaps the run that ends at 0x{previous:08X}"
        previous = high


def test_a_bracketed_name_is_marked_as_the_weaker_reading_it_is():
    """BRACKETED is named with an offset measured either side of the address rather than at it. It
    is kept in its own table so that no reader can mistake one for a measurement, and the two tables
    never both answer for an address."""
    assert not set(english_names.NAMES) & set(english_names.BRACKETED)
    for address, (name, offset) in english_names.BRACKETED.items():
        assert ROM_START <= address < ROM_END
        assert english_names.offset(address) is None, \
            f"0x{address:08X} is inside a measured run and does not need bracketing"
        assert isinstance(name, str) and isinstance(offset, int)


def test_the_three_division_helpers_are_what_session_42_said_would_be_left():
    """The corroboration worth keeping. Session 42 named 183 workers by zipping a body's measured
    calls against the decomp's, and said what the residue was: the 22 bodies where the compiler
    changed the call list, `__umodsi3` among them - agbcc emitting a helper for a division nobody
    wrote. Three call targets survived every later reading, reached from a dozen bodies each, and
    the English build reads them as exactly those helpers. Neither reading knew about the other."""
    helpers = {english_names.bracketed_name(a) for a in (0x081E2694, 0x081E2770, 0x081E2D00)}
    assert helpers == {"__divsi3", "__modsi3", "__umodsi3"}


def test_it_does_not_shadow_what_the_project_measured():
    """A name here never overrules `rom_map.CALLABLE` - an address this project CALLED on hardware,
    where something visible happened. Where both hold an address they have to say the same thing."""
    for name, address in rom_map.CALLABLE.items():
        theirs = english_names.name(address)
        if theirs is None:
            continue
        assert theirs == name or theirs.lstrip("_") == name.lstrip("_"), \
            f"0x{address:08X}: called on hardware as {name}, English build reads {theirs}"
