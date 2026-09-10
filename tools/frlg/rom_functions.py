#!/usr/bin/env python3
"""Read the BODIES of a ROM function table off the console's own dumps, and say what to dump next.

    ./.venv/bin/python tools/frlg/rom_functions.py --table specials --with-every-dump
    ./.venv/bin/python tools/frlg/rom_functions.py --table field --dump scratchpad/bs84_dump.bin@0x0806F800
    ./.venv/bin/python tools/frlg/rom_functions.py --table specials --plan --window 1024

The worker-naming method, generalised to every table read off a cartridge. A table entry is an
address; the code at it makes `bl` calls, in the decomp's own call order, and keeps the globals it
touches in its literal pool. So ONE 1 KB window turns a dozen table entries into a dozen named
bodies plus every worker behind them, which is what makes another window cost nothing to interpret.

The last section is the useful one, and it is the same idea as `tools/frlg/script_read.py`'s: the entries
this project does NOT hold are clustered into `--dump-address` windows and ranked by how many of
them one run would catch, so a run is spent where the table is densest rather than on a guess.

WHAT NAMES A BODY IS ITS CALLS, NOT ITS POSITION. `gSpecials` is 444 entries and its names come from
the decomp's table order; a body whose `bl` targets land on functions this project measured
elsewhere is that mapping confirmed against the cartridge, and a body that lands on nothing known is
the run's new surface. docs/frlg_rom.md.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.rom import (english_names, leafgreen_twins, rom_map, scrcmd, scrcmd_names,
                              special_names, thumb, worker_names)
from script_read import every_dump

ROM_START, ROM_END = 0x08000000, 0x0A000000


def tables():
    """-> {name: [(label, address)]} for every function table read off a console.

    Addresses are stripped of the THUMB bit: a table stores the pointer a `bx` needs, and code is at
    the even address."""
    specials = []
    for index, address in enumerate(rom_map.SPECIAL_ADDRESSES):
        specials.append((f"{special_names.SPECIALS[index]} [{index}]", address & ~1))
    return {
        "specials": specials,
        "field": [(f"ScrCmd_{name} [{opcode}]", address & ~1)
                  for opcode, (name, address)
                  in enumerate(zip(scrcmd_names.COMMANDS, scrcmd_names.HANDLERS))],
        # The Mystery Event table is kept by OPCODE name; the decomp's function for one is
        # `MEScrCmd_<opcode>` [decomp:src/mystery_event_script.c:97], which is the name a reader
        # can look up and the name `gen_worker_names.py` needs to find the body's source.
        "mystery-event": [(f"MEScrCmd_{name}", address & ~1)
                          for name, address in rom_map.MYSTERY_EVENT_HANDLERS],
        "callable": [(name, address & ~1) for name, address in sorted(rom_map.CALLABLE.items())],
    }


def known_names(with_workers=True, with_english=True):
    """-> {address: what this project calls it}, from every measured symbol and table.

    `with_workers` is False for the generator that WRITES `worker_names`: a name it produced last
    time is not evidence for producing it again, and a table this project can only regenerate from
    its own output cannot be checked. `with_english` is False for the same reason and for one more:
    a name out of the English build is a DEDUCTION, and it goes in LAST so that it can only fill a
    hole, never overrule a body this console's own calls named. It is marked in the listing.
    docs/frlg_leafgreen.md."""
    out = {}
    for name, value in vars(rom_map).items():
        if name.isupper() and isinstance(value, int) and ROM_START <= value < ROM_END:
            out.setdefault(value & ~1, name)
    for name, address in rom_map.CALLABLE.items():
        out[address & ~1] = name
    if with_workers:
        for address, name in worker_names.WORKERS.items():
            out.setdefault(address & ~1, name)
    for group, entries in tables().items():
        if group == "callable":
            continue
        for label, address in entries:
            out.setdefault(address, label)
    if with_english:
        for address, name in english_names.NAMES.items():
            out.setdefault(address & ~1, f"{name} [english]")
        # Weaker still, and marked as such: the offset was measured either side of the address and
        # not at it. english_names.BRACKETED says what stands in for that.
        for address, (name, _offset) in english_names.BRACKETED.items():
            out.setdefault(address & ~1, f"{name} [english?]")
    return out


def deduplicate(entries):
    """-> [(label, address)] with one line per DISTINCT address.

    `gSpecials` calls NullFieldSpecial from 171 indices and several real functions from more than
    one, so the table has 444 entries and 272 bodies. Reading one body 171 times is not evidence."""
    by_address = {}
    for label, address in entries:
        by_address.setdefault(address, []).append(label)
    out = []
    for address, labels in sorted(by_address.items()):
        label = labels[0] if len(labels) == 1 else f"{labels[0].split(' [')[0]} x{len(labels)}"
        out.append((label, address))
    return out


def windows(missing, window, limit):
    """-> [(start, [addresses caught])], densest first, disjoint.

    Greedy over the addresses not held: the window starting at each one, whichever catches the most,
    then the same again over what is left. A window is anchored ON an entry rather than on a round
    number because a body starts where the table says it does."""
    left, out = sorted(missing), []
    while left and len(out) < limit:
        best_start, best = left[0], []
        for start in left:
            inside = [a for a in left if start <= a < start + window]
            if len(inside) > len(best):
                best_start, best = start, inside
        out.append((best_start, best))
        left = [a for a in left if a not in set(best)]
    return out


def on_leafgreen(entries, names):
    """-> (entries, names) moved to where the OTHER cartridge keeps them.

    Every table this project holds was read off FireRed, so a LeafGreen dump read against those
    addresses is only coherent in the delta-0 region and quietly wrong above it. `leafgreen_twins`
    is where each address was MEASURED - the same instruction resolved on both cartridges - and
    `leafgreen()` falls back to the segment delta, which is measured too. An entry inside a boundary
    has neither and is DROPPED rather than read at a guess."""
    moved_entries, moved_names = [], {}
    for label, address in entries:
        try:
            moved_entries.append((label, leafgreen_twins.leafgreen(address) & ~1))
        except ValueError:
            continue
    for address, name in names.items():
        try:
            moved_names[leafgreen_twins.leafgreen(address) & ~1] = name
        except ValueError:
            continue
    return moved_entries, moved_names


def plan(missing, window, limit):
    """-> ready-made `--dump-address` lines, densest window first."""
    chosen = windows(missing, window, limit)
    lines = []
    for start, caught in chosen:
        names = ", ".join(missing[a].split(" [")[0] for a in caught[:6])
        lines.append(f"  --dump-address 0x{start:08X} --dump-size {window}   "
                     f"{len(caught)} entr{'y' if len(caught) == 1 else 'ies'}: {names}"
                     + (", ..." if len(caught) > 6 else ""))
    taken = {a for _start, caught in chosen for a in caught}
    return lines, len(missing) - len(taken)


def scatter_line(missing, window, blocks):
    """-> the one-join line for `memory-dump-scatter`: the N densest windows, in one session.

    THE POINT OF THE PAYLOAD. `memory-dump-multi` reads N CONSECUTIVE blocks, and a table's unread
    entries are not consecutive - the densest 16 KB of gSpecials holds 22 bodies where the sixteen
    densest KILOBYTES hold about sixty. Same join, same 16 KB off the wire."""
    chosen = windows(missing, window, blocks)
    if not chosen:
        return []
    addresses = ",".join(f"0x{start:08X}" for start, _caught in chosen)
    caught = sum(len(entries) for _start, entries in chosen)
    return [f"  --buffer-script memory-dump-scatter --dump-scatter {addresses}",
            f"    one join, {len(chosen)} block(s) of {window}: {caught} bodies"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--table", choices=sorted(tables()) + ["all"], default="specials")
    ap.add_argument("--with-every-dump", action="store_true", default=True,
                    help="use that cartridge's ROM dumps in scratchpad/, placed by its launcher "
                         "log (default)")
    ap.add_argument("--no-every-dump", dest="with_every_dump", action="store_false")
    ap.add_argument("--dump", action="append", default=[], metavar="PATH@0xADDR",
                    help="add a dump at an address; repeatable")
    ap.add_argument("--window", type=lambda v: int(v, 0), default=1024,
                    help="the dump size the plan should propose (default 1024)")
    ap.add_argument("--plan", action="store_true", help="the plan only, no bodies")
    ap.add_argument("--runs", type=int, default=10, help="how many windows to plan (default 10)")
    ap.add_argument("--blocks", type=int, default=16,
                    help="how many blocks one scattered join may carry (default 16, ceiling 32); "
                         "the plan ends with that join as a ready-made --dump-scatter line")
    ap.add_argument("--scratchpad", default="scratchpad")
    ap.add_argument("--console", choices=("firered", "leafgreen"), default="firered",
                    help="which cartridge's dumps to read (default firered). The two hold the same "
                         "code a segment delta apart, so an image of both answers with whichever "
                         "it placed at the address")
    args = ap.parse_args()

    segments = every_dump(args.scratchpad, args.console) if args.with_every_dump else []
    for spec in args.dump:
        path, _, address = spec.rpartition("@")
        segments.append((int(address, 0), open(path, "rb").read()))
    if not segments:
        raise SystemExit("no dumps: pass --dump PATH@0xADDR or run from the repo root")
    memory = scrcmd.Memory(segments)
    names = known_names()

    groups = sorted(tables()) if args.table == "all" else [args.table]
    for group in groups:
        entries = deduplicate(tables()[group])
        if args.console == "leafgreen":
            entries, names = on_leafgreen(entries, names)
        held = [(label, address) for label, address in entries if address in memory]
        missing = {address: label for label, address in entries if address not in memory}
        print(f"\n=== {group}: {len(entries)} distinct bodies, {len(held)} held in "
              f"{len(memory)} bytes across {len(memory.segments)} region(s)")

        # A body stops at the next entry in the table as well as on its own epilogue. Without the
        # first bound `function_end` runs past a function that returns from more than one place and
        # swallows its neighbour: ShowFieldMessageStringVar4 came back holding all of GetPlayerXY.
        new_workers = {}
        starts = sorted(address for _label, address in held)
        for label, address in sorted(held, key=lambda entry: entry[1]):
            base, data = memory.segment(address)
            after = [start for start in starts if start > address] + [base + len(data)]
            limit = min(after[0], base + len(data))
            end = thumb.function_end(data, base, address, limit)
            if not args.plan:
                print(f"\n  {label}  0x{address:08X}..0x{end:08X}")
            for _site, target in thumb.bl_targets(data, base, address, end):
                known = names.get(target & ~1)
                if not args.plan:
                    print(f"      bl  0x{target:08X}" + (f"   = {known}" if known else ""))
                if not known and ROM_START <= target < ROM_END:
                    new_workers.setdefault(target & ~1, []).append(label)
            for _site, pool, value in thumb.pc_literals(data, base, address, end):
                if value is None or args.plan:
                    continue
                known = names.get(value & ~1)
                print(f"      ldr 0x{pool:08X} = 0x{value:08X}"
                      + (f"   = {known}" if known and value >= ROM_START else ""))

        if new_workers:
            print(f"\n  {len(new_workers)} call target(s) this project has no name for:")
            for target, callers in sorted(new_workers.items()):
                print(f"    0x{target:08X}   called by {', '.join(sorted(set(callers))[:4])}")

        if missing:
            lines, left = plan(missing, args.window, args.runs)
            print(f"\n  {len(missing)} bodies not held. What to dump next, densest first:")
            for line in lines:
                print(line)
            if left:
                print(f"  ... and {left} bodies in windows of fewer than that")
            if args.blocks > 1:
                print(f"\n  The same windows as ONE scattered join:")
                for line in scatter_line(missing, args.window, args.blocks):
                    print(line)


if __name__ == "__main__":
    main()
