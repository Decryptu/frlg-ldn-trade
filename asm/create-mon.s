@ CLI_RUN_BUFFER_SCRIPT payload: CALL A ROM FUNCTION THAT TAKES EIGHT ARGUMENTS, and send back the
@ 100 bytes it built - optionally APPENDING them to the player's party.
@
@ bs15 called `Random` - no arguments, a u16 back, and the LCG's own recurrence to check it by.
@ CreateMon is the other end of the range [0x08041150, bs42, disassembled against pokemon.c:1755]:
@
@   void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
@                  u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
@
@ Four arguments in r0..r3 and FOUR ON THE STACK. The console's own prologue says where it reads
@ them, and that is what this is built against - it pushes five registers, then r8, then subtracts
@ 28, and then reads
@
@   0804115c  ldr r4, [sp, #52]   -> entry sp + 0    hasFixedPersonality  (masked to u8 at 116e)
@   0804115e  ldr r7, [sp, #56]   -> entry sp + 4    fixedPersonality     (NOT masked: it is u32)
@   08041160  ldr r5, [sp, #60]   -> entry sp + 8    otIdType             (masked to u8 at 1172)
@   08041184  ldr r0, [sp, #64]   -> entry sp + 12   fixedOtId            (u32)
@
@ so the four go at sp+0..sp+12 in that order, in whole words, at the moment of the call. The
@ callee does not pop them [080411b4: add sp,#28; pop {r3}; pop {r4-r7}; pop {r0}; bx r0], so we
@ take the 16 bytes back ourselves - and RETURNING AT ALL is the proof that we did, because a
@ payload that forgot would pop a garbage lr. Proven on hardware, bs43 and bs44.
@
@ THE MON IS ALWAYS BUILT INSIDE OUR OWN IMAGE, where nothing but the payload can be hurt, and read
@ back from there; there are 32 bytes of guard between it and the code so that an overrun of a
@ struct bigger than we think cannot reach an instruction. Only then is it copied anywhere, and
@ there are two ways to ask for that:
@
@ `party_append` = 1 APPENDS IT TO THE PLAYER'S PARTY, using r2 = gSaveBlock1Ptr as the console
@ hands it to us [decomp:src/mystery_gift_client.c:276] - never an absolute address, because the
@ save blocks MOVE between save loads (bs08 saw 0x02024598 and 0x0202553C on that boot and nothing
@ promises those again). playerPartyCount is at +0x34 and playerParty[6] at +0x38, 100 bytes each
@ [decomp:include/global.h:772]. It writes at slot == the CURRENT COUNT and then raises the count
@ by one, which is what the game itself does when a mon is caught: an occupied slot is never
@ touched, so this cannot destroy a Pokemon however wrong everything else is. A full party writes
@ NOTHING and says so, the way `givepokemon` answers 3 instead of 2.
@
@ `destination` is the general form: an absolute address to copy the 100 bytes to. It does not
@ touch the party count and it is not what a party write should use.
@
@ Both are skipped entirely when `function` is 0, because then the mon is a hundred zero bytes and
@ appending those would put a corrupt entry in the player's save.
@
@ The image, all offsets from _start and all fixed by construction:
@
@   0x000  b .Lcode
@   0x004  function        THUMB pointer to CreateMon, or 0 to call nothing
@   0x008  destination     absolute address to copy the finished mon to, or 0
@   0x00C  party_append    1 = append to gSaveBlock1Ptr's party instead
@   0x010  species         u16 in a word (the callee masks it itself)
@   0x014  level           u8 in a word
@   0x018  fixedIV         u8 in a word; 32 or more means "roll them" [USE_RANDOM_IVS]
@   0x01C  hasFixedPersonality
@   0x020  fixedPersonality
@   0x024  otIdType        0 = the player's own id, 1 = fixedOtId, 2 = rolled until not shiny
@   0x028  fixedOtId
@   0x02C  RESULT  calls used
@   0x030  RESULT  the address actually WRITTEN, or 0 if nothing was
@   0x034  RESULT  function, echoed
@   0x038  RESULT  where the mon was built - our own load address + 0x3C
@   0x03C  RESULT  100 bytes: struct Pokemon as the ROM left it
@   0x0A0  RESULT  the party word: countBefore | slot << 8 | status << 16
@                  status 0 = no party write asked for, 1 = appended, 2 = the party was full
@   0x0A4  32 bytes of guard
@   0x0C4  the code
@
@ The first 116 bytes of the answer are exactly what bs43 and bs44 returned, so their dumps still
@ read; the party word is an addendum past them.
@
@ *param comes back as the mon's first word, which for a real struct Pokemon is its PERSONALITY -
@ the whole of the Gen 3 shiny check together with the trainer ids bs01 read.
@
@ Writes its own image, the two link fields, and - only when asked - 100 bytes and one count byte
@ in the save. Position independent.

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lfunction:
    .word   0                       @ 0x004
.Ldestination:
    .word   0                       @ 0x008
.Lpartyappend:
    .word   0                       @ 0x00C
.Lspecies:
    .word   0                       @ 0x010
.Llevel:
    .word   0                       @ 0x014
.Lfixediv:
    .word   0                       @ 0x018
.Lhasfixedpersonality:
    .word   0                       @ 0x01C
.Lfixedpersonality:
    .word   0                       @ 0x020
.Lotidtype:
    .word   0                       @ 0x024
.Lfixedotid:
    .word   0                       @ 0x028
.Lresult:
    .word   0                       @ 0x02C calls used
    .word   0                       @ 0x030 the address actually written
    .word   0                       @ 0x034 function
    .word   0                       @ 0x038 where the mon was built
.Lmon:
    .space  100                     @ 0x03C struct Pokemon
.Lparty:
    .word   0                       @ 0x0A0 countBefore | slot << 8 | status << 16
.Lguard:
    .space  32                      @ 0x0A4 nothing may reach the code from below

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    mov     r6, r2                  @ gSaveBlock1Ptr; r4-r7 are callee-saved, so it survives
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start

    ldr     r0, [r4, #0x2C]
    add     r0, r0, #1
    str     r0, [r4, #0x2C]         @ this call counted before anything can go wrong

    add     r5, r4, #0x3C           @ the mon, in our own image
    str     r5, [r4, #0x38]
    ldr     r0, [r4, #0x04]
    str     r0, [r4, #0x34]         @ echo the function
    cmp     r0, #0
    beq     .Lsend                  @ nothing called: the mon is zeros, so write nothing anywhere

    sub     sp, sp, #16             @ the four stack arguments, in the order the prologue reads
    ldr     r1, [r4, #0x1C]
    str     r1, [sp, #0]            @ hasFixedPersonality
    ldr     r1, [r4, #0x20]
    str     r1, [sp, #4]            @ fixedPersonality
    ldr     r1, [r4, #0x24]
    str     r1, [sp, #8]            @ otIdType
    ldr     r1, [r4, #0x28]
    str     r1, [sp, #12]           @ fixedOtId
    mov     ip, r0                  @ the THUMB pointer; ip is ours to clobber
    mov     r0, r5                  @ mon
    ldr     r1, [r4, #0x10]         @ species
    ldr     r2, [r4, #0x14]         @ level
    ldr     r3, [r4, #0x18]         @ fixedIV
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      ip                      @ INTO THE ROM
    add     sp, sp, #16             @ the callee leaves its stack arguments to us

    ldr     r0, [r4, #0x0C]         @ party_append?
    cmp     r0, #0
    beq     .Labsolute

    ldrb    r1, [r6, #0x34]         @ playerPartyCount [global.h:772]
    cmp     r1, #6                  @ PARTY_SIZE
    bcs     .Lfull
    mov     r2, #100                @ sizeof(struct Pokemon)
    mla     r0, r1, r2, r6
    add     r0, r0, #0x38           @ &playerParty[count]: the first FREE slot, never an occupied one
    orr     r3, r1, r1, lsl #8      @ countBefore | slot << 8; they are the same by construction
    orr     r3, r3, #0x10000        @ status 1: appended
    str     r3, [r4, #0xA0]
    add     r1, r1, #1
    strb    r1, [r6, #0x34]         @ and the console can see it
    b       .Lcopy
.Lfull:
    orr     r3, r1, #0x20000        @ status 2: the party is full, nothing written
    str     r3, [r4, #0xA0]
    b       .Lsend

.Labsolute:
    ldr     r0, [r4, #0x08]
    cmp     r0, #0
    beq     .Lsend
.Lcopy:
    str     r0, [r4, #0x30]         @ the address actually written, before the loop advances it
    add     r1, r4, #0x3C
    mov     r2, #100                @ byte at a time: no alignment demanded of the destination
.Lcopyloop:
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    subs    r2, r2, #1
    bne     .Lcopyloop

.Lsend:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x2C
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #120                @ 16 of header, the 100 bytes, and the party word
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x3C]
    str     r2, [r3, #0x00]         @ *param = the mon's first word: its personality
    mov     r0, #1                  @ done, in one call
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
