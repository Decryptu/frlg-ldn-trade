@ CLI_RUN_BUFFER_SCRIPT payload: read the console's trainer id and report it back.
@
@ Client_RunBufferScript calls gDecompressionBuffer as
@     u32 (*func)(u32 *param, struct SaveBlock2 *sav2, struct SaveBlock1 *sav1)
@ [decomp:src/mystery_gift_client.c:276], so r0 = &client->param, r1 = gSaveBlock2Ptr,
@ r2 = gSaveBlock1Ptr, and returning 1 ends the call (anything else re-enters next frame).
@
@ gDecompressionBuffer is word aligned (ld_script.ld: ewram at 0x2000000, ALIGN(4), gHeap
@ 0x1C000, then src/main.o(ewram_data) whose first EWRAM_DATA is gDecompressionBuffer), so
@ the caller's bx lands with bit 0 clear: this is ARM code, not THUMB.
@
@ Position independent, no literal pool, only the AAPCS scratch registers r0-r3 and ip.

    .arm
    .text
    .global _start
_start:
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1] [global.h:332]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16     @ the whole 32-bit id
    str     r3, [r0]                @ *param: CLI_LOAD_TOSS_RESPONSE ships this back to us
    mov     r0, #1                  @ done
    bx      lr
