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
# DERIVED, no run of its own: `script_data` opens with gScriptCmdTable and puts gSpecialVars
# immediately after it [decomp:ld_script_rev10.ld:318], and the table is 214 entries of 4 bytes.
# One dump of it names every field-script command's handler on this build; frlgsim/scrcmd_names.py
# carries the order. docs/buffer_script.md.
G_SCRIPT_CMD_TABLE = G_SPECIAL_VARS - 214 * 4       # 0x08163650

# --- gSpecials, bs92 ----------------------------------------------------------------------------
# The field engine's SECOND dispatch table: ScrCmd_special reads a u16, bounds-checks &gSpecials[i]
# against gSpecialsEnd and calls through it [decomp:src/scrcmd.c:101]. Both addresses came out of
# that handler's own literal pool in one dump, needing no search and no scan.
#
# THREE CHECKS, none of them the dump's own: the span 0x081640EC - 0x081639FC is 0x6F0 = 444 * 4,
# and 444 is exactly the length of data/specials.inc; the table starts at G_SPECIAL_VARS + 21 * 4,
# which is the order ld_script puts them in; and the call goes through 0x081E2224, four bytes below
# CALL_VIA_R1, so it is _call_via_r0 of the same veneer block.
G_SPECIALS = 0x081639FC
G_SPECIALS_END = 0x081640EC
SPECIAL_COUNT = (G_SPECIALS_END - G_SPECIALS) // 4   # 444, and frlgsim/special_names.py names them
CALL_VIA_R0 = 0x081E2224

# DEDUCTION, not a measurement, and free: data/event_scripts.s puts `gStdScripts` immediately after
# the `.include "data/specials.inc"` that ends gSpecials, under `.align 2` which gSpecialsEnd
# already satisfies. So the ten standard scripts callstd reaches are at G_SPECIALS_END. Nothing
# depends on this yet; a 40-byte dump would confirm it, every entry being a pointer into script
# data rather than a THUMB function.
G_STD_SCRIPTS = G_SPECIALS_END          # 0x081640EC, DEDUCED
STD_SCRIPT_COUNT = 10
G_SPECIAL_VAR_0X8000 = 0x020370B4   # the first entry, read out of the table by the same run
# UNCONFIRMED: only entry 0 was read. The rest follow from event_data.c's declaration order, which
# is not the table's order; a dump of G_SPECIAL_VARS settles them.
G_SPECIAL_VAR_0X8001 = G_SPECIAL_VAR_0X8000 + 2

# --- the Mystery Event VM, bs109 + bs110 --------------------------------------------------------
# The one table this project had only ever read from the decomp. It carries no constant to search
# for and its 17 entries are unrelated function addresses, so neither `memory-scan` nor
# `table-scan`'s arithmetic-run fingerprint matches the TABLE. What matches is where its ADDRESS is
# kept: `InitMysteryEventScript` hands the table and its end to `InitScriptContext`
# [decomp:src/mystery_event_script.c:52], `struct ScriptContext` stores them as ADJACENT words at
# +0x5C and +0x60 [decomp:include/script.h], the table is 17 entries so they are exactly 68 apart,
# and the context is `EWRAM_DATA static sMysteryEventScriptContext` - so after any Mystery Event
# script runs, the pair sits in EWRAM for the rest of the boot.
#
# bs109 scanned all 256 KB of EWRAM for two adjacent words 68 apart: ONE hit, no false positives,
# and its value inside the bracket ld_script forces. mev25 was the mystery-event gift that filled
# the context an hour before it; a scan without one finds nothing, because 0 and 0 are not 68 apart.
S_MYSTERY_EVENT_SCRIPT_CONTEXT = 0x0203AA38     # bs109, the hit at +0x5C
G_MYSTERY_EVENT_CMD_TABLE = 0x081DE144          # bs109's value, bs110 read the table itself
MYSTERY_EVENT_CMD_COUNT = 17                    # [decomp:data/mystery_event_script_cmd_table.s]
G_MYSTERY_EVENT_CMD_TABLE_END = G_MYSTERY_EVENT_CMD_TABLE + 4 * MYSTERY_EVENT_CMD_COUNT

