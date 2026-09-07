#!/usr/bin/env python3
"""The ENGLISH rev10 build, used as an instrument on the FRENCH cartridges. Offline, no run.

    ./.venv/bin/python tools/frlg/english_build.py --check        # the control: our names vs its
    ./.venv/bin/python tools/frlg/english_build.py --offsets      # French -> English, by address
    ./.venv/bin/python tools/frlg/english_build.py --names        # what it names that we could not
    ./.venv/bin/python tools/frlg/english_build.py --boundaries   # the LeafGreen delta map, predicted
    ./.venv/bin/python tools/frlg/english_build.py --plan         # what to dump to close it

WHAT THIS IS. `pret/pokefirered` builds `firered_switch` and `leafgreen_switch` - REVISION 10, the
build the Switch release runs - and both come out byte-identical to the sha1 the decomp pins. It is
the ENGLISH release, so it is NOT this project's cartridges: at the same address the French console
and the English build agree on 3.7% of their bytes, because French text is a different length and
everything after a string moves. What it is instead is a second cartridge PAIR whose every symbol,
section and object is known, and the two pairs are built from the same source in the same order.

THE MEASUREMENT. A French address and an English address hold the same function whenever the content
matches, and the difference between them - the OFFSET - is piecewise constant, stepping only where a
language-dependent object changes size. Two independent readings give it, and they agree everywhere
both speak:

  1. THE TABLES, free. `gSpecials[i]`, `gScriptCmdTable[i]` and `gMysteryEventScriptCmdTable[i]` are
     the same function on both builds, so entry i on the console and entry i in the English ROM are
     an offset point. 675 of them, off dumps already on disk, no fingerprinting and no run.
  2. THE DUMPS. A 16-byte window that occurs exactly once in the English ROM places the French bytes
     that equal it. Thousands of windows per dump, and a disagreement inside one run is visible.

WHAT IT ANSWERS. Given the offset at an address, a French address becomes an English address, and
the English ELF names it - statics included, which the link map does not carry. THE CONTROL IS THE
POINT: run it against the 301 workers this project measured off the console's own bodies and it
agrees 80 times and disagrees 0 times. A name from here is a DEDUCTION with that control behind it,
never a measurement; `rom_map.CALLABLE` still means "called on hardware and something happened".

AND THE LEAFGREEN DELTA MAP. The English pair's own FireRed<->LeafGreen delta map is computable
exactly, by comparing the two ROMs: 0, -0x2c, -0x28, -0x24, -0x20, -0x1c4 - the same six values the
French cartridges measured, in the same order. Each step happens inside a version-divergent object,
not at its edge (title_screen.o, mystery_event_script.o, mystery_gift.o, pokemon.o, title_screen.o
again), and byte comparison brackets each one to a few hundred bytes. Carried across by the offset
map, that predicts where the French boundary is. A prediction, not a measurement - see --plan for
what to dump to settle it, and docs/frlg_leafgreen.md for what it is worth.

The build is not in this repository and never will be: it is a ROM. `scratchpad/build_decomp.sh`
makes it from the decomp in about two minutes, and both sha1s must match the decomp's own before any
of this is worth reading.
"""
import argparse
import collections
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.rom import rom_map, scrcmd_names, worker_names
from script_read import dumps

BUILD = os.environ.get("POKEFIRERED", os.path.expanduser("~/pokefirered"))
ROM_START, ROM_END = 0x08000000, 0x0A000000
WINDOW = 16              # how many bytes must be unique in the English ROM to place French bytes
MIN_VOTES = 8            # how many agreeing windows make an offset run worth reporting

BUILDS = {"firered": ("pokefirered_switch", "firered_switch.sha1"),
          "leafgreen": ("pokeleafgreen_switch", "leafgreen_switch.sha1")}


def build_path(console, extension):
    return os.path.join(BUILD, BUILDS[console][0] + extension)


def check_build(console):
    """-> None, or the reason this build cannot be trusted. The sha1 the decomp pins is the check."""
    rom = build_path(console, ".gba")
    if not os.path.exists(rom):
        return f"{rom} does not exist - run scratchpad/build_decomp.sh"
    want = open(os.path.join(BUILD, BUILDS[console][1])).read().split()[0]
    got = subprocess.run(["sha1sum", rom], capture_output=True, text=True).stdout.split()[0]
    return None if got == want else f"{rom} is {got}, the decomp pins {want}"


