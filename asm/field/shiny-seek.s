@ FIELD STUB: advance gRngValue to a state whose next encounter is SHINY.
@
@ This is not a buffer script. Nothing here is sent through CLI_RUN_BUFFER_SCRIPT; it is staged
@ into EWRAM one byte at a time by a RAM SCRIPT and reached with `callnative`, so it runs in the
@ OVERWORLD - the one place our native code could never reach [docs/rng.md].
@
@ WHY THE OVERWORLD CHANGES THE ANSWER. docs/rng.md calls hand-aiming structurally closed, and
@ that paragraph is about FIELD BYTECODE: `compare` and `goto_if` cannot walk an LCG or test for
@ shininess, so a target has to be computed before the trip and the title screen reseeds on the
@ way out of Mystery Gift. A staged native stub is not field bytecode. It does the search itself,
@ at the moment of the encounter, from whatever state the console is actually in - so there is no
@ target to go stale, no reseed to survive and no press to aim. The player talks to an NPC.
@
@ THE TWO COMMANDS RUN IN THE SAME FRAME, WHICH IS WHAT MAKES THIS EXACT.
@
@     bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
@     { void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
@     bool8 ScrCmd_setwildbattle(struct ScriptContext * ctx)   // 0xB6
@     { ... CreateScriptedWildMon(species, level, item); return FALSE; }
@ [decomp:src/scrcmd.c:120, :1935]
@
@ Both return FALSE, so ScriptContext_RunScript runs them back to back without yielding a frame
@ and without returning to the main loop. Nothing between them draws. The state this stub leaves
@ in gRngValue is the state CreateScriptedWildMon consumes.
@
@ WHAT CreateScriptedWildMon DRAWS [decomp:src/script_pokemon_util.c:128]:
@
@     CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0);
@
@ hasFixedPersonality is 0, so CreateBoxMon takes `personality = Random32()` - TWO draws, low half
@ first at this call site (measured, bs58) - and otIdType is OT_ID_PLAYER_ID, which READS
@ gSaveBlock2Ptr->playerTrainerId and draws NOTHING [decomp:src/pokemon.c]. fixedIV is 32, which is
@ not < USE_RANDOM_IVS, so the two IV draws follow. Shininess therefore depends on the FIRST TWO
@ draws only, which is all this stub computes:
@
@     shinyValue = TID ^ SID ^ (personality >> 16) ^ (personality & 0xFFFF) < SHINY_ODDS (8)
@
@ THE TRAINER ID IS READ OFF THE CONSOLE, NOT PATCHED IN BY THE HOST. gSaveBlock2Ptr is a POINTER
@ at a fixed IWRAM address (0x0300422C); the block it points at carries a re-rolled ASLR offset and
@ moves on every battle and load [SetSaveBlocksPointers, decomp:src/load_save.c:75, measured
@ bs45/bs46], so the stub dereferences the pointer every call and reads playerTrainerId at +0x0A
@ [struct SaveBlock2, decomp:include/global.h:327; the offset bs04 already used]. That makes the
@ stub console-agnostic: the same bytes are correct on FireRed and on LeafGreen, and no id has to
@ be known, typed or kept in step with anything.
@
@ THUMB, NOT ARM, AND THE REASON IS THE BUDGET. Every byte staged into EWRAM costs SIX bytes of
@ RAM script (`setptr` is opcode + immediate + a 4-byte address [decomp:src/scrcmd.c:300]) out of
@ the 995 a RAM script has [struct RamScriptData, decomp:include/global.h:439]. Thumb halves the
@ code, so it halves the only budget that binds. `callnative` calls through a function pointer, so
@ the address staged into the script carries bit 0 set and the CPU enters Thumb state.
@
@ IT NEVER HANGS. The search is bounded by `p_cap`; on exhaustion gRngValue is left EXACTLY as it
@ was and the encounter is an ordinary one. A stub that looped for ever would freeze the overworld
@ with no menu to back out of, which is worse than the Mystery Gift hang buffer scripts risk.
@
@ IT WRITES ONE WORD, gRngValue, and reads nothing else. Not the save, not the party.

    .syntax unified
    .text
    .thumb
    .global _start
    .thumb_func
_start:
    push    {r4-r7, lr}
    ldr     r4, p_rng               @ &gRngValue
    ldr     r5, p_mult              @ RAND_MULT
    ldr     r6, p_add               @ RAND_ADD
    ldr     r3, p_cap               @ how many states to try before giving up
    ldr     r0, p_sav2ptr           @ &gSaveBlock2Ptr, fixed in IWRAM
    ldr     r0, [r0]                @ gSaveBlock2Ptr - the BLOCK moves, the pointer does not
    ldrh    r1, [r0, #0xA]          @ playerTrainerId[0..1] = TID
    ldrh    r7, [r0, #0xC]          @ playerTrainerId[2..3] = SID
    eors    r7, r7, r1              @ TID ^ SID, the half of the shiny test that is not the PID
    ldr     r0, [r4]                @ S, the state the console is in right now

.Lloop:
    movs    r1, r0
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S1 = S*M + A
    lsrs    r2, r1, #16             @ draw 1 -> the personality's LOW half
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S2 = S1*M + A
    lsrs    r1, r1, #16             @ draw 2 -> the personality's HIGH half
    eors    r2, r2, r1
    eors    r2, r2, r7              @ TID ^ SID ^ pidLo ^ pidHi
    cmp     r2, #8                  @ SHINY_ODDS [decomp:include/constants/pokemon.h]
    blo     .Lfound
    muls    r0, r5, r0
    adds    r0, r0, r6              @ try the next state
    subs    r3, r3, #1
    bne     .Lloop
    pop     {r4-r7, pc}             @ cap exhausted: gRngValue untouched, ordinary encounter

.Lfound:
    str     r0, [r4]
    pop     {r4-r7, pc}

    .align 2
    .global p_rng, p_mult, p_add, p_sav2ptr, p_cap
p_rng:  .word 0x03004220            @ gRngValue [rom_map.GRNG_VALUE, bs14/bs15]
p_mult: .word 0x41C64E6D            @ RAND_MULT [decomp:include/random.h:18]
p_add:  .word 0x00006073            @ RAND_ADD  [:19]
p_sav2ptr: .word 0x0300422C         @ &gSaveBlock2Ptr [rom_map.GSAVEBLOCK2PTR]
p_cap:  .word 0x00040000            @ patched: iteration cap
