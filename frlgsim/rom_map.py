"""Addresses in the ROM the console actually runs, each read off it.

The console runs the FRENCH FireRed Switch build, game code `BPRF`, software version 0x0A, read out
of the cartridge header in bs07. The pret decomp's `firered_switch` target is GAME_REVISION=10 but
matches the ENGLISH rev-10 ROM, so its addresses are never assumed here. A symbol that has not been
read off the console does not belong in this file, and every entry carries the run that measured it.

How each address was obtained is in docs/buffer_script.md (the payloads and the runs),
docs/species_table.md (gSpeciesInfo and CreateMon) and docs/leafgreen.md (the second cartridge).
"""

GAME_CODE = b"BPRF"          # B-PR-F: Pokemon FireRed, French
SOFTWARE_VERSION = 0x0A      # the decomp's REVISION >= 0xA branches are the ones running
GAME_TITLE = b"POKEMON FIRE"
ROM_HEADER_TITLE = 0x080000A0
ROM_HEADER_GAME_CODE = 0x080000AC
ROM_HEADER_VERSION = 0x080000BC

# --- src/mystery_gift_client.c ----------------------------------------------------------------
# sClientFuncs, indexed by client->funcId, dumped whole in bs12.
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
# Where our payload's lr points: the instruction after `bl _call_via_r3` (bs08, bs11).
CLIENT_RUN_BUFFER_SCRIPT_RETURN = 0x08148C74
MYSTERY_GIFT_CLIENT_CALL_FUNC = 0x08148C94

# --- src/mystery_gift_server.c ------------------------------------------------------------------
# sFuncTable, immediately after sClientFuncs in bs12's dump. Named by what each function does, not
# by position: 0x08148DF0 is Server_Init's `funcId = FUNC_RUN; return SVR_RET_INIT` and 0x08148DF8
# is Server_Done returning SVR_RET_END = 3.
S_SERVER_FUNCS = 0x0845DBF0
SERVER_FUNCS = (
    ("Server_Init", 0x08148DF0),
    ("Server_Done", 0x08148DF8),
    ("Server_Recv", 0x08148DFC),
    ("Server_Send", 0x08148E18),
    ("Server_Run", 0x08148E34),
)

# --- src/mystery_gift_link.c ------------------------------------------------------------------
# `return link->recvFunc(link)` and `return link->sendFunc(link)`, called by Client_Recv and
# Client_Send (bs11).
MYSTERY_GIFT_LINK_RECV = 0x081485E8
MYSTERY_GIFT_LINK_SEND = 0x081485F4

# --- src/random.c ---------------------------------------------------------------------------------
# bs13 scanned for RAND_MULT, bs14 disassembled the lowest hit, bs15 called it 96 times and checked
# the LCG recurrence either side of every call.
RANDOM = 0x080486B0                 # u16 Random(void)
SEED_RNG = 0x080486D0               # void SeedRng(u16), whose pool names gRngValue a second time

# --- src/event_data.c and data/event_scripts.s ----------------------------------------------------
# Found by shape, not by value: gSpecialVars entries 0..11 point at twelve consecutive u16s, so each
# word is +2 on the last. bs57 found exactly one such run in 2.75 MB, and its first value is the
# answer. gSpecialVar_0x8000 may be hardcoded because it is EWRAM_DATA, a link-time global; a
# save-block address may not (see SAVEBLOCK_MOVE_RANGE below).
G_SPECIAL_VARS = 0x081639A8         # u16 *const gSpecialVars[21], by var id
G_SPECIAL_VAR_0X8000 = 0x020370B4   # the first entry, read out of the table by the same run
# UNCONFIRMED: only entry 0 was read. The rest follow from event_data.c's declaration order, which
# is not the table's order; a dump of G_SPECIAL_VARS settles them.
G_SPECIAL_VAR_0X8001 = G_SPECIAL_VAR_0X8000 + 2

# --- src/pokemon.c --------------------------------------------------------------------------------
# gSpeciesInfo, found by a content fingerprint (bs38) and confirmed by reading it (bs39, 34/34
# entries byte-identical to the decomp). The three all-100 species give a word at entry offset 0
# AND 2, so one of the two is word-aligned whatever the stride - which matters because memory-scan
# reads with `ldmia` and only sees word-aligned matches. The gaps between the hits measured the
# stride at 28.
GSPECIES_INFO = 0x0824CDFC
SPECIES_INFO_STRIDE = 28            # the decomp's struct is 26 bytes; the ROM pads it to 28
SPECIES_INFO_SLOTS = 412            # NUM_SPECIES, SPECIES_EGG included
SPECIES_INFO_ALL_100 = (151, 251, 409)                       # Mew, Celebi, Jirachi
BS38_SPECIES_INFO_HITS = (0x0824DE80, 0x0824E970, 0x0824FAB8)

