@ FIELD STUB: asm/field/mon-seek.s, run FROM THE RAM SCRIPT BODY instead of from staged bytes,
@ with a check that the far end of that body arrived.
@
@ WHY A SEPARATE FILE. mon-seek.s is PROVEN ON HARDWARE (mev19 + bs62: shiny, Jolly, Speed 28) and
@ stays exactly as it is, staged the old way, as the control. This file changes ONE thing - where
@ the code lives - and adds the measurement that makes the change worth a run.
@
@ asm/field/ram-jump.s is the trampoline and its header has the mechanism. In short: the field
@ engine runs a RAM script IN PLACE out of gSaveBlock1Ptr->ramScript.data.script
@ [GetRamScript, decomp:src/script.c:514], so bytes appended after the script's last command are
@ already in RAM and cost ONE script byte each instead of the six `setptr` charges. Only the
@ 36-byte trampoline still pays six.
@
@ WHAT THIS FILE ADDS, AND IT IS THE POINT OF THE RUN. Moving the code proves itself: if the
@ branch missed, nothing shiny appears. That would prove the JUMP and say nothing about the SIZE,
@ which is the actual claim - that a body far larger than 163 bytes is delivered intact. So the
@ stub is followed by `p_padlen` bytes of host-chosen filler at the very end of the 995, and the
@ first thing the stub does is add them up and compare against `p_padsum`. The search only runs if
@ the sum matches.
@
@     shiny mon        -> all of it arrived, including the last byte of the body
@     ordinary mon     -> the tail did not arrive, or the trampoline bailed on the magic guard
@
@ Both outcomes are safe and both are readable off the screen. There is no third outcome that
@ freezes the overworld, which is the only kind this run is not allowed to have.
@
@ THE SUM IS TAKEN FROM WHERE THE STUB ENDS. `.Lpadbase` is the label the assembler puts after the
@ literal pool, so `adr` gives the payload's own end at run time without the host having to say
@ where the code was placed. The host lays the filler down immediately after these bytes and
@ records its sum in the pool.
@
@ EXTRA PARAMETERS beyond mon-seek's:
@
@     p_padlen   how many filler bytes follow this stub in the script body. 0 skips the check.
@     p_padsum   their 32-bit sum, unsigned, wrapping.

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
