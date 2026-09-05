"""NATIVE CODE IN THE OVERWORLD: a RAM script that stages a stub into EWRAM and calls it.

THE GAP THIS CLOSES. `CLI_RUN_BUFFER_SCRIPT` hands the console 1024 bytes of our own code and calls
them [docs/buffer_script.md], but only while the Mystery Gift link is up - so native code could
read and write the console's memory and could never be present at an ENCOUNTER, which is where
everything about the RNG is decided. docs/rng.md records that as the structural limit, and the
paragraph is correct about what it says: FIELD BYTECODE cannot walk an LCG or test for shininess,
having only `compare` and `goto_if`, and a target computed before a Mystery Gift session is stale
by the time the player is back outside because the title screen reseeds on the way out
[mystery_gift_menu.c:463 -> CB2_InitTitleScreen -> SeedRng, title_screen.c:735].

A STAGED NATIVE STUB IS NOT FIELD BYTECODE. The field script command table has both halves:

    bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
    { u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
    bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
    { void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
[decomp:src/scrcmd.c:300, :120; data/script_cmd_table.inc]

so a script can WRITE ARBITRARY BYTES ANYWHERE and then CALL THEM. `setptr` was already used here
to set gRngValue [frlgsim/rng_script.py]; what is new is that the bytes it writes can be code.

WHERE THIS CAME FROM, and it should be said plainly: notblisy/RUBYSAPPHIREDLC, found by the user.
`SOURCE/*/eonticket.asm` stages sixteen bytes with sixteen `writebytetoaddr` (the Ruby/Sapphire
spelling of `setptr`) and then does `callasm` on them, and `SOURCE/*/celebirng.txt` is the ARM it
calls - an LCG loop that runs until the PID it would produce is shiny. Ruby/Sapphire, a completely
different delivery (dot codes over the e-Reader's link cable, which the Switch release does not
expose at all), and not one address in it is usable here. The TECHNIQUE is what transfers.
REFERENCES.local.md has the reading.

THE COST, AND IT IS THE ONLY BUDGET THAT BINDS. A RAM script body is 995 bytes
[struct RamScriptData.script, decomp:include/global.h:439] and every staged byte costs SIX of them
(opcode + immediate + a 4-byte absolute address), so:

    staged bytes  <=  (995 - the rest of the script) / 6   ~=  160

which is why the stubs are THUMB. asm/field/shiny-seek.s is 72 bytes = 432 script bytes, and the
whole hunt script is under half the body. `budget()` states this from the numbers rather than from
this comment.

WHERE THE CODE GOES: gDecompressionBuffer, 0x0201C000, measured twice [rom_map, bs08 and bs11].
It is a scratch buffer by design, it is fixed at link time (unlike anything in a save block, which
carries a re-rolled ASLR offset - bs45/bs46), and CLI_RUN_BUFFER_SCRIPT has been executing our code
out of it since bs01, so that EWRAM there is executable is not an assumption on this console.
Everything the script does happens inside ONE field-engine loop, because `setptr` and `callnative`
both return FALSE: no frame boundary between the last staged byte and the call.

THUMB, AND BIT 0. `callnative` calls through a function pointer, so the low bit of the address
selects the instruction set. The stubs are Thumb and `callnative_at` sets it. A word-aligned
address would enter ARM state and execute the same bytes as garbage.

A STUB MUST NOT BE ABLE TO HANG. There is no menu to back out of in the overworld; a loop that
never returns freezes the game. Every stub takes a bounded iteration count and every one of them
is run under unicorn here, offline, before it is ever staged - the same rule buffer payloads live
under.
"""

from . import rom_map
from .field_stubs import STUBS
# ONE encoder for `setptr`, not two. bs56 was lost to the same shape of duplication in config.py.
from .rng_script import (MAX_RAM_SCRIPT_SIZE, SCR_END, SCR_SETPTR, RngScriptError,  # noqa: F401
                         SCR_DOWILDBATTLE, SCR_SETWILDBATTLE, SCR_RELEASEALL, BATTLE_TAIL,
                         MAX_LEVEL, MAX_SPECIES, setptr)

SCR_CALLNATIVE = 0x23

SETPTR_SIZE = 6                     # opcode + immediate + 4-byte address
CALLNATIVE_SIZE = 5                 # opcode + 4-byte address

# gDecompressionBuffer. See the module docstring for why this address and not another.
SCRATCH = rom_map.GDECOMPRESSION_BUFFER
SCRATCH_SIZE = 0x4000               # [decomp:src/decompress.c, gDecompressionBuffer[0x4000]]

SHINY_ODDS = 8                      # [decomp:include/constants/pokemon.h]


class NativeScriptError(RngScriptError):
    """A field script that would not do what it says, refused before it can reach a console."""


