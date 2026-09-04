@ CLI_RUN_BUFFER_SCRIPT payload: follow an ARRAY OF POINTERS and send back the STRINGS.
@
@ A memory-dump reads a window, so reading a table of pointers costs one run for the pointers and
@ another run for every kilobyte they point at. The Easy Chat vocabulary is the case that makes
@ that unaffordable: sEasyChatGroups' 22 word arrays and their text span 21560 bytes of the
@ cartridge [bs17], which is 22 dumps, and only about a third of those bytes are the words - the
@ rest is struct EasyChatWordInfo's alphabeticalOrder and enabled, which say nothing about what
@ the console PRINTS [decomp:include/easy_chat.h:11].
@
@ So this one dereferences. Given the address of the first pointer, a stride and a count, it
@ copies each string it points at - bytes up to and including the terminator - into one contiguous
@ answer, and reports where a following run should resume. For struct EasyChatWordInfo the stride
@ is 12 and `text` is at offset 0, so the array address is the pointer address.
@
@ It never truncates. A string that does not fit in what is left of the budget ends the run
@ BEFORE it, and `next` names the entry to resume from: a partial word in the answer would be
@ indistinguishable from a French word that really is shorter, which is exactly the kind of
@ silent wrong this project keeps paying for.
@
@ `maxlen` bounds the walk. A pointer that is not a string would otherwise run the copy off into
@ memory until it happened to meet a terminator, and the answer would be garbage that looked like
@ data. Hitting it stops the run and says so.
@
@ The image, all offsets from _start, and every one of them a constant this file and
@ buffer_script.py both name (nothing here is recovered from a disassembly):
@
@   0x000  b .Lcode
@   0x004  src         address of the first pointer
@   0x008  stride      bytes from one pointer to the next
@   0x00C  count       how many pointers to follow at most
@   0x010  budget      how many bytes of string to write at most
@   0x014  maxlen      longest string accepted, terminator included
@   0x018  RESULT      strings copied
@   0x01C  RESULT      bytes written
@   0x020  RESULT      the src to resume from: src + copied * stride
@   0x024  RESULT      why it stopped: 0 count, 1 budget, 2 a string past maxlen
@   0x028  the strings, terminators included, back to back
@   ...    the code
@
@ The answer comes back the way every dump does: link->sendBuffer is repointed at the result block
@ and link->sendSize widened, between the InitSend that CLI_LOAD_TOSS_RESPONSE performs and the
@ CLI_SEND_LOADED that follows [mystery_gift_link.c:59,166]. The size is FIXED, however many
@ strings were copied, so the host's length check stays the proof that the payload repointed the
@ send.
@
@ Reads only. Writes nothing outside our own image and the two link fields.
@ Position independent; the loaded bytes never leave the AAPCS scratch set plus r4-r11, pushed.

    .equ    STRING_AREA, 760        @ chosen so the whole image is exactly 1024 bytes
    .equ    ANSWER_SIZE, 16 + STRING_AREA

    .arm
    .text
    .global _start
_start:
    b       .Lcode
.Lsrc:
    .word   0                       @ 0x004
.Lstride:
    .word   0                       @ 0x008
.Lcount:
    .word   0                       @ 0x00C
.Lbudget:
    .word   0                       @ 0x010
.Lmaxlen:
    .word   0                       @ 0x014
.Lresult:
    .word   0                       @ 0x018 strings copied
    .word   0                       @ 0x01C bytes written
    .word   0                       @ 0x020 resume here
    .word   0                       @ 0x024 why it stopped
.Lstrings:
    .space  STRING_AREA             @ 0x028

.Lcode:
    sub     ip, pc, #8              @ pc reads as this instruction + 8, so ip = .Lcode
    push    {r0, r4-r11, lr}        @ r0 = &client->param, kept at [sp]
    ldr     r1, .Lcodeoff
    sub     r1, ip, r1              @ r1 = _start: our base, whatever we were copied to

    ldr     r4, [r1, #0x04]         @ the pointer we are on
    ldr     r5, [r1, #0x08]         @ stride
    ldr     r6, [r1, #0x0C]         @ pointers left to follow
    ldr     r7, [r1, #0x10]         @ bytes of budget left
    ldr     r8, [r1, #0x14]         @ maxlen
    add     r9, r1, #0x28           @ where the next string goes
    mov     r10, #0                 @ strings copied
    mov     r11, #0                 @ stopped because the count ran out

.Lnext:
    cmp     r6, #0
    beq     .Ldone
    ldr     r0, [r4]                @ the string

    mov     r2, r0                  @ measure it first: a string is copied whole or not at all
    mov     r3, #0
.Lmeasure:
    cmp     r3, r8
    bhs     .Ltoolong               @ no terminator within maxlen: not a string
    ldrb    ip, [r2], #1
    add     r3, r3, #1
    cmp     ip, #0xFF               @ EOS [decomp:include/characters.h]
    bne     .Lmeasure

    cmp     r3, r7
    bhi     .Lfull                  @ it does not fit: stop before it, never half of it

    mov     r2, r0
    mov     ip, r3
.Lcopy:
    ldrb    r0, [r2], #1
    strb    r0, [r9], #1
    subs    ip, ip, #1
    bne     .Lcopy

    sub     r7, r7, r3
    add     r10, r10, #1
    add     r4, r4, r5
    sub     r6, r6, #1
    b       .Lnext

.Ltoolong:
    mov     r11, #2
    b       .Ldone
.Lfull:
    mov     r11, #1

.Ldone:
    ldr     r2, [r1, #0x10]
    sub     r2, r2, r7              @ bytes written = budget - what is left of it
    str     r10, [r1, #0x18]
    str     r2, [r1, #0x1C]
    str     r4, [r1, #0x20]         @ the entry a following run resumes from
    str     r11, [r1, #0x24]

    ldr     r3, [sp]                @ &client->param, as the console handed it to us
    add     r2, r1, #0x18
    str     r2, [r3, #0x3C]         @ client->link.sendBuffer = the result block
    ldr     r2, .Lanswer
    strh    r2, [r3, #0x34]         @ client->link.sendSize, always the same
    str     r10, [r3, #0x00]        @ *param = strings copied, for the 4-byte channel too
    mov     r0, #1                  @ done
    pop     {r2, r4-r11, lr}
    bx      lr

.Lanswer:
    .word   ANSWER_SIZE
.Lcodeoff:
    .word   .Lcode - _start
