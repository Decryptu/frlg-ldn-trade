@ FIELD STUB: advance gRngValue to a state whose next encounter is SHINY, of a NATURE we asked
@ for, and with every IV at or above a floor we chose.
@
@ asm/field/shiny-seek.s is this stub's ancestor and stays exactly as it is: it is the one PROVEN
@ ON HARDWARE (mev15, mev16, three shinies), so it remains the control. Everything in its header
@ about the mechanism holds here unchanged - staged a byte at a time by a RAM script with `setptr`
@ (0x11) and reached with `callnative` (0x23), both of which return FALSE, so the search, the
@ `setwildbattle` and the `dowildbattle` all happen in ONE pass of the field engine with nothing
@ between them that can draw. The state this stub leaves in gRngValue is the state
@ CreateScriptedWildMon consumes. Read that file first; this one only adds tests.
@
@ WHAT IS NEW: the four draws are all four, not the first two.
@
@     CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)
@     [decomp:src/script_pokemon_util.c:128]
@
@ fixedIV is 32 and USE_RANDOM_IVS is MAX_PER_STAT_IVS + 1 = 32 [decomp:include/constants/
@ pokemon.h:232], so `fixedIV < USE_RANDOM_IVS` is FALSE and the IVs are drawn
@ [decomp:src/pokemon.c:1836]:
@
@     personality = Random32()   -> draws 1 and 2, low half first at this call site (bs58)
@     value = Random()           -> draw 3: HP = v & 31, ATK = (v >> 5) & 31, DEF = (v >> 10) & 31
@     value = Random()           -> draw 4: SPE = v & 31, SPATK = (v >> 5) & 31, SPDEF = (v >> 10) & 31
@
@ and the nature is `personality % NUM_NATURES`, NUM_NATURES = 25 [decomp:src/pokemon.c:5020,
@ include/constants/pokemon.h:163]. Nothing between the personality and the IVs draws: the
@ SetBoxMonData calls in between read the save and the species tables and turn the RNG not at all.
@ So a state decides the whole mon, and the three tests here are the whole mon.
@
@ THE FILTER ORDER IS THE COST MODEL. Shininess is 8 in 65536 and it is tested in the hot loop,
@ where the fifteen instructions of an iteration are the whole search rate; the nature and the IVs
@ are tested in a block that only 1 state in 8192 ever reaches, so the 28-iteration division and
@ the six IV comparisons cost nothing on average. Adding a criterion multiplies the SEARCH, never
@ the iteration: `native_script.search_cost` computes the expected frames from that, and the host
@ refuses a combination whose search would freeze the overworld for longer than it allows.
@
@ THE PARAMETERS, all patched by the host into the pool at the end [scripts/gen_field_stubs.py
@ records the offsets from the assembler]:
@
@     p_nature   a 25-bit mask, bit N set = nature N is acceptable. 0x01FFFFFF is "any".
@     p_ivmin    six 5-bit floors in DRAW order (HP, ATK, DEF, SPE, SPATK, SPDEF) at bits
@                0, 5, 10, 15, 20, 25, PLUS A TERMINATOR AT BIT 30. The loop shifts the word
@                right five bits an iteration and stops when the terminator reaches bit 0, so
@                the count is carried in the word instead of in a register there is not one of
@                (`native_script.MonCriteria.iv_word` sets it; a test asserts it).
@
@ THE BUDGET IS THE ONLY THING THAT BINDS, and this stub is near it: 995 bytes of RAM script at
@ SIX per staged byte, less the call and the battle, is 163 bytes. That is why the registers are
@ reused as hard as they are below, why the trainer id is read through a pointer instead of being
@ passed, and why the division by 25 is eight instructions of shift-and-subtract rather than a
@ table. `native_script.budget` states it from the numbers; nothing here has to be believed.
@
@ IT NEVER HANGS. The search is bounded by p_cap; on exhaustion gRngValue is left EXACTLY as it
@ was and the player gets an ordinary encounter, which is a miss and not a broken game.
@
@ IT WRITES ONE WORD, gRngValue. It reads gSaveBlock2Ptr and the trainer id behind it, nothing else.

    .syntax unified
    .text
    .thumb
    .global _start
    .thumb_func
