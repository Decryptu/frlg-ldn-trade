#!/usr/bin/env python3
"""Read the BODIES of a ROM function table off the console's own dumps, and say what to dump next.

    ./.venv/bin/python tools/rom_functions.py --table specials --with-every-dump
    ./.venv/bin/python tools/rom_functions.py --table field --dump scratchpad/bs84_dump.bin@0x0806F800
    ./.venv/bin/python tools/rom_functions.py --table specials --plan --window 1024

bs84's method, generalised to every table this project has read off a cartridge. A table entry is an
address; the code at it makes `bl` calls, in the decomp's own call order, and keeps the globals it
touches in its literal pool. So ONE 1 KB window turns a dozen table entries into a dozen named
bodies plus every worker behind them, which is what makes another window cost nothing to interpret.

The last section is the useful one, and it is the same idea as `tools/script_read.py`'s: the entries
this project does NOT hold are clustered into `--dump-address` windows and ranked by how many of
them one run would catch, so a run is spent where the table is densest rather than on a guess.

WHAT NAMES A BODY IS ITS CALLS, NOT ITS POSITION. `gSpecials` is 444 entries and its names come from
the decomp's table order; a body whose `bl` targets land on functions this project measured
elsewhere is that mapping confirmed against the cartridge, and a body that lands on nothing known is
the run's new surface. docs/buffer_script.md.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map, scrcmd, scrcmd_names, special_names, thumb, worker_names
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


def known_names(with_workers=True):
    """-> {address: what this project calls it}, from every measured symbol and table.

    `with_workers` is False for the generator that WRITES `worker_names`: a name it produced last
    time is not evidence for producing it again, and a table this project can only regenerate from
    its own output cannot be checked."""
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


def plan(missing, window, limit):
    """-> ready-made `--dump-address` lines, densest window first.

    Greedy over the addresses not held: the window starting at each one, whichever catches the most,
    then the same again over what is left. A window is anchored ON an entry rather than on a round
    number because a body starts where the table says it does."""
    left, lines = sorted(missing), []
    while left and len(lines) < limit:
        best_start, best = left[0], []
        for start in left:
            inside = [a for a in left if start <= a < start + window]
            if len(inside) > len(best):
                best_start, best = start, inside
        names = ", ".join(missing[a].split(" [")[0] for a in best[:6])
        lines.append(f"  --dump-address 0x{best_start:08X} --dump-size {window}   "
                     f"{len(best)} entr{'y' if len(best) == 1 else 'ies'}: {names}"
                     + (", ..." if len(best) > 6 else ""))
        left = [a for a in left if a not in set(best)]
    return lines, len(left)


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


if __name__ == "__main__":
    main()