# AND THE SECTION BOUNDARY, free with it. `data/mystery_event_script_cmd_table.o(script_data)` is
# the LAST member of script_data and `lib_text` follows [ld_script_rev10.ld:318-330], so the end of
# the table is the end of script_data. bs110 read 0x4C41B510 at that address - `push {r4, lr}`,
# a THUMB prologue - which is libgcnmultiboot, the first thing in lib_text.
SCRIPT_DATA_END = G_MYSTERY_EVENT_CMD_TABLE_END     # 0x081DE188
LIB_TEXT_START = SCRIPT_DATA_END

# The 17 handlers, in table order, as bs110 read them. All odd (THUMB), all distinct, all inside
# .text and clustered in 1084 bytes - one object file's worth of functions, which is the check that
# the table is a table and not seventeen coincidences.
MYSTERY_EVENT_HANDLERS = (
    ("nop", 0x080DE451), ("checkcompat", 0x080DE401), ("end", 0x080DE3F5),
    ("setmsg", 0x080DE465), ("setstatus", 0x080DE455), ("runscript", 0x080DE49D),
    ("initramscript", 0x080DE5B5), ("setenigmaberry", 0x080DE4B9), ("giveribbon", 0x080DE581),
    ("givenationaldex", 0x080DE61D), ("addrareword", 0x080DE641),
    ("setrecordmixinggift", 0x080DE66D), ("givepokemon", 0x080DE681),
    ("addtrainer", 0x080DE78D), ("enableresetrtc", 0x080DE7D5), ("checksum", 0x080DE7E9),
    ("crc", 0x080DE831),
)


# --- the Mystery Event VM's workers, bs111 -------------------------------------------------------
# bs84's method on the VM's own table: a handler reads its arguments and then calls, and the decomp
# gives the call ORDER, so the bl targets name themselves by position
# [decomp:src/mystery_event_script.c]. The alignment check is that the targets this project had
# already measured land where they should - ScriptReadWord, ScriptReadHalfword, ScriptContext_Stop,
# GetMonData, CalculatePlayerPartyCount, and the specials EnableNationalPokedex (367),
# IsEnigmaBerryValid (50) and ValidateEReaderTrainer (246).
ME_CHECK_COMPATIBILITY = 0x080DE300     # checkcompat's test, before the branch
ME_SET_INCOMPATIBLE = 0x080DE330        # checkcompat's else, and BOTH dead opcodes call only this
STRING_EXPAND_PLACEHOLDERS = 0x0800CADC  # every handler that leaves a message ends on it
RUN_SCRIPT_IMMEDIATELY = 0x0806D438     # runscript: ScriptReadWord then this, and nothing else
INIT_RAM_SCRIPT = 0x0806D5F0            # initramscript, the call this project drives by wire
GIVE_GIFT_RIBBON_TO_PARTY = 0x080A43B0  # giveribbon
ENABLE_RARE_WORD = 0x080C1658           # addrareword

# AND A CHECK ON THE SECTION BOUNDARY, from a direction that knew nothing about it. addtrainer is
# `ScriptReadWord; memcpy; ValidateEReaderTrainer; StringExpandPlaceholders`, and its second bl is
# 0x081E44F4 - so that is memcpy, which comes from libgcc and therefore lives in `lib_text`. It is
# ABOVE 0x081DE188, which bs110 put the section boundary at by reading a THUMB prologue there.
MEMCPY = 0x081E44F4
CALC_CRC16 = 0x080489A0                 # crc: three ScriptReadWord then this, and nothing else

