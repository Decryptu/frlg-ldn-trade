#!/usr/bin/env python3
"""Read a ROM dump as field scripts: disassemble, follow every goto and call, and say what to dump
next.

    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base 0x081A7600 [--start ADDR ...]
    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base 0x081640EC --std-scripts
    ./.venv/bin/python tools/frlg/script_read.py DUMP.bin --base ADDR --with-every-dump

`--base` is the `--dump-address` the run used; without `--start` the whole dump is walked as
back-to-back scripts, which is what a region of `data/scripts/*.inc` actually is.

`--with-every-dump` adds every other ROM dump in `scratchpad/`, paired with the `--dump-address`
its launcher log records. 127 runs are on disk and a script does not care which one caught the
block it jumps to; without this the plan proposes runs for bytes we already have. `--dump
PATH@0xADDR` adds one by hand. It adds ONE cartridge's dumps - `--console`, FireRed by default -
because the two cartridges keep the same code at addresses a segment delta apart and an image
holding both answers with whichever it happened to place there.

The operands are named, not just printed: a var, a flag, a special and a comparison all come back
with the decomp's own name beside the number [pokeldn/frlg/rom/symbol_names.py, special_names.py]. An
operand of 0x4000 or more is a variable REFERENCE whatever it sits in, because every ScrCmd body
passes its arguments through VarGet [decomp:src/event_data.c:235].

The last section is the useful one. Following the jumps finds every address these scripts reach for,
and the ones this dump does not hold are printed as ready-made `--dump-address` lines, biggest catch
first. A dump aimed there is asked for by the console's own scripts rather than guessed at, and
several unknowns usually share one 1 KB window. docs/frlg_rom_buffer_script.md.
"""
import argparse
import gzip
import os
import pathlib
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pokeldn.frlg.rom import rom_map, scrcmd


def dump_console(tag, log_text):
    """-> which cartridge a run was against: its own `--expect-console`, else the tag.

    The flag is the run's own record and is checked against the game data before anything is sent,
    so it is the authority. The tag is the fallback for the runs that predate it, and it is the same
    rule `run_mg_fast.sh` uses to pass the flag: `lgNN` is LeafGreen, anything else is FireRed."""
    match = re.search(r"--expect-console\s+(\w+)", log_text)
    if match:
        return match.group(1).lower()
    return "leafgreen" if re.match(r"^lg\d", tag) else "firered"


def dumps(directory):
    """-> [(tag, console, base, data)] for every ROM dump in `directory`, from its launcher log.

    The log line is the run's own argv, so the pairing is the run's, not a guess. A dump with no
    `--dump-address` was a save-block or a scan and has no ROM address to place it at.

    A `--dump-scatter` run comes back as ONE segment PER BLOCK, tagged `run[n]`: the file holds the
    blocks end to end in the order the payload's table names them, and they are unrelated regions,
    so a single base would put fifteen of the sixteen kilobytes in the wrong place."""
    directory = pathlib.Path(directory)
    found = []
    # BOTH NAMES, BECAUSE THE ARCHIVE IS GZIPPED. `scratchpad/launcher_logs` holds 652 logs and
    # every one of them is `*_launcher.log.gz`; a glob for the uncompressed name matched none, so
    # `every_dump` returned nothing and every reading built on it came back empty. That is a silent
    # failure with a loud symptom: `test_worker_names.py` regenerates the shipped table from these
    # dumps and got an empty table. Read whichever name is on disk rather than re-expanding 652
    # files - this box is short of disk, and the logs are an archive that is only ever read.
    logs = sorted((directory / "launcher_logs").glob("*_launcher.log*"))
    for log in logs:
        name = log.name[: -len(".gz")] if log.suffix == ".gz" else log.name
        tag = name[: -len("_launcher.log")]
        dump = directory / f"{tag}_dump.bin"
        if not dump.exists():
            continue
        text = (gzip.decompress(log.read_bytes()).decode("utf-8", "replace")
                if log.suffix == ".gz" else log.read_text())
        data, console = dump.read_bytes(), dump_console(tag, text)
        scatter = re.search(r"--dump-scatter\s+([0-9A-Fa-fx,]+)", text)
        if scatter:
            # memory-dump-scatter: one file, but its blocks are UNRELATED regions, so the run's
            # own list of bases is the only thing that says where each one belongs.
            size = int((re.search(r"--dump-size\s+(\d+)", text) or [None, "1024"])[1])
            for index, base in enumerate(int(part, 0) for part in scatter.group(1).split(",")
                                         if part):
                block = data[index * size:(index + 1) * size]
                if block:
                    found.append((f"{tag}[{index}]", console, base, block))
            continue
        match = re.search(r"--dump-address\s+(0x[0-9A-Fa-f]+)", text)
        if match:
            found.append((tag, console, int(match.group(1), 0), data))
    return found


def every_dump(directory, console="firered"):
    """-> [(base, data)] for the dumps of ONE cartridge; `console=None` for all of them.

    ONE CARTRIDGE AT A TIME, and it is not a preference. lg191 dumped 16 KB of LeafGreen at
    0x08081C9C, which is FireRed's 0x08081CC8 shifted by that segment's -0x2C, and folding it into
    the same image as the FireRed dumps put LeafGreen bodies at FireRed addresses: gSpecials[54] is
    Script_HasTrainerBeenFought at 0x08083C08 on FireRed and the mixed image answered 0x08083C34,
    the +0x2C twin, whose body calls FlagSet where the decomp calls FlagGet. Every call target read
    out of the wrong cartridge's copy is that cartridge's address, which is where a good part of
    "127 call targets with no name" came from. Session 42."""
    return [(base, data) for _tag, its_console, base, data in dumps(directory)
            if console is None or its_console == console]


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
    ap.add_argument("--console", choices=("firered", "leafgreen", "both"), default="firered",
                    help="which cartridge's dumps --with-every-dump may add (default firered); "
                         "`both` puts two cartridges' code at one set of addresses, so use it only "
                         "to compare them, never to read one")
    args = ap.parse_args()

    data = open(args.path, "rb").read()
    segments = [(args.base, data)]
    if args.with_every_dump:
        segments += every_dump(args.scratchpad,
                               None if args.console == "both" else args.console)
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

    strings = scrcmd.data_pointers(memory, reached)
    if strings and not args.quiet:
        print("the data these scripts point at, as the dumps hold it:")
        for address in sorted(strings):
            why = ", ".join(sorted({kind for kind, _source in strings[address]}))
            text = scrcmd.read_string(memory, address)
            shown = repr(text) if text is not None else "<runs off the end of the dump>"
            print(f"  0x{address:08X}  {why:10s} {shown}")
        print()

    print(f"{len(memory)} bytes in {len(memory.segments)} region"
          f"{'s' if len(memory.segments) != 1 else ''}: {len(starts)} entry points, "
          f"{len(reached)} blocks read, {len(strings)} data addresses held, "
          f"{len(referenced)} wanted and not held")
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
