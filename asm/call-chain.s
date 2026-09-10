@ CLI_RUN_BUFFER_SCRIPT payload: A LIST OF ROM CALLS AND MEMORY ACCESSES, IN ONE FRAME.
@
@ call.s makes ONE call and reads one watched word either side of it. That was the right shape
@ while the question was "does calling the ROM work at all" and "is this address the
@ function we think it is" (AddBagItem). It is the wrong shape now that the tables name
@ twenty-four workers: every question about the console's game state is two or three calls -
@ read it, change it, read it back - and a hardware run is the expensive thing, not a call.
@
@ So: up to CHAIN_MAX_STEPS steps, executed in order in a single frame, each one leaving a word
@ in the answer. Nothing here is new machinery. The calling convention is call.s's, which is
@ CreateMon's own prologue, proven on hardware; the send is
@ call.s's; the one addition is that a step can use the PREVIOUS step's result, which is what
@ makes a pointer-returning function usable:
@
@     call GetVarPointer(0x4024)      -> the address of a saved var, computed by the game itself
@     write16 [prev] = 7              -> the var set, through the game's own pointer
@     read16  [prev]                  -> read back, which is the evidence
@
@ That sequence is the reason this payload exists. There is no VarSet among the field-script
@ ScrCmd_setvar writes through GetVarPointer's return [decomp:src/scrcmd.c:472] - so setting a var
@ the game's way is a call followed by an indirect store, and no single-call payload can do it.
@
@ A step is 24 bytes:
@
@   +0x00  op         low byte = the opcode below; bit 8 = target is PREV + target;
@                     bit 9 = a0 is PREV + a0; bit 10 = leave PREV alone
@   +0x04  target     a THUMB function pointer for CALL, an address for the reads and writes
@   +0x08  a0         r0, or the value to store
@   +0x0C  a1         r1
@   +0x10  a2         r2
@   +0x14  a3         r3
@
@   op 0  END        stop here; a zero step is the natural terminator
@      1  CALL       target(a0, a1, a2, a3), result = r0
@      2  READ32     result = *(u32 *)target
@      3  READ16     result = *(u16 *)target
@      4  READ8      result = *(u8  *)target
@      5  WRITE32    *(u32 *)target = a0, result = the word READ BACK
@      6  WRITE16    *(u16 *)target = a0, result = the halfword read back
@      7  WRITE8     *(u8  *)target = a0, result = the byte read back
@
@ EVERY WRITE READS ITSELF BACK, and that read is what lands in the answer. A write whose value
@ does not come back is a write the console refused or a target that is not what we thought, and
@ this is the only way to tell the two apart from here.
@
@ A WRITE DOES NOT BECOME PREV. A call and a read do; a write leaves PREV as it was, so the
@ pointer a call returned survives the store made through it and the read that checks it. Bit 10
@ says the same thing about any other step, which is what a read BEFORE the write needs - it would
@ otherwise replace the pointer with the value it read:
@
@     call GetVarPointer(0x4024)   PREV = the pointer
@     read16  [prev] keep          the value before, PREV untouched
@     write16 [prev] = 7           the halfword read back, PREV untouched
@     read16  [prev]               the value after, from the game's side of the store
@
@ The image, all offsets from _start and all fixed by construction:
@
@   0x000  b .Lcode
@   0x004  count       how many steps are meant, 0..16
@   0x008  reserved
@   0x00C  reserved
@   0x010  steps[16]   24 bytes each, as above
@   0x190  RESULT  calls (this is a one-frame payload, so 1)
@   0x194  RESULT  count, echoed
@   0x198  RESULT  steps executed - what the answer's first N words are good for
@   0x19C  RESULT  the op word that stopped the run early, or 0
@   0x1A0  RESULT  values[16], one per step, in order
@
@ The answer is the 80 bytes at 0x190, and *param comes back as the number of steps executed.
@
@ THE RISK IS THE CALLEE'S, AS IT IS IN call.s: an address that has not been read as code first
@ has no business here, a function that never returns hangs the Mystery Gift menu with no way
@ out, and a WRITE step writes the player's live save. The builder in pokeldn/frlg/rom/buffer_script.py
@ refuses a call outside the cartridge and refuses any write at all without an explicit override.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lcount:
    .word   0                       @ 0x004
