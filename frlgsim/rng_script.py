"""A field script that sets gRngValue with `setptr` [decomp:src/scrcmd.c:300], in the OVERWORLD.

The Mystery Gift link is the wrong place to seed from: every route out of the menu re-runs
`SeedRng` on the title screen, measured at bs50/bs51. A RAM script runs after that reseed, and
gRngValue is a link-time IWRAM global at 0x03004220, so `setptr` needs no address read and no sled
- unlike `callnative`, which would have to aim at a save block that moves. The script ends with
`end` (0x02), not `endram`, so the binding survives and can be re-triggered. docs/rng.md.
"""

from . import rom_map

SCR_END = 0x02
SCR_ENDRAM = 0x0D
SCR_SETPTR = 0x11
SCR_PLAYSE = 0x2F
SCR_WAITSE = 0x30

SE_SUCCESS = 25                     # [decomp:include/constants/songs.h:29]
MAX_RAM_SCRIPT_SIZE = 995           # sizeof(struct RamScriptData.script) [decomp:include/global.h]


class RngScriptError(Exception):
    pass


def setptr(value, address):
    """One `setptr`: write an immediate byte to an absolute address."""
    value, address = int(value), int(address)
    if not 0 <= value <= 0xFF:
        raise RngScriptError(f"setptr writes ONE byte, got {value}")
    if not 0 <= address <= 0xFFFFFFFF:
        raise RngScriptError(f"0x{address:X} is not a 32-bit address")
    return bytes([SCR_SETPTR, value]) + address.to_bytes(4, "little")


