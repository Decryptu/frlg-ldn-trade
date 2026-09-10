"""Addresses in the ROM the console runs, each read off it.

The console runs the French FireRed Switch build, game code `BPRF`, software version 0x0A. The pret
decomp's `firered_switch` target is GAME_REVISION=10 but matches the English rev-10 ROM, so its
addresses are never assumed here. A symbol that has not been read off the console does not belong
in this file.

How each address was obtained is in docs/frlg_rom.md, docs/frlg_rom_map.md (gSpeciesInfo and
CreateMon) and docs/frlg_leafgreen.md (the second cartridge).
"""

GAME_CODE = b"BPRF"          # B-PR-F: Pokemon FireRed, French
SOFTWARE_VERSION = 0x0A      # the decomp's REVISION >= 0xA branches are the ones running
GAME_TITLE = b"POKEMON FIRE"
ROM_HEADER_TITLE = 0x080000A0
ROM_HEADER_GAME_CODE = 0x080000AC
ROM_HEADER_VERSION = 0x080000BC

# --- src/mystery_gift_client.c ----------------------------------------------------------------
# sClientFuncs, indexed by client->funcId.
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
# Where our payload's lr points: the instruction after `bl _call_via_r3`.
CLIENT_RUN_BUFFER_SCRIPT_RETURN = 0x08148C74
MYSTERY_GIFT_CLIENT_CALL_FUNC = 0x08148C94

# --- src/mystery_gift_server.c ------------------------------------------------------------------
# sFuncTable, immediately after sClientFuncs. Named by what each function does, not by position:
# 0x08148DF0 is Server_Init's `funcId = FUNC_RUN; return SVR_RET_INIT` and 0x08148DF8 is
# Server_Done returning SVR_RET_END = 3.
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
# Client_Send.
MYSTERY_GIFT_LINK_RECV = 0x081485E8
MYSTERY_GIFT_LINK_SEND = 0x081485F4

# --- src/random.c ---------------------------------------------------------------------------------
# Found by scanning for RAND_MULT and confirmed by calling it 96 times and checking the LCG
# recurrence either side of every call.
RANDOM = 0x080486B0                 # u16 Random(void)
SEED_RNG = 0x080486D0               # void SeedRng(u16), whose pool names gRngValue a second time

# --- src/event_data.c and data/event_scripts.s ----------------------------------------------------
# gSpecialVars entries 0..11 point at twelve consecutive u16s, each word +2 on the last; exactly
# one such run exists in 2.75 MB. gSpecialVar_0x8000 may be hardcoded because it is EWRAM_DATA, a
# link-time global; a save-block address may not (see SAVEBLOCK_MOVE_RANGE below).
G_SPECIAL_VARS = 0x081639A8         # u16 *const gSpecialVars[21], by var id
# Derived, not measured: `script_data` opens with gScriptCmdTable and puts gSpecialVars
# immediately after it [decomp:ld_script_rev10.ld:318], and the table is 214 entries of 4 bytes.
# One dump names every field-script command's handler on this build;
# pokeldn/frlg/rom/scrcmd_names.py carries the order. docs/frlg_rom.md.
G_SCRIPT_CMD_TABLE = G_SPECIAL_VARS - 214 * 4       # 0x08163650

# --- gSpecials -----------------------------------------------------------------------------------
# The field engine's second dispatch table: ScrCmd_special reads a u16, bounds-checks &gSpecials[i]
# against gSpecialsEnd and calls through it [decomp:src/scrcmd.c:101]. Both addresses come out of
# that handler's own literal pool.
#
# Three independent checks: the span 0x081640EC - 0x081639FC is 0x6F0 = 444 * 4, and 444 is the
# length of data/specials.inc; the table starts at G_SPECIAL_VARS + 21 * 4, the order ld_script puts
# them in; and the call goes through 0x081E2224, four bytes below CALL_VIA_R1, so it is
# _call_via_r0 of the same veneer block.
G_SPECIALS = 0x081639FC
G_SPECIALS_END = 0x081640EC
SPECIAL_COUNT = (G_SPECIALS_END - G_SPECIALS) // 4   # 444, and pokeldn/frlg/rom/special_names.py names them
CALL_VIA_R0 = 0x081E2224

# Deduced, not measured: data/event_scripts.s puts `gStdScripts` immediately after the
# `.include "data/specials.inc"` that ends gSpecials, under `.align 2` which gSpecialsEnd already
# satisfies, so the ten standard scripts callstd reaches are at G_SPECIALS_END. A 40-byte dump
# would confirm it, every entry being a pointer into script data rather than a THUMB function.
G_STD_SCRIPTS = G_SPECIALS_END          # 0x081640EC, DEDUCED
STD_SCRIPT_COUNT = 10
G_SPECIAL_VAR_0X8000 = 0x020370B4   # the first entry, read out of the table by the same run
# Unconfirmed: only entry 0 is read. The rest follow from event_data.c's declaration order, which
# is not the table's order; a dump of G_SPECIAL_VARS settles them.
G_SPECIAL_VAR_0X8001 = G_SPECIAL_VAR_0X8000 + 2

