@ CLI_RUN_BUFFER_SCRIPT payload: find a TABLE by its SHAPE, not by any value we already know.
@
@ memory-scan answers "where is this word", which needs the word first. Every address this
@ project has found that way rested on a constant only one function could hold - RAND_MULT in
@ Random's literal pool [bs13], 0x00450045 in sEasyChatGroups [bs16], 0x64646464 in gSpeciesInfo
@ [bs38]. A table of POINTERS carries no such constant: gSpecialVars is 21 words that are the
@ addresses of the special script variables [decomp:data/event_scripts.s:51], and the only way to
@ recognise it is that its first twelve entries are the consecutive u16s gSpecialVar_0x8000 ..
@ gSpecialVar_0x800B [decomp:src/event_data.c:16], so each word is EXACTLY 2 more than the one
@ before it. That is a shape. This payload searches for the shape.
@
@ It answers: find every maximal run of `runlen` or more consecutive words where each is exactly
@ `delta` greater than its predecessor, and report where the run starts and what value it starts
@ with. For gSpecialVars that first value IS gSpecialVar_0x8000 - the address the RNG-reading NPC
@ needs - so the run does not merely locate the table, it reads the answer out of it.
@
@ The frame mechanics are memory-scan's and are not re-derived here: Client_RunBufferScript ends
@ the call only when we return 1 and is reached once a frame [decomp:src/mystery_gift_client.c:
@ 276-280], and the memcpy that loads us runs once [:239], so returning 0 resumes next frame with
@ our image - and here also our run state - intact.
@
@ THE RUN STATE IS WHAT MAKES THIS DIFFERENT FROM A SCAN. memory-scan is memoryless: a word
@ matches or it does not. A run has to be carried across the ldmia boundary AND across the frame
@ boundary, so `run`, `runstart` and `expect` live in the image beside the cursor.
@
@ ONE DOCUMENTED EDGE. `expect` starts at 0, so if the very first word of the range happens to be
@ 0 it is credited to a run whose `runstart` was never set and reads back as 0. The host discards
@ any hit outside the range it asked for, which is exactly that case; start the range a block
@ before anything of interest and it cannot arise at all.
@
@ The image, all offsets from _start, every one fixed by construction (the payload opens with a
@ branch over its own parameter block - nothing here is recovered from a disassembly):
@
@   0x000  b .Lcode
@   0x004  cursor      where the next call resumes; the caller patches the start address
@   0x008  end         one past the last address to read
@   0x00C  delta       the difference each word must have from the one before it
@   0x010  blocks      16-byte blocks per call: the frame budget
@   0x014  max_calls   watchdog: finish and answer once this many calls have run
@   0x018  RESULT      runs found (may exceed what is stored)
@   0x01C  RESULT      the cursor as we finished: == end means the range was scanned to the end
@   0x020  RESULT      calls used
@   0x024  RESULT      runs stored below
@   0x028  RESULT      64 x (address of the run's first word, value of that word)
@   0x228  runlen      how many words in a row make a run worth reporting
@   0x22C  run         STATE: words in the run in progress
@   0x230  runstart    STATE: address of that run's first word
@   0x234  expect      STATE: what the next word must equal to extend the run
@   0x238  the code
@
@ The answer comes back as every dump does: link->sendBuffer is repointed at the result block and
@ link->sendSize widened between the InitSend that CLI_LOAD_TOSS_RESPONSE performs and the
@ CLI_SEND_LOADED that follows [mystery_gift_link.c:59,166]. The size is FIXED at 0x210, runs
@ found or not, so the host's length check stays the proof that the payload repointed the send.
@
@ Reads only. Writes nothing outside our own image and the two link fields.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lcursor:
    .word   0                       @ 0x004
.Lend:
    .word   0                       @ 0x008
.Ldelta:
    .word   0                       @ 0x00C
.Lblocks:
    .word   0                       @ 0x010
.Lmaxcalls:
    .word   0                       @ 0x014
.Lresult:
    .word   0                       @ 0x018 runs found
    .word   0                       @ 0x01C final cursor
    .word   0                       @ 0x020 calls used
    .word   0                       @ 0x024 runs stored
.Lhits:
    .space  512                     @ 0x028 64 x (address, value)
.Lrunlen:
    .word   0                       @ 0x228
.Lrun:
    .word   0                       @ 0x22C
.Lrunstart:
    .word   0                       @ 0x230
.Lexpect:
    .word   0                       @ 0x234

.Lcode:
    sub     ip, pc, #8              @ pc reads as this instruction + 8, so ip = .Lcode
    push    {r0, r4-r11, lr}        @ r0 = &client->param, kept at [sp]
    ldr     r1, .Lcodeoff
    sub     r1, ip, r1              @ r1 = _start: our base, whatever we were copied to

    ldr     r2, [r1, #0x20]
    add     r2, r2, #1
    str     r2, [r1, #0x20]         @ this call counted before anything can go wrong
    ldr     r3, [r1, #0x14]
    ldr     r10, [r1, #0x04]        @ cursor
    ldr     r11, [r1, #0x08]        @ end
    ldr     r0, [r1, #0x0C]         @ delta
    ldr     r12, [r1, #0x10]        @ blocks left in this call
    ldr     r9, [r1, #0x228]        @ runlen
    ldr     r6, [r1, #0x22C]        @ run so far, carried across frames
    ldr     r7, [r1, #0x230]        @ where it started
    ldr     r8, [r1, #0x234]        @ what the next word must be
    cmp     r2, r3
    bhi     .Lfinish                @ the watchdog, not the range: answer with what we have

.Lloop:
    cmp     r10, r11
    bhs     .Lfinish                @ scanned to the end: the answer is complete
    cmp     r12, #0
    beq     .Lyield                 @ this frame's budget is spent; resume next frame
    sub     r12, r12, #1

    ldmia   r10!, {r2-r5}           @ four words - one block - in one sequential burst
    cmp     r2, r8
    addeq   r6, r6, #1              @ the run continues
    movne   r6, #1                  @ or this word begins a new one
    subne   r7, r10, #16
    add     r8, r2, r0              @ what would extend it
    cmp     r6, r9
    bleq    .Lrecord                @ exactly at runlen: report once per maximal run
    cmp     r3, r8
    addeq   r6, r6, #1
    movne   r6, #1
    subne   r7, r10, #12
    add     r8, r3, r0
    cmp     r6, r9
    bleq    .Lrecord
    cmp     r4, r8
    addeq   r6, r6, #1
    movne   r6, #1
    subne   r7, r10, #8
    add     r8, r4, r0
    cmp     r6, r9
    bleq    .Lrecord
    cmp     r5, r8
    addeq   r6, r6, #1
    movne   r6, #1
    subne   r7, r10, #4
    add     r8, r5, r0
    cmp     r6, r9
    bleq    .Lrecord

    b       .Lloop

@ A run has just reached exactly runlen words. r7 is where it started; its value is recovered
@ from the running expectation - expect is (last word + delta), so the first word of a run of
@ runlen is expect - runlen*delta. r0, r1, r6-r12 must survive; r2 and r3 are still live words.
.Lrecord:
    push    {r2, r3, lr}
    mul     r2, r9, r0              @ runlen * delta
    sub     r2, r8, r2              @ the value the run starts with
    ldr     r3, [r1, #0x18]
    add     r3, r3, #1
    str     r3, [r1, #0x18]         @ found, whether or not there is room to store it
    ldr     r3, [r1, #0x24]
    cmp     r3, #64
    bhs     .Lrecord_done
    add     lr, r1, #0x28
    add     lr, lr, r3, lsl #3
    str     r7, [lr, #0]            @ where the run starts
    str     r2, [lr, #4]            @ and what it starts with: for a pointer table, the pointer
    add     r3, r3, #1
    str     r3, [r1, #0x24]
.Lrecord_done:
    pop     {r2, r3, lr}
    bx      lr

.Lyield:
    str     r10, [r1, #0x04]        @ resume here next frame
    str     r6, [r1, #0x22C]        @ with the run in progress intact: a table may straddle
    str     r7, [r1, #0x230]        @ a frame boundary as easily as an ldmia boundary
    str     r8, [r1, #0x234]
    mov     r0, #0                  @ NOT 1: call me again [mystery_gift_client.c:277]
    pop     {r2, r4-r11, lr}
    bx      lr

.Lfinish:
    str     r10, [r1, #0x04]
    str     r10, [r1, #0x1C]        @ how far the scan actually got
    str     r6, [r1, #0x22C]
    str     r7, [r1, #0x230]
    str     r8, [r1, #0x234]
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r1, #0x18
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #0x210
    strh    r2, [r3, #0x34]         @ client->link.sendSize = header + 64 hits, always
    ldr     r2, [r1, #0x18]
    str     r2, [r3, #0x00]         @ *param = runs found, for the 4-byte channel too
    mov     r0, #1                  @ done
    pop     {r2, r4-r11, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