# bs111/bs112 again, from the two longest handlers. `setenigmaberry` and `givepokemon` are written
# out call for call in the decomp, so every bl lands on a name by position - and every already
# measured target in them (IsEnigmaBerryValid, ScriptReadWord, GetMonData,
# CalculatePlayerPartyCount, memcpy, StringExpandPlaceholders) lands where it should.
STRING_COPY_N = 0x0800C8CC              # setenigmaberry calls it twice, givepokemon twice
STRING_COMPARE = 0x0800C938
SET_ENIGMA_BERRY = 0x080A01B0
SPECIES_TO_NATIONAL_POKEDEX_NUM = 0x08046994
GET_SET_POKEDEX_FLAG = 0x0808C860       # givepokemon calls it twice: FLAG_SET_SEEN, FLAG_SET_CAUGHT
ITEM_IS_MAIL = 0x0809BB18
GIVE_MAIL_TO_MON2 = 0x0809B964
COMPACT_PARTY_SLOTS = 0x080971FC

# VarSet, WHICH NOTHING ELSE HAD REACHED. No ScrCmd body calls it - `setvar`'s worker is
# GetVarPointer and a store through what it returns - so session 39 built `call-chain`'s `prev`
# mechanism precisely because there was no VarSet to call. `MEScrCmd_setenigmaberry`'s last call is
# `VarSet(VAR_ENIGMA_BERRY_AVAILABLE, 1)` [decomp:src/mystery_event_script.c], and it is here.
#
# The check is the layout: event_data.c declares GetVarPointer, then VarGet, then VarSet, and
# 0x08071CC8 < 0x08071DDC < 0x08071DF8 in exactly that order - with 0x1C between VarGet and VarSet,
# which is the whole of VarGet's body (GetVarPointer, a null test, one load).
VAR_SET = 0x08071DF8


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

# --- the workers behind the field-script commands, bs84 -----------------------------------------
# One 1 KB dump of 0x0806DE00 covered 24 handlers, and each one names its worker by position: the
# decomp's body is `VarGet(ScriptReadHalfword(ctx))` per argument and then one call
# [decomp:src/scrcmd.c:463-590]. Every address below is that call, matched instruction for
# instruction - ScrCmd_additem's `(u8)quantity` cast is even visible as `lsls r1,#24; lsrs r1,#24`.
#
# THE CHECK THAT MAKES IT A MEASUREMENT: ScrCmd_random's third call is 0x080486B0, which is RANDOM
# above, found independently at bs13 from its own literal pool. A misaligned or mis-decoded
# extraction could not land on an address this file already held.
SCRIPT_READ_HALFWORD = 0x0806D1E8   # u16 ScriptReadHalfword(ctx), every command's argument reader
VAR_GET = 0x08071DDC                # u16 VarGet(u16), the value behind a var id or a literal
GET_VAR_POINTER = 0x08071CC8        # u16 *GetVarPointer(u16), what addvar/setvar write through
ADD_BAG_ITEM = 0x0809DA70           # bool8 AddBagItem(u16 itemId, u8 quantity)
REMOVE_BAG_ITEM = 0x0809DBC4        # bool8 RemoveBagItem(u16 itemId, u8 quantity)
CHECK_BAG_HAS_SPACE = 0x0809D9EC    # bool8 CheckBagHasSpace(u16 itemId, u8 quantity)
CHECK_BAG_HAS_ITEM = 0x0809D92C     # bool8 CheckBagHasItem(u16 itemId, u8 quantity)
ADD_PC_ITEM = 0x0809DDB4            # bool8 AddPCItem(u16 itemId, u16 quantity)
FLAG_SET = 0x08071EF4               # void FlagSet(u16 flagId)
FLAG_CLEAR = 0x08071F1C             # void FlagClear(u16 flagId)
FLAG_GET = 0x08071F44               # bool8 FlagGet(u16 flagId)
INCREMENT_GAME_STAT = 0x080587A4    # void IncrementGameStat(u8 statId)
TRY_SET_OBTAINED_ITEM_QUEST_LOG_EVENT = 0x0809E210   # ScrCmd_additem's second call

