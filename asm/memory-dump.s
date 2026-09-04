@ CLI_RUN_BUFFER_SCRIPT payload: read out any region of the console's memory.
@
@ r0 = &client->param, so the rest of struct MysteryGiftClient is at a fixed offset from it
@ [decomp:include/mystery_gift_client.h:71]. MysteryGiftLink_InitSend stores the POINTER it is
@ given [mystery_gift_link.c:59] and the CRC is computed later, at send time, over
@ link->sendBuffer for link->sendSize bytes [mystery_gift_link.c:166]. So between the InitSend
@ that CLI_LOAD_TOSS_RESPONSE performs and the CLI_SEND_LOADED that follows, repointing those two
@ fields makes the console read out an address of our choosing and CRC it for us.
@
@ The client script order is what makes this work:
@     CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED
@
@ The two words at the end are patched per run by buffer_script.build_memory_dump.
@ Position independent, only the AAPCS scratch registers.

    .arm
    .text
    .global _start
_start:
    ldr     r3, .Ltarget            @ pc-relative: our own literal, wherever we were copied to
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer
    ldr     r3, .Lsize
    strh    r3, [r0, #0x34]         @ client->link.sendSize
    mov     r0, #1                  @ done
    bx      lr
.Ltarget:
    .word   0
.Lsize:
    .word   0
