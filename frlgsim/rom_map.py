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
- `memory-scan` (bs13) SEARCHED 4 MB of the cartridge for RAND_MULT, which no ARM or THUMB
  instruction can encode, so every use of the game's LCG has it in a literal pool. Eleven hits; the
  decomp's link order puts src/random.o (#86 in ld_script.ld) before every other user of the macro
  (the next is src/title_screen.o at #123), so the LOWEST hit is Random's pool.
- A `memory-dump` there (bs14) disassembles as Random and SeedRng exactly as [decomp:src/random.c]
  writes them, and their pools name gRngValue - twice, from two independent functions.
- `rng-trace` (bs15) then CALLED Random 96 times, one frame apart, reading gRngValue either side of
  each call: `after == before * RAND_MULT + RAND_ADD` held 96 out of 96. That is the address, the
  ROM call and the identity of the function, checked by the LCG's own arithmetic - and the first
  time this project has called into the console's ROM at all.

- `memory-scan` again (bs38) found gSpeciesInfo by a CONTENT fingerprint - three species whose
  base stats are all 100, giving one word at two entry offsets so that it is visible whatever the
  stride - and the gaps between the three hits MEASURED the entry stride at 28. bs39 dumped the
  table: 34 of 34 entries byte-identical to the decomp's data. bs37, the run before, scanned the
  whole 16 MB for a needle built on a 26-byte stride and found nothing, which is what put the
  layout in question in the first place.
- `memory-scan` on that address (bs40) found every function carrying &gSpeciesInfo in its literal
  pool, and dumps at two of them (bs41, bs42) disassemble as src/battle_ai_switch_items.c and as
  CreateMon/CreateBoxMon. bs41 REFUTED the first guess at the object boundary; bs42 confirmed the
  second.

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

# --- src/random.c ---------------------------------------------------------------------------------
# Found by SEARCH, not by luck: bs13 scanned for RAND_MULT, bs14 dumped the lowest hit. The
# disassembly is byte for byte src/random.c:11 -
#   4A04 ldr r2,[pc,#16] -> &gRngValue   6811 ldr r1,[r2]      4804 ldr r0,[pc,#16] -> RAND_MULT
#   4348 mul r0,r1       4904 ldr r1,[pc,#16] -> 24691         1840 add r0,r0,r1
#   6010 str r0,[r2]     0C00 lsr r0,r0,#16                    4770 bx lr
# CALLED on hardware in bs15, 96 times, with the recurrence checked either side of every call.
RANDOM = 0x080486B0                 # u16 Random(void)
SEED_RNG = 0x080486D0               # void SeedRng(u16), whose pool names gRngValue a second time

# --- src/event_data.c and data/event_scripts.s ----------------------------------------------------
# The special script variables, found by SHAPE (bs57, first try after bs56 lost its answer to a
# host-side wiring bug). gSpecialVars is a ROM table of POINTERS, so it holds no constant to search
# for - its entries ARE the addresses being looked for. What it does have is a relation: entries
# 0..11 point at gSpecialVar_0x8000..0x800B, twelve u16s declared consecutively
# [decomp:src/event_data.c:16], so each word is exactly 2 above the last. `table-scan` searched
# 0x08140000..0x08400000 (2.75 MB, 939 frames, ~23 s) for a twelve-word run rising by 2 and found
# EXACTLY ONE, and the run's first value is the answer itself.
#
# Four independent checks, none of them a re-reading of the same measurement:
#   1. gScriptCmdTable is 214 entries [decomp:data/script_cmd_table.inc] and opens `script_data`
#      with gSpecialVars immediately after it, so the section starts at 0x081639A8 - 856 =
#      0x08163650. script_data follows every .text object [ld_script_rev10.ld:318], and the
#      highest ROM address read as code is 0x08148C74 (bs08's return address), leaving 106 KB for
#      the ~25 objects linked after mystery_gift_client.o. Consistent.
#   2. The pointer lands inside EWRAM, 0x02000000..0x02040000.
#   3. It is ABOVE gPlayerParty (0x02024280, bs47), which is what the EWRAM link order requires:
#      src/event_data.o comes after src/pokemon.o in sym_ewram_rev10.txt.
#   4. It is u16-aligned.
#
# gSpecialVar_0x8000 may be hardcoded, and a save-block address may not: this is EWRAM_DATA, a
# link-time global, where SetSaveBlocksPointers re-rolls a save block's base on every battle
# [decomp:src/load_save.c:75, measured moving 76 bytes between bs45 and bs46].
G_SPECIAL_VARS = 0x081639A8         # u16 *const gSpecialVars[21], by var id
G_SPECIAL_VAR_0X8000 = 0x020370B4   # the first entry, read out of the table by the same run
# The rest follow from the declaration order in event_data.c, which is NOT the table's order.
# UNCONFIRMED - only entry 0 was read off the console; a dump of G_SPECIAL_VARS settles them.
G_SPECIAL_VAR_0X8001 = G_SPECIAL_VAR_0X8000 + 2

# --- src/pokemon.c --------------------------------------------------------------------------------
# gSpeciesInfo, the species table, found by a CONTENT fingerprint rather than by any address
# (bs38) and confirmed by reading it (bs39).
#
# bs37 looked for a word built from friendship/growthRate/eggGroups and found NOTHING in the whole
# 16 MB - the first full-cartridge scan this project has run, and a clean negative. The needle was
# not wrong about the DATA: recomputing bs06's five party mons' six stats each from the decomp's
# base stats, IVs, EVs, level and nature reproduces what the console stored, 30 out of 30, so the
# French cartridge holds the English decomp's species values exactly. It was wrong about the
# LAYOUT. struct SpeciesInfo as the decomp declares it is 26 bytes by ISO alignment (its widest
# member is u16), and at a 26-byte stride bs37's needle sat at entry offset 18, which with a
# 4-aligned table is NEVER word-aligned - and `memory-scan` reads with `ldmia`, so it can only see
# word-aligned matches. Zero hits was the only answer it could have given.
#
# bs38's needle is the one value that survives every hypothesis for the stride and the table's own
# alignment: Mew, Celebi and Jirachi have all six base stats at 100, so bytes 0x00..0x05 of those
# three entries are 0x64 and the word appears at entry offset 0 AND offset 2 - one of the two is
# always aligned. Three hits, no false positives in 4 MB, gaps 2800 and 4424. Those gaps are 100
# and 158 entries at 28 bytes, so the stride is 28: the decomp's 26 declared bytes plus two of
# padding. bs39 then dumped the table and compared it to the decomp entry by entry - 34 of 34
# byte-identical, and the padding is 00 00 on every one of them, so it is padding and not a field
# the decomp is missing.
#
# The link order said where to look and was right a THIRD time (after src/random.o in bs13 and
# src/easy_chat.o in bs16): src/pokemon.o is the 26th .rodata entry in ld_script.ld, so the table
# had to sit early in rodata and below src/easy_chat.o's word data, which bs17 had already
# measured at 0x083DE2C8.
GSPECIES_INFO = 0x0824CDFC
SPECIES_INFO_STRIDE = 28            # sizeof is 26 in the decomp's struct; the ROM pads it to 28
SPECIES_INFO_SLOTS = 412            # NUM_SPECIES, SPECIES_EGG included
# What bs38 actually returned, kept so the address above can be checked against its own evidence:
# the three all-100 species, at GSPECIES_INFO + SPECIES_INFO_STRIDE * species.
SPECIES_INFO_ALL_100 = (151, 251, 409)                       # Mew, Celebi, Jirachi
BS38_SPECIES_INFO_HITS = (0x0824DE80, 0x0824E970, 0x0824FAB8)

# The functions, found by scanning for GSPECIES_INFO itself (bs40) and disassembling where the hits
# landed (bs41, bs42). 31 hits in 0x08028000..0x08048800; the block from 0x080413C0 up is
# src/pokemon.o's, bounded above by src/trig.o and src/random.o - neither of which references the
# table - and below by a 15.6 KB gap that is src/battle_controller_link_opponent.o, which does not
# reference it either. bs41 checked the boundary the honest way and REFUTED a first guess: the
# hits at 0x0803CC54 disassemble as src/battle_ai_switch_items.c:88, not as pokemon.o.
#
# CreateMon is identified instruction for instruction against [decomp:src/pokemon.c:1755], and by
# two constants the decomp fixes independently: it calls SetMonData with field 56 (MON_DATA_LEVEL)
# and then with field 64 (MON_DATA_MAIL) carrying 255 (MAIL_NONE), in that order, between
# CreateBoxMon and CalculateMonStats.
CREATE_MON = 0x08041150             # void CreateMon(mon, species, level, fixedIV,
                                    #   hasFixedPersonality, fixedPersonality, otIdType, fixedOtId)
                                    # args 5..8 go on the stack; the first four are r0..r3
CREATE_BOX_MON = 0x080411C0         # the same signature on a struct BoxPokemon
ZERO_MON_DATA = 0x08041090          # CreateMon's first call
SET_MON_DATA = 0x08043A78           # SetMonData(mon, field, &value)
CALCULATE_MON_STATS = 0x08041B78    # CreateMon's last call

# CALLED ON HARDWARE, bs43 and bs44, both first try. The eight-argument call: four in r0..r3 and
# four at sp+0..sp+12 at the moment of the call, which is where CreateMon's own prologue reads them
# [bs42's disassembly]. bs43 used otIdType 0 (the OT is the player, so fixedOtId is ignored); bs44
# changed only that, to otIdType 1 with the same value, so the fourth stack argument had to arrive
# from the stack instead of from the save. Both answers are byte-identical and 13/13 predicted
# fields hold [scratchpad/verify_create_mon.py], including the moves the ROM walked out of the
# level-up learnset and the six stats CalculateMonStats derived from OUR personality's nature.

# Read off the console for the first time in bs44, out of the mon CreateMon built - these are
# globals no link message carries and no dump had been aimed at.
GGAME_LANGUAGE = 3                  # LANGUAGE_FRENCH [decomp:include/constants/global.h:22]
GGAME_VERSION = 4                   # VERSION_FIRE_RED [:11]
# gSpeciesNames is the FRENCH table, and CreateBoxMon copies from it into the nickname
# [decomp:src/pokemon.c:1810], so one species a run is readable this way. bs44 read species 59 as
# ARCANIN - which bs06's party dump had already read by a completely different route.
SPECIES_NAMES_READ = {59: "ARCANIN"}

# --- read off the console but NOT yet confirmed by disassembling the function itself -------------
# Named by call count and by the shape of the access, which is weaker evidence than the entries
# above. Kept apart so nothing downstream mistakes them for measurements.
PROBABLE = (
    # CreateBoxMon calls one function 20 times, which is what SetBoxMonData does there.
    ("SetBoxMonData", 0x08043BCC),
    # Indexed by a move id at a 12-byte stride with offset 1 compared against zero, which is
    # struct BattleMove's `power` [decomp:include/pokemon.h]. Read in bs41.
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
# gDecompressionBuffer, where CLI_RUN_BUFFER_SCRIPT copies our 1024 bytes and calls them. Deduced
# from ld_script.ld, then MEASURED twice: `anchors` read it from pc (bs08), and it is the first word
# of Client_RunBufferScript's literal pool (bs11).
GDECOMPRESSION_BUFFER = 0x0201C000
# The pointer variables in IWRAM, not the blocks they point at. THEIR VALUES MOVE, and bs45/bs46
# MEASURED it: six minutes apart, with no reboot, gSaveBlock1Ptr was 0x0202559C and then
# 0x02025550 - a delta of 0x4C, 76 bytes, 4-aligned. SetSaveBlocksPointers [decomp:src/load_save.c:75]
# is why:
#
#     offset = (Random()) & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3);      // 128, so 0..124 by 4
#     gSaveBlock2Ptr  = (void *)(&gSaveBlock2) + offset;
#     gSaveBlock1Ptr  = (void *)(&gSaveBlock1) + offset;
#
# a RANDOM 4-aligned offset the game re-rolls in MoveSaveBlocks_ResetHeap, which CB2_InitBattle
# calls - so every battle moves the save blocks, as does every load. 76 is in range and 4-aligned,
# which is the measurement agreeing with the mechanism rather than merely not contradicting it.
# The decomp's own name for it is QL_AddASLROffset [:82].
#
# THE RULE: an absolute address into a save block is valid only until the next battle or load.
# Never carry one between runs. A payload that touches the save must compute from r1/r2, which the
# console hands it every call - save-dump, save-write and --create-mon-append all do. bs45's dry
# run reported the slot it WOULD write at 0x02025638; using that as bs46's --create-mon-destination
# would have written 76 bytes too high, through the end of playerParty[1] and into playerParty[2].
SAVEBLOCK_MOVE_RANGE = 128          # [decomp:src/load_save.c:15]
SAVEBLOCK_MOVE_MASK = (SAVEBLOCK_MOVE_RANGE - 1) & ~3        # 0x7C: 0..124 in steps of 4
# What bs45 and bs46 read, minutes apart, on one boot.
GSAVEBLOCK1_SEEN = (0x0202553C, 0x0202559C, 0x02025550)      # bs08, bs45, bs46
GSAVEBLOCK2PTR = 0x0300422C
GSAVEBLOCK1PTR = 0x03004228
# THE PARTY THE GAME ACTUALLY USES, measured in bs47 by finding a Pokemon rather than by looking
# where it was predicted. `gSaveBlock1Ptr->playerParty` is NOT this: it is only where the save path
# copies to. SavePlayerParty [decomp:src/load_save.c:160] does
#
#     gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
#     for (i = 0; i < PARTY_SIZE; i++) gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
#
# and SaveSerializedGame [:196] is that call plus SaveObjectEvents - so anything written into the
# save block's party is overwritten by the console's own save. bs46 learned this the expensive way:
# it appended into gSaveBlock1Ptr->playerParty, the payload correctly reported APPENDED at slot 2
# with the count raised, and the mon was gone because the save copied the live array back over it.
# Write gPlayerParty and the same call CARRIES the write to flash instead of erasing it.
#
# bs47 dumped 1024 bytes at 0x02024000 and walked every 4-aligned window looking for a struct
# Pokemon with a VALID CHECKSUM - the substruct region summed after decrypting with
# personality ^ otId, which nothing passes by accident. Exactly one did, at +0x280: the player's
# CHANSEY, Lv26, nicknamed 'Cheemsey', OT 'Tops' (traded to them, so the OT is not their own).
# Species, level and nickname are things only their console knew.
#
# Two independent deductions had predicted it and both were right: bs42's dump holds 0x02024280 in
# the literal pool of the first of two functions that zero six 100-byte structs (ZeroPlayerPartyMons
# by source order) and 0x02024028 in the second's; and the decomp declares gEnemyParty[6]
# immediately before gPlayerParty[6] [src/pokemon.c:61-62], so they are exactly 600 bytes apart -
# 0x02024028 + 600 = 0x02024280.
#
# UNLIKE THE SAVE BLOCKS THESE DO NOT MOVE. They are ordinary EWRAM globals fixed at link time,
# which is why bs42 could read one as a literal constant; the ASLR offset above applies only to
# gSaveBlock1/gSaveBlock2/gPokemonStorage.
GPLAYER_PARTY = 0x02024280          # struct Pokemon[6]
GPLAYER_PARTY_COUNT = 0x02024025    # u8; bs47 read 1, matching the one mon on the player's screen
GENEMY_PARTY = 0x02024028           # struct Pokemon[6], 600 bytes below gPlayerParty

# The seed EVERY random outcome in the game comes out of: encounters, shininess, damage rolls,
# critical hits [Random, decomp:src/random.c:9]. Read out of Random's and SeedRng's literal pools
# (bs14) and confirmed on hardware by its own recurrence (bs15). At the Mystery Gift link menu the
# game itself turns it exactly TWICE a frame, measured over 95 consecutive frames.
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
