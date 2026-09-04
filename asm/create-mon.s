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
@ `party_append` = 1 APPENDS IT TO THE PLAYER'S PARTY - gPlayerParty, NOT the save block's copy.
@ bs46 wrote gSaveBlock1Ptr->playerParty, correctly reported APPENDED at slot 2 with the count
@ raised, and the mon was not there afterwards: SavePlayerParty [decomp:src/load_save.c:160] copies
@ gPlayerPartyCount and all six gPlayerParty[i] INTO the save block when the console saves, so the
@ save block's party is a destination, never the live one. Writing gPlayerParty makes that same
@ call carry the mon to flash instead of erasing it.
@
@ Both addresses are given, not computed, and that is correct HERE precisely where it was wrong
@ for the save block: gPlayerParty and gPlayerPartyCount are ordinary EWRAM globals fixed at link
@ time - bs42 read 0x02024280 as a literal constant out of ZeroPlayerPartyMons' pool - while
@ gSaveBlock1Ptr carries a random 4-aligned offset re-rolled on every battle and load
@ [SetSaveBlocksPointers, decomp:src/load_save.c:75], which bs45 and bs46 measured moving 76 bytes.
@
@ It writes at slot == the CURRENT COUNT and then raises the count by one, which is what the game
@ itself does when a mon is caught: an occupied slot is never touched, so this cannot destroy a
@ Pokemon however wrong everything else is. A full party writes NOTHING and says so, the way
@ `givepokemon` answers 3 instead of 2.
@
@ `party_append` = 2 is the DRY RUN: the same call and the same arithmetic on the same r2, with
@ the two `str`s that would change the save left out. It reports the count and the address it
@ WOULD have written, and reads that slot's current 100 bytes back in place of the mon, so the
@ answer says what a real run would overwrite. Nothing on the console is touched.
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
@   0x00C  party_append    1 = append to gPlayerParty; 2 = DRY RUN
@   0x010  party_base      gPlayerParty  [0x02024280, measured bs47]
@   0x014  party_count     &gPlayerPartyCount  [0x02024025, measured bs47]
@   0x018  species         u16 in a word (the callee masks it itself)
@   0x01C  level           u8 in a word
@   0x020  fixedIV         u8 in a word; 32 or more means "roll them" [USE_RANDOM_IVS]
@   0x024  hasFixedPersonality
@   0x028  fixedPersonality
@   0x02C  otIdType        0 = the player's own id, 1 = fixedOtId, 2 = rolled until not shiny
@   0x030  fixedOtId
@   0x034  RESULT  calls used
@   0x038  RESULT  the address actually WRITTEN, or 0 if nothing was
@   0x03C  RESULT  function, echoed
@   0x040  RESULT  where the mon was built - our own load address + 0x44
@   0x044  RESULT  100 bytes: struct Pokemon as the ROM left it
@   0x0A8  RESULT  the party word: countBefore | slot << 8 | status << 16
@                  status 0 = none asked for, 1 = appended, 2 = the party was full,
@                          3 = DRY RUN: nothing written, and the 100 bytes above are the
@                          slot's CURRENT contents rather than the mon we built
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
.Lpartybase:
    .word   0                       @ 0x010 gPlayerParty
.Lpartycount:
    .word   0                       @ 0x014 &gPlayerPartyCount
.Lspecies:
    .word   0                       @ 0x018
.Llevel:
    .word   0                       @ 0x01C
.Lfixediv:
    .word   0                       @ 0x020
.Lhasfixedpersonality:
    .word   0                       @ 0x024
.Lfixedpersonality:
    .word   0                       @ 0x028
.Lotidtype:
    .word   0                       @ 0x02C
.Lfixedotid:
    .word   0                       @ 0x030
.Lresult:
    .word   0                       @ 0x034 calls used
    .word   0                       @ 0x038 the address actually written
    .word   0                       @ 0x03C function
    .word   0                       @ 0x040 where the mon was built
.Lmon:
    .space  100                     @ 0x044 struct Pokemon
.Lparty:
    .word   0                       @ 0x0A8 countBefore | slot << 8 | status << 16
.Lguard:
    .space  32                      @ 0x0A4 nothing may reach the code from below