# --- the money workers, bs89 --------------------------------------------------------------------
# A second 1 KB dump, of 0x0806F800, by exactly the method bs84 established. ScrCmd_addmoney,
# _removemoney, _checkmoney and _updatemoneybox each read their argument and then make ONE call
# through a pointer they build the same way: `ldr r0,[0x03004228]; ldr r0,[r0]; r1 = 0xA4 << 2;
# adds r0,r0,r1` - gSaveBlock1Ptr, then &money [decomp:src/scrcmd.c, include/global.h:774].
#
# THE CHECKS THAT MAKE IT A MEASUREMENT: that literal is 0x03004228, which is GSAVEBLOCK1PTR as
# lg175 measured it; 0xA4 << 2 is 0x290, which is `struct SaveBlock1.money`'s own offset; and
# ScrCmd_givemon in the same window calls 0x08071DDC, which is VarGet from bs84.
SCRIPT_READ_WORD = 0x0806D200        # u32 ScriptReadWord(ctx), the u32 sibling of ReadHalfword
GET_MONEY = 0x080A3764               # u32 GetMoney(u32 *money)
IS_ENOUGH_MONEY = 0x080A3794         # bool8 IsEnoughMoney(u32 *money, u32 cost)
ADD_MONEY = 0x080A37AC               # void AddMoney(u32 *money, u32 toAdd), capped at MAX_MONEY
REMOVE_MONEY = 0x080A37E4            # void RemoveMoney(u32 *money, u32 toSub), floored at 0
CHANGE_AMOUNT_MONEY_BOX = 0x080A39AC  # ScrCmd_updatemoneybox's second call

# MONEY IS ENCRYPTED, which is why GetMoney exists at all: `*moneyPtr ^ encryptionKey`
# [decomp:src/money.c:14], the key being gSaveBlock2Ptr->encryptionKey. So a raw read of
# SAV1_MONEY is the ciphertext and the two together give the key.
SAV1_MONEY = 0x290                   # struct SaveBlock1.money [decomp:include/global.h:774]
SAV2_ENCRYPTION_KEY = 0xF20          # struct SaveBlock2.encryptionKey [:358]
# The literal ScrCmd_additem stores its result through, which is what gSpecialVar_Result must be.
GSPECIAL_VAR_RESULT = 0x020370CC

# The workers above, by the decomp's own name, so that a payload can be asked for one of them
# instead of a bare address. Everything here was read off the console (bs84) or called on it
# (bs85, AddBagItem); nothing is here on the strength of the decomp alone, because an address the
# decomp knows is an address for a DIFFERENT build. `callable_function` returns the THUMB pointer
# a `bx` needs.
CALLABLE = {
    "Random": RANDOM,
    "SeedRng": SEED_RNG,
    "CreateMon": CREATE_MON,
    "VarGet": VAR_GET,
    "VarSet": VAR_SET,
    "GetVarPointer": GET_VAR_POINTER,
    "AddBagItem": ADD_BAG_ITEM,
    "RemoveBagItem": REMOVE_BAG_ITEM,
    "CheckBagHasSpace": CHECK_BAG_HAS_SPACE,
    "CheckBagHasItem": CHECK_BAG_HAS_ITEM,
    "AddPCItem": ADD_PC_ITEM,
    "FlagSet": FLAG_SET,
    "FlagClear": FLAG_CLEAR,
    "FlagGet": FLAG_GET,
    "IncrementGameStat": INCREMENT_GAME_STAT,
    "GetMoney": GET_MONEY,
    "IsEnoughMoney": IS_ENOUGH_MONEY,
    "AddMoney": ADD_MONEY,
    "RemoveMoney": REMOVE_MONEY,
    "CalcCRC16": CALC_CRC16,
    "GetSetPokedexFlag": GET_SET_POKEDEX_FLAG,
    "SpeciesToNationalPokedexNum": SPECIES_TO_NATIONAL_POKEDEX_NUM,
    "CompactPartySlots": COMPACT_PARTY_SLOTS,
    "ItemIsMail": ITEM_IS_MAIL,
    "StringCompare": STRING_COMPARE,
    "InitRamScript": INIT_RAM_SCRIPT,
    "RunScriptImmediately": RUN_SCRIPT_IMMEDIATELY,
}