# Found by scanning for GSPECIES_INFO itself (bs40) and disassembling where the hits landed (bs41
# refuted the first guess at the object boundary, bs42 confirmed the second). CreateMon is
# identified instruction for instruction against [decomp:src/pokemon.c:1755], and by calling
# SetMonData with MON_DATA_LEVEL then MON_DATA_MAIL carrying MAIL_NONE.
CREATE_MON = 0x08041150             # void CreateMon(mon, species, level, fixedIV,
                                    #   hasFixedPersonality, fixedPersonality, otIdType, fixedOtId)
                                    # args 5..8 go on the stack; the first four are r0..r3
CREATE_BOX_MON = 0x080411C0         # the same signature on a struct BoxPokemon
ZERO_MON_DATA = 0x08041090          # CreateMon's first call
SET_MON_DATA = 0x08043A78           # SetMonData(mon, field, &value)
CALCULATE_MON_STATS = 0x08041B78    # CreateMon's last call

# Read out of the mon CreateMon built in bs44: globals no link message carries.
GGAME_LANGUAGE = 3                  # LANGUAGE_FRENCH [decomp:include/constants/global.h:22]
GGAME_VERSION = 4                   # VERSION_FIRE_RED [:11]
# CreateBoxMon copies the nickname from the FRENCH gSpeciesNames [decomp:src/pokemon.c:1810], so one
# species a run is readable this way. bs06's party dump had read the same name by another route.
SPECIES_NAMES_READ = {59: "ARCANIN"}

# --- read off the console but NOT confirmed by disassembling the function itself -----------------
# Named by call count and by the shape of the access, which is weaker than the entries above. Kept
# apart so nothing downstream mistakes them for measurements.
PROBABLE = (
    # CreateBoxMon calls one function 20 times, which is what SetBoxMonData does there.
    ("SetBoxMonData", 0x08043BCC),
    # Indexed by move id at a 12-byte stride, offset 1 compared against zero: struct BattleMove's
    # `power` [decomp:include/pokemon.h]. Read in bs41.
    ("gBattleMoves", 0x0824927C),
    # bs41: called with TRUE immediately before `Random() % 3` [battle_ai_switch_items.c:88].
    ("HasSuperEffectiveMoveAgainstOpponents", 0x0803CD94),
)

# --- gcc's THUMB-to-ARM call veneers ------------------------------------------------------------
# Client_RunBufferScript reaches our ARM payload through one of these, which is why lr comes back
# pointing into the caller rather than into the veneer.
CALL_VIA_R1 = 0x081E2228
CALL_VIA_R3 = 0x081E2230

# --- variables ----------------------------------------------------------------------------------
# Where CLI_RUN_BUFFER_SCRIPT copies our 1024 bytes and calls them. Deduced from ld_script.ld, then
# measured twice: `anchors` read it from pc (bs08), and it is the first word of
# Client_RunBufferScript's literal pool (bs11).
GDECOMPRESSION_BUFFER = 0x0201C000

# The pointer variables in IWRAM, not the blocks they point at. SetSaveBlocksPointers re-rolls a
# random 4-aligned offset in 0..124 on every battle and every load [decomp:src/load_save.c:75];
# bs45 and bs46 measured the blocks moving 76 bytes six minutes apart with no reboot.
#
# THE RULE: an absolute address into a save block is valid only until the next battle or load. Never
# carry one between runs - compute from the r1/r2 the console hands the payload every call, as
# save-dump, save-write and --create-mon-append all do.
SAVEBLOCK_MOVE_RANGE = 128          # [decomp:src/load_save.c:15]
SAVEBLOCK_MOVE_MASK = (SAVEBLOCK_MOVE_RANGE - 1) & ~3        # 0x7C: 0..124 in steps of 4
GSAVEBLOCK1_SEEN = (0x0202553C, 0x0202559C, 0x02025550)      # bs08, bs45, bs46
GSAVEBLOCK2PTR = 0x0300422C
GSAVEBLOCK1PTR = 0x03004228

# The party the game plays with. `gSaveBlock1Ptr->playerParty` is NOT this: SavePlayerParty copies
# gPlayerParty into it when the console saves [decomp:src/load_save.c:160], so a write there is
# erased by the console's own save (bs46). These are ordinary EWRAM globals fixed at link time, so
# unlike the save blocks they do not move. bs47 found them by finding a Pokemon - the one 4-aligned
# window of a dump that decoded with a valid checksum.
GPLAYER_PARTY = 0x02024280          # struct Pokemon[6]
GPLAYER_PARTY_COUNT = 0x02024025    # u8
GENEMY_PARTY = 0x02024028           # struct Pokemon[6], 600 bytes below gPlayerParty