# --- the Mystery Event VM ------------------------------------------------------------------------
# The table carries no constant to search for and its 17 entries are unrelated function addresses,
# so neither `memory-scan` nor `table-scan`'s arithmetic-run fingerprint matches it. Its address is
# findable instead: `InitMysteryEventScript` hands the table and its end to `InitScriptContext`
# [decomp:src/mystery_event_script.c:52], `struct ScriptContext` stores them as adjacent words at
# +0x5C and +0x60 [decomp:include/script.h], the table is 17 entries so they are exactly 68 apart,
# and the context is `EWRAM_DATA static sMysteryEventScriptContext`, so after any Mystery Event
# script runs the pair sits in EWRAM for the rest of the boot.
#
# A scan of all 256 KB of EWRAM for two adjacent words 68 apart gives one hit. The scan only works
# after a Mystery Event has filled the context: 0 and 0 are not 68 apart.
S_MYSTERY_EVENT_SCRIPT_CONTEXT = 0x0203AA38     # the EWRAM hit, at +0x5C
G_MYSTERY_EVENT_CMD_TABLE = 0x081DE144          # its value; the table itself was read too
MYSTERY_EVENT_CMD_COUNT = 17                    # [decomp:data/mystery_event_script_cmd_table.s]
G_MYSTERY_EVENT_CMD_TABLE_END = G_MYSTERY_EVENT_CMD_TABLE + 4 * MYSTERY_EVENT_CMD_COUNT

# The section boundary comes with it: `data/mystery_event_script_cmd_table.o(script_data)` is the
# last member of script_data and `lib_text` follows [ld_script_rev10.ld:318-330], so the end of the
# table is the end of script_data. That address reads 0x4C41B510 (`push {r4, lr}`, a THUMB
# prologue), which is libgcnmultiboot, the first thing in lib_text.
SCRIPT_DATA_END = G_MYSTERY_EVENT_CMD_TABLE_END     # 0x081DE188
LIB_TEXT_START = SCRIPT_DATA_END

# The 17 handlers in table order. All odd (THUMB), all distinct, all inside .text and clustered in
# 1084 bytes, one object file's worth of functions.
MYSTERY_EVENT_HANDLERS = (
    ("nop", 0x080DE451), ("checkcompat", 0x080DE401), ("end", 0x080DE3F5),
    ("setmsg", 0x080DE465), ("setstatus", 0x080DE455), ("runscript", 0x080DE49D),
    ("initramscript", 0x080DE5B5), ("setenigmaberry", 0x080DE4B9), ("giveribbon", 0x080DE581),
    ("givenationaldex", 0x080DE61D), ("addrareword", 0x080DE641),
    ("setrecordmixinggift", 0x080DE66D), ("givepokemon", 0x080DE681),
    ("addtrainer", 0x080DE78D), ("enableresetrtc", 0x080DE7D5), ("checksum", 0x080DE7E9),
    ("crc", 0x080DE831),
)


# --- the Mystery Event VM's workers ---------------------------------------------------------------
# A handler reads its arguments and then calls, and the decomp gives the call order, so the bl
# targets name themselves by position [decomp:src/mystery_event_script.c]. The alignment check is
# that already-measured targets land where they should: ScriptReadWord, ScriptReadHalfword,
# ScriptContext_Stop, GetMonData, CalculatePlayerPartyCount, and the specials EnableNationalPokedex
# (367), IsEnigmaBerryValid (50) and ValidateEReaderTrainer (246).
ME_CHECK_COMPATIBILITY = 0x080DE300     # checkcompat's test, before the branch
ME_SET_INCOMPATIBLE = 0x080DE330        # checkcompat's else, and BOTH dead opcodes call only this
STRING_EXPAND_PLACEHOLDERS = 0x0800CADC  # every handler that leaves a message ends on it
RUN_SCRIPT_IMMEDIATELY = 0x0806D438     # runscript: ScriptReadWord then this, and nothing else
INIT_RAM_SCRIPT = 0x0806D5F0            # initramscript, the call this project drives by wire
GIVE_GIFT_RIBBON_TO_PARTY = 0x080A43B0  # giveribbon
ENABLE_RARE_WORD = 0x080C1658           # addrareword

# An independent check on the section boundary: addtrainer is
# `ScriptReadWord; memcpy; ValidateEReaderTrainer; StringExpandPlaceholders`, and its second bl is
# 0x081E44F4, so that is memcpy, which comes from libgcc and lives in `lib_text`. It is above
# 0x081DE188, the section boundary read from a THUMB prologue.
MEMCPY = 0x081E44F4
CALC_CRC16 = 0x080489A0                 # crc: three ScriptReadWord then this, and nothing else

