@ CLI_RUN_BUFFER_SCRIPT payload: CALL ANY FUNCTION IN THE ROM, with arguments we choose.
@
@ create-mon.s calls ONE function and knows its signature; rng-trace.s calls one with whatever
@ happens to be in the registers. This is the general form the two of them leave missing: an
@ address, up to eight argument words, and the r0 that comes back. Every symbol in rom_map.py
@ becomes callable with chosen arguments instead of only the one CreateMon was written for.
@
@ THE ARGUMENT MECHANICS ARE NOT NEW AND ARE NOT GUESSED. bs42 disassembled CreateMon's own
@ prologue and read its four stack arguments at entry sp + 0, 4, 8 and 12; bs43 and bs44 then
@ called it on hardware with eight arguments and got 13/13 predicted fields back, bs44 existing
@ only to prove the fourth stack word ([sp+12]) that bs43's otIdType left unread. So r0..r3 and
@ [sp+0..12] is a MEASURED calling convention here, not one taken on trust. The sixteen bytes are
@ pushed for every call, whatever `argc` says, because the callee never pops them and a function
@ that takes fewer simply does not read them - which is the same thing create-mon.s does.
@
@ WHY IT IS WORTH A RUN: SeedRng(k). SeedRng is a one-argument function [0x080486D0, named out of
@ its own literal pool in bs14] that assigns gRngValue = k outright [decomp:src/random.c:15], and
@ NOTHING reseeds it afterwards in ordinary play - the only other call sites are two unused debug
@ screens and the title screen [decomp:src/title_screen.c:735], which runs before the main menu and
@ so before Mystery Gift. Seeding during the link therefore fixes the console's RNG for everything
@ the player does next, out in the overworld where our code cannot reach.
@
@ `watch` IS WHAT MAKES THE ANSWER SELF-CHECKING. One word is read immediately before the call and
@ again immediately after, and both come back. For SeedRng(k) that is gRngValue, and `after` must
@ be k exactly - a return value alone would prove only that something ran. It is the same idea as
@ rng-trace's two reads around its call, which is what turned 0x03004220 from a hypothesis into
@ the address.
@
@ NOTHING HERE IS WRITTEN TO THE CONSOLE BY THE PAYLOAD. Whatever the CALLEE writes is the
@ callee's business, and that is the whole risk of this payload: `function` decides everything.
@ The builder in frlgsim/buffer_script.py refuses an address outside the cartridge, and a function
@ that never returns hangs the Mystery Gift menu with no way out - so an address that has not been
@ read as code first has no business here.
@
@ The image, all offsets from _start and all fixed by construction:
@
@   0x000  b .Lcode
@   0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing and just read `watch`
@   0x008  argc        how many of the eight words below are meant; documentation for the answer
@   0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
@   0x02C  watch       a word to read before and after the call, or 0
@   0x030  RESULT  calls used
@   0x034  RESULT  function, echoed
@   0x038  RESULT  argc, echoed
@   0x03C  RESULT  r0 as the callee left it
@   0x040  RESULT  *watch before the call
@   0x044  RESULT  *watch after the call
@
@ The answer is the 24 bytes at 0x030, and *param comes back as the returned r0.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lfunction:
    .word   0                       @ 0x004
.Largc:
    .word   0                       @ 0x008
.Largs:
    .space  32                      @ 0x00C .. 0x02B
.Lwatch:
    .word   0                       @ 0x02C
.Lresult:
    .word   0                       @ 0x030 calls
    .word   0                       @ 0x034 function
    .word   0                       @ 0x038 argc
    .word   0                       @ 0x03C r0
    .word   0                       @ 0x040 watch before
    .word   0                       @ 0x044 watch after

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start; r4-r7 are callee-saved, so they survive the call

    ldr     r0, [r4, #0x30]
    add     r0, r0, #1
    str     r0, [r4, #0x30]         @ this call counted before anything can go wrong

    ldr     r0, [r4, #0x04]
    str     r0, [r4, #0x34]         @ echo the function
    ldr     r1, [r4, #0x08]
    str     r1, [r4, #0x38]         @ echo argc

    ldr     r5, [r4, #0x2C]         @ watch
    cmp     r5, #0
    beq     .Lnowatchbefore
    ldr     r1, [r5]
    str     r1, [r4, #0x40]         @ *watch, before
.Lnowatchbefore:

    cmp     r0, #0
    beq     .Lafter                 @ nothing to call: the two reads are the whole answer

    sub     sp, sp, #16             @ arguments five to eight, where bs42 read them
    ldr     r1, [r4, #0x1C]
    str     r1, [sp, #0]
    ldr     r1, [r4, #0x20]
    str     r1, [sp, #4]
    ldr     r1, [r4, #0x24]
    str     r1, [sp, #8]
    ldr     r1, [r4, #0x28]
    str     r1, [sp, #12]
    mov     ip, r0                  @ the THUMB pointer; ip is ours to clobber
    ldr     r0, [r4, #0x0C]
    ldr     r1, [r4, #0x10]
    ldr     r2, [r4, #0x14]
    ldr     r3, [r4, #0x18]
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      ip                      @ INTO THE ROM
    add     sp, sp, #16             @ the callee leaves its stack arguments to us
    str     r0, [r4, #0x3C]         @ what it returned

.Lafter:
    ldr     r5, [r4, #0x2C]
    cmp     r5, #0
    beq     .Lsend
    ldr     r1, [r5]
    str     r1, [r4, #0x44]         @ *watch, after

.Lsend:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x30
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #24
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x3C]
    str     r2, [r3, #0x00]         @ *param = the returned r0
    mov     r0, #1                  @ done, in one call
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
