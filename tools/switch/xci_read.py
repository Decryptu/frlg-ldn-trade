#!/usr/bin/env python3
"""Walk a Switch container (XCI/HFS0 or NSP/PFS0) and read its NCAs in place.

Offline, game-independent, and NOTHING is extracted unless asked for: the NCA
header is 0xC00 bytes of AES-128-XTS under `header_key` with a big-endian sector
tweak, and every section below it is AES-128-CTR, which is seekable. So the whole
map - title id, content type, key generation, each section's absolute offset, its
counter and its section key - comes off a 13 GB cartridge image on a network share
with no disk spent.

`--exefs N` lists the PartitionFS in section N and `--extract PATH` writes one file
out of it, which is how the `main` NSO is obtained without unpacking anything.
For a RomFS section the printed `level6` offset is what tools/switch/romfs_read.py
wants for --romfs-offset, and the printed section key is its --title-key.

Key rule, from hactool nca.c: the generation is max(crypto_type, crypto_type2),
minus one when non-zero (0 and 1 are both master key 0), and it indexes
key_area_key_application_%02x. A rights id of all zeroes means key-area crypto and
no ticket is needed at all.

docs/switch_re.md "Do not unpack the NSP".
"""

import argparse
import os
import struct
import sys

from Crypto.Cipher import AES

CONTENT_TYPES = {0: "Program", 1: "Meta", 2: "Control", 3: "Manual", 4: "Data", 5: "PublicData"}
FS_TYPES = {0: "RomFS", 1: "PartitionFS"}
HASH_TYPES = {0: "auto", 1: "none", 2: "sha256(pfs0)", 3: "ivfc(romfs)"}
CRYPT_TYPES = {0: "auto", 1: "none", 2: "XTS", 3: "CTR", 4: "BKTR"}
SECTOR = 0x10


def load_keys(path):
    keys = {}
    with open(path) as fh:
        for line in fh:
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            value = value.strip()
            # A malformed line (34 hex digits) aborts hactool; skip it rather than die.
            if len(value) in (32, 64) and all(c in "0123456789abcdefABCDEF" for c in value):
                keys[name.strip()] = bytes.fromhex(value)
    return keys


def _gf_mul(t):
    n = int.from_bytes(t, "little") << 1
    if n >> 128:
        n = (n ^ 0x87) & ((1 << 128) - 1)
    return n.to_bytes(16, "little")