# From the two longest handlers. `setenigmaberry` and `givepokemon` are written out call for call
# in the decomp, so every bl lands on a name by position, and every already measured target in them
# (IsEnigmaBerryValid, ScriptReadWord, GetMonData, CalculatePlayerPartyCount, memcpy,
# StringExpandPlaceholders) lands where it should.
STRING_COPY_N = 0x0800C8CC              # setenigmaberry calls it twice, givepokemon twice
STRING_COMPARE = 0x0800C938
SET_ENIGMA_BERRY = 0x080A01B0
SPECIES_TO_NATIONAL_POKEDEX_NUM = 0x08046994
GET_SET_POKEDEX_FLAG = 0x0808C860       # givepokemon calls it twice: FLAG_SET_SEEN, FLAG_SET_CAUGHT
ITEM_IS_MAIL = 0x0809BB18
GIVE_MAIL_TO_MON2 = 0x0809B964
COMPACT_PARTY_SLOTS = 0x080971FC

# VarSet is reachable only from here. No ScrCmd body calls it (`setvar`'s worker is GetVarPointer
# and a store through what it returns); `MEScrCmd_setenigmaberry`'s last call is
# `VarSet(VAR_ENIGMA_BERRY_AVAILABLE, 1)` [decomp:src/mystery_event_script.c].
#
# The check is the layout: event_data.c declares GetVarPointer, then VarGet, then VarSet, and
# 0x08071CC8 < 0x08071DDC < 0x08071DF8 in that order, with 0x1C between VarGet and VarSet, the
# whole of VarGet's body (GetVarPointer, a null test, one load).
VAR_SET = 0x08071DF8


# --- src/pokemon.c --------------------------------------------------------------------------------
# gSpeciesInfo, found by a content fingerprint and confirmed by reading it (34 of 34 entries
# byte-identical to the decomp). The three all-100 species give a word at entry offset 0 and 2, so
# one of the two is word-aligned whatever the stride; memory-scan reads with `ldmia` and only sees
# word-aligned matches. The gaps between the hits give the stride, 28.
GSPECIES_INFO = 0x0824CDFC
SPECIES_INFO_STRIDE = 28            # the decomp's struct is 26 bytes; the ROM pads it to 28
SPECIES_INFO_SLOTS = 412            # NUM_SPECIES, SPECIES_EGG included
SPECIES_INFO_ALL_100 = (151, 251, 409)                       # Mew, Celebi, Jirachi
BS38_SPECIES_INFO_HITS = (0x0824DE80, 0x0824E970, 0x0824FAB8)

# Found by scanning for GSPECIES_INFO itself and disassembling where the hits landed. CreateMon is
# identified instruction for instruction against [decomp:src/pokemon.c:1755], and by calling
# SetMonData with MON_DATA_LEVEL then MON_DATA_MAIL carrying MAIL_NONE.
CREATE_MON = 0x08041150             # void CreateMon(mon, species, level, fixedIV,
                                    #   hasFixedPersonality, fixedPersonality, otIdType, fixedOtId)
                                    # args 5..8 go on the stack; the first four are r0..r3
CREATE_BOX_MON = 0x080411C0         # the same signature on a struct BoxPokemon
ZERO_MON_DATA = 0x08041090          # CreateMon's first call
SET_MON_DATA = 0x08043A78           # SetMonData(mon, field, &value)
CALCULATE_MON_STATS = 0x08041B78    # CreateMon's last call

# Read out of a mon CreateMon built on the console: globals no link message carries.
GGAME_LANGUAGE = 3                  # LANGUAGE_FRENCH [decomp:include/constants/global.h:22]
GGAME_VERSION = 4                   # VERSION_FIRE_RED [:11]
# CreateBoxMon copies the nickname from the French gSpeciesNames [decomp:src/pokemon.c:1810], so
# one species a run is readable this way.
SPECIES_NAMES_READ = {59: "ARCANIN"}

# --- read off the console but NOT confirmed by disassembling the function itself -----------------
# Named by call count and by the shape of the access, which is weaker than the entries above. Kept
# apart so nothing downstream mistakes them for measurements.
PROBABLE = (
    # CreateBoxMon calls one function 20 times, which is what SetBoxMonData does there.
    ("SetBoxMonData", 0x08043BCC),
    # Indexed by move id at a 12-byte stride, offset 1 compared against zero: struct BattleMove's
    # `power` [decomp:include/pokemon.h].
    ("gBattleMoves", 0x0824927C),
    # Called with TRUE immediately before `Random() % 3` [battle_ai_switch_items.c:88].
    ("HasSuperEffectiveMoveAgainstOpponents", 0x0803CD94),
)