def stage(blob, address=SCRATCH):
    """-> the `setptr` run that writes `blob` to `address`, one byte per command.

    Six bytes of script per byte of payload. There is no block-copy command in the field engine -
    `copybyte` (0x15) moves ONE byte and needs an absolute source, which is no cheaper and would
    need the bytes to already be somewhere the script can name.
    """
    blob, address = bytes(blob), int(address)
    if not blob:
        raise NativeScriptError("nothing to stage")
    if not 0 <= address <= 0xFFFFFFFF - len(blob):
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address for {len(blob)} bytes")
    return b"".join(setptr(byte, address + i) for i, byte in enumerate(blob))


def callnative_at(address, *, thumb=True):
    """-> one `callnative`. `thumb` sets bit 0, which is what puts the CPU in Thumb state."""
    address = int(address)
    if address % 2:
        raise NativeScriptError(f"0x{address:X} is odd; pass the address, the bit is set here")
    if not 0 <= address <= 0xFFFFFFFF:
        raise NativeScriptError(f"0x{address:X} is not a 32-bit address")
    return bytes([SCR_CALLNATIVE]) + (address | (1 if thumb else 0)).to_bytes(4, "little")


def budget(code_size, other=0):
    """-> {} : what staging `code_size` bytes costs against the 995 a RAM script has."""
    staged = int(code_size) * SETPTR_SIZE
    total = staged + CALLNATIVE_SIZE + int(other)
    return {"code_size": int(code_size), "staged_bytes": staged, "other_bytes": int(other),
            "total": total, "limit": MAX_RAM_SCRIPT_SIZE, "spare": MAX_RAM_SCRIPT_SIZE - total,
            "max_code_size": (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(other)) // SETPTR_SIZE,
            "fits": total <= MAX_RAM_SCRIPT_SIZE}


def stub(name, **params):
    """-> the stub's THUMB bytes with its literal pool patched.

    The offsets come from the assembler (scripts/gen_field_stubs.py reads the symbol table), so a
    parameter that is renamed or moved in the .s is a KeyError here and not a silently wrong word.
    """
    try:
        code, _digest, symbols = STUBS[name]
    except KeyError:
        raise NativeScriptError(f"unknown field stub {name!r}; have {sorted(STUBS)}") from None
    out = bytearray(code)
    for key, value in params.items():
        symbol = f"p_{key}"
        if symbol not in symbols:
            raise NativeScriptError(
                f"{name} has no parameter {key!r}; have "
                f"{sorted(s[2:] for s in symbols if s.startswith('p_'))}")
        offset = symbols[symbol]
        value = int(value) & 0xFFFFFFFF
        out[offset:offset + 4] = value.to_bytes(4, "little")
    return bytes(out)


def build_shiny_hunt_script(species, level, *, item=0, cap=1 << 18, scratch=SCRATCH,
                            rng_address=None, sav2_pointer=None):
    """The RAM script that makes the NEXT scripted encounter shiny, from any state, no aiming.

    Stage `shiny-seek`, call it, then `setwildbattle` + `dowildbattle`. Every command before
    dowildbattle returns FALSE [decomp:src/scrcmd.c], so the field engine runs the whole thing in
    ONE frame with nothing in between: the state the stub leaves in gRngValue is the state
    CreateScriptedWildMon consumes two commands later, and shininess is decided by the two draws
    the stub just tested. There is no press to time and no target to go stale.

    NO TRAINER ID IS PASSED, and that is deliberate. The stub dereferences gSaveBlock2Ptr and reads
    playerTrainerId itself, so the same bytes are correct on FireRed and on LeafGreen and nothing
    here has to know, or be kept in step with, whose console it is [asm/field/shiny-seek.s].
    """
    species, level, item, cap = int(species), int(level), int(item), int(cap)
    if not 1 <= species <= MAX_SPECIES:
        raise NativeScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise NativeScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise NativeScriptError(f"item is a u16, got {item}")
    if not 1 <= cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {cap}")
    code = stub("shiny-seek",
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=cap)
    battle = (bytes([SCR_SETWILDBATTLE]) + species.to_bytes(2, "little")
              + bytes([level]) + item.to_bytes(2, "little") + bytes([SCR_DOWILDBATTLE])
              + BATTLE_TAIL)      # the battle RESUMES the script; see rng_script.BATTLE_TAIL
    body = stage(code, scratch) + callnative_at(scratch) + battle
    plan = budget(len(code), other=len(battle))
    if not plan["fits"]:
        raise NativeScriptError(
            f"{plan['total']} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}; the stub is "
            f"{len(code)} bytes and at most {plan['max_code_size']} can be staged")
    assert len(body) == plan["total"]
    return body


