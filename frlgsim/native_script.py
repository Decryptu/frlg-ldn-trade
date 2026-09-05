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
                         SCR_DOWILDBATTLE, SCR_SETWILDBATTLE, SCR_RELEASEALL, SCR_GOTO,
                         SCR_SETVAR, BATTLE_TAIL, TRAMPOLINE_ADDRESS, TRAMPOLINE_WORD,
                         MAX_LEVEL, MAX_SPECIES, battle_and_exit, setptr)

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

    The tail is the whole reason the builders share a path, and mev18 is why it is what it is: a
    battle MOVES the save block the RAM script lives in, so the engine comes back from the battle
    to an address the script no longer occupies. `battle_and_exit` starts the battle from
    gSpecialVar_0x8000 instead, which does not move [rng_script, and the block above it].
    """
    try:
        battle = battle_and_exit(species, level, item)
    except RngScriptError as error:
        raise NativeScriptError(str(error)) from None
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


def probability_for(criteria, placements=1):
    """-> the fraction of states that pass, when the IV floors must hold in `placements` words.

    asm/field/mon-seek-both.s tests the floors at TWO draw placements because the stray draw moves
    them (mev20; docs/rng.md's Methods 1, 2 and 4), so the IV term is raised to that power. The
    shiny and nature terms are not: both come from the personality, which is drawn before the stray
    and is the same word in every method.
    """
    chance = SHINY_ODDS / 65536
    chance *= (len(criteria.natures) or NUM_NATURES) / NUM_NATURES
    ivs = 1.0
    for minimum in criteria.iv_minimums:
        ivs *= (MAX_IV + 1 - minimum) / (MAX_IV + 1)
    return chance * ivs ** int(placements)


def cap_for(criteria, confidence=SEARCH_CONFIDENCE, placements=1):
    """-> the smallest cap that finds a state `confidence` of the time."""
    chance = probability_for(criteria, placements)
    if not 0 < confidence < 1:
        raise NativeScriptError(f"confidence is a probability, got {confidence}")
    return max(1, math.ceil(math.log1p(-confidence) / math.log1p(-chance)))


def search_cost(criteria, cap, placements=1):
    """-> what asking for this costs: how long it is expected to take, and the worst it can take.

    The freeze is what the player sees, so both are in frames. Everything here rests on
    INSTRUCTIONS_PER_ITERATION and the GBA's clock and NOT on a hardware measurement; the first
    run that reports a visible pause is the measurement, and it goes in docs/rng.md when it comes.
    """
    chance = probability_for(criteria, placements)
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
        elif op == SCR_SETVAR:
            var = int.from_bytes(script[i + 1:i + 3], "little")
            value = int.from_bytes(script[i + 3:i + 5], "little")
            note = ""
            if var == 0x8000 and value == TRAMPOLINE_WORD:
                note = "  (dowildbattle; end, at gSpecialVar_0x8000 - out of the save block)"
            lines.append(f"  setvar 0x{var:04X} = 0x{value:04X}{note}")
            i += 5
        elif op == SCR_GOTO:
            target = int.from_bytes(script[i + 1:i + 5], "little")
            where = " (the trampoline)" if target == TRAMPOLINE_ADDRESS else ""
            lines.append(f"  goto 0x{target:08X}{where}")
            i += 5
            # `goto` is unconditional, so nothing after it is script at all. On a body-hosted
            # card what follows is the PAYLOAD, and decoding it as commands prints nonsense.
            if i < len(script):
                lines.append(f"  ... {len(script) - i} bytes of payload at offset {i}, never "
                             f"read by the engine (the trampoline branches to it)")
                break
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


# --- the payload in the script body: one byte each instead of six -------------------------------
# Everything above stages code with `setptr`, six script bytes a payload byte, which caps a field
# stub at ~163 bytes. The cap comes off here because the field engine does not copy the body:
# `GetRamScript` returns `scriptData->script` itself [decomp:src/script.c:514], a pointer into
# gSaveBlock1Ptr->ramScript.data, and never reads past the last command. Bytes appended after it are
# delivered storage at one script byte each.
#
# Aiming at them is a run-time read, not a build-time constant: the save-block offset is re-rolled at
# a battle or a load and then fixed for the frame our script runs in, and &gSaveBlock1Ptr is a
# link-time IWRAM word that says what it currently is. A 36-byte trampoline reads it.
#
# The body is 995 bytes [RamScriptData.script] and the Mystery Event script carrying it is 1024
# [mystery_event.MAX_SCRIPT_SIZE] less the VM's own 16, so 995 binds by 13 bytes. `body_capacity`
# states it. docs/rng.md.

RAMSCRIPT_IN_SAVEBLOCK1 = 0x361C        # SaveBlock1.ramScript [decomp:include/global.h]
RAMSCRIPT_MAGIC_OFFSET = RAMSCRIPT_IN_SAVEBLOCK1 + 4        # past the u32 checksum
RAMSCRIPT_BODY_OFFSET = RAMSCRIPT_MAGIC_OFFSET + 4          # past magic, mapGroup, mapNum, objectId
RAM_SCRIPT_MAGIC = 51                   # [decomp:src/script.c:12], written by InitRamScript [:505]

# Where a hunt reports what it did: SaveBlock1.unused_348C[400] [decomp:include/global.h]. bs65 read
# all 400 bytes off the console as zero before anything was written there. It is in the save, so it
# survives the battle and reaches flash when the player saves, and it is outside ramScript, so the
# RAM script checksum is untouched and the binding survives.
HUNT_LOG_OFFSET = 0x348C
HUNT_LOG_MAGIC = 0x474F4C31             # so an untouched region is not read as a report
HUNT_LOG_SIZE = 20
HUNT_LOG_FIELDS = ("magic", "start", "found", "iterations", "cap")

TRAMPOLINE_STUB = "ram-jump"

# THE PAYLOAD MUST START AT A MULTIPLE OF FOUR, not merely an even offset. A Thumb stub reaches its
# literal pool with `ldr rN, [pc, #imm]` and its tail with `adr`, and both use Align(PC, 4). Place
# the same bytes two off and the branch still lands and the code still runs, but every pool word is
# read two bytes past where it lives - for mon-seek-far, a filler length of 0x0433CF15 and a fault
# inside its own checksum loop. Caught by emulate_body_script below, which walks the real script
# bytes rather than running a stub at an address a harness chose.
#
# Four is also sufficient, provably, which is why nothing checks it at run time:
# `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)` [decomp:src/load_save.c:75] is `& 0x7C`,
# and gSaveBlock1 is an EWRAM struct of u32 fields, so RAMSCRIPT_BODY_OFFSET (0x3624) keeps the base
# word-aligned.
BODY_ALIGNMENT = 4


def ram_jump_stub(payload_offset, *, sb1_pointer=None, magic_offset=RAMSCRIPT_MAGIC_OFFSET):
    """-> the trampoline, patched to branch at the payload `payload_offset` bytes into the body.

    `p_entry` is measured from the MAGIC BYTE rather than from the block base so the stub can add
    the same register twice and needs no third pool word. See asm/field/ram-jump.s.
    """
    offset = int(payload_offset)
    if offset < 0:
        raise NativeScriptError(f"the payload offset is not negative, got {offset}")
    if offset % 4:
        raise NativeScriptError(
            f"the payload must start at a MULTIPLE OF FOUR, got {offset}; see BODY_ALIGNMENT")
    entry = (RAMSCRIPT_BODY_OFFSET - int(magic_offset)) + offset
    return stub(TRAMPOLINE_STUB,
                sb1ptr=rom_map.GSAVEBLOCK1PTR if sb1_pointer is None else int(sb1_pointer),
                magic=int(magic_offset), entry=entry | 1)


def body_prefix_size(tail_size):
    """-> how many script bytes come before the payload: the staged trampoline, the call, the tail.

    The trampoline's LENGTH does not depend on what it is patched with, so this is knowable before
    the stub exists - which is what breaks the circularity of "the offset depends on the script
    that contains the offset".
    """
    size = len(STUBS[TRAMPOLINE_STUB][0]) * SETPTR_SIZE + CALLNATIVE_SIZE + int(tail_size)
    return size + (-size % BODY_ALIGNMENT)


def body_capacity(tail_size):
    """-> how many payload bytes fit after a tail of `tail_size`, and what the old way allowed."""
    prefix = body_prefix_size(tail_size)
    staged = (MAX_RAM_SCRIPT_SIZE - CALLNATIVE_SIZE - int(tail_size)) // SETPTR_SIZE
    return {"prefix": prefix, "payload": MAX_RAM_SCRIPT_SIZE - prefix,
            "staged_equivalent": staged, "limit": MAX_RAM_SCRIPT_SIZE}


def build_body_script(payload, tail=b"", *, scratch=SCRATCH, sb1_pointer=None):
    """-> the RAM script that stages the trampoline, calls it, runs `tail`, and carries `payload`.

    The layout, and the order is the argument:

        setptr x36    the trampoline, into gDecompressionBuffer      216 bytes
        callnative    -> the trampoline -> the payload -> back         5
        <tail>        whatever the script does after the payload has returned
        <pad>         one byte at most, so the payload starts even
        <payload>     never reached by the engine: `tail` ends in a `goto`

    The payload returns with `pop {r4-r7, pc}`, which lands back in ScrCmd_callnative's caller
    because the trampoline BRANCHES rather than calls, so the script continues into `tail`.
    """
    payload = bytes(payload)
    tail = bytes(tail)
    if not payload:
        raise NativeScriptError("nothing to run")
    prefix = body_prefix_size(len(tail))
    code = ram_jump_stub(prefix, sb1_pointer=sb1_pointer)
    body = (stage(code, scratch) + callnative_at(scratch) + tail
            + b"\x00" * (prefix - len(stage(code, scratch)) - CALLNATIVE_SIZE - len(tail))
            + payload)
    assert body.index(payload, prefix) == prefix
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(
            f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}; the payload is "
            f"{len(payload)} bytes and at most {body_capacity(len(tail))['payload']} fit")
    return body


# The filler that proves the far end of the body arrived. EVERY BYTE IS NON-ZERO, and that is the
# whole design: `InitRamScript` zero-fills the body before copying what it was given
# [ClearRamScript, decomp:src/script.c:495], so a short delivery reads back as zeros and the sum
# the stub computes is STRICTLY LOWER than the one in its pool. A missing tail cannot sum right.
FILLER_SEED = 0x5EED1E55


def filler_bytes(count, seed=FILLER_SEED):
    """-> `count` reproducible non-zero bytes. Not random, just not uniform: a constant fill would
    sum the same under a reordering, and a zero byte would hide a truncation."""
    out = bytearray()
    state = int(seed) & 0xFFFFFFFF
    while len(out) < int(count):
        state = (state * 0x41C64E6D + 0x00006073) & 0xFFFFFFFF
        out.append(((state >> 16) & 0xFE) + 1)      # 1..255, never 0
    return bytes(out)


# THE SEARCH MUST HOLD AT 95%, NOT 99%, WHEN THE FLOORS ARE TESTED TWICE, and the reason is what a
# miss costs. The RAM script ends in `end` and not `endram`, so the binding SURVIVES and the player
# re-triggers the whole thing by talking to their MOM again [rng_script]. A miss is one A press; a
# 99% cap would freeze the overworld for 18 s on the unlucky run, every time it is unlucky. Cheap
# retry, expensive stare - so buy the retry.
BOTH_CONFIDENCE = 0.95


def build_mon_hunt_far_script(species, level, *, criteria=None, item=0, cap=None,
                              max_freeze_frames=MAX_FREEZE_FRAMES, scratch=SCRATCH,
                              rng_address=None, sav2_pointer=None, sb1_pointer=None,
                              payload_bytes=None, seed=FILLER_SEED,
                              stub_name="mon-seek-far", placements=1,
                              confidence=SEARCH_CONFIDENCE):
    """build_mon_hunt_script, with the code RUN OUT OF THE BODY and the body FILLED to prove it.

    ONE variable changes against mev19's card: where the search code lives. Same criteria, same
    species, same cap, same battle tail. What is new is the filler behind the stub and the sum the
    stub takes over it before it will search at all - so the run distinguishes three things the
    screen could not otherwise tell apart:

        a shiny mon of the nature and IVs asked for   the whole body arrived and ran from the body
        an ordinary mon                               the guard bailed, or the tail is short
        a frozen overworld                            neither of the above; it must not happen

    `payload_bytes` is how much of the body the payload occupies, filler included; it defaults to
    every byte that fits. Passing a smaller number is the way to bisect a partial delivery without
    changing anything else.
    """
    criteria = MonCriteria() if criteria is None else criteria
    if not isinstance(criteria, MonCriteria):
        raise NativeScriptError("criteria must be a MonCriteria")
    chosen_cap = (cap_for(criteria, confidence, placements) if cap is None else int(cap))
    cost = search_cost(criteria, chosen_cap, placements)
    if cost["worst_frames"] > max_freeze_frames:
        raise NativeScriptError(
            f"{criteria.describe()} is 1 state in {1 / cost['probability']:,.0f}: searching for "
            f"it can block the overworld for {cost['worst_frames']:,.0f} frames "
            f"({cost['worst_seconds']:.1f} s), past the {max_freeze_frames} frame ceiling. Ask "
            f"for less, or raise max_freeze_frames deliberately.")
    if not 1 <= chosen_cap <= 1 << 24:
        raise NativeScriptError(f"the iteration cap is 1..{1 << 24}, got {chosen_cap}")

    try:
        tail = battle_and_exit(species, level, item)
    except RngScriptError as error:
        raise NativeScriptError(str(error)) from None
    room = body_capacity(len(tail))["payload"]
    total = room if payload_bytes is None else int(payload_bytes)
    bare = len(STUBS[stub_name][0])
    if not bare <= total <= room:
        raise NativeScriptError(
            f"the payload is {bare}..{room} bytes here; asked for {total}")
    filler = filler_bytes(total - bare, seed)
    code = stub(stub_name,
                rng=rom_map.GRNG_VALUE if rng_address is None else int(rng_address),
                sav2ptr=rom_map.GSAVEBLOCK2PTR if sav2_pointer is None else int(sav2_pointer),
                cap=chosen_cap, nature=criteria.nature_mask, ivmin=criteria.iv_word,
                padlen=len(filler), padsum=sum(filler) & 0xFFFFFFFF)
    return build_body_script(code + filler, tail, scratch=scratch, sb1_pointer=sb1_pointer)


# --- running the WHOLE script offline, not just the stub ----------------------------------------
# bs56's lesson, and it cost a run: "the offline harness passed throughout because it builds its
# distribution DIRECTLY - the one path the hardware uses was the one never exercised offline."
# `emulate` above runs a stub at an address someone hands it. That is not the path any more. The
# path is: the engine walks the body, `setptr` writes the trampoline a byte at a time, `callnative`
# enters it, the trampoline reads gSaveBlock1Ptr and branches BACK INTO THE BODY at an offset the
# host computed. Every one of those can be wrong on its own, so all of them run here.

def emulate_body_script(script, *, sb1_base=0x02025734, rng_state=0, trainer_id=0, secret_id=0,
                        sav2_base=0x02024588, instruction_limit=1 << 26,
                        magic=RAM_SCRIPT_MAGIC):
    """Execute `script` the way the field engine would, and return what it left behind.

    Only the four commands these scripts use are interpreted - `setptr`, `callnative`, and enough
    of the battle tail to stop at it. `goto` ENDS the walk: it leaves the body for the trampoline
    at gSpecialVar_0x8000, which is where the battle happens and where nothing offline can follow.

    `sb1_base` stands in for whatever SetSaveBlocksPointers rolled this time; the default is the
    address the console was actually seen at. The script's own bytes are placed at
    sb1_base + RAMSCRIPT_BODY_OFFSET, which is where `GetRamScript` hands them to the engine, and
    the magic byte in front of them is set to RAM_SCRIPT_MAGIC exactly as InitRamScript sets it.
    """
    script = bytes(script)
    if len(script) > MAX_RAM_SCRIPT_SIZE:
        raise NativeScriptError(f"{len(script)} bytes is past the {MAX_RAM_SCRIPT_SIZE}-byte body")
    save2 = bytearray(0x10)
    save2[0x0A:0x0C] = int(trainer_id).to_bytes(2, "little")
    save2[0x0C:0x0E] = int(secret_id).to_bytes(2, "little")
    # The RamScript as InitRamScript leaves it: magic, the three binding bytes, then the body
    # zero-filled to 995 [ClearRamScript then memcpy, decomp:src/script.c:495].
    ram_script = (bytes([int(magic) & 0xFF, 0xFF, 0xFF, 0xFF])
                  + script.ljust(MAX_RAM_SCRIPT_SIZE, b"\0"))
    staged, called, executed = {}, [], []
    i = 0
    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            staged[int.from_bytes(script[i + 2:i + 6], "little")] = script[i + 1]
            i += SETPTR_SIZE
        elif op == SCR_CALLNATIVE:
            called.append(int.from_bytes(script[i + 1:i + 5], "little"))
            i += CALLNATIVE_SIZE
        elif op == SCR_SETWILDBATTLE:
            i += 6
        elif op == SCR_SETVAR:
            i += 5
        elif op == SCR_GOTO:
            break
        elif op == SCR_END:
            break
        else:
            raise NativeScriptError(f"unhandled opcode 0x{op:02X} at {i} of the body")
    if len(called) != 1:
        raise NativeScriptError(f"expected exactly one callnative, found {len(called)}")
    # The staged bytes have to be contiguous or `callnative`'s entry means nothing.
    low, high = min(staged), max(staged)
    if sorted(staged) != list(range(low, high + 1)):
        raise NativeScriptError("the staged bytes are not contiguous")
    blob = bytes(staged[a] for a in range(low, high + 1))
    entry = called[0]
    if entry & ~1 != low:
        raise NativeScriptError(
            f"callnative goes to 0x{entry & ~1:08X}, the staged bytes start at 0x{low:08X}")
    regions = {
        rom_map.GRNG_VALUE: int(rng_state).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK1PTR: int(sb1_base).to_bytes(4, "little"),
        rom_map.GSAVEBLOCK2PTR: int(sav2_base).to_bytes(4, "little"),
        int(sav2_base): bytes(save2),
        int(sb1_base) + RAMSCRIPT_MAGIC_OFFSET: ram_script,
        int(sb1_base) + HUNT_LOG_OFFSET: bytes(HUNT_LOG_SIZE),
    }
    result = emulate(blob, base=low, memory=regions, instruction_limit=instruction_limit)
    executed.append(entry)
    return {"rng": int.from_bytes(result["memory"][rom_map.GRNG_VALUE], "little"),
            "instructions": result["instructions"],
            "staged_bytes": len(blob), "staged_at": low, "entry": entry,
            "payload_at": int(sb1_base) + RAMSCRIPT_BODY_OFFSET,
            "log": decode_hunt_log(result["memory"][int(sb1_base) + HUNT_LOG_OFFSET]),
            "body": ram_script}


def build_mon_hunt_both_script(species, level, **kwargs):
    """build_mon_hunt_far_script with asm/field/mon-seek-both.s: the floors tested at BOTH draw
    placements, so the stray draw cannot move the IVs out from under the answer.

    mev20 is why this exists and the .s header has the derivation: two words cover all three
    methods docs/rng.md records, because word A puts the first IV triple on d3 and the second on
    d4, and word B puts them on d4 and d5.
    """
    kwargs.setdefault("stub_name", "mon-seek-both")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)


def decode_hunt_log(blob):
    """-> what a hunt wrote into SaveBlock1.unused_348C, or None if nothing did.

    `magic` is checked rather than assumed: the region is zero on an untouched save (bs65), and a
    run whose search was exhausted writes a `found` of 0 on purpose - so without the marker a miss
    and a stub that never ran would decode identically, which is exactly the pair this is for.
    """
    blob = bytes(blob)
    if len(blob) < HUNT_LOG_SIZE:
        raise NativeScriptError(f"a hunt log is {HUNT_LOG_SIZE} bytes, got {len(blob)}")
    words = [int.from_bytes(blob[i * 4:i * 4 + 4], "little") for i in range(len(HUNT_LOG_FIELDS))]
    record = dict(zip(HUNT_LOG_FIELDS, words))
    if record["magic"] != HUNT_LOG_MAGIC:
        return None
    record["found_one"] = record["found"] != 0
    record["exhausted"] = not record["found_one"]
    record["instructions"] = record["iterations"] * INSTRUCTIONS_PER_ITERATION
    record["frames"] = frames_for(record["instructions"])
    record["seconds"] = record["frames"] / 59.7275
    return record


def build_mon_hunt_log_script(species, level, **kwargs):
    """build_mon_hunt_both_script with asm/field/mon-seek-log.s: the same search, reporting.

    The stub writes {marker, start, found, iterations, cap} to SaveBlock1 + HUNT_LOG_OFFSET, which
    a `save-dump` of sav1 at that offset reads back. That is what turns a hunt from something
    reconstructed out of the caught mon into something measured while it happens.
    """
    kwargs.setdefault("stub_name", "mon-seek-log")
    kwargs.setdefault("placements", 2)
    kwargs.setdefault("confidence", BOTH_CONFIDENCE)
    return build_mon_hunt_far_script(species, level, **kwargs)