# --- the workers behind the field-script commands ------------------------------------------------
# One 1 KB dump of 0x0806DE00 covers 24 handlers, and each names its worker by position: the
# decomp's body is `VarGet(ScriptReadHalfword(ctx))` per argument and then one call
# [decomp:src/scrcmd.c:463-590]. Every address below is that call, matched instruction for
# instruction; ScrCmd_additem's `(u8)quantity` cast is visible as `lsls r1,#24; lsrs r1,#24`.
#
# The alignment check: ScrCmd_random's third call is 0x080486B0, which is RANDOM above, found
# independently from its own literal pool.
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

# --- the money workers ----------------------------------------------------------------------------
# A second 1 KB dump, of 0x0806F800. ScrCmd_addmoney, _removemoney, _checkmoney and _updatemoneybox
# each read their argument and then make one call through a pointer they build the same way:
# `ldr r0,[0x03004228]; ldr r0,[r0]; r1 = 0xA4 << 2; adds r0,r0,r1`, gSaveBlock1Ptr then &money
# [decomp:src/scrcmd.c, include/global.h:774].
#
# The alignment checks: that literal is 0x03004228, GSAVEBLOCK1PTR; 0xA4 << 2 is 0x290, which is
# `struct SaveBlock1.money`'s own offset; and ScrCmd_givemon in the same window calls 0x08071DDC,
# VarGet.
SCRIPT_READ_WORD = 0x0806D200        # u32 ScriptReadWord(ctx), the u32 sibling of ReadHalfword
GET_MONEY = 0x080A3764               # u32 GetMoney(u32 *money)
IS_ENOUGH_MONEY = 0x080A3794         # bool8 IsEnoughMoney(u32 *money, u32 cost)
ADD_MONEY = 0x080A37AC               # void AddMoney(u32 *money, u32 toAdd), capped at MAX_MONEY
REMOVE_MONEY = 0x080A37E4            # void RemoveMoney(u32 *money, u32 toSub), floored at 0
CHANGE_AMOUNT_MONEY_BOX = 0x080A39AC  # ScrCmd_updatemoneybox's second call

# Money is encrypted: `*moneyPtr ^ encryptionKey` [decomp:src/money.c:14], the key being
# gSaveBlock2Ptr->encryptionKey. A raw read of SAV1_MONEY is the ciphertext; the two together give
# the key.
SAV1_MONEY = 0x290                   # struct SaveBlock1.money [decomp:include/global.h:774]
SAV2_ENCRYPTION_KEY = 0xF20          # struct SaveBlock2.encryptionKey [:358]
# The literal ScrCmd_additem stores its result through, which is what gSpecialVar_Result must be.
GSPECIAL_VAR_RESULT = 0x020370CC

# The workers above by the decomp's own name, so a payload can be asked for one instead of a bare
# address. Everything here was read off the console or called on it; nothing rests on the decomp
# alone, whose addresses are a different build's. `callable_function` returns the THUMB pointer a
# `bx` needs.
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


# --- more workers, extracted with scratchpad/handler_workers.py -----------------------------------
# Every `bl` a handler makes, in order, against the decomp's body for that command. Two of the warp
# workers name themselves: the specials table calls 0x08081CC8 DoDiveWarp and 0x08081DA0
# DoFallWarp, so the two tables confirm each other without either being assumed.
#
# 0x0806D0EC is ScrCmd_end's one call, which the decomp gives as `StopScript(ctx)`
# [src/script.c:76]. `ScriptContext_Stop` is a different function taking no argument
# [src/script.c:360] at 0x0806D418, called by twelve handlers (waitstate, dowildbattle, multichoice,
# pokemart, yesnobox and others); `ScrCmd_waitstate` is `ScriptContext_Stop(); return TRUE;` and
# nothing else. The declaration order agrees: script.c:76 before script.c:360, 0x0806D0EC before
# 0x0806D418.
STOP_SCRIPT = 0x0806D0EC              # StopScript(ctx), what `end` and `endram` call
SCRIPT_CONTEXT_STOP = 0x0806D418      # ScriptContext_Stop(void), what the twelve waiters call
SCRIPT_CONTEXT_SET_NATIVE = 0x0806D0E4  # what gotonative/delay/fadescreen hand their function to

# --- the rest of the field-script workers ---------------------------------------------------------
# 213 of 213 bodies read off the console. Each is named by the commands that call it and the
# decomp's body for them, not by position; the caller count is the check, matching how many
# commands the decomp gives that call.
COMPARE = 0x0806DCCC                  # Compare(a, b) [scrcmd.c:355]; exactly the 8 compare_* commands
STRING_COPY = 0x0800C894              # the 7 buffer* commands, and the two specials that build a
                                      # name from gText_BigGuy/gText_Son