def callable_function(name):
    """-> the THUMB pointer for one of CALLABLE, by the decomp's name, case-insensitively."""
    for known, address in CALLABLE.items():
        if known.lower() == str(name).lower():
            return thumb(address)
    raise KeyError(f"{name!r} is not a function this project has measured; known: "
                   + ", ".join(sorted(CALLABLE)))


# --- more workers, bs92/bs99, extracted with scratchpad/handler_workers.py ----------------------
# The same method as bs84, but read out by tool rather than by eye: every `bl` a handler makes, in
# order, against the decomp's body for that command. Two of the warp workers name THEMSELVES - the
# specials table bs93/bs95 dumped calls 0x08081CC8 DoDiveWarp and 0x08081DA0 DoFallWarp - so the
# two tables confirm each other here without either being assumed.
SCRIPT_CONTEXT_STOP = 0x0806D0EC      # ScrCmd_end's one call
SCRIPT_CONTEXT_SET_NATIVE = 0x0806D0E4  # what gotonative/delay/fadescreen hand their function to
SCRIPT_JUMP = 0x0806D1C0              # goto, goto_if, vgoto
SCRIPT_CALL = 0x0806D1C4              # call, call_if, vcall
SCRIPT_RETURN = 0x0806D1D8
GET_MON_DATA = 0x080432E4             # ScrCmd_checkpartymove's reader, and HealPlayerParty's
SCRIPT_GIVE_MON = 0x080A3B28          # ScrCmd_givemon's one call, after four operand reads
SCRIPT_GIVE_EGG = 0x080A3BB8
SCRIPT_SET_MON_MOVE_SLOT = 0x080A3D08

# The warp family [decomp:src/scrcmd.c:719]: every one of them is
# SetWarpDestination(...); Do<kind>Warp(); ResetInitialPlayerAvatarState().
SET_WARP_DESTINATION = 0x08058CA0
RESET_INITIAL_PLAYER_AVATAR_STATE = 0x080592F8
DO_WARP = 0x08081C90
DO_DIVE_WARP = 0x08081CC8             # = special 318, which is how it is named
DO_DOOR_WARP = 0x08081D34
DO_FALL_WARP = 0x08081DA0             # = special 319
SHOW_FIELD_MESSAGE = 0x0806CD2C        # ScrCmd_message's one call: the text box, given a pointer
SHOW_FIELD_AUTOSCROLL_MESSAGE = 0x0806CD54
CALCULATE_PLAYER_PARTY_COUNT = 0x08044338   # = special 131, which is how it is named
GET_PLAYER_FACING_DIRECTION = 0x0805FFC4    # = special 287
SET_RESPAWN = 0x08058DE0               # ScrCmd_setrespawn: where a white-out returns the player

# NOT CALLABLE FROM A BUFFER SCRIPT. These run inside the Mystery Gift menu, where there is no
# overworld to warp: they belong to a FIELD stub, which runs from the field engine. docs/rng.md
# has how a stub is staged.

