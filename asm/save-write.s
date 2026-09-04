@ CLI_RUN_BUFFER_SCRIPT payload: WRITE bytes into a save block, then read the same region back out.
@
@ Everything before this only read. The console hands us r1 = gSaveBlock2Ptr and r2 = gSaveBlock1Ptr
@ [decomp:src/mystery_gift_client.c:276], and a pointer takes a `strb` as readily as a `ldrb`. The
@ session ends in CLI_MSG_BUFFER_SUCCESS, which sends the console on to MG_STATE_SAVE_LOAD_GIFT
@ [mystery_gift_menu.c], so what this writes into the live save block is then written to flash.
@
@ It reads the region back in the same run rather than trusting the write: link->sendBuffer is
@ pointed AT THE DESTINATION, so the bytes that come back over the air are the bytes now in the
@ console's save. One run both writes and proves the write.
@
@ The three words at the end are patched per run by buffer_script.build_save_write, and the data to
@ write follows them:
@   .Lwhich   0 = SaveBlock2 (r1), anything else = SaveBlock1 (r2)
@   .Loffset  bytes from the start of that block
@   .Lsize    how many bytes to write, and to read back
@
@ Position independent. Preserves lr; r0 is only reused once the two link fields are set.

    .arm
    .text
    .global _start
_start:
    ldr     r3, .Lwhich
    cmp     r3, #0
    moveq   r3, r1                  @ gSaveBlock2Ptr
    movne   r3, r2                  @ gSaveBlock1Ptr
    ldr     ip, .Loffset
    add     r3, r3, ip              @ r3 = destination
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer = the destination: read it back
    ldr     ip, .Lsize
    strh    ip, [r0, #0x34]         @ client->link.sendSize
    adr     r1, .Ldata              @ source, pc-relative: still position independent
    mov     r2, r3                  @ write cursor; r0 is free from here
    cmp     ip, #0
    beq     .Ldone
.Lcopy:
    ldrb    r0, [r1], #1
    strb    r0, [r2], #1
    subs    ip, ip, #1
    bne     .Lcopy
.Ldone:
    mov     r0, #1                  @ done
    bx      lr
.Lwhich:
    .word   0
.Loffset:
    .word   0
.Lsize:
    .word   0
.Ldata:
    .word   0