HIDE_FIELD_MESSAGE_BOX = 0x0806CDE4   # closemessage, release, releaseall - each calls it first
SCRIPT_MOVEMENT_START = 0x0809AE54    # ScriptMovement_StartObjectMovementScript; applymovement and
                                      # applymovementat, the two commands whose operand width
                                      # needs its own branch
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

# --- the decomp's own name for four addresses named here independently ----------------------------
# `scripts/gen_worker_names.py` zips a body's measured `bl` order against the decomp's call order
# for the same function. Each of these four is what every body that reaches the address agrees it
# is; the caller count is the evidence. The names used elsewhere in this file stay, so the
# citations in docs/ keep resolving.
DECOMP_NAMES = {
    GET_MON_DATA: "GetMonData3",          # 15 bodies. GetMonData is a macro that dispatches on the
                                          # argument count [include/pokemon.h:343] and GetMonData2
                                          # is an alias of GetMonData3 [pokemon.c:2970]: one symbol
    SET_RESPAWN: "SetLastHealLocationWarp",              # ScrCmd_setrespawn's one call
    SCRIPT_CONTEXT_SET_NATIVE: "SetupNativeScript",      # 11 bodies, every wait* command
    SCRIPT_MOVEMENT_START: "ScriptMovement_StartObjectMovementScript",   # applymovement(at)
    CHANGE_AMOUNT_MONEY_BOX: "ChangeAmountInMoneyBox",   # showmoneybox and updatemoneybox
    ME_CHECK_COMPATIBILITY: "CheckCompatibility",        # MEScrCmd_checkcompat's first call
    ME_SET_INCOMPATIBLE: "SetIncompatible",              # the one call both dead opcodes make
}

# Not callable from a buffer script: those run inside the Mystery Gift menu, where there is no
# overworld to warp. These belong to a field stub, which runs from the field engine.
# docs/frlg_rng.md has how a stub is staged.

# --- what the two cartridges share ----------------------------------------------------------------
# Four needles from FireRed dumps come back at the same address on LeafGreen (0x0806D7F4,
# 0x080701C0, 0x08071E1C, 0x08071FC4); the control is a fifth from inside AddBagItem, above the
# 0x0807D238 boundary, which comes back shifted -0x2C. So the gScriptCmdTable handler block
# 0x0806D7C0..0x080700B8, the script engine from 0x0806D0E4,
# GetVarPointer/VarGet/FlagSet/FlagClear/FlagGet and the special/callnative veneer are all at the
# same address on both cartridges.
#
# The shared region reaches 0x0807AF04, not 0x08071FC4: paired dumps hold 1225 call sites that did
# not move, the highest GetPlayerAvatarObjectId's caller at 0x0807AF04, and 283 that moved by -0x2C
# from 0x0807E068 up. `tools/frlg/cartridge_pair.py`; every one of those addresses is in
# `pokeldn/frlg/rom/leafgreen_twins.py`, read off its own cartridge.
SHARED_WITH_LEAFGREEN_THROUGH = 0x0807AF04
LEAFGREEN_ADD_BAG_ITEM = 0x0809DA44      # the rest of that block is -0x2C by segment

# --- gcc's THUMB-to-ARM call veneers ------------------------------------------------------------
# Client_RunBufferScript reaches our ARM payload through one of these, which is why lr comes back
# pointing into the caller rather than into the veneer.
CALL_VIA_R1 = 0x081E2228
CALL_VIA_R3 = 0x081E2230
# Deduced: the veneers are one THUMB `bx rN` plus alignment, four bytes each, and two are measured
# (r0 at 0x081E2224, r1 at 0x081E2228). That fixes the block by arithmetic: r2 0x081E222C, r3
# 0x081E2230 (measured, and it agrees), r4 0x081E2234, r5 0x081E2238, r6 0x081E223C. The tables
# reach r4 and r6.
CALL_VIA_R4 = 0x081E2234
CALL_VIA_R6 = 0x081E223C

# --- variables ----------------------------------------------------------------------------------
# Where CLI_RUN_BUFFER_SCRIPT copies our 1024 bytes and calls them. Deduced from ld_script.ld, then
# measured twice: `anchors` reads it from pc, and it is the first word of Client_RunBufferScript's
# literal pool.
GDECOMPRESSION_BUFFER = 0x0201C000