_start:
    push    {r4-r7, lr}
    ldr     r5, p_mult              @ RAND_MULT
    ldr     r6, p_add               @ RAND_ADD
    ldr     r3, p_cap               @ states to try before giving up
    ldr     r0, p_sav2ptr           @ &gSaveBlock2Ptr, fixed in IWRAM
    ldr     r0, [r0]                @ gSaveBlock2Ptr - the BLOCK moves, the pointer does not
    ldrh    r1, [r0, #0xA]          @ playerTrainerId[0..1] = TID
    ldrh    r7, [r0, #0xC]          @ playerTrainerId[2..3] = SID
    eors    r7, r7, r1              @ TID ^ SID, the half of the shiny test that is not the PID
    ldr     r0, p_rng
    ldr     r0, [r0]                @ S, the state the console is in right now

@ The hot loop. Shininess only: 8 states in 65536 reach .Lcandidate.
.Lloop:
    movs    r1, r0
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S1 = S*M + A
    lsrs    r2, r1, #16             @ draw 1 -> the personality's LOW half
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S2 = S1*M + A, KEPT: the IV draws continue from it
    lsrs    r4, r1, #16             @ draw 2 -> the personality's HIGH half, KEPT
    eors    r2, r2, r4
    eors    r2, r2, r7              @ TID ^ SID ^ pidLo ^ pidHi
    cmp     r2, #8                  @ SHINY_ODDS [decomp:include/constants/pokemon.h:185]
    blo     .Lcandidate
.Lnext:
    muls    r0, r5, r0
    adds    r0, r0, r6              @ try the next state
    subs    r3, r3, #1
    bne     .Lloop
    pop     {r4-r7, pc}             @ cap exhausted: gRngValue untouched, ordinary encounter

@ Shiny. r0 = S, r1 = S2, r2 = the shiny value, r4 = pidHi, r7 = TID ^ SID.
.Lcandidate:
    eors    r2, r2, r7
    eors    r2, r2, r4              @ back to pidLo: the shiny value is its own inverse
    lsls    r4, r4, #16
    orrs    r2, r2, r4              @ r2 = personality

@ nature = personality % 25, by restoring division: subtract 25 << k for k = 27 down to 0.
@ 25 << 27 is 0xC8000000 and 25 << 28 does not fit in 32 bits, so 27 is where a u32 starts.
    movs    r4, #25
    lsls    r4, r4, #27
.Lmod:
    cmp     r2, r4
    blo     .Lmodnext
    subs    r2, r2, r4
.Lmodnext:
    lsrs    r4, r4, #1
    cmp     r4, #25                 @ the divisor itself is the counter: stop after 25 << 0
    bhs     .Lmod                   @ r2 = the nature, 0..24

    ldr     r4, p_nature
    lsrs    r4, r4, r2              @ the mask, rotated so the nature we have is bit 0
    lsrs    r4, r4, #1              @ ... and out into the carry
    bcc     .Lreject                @ not a nature we asked for

@ The IV draws. S2 is still in r1, so they continue from where the personality stopped.
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S3
    lsls    r4, r1, #1
    lsrs    r4, r4, #17             @ draw 3, bits 0..14: HP, ATK, DEF
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S4
    lsrs    r1, r1, #16
    lsls    r1, r1, #15             @ draw 4, bits 15..29: SPE, SPATK, SPDEF
    orrs    r4, r4, r1              @ r4 = the six IVs, five bits each, in draw order

@ Every IV at or above its floor. Both fields are shifted UP to bits 27..31, which discards the
@ five bits' neighbours in one instruction each and leaves the comparison an ordinary unsigned one.
    ldr     r1, p_ivmin
.Liv:
    lsls    r2, r4, #27
    lsls    r5, r1, #27             @ r5 was RAND_MULT; .Lreject loads it back
    cmp     r2, r5
    blo     .Lreject
    lsrs    r4, r4, #5
    lsrs    r1, r1, #5
    cmp     r1, #1                  @ the terminator from bit 30 has reached bit 0: six done
    bne     .Liv

.Lfound:
    ldr     r4, p_rng
    str     r0, [r4]
    pop     {r4-r7, pc}

.Lreject:
    ldr     r5, p_mult
    b       .Lnext

    .align 2
    .global p_rng, p_mult, p_add, p_sav2ptr, p_cap, p_nature, p_ivmin
p_rng:  .word 0x03004220            @ gRngValue [rom_map.GRNG_VALUE, bs14/bs15]
p_mult: .word 0x41C64E6D            @ RAND_MULT [decomp:include/random.h:18]
p_add:  .word 0x00006073            @ RAND_ADD  [:19]
p_sav2ptr: .word 0x0300422C         @ &gSaveBlock2Ptr [rom_map.GSAVEBLOCK2PTR]
p_cap:  .word 0x00040000            @ patched: iteration cap
p_nature: .word 0x01FFFFFF          @ patched: bit N set = nature N accepted; this is "any"
p_ivmin: .word 0x40000000           @ patched: six 5-bit floors + the terminator at bit 30
