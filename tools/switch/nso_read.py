#!/usr/bin/env python3
"""Decompress a Switch NSO (exefs module) into its three segments, laid out at their memory offsets.

No lz4 dependency: NSO segments use the LZ4 *block* format, which is 40 lines. Written for the BDSP
work (session 43) - the Pia layer we need the key derivation from is statically linked into one of
`main` / `sdk` / `subsdk0`.  Usage: nso_read.py <nso> <out.bin>
"""
import struct, sys

def lz4_block(src, want):
    """LZ4 block decompression. Raises on a malformed stream rather than returning short."""
    out = bytearray(); i = 0; n = len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255: break
        out += src[i:i+lit]; i += lit
        if i >= n: break
        off = src[i] | (src[i+1] << 8); i += 2
        if off == 0: raise ValueError("zero match offset")
        ml = tok & 0xF
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        ml += 4
        start = len(out) - off
        if start < 0: raise ValueError("match before start of output")
        for k in range(ml):
            out.append(out[start + k])
    if want is not None and len(out) != want:
        raise ValueError(f"decompressed {len(out)} bytes, header says {want}")
    return bytes(out)

def read_nso(path):
    d = open(path, 'rb').read()
    if d[:4] != b'NSO0':
        raise ValueError(f"not an NSO: magic {d[:4]!r}")
    flags = struct.unpack('<I', d[0x0C:0x10])[0]
    segs = {}
    for idx, (name, hoff, coff) in enumerate((("text", 0x10, 0x60),
                                              ("rodata", 0x20, 0x64),
                                              ("data", 0x30, 0x68))):
        foff, moff, dsize = struct.unpack('<III', d[hoff:hoff+12])
        csize = struct.unpack('<I', d[coff:coff+4])[0]
        raw = d[foff:foff+csize]
        seg = lz4_block(raw, dsize) if (flags >> idx) & 1 else raw[:dsize]
        segs[name] = (moff, seg)
        print(f"  {name:7s} mem=0x{moff:08x} size=0x{dsize:x} "
              f"{'lz4' if (flags >> idx) & 1 else 'raw'}")
    return segs

def main():
    segs = read_nso(sys.argv[1])
    end = max(m + len(s) for m, s in segs.values())
    img = bytearray(end)
    for m, s in segs.values():
        img[m:m+len(s)] = s
    open(sys.argv[2], 'wb').write(img)
    print(f"wrote {sys.argv[2]}, 0x{end:x} bytes (segments at their memory offsets)")

if __name__ == "__main__":
    main()
