"""Addresses in the ROM the console actually runs, established by reading them off it.

The console runs the FRENCH FireRed Switch build - game code `BPRF`, software version 0x0A, read out
of the cartridge header at 0x080000A0 in bs07. The pret decomp has a `firered_switch` target at
GAME_REVISION=10, but it matches the ENGLISH rev-10 ROM, so its addresses cannot be assumed to be
these. Everything here was measured on hardware or read out of code that was.

How each one was obtained, because that is what makes it trustworthy:

- `anchors` (bs08) returned `lr`, which Client_RunBufferScript's own `bl` had set: the instruction
  after the call, at 0x08148C74. One absolute ROM address, from the CPU.
- A `memory-dump` around it (bs11) disassembles as Client_RunBufferScript exactly as
  [decomp:src/mystery_gift_client.c:274] writes it - `adds r0,r4,#4` for &client->param, two
  `ldr`s through pointers for the save blocks, `cmp r0,#1` at the anchor - and its THUMB literal
  pool holds gDecompressionBuffer and the addresses of the two save-block pointers.
- MysteryGiftClient_CallFunc, right after it, copies an eight-entry table onto the stack and indexes
  it by `client->funcId`, which names sClientFuncs and where it is.
- A `memory-dump` of that table (bs12) returned eight THUMB pointers, and every one of them lands on
  a `push {r4, lr}` in bs11's disassembly. Entry 7 is 0x08148C61 - the function bs08 measured from
  the other end. Three runs, three routes, one answer.

Nothing here is inferred from the English build. A symbol that has not been read off the console does
not belong in this file.
"""

# The build these belong to. A dump of the cartridge header that does not read this back is a
# different console or a different game, and none of the addresses below apply to it.
GAME_CODE = b"BPRF"          # B-PR-F: Pokemon FireRed, French
SOFTWARE_VERSION = 0x0A      # the decomp's REVISION >= 0xA branches are the ones running
GAME_TITLE = b"POKEMON FIRE"
ROM_HEADER_TITLE = 0x080000A0
ROM_HEADER_GAME_CODE = 0x080000AC
ROM_HEADER_VERSION = 0x080000BC

# --- src/mystery_gift_client.c ----------------------------------------------------------------
# sClientFuncs, indexed by client->funcId [enum FUNC_INIT..FUNC_RUN_BUFFER]. Read out in bs12.
S_CLIENT_FUNCS = 0x0845DBD0
CLIENT_FUNCS = (
    ("Client_Init", 0x081489D8),
    ("Client_Done", 0x08148A00),
    ("Client_Recv", 0x08148A04),
    ("Client_Send", 0x08148A24),
    ("Client_Run", 0x08148A44),
    ("Client_Wait", 0x08148C10),
    ("Client_RunMysteryEventScript", 0x08148C28),
    ("Client_RunBufferScript", 0x08148C60),
)
CLIENT_RUN_BUFFER_SCRIPT = 0x08148C60
# The instruction after `bl _call_via_r3` in Client_RunBufferScript: where our payload's lr points,
# and the first address this project ever had inside the ROM (bs08).
CLIENT_RUN_BUFFER_SCRIPT_RETURN = 0x08148C74
MYSTERY_GIFT_CLIENT_CALL_FUNC = 0x08148C94

# --- src/mystery_gift_server.c ------------------------------------------------------------------
# sFuncTable, indexed by svr->funcId [enum FUNC_INIT..FUNC_RUN, five entries]. It sits immediately
# after sClientFuncs and bs12's dump caught it whole. The names are matched to the decomp by what the
# code does, not by position alone: 0x08148DF0 is `movs r1,#4; str r1,[r0,#8]; movs r0,#0; bx lr`,
# which is Server_Init's `svr->funcId = FUNC_RUN; return SVR_RET_INIT` with FUNC_RUN 4 and
# SVR_RET_INIT 0, and 0x08148DF8 is `movs r0,#3; bx lr`, Server_Done returning SVR_RET_END = 3
# [decomp:include/mystery_gift_server.h:10-13]. Both constants are what this repo already used.
S_SERVER_FUNCS = 0x0845DBF0
SERVER_FUNCS = (
    ("Server_Init", 0x08148DF0),
    ("Server_Done", 0x08148DF8),
    ("Server_Recv", 0x08148DFC),
    ("Server_Send", 0x08148E18),
    ("Server_Run", 0x08148E34),
)