class English:
    """The English build of one cartridge: its bytes, its symbols and where a window of ours is."""

    def __init__(self, console):
        self.console = console
        self.rom = open(build_path(console, ".gba"), "rb").read()
        self._index = None
        self._symbols = None
        self._code = set()

    @property
    def symbols(self):
        """-> {address: (name, ...)}, off the ELF so that STATIC functions are in it too.

        An address can carry several names: `GetBoxMonData2` is `__attribute__((alias))` of
        `GetBoxMonData3` [decomp:src/pokemon.c:3332], one function with two symbols, and reading
        only the first would report a disagreement where there is none."""
        if self._symbols is None:
            out = collections.defaultdict(list)
            code = set()
            text = subprocess.run(["arm-none-eabi-nm", "-n", build_path(self.console, ".elf")],
                                  capture_output=True, text=True).stdout
            for line in text.splitlines():
                parts = line.split()
                if len(parts) == 3 and parts[1] in "tTdDrRbB":
                    address, name = int(parts[0], 16), parts[2]
                    if parts[1] in "tT":
                        code.add(address & ~1)
                    if name.startswith(".") or name.startswith("$"):
                        continue          # .gcc2_compiled. marks a file and sits on its first symbol
                    if ROM_START <= address < ROM_END and name not in out[address & ~1]:
                        out[address & ~1].append(name)
            self._symbols = {a: tuple(n) for a, n in out.items()}
            self._code = code
        return self._symbols

    @property
    def code(self):
        """-> the addresses that start a FUNCTION. A data symbol names a table, not a call target."""
        if self._symbols is None:
            _ = self.symbols
        return self._code

    @property
    def index(self):
        """-> {16 bytes: offset} for every window that occurs EXACTLY once. Ambiguous ones are out."""
        if self._index is None:
            seen, duplicated = {}, set()
            rom = self.rom
            for i in range(len(rom) - WINDOW):
                key = rom[i:i + WINDOW]
                if key in seen:
                    duplicated.add(key)
                else:
                    seen[key] = i
            for key in duplicated:
                del seen[key]
            self._index = seen
        return self._index

    def word(self, address):
        i = address - ROM_START
        return int.from_bytes(self.rom[i:i + 4], "little")

    def symbol(self, name):
        for address, names in self.symbols.items():
            if name in names:
                return address
        return None

    def names_at(self, address):
        """-> every name for what starts at `address`, THUMB bit ignored."""
        return self.symbols.get(address & ~1, ())

    def name_at(self, address):
        """-> one name for what starts at `address`, or None."""
        names = self.names_at(address)
        return names[0] if names else None


ENGLISH = {}


def english(console="firered"):
    if console not in ENGLISH:
        ENGLISH[console] = English(console)
    return ENGLISH[console]


# --------------------------------------------------------------------------- the offset map

def table_points():
    """-> [(french, english, source)] from the tables. Entry i is the same function in both builds."""
    rom = english("firered")
    tables = (("gSpecials", rom_map.SPECIAL_ADDRESSES),
              ("gScriptCmdTable", scrcmd_names.HANDLERS),
              ("gMysteryEventScriptCmdTable", tuple(a for _n, a in rom_map.MYSTERY_EVENT_HANDLERS)))
    out = []
    for name, ours in tables:
        base = rom.symbol(name)
        if base is None:
            continue
        for index, french in enumerate(ours):
            theirs = rom.word(base + 4 * index)
            if not french or not theirs:
                continue
            if not (ROM_START <= (theirs & ~1) < ROM_END):
                continue
            out.append((french & ~1, theirs & ~1, f"{name}[{index}]"))
    return sorted(out)


def dump_points(console="firered", step=4):
    """-> [(french, english, tag)] for every uniquely-placed window of every dump we hold."""
    rom = english(console)
    index = rom.index
    out = []
    for tag, other, base, data in dumps(os.path.join(os.path.dirname(__file__), "..", "..",
                                                     "scratchpad")):
        if other != console or not base or not (ROM_START <= base < ROM_END):
            continue
        for offset in range(0, len(data) - WINDOW, step):
            hit = index.get(data[offset:offset + WINDOW])
            if hit is not None:
                out.append((base + offset, hit + ROM_START, tag))
    return sorted(out)