# The seed every random outcome in the game comes out of. Read out of Random's and SeedRng's literal
# pools (bs14) and confirmed by its own recurrence (bs15). docs/rng.md.
GRNG_VALUE = 0x03004220
GAME_RANDOM_CALLS_PER_FRAME_AT_MG_MENU = 2


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


# --- LeafGreen: a separate table, measured separately ---------------------------------------------
# The second console is FRENCH LEAFGREEN, BPGF 0x0A (lg163 read the header). Every RAM address
# measured so far is the same as FireRed's and every ROM address above 0x080486C8 differs, because
# two builds of the same game diverge where their data does and the divergence grows along the link
# order. An address read low in the ROM therefore says nothing about one read high in it.
#
# THE RULE: an address is LeafGreen's only when it was measured ON LEAFGREEN. docs/leafgreen.md has
# each run and what it read.
LEAFGREEN_GAME_CODE = b"BPGF"       # lg163, off the cartridge; FireRed is BPRF
LEAFGREEN_SOFTWARE_VERSION = 0x0A   # lg163; the same Switch revision as FireRed
LEAFGREEN = {
    # symbol: (address, the run that measured it)
    "gDecompressionBuffer": (0x0201C000, "lg160"),
    "mystery_gift_call_site": (0x08148C50, "lg160"),   # FireRed 0x08148C74, so -0x24
    "Random": (0x080486B0, "lg162"),
    "SeedRng": (0x080486D0, "lg162"),
    "gRngValue": (0x03004220, "lg162"),                # named twice, two independent pools
    "gPlayerParty": (0x02024280, "lg164"),             # found by finding a Pokemon, as bs47 did
    "gPlayerPartyCount": (0x02024025, "lg164"),
    "gEnemyParty": (0x02024028, "lg164"),              # 600 bytes below [src/pokemon.c:61-62]
    "gSpeciesInfo": (0x0824CDD8, "lg165"),             # FireRed 0x0824CDFC, so -0x24
    "CreateMon": (0x08041150, "lg166"),                # same as FireRed: below the split
    "sEasyChatGroups": (0x083E353C, "lg168/lg169"),    # FireRed 0x083E3700, so -0x1C4
    "gSpecialVar_0x8000": (0x020370B4, "lg171"),       # same as FireRed
    "gSpecialVars": (0x08163984, "lg171"),             # FireRed 0x081639A8, so -0x24
    "gSaveBlock1Ptr": (0x03004228, "lg175"),           # same as FireRed
    "gSaveBlock2Ptr": (0x0300422C, "lg175"),           # same as FireRed
}

# The ROM delta is a property of a REGION, not of the ROM. lg161 and bs13 each scanned their console
# for RAND_MULT and got eleven hits in the same order, so the pairs give the delta at eleven points
# across 1.3 MB for no hardware run at all. There are at least three boundaries; lg167 carried -0x24
# upward on faith and found nothing, which is what exposed them.
LEAFGREEN_DELTA_SEGMENTS = (
    # (low, high, delta, evidence): the delta is measured at both ends of each span
    (0x08000000, 0x080486C8, 0x00, "lg162/lg166 and the lg161-vs-bs13 pairing"),
    (0x0807D238, 0x080AFC00, -0x2C, "lg161 vs bs13, 4 paired hits"),
    (0x080F1EA0, 0x08122518, -0x28, "lg161 vs bs13, 5 paired hits"),
    (0x08148C74, 0x0824CDFC, -0x24, "lg160 at 0x08148C74, lg161-vs-bs13 at 0x0814CBFC, lg165"),
    (0x083DE528, 0x083E3700, -0x1C4, "lg169: 18 word-list pointers and the table, all -0x1C4"),
)

def leafgreen_guess(firered_address):
    """-> where `firered_address` probably is on LeafGreen. A place to point a dump, not an answer.

    Only the measured segments answer; the gaps refuse rather than interpolate, because a boundary is
    known to be in there and its position is not. The delta says nothing about content either: a
    table can sit exactly where predicted and hold different data.
    """
    address = int(firered_address)
    for low, high, delta, _evidence in LEAFGREEN_DELTA_SEGMENTS:
        if low <= address <= high:
            return address + delta
    raise ValueError(
        f"0x{address:X} falls in a gap between measured segments, where a boundary is known to "
        "exist and its position is not. Point a dump at it and measure.")


def leafgreen(symbol):
    """-> the LeafGreen address of `symbol`, or raise. Never falls back to the FireRed table."""
    try:
        return LEAFGREEN[symbol][0]
    except KeyError:
        raise KeyError(
            f"{symbol!r} has not been measured on LeafGreen; have {sorted(LEAFGREEN)}. "
            "Do not substitute the FireRed value: the two builds differ at three or more points "
            "between 0x080486C8 and 0x0814CBFC (LEAFGREEN_DELTA_SEGMENTS).") from None
