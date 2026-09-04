@ CLI_RUN_BUFFER_SCRIPT payload: read out any part of either save block.
@
@ memory-dump needs an absolute address. This one does not: the console hands us
@ r1 = gSaveBlock2Ptr and r2 = gSaveBlock1Ptr [decomp:src/mystery_gift_client.c:276], so the save
@ is reachable without knowing where the game put it. Same trick as memory-dump - repoint the
@ console's own outgoing message [mystery_gift_link.c:59,166] between the InitSend that
@ CLI_LOAD_TOSS_RESPONSE performs and the CLI_SEND_LOADED that follows.
@
@ The three words at the end are patched per run by buffer_script.build_save_dump:
@   .Lwhich   0 = SaveBlock2 (r1), anything else = SaveBlock1 (r2)
@   .Loffset  bytes from the start of that block
@   .Lsize    how many bytes to read, up to MG_LINK_BUFFER_SIZE
@
@ Position independent, only the AAPCS scratch registers.

    .arm
    .text
    .global _start
_start:
    ldr     r3, .Lwhich
    cmp     r3, #0
    moveq   r3, r1                  @ gSaveBlock2Ptr
    movne   r3, r2                  @ gSaveBlock1Ptr
    ldr     ip, .Loffset
    add     r3, r3, ip
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer
    ldr     r3, .Lsize
    strh    r3, [r0, #0x34]         @ client->link.sendSize
    mov     r0, #1                  @ done
    bx      lr
.Lwhich:
    .word   0
.Loffset:
    .word   0
.Lsize:
    .word   0
