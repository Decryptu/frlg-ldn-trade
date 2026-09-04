@ CLI_RUN_BUFFER_SCRIPT payload: CALL A ROM FUNCTION THAT TAKES EIGHT ARGUMENTS, and send back the
@ 100 bytes it built.
@
@ bs15 called `Random` - no arguments, a u16 back, and the LCG's own recurrence to check it by.
@ CreateMon is the other end of the range [0x08041150, bs42, disassembled against pokemon.c:1755]:
@
@   void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
@                  u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
@
@ Four arguments in r0..r3 and FOUR ON THE STACK, which no payload here has passed. The console's
@ own prologue says where it reads them, and that is what this one is built against - it pushes
@ five registers, then r8, then subtracts 28, and then reads
@
@   0804115c  ldr r4, [sp, #52]   -> entry sp + 0    hasFixedPersonality  (masked to u8 at 116e)
@   0804115e  ldr r7, [sp, #56]   -> entry sp + 4    fixedPersonality     (NOT masked: it is u32)
@   08041160  ldr r5, [sp, #60]   -> entry sp + 8    otIdType             (masked to u8 at 1172)
@   08041184  ldr r0, [sp, #64]   -> entry sp + 12   fixedOtId            (u32)
@
@ so the four go at sp+0..sp+12 in that order, in whole words, at the moment of the call. The
@ callee does not pop them [080411b4: add sp,#28; pop {r3}; pop {r4-r7}; pop {r0}; bx r0], so we
@ take the 16 bytes back ourselves.
@
@ THE DESTINATION IS OUR OWN IMAGE, ALWAYS. CreateMon writes 100 bytes wherever it is pointed, and
@ the only interesting address on the console is the player's real party - a live save. So the mon
@ is built inside the 1024 bytes we were copied into, where nothing but us can be hurt, and it is
@ read back out of there. `destination` copies those 100 bytes on afterwards, as a plain byte copy
@ we can see, rather than by aiming a ROM function at a save block; 0 means do not copy, which is
@ the whole payload with no write at all. There are 32 bytes of guard between the mon and the code
@ so that an overrun of a struct bigger than we think cannot reach an instruction.
@
@ `function` = 0 calls nothing and answers the zeroed buffer, which is how the send path and the
@ answer's shape are checked without the ROM being involved at all.
@
@ The image, all offsets from _start and all fixed by construction:
@
@   0x000  b .Lcode
@   0x004  function        THUMB pointer to CreateMon, or 0 to call nothing
@   0x008  destination     absolute address to copy the finished mon to, or 0
@   0x00C  species         u16 in a word (the callee masks it itself)
@   0x010  level           u8 in a word
@   0x014  fixedIV         u8 in a word; 32 or more means "roll them" [USE_RANDOM_IVS]
@   0x018  hasFixedPersonality
@   0x01C  fixedPersonality
@   0x020  otIdType        0 = the player's own id, 1 = fixedOtId, 2 = rolled until not shiny
@   0x024  fixedOtId
@   0x028  RESULT  calls used
@   0x02C  RESULT  destination, echoed
@   0x030  RESULT  function, echoed
@   0x034  RESULT  where the mon was built - our own load address + 0x38, so the answer says where
@   0x038  RESULT  100 bytes: struct Pokemon as the ROM left it
@   0x09C  32 bytes of guard
@   0x0BC  the code
@
@ *param comes back as the mon's first word, which for a real struct Pokemon is its PERSONALITY -
@ the whole of the Gen 3 shiny check together with the trainer ids bs01 read. So the 4-byte channel
@ answers the one question the run is about, independently of the 116 bytes.
@
@ Writes its own image, the two link fields, and `destination` if one was given. Position independent.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lfunction:
    .word   0                       @ 0x004
.Ldestination:
    .word   0                       @ 0x008
.Lspecies:
    .word   0                       @ 0x00C
.Llevel:
    .word   0                       @ 0x010
.Lfixediv:
    .word   0                       @ 0x014
.Lhasfixedpersonality:
    .word   0                       @ 0x018
.Lfixedpersonality:
    .word   0                       @ 0x01C
.Lotidtype:
    .word   0                       @ 0x020
.Lfixedotid:
    .word   0                       @ 0x024
.Lresult:
    .word   0                       @ 0x028 calls used
    .word   0                       @ 0x02C destination
    .word   0                       @ 0x030 function
    .word   0                       @ 0x034 where the mon was built
.Lmon:
    .space  100                     @ 0x038 struct Pokemon
.Lguard:
    .space  32                      @ 0x09C nothing may reach the code from below

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, lr}        @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start; r4 and r5 are callee-saved, so they survive

    ldr     r0, [r4, #0x28]
    add     r0, r0, #1
    str     r0, [r4, #0x28]         @ this call counted before anything can go wrong

    add     r5, r4, #0x38           @ the mon, in our own image
    str     r5, [r4, #0x34]
    ldr     r0, [r4, #0x08]
    str     r0, [r4, #0x2C]         @ echo the destination
    ldr     r0, [r4, #0x04]
    str     r0, [r4, #0x30]         @ echo the function
    cmp     r0, #0
    beq     .Lcopy                  @ nothing to call: answer the buffer as it stands

    sub     sp, sp, #16             @ the four stack arguments, in the order the prologue reads
    ldr     r1, [r4, #0x18]
    str     r1, [sp, #0]            @ hasFixedPersonality
    ldr     r1, [r4, #0x1C]
    str     r1, [sp, #4]            @ fixedPersonality
    ldr     r1, [r4, #0x20]
    str     r1, [sp, #8]            @ otIdType
    ldr     r1, [r4, #0x24]
    str     r1, [sp, #12]           @ fixedOtId
    mov     ip, r0                  @ the THUMB pointer; ip is ours to clobber
    mov     r0, r5                  @ mon
    ldr     r1, [r4, #0x0C]         @ species
    ldr     r2, [r4, #0x10]         @ level
    ldr     r3, [r4, #0x14]         @ fixedIV
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      ip                      @ INTO THE ROM
    add     sp, sp, #16             @ the callee leaves its stack arguments to us

.Lcopy:
    ldr     r0, [r4, #0x08]
    cmp     r0, #0
    beq     .Lsend
    add     r1, r4, #0x38
    mov     r2, #100                @ sizeof(struct Pokemon), byte at a time: no alignment demanded
.Lcopyloop:
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    subs    r2, r2, #1
    bne     .Lcopyloop

.Lsend:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x28
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #116                @ 16 of header and the 100 bytes
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x38]
    str     r2, [r3, #0x00]         @ *param = the mon's first word: its personality
    mov     r0, #1                  @ done, in one call
    pop     {r2, r4, r5, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