# The pointer variables in IWRAM, not the blocks they point at. SetSaveBlocksPointers re-rolls a
# random 4-aligned offset in 0..124 on every battle and every load [decomp:src/load_save.c:75]; the
# blocks were measured moving 76 bytes six minutes apart with no reboot.
#
# An absolute address into a save block is valid only until the next battle or load. Never carry one
# between runs; compute from the r1/r2 the console hands the payload every call, as save-dump,
# save-write and --create-mon-append do.
SAVEBLOCK_MOVE_RANGE = 128          # [decomp:src/load_save.c:15]
SAVEBLOCK_MOVE_MASK = (SAVEBLOCK_MOVE_RANGE - 1) & ~3        # 0x7C: 0..124 in steps of 4
GSAVEBLOCK1_SEEN = (0x0202553C, 0x0202559C, 0x02025550)      # three readings, one boot apart
GSAVEBLOCK2PTR = 0x0300422C
GSAVEBLOCK1PTR = 0x03004228

# The party the game plays with. `gSaveBlock1Ptr->playerParty` is a different array: SavePlayerParty
# copies gPlayerParty into it when the console saves [decomp:src/load_save.c:160], so a write there
# is erased by the console's own save. These are ordinary EWRAM globals fixed at link time and do
# not move.
GPLAYER_PARTY = 0x02024280          # struct Pokemon[6]
GPLAYER_PARTY_COUNT = 0x02024025    # u8
GENEMY_PARTY = 0x02024028           # struct Pokemon[6], 600 bytes below gPlayerParty