def offset_runs(points, min_votes=MIN_VOTES):
    """-> [(low, high, offset, points, source)] merging neighbours that agree.

    A run is a claim that everything between its ends is that far from the English build. It holds
    because the offset only moves where an object's size differs, and a run with hundreds of
    agreeing points either side of an address is what says no such object is in between."""
    runs = []
    for french, other, source in points:
        offset = other - french
        if runs and runs[-1][2] == offset:
            runs[-1][1] = french
            runs[-1][3] += 1
        else:
            runs.append([french, french, offset, 1, source])
    return [tuple(r) for r in runs if r[3] >= min_votes]


def merged_runs(console="firered"):
    """-> the offset map: the tables and the dumps together, sorted, agreeing runs merged."""
    points = sorted(table_points() + [(f, e, t) for f, e, t in dump_points(console)]) \
        if console == "firered" else sorted(dump_points(console))
    runs = offset_runs(points, min_votes=2)
    out = []
    for low, high, offset, votes, source in runs:
        if out and out[-1][2] == offset and low <= out[-1][1] + 0x400:
            out[-1][1] = max(out[-1][1], high)
            out[-1][3] += votes
        else:
            out.append([low, high, offset, votes, source])
    return [tuple(r) for r in out]


def offset_at(runs, address):
    """-> (offset, votes) for an address a run covers, else (None, None). Never extrapolates."""
    for low, high, offset, votes, _source in runs:
        if low <= address <= high:
            return offset, votes
    return None, None


def name_of(address, runs=None, console="firered"):
    """-> the English build's name for a French address, or None. A DEDUCTION - see --check."""
    runs = merged_runs(console) if runs is None else runs
    offset, _votes = offset_at(runs, address & ~1)
    if offset is None:
        return None
    return english(console).name_at((address & ~1) + offset)


# --------------------------------------------------------------------------- the delta map

DELTA_STEPS = ((0x0, -0x2C), (-0x2C, -0x28), (-0x28, -0x24), (-0x24, -0x20), (-0x20, -0x1C4))


def english_delta_at(address, delta, length=64):
    """does the English LeafGreen hold, at `address + delta`, what English FireRed holds here?

    Padding matches at every delta, so a window has to SAY something before its match means
    anything: sixteen distinct byte values is what separates real content from a run of zeros and
    from the 0xFF filler between objects."""
    fr, lg = english("firered").rom, english("leafgreen").rom
    i = address - ROM_START
    here = fr[i:i + length]
    if len(set(here)) < 16:
        return None
    return here == lg[i + delta:i + delta + length]


def english_divergence(low, high, before, after, length=64):
    """-> (last address that still maps at `before`, first that maps at `after`).

    The step is INSIDE a version-divergent object, not at its edge, and between the two returned
    addresses the builds hold different code and no delta is defined."""
    last = None
    first = None
    for address in range(low, high):
        if english_delta_at(address, before, length):
            last = address
    for address in range(high, low, -1):
        if english_delta_at(address, after, length):
            first = address
    return last, first


def delta_windows(coarse=0x8000):
    """-> [(before, after, english low, english high)] bracketing every step in the English pair."""
    out = []
    for before, after in DELTA_STEPS:
        recorded = next(b for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES
                        if b[0] == before and b[1] == after)
        low, high = recorded[2] - coarse, recorded[3] + coarse
        step = 0x40
        first_after = None
        for address in range(low, high, step):
            if english_delta_at(address, after) and not english_delta_at(address, before):
                first_after = address
                break
        if first_after is None:
            out.append((before, after, None, None))
            continue
        last_before = None
        for address in range(first_after, low, -step):
            if english_delta_at(address, before) and not english_delta_at(address, after):
                last_before = address
                break
        low = last_before if last_before else low
        last, first = english_divergence(low, first_after + step, before, after)
        out.append((before, after, last, first))
    return out


