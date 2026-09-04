@ CLI_RUN_BUFFER_SCRIPT payload: sample one word of the console's memory ONCE A FRAME, optionally
@ calling a ROM function between the two halves of each sample.
@
@ bs13 found RAND_MULT and bs14's dump named gRngValue at 0x03004220 [Random, 0x080486B0, whose
@ disassembly is byte for byte src/random.c:11]. Both are still only READ addresses: a word that
@ changes proves nothing, and at the Mystery Gift menu the game may not call Random at all.
@
@ So this payload proves the address by ITS OWN ARITHMETIC. Each call it reads the word, calls the
@ function it was given, and reads the word again, sending back both:
@
@     after == before * 1103515245 + 24691   (mod 2^32)
@
@ is the LCG's own recurrence [ISO_RANDOMIZE1, decomp:include/random.h:19]. Nothing else in memory
@ answers that, and it settles three things in one run: the address IS gRngValue, our ARM code CAN
@ call the console's THUMB ROM and come back, and the address we call is Random.
@
@ The call is `mov lr, pc; bx r2`: pc reads as this instruction + 8, which is the instruction after
@ the bx, and its bit 0 is clear, so the callee's own `bx lr` returns us to ARM state. The callee
@ is compiled C, so r4-r7 survive it; r6 is reloaded anyway rather than trusted.
@ `function` = 0 skips the call, which makes the same payload a plain per-frame sampler.
@
@ The image, all offsets from _start and all fixed by construction:
@
@   0x000  b .Lcode
@   0x004  address     the word to sample
@   0x008  function    THUMB pointer to call between the two reads, or 0
@   0x00C  samples     how many frames to sample, <= 96
@   0x010  max_calls   watchdog
@   0x014  RESULT      calls used
@   0x018  RESULT      samples taken
@   0x01C  RESULT      the address, echoed so the answer describes itself
@   0x020  RESULT      the function, echoed
@   0x024  RESULT      96 x (before, after)
@   0x324  the code
@
@ Reads the sampled address; writes only its own image and the two link fields. Whatever the called
@ function writes is the function's own business - Random advances gRngValue by one step, which the
@ game does thousands of times a second and which no save holds.
@ Position independent.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Laddress:
    .word   0                       @ 0x004
.Lfunction:
    .word   0                       @ 0x008
.Lsamples:
    .word   0                       @ 0x00C
.Lmaxcalls:
    .word   0                       @ 0x010
.Lresult:
    .word   0                       @ 0x014 calls used
    .word   0                       @ 0x018 samples taken
    .word   0                       @ 0x01C address
    .word   0                       @ 0x020 function
.Lsamplebuf:
    .space  768                     @ 0x024 96 x (before, after)

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4-r7, lr}         @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start, and it survives the ROM call

    ldr     r0, [r4, #0x14]
    add     r0, r0, #1
    str     r0, [r4, #0x14]         @ this call counted before anything can go wrong
    ldr     r1, [r4, #0x10]
    cmp     r0, r1
    bhi     .Lfinish                @ the watchdog

    ldr     r5, [r4, #0x18]         @ samples taken
    ldr     r1, [r4, #0x0C]
    cmp     r5, r1
    bhs     .Lfinish                @ already have them all

    ldr     r6, [r4, #0x04]
    ldr     r7, [r6]                @ BEFORE
    add     r1, r4, #0x24
    add     r1, r1, r5, lsl #3
    str     r7, [r1, #0]

    ldr     r2, [r4, #0x08]
    cmp     r2, #0
    beq     .Lafter
    str     r2, [r4, #0x20]         @ echo it: the answer says what it called
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      r2                      @ INTO THE ROM
.Lafter:
    ldr     r6, [r4, #0x04]         @ reloaded rather than trusted across the call
    ldr     r7, [r6]                @ AFTER
    add     r1, r4, #0x24
    add     r1, r1, r5, lsl #3
    str     r7, [r1, #4]
    str     r6, [r4, #0x1C]         @ echo the address too

    add     r5, r5, #1
    str     r5, [r4, #0x18]
    ldr     r1, [r4, #0x0C]
    cmp     r5, r1
    bhs     .Lfinish                @ that was the last one: answer in this same call
    mov     r0, #0                  @ NOT 1: call me again next frame
    pop     {r2, r4-r7, lr}
    bx      lr

.Lfinish:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x14
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    ldr     r2, [r4, #0x0C]
    mov     r1, #16
    add     r2, r1, r2, lsl #3      @ header + 8 bytes a sample, however many were taken
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x18]
    str     r2, [r3, #0x00]         @ *param = samples taken
    mov     r0, #1                  @ done
    pop     {r2, r4-r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
