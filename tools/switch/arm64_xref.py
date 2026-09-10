#!/usr/bin/env python3
"""Find the ARM64 code that references an address, via ADRP(+ADD|+LDR) pairs.

The NSO images written by nso_read.py put every segment at its memory offset, so a file offset IS
the address. That makes an xref a scan: ADRP loads a 4 KB page into Xd, and a following ADD or LDR
with the same base register completes the address. Written for the BDSP work - Pia's
transport carries no searchable constant, so its code is reached from the strings instead.
"""
import struct, sys

def adrp_target(pc, w):
    immlo = (w >> 29) & 3
    immhi = (w >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20): imm -= (1 << 21)          # sign-extend the 21-bit immediate
    return ((pc & ~0xFFF) + (imm << 12)) & 0xFFFFFFFFFFFF

def xrefs(text, targets, base=0, window=12):
    """-> {target: [(code_addr, kind), ...]}. `targets` is a set of addresses."""
    out = {t: [] for t in targets}
    pages = {}
    for t in targets: pages.setdefault(t & ~0xFFF, []).append(t)
    n = len(text) // 4
    words = struct.unpack(f"<{n}I", text[:n*4])
    for i, w in enumerate(words):
        if (w & 0x9F000000) != 0x90000000: continue   # ADRP
        pc = base + i*4
        page = adrp_target(pc, w)
        if page not in pages: continue
        rd = w & 31
        for j in range(i+1, min(i+1+window, n)):
            w2 = words[j]
            if (w2 & 0xFF800000) == 0x91000000 and ((w2 >> 5) & 31) == rd:   # ADD imm
                a = page + ((w2 >> 10) & 0xFFF)
                if a in out: out[a].append((pc, "adrp+add"))
            elif (w2 & 0xFFC00000) == 0xF9400000 and ((w2 >> 5) & 31) == rd: # LDR imm (64)
                a = page + (((w2 >> 10) & 0xFFF) * 8)
                if a in out: out[a].append((pc, "adrp+ldr"))
            elif (w2 & 0x9F000000) == 0x90000000 and (w2 & 31) == rd:
                break                                  # register reloaded
    return out

def bl_targets(text, base=0):
    """-> {callee: [caller_addr,...]} for every BL in the image."""
    n = len(text)//4
    words = struct.unpack(f"<{n}I", text[:n*4])
    calls = {}
    for i, w in enumerate(words):
        if (w & 0xFC000000) != 0x94000000: continue    # BL
        imm = w & 0x03FFFFFF
        if imm & (1 << 25): imm -= (1 << 26)
        pc = base + i*4
        calls.setdefault(pc + imm*4, []).append(pc)
    return calls

def function_start(text, addr, limit=0x4000):
    """Walk back to a plausible prologue (stp x29,x30 / sub sp) - a heuristic, not proof."""
    a = addr
    while a > 0 and addr - a < limit:
        w = struct.unpack_from('<I', text, a)[0]
        if (w & 0xFFC003E0) == 0xA98003E0 or (w & 0xFF8003FF) == 0xD10003FF:
            return a
        a -= 4
    return None

if __name__ == "__main__":
    img = open(sys.argv[1], 'rb').read()
    tend = int(sys.argv[2], 0)
    tgts = {int(x, 0) for x in sys.argv[3:]}
    for t, refs in xrefs(img[:tend], tgts).items():
        print(f"0x{t:08x}: {len(refs)} xref(s)")
        for a, k in refs[:10]:
            print(f"    0x{a:08x}  {k}")