def predicted_boundaries():
    """-> [(before, after, french low, french high, note)] carrying the English step across.

    HYPOTHESIS, and the one the next run settles: the object that diverges is the same object on the
    French cartridges - the delta values are the same six in the same order, which is what says so -
    and the offset map puts it at a French address. Where the offset is not measured either side of
    the step, the answer is a range as wide as the offsets around it."""
    runs = merged_runs("firered")
    out = []
    for before, after, last, first in delta_windows():
        if last is None:
            out.append((before, after, None, None, "no English step found"))
            continue
        low_offset, low_votes = offset_at(runs, last)
        high_offset, high_votes = offset_at(runs, first)
        offsets = [o for o in (low_offset, high_offset) if o is not None]
        recorded = next(b for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES
                        if b[0] == before and b[1] == after)
        if not offsets:
            nearest = min(runs, key=lambda r: min(abs(r[0] - last), abs(r[1] - last)))
            out.append((before, after, last - nearest[2], first - nearest[2],
                        f"offset NOT measured here; nearest run {nearest[2]:+#x} at "
                        f"0x{nearest[0]:08X}..0x{nearest[1]:08X} - DUMP FIRST"))
            continue
        note = f"offset {low_offset:+#x}" if low_offset == high_offset or high_offset is None \
            else f"offset {low_offset:+#x} below, {high_offset:+#x} above"
        # An address is French = English - offset, and the recorded bracket is a measurement:
        # intersecting the two is tighter than either, and a disagreement is visible as an empty one.
        low = max(last - max(offsets), recorded[2])
        high = min(first - min(offsets), recorded[3])
        out.append((before, after, low, high, note))
    return out


# --------------------------------------------------------------------------- the control

def check():
    """-> (agreed, disagreed, silent, uncovered) against every name the console's bodies proved."""
    runs = merged_runs("firered")
    rom = english("firered")
    agreed, disagreed, silent, uncovered = [], [], [], []
    for address, ours in sorted(worker_names.WORKERS.items()):
        offset, _votes = offset_at(runs, address & ~1)
        if offset is None:
            uncovered.append((address, ours))
            continue
        theirs = rom.names_at((address & ~1) + offset)
        if not theirs:
            silent.append((address, ours))
        elif any(t == ours or t.lstrip("_") == ours.lstrip("_") for t in theirs):
            agreed.append((address, ours))
        else:
            disagreed.append((address, ours, "/".join(theirs)))
    return agreed, disagreed, silent, uncovered


# --------------------------------------------------------------------------- what to dump next

