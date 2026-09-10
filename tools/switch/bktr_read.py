#!/usr/bin/env python3
"""Read a game update's RomFS in place: a BKTR section over the base game's RomFS.

Offline and game-independent. An update NCA's RomFS section is a patch: a relocation table
maps every virtual RomFS range either to a range of the update's own section (with its own
counter, from a subsection table) or to a range of the base game's RomFS. Both tables sit at
the end of the update's section and decrypt under the section's ordinary CTR, so the whole
virtual RomFS can be read straight off the two containers without extracting either.

    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp --list
    ./.venv/bin/python tools/switch/bktr_read.py UPDATE.nsp --base BASE.nsp \\
        --extract /Data/Managed/Metadata/global-metadata.dat --out global-metadata.dat

Layouts are hactool's (nca.h, bktr.c). A relocation entry is {u64 virt, u64 phys, u32 is_patch}
in 0x4000-byte buckets keyed by virtual offset; a subsection entry is {u64 phys, u32, u32 ctr}
in 0x4000-byte buckets keyed by physical offset, and its ctr replaces bytes 4..8 of the section
counter. A read never crosses a relocation entry, and a base-side read is the base NCA's own
section at the physical offset.

docs/switch_re.md "Reading a game update's RomFS".
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xci_read import (Container, CtrSection, load_keys, nca_header, section_key,   # noqa: E402
                      CONTENT_TYPES)
from romfs_read import RomFs                                                       # noqa: E402

BUCKET = 0x4000
RELOC_ENTRY = struct.Struct("<QQI")        # virt_offset, phys_offset, is_patch
SUBSEC_ENTRY = struct.Struct("<QII")       # offset, _, ctr_val


def _buckets(raw, entry):
    """-> (keys, [entries]) for one BKTR block: a header bucket of keys then one bucket per key."""
    _z, num_buckets, _total = struct.unpack_from("<IIQ", raw, 0)
    keys = struct.unpack_from(f"<{num_buckets}Q", raw, 0x10)
    per_bucket = (BUCKET - 0x10) // entry.size
    out = []
    for b in range(num_buckets):
        at = BUCKET * (1 + b)
        _z, count, end = struct.unpack_from("<IIQ", raw, at)
        entries = [entry.unpack_from(raw, at + 0x10 + i * entry.size)
                   for i in range(min(count, per_bucket))]
        out.append((end, entries))
    return keys, out


def _lookup(keys, buckets, offset):
    """hactool bktr.c: the last bucket whose key is <= offset, then the last entry whose
    offset is <= offset, and the entry's reach ends at the next entry (or the bucket's end)."""
    b = 0
    for i in range(1, len(keys)):
        if keys[i] > offset:
            break
        b = i
    end, entries = buckets[b]
    e = 0
    for i in range(1, len(entries)):
        if entries[i][0] > offset:
            break
        e = i
    reach = entries[e + 1][0] if e + 1 < len(entries) else end
    return entries[e], reach


class BktrSection:
    """The virtual RomFS section of an update NCA, readable at section-relative offsets."""

    def __init__(self, patch, base):
        self.patch = patch          # CtrSection over the update's BKTR section
        self.base = base            # CtrSection over the base game's RomFS section
        sec = patch.section
        reloc = patch.read(sec["relocation"]["offset"], sec["relocation"]["size"])
        subsec = patch.read(sec["subsection"]["offset"], sec["subsection"]["size"])
        self.reloc = _buckets(reloc, RELOC_ENTRY)
        self.subsec = _buckets(subsec, SUBSEC_ENTRY)
        self.size = struct.unpack_from("<Q", reloc, 8)[0]

    def read(self, offset, size):
        out = bytearray()
        while size > 0:
            (virt, phys, is_patch), reach = _lookup(*self.reloc, offset)
            n = min(size, reach - offset)
            at = offset - virt + phys
            if is_patch:
                out += self._read_patch(at, n)
            else:
                out += self.base.read(at, n)
            offset += n
            size -= n
        return bytes(out)

    def _read_patch(self, offset, size):
        out = bytearray()
        while size > 0:
            (start, _z, ctr_val), reach = _lookup(*self.subsec, offset)
            n = min(size, reach - offset)
            ctr_high = self.patch.ctr_high[:4] + struct.pack(">I", ctr_val)
            out += self._ctr_read(offset, n, ctr_high)
            offset += n
            size -= n
        return bytes(out)

    def _ctr_read(self, offset, size, ctr_high):
        saved = self.patch.ctr_high
        self.patch.ctr_high = ctr_high
        try:
            return self.patch.read(offset, size)
        finally:
            self.patch.ctr_high = saved


def program_nca(container_path, keys, want=None):
    """-> (container, nca offset, header, section key) of the Program NCA."""
    c = Container(container_path)
    entries = list(c.partitions())
    tickets = {name.split(":")[-1][:-4]: c.read(off, size)
               for name, off, size in entries if name.endswith(".tik")}
    for name, off, size in entries:
        if not name.endswith(".nca"):
            continue
        base = name.split(":")[-1]
        if want and not base.startswith(want):
            continue
        h = nca_header(c, off, keys["header_key"])
        if h is None or CONTENT_TYPES.get(h["content_type"]) != "Program":
            continue
        key, keyname = section_key(h, keys, tickets)
        if key is None:
            sys.exit(f"{base}: no {keyname}")
        return c, off, h, key
    sys.exit(f"{container_path}: no Program NCA")


def open_update_romfs(update_path, base_path, keys, update_nca=None, base_nca=None):
    """-> (BktrSection, RomFs) for the update's virtual RomFS."""
    uc, uoff, uh, ukey = program_nca(update_path, keys, update_nca)
    bc, boff, bh, bkey = program_nca(base_path, keys, base_nca)
    usec = next((s for s in uh["sections"] if s["crypt"] == 4), None)
    if usec is None:
        sys.exit(f"{update_path}: the Program NCA has no BKTR section")
    bsec = next((s for s in bh["sections"] if s["fs_type"] == 0 and s["crypt"] == 3), None)
    if bsec is None:
        sys.exit(f"{base_path}: the Program NCA has no CTR RomFS section")
    virt = BktrSection(CtrSection(uc, uoff, usec, ukey), CtrSection(bc, boff, bsec, bkey))
    return virt, RomFs(virt, usec["data_offset"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("update", help="the update NSP/XCI, read in place")
    ap.add_argument("--base", required=True, help="the base game's NSP/XCI, read in place")
    ap.add_argument("--keys", default=os.path.expanduser("~/.switch/prod.keys"))
    ap.add_argument("--nca", help="only the update NCA whose name starts with this")
    ap.add_argument("--base-nca", help="only the base NCA whose name starts with this")
    ap.add_argument("--list", action="store_true", help="print every file")
    ap.add_argument("--grep", help="only paths containing this (case-insensitive)")
    ap.add_argument("--extract", help="path of one file to write out")
    ap.add_argument("--out", help="where --extract writes")
    args = ap.parse_args(argv)

    keys = load_keys(args.keys)
    virt, romfs = open_update_romfs(args.update, args.base, keys, args.nca, args.base_nca)
    print(f"romfs ok: header_size 0x50, virtual section {virt.size:,} bytes, "
          f"{len(virt.reloc[0])} relocation buckets, {len(virt.subsec[0])} subsection buckets",
          file=sys.stderr)

    if args.list or args.grep:
        want = args.grep.lower() if args.grep else None
        total = shown = 0
        for path, off, size in romfs.walk():
            total += 1
            if want and want not in path.lower():
                continue
            shown += 1
            print(f"{size:12d}  {off:#014x}  {path}")
        print(f"{total} files, {shown} shown", file=sys.stderr)

    if args.extract:
        for path, off, size in romfs.walk():
            if path == args.extract:
                data = romfs.read_file(off, size)
                out = args.out or path.rsplit("/", 1)[-1]
                with open(out, "wb") as fh:
                    fh.write(data)
                print(f"{len(data)} bytes -> {out}", file=sys.stderr)
                break
        else:
            sys.exit(f"no such file in the romfs: {args.extract}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