# --- src/mystery_gift_link.c ------------------------------------------------------------------
# `return link->recvFunc(link)` and `return link->sendFunc(link)`, twelve bytes apart, called by
# Client_Recv and Client_Send respectively (bs11).
MYSTERY_GIFT_LINK_RECV = 0x081485E8
MYSTERY_GIFT_LINK_SEND = 0x081485F4

# --- gcc's THUMB-to-ARM call veneers ------------------------------------------------------------
# Client_RunBufferScript reaches our ARM payload through one of these, which is why lr comes back
# pointing into the caller rather than into the veneer.
CALL_VIA_R1 = 0x081E2228
CALL_VIA_R3 = 0x081E2230

# --- variables ----------------------------------------------------------------------------------
# gDecompressionBuffer, where CLI_RUN_BUFFER_SCRIPT copies our 1024 bytes and calls them. Deduced
# from ld_script.ld, then MEASURED twice: `anchors` read it from pc (bs08), and it is the first word
# of Client_RunBufferScript's literal pool (bs11).
GDECOMPRESSION_BUFFER = 0x0201C000
# The pointer variables in IWRAM, not the blocks they point at. Their VALUES move per save load; on
# GURVAN's console in bs08 they were 0x02024598 and 0x0202553C.
GSAVEBLOCK2PTR = 0x0300422C
GSAVEBLOCK1PTR = 0x03004228


def client_func(name):
    """-> the ROM address of one sClientFuncs or sFuncTable entry, by name."""
    for entry, address in CLIENT_FUNCS + SERVER_FUNCS:
        if entry == name:
            return address
    raise KeyError(f"{name!r} is not in sClientFuncs or sFuncTable; known: "
                   + ", ".join(n for n, _ in CLIENT_FUNCS + SERVER_FUNCS))


def thumb(address):
    """A THUMB function pointer as the table stores it, and as a `bx` needs it."""
    return address | 1


def describe_header(dump, offset=0):
    """-> lines describing a dump that starts at 0x08000000, and whether it is the build above."""
    title = bytes(dump[0xA0 - offset:0xAC - offset])
    code = bytes(dump[0xAC - offset:0xB0 - offset])
    version = dump[0xBC - offset]
    checksum = dump[0xBD - offset]
    computed = 0
    for byte in dump[0xA0 - offset:0xBD - offset]:
        computed = (computed - byte) & 0xFF
    computed = (computed - 0x19) & 0xFF
    return [
        f"title      {title!r}",
        f"game code  {code!r}",
        f"version    0x{version:02X}",
        f"header checksum 0x{checksum:02X}, recomputed 0x{computed:02X} -> "
        + ("VALID" if computed == checksum else "MISMATCH: this is not a whole header"),
        ("-> the build rom_map.py describes" if (code, version) == (GAME_CODE, SOFTWARE_VERSION)
         else f"-> NOT the build rom_map.py describes ({GAME_CODE!r} version "
              f"0x{SOFTWARE_VERSION:02X}); none of its addresses apply"),
    ]


def read_client_funcs(dump):
    """-> [(name, address, thumb_bit)] for a dump of S_CLIENT_FUNCS."""
    out = []
    for i, (name, _known) in enumerate(CLIENT_FUNCS):
        value = int.from_bytes(bytes(dump[4 * i:4 * i + 4]), "little")
        out.append((name, value & ~1, bool(value & 1)))
    return out
