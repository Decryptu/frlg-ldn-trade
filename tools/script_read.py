#!/usr/bin/env python3
"""Read a ROM dump as field scripts: disassemble, follow every goto and call, and say what to dump
next.

    ./.venv/bin/python tools/script_read.py DUMP.bin --base 0x081A7600 [--start ADDR ...]
    ./.venv/bin/python tools/script_read.py DUMP.bin --base 0x081640EC --std-scripts
    ./.venv/bin/python tools/script_read.py DUMP.bin --base ADDR --with-every-dump

`--base` is the `--dump-address` the run used; without `--start` the whole dump is walked as
back-to-back scripts, which is what a region of `data/scripts/*.inc` actually is.

`--with-every-dump` adds every other ROM dump in `scratchpad/`, paired with the `--dump-address`
its launcher log records. 127 runs are on disk and a script does not care which one caught the
block it jumps to; without this the plan proposes runs for bytes we already have. `--dump
PATH@0xADDR` adds one by hand.

The operands are named, not just printed: a var, a flag, a special and a comparison all come back
with the decomp's own name beside the number [frlgsim/symbol_names.py, special_names.py]. An
operand of 0x4000 or more is a variable REFERENCE whatever it sits in, because every ScrCmd body
passes its arguments through VarGet [decomp:src/event_data.c:235].

The last section is the useful one. Following the jumps finds every address these scripts reach for,
and the ones this dump does not hold are printed as ready-made `--dump-address` lines, biggest catch
first. A dump aimed there is asked for by the console's own scripts rather than guessed at, and
several unknowns usually share one 1 KB window. docs/buffer_script.md.
"""
import argparse
import os
import pathlib
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map, scrcmd


def every_dump(directory):
    """-> [(base, data)] for every ROM dump in `directory`, from what its launcher log recorded.

    The log line is the run's own argv, so the pairing is the run's, not a guess. A dump with no
    `--dump-address` was a save-block or a scan and has no ROM address to place it at."""
    directory = pathlib.Path(directory)
    found = []
    for log in sorted((directory / "launcher_logs").glob("*_launcher.log")):
        tag = log.name[: -len("_launcher.log")]
        dump = directory / f"{tag}_dump.bin"
        if not dump.exists():
            continue
        match = re.search(r"--dump-address\s+(0x[0-9A-Fa-f]+)", log.read_text())
        if match:
            found.append((int(match.group(1), 0), dump.read_bytes()))
    return found


def entry_points(data, base, args):
    if args.std_scripts:
        # gStdScripts is ten pointers [decomp:data/event_scripts.s]; a dump of it starts with them.
        return list(struct.unpack_from("<10I", data, rom_map.G_STD_SCRIPTS - base))
    if args.start:
        return args.start
    # No entry points given: walk the dump as one script after another, which is how the decomp
    # lays a script file out. Each run stops on a terminator and the next begins on the next byte.
    starts, cursor = [], 0
    while cursor < len(data):
        measured = scrcmd.shape(data, base, cursor)
        if measured is None:
            cursor += 1
            continue
        starts.append(base + cursor)
        while cursor < len(data):
            measured = scrcmd.shape(data, base, cursor)
            if measured is None:
                cursor += 1
                break
            opcode = data[cursor]
            cursor += measured[2]
            if opcode in scrcmd.TERMINATORS:
                break
    return starts


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--base", type=lambda v: int(v, 0), required=True,
                    help="the --dump-address the run used")
    ap.add_argument("--start", type=lambda v: int(v, 0), action="append",
                    help="an entry point to follow; repeatable. Default: walk the whole dump")
    ap.add_argument("--std-scripts", action="store_true",
                    help="the dump IS gStdScripts: follow its ten pointers")
    ap.add_argument("--window", type=lambda v: int(v, 0), default=1024,
                    help="the dump size the plan should propose (default 1024)")
    ap.add_argument("--quiet", action="store_true", help="the plan only, no disassembly")
    ap.add_argument("--with-every-dump", action="store_true",
                    help="add every other ROM dump in scratchpad/, placed by its launcher log")
    ap.add_argument("--dump", action="append", default=[], metavar="PATH@0xADDR",
                    help="add another dump at an address; repeatable")
    ap.add_argument("--scratchpad", default="scratchpad",
                    help="where the dumps and launcher logs live (default scratchpad)")
    args = ap.parse_args()

    data = open(args.path, "rb").read()
    segments = [(args.base, data)]
    if args.with_every_dump:
        segments += every_dump(args.scratchpad)
    for spec in args.dump:
        path, _, address = spec.rpartition("@")
        segments.append((int(address, 0), open(path, "rb").read()))
    memory = scrcmd.Memory(segments)

    starts = entry_points(data, args.base, args)
    reached, referenced = scrcmd.follow(memory, starts)

    if not args.quiet:
        for address in sorted(reached):
            print(f"0x{address:08X}:")
            for line in reached[address]:
                print(line)
            print()

    print(f"{len(memory)} bytes in {len(memory.segments)} region"
          f"{'s' if len(memory.segments) != 1 else ''}: {len(starts)} entry points, "
          f"{len(reached)} blocks read, {len(referenced)} addresses wanted and not held")
    if referenced:
        print("\nreached for, and not in this dump:")
        for address in sorted(referenced):
            why = ", ".join(f"{kind} at 0x{source:08X}"
                            for kind, source in sorted(referenced[address]))
            print(f"  0x{address:08X}  {why}")
        print("\nwhat to dump next:")
        for line in scrcmd.dump_plan(referenced, args.window):
            print(line)


if __name__ == "__main__":
    main()
