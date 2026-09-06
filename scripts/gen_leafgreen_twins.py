#!/usr/bin/env python3
"""Regenerate frlgsim/leafgreen_twins.py: LeafGreen's address for what FireRed holds, MEASURED.

    ./.venv/bin/python scripts/gen_leafgreen_twins.py [--scratchpad scratchpad]

`rom_map.leafgreen_guess` applies a segment's delta and refuses inside a boundary, which is the
right answer when nothing better exists. Something better exists for every pointer that appears in a
window both cartridges have been dumped at: `tools/cartridge_pair.py` reads the same instruction off
both consoles and the two targets it resolves to are FireRed's address and LeafGreen's, each read
off its own cartridge. No delta is applied and no segment has to be trusted.

Two 16 KB pairs and one 1 KB pair are on disk (bs120/lg191, bs121/lg192, bs117/lg190) and they hold
1863 such points. The generator keeps the ones that are consistent: an address that pairs to two
different LeafGreen addresses across the runs is dropped rather than picked between.
"""
import argparse
import collections
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))

from cartridge_pair import candidate_pairs, paired_calls, paired_literals   # noqa: E402
from script_read import dumps                                              # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "frlgsim" / "leafgreen_twins.py"

HEADER = '''"""LeafGreen's address for a FireRed one, read off LeafGreen. Generated; do not edit by hand.

`scripts/gen_leafgreen_twins.py`, from the windows both cartridges have been dumped at. A `bl` is a
relative call, so the same instruction resolves to a different address on each cartridge and the
pair is two measurements rather than one plus a delta; a literal-pool word is the same trick for
data. Nothing here is interpolated - an address absent from this table has not been measured, and
`leafgreen()` falls back to `rom_map.leafgreen_guess`, which applies the segment delta and REFUSES
inside a boundary.

THE DELTA IS A PROPERTY OF A REGION. These pairs are also what the segment map is built from: 1863
points across three run pairs, quantised into seven deltas with no outlier, which is what says the
windows are really each other's twin. docs/leafgreen.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map


def leafgreen(address):
    """-> LeafGreen's address for `address`: the measured twin if there is one, else the guess."""
    address = int(address)
    for candidate in (address, address & ~1):
        if candidate in TWINS:
            return TWINS[candidate] | (address & 1)
    return rom_map.leafgreen_guess(address)


def delta(address):
    """-> how far LeafGreen's copy sits from FireRed's, at a measured address."""
    return leafgreen(address) - int(address)

'''


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scratchpad", default=str(ROOT / "scratchpad"))
    args = ap.parse_args()

    everything = dumps(args.scratchpad)
    by_tag = {tag: (tag, console, base, data) for tag, console, base, data in everything}
    pairs = candidate_pairs(everything)
    if not pairs:
        raise SystemExit("no window is held on both cartridges")

    seen = collections.defaultdict(set)
    provenance = {}
    for fr_tag, lg_tag, _code_delta, _alike in pairs:
        fr, lg = by_tag[fr_tag], by_tag[lg_tag]
        for ours, theirs in paired_calls(fr, lg) + paired_literals(fr, lg):
            seen[ours].add(theirs)
            provenance.setdefault(ours, f"{fr_tag}/{lg_tag}")

    twins = {ours: next(iter(theirs)) for ours, theirs in seen.items() if len(theirs) == 1}
    dropped = [ours for ours, theirs in seen.items() if len(theirs) > 1]

    lines = [HEADER, "TWINS = {"]
    for ours in sorted(twins):
        lines.append(f"    0x{ours:08X}: 0x{twins[ours]:08X},".ljust(40)
                     + f"# {twins[ours] - ours:#x}, {provenance[ours]}")
    lines.append("}")
    lines.append("")
    lines.append("TWIN_COUNT = len(TWINS)")
    lines.append("")
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(ROOT)}: {len(twins)} twins from {len(pairs)} run pair(s)"
          + (f", {len(dropped)} address(es) dropped for disagreeing" if dropped else ""))
    for ours in dropped:
        print(f"  0x{ours:08X}: " + ", ".join(f"0x{value:08X}" for value in sorted(seen[ours])))


if __name__ == "__main__":
    main()
