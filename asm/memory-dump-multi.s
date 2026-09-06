@ CLI_RUN_BUFFER_SCRIPT payload: read out SEVERAL regions in ONE Mystery Gift session.
@
@ asm/memory-dump.s reads one 1 KB block, because MG_LINK_BUFFER_SIZE caps a single message and a
@ session sent one. But the cap is per MESSAGE, not per session: the client runs a SCRIPT of
@ commands [decomp:src/mystery_gift_client.c:140], and
@     CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED
@ can appear in it as many times as fit. Each pass sends another block.
@
@ THE PROBLEM THAT SHAPES THIS PAYLOAD: CLI_RUN_BUFFER_SCRIPT memcpys client->recvBuffer over
@ gDecompressionBuffer EVERY time [:238], so our image is restored to its initial state on every
@ pass and a cursor kept inside the payload would never advance. What survives is what we are
@ handed a POINTER to: client->param, the return channel [:275]. So the cursor lives there.
@
@ It has to self-initialise, because nothing in the client script sets param before the first pass
@ and its value at that point is not ours. A magic in the high half is the check: if param does not
@ carry it, this is pass zero.
@
@ .Lbase and .Lsize are patched per run by buffer_script.build_memory_dump_multi.
@ Position independent, only the AAPCS scratch registers.

    .arm
    .text
    .global _start
_start:
    ldr     r2, [r0]                @ client->param, whatever a previous pass left there
    ldr     r3, .Lmagic
    eor     r1, r2, r3
    cmp     r1, #0x100              @ high half ours AND cursor in 0..255?
    movcs   r2, r3                  @ no: this is the first pass, cursor 0
    and     r1, r2, #0xFF           @ r1 = the block index
    ldr     r3, .Lbase
    add     r3, r3, r1, lsl #10     @ base + index * 1024
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer
    ldr     r3, .Lsize
    strh    r3, [r0, #0x34]         @ client->link.sendSize
    add     r1, r1, #1
    ldr     r3, .Lmagic
    orr     r3, r3, r1
    str     r3, [r0]                @ hand the next index to the next pass
    mov     r0, #1                  @ done, this pass
    bx      lr
.Lmagic:
    .word   0x5A5A0000
.Lbase:
    .word   0
.Lsize:
    .word   0
