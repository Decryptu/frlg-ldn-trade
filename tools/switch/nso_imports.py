#!/usr/bin/env python3
"""Map an NSO's imported symbols to the GOT slots that hold them.

A call into another module (nnSdk's nn::ldn, say) goes through a GOT slot filled at
load time by a JUMP_SLOT or GLOB_DAT relocation naming a dynamic symbol. So "where
does this module call nn::ldn::CreateNetwork" is: find the slot, then find the code
that loads it. tools/switch/nso_relocs.py only reads RELATIVE relocations, which are
the intra-module ones.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nso_relocs import mod0, dynamic

R_GLOB_DAT, R_JUMP_SLOT = 1025, 1026


def imports(img):
    """-> list of (got_slot, symbol_name)."""
    _, dyn = mod0(img)
    t = dynamic(img, dyn)
    symtab, strtab, syment = t.get(6), t.get(5), t.get(11, 24)
    out = []
    ranges = [(t.get(7), t.get(8), t.get(9, 24)), (t.get(23), t.get(2), 24)]
    for rela, sz, ent in ranges:
        if not rela or not sz:
            continue
        for o in range(rela, rela + sz, ent):
            off, info, add = struct.unpack_from("<QQq", img, o)
            rtype, sym = info & 0xFFFFFFFF, info >> 32
            if rtype not in (R_GLOB_DAT, R_JUMP_SLOT) or not sym:
                continue
            name_off = struct.unpack_from("<I", img, symtab + sym * syment)[0]
            end = img.find(b"\0", strtab + name_off)
            out.append((off, img[strtab + name_off:end].decode("utf-8", "replace")))
    return out


if __name__ == "__main__":
    img = open(sys.argv[1], "rb").read()
    want = [a.lower() for a in sys.argv[2:]]
    got = imports(img)
    print(f"{len(got):,} imported symbols", file=sys.stderr)
    for slot, name in sorted(got):
        if not want or any(w in name.lower() for w in want):
            print(f"got 0x{slot:08x}  {name}")
