"""A field script that sets gRngValue in the OVERWORLD, where our native code cannot reach.

bs50 seeded the RNG during a Mystery Gift link and bs51 proved it never got out: the encounter was
1,898,278,119 turns from the value we set. The reason is not timing and not a bug - it is the menu
structure. Backing out of Mystery Gift runs
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` -> `CB2_InitTitleScreen`
[decomp:src/mystery_gift_menu.c:463], which calls `StartTimer1` [src/title_screen.c:351], and
pressing START then re-runs `SeedRng(REG_TM1CNT_L)` [:735]. THERE IS NO ROUTE FROM MYSTERY GIFT TO
THE OVERWORLD THAT DOES NOT RESEED, so the link is the wrong place to do it from.

A RAM SCRIPT IS THE RIGHT PLACE, because it runs in the overworld, after the reseed.
`initramscript` binds a field script to a map object (proven on hardware, mev03), `GetRamScript`
hands the saved body to the ordinary field engine when the player interacts [decomp:src/script.c],
and the field engine has a command that writes memory:

    bool8 ScrCmd_setptr(struct ScriptContext * ctx)      // opcode 0x11
    {
        u8 value = ScriptReadByte(ctx);
        *(u8 *)ScriptReadWord(ctx) = value;
    }
[decomp:src/scrcmd.c:300]

An immediate BYTE and an absolute ADDRESS, both read straight out of the script. Four of them set
`gRngValue` to anything we like.

WHY THIS AND NOT `callnative`. `ScrCmd_callnative` (opcode 0x23) calls a function pointer out of
the script, which would be native code in the overworld and strictly more powerful. It is also
strictly harder to aim: our code would live in `gSaveBlock1Ptr->ramScript.data.script`, and
gSaveBlock1Ptr carries a random 4-aligned offset re-rolled on every battle and load
[SetSaveBlocksPointers, decomp:src/load_save.c:75] - bs45 and bs46 measured it moving 76 bytes
between two runs minutes apart. Aiming at a moving target needs the address read first and a sled
to absorb what is left. `setptr` needs neither, because **gRngValue is not in the save**: it is a
link-time IWRAM global at 0x03004220, read out of Random's own literal pool in bs14, and it does
not move. The weaker command is the one that fits the target. Keep callnative for something that
actually needs it.

THE SCRIPT ENDS WITH `end` (0x02), NOT `endram` (0x0d). `ScrCmd_endram` calls ClearRamScript
[decomp:src/scrcmd.c:262]; `ScrCmd_end` does not. So the binding SURVIVES, and the player can
re-trigger it by talking to the object again - one Mystery Gift session, then as many reseeds as
the experiment needs. That matters because a RAM script and a Wonder Card are mutually exclusive
(one slot, confirmed mev03-mev06), so installing one is not free.
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


# --- the RNG owned: seed it and generate the mon in the SAME frame -------------------------------
# Seeding alone still leaves the player walking, and the overworld turns the RNG ~148 times a second
# (measured E1->E2, bs52: 18900 turns over 128.0 s), so no human and no network can aim at a
# particular draw. The fix is not better timing - it is to remove the interval entirely.
#
#   bool8 ScrCmd_setwildbattle(struct ScriptContext * ctx)      // opcode 0xB6
#   {
#       u16 species = ScriptReadHalfword(ctx);
#       u8 level = ScriptReadByte(ctx);
#       u16 item = ScriptReadHalfword(ctx);
#       CreateScriptedWildMon(species, level, item);
#   }
# [decomp:src/scrcmd.c:1935], and CreateScriptedWildMon is
#   CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0);
# [decomp:src/script_pokemon_util.c:128] - fixedIV 32 is USE_RANDOM_IVS and hasFixedPersonality 0,
# so the PID and the IVs are rolled RIGHT THERE, in four draws, with NO nature rejection loop (that
# lives in CreateMonWithNature, which only the real encounter path uses). Species and level are
# operands we write.
#
# WHY THERE IS NO DRIFT, AND IT IS THE WHOLE POINT: `setptr` and `setwildbattle` both return FALSE,
# and the field engine runs commands in a loop until one returns TRUE. So all four setptrs and the
# generation happen BACK TO BACK IN ONE FRAME with nothing in between - not a frame boundary, not
# the per-frame consumer, nothing. The four draws are a pure function of the seed we just wrote.
#
# So NOTHING may be put between them that yields. `playse`/`waitse` would; the battle starting is
# the feedback instead.

SCR_SETWILDBATTLE = 0xB6
SCR_DOWILDBATTLE = 0xB7

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
    body += (bytes([SCR_SETWILDBATTLE]) + species.to_bytes(2, "little")
             + bytes([level]) + item.to_bytes(2, "little"))
    body += bytes([SCR_DOWILDBATTLE])                   # this one yields, and stops the script
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
