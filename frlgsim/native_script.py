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

import math
from dataclasses import dataclass, field

from . import rom_map
from .field_stubs import STUBS
from .rng_countdown import NATURE_NAMES, NUM_NATURES
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
    cap = int(cap)
    if not 1 <= cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {cap}")
    code = stub("shiny-seek",
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=cap)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


def _stage_and_battle(code, species, level, *, item=0, scratch=SCRATCH):
    """-> the staged stub, the call, and the encounter. ONE of these, for every hunt stub.

    The tail is the whole reason the builders share a path: `releaseall` + `end` after
    dowildbattle, because the battle RESUMES the script [rng_script.BATTLE_TAIL].
    """
    species, level, item = int(species), int(level), int(item)
    if not 1 <= species <= MAX_SPECIES:
        raise NativeScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise NativeScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise NativeScriptError(f"item is a u16, got {item}")
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


# --- asking for more than a shiny -----------------------------------------------------------
# shiny-seek tests the first two draws. mon-seek tests all four, which is the whole mon: the
# personality decides shininess AND the nature, and draws 3 and 4 are the six IVs
# [decomp:src/pokemon.c:1836]. Everything here is the HOST half of asm/field/mon-seek.s - the
# packed words it reads, and the cost of asking for each thing.

# The IVs in the order the ROM draws them, which is the order the packed words use. It is NOT the
# order a summary screen shows (that one puts SPEED last), and mixing the two silently asks for a
# floor on the wrong stat, so the names are spelled out once here and parsed against.
IV_FIELDS = ("hp", "attack", "defense", "speed", "sp_attack", "sp_defense")
MAX_IV = 31                             # MAX_PER_STAT_IVS [decomp:include/constants/pokemon.h]
IV_BITS = 5
IV_TERMINATOR_BIT = 30                  # asm/field/mon-seek.s: the loop counts with this bit
ANY_NATURE = (1 << NUM_NATURES) - 1

# The hot loop, counted off the disassembly and asserted against unicorn in the tests: fifteen
# THUMB instructions for a state that is not shiny, which is 8191 states in 8192.
INSTRUCTIONS_PER_ITERATION = 15

# HOW LONG A SEARCH MAY FREEZE THE OVERWORLD. There is no menu to back out of, the field engine
# has not returned, and the player is looking at a still frame with the music still playing.
# The ceiling is on the WORST case - the whole cap - which by construction of `cap_for` is what
# 1 search in 100 costs; the expected search is `SEARCH_CONFIDENCE`-dependent and several times
# shorter, and `search_cost` reports both so the number the player will actually see is the one
# quoted to them. AN ESTIMATE FROM THE GBA's CLOCK, NOT A MEASUREMENT - see
# CYCLES_PER_INSTRUCTION_FROM_EWRAM below, and the first run to report a visible pause settles it.
MAX_FREEZE_FRAMES = 900                 # ~15 s at 59.7275 Hz
SEARCH_CONFIDENCE = 0.99                # the default cap is the one that finds a state this often


@dataclass(frozen=True)
class MonCriteria:
    """What mon-seek will accept. SHINY IS NOT A FIELD HERE - the hot loop always tests it.

    `natures` is a tuple of nature ids (empty means any) and `iv_minimums` six floors in DRAW
    order, IV_FIELDS. Both turn into one packed word the stub reads out of its literal pool.
    """

    natures: tuple = ()
    iv_minimums: tuple = field(default_factory=lambda: (0,) * len(IV_FIELDS))

    def __post_init__(self):
        natures = tuple(sorted({int(n) for n in self.natures}))
        for nature in natures:
            if not 0 <= nature < NUM_NATURES:
                raise NativeScriptError(
                    f"nature ids are 0..{NUM_NATURES - 1}, got {nature}")
        minimums = tuple(int(v) for v in self.iv_minimums)
        if len(minimums) != len(IV_FIELDS):
            raise NativeScriptError(
                f"iv_minimums takes {len(IV_FIELDS)} floors in draw order "
                f"({', '.join(IV_FIELDS)}), got {len(minimums)}")
        for value in minimums:
            if not 0 <= value <= MAX_IV:
                raise NativeScriptError(f"an IV floor is 0..{MAX_IV}, got {value}")
        object.__setattr__(self, "natures", natures)
        object.__setattr__(self, "iv_minimums", minimums)

    @property
    def nature_mask(self):
        """-> p_nature: bit N set = nature N accepted. No nature named means every one."""
        if not self.natures:
            return ANY_NATURE
        mask = 0
        for nature in self.natures:
            mask |= 1 << nature
        return mask

    @property
    def iv_word(self):
        """-> p_ivmin: six 5-bit floors, plus the terminator the stub's loop counts with."""
        word = 1 << IV_TERMINATOR_BIT
        for index, minimum in enumerate(self.iv_minimums):
            word |= minimum << (IV_BITS * index)
        return word

    @property
    def probability(self):
        """-> roughly what fraction of states pass all three tests.

        An ESTIMATE, and the approximation is named: shininess and the nature are both functions
        of the same personality, so they are not independent in the strict sense, and `% 25` over
        2**32 favours 21 of the 25 residues by one part in 171 million. Neither moves a search
        budget. The IV draws are separate draws and multiply exactly.
        """
        chance = SHINY_ODDS / 65536
        chance *= (len(self.natures) or NUM_NATURES) / NUM_NATURES
        for minimum in self.iv_minimums:
            chance *= (MAX_IV + 1 - minimum) / (MAX_IV + 1)
        return chance

    def describe(self):
        """-> one line naming everything asked for, read back out of the packed words."""
        parts = ["shiny"]
        if self.natures:
            parts.append("/".join(NATURE_NAMES[n] for n in self.natures))
        floors = [f"{name} >= {value}"
                  for name, value in zip(IV_FIELDS, self.iv_minimums) if value]
        parts.extend(floors)
        return ", ".join(parts)


