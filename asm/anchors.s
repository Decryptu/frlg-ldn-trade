@ CLI_RUN_BUFFER_SCRIPT payload: report the runtime addresses nothing else can tell us.
@
@ Every other payload works from the two pointers the console hands us. This one asks the machine
@ where it is. Four of the eleven words cannot be obtained by any other route:
@
@   [0] our own load address, from pc. gDecompressionBuffer is 0x0201C000 by DEDUCTION from
@       ld_script.ld [docs/buffer_script.md]; this measures it.
@   [1] lr. Client_RunBufferScript reaches us with `bx` through a function pointer
@       [decomp:src/mystery_gift_client.c:276], so lr is the address IN ROM of the instruction after
@       that call, with bit 0 set because the caller is THUMB. An absolute ROM address of a code site
@       we can name in the decomp - the anchor every "call into the ROM" needs.
@   [2] sp, so the stack, in IWRAM.
@   [3] r0, which is &client->param, so `client` itself: where AllocZeroed put it in gHeap.
@
@ The rest are the four AllocZeroed buffers and the pointer InitSend left, which check the struct
@ offsets this project has been computing from r0 [include/mystery_gift_client.h:71].
@
@ No repointing: CLI_LOAD_TOSS_RESPONSE has already aimed link->sendBuffer at client->sendBuffer
@ [MysteryGiftClient_InitSendWord, mystery_gift_client.c:91], so the payload writes there and only
@ has to widen link->sendSize. Reads everything, writes only its own outgoing buffer.
@
@ Position independent, only the AAPCS scratch registers.

    .arm
    .text
    .global _start
_start:
    sub     ip, pc, #8              @ pc reads as this instruction + 8, so ip = _start
    ldr     r3, [r0, #0x10]         @ client->sendBuffer
    str     ip, [r3, #0x00]         @ [0] where the console put our code
    str     lr, [r3, #0x04]         @ [1] return address into ROM (THUMB caller: bit 0 set)
    str     sp, [r3, #0x08]         @ [2] stack pointer
    str     r0, [r3, #0x0C]         @ [3] &client->param
    str     r1, [r3, #0x10]         @ [4] gSaveBlock2Ptr
    str     r2, [r3, #0x14]         @ [5] gSaveBlock1Ptr
    str     r3, [r3, #0x18]         @ [6] client->sendBuffer
    ldr     ip, [r0, #0x14]
    str     ip, [r3, #0x1C]         @ [7] client->recvBuffer
    ldr     ip, [r0, #0x18]
    str     ip, [r3, #0x20]         @ [8] client->script
    ldr     ip, [r0, #0x1C]
    str     ip, [r3, #0x24]         @ [9] client->msg
    ldr     ip, [r0, #0x3C]
    str     ip, [r3, #0x28]         @ [10] link->sendBuffer, as InitSend left it
    mov     ip, #44
    strh    ip, [r0, #0x34]         @ link->sendSize = 11 words
    mov     r0, #1                  @ done
    bx      lr
