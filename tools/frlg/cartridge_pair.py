#!/usr/bin/env python3
"""Pair the two cartridges' copies of the same code and read the delta off every pointer in it.

    ./.venv/bin/python tools/frlg/cartridge_pair.py
    ./.venv/bin/python tools/frlg/cartridge_pair.py --names        # the LeafGreen twin of what we name
    ./.venv/bin/python tools/frlg/cartridge_pair.py --pair bs121 lg192

THE MEASUREMENT lg169 made without naming it: a POINTER dumped off both consoles is a delta point at
wherever it points, and one window holds hundreds of them. Sessions 40 and 41 read the literal pools
that way - 27 paired words moved both ends of the -0x1C4 segment, 13 more found the -0x20 segment
nobody had seen. What this adds is the OTHER pointer in every window, and there are more of them:
a `bl` is a relative call, so the same instruction on the two cartridges resolves to two addresses
whose difference is the delta AT THE TARGET. 16 KB of handlers is 834 of those.

WHY IT COSTS NOTHING. The dumps are already on disk. bs120/lg191 and bs121/lg192 were each spent to
pair one pool; they hold 1592 paired call sites between them, and every one is a delta point at a
place no needle was ever aimed at.

WHAT MAKES IT TRUSTWORTHY. Every site pairs or the window is not the twin: 734 of 734 and 834 of 834
here, and the deltas come out QUANTISED - four values across 16 KB, no outliers, no "nearly". A
misplaced window does not do that; the first run of this tool had the LeafGreen offsets computed off
the FireRed base and answered with 64 different deltas, none of them repeated.

PAIR BY CODE OFFSET. The LeafGreen dump is aimed at the twin of the FireRed window, so offset N in
one is offset N in the other whatever the bases are. Pairing by INDEX - the n-th pool word against
the n-th - drifts the moment one side holds a word the other does not, and invents deltas.
docs/frlg_leafgreen.md.
"""
import argparse
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.rom import rom_map, thumb, worker_names
from rom_functions import known_names
from script_read import dumps

ROM_START, ROM_END = 0x08000000, 0x0A000000
IDENTITY = 0.80          # how alike two windows must be before they are called the same code


def candidate_pairs(everything, minimum=IDENTITY):
    """-> [(firered tag, leafgreen tag, code delta, how alike)] for windows that hold the same code.

    A LeafGreen run is aimed at the twin of a FireRed window, so its base minus that window's base
    IS the code delta and the two dumps should be nearly byte for byte. Nearly, not exactly: the
    literal pools and the `bl` immediates are what differ, which is the whole point."""
    firered = [entry for entry in everything if entry[1] == "firered"]
    leafgreen = [entry for entry in everything if entry[1] == "leafgreen"]
    out = []
    for fr_tag, _c, fr_base, fr_data in firered:
        for lg_tag, _c2, lg_base, lg_data in leafgreen:
            size = min(len(fr_data), len(lg_data))
            if not size:
                continue
            alike = sum(fr_data[i] == lg_data[i] for i in range(size)) / size
            if alike >= minimum:
                out.append((fr_tag, lg_tag, lg_base - fr_base, alike))
    return sorted(out)


def paired_calls(fr, lg):
    """-> [(FireRed target, LeafGreen target)] for the `bl` at the same offset in both windows."""
    _tag, _c, fr_base, fr_data = fr
    _tag2, _c2, lg_base, lg_data = lg
    size = min(len(fr_data), len(lg_data))
    theirs = {site - lg_base: target
              for site, target in thumb.bl_targets(lg_data, lg_base, lg_base, lg_base + size)}
    out = []
    for site, target in thumb.bl_targets(fr_data, fr_base, fr_base, fr_base + size):
        other = theirs.get(site - fr_base)
        if other is not None:
            out.append((target, other))
    return out


def paired_literals(fr, lg):
    """-> [(FireRed pointer, LeafGreen pointer)] for the pool word each `ldr [pc]` reaches.

    One pool word is read by several instructions, so the pool ADDRESS is what makes a point
    distinct - counting an entry once per `ldr` would report the same measurement three times."""
    _tag, _c, fr_base, fr_data = fr
    _tag2, _c2, lg_base, lg_data = lg
    size = min(len(fr_data), len(lg_data))
    theirs = {site - lg_base: value for site, _pool, value
              in thumb.pc_literals(lg_data, lg_base, lg_base, lg_base + size)}
    out, seen = [], set()
    for site, pool, value in thumb.pc_literals(fr_data, fr_base, fr_base, fr_base + size):
        other = theirs.get(site - fr_base)
        if value is None or other is None or pool in seen:
            continue
        if ROM_START <= value < ROM_END and ROM_START <= other < ROM_END:
            seen.add(pool)
            out.append((value, other))
    return out


