#!/usr/bin/env python3
"""Disassemble a window of an NSO image, naming BL targets and ADRP+ADD data addresses.
Usage: arm64_dis.py <image> <addr> [count]     (addresses ARE file offsets - see nso_read.py)"""
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

def dis(img, addr, count=60, note=None):
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    out = []
    for ins in md.disasm(img[addr:addr+count*4], addr):
        line = f"0x{ins.address:08x}  {ins.mnemonic:<8} {ins.op_str}"
        if note:
            n = note(ins)
            if n: line += f"    ; {n}"
        out.append(line)
        if len(out) >= count: break
    return out

if __name__ == "__main__":
    img = open(sys.argv[1], 'rb').read()
    addr = int(sys.argv[2], 0)
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    print("\n".join(dis(img, addr, count)))