def plan(blocks=32):
    """-> the scattered kilobytes that settle what is predicted rather than measured.

    THE SHAPE, and it is why one address list serves both cartridges: a block fingerprinted into
    ITS OWN English build gives the offset there, and the English pair's delta map joins the two
    English addresses. So a LeafGreen block does NOT have to be aimed at the twin of a FireRed one -
    which is what a bisection needs when the delta it is bisecting is the unknown. Dump the same 32
    addresses on both consoles and every block is a delta point.

    Blocks go where the offset is NOT measured yet: two at each prediction that already has one (the
    control), and a spread across the recorded bracket where it does not."""
    runs = merged_runs("firered")
    out = []
    for before, after, low, high, note in predicted_boundaries():
        recorded = next(b for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES
                        if b[0] == before and b[1] == after)
        step = f"{before:+#x} -> {after:+#x}"
        if low is None:
            continue
        measured = offset_at(runs, low)[0] is not None
        if measured:
            bases = [(low - 512) & ~0x3FF, ((high + 512) & ~0x3FF)]
        else:
            span = recorded[3] - recorded[2]
            count = 4 if span < 0x20000 else 6
            bases = [((recorded[2] + span * i // (count - 1)) & ~0x3FF) for i in range(count)]
            bases.append((low - 512) & ~0x3FF)
        out.append((step, low, high, sorted(set(bases)), measured, note))
    # The last gap has no prediction at all: the English pair cascades through several deltas in a
    # region where every object is language-dependent, so it is a spread and nothing more.
    last = rom_map.LEAFGREEN_DELTA_BOUNDARIES[-1]
    span = last[3] - last[2]
    out.append((f"{last[0]:+#x} -> {last[1]:+#x}", None, None,
                [((last[2] + span * i // 7) & ~0x3FF) for i in range(8)], False,
                "no English prediction: the English pair steps three times in here and every "
                "object in it is language-dependent"))
    return out


# --------------------------------------------------------------------------- CLI

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--offsets", action="store_true", help="the French -> English offset map")
    parser.add_argument("--names", action="store_true", help="name what this project could not")
    parser.add_argument("--boundaries", action="store_true", help="the predicted French boundaries")
    parser.add_argument("--check", action="store_true", help="the control against worker_names")
    parser.add_argument("--plan", action="store_true", help="what to dump to settle a prediction")
    parser.add_argument("--console", choices=("firered", "leafgreen"), default="firered")
    args = parser.parse_args()
    if not any((args.offsets, args.names, args.boundaries, args.check, args.plan)):
        args.check = True

    for console in ("firered", "leafgreen"):
        problem = check_build(console)
        print(f"{console:10s} {problem or 'sha1 matches the decomp'}")
    if any(check_build(c) for c in ("firered", "leafgreen")):
        return 1
    print()

    if args.offsets:
        runs = merged_runs(args.console)
        print(f"=== the offset map, {args.console}: {len(runs)} runs "
              f"(French + offset = English)")
        for low, high, offset, votes, source in runs:
            print(f"  0x{low:08X}..0x{high:08X}  {offset:+#8x}  {votes:6d} points  {source}")

    if args.check:
        agreed, disagreed, silent, uncovered = check()
        print(f"=== the control: {len(agreed)} agree, {len(disagreed)} DISAGREE, "
              f"{len(silent)} no English symbol there, {len(uncovered)} not covered by the map")
        for address, ours, theirs in disagreed:
            print(f"  0x{address:08X}  ours {ours}  English {theirs}")
        if not disagreed:
            print("  every name the console's own bodies proved comes back the same")

    if args.names:
        runs = merged_runs("firered")
        rom = english("firered")
        known = dict(worker_names.WORKERS)
        found = []
        for low, high, offset, _votes, _source in runs:
            for address, names in rom.symbols.items():
                french = address - offset
                if low <= french <= high and french not in known:
                    found.append((french, names[0]))
        found = sorted(set(found))
        print(f"=== {len(found)} French addresses the English build names inside the offset map")
        for french, name in found[:60]:
            print(f"  0x{french:08X}  {name}")
        if len(found) > 60:
            print(f"  ... and {len(found) - 60} more")

    if args.boundaries:
        print("=== the LeafGreen delta map: where the English pair steps, carried to French")
        for before, after, low, high, note in predicted_boundaries():
            recorded = next(b for b in rom_map.LEAFGREEN_DELTA_BOUNDARIES
                            if b[0] == before and b[1] == after)
            inside = low is not None and recorded[2] <= low and high <= recorded[3] + 0x400
            print(f"  {before:+#8x} -> {after:+#8x}")
            if low is None:
                print(f"      {note}")
                continue
            print(f"      PREDICTED French 0x{low:08X}..0x{high:08X}  ({high - low} bytes)  {note}")
            print(f"      recorded          0x{recorded[2]:08X}..0x{recorded[3]:08X}  "
                  f"({(recorded[3] - recorded[2]) / 1024:.1f} KB)"
                  f"   {'consistent' if inside else 'OUTSIDE the recorded bracket - one is wrong'}")

    if args.plan:
        print("=== what to dump to turn a prediction into a measurement")
        addresses = []
        for step, low, high, bases, measured, note in plan():
            where = f"French 0x{low:08X}..0x{high:08X}" if low else "no prediction"
            print(f"  {step:18s} {where:34s} "
                  f"{'offset measured, these are the control' if measured else note[:60]}")
            print("      " + " ".join(f"0x{b:08X}" for b in bases))
            addresses.extend(bases)
        addresses = sorted(set(addresses))[:32]
        print(f"\n  {len(addresses)} blocks. THE SAME LIST ON BOTH CARTRIDGES - a block is placed by")
        print("  its own English build, so a LeafGreen block need not be aimed at a FireRed twin.\n")
        print("    --buffer-script memory-dump-scatter --dump-scatter " +
              ",".join(f"0x{a:08X}" for a in addresses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
