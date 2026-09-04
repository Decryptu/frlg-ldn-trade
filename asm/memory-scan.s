@ CLI_RUN_BUFFER_SCRIPT payload: SEARCH the console's memory for a 32-bit value.
@
@ Every payload before this one read a window we had to name in advance, 1024 bytes at a time.
@ 16 MB of cartridge at 1024 bytes a run is 16384 runs, so the ROM has only ever been read where
@ some other measurement already pointed. This one searches instead of reading: it is handed a
@ needle and a range and it comes back with the addresses that hold it.
@
@ WHAT MAKES IT POSSIBLE, and it is in the decomp in one line: Client_RunBufferScript ends the
@ call only when our code returns 1 [decomp:src/mystery_gift_client.c:276-280], and it is reached
@ from Task_MysteryGift, once a frame. So a payload that returns anything else IS CALLED AGAIN
@ NEXT FRAME, with gDecompressionBuffer - our own image, code and data - exactly as it left it.
@ The memcpy that loads us happens once, at CLI_RUN_BUFFER_SCRIPT [mystery_gift_client.c:239],
@ not per call. That turns a 1024-byte window into a resumable loop: scan a frame's worth of
@ words, save the cursor in our own image, return 0, and continue next frame.
@
@ THE BUDGET IS THE WHOLE POINT. The console is holding an RFU link open while this runs, so a
@ call that overruns its frame costs frames the link needs. `blocks` is how many 32-byte blocks
@ one call scans; the caller sizes it for a few milliseconds and the scan takes as many frames as
@ it takes. `max_calls` is a watchdog: a payload that never returns 1 hangs the Mystery Gift menu
@ with no way out, so the count is bounded here rather than trusted to arithmetic.
@
@ The image, all offsets from _start, and every one of them a constant this file and
@ buffer_script.py both name (nothing here is recovered from a disassembly):
@
@   0x000  b .Lcode
@   0x004  cursor      where the next call resumes; the caller patches the start address
@   0x008  end         one past the last address to read
@   0x00C  needle      the word to look for
@   0x010  blocks      32-byte blocks per call
@   0x014  max_calls   watchdog: finish and answer once this many calls have run
@   0x018  RESULT      matches found (may exceed what is stored)
@   0x01C  RESULT      the cursor as we finished: == end means the range was scanned to the end
@   0x020  RESULT      calls used
@   0x024  RESULT      matches stored below
@   0x028  RESULT      64 x (address, value)
@   0x228  the code
@
@ The answer comes back the way every dump does: link->sendBuffer is repointed at the result
@ block and link->sendSize widened, between the InitSend that CLI_LOAD_TOSS_RESPONSE performs and
@ the CLI_SEND_LOADED that follows [mystery_gift_link.c:59,166]. The size is FIXED at 0x210, hits
@ found or not, so the host's length check stays the proof that the payload repointed the send.
@
@ Reads only. Writes nothing outside our own image and the two link fields.
@ Position independent, and the loaded words never leave the AAPCS scratch set plus r4-r11, which
@ are pushed.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lcursor:
    .word   0                       @ 0x004
.Lend:
    .word   0                       @ 0x008
.Lneedle:
    .word   0                       @ 0x00C
.Lblocks:
    .word   0                       @ 0x010
.Lmaxcalls:
    .word   0                       @ 0x014
.Lresult:
    .word   0                       @ 0x018 matches found
    .word   0                       @ 0x01C final cursor
    .word   0                       @ 0x020 calls used
    .word   0                       @ 0x024 matches stored
.Lhits:
    .space  512                     @ 0x028 64 x (address, value)

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
    ldr     r0, [r1, #0x0C]         @ needle
    ldr     r12, [r1, #0x10]        @ blocks left in this call
    cmp     r2, r3
    bhi     .Lfinish                @ the watchdog, not the range: answer with what we have

.Lloop:
    cmp     r10, r11
    bhs     .Lfinish                @ scanned to the end: the answer is complete
    cmp     r12, #0
    beq     .Lyield                 @ this frame's budget is spent; resume next frame
    sub     r12, r12, #1
    ldmia   r10!, {r2-r9}           @ eight words, one sequential burst
    cmp     r2, r0
    cmpne   r3, r0
    cmpne   r4, r0
    cmpne   r5, r0
    cmpne   r6, r0
    cmpne   r7, r0
    cmpne   r8, r0
    cmpne   r9, r0                  @ each compare runs only while none has matched
    bne     .Lloop
    bl      .Lrecord                @ rare: re-walk the block and write the matches down
    b       .Lloop

@ The block that just matched is [r10-32, r10). Registers r2-r9 are free again; r0 (needle),
@ r1 (base), r10, r11 and r12 must survive.
.Lrecord:
    sub     r2, r10, #32
.Lrecord_word:
    ldr     r3, [r2]
    cmp     r3, r0
    bne     .Lrecord_next
    ldr     r4, [r1, #0x18]
    add     r4, r4, #1
    str     r4, [r1, #0x18]         @ found, whether or not there is room to store it
    ldr     r5, [r1, #0x24]
    cmp     r5, #64
    bhs     .Lrecord_next
    add     r6, r1, #0x28
    add     r6, r6, r5, lsl #3
    str     r2, [r6, #0]            @ where
    str     r3, [r6, #4]            @ and what, which a masked search would need
    add     r5, r5, #1
    str     r5, [r1, #0x24]
.Lrecord_next:
    add     r2, r2, #4
    cmp     r2, r10
    blo     .Lrecord_word
    bx      lr

.Lyield:
    str     r10, [r1, #0x04]        @ resume here next frame
    mov     r0, #0                  @ NOT 1: call me again [mystery_gift_client.c:277]
    pop     {r2, r4-r11, lr}
    bx      lr

.Lfinish:
    str     r10, [r1, #0x04]
    str     r10, [r1, #0x1C]        @ how far the scan actually got
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r1, #0x18
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #0x210
    strh    r2, [r3, #0x34]         @ client->link.sendSize = header + 64 hits, always
    ldr     r2, [r1, #0x18]
    str     r2, [r3, #0x00]         @ *param = matches found, for the 4-byte channel too
    mov     r0, #1                  @ done
    pop     {r2, r4-r11, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