# The seed every random outcome in the game comes out of. Read out of Random's and SeedRng's
# literal pools and confirmed by its own recurrence. docs/frlg_rng.md.
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
# The second console is French LeafGreen, BPGF 0x0A. Every RAM address measured so far is the same
# as FireRed's; every ROM address above 0x080486C8 differs, and the divergence grows along the link
# order, so an address read low in the ROM says nothing about one read high in it.
#
# An address is LeafGreen's only when it was measured on LeafGreen. docs/frlg_leafgreen.md.
LEAFGREEN_GAME_CODE = b"BPGF"       # off the cartridge; FireRed is BPRF
LEAFGREEN_SOFTWARE_VERSION = 0x0A   # the same Switch revision as FireRed
LEAFGREEN = {
    # symbol: (address, provenance)
    "gDecompressionBuffer": (0x0201C000, "lg160"),
    "mystery_gift_call_site": (0x08148C50, "lg160"),   # FireRed 0x08148C74, so -0x24
    "Random": (0x080486B0, "lg162"),
    "SeedRng": (0x080486D0, "lg162"),
    "gRngValue": (0x03004220, "lg162"),                # named twice, from two independent pools
    "gPlayerParty": (0x02024280, "lg164"),             # found by finding a Pokemon in a dump
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

# The ROM delta is a property of a region. Scanning both consoles for RAND_MULT gives eleven hits
# each, in the same order, so the pairs give the delta at eleven points across 1.3 MB. There are at
# least three boundaries; a delta carried upward past one answers about nowhere.
LEAFGREEN_DELTA_SEGMENTS = (
    # (low, high, delta, evidence): the delta is measured at both ends of each span.
    #
    # Two blocks dumped at one address on both cartridges read the delta off each other directly: if
    # the delta is d the LeafGreen block holds the FireRed block shifted by d, and any |d| under a
    # kilobyte leaves hundreds of bytes of overlap. No needle and no guess about where the twin is,
    # which is what a bisection cannot do when the delta is the unknown. docs/frlg_leafgreen.md.
    (0x08000000, 0x0807CF68, 0x00, "paired blocks read delta 0 to the last window; 1225 paired "
     "call sites below it"),
    (0x0807D1EC, 0x080DE2E4, -0x2C, "paired blocks at 0x0807D000 and 0x080DE000, both ends inside "
     "one block"),
    (0x080DE322, 0x081480CE, -0x28, "paired blocks at 0x080DE000 and 0x08148000, both boundaries "
     "inside a block"),
    (0x08148128, 0x08251D8E, -0x24, "paired blocks at 0x08148000 and 0x08251C00"),
    (0x08251DAD, 0x083B7B47, -0x20, "the step at 0x08251C00 read 31 bytes wide; a paired block at "
     "0x083B7800 above"),
    (0x083B8000, 0x0843AFFF, -0x1C4, "0x083B8000 matches -0x1C4 from its first window; 0x0843AC00, "
     "888 of 888 bytes, is the highest point that does"),
    # The step from -0x1C4 to -0x12D8 across 421 KB is three segments, not one. Each is separated
    # from its neighbours by a clean margin: at 0x08442800 the -0x124C reading is 436 of 436 where
    # -0x1240 is 6.9% and -0x12D8 is 2.7%, so a repeating graphics pattern matching at two shifts is
    # ruled out by the numbers.
    (0x08442800, 0x08442BFF, -0x124C, "FireRed 0x08442800 against LeafGreen 0x08441800, 436 of 436 "
     "bytes. One point; the segment's extent is not measured"),
    (0x08447000, 0x0844F3FF, -0x1240, "900/1012 at 0x08447000 and 980/1012 at 0x0844F000, two "
     "points 32 KB apart, each with the other two deltas under 23%"),
    (0x0845F000, 0x086803FC, -0x12D8, "0x0845F000, 0x08467000, 0x0846F000 and 0x08477000, two of "
     "them 884 of 884 bytes; 0x0847DC00, and three paired points above it"),
)

# The high segment is measured without knowing a symbol up there: dump 1 KB off one console, pick a
# word that occurs exactly once in it and has four distinct bytes, then scan a window on the other
# console for that word; the address it comes back at is the delta. Two runs a point, anywhere in
# the ROM. 0xE1926F4D pairs FireRed 0x08600000 with LeafGreen 0x085FF108 and 0xC35D61AE pairs
# 0x08680000 with 0x0867F124, both -0x12D8 and half a megabyte apart, which makes it a segment and
# not a point.
#
# FireRed's ROM data ends between 0x08680400 and 0x08800000: 0x08800000 reads all 0xFF and
# 0x08E00000 all 0x00, while 0x08680000 is high-entropy data. gSongTable's headers point to
# 0x086A9930..0x086ABE68, so the data runs at least that far.

# The low end of that segment comes from a literal pool, which pairs the way a pointer table does
# and reaches places no table indexes. m4a's code is in lib_text, which starts at 0x081DE188 and
# sits inside the -0x24 segment, so the same window on LeafGreen is at -0x24 exactly. FireRed
# 0x081DF200 against LeafGreen 0x081DF1DC lines up word for word (13 of 24 identical, the RAM
# addresses and the constants), and the five cartridge pointers all move by -0x12D8:
#
#   0x0847DCF8 -> 0x0847CA20      0x0847DDAC -> 0x0847CAD4     0x0847DF10 -> 0x0847CC38
#   0x0849758C -> 0x084962B4      0x084975BC -> 0x084962E4      (gMPlayTable, gSongTable)
#
# gMPlayTable and gSongTable are 0x30 apart, 4 music players of 12 bytes
# [decomp:include/gba/m4a_internal.h:352, sound/music_player_table.inc], so the pair proves its own
# alignment. Five points, not one.
#
# The -0x1C4 segment is measured the same way off a 16-block dump, which is 16 KB of literal pools.
# 0x08081CC8 on FireRed (the warp and battle-start specials) against the same code on LeafGreen at
# -0x2C, the delta that segment is known to have. Pair by CODE OFFSET, not by index: the two pools
# hold 552 and 550 words, so index-pairing drifts after the first mismatch and invents deltas.
# 550 sites, 369 of them identical (the RAM addresses and the constants, which is the alignment
# proof) and:
#
#   27 cartridge pointers, 0x083BEE74..0x0841463E, ALL -0x1C4
#    2 cartridge pointers at 0x082370FC, both -0x24
#
# The second pair is the control: 0x082370FC is inside the measured -0x24 segment, so anything
# else there would be answering about the wrong console. The 27 carry both ends of the -0x1C4
# segment outwards at once.
G_MPLAY_TABLE = 0x0849758C          # struct MusicPlayer[4]
G_SONG_TABLE = 0x084975BC           # struct Song[347], {const u32 *header; u16 ms; u16 me}

# Where each boundary is comes from the same measurement. Scanning each console for its own
# gSpeciesInfo (LeafGreen 0x0824CDD8, FireRed 0x0824CDFC) over the whole ROM gives every
# literal-pool reference to the species table, 56 hits each, pairing one to one and giving the
# delta at 56 points. Three boundaries and no more are visible in 0x08000000..0x0815A630, as high
# as a reference to that table goes.
#
# A boundary read this way is the span between the last paired hit at one delta and the first at
# the next. It is not located to the byte; halving one needs a needle known to sit inside it.
LEAFGREEN_DELTA_BOUNDARIES = (
    # (from_delta, to_delta, low, high, evidence)
    #
    # A boundary is the divergent region itself: the version-specific code inside one object,
    # where the two builds hold different bytes and no delta describes anything. Each span below is
    # measured as the last window that still matches at the old delta and the first that matches at
    # the new. The English build brackets five of them independently and lands inside every one
    # (docs/frlg_leafgreen.md).
    (0x00, -0x2C, 0x0807CF68, 0x0807D1EC, "644 bytes, inside title_screen.o's version-specific "
     "code"),
    (-0x2C, -0x28, 0x080DE2E4, 0x080DE322, "both sides in one block at 0x080DE000: 62 bytes, in "
     "mystery_event_script.o"),
    (-0x28, -0x24, 0x081480CE, 0x08148128, "both sides in one block at 0x08148000: 90 bytes, in "
     "mystery_gift.o"),
    (-0x24, -0x20, 0x08251D8E, 0x08251DAD, "both sides in one block at 0x08251C00: 31 bytes, in "
     "pokemon.o's rodata"),
    (-0x20, -0x1C4, 0x083B7B47, 0x083B8000, "0x083B7800 below and 0x083B8000 above; 0x083B7C00 "
     "matches neither delta, which is the divergence itself"),
    (-0x1C4, -0x124C, 0x0843AFFF, 0x08442800, "-0x1C4 to the last window of 0x0843AC00; "
     "0x0843B400 onwards matches nothing at any shift a paired block can see"),
    (-0x124C, -0x1240, 0x08442BFF, 0x08447000, "paired blocks either side"),
    (-0x1240, -0x12D8, 0x0844F3FF, 0x0845F000, "paired blocks either side; 0x08457000 in the "
     "middle reads 74.7% at -0x1240 against 57.3% at -0x124C, which is graphics resembling itself "
     "and not a verdict"),
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


# --- gSpecials as the console holds it -------------------------------------------------------------
# All 444 entries, read in two dumps at G_SPECIALS and G_SPECIALS + 1024.
# pokeldn/special_names.SPECIALS names them by index; `special_function(name)` resolves one to a
# THUMB pointer.
#
# The dump proves its own alignment: every word came back a THUMB pointer into the cartridge, and
# the 128 indices this half calls NullFieldSpecial all came back with one address (0x080CE8DC).
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
    # --- indices 256..443, the rest of the table -------------------------------------------
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


# --- the specials' bodies ---------------------------------------------------------------------------
# The code at the densest 2 KB of the table, 31 distinct bodies
# (`tools/frlg/rom_functions.py --table specials`), which turns the decomp's table order from an
# assumption into a measurement. A body is named by what it calls, not by where it sits, and each of
# these lands on a function measured independently:
#
#   SetHiddenItemFlag [150]           -> FlagSet
#   GiveLeadMonEffortRibbon [293]     -> IncrementGameStat, FlagSet, SetMonData
#   GetRandomSlotMachineId [286]      -> Random
#   IsStarterFirstStageInParty [302]  -> VarGet, and special 131 CalculatePlayerPartyCount
#   PlayerHasGrassPokemonInParty[299] -> gSpeciesInfo
#   ShowDiploma [264], ShowTownMap    -> special 392 QuestLog_CutRecording
#
# The last two are the specials table naming its own entries (DoDiveWarp is special 318).
NULL_FIELD_SPECIAL = 0x080CE8DC     # `bx lr`, two bytes; 171 of the 444 indices point at it, and
                                    # a dump read at a wrong offset could not produce that
GET_LEAD_MON_INDEX = 0x080CE818     # CalculatePlayerPartyCount, then GetMonData twice - command
                                    # for command the decomp's body [src/field_specials.c]. Four
                                    # lead-mon specials (230, 292, 293, 294) call it.

# The EWRAM a special reaches for, read out of the literal pools rather than searched for.
GSTRING_VAR1 = 0x02021CD0           # BufferBigGuyOrBigGirlString and BufferSonOrDaughterString
                                    # StringCopy into it [field_specials.c:140]; the Mystery Event
                                    # VM's setenigmaberry loads the same address
GSTRING_VAR4 = 0x02021D18           # ShowFieldMessageStringVar4 [141] passes it to
                                    # ShowFieldMessage, so the special names the global it loads
                                    # [field_specials.c:122]
GBATTLE_OUTCOME = 0x02023E86        # GetBattleOutcome [180] is `ldr; ldrb; bx lr` and nothing else

# The var layout: ShakeScreen [310] takes four arguments and loads 0x020370BC, BE, C0 and C2, four
# consecutive halfwords in one body, and the decomp's ShakeScreen reads
# gSpecialVar_0x8004..0x8007. GetPlayerXY [143] writes the first two; GetPartyMonSpecies [327] and
# SetHiddenItemFlag [150] read the first. So the vars are laid out in id order at 2 bytes each, and
# 0x8004 is 8 bytes past 0x8000.
G_SPECIAL_VAR_0X8004 = G_SPECIAL_VAR_0X8000 + 8     # 0x020370BC, four bodies agreeing
G_SPECIAL_VAR_0X8005 = G_SPECIAL_VAR_0X8000 + 10    # 0x020370BE
G_SPECIAL_VAR_0X8006 = G_SPECIAL_VAR_0X8000 + 12    # 0x020370C0
G_SPECIAL_VAR_0X8007 = G_SPECIAL_VAR_0X8000 + 14    # 0x020370C2


def special_function(name, addresses=None):
    """-> the THUMB pointer for a special by the decomp's name."""
    from pokeldn.frlg.rom import special_names
    index = special_names.index(name)
    table = SPECIAL_ADDRESSES if addresses is None else addresses
    if index >= len(table):
        raise KeyError(f"{name!r} is special {index}, past the {len(table)} entries measured")
    return thumb(table[index])