def parse_natures(text):
    """-> the nature ids in `text`: names as the game spells them, or plain numbers."""
    if text is None or not str(text).strip():
        return ()
    lowered = {name.lower(): index for index, name in enumerate(NATURE_NAMES)}
    out = []
    for token in str(text).replace(",", " ").split():
        if token.lower() in lowered:
            out.append(lowered[token.lower()])
            continue
        try:
            value = int(token, 0)
        except ValueError:
            raise NativeScriptError(
                f"{token!r} is not a nature; they are {', '.join(NATURE_NAMES)}") from None
        if not 0 <= value < NUM_NATURES:
            raise NativeScriptError(f"nature ids are 0..{NUM_NATURES - 1}, got {value}")
        out.append(value)
    return tuple(sorted(set(out)))


def parse_iv_minimums(items):
    """-> six floors in draw order, from `stat=value` strings (`speed=31`, `hp=20`)."""
    minimums = [0] * len(IV_FIELDS)
    for item in items or ():
        text = str(item).replace(">=", "=").replace(":", "=")
        name, _, value = text.partition("=")
        name = name.strip().lower().replace("-", "_")
        aliases = {"atk": "attack", "def": "defense", "spe": "speed", "spd": "speed",
                   "spa": "sp_attack", "spatk": "sp_attack", "spdef": "sp_defense",
                   "spd_def": "sp_defense"}
        name = aliases.get(name, name)
        if name not in IV_FIELDS:
            raise NativeScriptError(
                f"{item!r} does not name an IV; they are {', '.join(IV_FIELDS)}")
        try:
            floor = int(value, 0)
        except ValueError:
            raise NativeScriptError(f"{item!r} needs a floor, as in {name}=31") from None
        if not 0 <= floor <= MAX_IV:
            raise NativeScriptError(f"an IV floor is 0..{MAX_IV}, got {floor}")
        minimums[IV_FIELDS.index(name)] = floor
    return tuple(minimums)


def frames_for_iterations(iterations):
    """-> how long a search of this many states blocks the field engine, in frames. AN ESTIMATE."""
    return frames_for(float(iterations) * INSTRUCTIONS_PER_ITERATION)


def cap_for(criteria, confidence=SEARCH_CONFIDENCE):
    """-> the smallest cap that finds a state `confidence` of the time."""
    chance = criteria.probability
    if not 0 < confidence < 1:
        raise NativeScriptError(f"confidence is a probability, got {confidence}")
    return max(1, math.ceil(math.log1p(-confidence) / math.log1p(-chance)))


def search_cost(criteria, cap):
    """-> what asking for this costs: how long it is expected to take, and the worst it can take.

    The freeze is what the player sees, so both are in frames. Everything here rests on
    INSTRUCTIONS_PER_ITERATION and the GBA's clock and NOT on a hardware measurement; the first
    run that reports a visible pause is the measurement, and it goes in docs/rng.md when it comes.
    """
    chance = criteria.probability
    cap = int(cap)
    expected = 1 / chance
    return {"probability": chance,
            "expected_iterations": expected,
            "expected_frames": frames_for_iterations(expected),
            "expected_seconds": frames_for_iterations(expected) / 59.7275,
            "cap": cap,
            "worst_frames": frames_for_iterations(cap),
            "worst_seconds": frames_for_iterations(cap) / 59.7275,
            "found_within_cap": 1 - (1 - chance) ** cap}


def build_mon_hunt_script(species, level, *, criteria=None, item=0, cap=None,
                          max_freeze_frames=MAX_FREEZE_FRAMES, scratch=SCRATCH,
                          rng_address=None, sav2_pointer=None):
    """The RAM script that makes the next scripted encounter a mon we described, from any state.

    build_shiny_hunt_script with three tests instead of one, and the same one-frame guarantee:
    every command before `dowildbattle` returns FALSE, so the search and the generation happen in
    one pass of the field engine with nothing between them that draws.

    THE COST IS CHECKED BEFORE THE CARD IS BUILT, not after the player is looking at a frozen
    overworld. A criterion does not slow an iteration down - it multiplies how many are needed -
    so `cap` is what bounds the freeze, and a cap whose worst case exceeds `max_freeze_frames` is
    refused here. Raising that ceiling is a decision, so it is an argument and not a default.
    """
    criteria = MonCriteria() if criteria is None else criteria
    if not isinstance(criteria, MonCriteria):
        raise NativeScriptError("criteria must be a MonCriteria")
    chosen_cap = cap_for(criteria) if cap is None else int(cap)
    cost = search_cost(criteria, chosen_cap)
    # The freeze is checked BEFORE the cap's own range, because a cap past that range is always a
    # freeze past this ceiling and the ceiling is the answer that says what to do about it.
    if cost["worst_frames"] > max_freeze_frames:
        raise NativeScriptError(
            f"{criteria.describe()} is 1 state in {1 / cost['probability']:,.0f}: searching for "
            f"it can block the overworld for {cost['worst_frames']:,.0f} frames "
            f"({cost['worst_seconds']:.1f} s), past the {max_freeze_frames} frame ceiling. Ask "
            f"for less, or raise max_freeze_frames deliberately.")
    if not 1 <= chosen_cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {chosen_cap}")
    code = stub("mon-seek",
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word)
    return _stage_and_battle(code, species, level, item=item, scratch=scratch)


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
