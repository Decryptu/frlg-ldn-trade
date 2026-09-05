@ FIELD STUB: mon-seek-both, made to REPORT. It writes what it did into the save.
@
@ WHY. Everything mev19-mev21 learned about a hunt was reconstructed AFTER the fact from the mon
@ the player caught: brute-force 2**16 candidate states out of the PID, then read which pair of
@ draws the IVs came from. bs64 came back with TWO candidate states and only the IVs told them
@ apart. And the only measurement of how long the overworld froze was the player with a stopwatch.
@ None of that has to be inferred - the stub knows all of it while it runs.
@
@ WHERE IT WRITES: gSaveBlock1Ptr + 0x348C, `u8 unused_348C[400]` [decomp:include/global.h], read
@ back as 400 zero bytes off this console at bs65 before anything was ever written there. It is IN
@ THE SAVE, so it survives the battle - MoveSaveBlocks_ResetHeap copies the blocks rather than
@ abandoning them [decomp:src/load_save.c] - and it reaches flash when the player saves. It is NOT
@ in ramScript, so it does not disturb CalculateRamScriptChecksum and the binding still survives:
@ the player can talk to their MOM again and the log is simply overwritten.
@
@     +0   marker      0x474F4C31, so a zero region is told apart from a run that wrote zeros
@     +4   start       gRngValue as the stub found it
@     +8   found       the state written back, or 0 if the cap was exhausted
@     +12  iterations  p_cap minus what was left, so the search length is exact
@     +16  cap         what it was allowed, so the dump is self-describing
@
@ WHAT ONE RUN THEN SETTLES:
@   - the found state EXACTLY, with no brute-force recovery and no ambiguity between candidates;
@   - which stray-draw method fired, by comparing the caught mon against draws from `found` -
@     measured every run instead of inferred from the four we happen to have;
@   - the exact instruction count (iterations * 15), which against the player's stopwatch is the
@     first real measurement of CYCLES_PER_INSTRUCTION_FROM_EWRAM. docs/rng.md carries 3 as an
@     estimate from the GBA's clock and mev20/mev21 both ran high against it.
@
@ A MISS IS NOW INFORMATIVE TOO. If the cap is exhausted, `found` stays 0 and `iterations` says the
@ whole cap was spent - so an ordinary encounter is distinguishable from a stub that never ran at
@ all, which until now looked identical from the player's side.
@
@ THE LOG COSTS ABOUT FIFTY BYTES and is affordable for exactly one reason: the payload lives in
@ the RAM script body at one script byte each [asm/field/ram-jump.s], so there are 755 bytes here
@ and not 162. mon-seek-both stays as it is and is the control.

    .syntax unified
    .text
    .thumb
    .global _start
    .thumb_func
_start:
    push    {r4-r7, lr}

@ Did the tail of the body arrive? Sum p_padlen filler bytes sitting immediately after this stub.
@ r2 = our own end, from `adr`, so nothing here depends on where the host put the code.
    adr     r2, .Lpadbase
    ldr     r3, p_padlen
    movs    r1, #0
    cmp     r3, #0
    beq     .Lpadok
.Lpadsum:
    subs    r3, r3, #1
    ldrb    r4, [r2, r3]
    adds    r1, r1, r4
    cmp     r3, #0
    bne     .Lpadsum
.Lpadok:
    ldr     r4, p_padsum
    cmp     r1, r4
    beq     .Lsearch
    pop     {r4-r7, pc}             @ the tail is not there: leave gRngValue alone

