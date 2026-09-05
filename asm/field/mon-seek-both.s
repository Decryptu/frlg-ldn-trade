@ FIELD STUB: mon-seek-far, made to hold against the STRAY DRAW.
@
@ WHY. mev20 delivered 995 bytes into the body and the search ran - a shiny JOLLY MAGIKARP, from a
@ state that could only have been found by testing all three criteria. Its SPEED came out 10 against
@ a floor of 20, and the reason is not this code:
@
@     state 0x429D2189, the unique state whose draws 1,2 are that PID
@       draws 3,4 -> 15/0/12/25/7/14      what the stub tested: speed 25, PASSES
@       draws 4,5 -> 25/7/14/10/10/30     the mon that actually appeared
@
@ ONE EXTRA Random() ran between the personality draw and the IV draws. `CreateBoxMon` has no draw
@ there [decomp:src/pokemon.c], and docs/rng.md already records this as measured and unexplained for
@ WILD encounters - bs51's Weedle (Method 2, the stray before the IVs), bs52 and bs54 (Method 4,
@ between the IV draws). What mev20 adds is that it happens on a SCRIPTED encounter too: bs53's
@ Ditto was clean and so was mev19, so it is intermittent there rather than absent. A search that
@ assumes one placement is right most of the time and silently wrong the rest.
@
@ THE FIX, AND WHY TWO TESTS COVER THREE METHODS. Let d3, d4, d5 be the three draws after the
@ personality. The first IV triple (HP, ATK, DEF) and the second (SPE, SPATK, SPDEF) come from:
@
@     Method 1 (clean)     first d3, second d4
@     Method 2 (mev20)     first d4, second d5
@     Method 4 (bs52/54)   first d3, second d5
@
@ This stub builds word A = d3 | d4<<15 and word B = d4 | d5<<15 and requires the floors to hold in
@ BOTH. That puts the first triple's floors on d3 (from A) and d4 (from B), and the second triple's
@ on d4 (from A) and d5 (from B) - so every one of the three methods is covered, Method 4 included,
@ without ever building its word. Two tests, three methods, and the proof is the four placements.
@
@ WHAT IT COSTS is search and not iteration: the hot loop is the same fifteen instructions, and the
@ IV block is only reached by 1 state in 8192. The IV term is SQUARED, so shiny + Jolly + SPEED >= 20
@ goes from 1 state in 546,000 to 1 in 1,456,000 - about 4 s of frozen overworld typically. The
@ host's cost model takes `placements` and refuses anything past the freeze ceiling as before.
@
@ THE UNROLL IS THE POINT. Checking twice costs about forty bytes of code, and the reason that is
@ affordable at all is the change mev20 proved: the payload lives in the RAM script body at one
@ script byte each, so there are 755 bytes here instead of 162 [asm/field/ram-jump.s]. This stub is
@ the first thing that could not have been staged.
@
@ mon-seek-far stays exactly as it is, and it is the control: it is the one that ran on hardware.

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
    pop     {r4-r7, pc}

.LrejectA:
    add     sp, #4                  @ word A failed: drop word B, the stack must balance
.Lreject:
    ldr     r5, p_mult
    b       .Lnext

    .align 2
    .global p_rng, p_mult, p_add, p_sav2ptr, p_cap, p_nature, p_ivmin, p_padlen, p_padsum
p_rng:  .word 0x03004220            @ gRngValue [rom_map.GRNG_VALUE, bs14/bs15]
p_mult: .word 0x41C64E6D            @ RAND_MULT [decomp:include/random.h:18]
p_add:  .word 0x00006073            @ RAND_ADD  [:19]
p_sav2ptr: .word 0x0300422C         @ &gSaveBlock2Ptr [rom_map.GSAVEBLOCK2PTR]
p_cap:  .word 0x00040000            @ patched: iteration cap
p_nature: .word 0x01FFFFFF          @ patched: bit N set = nature N accepted; this is "any"
p_ivmin: .word 0x40000000           @ patched: six 5-bit floors + the terminator at bit 30
p_padlen: .word 0x00000000          @ patched: filler bytes following this stub in the body
p_padsum: .word 0x00000000          @ patched: their 32-bit wrapping sum

    .align 2
.Lpadbase:                          @ emits nothing: the filler starts here, at len(the stub)
