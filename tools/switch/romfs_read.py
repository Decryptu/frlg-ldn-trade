#!/usr/bin/env python3
"""Read a retail Switch title's RomFS in place, without extracting it.

Offline and game-independent. A retail RomFS is tens of thousands of files and
gigabytes; hactool's --listromfs segfaults on a sparse NCA and a full extraction
does not fit on this machine. Nothing here needs either: the NCA's RomFS section
is AES-128-CTR with the decrypted title key, and CTR is seekable, so any range of
it can be decrypted straight off the container.

The counter is the section CTR's high half followed by (nca_relative_offset >> 4)
big-endian, which makes every read independent. Reading the 0x50-byte RomFS header
back with header_size == 0x50 is the proof the counter is right.

docs/switch_re.md "Reading the RomFS".
"""

import argparse
import struct
import sys

from Crypto.Cipher import AES

SECTOR = 0x10


class CtrReader:
    """A seekable window onto one AES-128-CTR section of a container."""

    def __init__(self, path, base, key, ctr_high):
        self.fh = open(path, "rb")
        self.base = base          # where the NCA starts inside the container
        self.key = key
        self.ctr_high = ctr_high  # the section CTR's high 8 bytes

    def read(self, nca_offset, size):
        """Decrypt `size` bytes at `nca_offset` (relative to the NCA's start)."""
        if size <= 0:
            return b""
        pad = nca_offset % SECTOR
        aligned = nca_offset - pad
        raw_len = pad + size
        self.fh.seek(self.base + aligned)
        raw = self.fh.read(raw_len)
        if len(raw) < raw_len:
            raise EOFError(f"short read at {nca_offset:#x}: {len(raw)} of {raw_len}")
        ctr = self.ctr_high + struct.pack(">Q", aligned >> 4)
        clear = AES.new(self.key, AES.MODE_CTR, nonce=b"", initial_value=ctr).decrypt(raw)
        return clear[pad:pad + size]

    def close(self):
        self.fh.close()


class RomFs:
    """The RomFS metadata tables, parsed once and held in memory."""

    HEADER_FMT = "<10Q"

    def __init__(self, reader, romfs_offset):
        self.reader = reader
        self.romfs_offset = romfs_offset   # NCA-relative start of the level-5 data
        head = struct.unpack(self.HEADER_FMT, reader.read(romfs_offset, 0x50))
        (self.header_size,
         self.dir_hash_off, self.dir_hash_size,
         self.dir_meta_off, self.dir_meta_size,
         self.file_hash_off, self.file_hash_size,
         self.file_meta_off, self.file_meta_size,
         self.file_data_off) = head
        if self.header_size != 0x50:
            raise ValueError(
                f"header_size is {self.header_size:#x}, not 0x50 - the CTR or the "
                f"offset is wrong, and nothing read past here means anything")
        self.dir_meta = reader.read(romfs_offset + self.dir_meta_off, self.dir_meta_size)
        self.file_meta = reader.read(romfs_offset + self.file_meta_off, self.file_meta_size)

    def _dir(self, off):
        parent, sibling, child_dir, child_file, _hash, name_len = struct.unpack_from(
            "<6I", self.dir_meta, off)
        name = self.dir_meta[off + 24:off + 24 + name_len].decode("utf-8", "replace")
        return parent, sibling, child_dir, child_file, name

    def _file(self, off):
        parent, sibling = struct.unpack_from("<2I", self.file_meta, off)
        data_off, data_size = struct.unpack_from("<2Q", self.file_meta, off + 8)
        _hash, name_len = struct.unpack_from("<2I", self.file_meta, off + 24)
        name = self.file_meta[off + 32:off + 32 + name_len].decode("utf-8", "replace")
        return parent, sibling, data_off, data_size, name

    def walk(self):
        """Yield (path, data_offset, data_size) for every file, depth first."""
        stack = [(0, "")]
        while stack:
            dir_off, prefix = stack.pop()
            _p, _s, child_dir, child_file, _n = self._dir(dir_off)
            off = child_file
            while off != 0xFFFFFFFF:
                _p, sibling, data_off, data_size, name = self._file(off)
                yield prefix + "/" + name, data_off, data_size
                off = sibling
            off = child_dir
            while off != 0xFFFFFFFF:
                _p, sibling, _cd, _cf, name = self._dir(off)
                stack.append((off, prefix + "/" + name))
                off = sibling

    def read_file(self, data_off, size):
        return self.reader.read(self.romfs_offset + self.file_data_off + data_off, size)


def scan(romfs, needles, names=None, chunk=8 << 20):
    """Search every file's DATA for any of `needles`; yield (path, offset, needle).

    Streamed, so a 4 GB RomFS costs no disk. One pass takes as many needles as
    wanted because the read, not the search, is what a scan spends.
    """
    overlap = max(len(n) for n in needles) - 1
    for path, data_off, size in romfs.walk():
        if names is not None and not any(n in path.lower() for n in names):
            continue
        pos = 0
        tail = b""
        while pos < size:
            n = min(chunk, size - pos)
            buf = tail + romfs.read_file(data_off + pos, n)
            for needle in needles:
                start = 0
                while True:
                    hit = buf.find(needle, start)
                    if hit < 0:
                        break
                    yield path, pos - len(tail) + hit, needle
                    start = hit + 1
            tail = buf[-overlap:] if overlap else b""
            pos += n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container", help="the NSP (or bare NCA) to read in place")
    ap.add_argument("--nca-offset", type=lambda s: int(s, 0), default=0,
                    help="where the program NCA starts inside the container")
    ap.add_argument("--romfs-offset", type=lambda s: int(s, 0), required=True,
                    help="NCA-relative start of the RomFS level-5 data")
    ap.add_argument("--title-key", required=True, help="the DECRYPTED title key, hex")
    ap.add_argument("--ctr-high", default="0000000200000000",
                    help="the section CTR's high 8 bytes, hex")
    ap.add_argument("--list", action="store_true", help="print every file")
    ap.add_argument("--grep", help="only paths containing this (case-insensitive)")
    ap.add_argument("--extract", help="path of one file to write out")
    ap.add_argument("--out", help="where --extract writes")
    ap.add_argument("--search", action="append", default=[],
                    help="hex bytes to look for in the file DATA; repeatable")
    ap.add_argument("--search-text", action="append", default=[],
                    help="ASCII to look for in the file DATA; repeatable")
    ap.add_argument("--search-in", help="comma-separated path substrings to limit --search")
    args = ap.parse_args(argv)

    reader = CtrReader(args.container, args.nca_offset,
                       bytes.fromhex(args.title_key), bytes.fromhex(args.ctr_high))
    romfs = RomFs(reader, args.romfs_offset)
    print(f"romfs ok: header_size 0x50, file_data at "
          f"{args.romfs_offset + romfs.file_data_off:#x}", file=sys.stderr)

    if args.list or args.grep:
        want = args.grep.lower() if args.grep else None
        total = 0
        shown = 0
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

    if args.search or args.search_text:
        needles = [bytes.fromhex(h) for h in args.search]
        needles += [t.encode() for t in args.search_text]
        names = [s.strip().lower() for s in args.search_in.split(",")] if args.search_in else None
        hits = 0
        for path, off, needle in scan(romfs, needles, names):
            hits += 1
            print(f"HIT {needle.hex()} {path} +{off:#x}", flush=True)
        print(f"{hits} hits", file=sys.stderr)

    reader.close()


if __name__ == "__main__":
    main()