.Lsearch:
@ Open the log before searching, so that even a run that finds nothing says what it spent.
    ldr     r4, p_sb1ptr
    ldr     r4, [r4]                @ SaveBlock1 base; fixed for this frame
    ldr     r2, p_logoff
    adds    r4, r4, r2              @ the record
    ldr     r2, p_logmagic
    str     r2, [r4, #0]
    ldr     r2, p_rng
    ldr     r2, [r2]
    str     r2, [r4, #4]            @ the state we started from
    ldr     r2, p_cap
    str     r2, [r4, #16]
    movs    r2, #0
    str     r2, [r4, #8]            @ found: 0 until there is one
    str     r2, [r4, #12]           @ iterations: filled in on success

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

@ THREE draws now, not two. S2 is still in r1, so they continue from the personality.
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S3
    lsls    r4, r1, #1
    lsrs    r4, r4, #17             @ d3, bits 0..14
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S4
    lsls    r2, r1, #1
    lsrs    r2, r2, #17             @ d4, bits 0..14
    muls    r1, r5, r1
    adds    r1, r1, r6              @ S5
    lsrs    r1, r1, #16
    lsls    r1, r1, #15             @ d5, bits 15..29

    orrs    r1, r1, r2              @ word B = d4 | d5<<15   (Method 2's placement)
    lsls    r2, r2, #15
    orrs    r4, r4, r2              @ word A = d3 | d4<<15   (Method 1's placement)

@ Every IV at or above its floor, in BOTH words. Each field is shifted UP to bits 27..31, which
@ discards its neighbours in one instruction and leaves an ordinary unsigned comparison.
    push    {r1}                    @ word B, checked second
    ldr     r1, p_ivmin
.LivA:
    lsls    r2, r4, #27
    lsls    r5, r1, #27             @ r5 was RAND_MULT; .Lreject loads it back
    cmp     r2, r5
    blo     .LrejectA
    lsrs    r4, r4, #5
    lsrs    r1, r1, #5
    cmp     r1, #1                  @ the terminator from bit 30 has reached bit 0: six done
    bne     .LivA

    pop     {r4}                    @ word B
    ldr     r1, p_ivmin
.LivB:
    lsls    r2, r4, #27
    lsls    r5, r1, #27
    cmp     r2, r5
    blo     .Lreject
    lsrs    r4, r4, #5
    lsrs    r1, r1, #5
    cmp     r1, #1
    bne     .LivB

.Lfound:
    ldr     r4, p_rng
    str     r0, [r4]
    ldr     r4, p_sb1ptr
    ldr     r4, [r4]
    ldr     r2, p_logoff
    adds    r4, r4, r2
    str     r0, [r4, #8]            @ the state the encounter will consume
    ldr     r2, p_cap
    subs    r2, r2, r3              @ what the search actually cost, to within the last iteration
    str     r2, [r4, #12]
    pop     {r4-r7, pc}

.LrejectA:
    add     sp, #4                  @ word A failed: drop word B, the stack must balance
.Lreject:
    ldr     r5, p_mult
    b       .Lnext

    .align 2
    .global p_rng, p_mult, p_add, p_sav2ptr, p_cap, p_nature, p_ivmin, p_padlen, p_padsum
    .global p_sb1ptr, p_logoff, p_logmagic
p_rng:  .word 0x03004220            @ gRngValue [rom_map.GRNG_VALUE, bs14/bs15]
p_mult: .word 0x41C64E6D            @ RAND_MULT [decomp:include/random.h:18]
p_add:  .word 0x00006073            @ RAND_ADD  [:19]
p_sav2ptr: .word 0x0300422C         @ &gSaveBlock2Ptr [rom_map.GSAVEBLOCK2PTR]
p_cap:  .word 0x00040000            @ patched: iteration cap
p_nature: .word 0x01FFFFFF          @ patched: bit N set = nature N accepted; this is "any"
p_ivmin: .word 0x40000000           @ patched: six 5-bit floors + the terminator at bit 30
p_padlen: .word 0x00000000          @ patched: filler bytes following this stub in the body
p_padsum: .word 0x00000000          @ patched: their 32-bit wrapping sum
p_sb1ptr: .word 0x03004228          @ &gSaveBlock1Ptr [rom_map.GSAVEBLOCK1PTR]
p_logoff: .word 0x0000348C          @ SaveBlock1 -> unused_348C[400]; bs65 read it all zero
p_logmagic: .word 0x474F4C31        @ so an untouched region is not mistaken for a report

    .align 2
.Lpadbase:                          @ emits nothing: the filler starts here, at len(the stub)