# --- what the two cartridges share, lg184-lg189 -------------------------------------------------
# Four needles from FireRed dumps came back at the same address on LeafGreen (0x0806D7F4,
# 0x080701C0, 0x08071E1C, 0x08071FC4), and lg189 is the control: a fifth from inside AddBagItem,
# above the 0x0807D238 boundary, came back shifted -0x2C. So everything below 0x08071FC4 is the
# same address on both cartridges - the gScriptCmdTable handler block 0x0806D7C0..0x080700B8, the
# script engine from 0x0806D0E4, GetVarPointer/VarGet/FlagSet/FlagClear/FlagGet, and the
# special/callnative veneer.
SHARED_WITH_LEAFGREEN_THROUGH = 0x08071FC4
LEAFGREEN_ADD_BAG_ITEM = 0x0809DA44      # lg189; the rest of that block is -0x2C by segment

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
    (0x08000000, 0x08071FC4, 0x00, "lg176b vs bs68b, 42 paired hits; lg184-lg187 carried it up "
     "from 0x0805359C with four needles from bs92/bs103/bs105, lg189 the control"),
    (0x0807D238, 0x080CE36C, -0x2C, "lg176b vs bs68b, 2 paired hits; lg161 vs bs13, 4 more"),
    (0x080EBA14, 0x0813E8CC, -0x28, "lg176b vs bs68b, 9 paired hits; lg161 vs bs13, 5 more"),
    (0x08148C74, 0x0824CDFC, -0x24, "lg176b vs bs68b, 3 paired hits; lg160, lg161-vs-bs13, lg165"),
    (0x083DE528, 0x083E3700, -0x1C4, "lg169: 18 word-list pointers and the table, all -0x1C4"),
    (0x086003E0, 0x086803FC, -0x12D8, "bs69/lg178 and bs72/lg179, two points 0x80000 apart"),
)

# THE HIGH SEGMENT, and how it was measured without knowing a single symbol up there. Dump 1 KB off
# one console, pick a word that occurs exactly once in it and has four distinct bytes, then scan a
# window on the other console for that word: the address it comes back at IS the delta. Two runs a
# point, anywhere in the ROM, needing no symbol and no decomp. bs69 dumped FireRed 0x08600000 and
# lg178 found 0xE1926F4D at LeafGreen 0x085FF108; bs72 dumped 0x08680000 and lg179 found 0xC35D61AE
# at 0x0867F124. Both -0x12D8, half a megabyte apart, which is what makes it a segment and not a
# point - one point would have been the mistake lg167 already paid for.
#
# FireRed's ROM data ENDS between 0x08680400 and 0x08800000: bs71 read all 0xFF at 0x08800000 and
# bs70 all 0x00 at 0x08E00000, while 0x08680000 is high-entropy data.