.Lreserved1:
    .word   0                       @ 0x008
.Lreserved2:
    .word   0                       @ 0x00C
.Lsteps:
    .space  384                     @ 0x010 .. 0x18F
.Lresult:
    .word   0                       @ 0x190 calls
    .word   0                       @ 0x194 count
    .word   0                       @ 0x198 executed
    .word   0                       @ 0x19C refused
.Lvalues:
    .space  64                      @ 0x1A0 .. 0x1DF

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start; r4-r7 are callee-saved, so they survive a call

    ldr     r0, [r4, #0x190]
    add     r0, r0, #1
    str     r0, [r4, #0x190]        @ this frame counted before anything can go wrong

    ldr     r0, [r4, #0x04]
    str     r0, [r4, #0x194]        @ echo the count

    mov     r6, #0                  @ the step index, and the result index with it
    mov     r7, #0                  @ PREV: the previous step's result, 0 before the first
    add     r5, r4, #0x10           @ the first step

.Lloop:
    cmp     r6, #16                 @ the capacity, whatever the count says
    bhs     .Ldone
    ldr     r0, [r4, #0x04]
    cmp     r6, r0
    bhs     .Ldone
    ldr     r0, [r5, #0x00]         @ the op word
    ands    r1, r0, #0xFF
    beq     .Ldone                  @ END, or a step that was never filled in

    ldr     r2, [r5, #0x04]         @ target
    tst     r0, #0x100
    addne   r2, r2, r7              @ ... offset from PREV, which is how a returned pointer is used
    ldr     r3, [r5, #0x08]         @ a0
    tst     r0, #0x200
    addne   r3, r3, r7              @ ... or offset from PREV, which is how &money is reached:
                                    @ the base is a pointer only the console knows

    cmp     r1, #1
    beq     .Lopcall
    cmp     r1, #2
    beq     .Lopread32
    cmp     r1, #3
    beq     .Lopread16
    cmp     r1, #4
    beq     .Lopread8
    cmp     r1, #5
    beq     .Lopwrite32
    cmp     r1, #6
    beq     .Lopwrite16
    cmp     r1, #7
    beq     .Lopwrite8
    str     r0, [r4, #0x19C]        @ an opcode this payload does not have: stop, and name it
    b       .Ldone

.Lopcall:
    mov     ip, r2                  @ the THUMB pointer; ip is ours to clobber
    mov     r0, r3                  @ a0, already resolved
    ldr     r1, [r5, #0x0C]
    ldr     r2, [r5, #0x10]
    ldr     r3, [r5, #0x14]
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      ip                      @ INTO THE ROM
    b       .Lstore                 @ r0 is what it returned

.Lopread32:
    ldr     r0, [r2]
    b       .Lstore
.Lopread16:
    ldrh    r0, [r2]
    b       .Lstore
.Lopread8:
    ldrb    r0, [r2]
    b       .Lstore

.Lopwrite32:
    str     r3, [r2]
    ldr     r0, [r2]                @ the store, read back: the answer is the memory, not the ask
    b       .Lstorekeep
.Lopwrite16:
    strh    r3, [r2]
    ldrh    r0, [r2]
    b       .Lstorekeep
.Lopwrite8:
    strb    r3, [r2]
    ldrb    r0, [r2]
    b       .Lstorekeep

.Lstore:
    ldr     r1, [r5, #0x00]         @ the op word again: the call clobbered r0
    tst     r1, #0x400
    moveq   r7, r0                  @ PREV, for the next step, unless the step asked to keep it
.Lstorekeep:                        @ a write never sets it, so a pointer survives a store
    add     r1, r4, #0x1A0
    str     r0, [r1, r6, lsl #2]
    add     r6, r6, #1
    str     r6, [r4, #0x198]        @ steps executed, kept current the whole way down
    add     r5, r5, #24
    b       .Lloop

.Ldone:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x190
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #80
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x198]
    str     r2, [r3, #0x00]         @ *param = the steps executed
    mov     r0, #1                  @ done, in one call
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