def xts_decrypt(key, data, sector=0, sector_size=0x200):
    """Nintendo XTS: the tweak is the sector index BIG-endian, not little."""
    data_ecb = AES.new(key[:16], AES.MODE_ECB)
    tweak_ecb = AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for i in range(0, len(data), sector_size):
        tweak = tweak_ecb.encrypt(struct.pack(">QQ", 0, sector + i // sector_size))
        for j in range(i, min(i + sector_size, len(data)), 16):
            block = bytes(a ^ b for a, b in zip(data[j:j + 16], tweak))
            out += bytes(a ^ b for a, b in zip(data_ecb.decrypt(block), tweak))
            tweak = _gf_mul(tweak)
    return bytes(out)


class Container:
    """The file, and the partition trees inside it. Yielded offsets are ABSOLUTE."""

    def __init__(self, path):
        self.fh = open(path, "rb")
        self.path = path

    def read(self, off, size):
        self.fh.seek(off)
        return self.fh.read(size)

    def partitions(self):
        head = self.read(0, 0x200)
        if head[0x100:0x104] == b"HEAD":
            root = struct.unpack_from("<Q", head, 0x130)[0]
            for name, off, size in self._hfs0(root):
                yield f"rootpt:{name}", off, size
                for sub, soff, ssize in self._hfs0(off):
                    yield f"{name}:{sub}", soff, ssize
        elif head[:4] == b"PFS0":
            yield from self._pfs0(0)
        else:
            sys.exit(f"{self.path}: not an XCI (HEAD) or NSP (PFS0)")

    def _hfs0(self, base):
        hdr = self.read(base, 0x10)
        if hdr[:4] != b"HFS0":
            return
        count, str_size = struct.unpack_from("<II", hdr, 4)
        table = self.read(base + 0x10, count * 0x40)
        strings = self.read(base + 0x10 + count * 0x40, str_size)
        data = base + 0x10 + count * 0x40 + str_size
        for i in range(count):
            off, size, name_off = struct.unpack_from("<QQI", table, i * 0x40)
            name = strings[name_off:strings.index(b"\0", name_off)].decode()
            yield name, data + off, size

    def _pfs0(self, base):
        hdr = self.read(base, 0x10)
        if hdr[:4] != b"PFS0":
            return
        count, str_size = struct.unpack_from("<II", hdr, 4)
        table = self.read(base + 0x10, count * 0x18)
        strings = self.read(base + 0x10 + count * 0x18, str_size)
        data = base + 0x10 + count * 0x18 + str_size
        for i in range(count):
            off, size, name_off = struct.unpack_from("<QQI", table, i * 0x18)
            name = strings[name_off:strings.index(b"\0", name_off)].decode()
            yield name, data + off, size


class CtrSection:
    """A seekable window onto one AES-128-CTR NCA section, decrypting on read."""

    def __init__(self, container, nca_offset, section, key):
        self.c = container
        self.base = nca_offset + section["offset"]
        self.key = key
        self.ctr_high = section["ctr"]
        self.section = section

    def read(self, offset, size):
        """`offset` is relative to the SECTION; the counter is NCA-relative."""
        if size <= 0:
            return b""
        nca_off = self.section["offset"] + offset
        pad = nca_off % SECTOR
        aligned = nca_off - pad
        raw = self.c.read(self.base - self.section["offset"] + aligned, pad + size)
        ctr = self.ctr_high + struct.pack(">Q", aligned >> 4)
        clear = AES.new(self.key, AES.MODE_CTR, nonce=b"", initial_value=ctr).decrypt(raw)
        return clear[pad:pad + size]


def parse_fs_header(fs):
    """One 0x200 FS header. Offsets per hactool nca.h: 0x2 fs, 0x3 hash, 0x4 crypt."""
    s = {"fs_type": fs[2], "hash_type": fs[3], "crypt": fs[4], "ctr": fs[0x140:0x148][::-1],   # hactool nca.c: the 8 CTR bytes are used REVERSED
         "data_offset": None, "data_size": None}
    sb = fs[0x8:0x140]
    if s["hash_type"] == 3 and sb[:4] == b"IVFC":
        num_levels = struct.unpack_from("<I", sb, 0xC)[0]
        best = None
        for i in range(min(num_levels, 6)):
            off, size, _blk, _r = struct.unpack_from("<QQII", sb, 0x10 + i * 0x18)
            if size:
                best = (off, size)
        if best:
            s["data_offset"], s["data_size"] = best
    elif s["hash_type"] == 2:
        # pfs0_superblock_t: master_hash 0x20, block_size, always_2, hash tbl off/size, pfs0 off/size
        s["data_offset"], s["data_size"] = struct.unpack_from("<QQ", sb, 0x38)
    if s["crypt"] == 4:
        # bktr_superblock_t: the IVFC header (0xE0), 0x18 of padding, then two bktr_header_t
        # {u64 offset, u64 size, "BKTR", u32, u32 num_entries, u32}: relocation, subsection.
        # Both offsets are section-relative. tools/switch/bktr_read.py reads them.
        for name, at in (("relocation", 0xF8), ("subsection", 0x118)):
            off, size, magic, _v, count, _r = struct.unpack_from("<QQ4sIII", sb, at)
            if magic == b"BKTR":
                s[name] = {"offset": off, "size": size, "entries": count}
    return s


def nca_header(container, off, header_key):
    clear = xts_decrypt(header_key, container.read(off, 0xC00))
    if clear[0x200:0x203] != b"NCA":
        return None
    h = {
        "magic": clear[0x200:0x204].decode(errors="replace"),
        "content_type": clear[0x205],
        "kaek_index": clear[0x207],
        "size": struct.unpack_from("<Q", clear, 0x208)[0],
        "title_id": struct.unpack_from("<Q", clear, 0x210)[0],
        "sdk": tuple(clear[0x21F:0x21B:-1]),
        "rights_id": clear[0x230:0x240],
        "key_area": clear[0x300:0x340],
        "sections": [],
    }
    gen = max(clear[0x206], clear[0x220])
    h["keygen"] = gen - 1 if gen else 0
    for i in range(4):
        start, end = struct.unpack_from("<II", clear, 0x240 + i * 0x10)
        if not end:
            continue
        s = parse_fs_header(clear[0x400 + i * 0x200:0x600 + i * 0x200])
        s.update(index=i, offset=start * 0x200, size=(end - start) * 0x200)
        h["sections"].append(s)
    return h


def section_key(h, keys, tickets=None):
    """The body key: key area slot 2 under key_area_key_application_<keygen>, or, for an NCA
    with a rights id, the ticket's title key under titlekek_<keygen>.

    The ticket is `<rights id>.tik` in the same container, its encrypted title key at +0x180
    (hactool ticket.c). The rights id's last byte is the key generation and the titlekek index
    is that minus one, which is the same number as `h["keygen"]`."""
    rights = h["rights_id"]
    if rights != bytes(16):
        name = f"titlekek_{h['keygen']:02x}"
        tik = (tickets or {}).get(rights.hex())
        kek = keys.get(name)
        if tik is None or kek is None:
            return None, name if kek is None else f"ticket {rights.hex()}.tik"
        return AES.new(kek, AES.MODE_ECB).decrypt(tik[0x180:0x190]), name
    name = f"key_area_key_application_{h['keygen']:02x}"
    kaek = keys.get(name)
    if kaek is None:
        return None, name
    area = AES.new(kaek, AES.MODE_ECB).decrypt(h["key_area"])
    return area[0x20:0x30], name


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container")
    ap.add_argument("--keys", default=os.path.expanduser("~/.switch/prod.keys"))
    ap.add_argument("--type", help="only NCAs of this content type, e.g. Program")
    ap.add_argument("--nca", help="only the NCA whose name starts with this")
    ap.add_argument("--exefs", type=int, metavar="N",
                    help="list the PartitionFS in section N of the selected NCA")
    ap.add_argument("--extract", help="with --exefs: the file in it to write out")
    ap.add_argument("--out", help="where --extract writes")
    args = ap.parse_args(argv)

    keys = load_keys(args.keys)
    if "header_key" not in keys:
        sys.exit(f"{args.keys}: no header_key")

    c = Container(args.container)
    entries = list(c.partitions())
    tickets = {name.split(":")[-1][:-4]: c.read(off, size)
               for name, off, size in entries if name.endswith(".tik")}
    for name, off, size in entries:
        if not name.endswith(".nca"):
            if not args.nca:
                print(f"{name:64s} {off:#014x} {size:>16,}")
            continue
        base = name.split(":")[-1]
        if args.nca and not base.startswith(args.nca):
            continue
        h = nca_header(c, off, keys["header_key"])
        if h is None:
            print(f"{name:64s} {off:#014x} {size:>16,}  (header did not decrypt)")
            continue
        ctype = CONTENT_TYPES.get(h["content_type"], str(h["content_type"]))
        if args.type and ctype.lower() != args.type.lower():
            continue
        key, keyname = section_key(h, keys, tickets)
        rights = h["rights_id"].hex()
        print(f"\n{name}  nca at {off:#014x}  {size:,} bytes")
        print(f"    {h['magic']}  {ctype}  title {h['title_id']:016x}  keygen {h['keygen']}"
              f"  sdk {'.'.join(map(str, h['sdk']))}")
        print(f"    rights id {rights}"
              f"{'  (zero: key-area crypto, no ticket needed)' if rights == '0' * 32 else ''}")
        print(f"    section key {key.hex() if key else f'?? no {keyname} in the keyset'}")
        for s in h["sections"]:
            line = (f"    section {s['index']}  {FS_TYPES.get(s['fs_type'], s['fs_type'])}"
                    f"  {HASH_TYPES.get(s['hash_type'], s['hash_type'])}"
                    f"  {CRYPT_TYPES.get(s['crypt'], s['crypt'])}"
                    f"  nca+{s['offset']:#x}..{s['offset'] + s['size']:#x}"
                    f"  ctr {s['ctr'].hex()}")
            if s["data_offset"] is not None:
                line += (f"\n              data at nca+{s['offset'] + s['data_offset']:#x}"
                         f"  ({s['data_size']:,} bytes)")
            print(line)

        if args.exefs is None:
            continue
        want = next((s for s in h["sections"] if s["index"] == args.exefs), None)
        if want is None:
            sys.exit(f"no section {args.exefs} in {base}")
        if want["crypt"] != 3:
            sys.exit(f"section {args.exefs} is {CRYPT_TYPES.get(want['crypt'])}, not CTR")
        sec = CtrSection(c, off, want, key)
        pfs_at = want["data_offset"]
        hdr = sec.read(pfs_at, 0x10)
        if hdr[:4] != b"PFS0":
            sys.exit(f"section {args.exefs} data is not a PFS0: {hdr[:4]!r}")
        count, str_size = struct.unpack_from("<II", hdr, 4)
        table = sec.read(pfs_at + 0x10, count * 0x18)
        strings = sec.read(pfs_at + 0x10 + count * 0x18, str_size)
        data = pfs_at + 0x10 + count * 0x18 + str_size
        print(f"    PFS0: {count} files")
        for i in range(count):
            foff, fsize, name_off = struct.unpack_from("<QQI", table, i * 0x18)
            fname = strings[name_off:strings.index(b"\0", name_off)].decode()
            print(f"        {fsize:12,}  {fname}")
            if args.extract == fname:
                out = args.out or fname
                with open(out, "wb") as fh:
                    left, at = fsize, data + foff
                    while left:
                        chunk = sec.read(at, min(left, 1 << 20))
                        fh.write(chunk)
                        at += len(chunk)
                        left -= len(chunk)
                print(f"        -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
