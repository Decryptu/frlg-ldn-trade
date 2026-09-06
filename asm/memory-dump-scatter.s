@ CLI_RUN_BUFFER_SCRIPT payload: read out SEVERAL UNRELATED regions in ONE Mystery Gift session.
@
@ asm/memory-dump-multi.s reads N consecutive blocks - base, base + 1024, base + 2048 - because the
@ first thing a session was ever asked for was one long region. What a PLAN asks for is not long and
@ not one region: the 166 gSpecials bodies left to read are scattered over a megabyte, and the
@ densest kilobyte in the ROM holds nine of them while the densest SIXTEEN kilobytes hold twenty-two.
@ Sixteen 1 KB windows chosen where the entries actually are catch about sixty.
@
@ So the cursor indexes a TABLE of bases carried inside the payload rather than multiplying by 1024.
@ Everything else is memory-dump-multi's: the cursor lives in client->param because
@ CLI_RUN_BUFFER_SCRIPT memcpys recvBuffer over gDecompressionBuffer on EVERY pass [decomp:
@ src/mystery_gift_client.c:238] and only what we are handed a pointer to survives [:275], and it
@ self-initialises off a magic in the high half because nothing sets param before the first pass.
@
@ .Lsize and .Ltable are patched per run by buffer_script.build_memory_dump_scatter, which fills
@ EVERY table slot - the unused ones with the last address - so a pass the client script did not
@ promise re-sends a block we already have instead of pointing the link at 0x00000000.
@
@ Position independent, only the AAPCS scratch registers. `adr` is PC-relative, which is what lets
@ the table be read from wherever gDecompressionBuffer happens to be.

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
    adr     r3, .Ltable
    ldr     r3, [r3, r1, lsl #2]    @ r3 = .Ltable[index], this block's own base
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
.Lsize:
    .word   0
.Ltable:
    .space  4 * 32, 0               @ mg_script.MAX_DUMP_BLOCKS entries, all patched
