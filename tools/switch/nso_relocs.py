#!/usr/bin/env python3
"""Resolve an NSO's R_AARCH64_RELATIVE relocations, so vtable slots can be read.

An NSO's vtables are empty in the static image - each slot is filled at load time from a RELATIVE
relocation whose ADDEND is the function address. So "who points at this function" is a question for
the relocation table, not a pointer scan (session 43: the GCM pair had no pointers and no BL
callers, which is what sent us here).
"""
import struct, sys

def mod0(img):
    off = struct.unpack_from('<I', img, 4)[0]
    if img[off:off+4] != b'MOD0':
        raise ValueError(f"no MOD0 at 0x{off:x} (found {img[off:off+4]!r})")
    dyn_rel, bss_start, bss_end, eh_s, eh_e, modobj = struct.unpack_from('<iiiiii', img, off+4)
    return off, off + dyn_rel

def dynamic(img, dyn_off):
    tags = {}
    o = dyn_off
    while True:
        tag, val = struct.unpack_from('<qQ', img, o)
        if tag == 0: break
        tags.setdefault(tag, val)
        o += 16
    return tags

def relatives(img):
    """-> list of (slot_address, addend) for every R_AARCH64_RELATIVE."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    rela, sz, ent = t.get(7), t.get(8), t.get(9, 24)
    if rela is None: return []
    out = []
    for o in range(rela, rela + sz, ent):
        off, info, add = struct.unpack_from('<QQq', img, o)
        if (info & 0xFFFFFFFF) == 1027:            # R_AARCH64_RELATIVE
            out.append((off, add))
    return out

if __name__ == "__main__":
    img = open(sys.argv[1], 'rb').read()
    rels = relatives(img)
    print(f"{len(rels):,} RELATIVE relocations")
    want = {int(a, 0) for a in sys.argv[2:]}
    for slot, add in rels:
        if add in want:
            print(f"  slot 0x{slot:08x} -> 0x{add:08x}")