# WHERE EACH BOUNDARY IS, which is the other half of the same measurement. lg176b scanned LeafGreen
# for ITS gSpeciesInfo (0x0824CDD8) and bs68b scanned FireRed for ITS OWN (0x0824CDFC), each over
# the whole ROM: every literal-pool reference to the species table, 56 hits on each console, so they
# pair one to one and give the delta at 56 points for two runs. Three boundaries and no more are
# visible in 0x08000000..0x0815A630, which is as high as a reference to that table goes.
#
# A boundary is the span between the last paired hit at one delta and the first at the next. It is
# NOT located to the byte; halving one of these needs a needle known to sit inside it.
LEAFGREEN_DELTA_BOUNDARIES = (
    # (from_delta, to_delta, low, high, evidence)
    (0x00, -0x2C, 0x08071FC4, 0x0807D238, "lg184-lg187 below, lg161/bs13/lg189 above; was "
     "0x0805359C, narrowed 25x"),
    (-0x2C, -0x28, 0x080CE36C, 0x080EBA14, "lg176b vs bs68b, both ends"),
    (-0x28, -0x24, 0x0813E8CC, 0x08148C74, "lg176b/bs68b below, lg160 above"),
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


# --- gSpecials as the console holds it, bs93 ----------------------------------------------------
# All 444 entries, in two runs: bs93 dumped the first 256 at G_SPECIALS and bs95 the
# remaining 188 at G_SPECIALS + 1024. frlgsim/special_names.SPECIALS
# names them by index, and `special_function(name)` resolves one to a THUMB pointer.
#
# THE DUMP PROVES ITS OWN ALIGNMENT: every word came back a THUMB pointer into the cartridge, and
# the 128 indices this half calls NullFieldSpecial all came back with ONE address (0x080CE8DC). A dump
# read at the wrong offset could not produce that.
SPECIAL_ADDRESSES = (
    0x080A3A64, 0x08071900, 0x08081EAC, 0x08081F5C,
    0x08084FA4, 0x08084FD0, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080848BC, 0x08084924, 0x0808494C, 0x0800D25C,
    0x08085234, 0x080851E4, 0x08085224, 0x08084B64,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x0804FAF8,
    0x0804FB38, 0x080A3D40, 0x08085288, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080A0240, 0x08083C1C,
    0x08083E28, 0x08083E68, 0x08083C34, 0x08085D8C,
    0x08083E78, 0x081107F4, 0x0811095C, 0x08083E00,
    0x080900C8, 0x080A3C00, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CF9D8, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x08084980, 0x08072EF0, 0x080A4878, 0x08102AC0,
    0x080C1564, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080A431C,
    0x080A4334, 0x080A4370, 0x080A4388, 0x080CFABC,
    0x080CFC8C, 0x080CFCBC, 0x080CE8DC, 0x080CE8DC,
    0x080C1604, 0x080CE8DC, 0x0809DF2C, 0x08044338,
    0x0808FB48, 0x0808FBEC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE1A8, 0x0805DF84, 0x080CE1B8,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE1D8,
    0x080CE1F8, 0x080CE230, 0x080CE274, 0x080CE8DC,
    0x080CE8DC, 0x080596D8, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080830E0, 0x080CFBA4, 0x080C33E4,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x08116E58,
    0x08116D7C, 0x08116E98, 0x08116B58, 0x08116DC0,
    0x08117004, 0x08116B9C, 0x08117024, 0x080866C0,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE268, 0x08049C84, 0x08049C9C, 0x08049770,
    0x08049A94, 0x08049E70, 0x08049C48, 0x08048D68,
    0x0804A310, 0x0804A2A0, 0x08049080, 0x08049020,
    0x08048F10, 0x0804A608, 0x0804A7BC, 0x0804A694,
    0x080D0D2C, 0x080A3808, 0x080A382C, 0x080A400C,
    0x080CDEE0, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080A48C8, 0x080A48F0, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CDEF4, 0x080CE040, 0x080CE388, 0x080CE4C4,
    0x080CED20, 0x080CE8DC, 0x080CE8DC, 0x080C3424,
    0x080C34A4, 0x080C3690, 0x080C3538, 0x080C34F0,
    0x080E8134, 0x080CE8DC, 0x080CE8DC, 0x080CE180,
    0x080CE8DC, 0x080CE8DC, 0x080CE288, 0x080E9470,
    0x080E9728, 0x080EA148, 0x080EA2FC, 0x080EB038,
    0x080EA400, 0x080EA50C, 0x080EA78C, 0x080EA914,
    0x080EAAB8, 0x080EAB58, 0x080EACD0, 0x080EAD4C,
    0x080EADB8, 0x080A3D8C, 0x080EAF90, 0x080CE8DC,
    0x080A3DE4, 0x080EF1AC, 0x080EF1FC, 0x080CE308,
    0x080573B0, 0x0805767C, 0x08057D54, 0x08057640,
    # --- bs95: indices 256..443, the rest of the table -------------------------------------
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080A0A2C, 0x080CE090,
    0x080CE134, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080A4890, 0x080008D0,
    0x080CDDB4, 0x080CEFB4, 0x080CE8DC, 0x080CE550,
    0x080CE5A4, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE8DC, 0x080CE5C8, 0x080CE5D8, 0x0805FFC4,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE8DC,
    0x080CE5FC, 0x080CE624, 0x080CE660, 0x0806D030,
    0x0806D058, 0x08145B9C, 0x080CE8DC, 0x080CE320,
    0x080CE8DC, 0x080CE8DC, 0x080CE694, 0x080CE8DC,
    0x080CE6EC, 0x080CE8DC, 0x080CF09C, 0x080CE8DC,
    0x080CE724, 0x08072210, 0x080CE744, 0x080832C0,
    0x08083230, 0x08083314, 0x08083BE8, 0x080CE8DC,
    0x080CE8DC, 0x0807EF10, 0x08081CC8, 0x08081DA0,
    0x080CE8DC, 0x080CE8DC, 0x080E9970, 0x080831F0,
    0x080CE8DC, 0x080CE8DC, 0x080CE8DC, 0x080CE870,
    0x080C36FC, 0x080CE8DC, 0x080CE8DC, 0x0804FC28,
    0x08082908, 0x080CE8DC, 0x080CE8DC, 0x0808C944,
    0x080CE898, 0x080CE8DC, 0x080EB09C, 0x080A3C78,
    0x080CE8DC, 0x0810F2D4, 0x0808315C, 0x080CE14C,
    0x080CF2E0, 0x080CF778, 0x080CE8E0, 0x080CE908,
    0x08060AA8, 0x080CEBC4, 0x080CECF4, 0x08049CE0,
    0x080CF158, 0x080CF89C, 0x080CF8CC, 0x080CF8E8,
    0x0810FEEC, 0x080D02B8, 0x080CFAFC, 0x080CFDD8,
    0x080CFEE8, 0x080D0040, 0x0800CF90, 0x08119518,
    0x0811A3A0, 0x0811C390, 0x08152BE8, 0x08071AA0,
    0x0806D2D0, 0x0806D2AC, 0x0810FE4C, 0x0813138C,
    0x081313F0, 0x0805855C, 0x0804A328, 0x0804A358,
    0x0804A37C, 0x0804A3A4, 0x0804A3C4, 0x0814A8C8,
    0x080CFFA8, 0x0812EFC0, 0x0812EFD4, 0x0812EFE8,
    0x08147DC8, 0x0810F2B8, 0x0811D7B0, 0x0811D928,
    0x08117400, 0x080CFFF0, 0x080D024C, 0x08114594,
    0x08115E58, 0x0814A750, 0x080D02AC, 0x080A0EF0,
    0x080A100C, 0x0812B5A0, 0x0812B60C, 0x08083C4C,
    0x0812F0FC, 0x08160D40, 0x0814D468, 0x08071AD0,
    0x081613C4, 0x0814EF18, 0x080D03D0, 0x080D044C,
    0x0812F218, 0x0812F224, 0x0810F2D4, 0x0809D998,
    0x08162A2C, 0x08162AAC, 0x08162848, 0x081628F4,
    0x08162A08, 0x080D0478, 0x08152490, 0x080D0698,
    0x080D07FC, 0x080F750C, 0x08157218, 0x080A1150,
    0x080A12AC, 0x0814AF50, 0x0805FFC4, 0x080D0900,
    0x080D0B0C, 0x0814AFE4, 0x080D0B38, 0x08161210,
    0x0808C970, 0x080D0B78, 0x080D0B9C, 0x0811EF34,
    0x080D0BF8, 0x0809FE94, 0x081571C8, 0x0809FFE8,
    0x080CEE44, 0x080D0C58, 0x080D0CB8, 0x08047F34,
)


def special_function(name, addresses=None):
    """-> the THUMB pointer for a special by the decomp's name, from what bs93 measured."""
    from . import special_names
    index = special_names.index(name)
    table = SPECIAL_ADDRESSES if addresses is None else addresses
    if index >= len(table):
        raise KeyError(f"{name!r} is special {index}, past the {len(table)} entries bs93 dumped")
    return thumb(table[index])