def describe(script):
    """-> lines: what the bytes do, read back OUT of them rather than from what we meant.

    A run of `setptr` into one region is collapsed, because 72 of them say nothing one at a time.
    """
    lines, i, run = [], 0, []

    def flush():
        if run:
            base = run[0][0]
            lines.append(f"  setptr x{len(run)} -> 0x{base:08X}..0x{run[-1][0]:08X}  "
                         f"({bytes(v for _, v in run)[:8].hex()}...)")
            run.clear()

    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            run.append((int.from_bytes(script[i + 2:i + 6], "little"), script[i + 1]))
            i += SETPTR_SIZE
            continue
        flush()
        if op == SCR_CALLNATIVE:
            address = int.from_bytes(script[i + 1:i + 5], "little")
            state = "THUMB" if address & 1 else "ARM"
            lines.append(f"  callnative 0x{address:08X} ({state})")
            i += CALLNATIVE_SIZE
        elif op == SCR_SETWILDBATTLE:
            species = int.from_bytes(script[i + 1:i + 3], "little")
            lines.append(f"  setwildbattle species {species} Lv{script[i + 3]} "
                         f"item {int.from_bytes(script[i + 4:i + 6], 'little')}")
            i += 6
        elif op == SCR_DOWILDBATTLE:
            lines.append("  dowildbattle (yields; the battle RESUMES the script after it)")
            i += 1
        elif op == SCR_RELEASEALL:
            lines.append("  releaseall")
            i += 1
        elif op == SCR_END:
            lines.append("  end (the binding SURVIVES; endram 0x0d would clear it)")
            i += 1
        else:
            lines.append(f"  UNKNOWN opcode 0x{op:02X} at {i}")
            break
    flush()
    return lines


# --- running a stub offline, before it can ever reach the overworld ------------------------------
# The same rule buffer payloads live under [docs/buffer_script.md], and it matters MORE here: a
# buffer script that hangs freezes the Mystery Gift menu, which the player can at least see is
# stuck; a field stub that hangs freezes the overworld inside a script, with no menu at all.

_EWRAM, _EWRAM_SIZE = 0x02000000, 0x40000
_IWRAM, _IWRAM_SIZE = 0x03000000, 0x8000
_STACK, _STACK_SIZE = 0x03007000, 0x1000        # inside IWRAM, where the GBA's sp lives
_RETURN = 0x02FF0000                            # our own marker, mapped but never executed
_INSTRUCTION_LIMIT = 1 << 24


def emulate(code, *, base=SCRATCH, memory=None, instruction_limit=_INSTRUCTION_LIMIT):
    """Run a staged stub the way `callnative` does: no arguments, Thumb, returns to lr.

    `memory` places regions the stub reads or writes as {address: bytes}; the result's `memory` is
    those same regions read back afterwards, which is where the answer is - a field stub returns
    nothing (`callnative` ignores r0) and speaks only through what it wrote.
    """
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UcError
    from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    uc.mem_map(_EWRAM, _EWRAM_SIZE)
    uc.mem_map(_IWRAM, _IWRAM_SIZE)
    uc.mem_map(_RETURN & ~0xFFF, 0x1000)
    code = bytes(code)
    uc.mem_write(base, code)
    for address, blob in (memory or {}).items():
        uc.mem_write(int(address), bytes(blob))
    counted = [0]
    uc.hook_add(UC_HOOK_CODE, lambda *_args: counted.__setitem__(0, counted[0] + 1))
    uc.reg_write(UC_ARM_REG_SP, _STACK + _STACK_SIZE - 0x40)
    uc.reg_write(UC_ARM_REG_LR, _RETURN | 1)
    try:
        uc.emu_start(base | 1, _RETURN, count=instruction_limit)
    except UcError as error:
        raise NativeScriptError(f"the stub faulted: {error}") from error
    if uc.reg_read(UC_ARM_REG_PC) & ~1 != _RETURN:
        raise NativeScriptError(
            f"the stub had not returned after {instruction_limit} instructions. In the overworld "
            "that is a frozen game with no menu to back out of.")
    return {"instructions": counted[0],
            "memory": {int(a): bytes(uc.mem_read(int(a), len(b)))
                       for a, b in (memory or {}).items()}}


# The CPU is 16.78 MHz and a frame is 280,896 cycles [the GBA's clock]. A Thumb ALU instruction is
# one cycle from IWRAM but this runs from EWRAM, which is 16-bit and WAITS: 3 cycles a halfword
# fetch on the default waitstate setting, so ~3 cycles an instruction is the honest figure. The
# search is 15 instructions an iteration and averages 8192 iterations (1 state in 8192 is shiny),
# so ~370k cycles - a little over ONE FRAME. The worst case allowed by the default cap is ~50
# frames, or most of a second. That is a visible hitch and nothing worse: interrupts stay enabled
# throughout, so VBlank, DMA and the music carry on; the field engine simply has not returned yet.
# NOT MEASURED ON HARDWARE. It is an estimate from the clock, and the run will say what it was.
CYCLES_PER_INSTRUCTION_FROM_EWRAM = 3
CYCLES_PER_FRAME = 280896


def frames_for(instructions):
    """-> roughly how many frames a stub of this length blocks the field engine for."""
    return int(instructions) * CYCLES_PER_INSTRUCTION_FROM_EWRAM / CYCLES_PER_FRAME
