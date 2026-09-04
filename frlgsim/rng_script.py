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