.Lcode:
    sub     ip, pc, #8              @ ip = .Lcode
    push    {r0, r4, r5, r6, r7, lr}    @ r0 = &client->param, kept at [sp]
    ldr     r4, .Lcodeoff
    sub     r4, ip, r4              @ r4 = _start; r4-r7 are callee-saved, so they survive the call

    ldr     r0, [r4, #0x34]
    add     r0, r0, #1
    str     r0, [r4, #0x34]         @ this call counted before anything can go wrong

    add     r5, r4, #0x44           @ the mon, in our own image
    str     r5, [r4, #0x40]
    ldr     r0, [r4, #0x04]
    str     r0, [r4, #0x3C]         @ echo the function
    cmp     r0, #0
    beq     .Lsend                  @ nothing called: the mon is zeros, so write nothing anywhere

    sub     sp, sp, #16             @ the four stack arguments, in the order the prologue reads
    ldr     r1, [r4, #0x24]
    str     r1, [sp, #0]            @ hasFixedPersonality
    ldr     r1, [r4, #0x28]
    str     r1, [sp, #4]            @ fixedPersonality
    ldr     r1, [r4, #0x2C]
    str     r1, [sp, #8]            @ otIdType
    ldr     r1, [r4, #0x30]
    str     r1, [sp, #12]           @ fixedOtId
    mov     ip, r0                  @ the THUMB pointer; ip is ours to clobber
    mov     r0, r5                  @ mon
    ldr     r1, [r4, #0x18]         @ species
    ldr     r2, [r4, #0x1C]         @ level
    ldr     r3, [r4, #0x20]         @ fixedIV
    mov     lr, pc                  @ = the instruction after the bx, ARM (bit 0 clear)
    bx      ip                      @ INTO THE ROM
    add     sp, sp, #16             @ the callee leaves its stack arguments to us

    ldr     r0, [r4, #0x0C]         @ party mode: 0 none, 1 append, 2 dry run
    cmp     r0, #0
    beq     .Labsolute

    ldr     r6, [r4, #0x10]         @ gPlayerParty - the array the GAME uses, not the save's copy
    ldr     r7, [r4, #0x14]         @ &gPlayerPartyCount
    ldrb    r1, [r7]
    cmp     r1, #6                  @ PARTY_SIZE
    bcs     .Lfull
    mov     r2, #100                @ sizeof(struct Pokemon)
    mla     r6, r1, r2, r6          @ &gPlayerParty[count]: the first FREE slot, never an occupied one
    str     r6, [r4, #0x38]         @ reported either way: the address this run WOULD write
    orr     r3, r1, r1, lsl #8      @ countBefore | slot << 8; they are the same by construction
    cmp     r0, #2
    beq     .Ldryrun

    orr     r3, r3, #0x10000        @ status 1: appended
    str     r3, [r4, #0xA8]
    add     r1, r1, #1
    strb    r1, [r7]                @ gPlayerPartyCount, which SavePlayerParty copies out
    mov     r0, r6
    b       .Lcopy

@ THE DRY RUN. Everything above this point is the real thing - the same call, the same arithmetic
@ on the same r2 - and the two `str`s that would change the save are the only difference. Instead
@ it reads the slot's CURRENT 100 bytes back into the answer, in place of the mon it built, so the
@ run says what a real one would overwrite. An empty slot reads as 100 zero bytes.
.Ldryrun:
    orr     r3, r3, #0x30000        @ status 3: nothing was written
    str     r3, [r4, #0xA8]
    add     r0, r4, #0x44
    mov     r1, r6
    mov     r2, #100
.Ldryloop:
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    subs    r2, r2, #1
    bne     .Ldryloop
    b       .Lsend

.Lfull:
    orr     r3, r1, #0x20000        @ status 2: the party is full, nothing written
    str     r3, [r4, #0xA8]
    b       .Lsend

.Labsolute:
    ldr     r0, [r4, #0x08]
    cmp     r0, #0
    beq     .Lsend
    str     r0, [r4, #0x38]         @ the address written, before the loop advances it
.Lcopy:
    add     r1, r4, #0x44
    mov     r2, #100                @ byte at a time: no alignment demanded of the destination
.Lcopyloop:
    ldrb    r3, [r1], #1
    strb    r3, [r0], #1
    subs    r2, r2, #1
    bne     .Lcopyloop

.Lsend:
    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r4, #0x34
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    mov     r2, #120                @ 16 of header, the 100 bytes, and the party word
    strh    r2, [r3, #0x34]         @ client->link.sendSize
    ldr     r2, [r4, #0x44]
    str     r2, [r3, #0x00]         @ *param = the mon's first word: its personality
    mov     r0, #1                  @ done, in one call
    pop     {r2, r4, r5, r6, r7, lr}
    bx      lr

.Lcodeoff:
    .word   .Lcode - _start
