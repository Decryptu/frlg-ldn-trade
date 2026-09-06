"""Reading THUMB code out of a ROM dump: where a function ends, what it calls, what it points at.

bs84 established the method by hand and `scratchpad/handler_workers.py` automated it for one table:
a handler is an entry point, the worker behind it is what is worth calling, and the `bl` targets a
body makes - in order - name those workers against the decomp's own call order. This module is that
reading, table-agnostic, so `tools/frlg/rom_functions.py` can point it at gSpecials, gScriptCmdTable or
gMysteryEventScriptCmdTable without three copies of the arithmetic.

THE TRAP, and it cost one wrong answer (MEScrCmd_crc came back with 25 `bl` targets where the decomp
gives it four): this ROM is agbcc-built and agbcc does NOT end a THUMB function `pop {..., pc}`
(0xBDxx). It ends it `pop {r4,r5,r6}; pop {r1}; bx r1` - so `bx Rn` is a terminator too, and a
reader looking only for 0xBDxx walks straight into the next function. docs/frlg_rom_buffer_script.md.
"""

# `bl` is a PAIR of halfwords on this core: F800|hi carries bits 22..12 of the offset, F800|lo bits
# 11..1. THUMB PC is the instruction address + 4.
BL_HI, BL_LO, BL_MASK = 0xF000, 0xF800, 0xF800

# `ldr Rd, [pc, #imm8*4]` - 0x48xx..0x4Fxx. The literal pool is where a function keeps the addresses
# it touches, which is how G_SPECIALS was read out of ScrCmd_special (bs92).
LDR_PC, LDR_PC_MASK = 0x4800, 0xF800


def is_return(halfword):
    """`pop {..., pc}` or `bx Rn`. Both, because of the agbcc epilogue in the module docstring."""
    return halfword & 0xFF00 == 0xBD00 or halfword & 0xFF87 == 0x4700


def is_prologue(halfword):
    """`push {...}` with or without lr - the first instruction of the next function."""
    return halfword & 0xFF00 in (0xB500, 0xB400)


def _halfword(data, at):
    return int.from_bytes(data[at:at + 2], "little")


def function_end(data, base, start, limit):
    """-> where the function at `start` ends, by finding its epilogue rather than trusting `limit`.

    Without this the LAST entry in a dump has no next entry to stop it and swallows everything to
    the end. A return is only a boundary when the next function's prologue follows it, allowing a
    couple of halfwords of alignment and of literal pool, because a function can return from more
    than one place and agbcc parks its pool immediately after the body."""
    for at in range(start - base, min(limit - base, len(data) - 1), 2):
        if not is_return(_halfword(data, at)):
            continue
        for ahead in range(at + 2, min(at + 12, len(data) - 1), 2):
            if is_prologue(_halfword(data, ahead)):
                return base + at + 2
    return limit


def bl_targets(data, base, start, stop):
    """-> [(call site, absolute target)] for the `bl` pairs between `start` and `stop`."""
    out = []
    for at in range(start - base, min(stop - base, len(data) - 3), 2):
        hi, lo = _halfword(data, at), _halfword(data, at + 2)
        if hi & BL_MASK != BL_HI or lo & BL_MASK != BL_LO:
            continue
        offset = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
        if offset & (1 << 22):
            offset -= 1 << 23
        out.append((base + at, (base + at + 4 + offset) & 0xFFFFFFFF))
    return out


def pc_literals(data, base, start, stop):
    """-> [(site, pool address, value or None)] for the `ldr Rd, [pc, #imm]` between the two.

    The value is None when the pool word falls outside this dump. A function's pool is its list of
    globals: bs92 read G_SPECIALS and G_SPECIALS_END straight out of ScrCmd_special's, and their
    difference - 444 * 4 - is what proved the table's length without a second run."""
    out = []
    for at in range(start - base, min(stop - base, len(data) - 1), 2):
        word = _halfword(data, at)
        if word & LDR_PC_MASK != LDR_PC:
            continue
        pool = (((base + at) + 4) & ~3) + (word & 0xFF) * 4
        inside = pool - base
        value = (int.from_bytes(data[inside:inside + 4], "little")
                 if 0 <= inside <= len(data) - 4 else None)
        out.append((base + at, pool, value))
    return out