def segments(points):
    """-> {delta: (lowest, highest)} over [(FireRed address, LeafGreen address)] pairs."""
    spans = {}
    for ours, theirs in points:
        delta = theirs - ours
        low, high = spans.get(delta, (ours, ours))
        spans[delta] = (min(low, ours), max(high, ours))
    return spans


def boundaries(spans):
    """-> [(from delta, to delta, low, high)]: what is left unmeasured between the segments.

    Ordered by where they sit in the ROM, not by delta: the deltas are NOT monotonic - the low
    segments step -0x2C, -0x28, -0x24, -0x20 - so reading a less divergent segment as a mistake is
    how a boundary gets put in the wrong place."""
    ordered = sorted(spans.items(), key=lambda item: item[1][0])
    out = []
    for (delta, (_low, high)), (next_delta, (next_low, _high)) in zip(ordered, ordered[1:]):
        out.append((delta, next_delta, high, next_low))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratchpad", default="scratchpad")
    ap.add_argument("--pair", nargs=2, metavar=("FIRERED", "LEAFGREEN"), action="append",
                    help="pair these two run tags rather than searching; repeatable")
    ap.add_argument("--names", action="store_true",
                    help="the LeafGreen address of every target this project has a name for")
    ap.add_argument("--identity", type=float, default=IDENTITY)
    args = ap.parse_args()

    everything = dumps(args.scratchpad)
    by_tag = {tag: (tag, console, base, data) for tag, console, base, data in everything}
    if args.pair:
        pairs = []
        for fr_tag, lg_tag in args.pair:
            fr, lg = by_tag[fr_tag], by_tag[lg_tag]
            size = min(len(fr[3]), len(lg[3]))
            alike = sum(fr[3][i] == lg[3][i] for i in range(size)) / size
            pairs.append((fr_tag, lg_tag, lg[2] - fr[2], alike))
    else:
        pairs = candidate_pairs(everything, args.identity)
    if not pairs:
        raise SystemExit("no window is held on both cartridges")

    everything_points, named = [], {}
    for fr_tag, lg_tag, code_delta, alike in pairs:
        fr, lg = by_tag[fr_tag], by_tag[lg_tag]
        calls, literals = paired_calls(fr, lg), paired_literals(fr, lg)
        print(f"\n=== {fr_tag} 0x{fr[2]:08X} + {len(fr[3])} bytes  vs  {lg_tag} 0x{lg[2]:08X}"
              f"   code delta {code_delta:#x}, {alike:.1%} of the bytes identical")
        for what, points in (("bl target", calls), ("pool pointer", literals)):
            spans = segments(points)
            print(f"  {len(points)} paired {what}s, {len(spans)} distinct delta(s):")
            for delta, (low, high) in sorted(spans.items(), key=lambda item: item[1][0]):
                count = sum(1 for ours, theirs in points if theirs - ours == delta)
                print(f"    {delta:#8x}  {count:4d} point(s)  0x{low:08X}..0x{high:08X}")
            everything_points += points
        for ours, theirs in calls:
            named[ours & ~1] = theirs & ~1

    spans = segments(everything_points)
    print(f"\n=== every pair together: {len(everything_points)} points, {len(spans)} deltas")
    for delta, (low, high) in sorted(spans.items(), key=lambda item: item[1][0]):
        print(f"  {delta:#8x}  0x{low:08X}..0x{high:08X}")

    print("\n=== what that leaves unmeasured, against rom_map.LEAFGREEN_DELTA_BOUNDARIES")
    recorded = {(entry[0], entry[1]): entry for entry in rom_map.LEAFGREEN_DELTA_BOUNDARIES}
    for from_delta, to_delta, low, high in boundaries(spans):
        was = recorded.get((from_delta, to_delta))
        line = f"  {from_delta:#7x} -> {to_delta:#7x}   0x{low:08X}..0x{high:08X}" \
               f"  ({(high - low) / 1024:.1f} KB)"
        if was:
            best_low, best_high = max(low, was[2]), min(high, was[3])
            width, before = best_high - best_low, was[3] - was[2]
            line += (f"   recorded 0x{was[2]:08X}..0x{was[3]:08X} ({before / 1024:.1f} KB)"
                     + (f"   -> NARROWS to {width / 1024:.1f} KB" if width < before else ""))
        else:
            line += "   NOT in rom_map"
        print(line)

    if args.names:
        names = known_names()
        names.update({address: name for address, name in worker_names.WORKERS.items()})
        print(f"\n=== the LeafGreen address of what we name, read off ITS OWN code ({len(named)} "
              "targets paired)")
        for ours in sorted(named):
            name = names.get(ours)
            if name:
                print(f"  {name.split(' [')[0]:52s} 0x{ours:08X} -> 0x{named[ours]:08X}"
                      f"  {named[ours] - ours:#x}")


if __name__ == "__main__":
    main()