def build_seed_script(value, address=None, sound=SE_SUCCESS):
    """The field script that sets a 32-bit word - gRngValue by default - and says it did.

    `sound` is played so the player knows the script ran: talking to an object whose script does
    nothing looks exactly like talking to an object whose script did not run, and mev03's evidence
    was only that the NPC's normal dialogue did NOT appear. A sound is a positive signal. Pass
    sound=None to write in silence.
    """
    address = rom_map.GRNG_VALUE if address is None else int(address)
    value = int(value) & 0xFFFFFFFF
    if address % 4:
        raise RngScriptError(f"0x{address:X} is not word aligned")
    body = b"".join(setptr((value >> (8 * i)) & 0xFF, address + i) for i in range(4))
    if sound is not None:
        body += bytes([SCR_PLAYSE]) + int(sound).to_bytes(2, "little") + bytes([SCR_WAITSE])
    body += bytes([SCR_END])
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise RngScriptError(f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    return body


def describe_seed_script(script):
    """-> lines: what the bytes do, decoded back out of them rather than from what we meant."""
    lines, i, writes = [], 0, {}
    while i < len(script):
        op = script[i]
        if op == SCR_SETPTR:
            value = script[i + 1]
            address = int.from_bytes(script[i + 2:i + 6], "little")
            writes[address] = value
            lines.append(f"  setptr 0x{value:02X} -> 0x{address:08X}")
            i += 6
        elif op == SCR_PLAYSE:
            lines.append(f"  playse {int.from_bytes(script[i + 1:i + 3], 'little')}")
            i += 3
        elif op == SCR_WAITSE:
            lines.append("  waitse")
            i += 1
        elif op == SCR_END:
            lines.append("  end (the binding SURVIVES; endram 0x0d would clear it)")
            i += 1
        else:
            lines.append(f"  UNKNOWN opcode 0x{op:02X} at {i}")
            break
    base = min(writes) if writes else None
    if base is not None and set(writes) == {base + n for n in range(4)}:
        word = sum(writes[base + n] << (8 * n) for n in range(4))
        what = " (gRngValue)" if base == rom_map.GRNG_VALUE else ""
        lines.append(f"  => 0x{base:08X}{what} = 0x{word:08X}")
    return lines


# --- seed the RNG and generate the mon in the SAME frame -----------------------------------------
# `setwildbattle` (0xB6) calls CreateScriptedWildMon -> CreateMon(&gEnemyParty[0], species, level,
# 32, 0, 0, OT_ID_PLAYER_ID, 0) [decomp:src/scrcmd.c:1935, src/script_pokemon_util.c:128]: fixedIV
# 32 is USE_RANDOM_IVS and hasFixedPersonality 0, so the PID and the IVs are rolled right there in
# four draws with no nature rejection loop.
#
# `setptr` and `setwildbattle` both return FALSE and the field engine runs commands until one
# returns TRUE, so the seed writes and the generation happen back to back in one frame and the four
# draws are a pure function of the seed just written. Nothing that yields may go between them - a
# `playse` would break it silently. docs/rng.md.

SCR_SETWILDBATTLE = 0xB6
SCR_DOWILDBATTLE = 0xB7
SCR_RELEASEALL = 0x6B

SCR_GOTO = 0x05
SCR_SETVAR = 0x16
VAR_0x8000 = 0x8000

# A RAM SCRIPT MAY NOT COME BACK FROM A BATTLE, and nothing placed after `dowildbattle` can be
# relied on. CB2_InitBattle and InitOverworldBgs both call MoveSaveBlocks_ResetHeap
# [decomp:src/battle_main.c:614, src/overworld.c:1337], which re-rolls gSaveBlock1's address by a
# multiple of 4 in 0..124 [src/load_save.c:75]; the engine keeps its pointer INTO that block
# [GetRamScript, src/script.c:514] and so resumes where the script no longer is. One mechanism,
# three symptoms: mev11's stray second battle, mev15/mev16 walking away clean, and mev18 freezing
# the overworld dead. `releaseall` + `end` was never a fix - those bytes are simply not at the
# address the engine returns to.
#
# The fix is to start the battle from outside the save block. `goto` (0x05) takes an absolute
# address and gSpecialVar_0x8000 is a fixed EWRAM u16 [rom_map, bs57] that `setvar` (0x16) writes:
#
#     setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02   =   dowildbattle ; end
#     goto   0x020370B4
#
# ScriptContext_RunScript calls UnlockPlayerFieldControls() the moment a script stops
# [decomp:src/script.c:335], so the `end` alone gives the player back. Nothing in the battle or
# overworld code writes gSpecialVar_0x8000. docs/rng.md.
BATTLE_TAIL = bytes([SCR_RELEASEALL, SCR_END])      # kept for the disassemblers only

# The two bytes the trampoline holds, as the u16 `setvar` writes: dowildbattle, then end.
TRAMPOLINE_ADDRESS = rom_map.G_SPECIAL_VAR_0X8000
TRAMPOLINE_WORD = SCR_DOWILDBATTLE | (SCR_END << 8)


def battle_and_exit(species, level, item=0, *, trampoline=None):
    """-> setwildbattle, then the battle itself from an address the save block cannot move.

    Every builder that starts a wild battle from a RAM script ends this way, and the reason is
    the block above: bytes written after `dowildbattle` are not where the engine comes back to.
    """
    species, level, item = int(species), int(level), int(item)
    if not 1 <= species <= MAX_SPECIES:
        raise RngScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise RngScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise RngScriptError(f"item is a u16, got {item}")
    address = TRAMPOLINE_ADDRESS if trampoline is None else int(trampoline)
    if address % 2:
        raise RngScriptError(f"0x{address:X} is not a u16 a var command can write")
    return (bytes([SCR_SETWILDBATTLE]) + species.to_bytes(2, "little")
            + bytes([level]) + item.to_bytes(2, "little")
            + bytes([SCR_SETVAR]) + VAR_0x8000.to_bytes(2, "little")
            + TRAMPOLINE_WORD.to_bytes(2, "little")
            + bytes([SCR_GOTO]) + address.to_bytes(4, "little"))

MAX_SPECIES = 411           # the internal table's last entry
MAX_LEVEL = 100


def build_wild_battle_script(seed, species, level, item=0, address=None):
    """Set gRngValue, then have the ROM roll a wild Pokemon from it and start the battle.

    The four draws that follow the seed are exactly PID-low, PID-high, IV word 1, IV word 2, so the
    mon is decided in advance - species, level, shininess, nature, ability, gender and all six IVs.
    Use `frlgsim.lcg.draws(seed, 4)` to say what it will be, and check it rather than trusting it.
    """
    address = rom_map.GRNG_VALUE if address is None else int(address)
    species, level, item = int(species), int(level), int(item)
    if not 1 <= species <= MAX_SPECIES:
        raise RngScriptError(f"species is 1..{MAX_SPECIES}, got {species}")
    if not 1 <= level <= MAX_LEVEL:
        raise RngScriptError(f"level is 1..{MAX_LEVEL}, got {level}")
    if not 0 <= item <= 0xFFFF:
        raise RngScriptError(f"item is a u16, got {item}")
    body = build_seed_script(seed, address=address, sound=None)
    if body[-1] != SCR_END:
        raise RngScriptError("the seed script must end with end (0x02)")
    body = body[:-1]                                    # the battle replaces the end
    body += battle_and_exit(species, level, item)       # ...and it ends OUT of the save block
    if len(body) > MAX_RAM_SCRIPT_SIZE:
        raise RngScriptError(f"{len(body)} bytes will not fit in {MAX_RAM_SCRIPT_SIZE}")
    return body


def predict_wild_mon(seed, tid, sid):
    """-> {personality, ivs, shiny, ...}: what build_wild_battle_script's four draws will make.

    BOTH personality half-orders are reported, because `Random32()` is `Random() | (Random() << 16)`
    and C does not order the operands of `|` - the three mons bs51/bs52 recovered all read
    low-half-first, but that was CreateMonWithNature's call site, and this is CreateBoxMon's.
    It matters less than it looks: the shiny test is TID ^ SID ^ PIDhigh ^ PIDlow, which is
    SYMMETRIC under swapping the halves, and the IVs come from the two draws after. So shininess
    and every IV are the same either way, and only the nature, ability and gender differ.
    """
    from . import lcg
    (first, second, third, fourth), _ = lcg.draws(int(seed), 4)
    ivs = (third & 31, (third >> 5) & 31, (third >> 10) & 31,
           fourth & 31, (fourth >> 5) & 31, (fourth >> 10) & 31)
    out = {"ivs": ivs, "iv_total": sum(ivs), "draws": (first, second, third, fourth)}
    for name, personality in (("low_first", first | (second << 16)),
                              ("high_first", second | (first << 16))):
        value = (int(tid) ^ int(sid) ^ (personality >> 16) ^ (personality & 0xFFFF))
        out[name] = {"personality": personality, "shiny_value": value, "shiny": value < 8,
                     "nature": personality % 25, "ability_num": personality & 1}
    out["shiny"] = out["low_first"]["shiny"]
    assert out["shiny"] == out["high_first"]["shiny"], "the shiny test is symmetric in the halves"
    return out


# --- reading the seed back out, which is the other half ------------------------------------------
# Writing gRngValue was always the easy direction. READING it in the overworld is what a countdown
# needs, and it was blocked for two sessions on one unknown: the absolute address of
# gSpecialVar_0x8000, because `copybyte` needs a destination ADDRESS while `buffernumberstring` only
# needs a var ID. bs57 found it at 0x020370B4 by searching the cartridge for the SHAPE of
# gSpecialVars (frlgsim/buffer_script.py, `table-scan`).
#
# The script is `gift_composer.build_seed_read_script`; it lives there because that is where the
# field-script builder and its relocatable-text machinery are. It READS gRngValue and writes
# nothing.

from .gift_composer import build_seed_read_script     # noqa: E402,F401  (re-exported here)


def seed_from_printed(low, high):
    """-> gRngValue, from the two decimal numbers the NPC prints.

    gRngValue is a u32 at 0x03004220, little-endian, so its bytes 0..1 are the LOW half and 2..3
    the HIGH half. The script copies them into gSpecialVar_0x8000 and 0x8001 in that order, and
    prints 0x8000 as STR_VAR_1 and 0x8001 as STR_VAR_2 - so the screen reads "RNG HI <high>" and
    "RNG LO <low>".
    """
    low, high = int(low), int(high)
    for name, value in (("low", low), ("high", high)):
        if not 0 <= value <= 0xFFFF:
            raise RngScriptError(f"the {name} half is a u16 the console printed, got {value}")
    return (high << 16) | low


def check_two_readings(first, second, *, seconds=None):
    """-> lines: what two readings of the NPC say, and whether they can both be gRngValue.

    THIS IS THE PROOF THAT THE ADDRESS IS RIGHT, and it needs no extra hardware run. Two readings
    of a real gRngValue are related by the LCG: the second is some number of turns after the first,
    and `lcg.distance` finds that number exactly. A distance ALWAYS exists - the map is a
    permutation of all 2**32 states - so the distance alone proves nothing. What proves it is the
    distance being SMALL and consistent with the time between the readings: the RNG advances on the
    order of 10**2 turns a second, so seconds apart means a distance of thousands, not billions.
    A wrong address prints two unrelated numbers, whose distance is ~2**31 on average.

    `seconds` is optional and deliberately not required: it sharpens the statement, it does not
    make it. The order-of-magnitude test stands without any clock, which is the point - see
    docs/rng.md on why nothing here may depend on a hand-timed elapsed.
    """
    from . import lcg
    turns = lcg.distance(first, second)
    lines = [f"reading 1  0x{first:08X}",
             f"reading 2  0x{second:08X}",
             f"distance   {turns:,} turns"]
    # A uniformly random pair sits ~2**31 apart; anything a human waited through is far below it.
    plausible = turns < 10 ** 7
    if seconds is not None:
        lines.append(f"           = {turns / float(seconds):,.0f} turns/second over the "
                     f"{seconds} s between them")
    lines.append(
        "  => CONSISTENT with two readings of a live gRngValue: the second is a short walk "
        "along the orbit from the first."
        if plausible else
        "  => NOT consistent: 0x%08X and 0x%08X are ~2**31 apart, which is what two UNRELATED "
        "numbers look like. The address is wrong, or the read tore." % (first, second))
    lines.append(f"  (a distance always exists; this one is 1 in {2 ** 32 // max(turns, 1):,})")
    return lines


from .gift_composer import build_seed_rate_script      # noqa: E402,F401  (re-exported here)


def measure_rate(first, second, frames):
    """-> lines: turns per frame, from two readings and an EXACT frame count.

    This is the measurement docs/rng.md says had never been made outside the Mystery Gift menu.
    Both inputs are exact - `lcg.distance` is exact arithmetic and `frames` is what `delay` was
    told to wait - so unlike every earlier attempt there is no clock in it and no rounding to argue
    about. 600 frames at ~2 turns each is ~1200 turns, twenty million times below the 2**32 point
    where the distance would stop being unique, so the answer is not an alias.

    It says nothing about the rate while the player is WALKING. It is the rate while a field script
    is delaying, which is a different situation and the one that matters for a script that waits
    for a target state.
    """
    from . import lcg
    frames = int(frames)
    if frames <= 0:
        raise RngScriptError(f"frames must be positive, got {frames}")
    turns = lcg.distance(first, second)
    per_frame = turns / frames
    lines = [f"before  0x{first:08X}",
             f"after   0x{second:08X}  ({frames} frames later, exactly)",
             f"turns   {turns:,}",
             f"rate    {per_frame:.6f} turns/frame"]
    exact = turns % frames == 0
    if exact:
        lines.append(f"        = EXACTLY {turns // frames} per frame, on every frame of the wait")
    remainder = turns - 2 * frames
    lines.append(f"        vs 2/frame: {remainder:+,} turns over {frames} frames"
                 + (" - the link menu's rate holds here too" if remainder == 0 else ""))
    lines.append(f"        (~{per_frame * 59.7275:,.1f} turns/second at 59.7275 Hz - commentary,"
                 " not data: no clock was used)")
    return lines
