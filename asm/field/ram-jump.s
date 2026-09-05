@ FIELD STUB: the trampoline that ends the six-bytes-per-byte tax on native field code.
@
@ THE TAX. A RAM script stages native code with `setptr` (0x11), which writes ONE byte and costs
@ SIX script bytes to say so (opcode + immediate + a 4-byte absolute address). Against a 995-byte
@ body that is ~163 bytes of code [native_script.budget], and asm/field/mon-seek.s is at 160 of
@ them. Every register in that file is reused as hard as it is because of this one number.
@
@ THE WAY OUT, and it is one line of the decomp:
@
@     const u8 *GetRamScript(u8 objectId, const u8 *script)
@     { ... return scriptData->script; }
@ [decomp:src/script.c:514]
@
@ The engine does NOT copy the body anywhere. It runs it IN PLACE, out of
@ `gSaveBlock1Ptr->ramScript.data.script`. So every byte of the body is ALREADY IN RAM while the
@ script runs, at one script byte each - and bytes after the script's last command are never read
@ by the field engine at all. They are free storage that has already been delivered.
@
@ The only reason that was not usable before is aiming at it. frlgsim/rng_script.py's header says
@ so in as many words: gSaveBlock1Ptr "carries a random 4-aligned offset re-rolled on every battle
@ and load" [SetSaveBlocksPointers, decomp:src/load_save.c:75], measured moving 76 bytes between
@ two runs (bs45, bs46), so a `callnative` address baked in when the card is built is a guess.
@ THAT PARAGRAPH IS ABOUT A BUILD-TIME CONSTANT AND THIS IS NOT ONE. The offset is re-rolled at a
@ battle or a load; it is fixed for the whole frame our script runs in, and `gSaveBlock1Ptr` is a
@ LINK-TIME IWRAM word at 0x03004228 [rom_map.GSAVEBLOCK1PTR] that says what it currently is. Read
@ the pointer at run time and the target is exact. No sled, no search, no aiming.
@
@ SO THIS STUB IS THE ONLY THING THAT STILL PAYS SIX PER BYTE. It is staged at
@ gDecompressionBuffer, `callnative` reaches it there, and it branches to the payload sitting in
@ the script body behind it. 36 bytes staged instead of 160, and the payload costs one byte each:
@
@     staged trampoline  36 * 6 = 216      the payload   763 bytes, up from 163
@
@ IT IS A TAIL BRANCH, NOT A CALL. `bx r0` with lr untouched, so the payload's own
@ `pop {r4-r7, pc}` returns straight to ScrCmd_callnative's caller and the script carries on to
@ the battle. ARMv4T has no `blx <reg>`, and it does not need one here.
@
@ THE GUARD IS THE WHOLE SAFETY ARGUMENT. p_magic addresses `ramScript.data.magic`, which
@ InitRamScript sets to RAM_SCRIPT_MAGIC = 51 [decomp:src/script.c:12, :505]. If the save-block
@ offset of the RamScript is not what the host thinks it is, that byte is not 51 and this stub
@ RETURNS instead of branching: the player gets an ordinary encounter, which is a miss and not a
@ frozen overworld. There is no menu to back out of in the field, so a wrong address must not be
@ able to execute anything. The check costs four instructions and one pool word.
@
@ THE PARAMETERS:
@
@     p_sb1ptr   &gSaveBlock1Ptr, the fixed IWRAM word holding the current base
@     p_magic    byte offset of ramScript.data.magic within SaveBlock1 (0x3620)
@     p_entry    byte offset of the payload FROM THAT MAGIC BYTE, with bit 0 set for Thumb.
@                Measured from the magic byte and not from the block base so that the two
@                additions below reuse r1 and no third pool word is needed.

    .syntax unified
    .text
    .thumb
    .global _start
    .thumb_func
_start:
    ldr     r0, p_sb1ptr
    ldr     r0, [r0]                @ SaveBlock1 base - re-rolled at a battle, fixed for this frame
    ldr     r1, p_magic
    ldrb    r2, [r0, r1]
    cmp     r2, #51                 @ RAM_SCRIPT_MAGIC [decomp:src/script.c:12]
    bne     .Lbail
    ldr     r2, p_entry
    adds    r0, r0, r1
    adds    r0, r0, r2              @ the payload, bit 0 set: Thumb
    bx      r0                      @ tail branch; lr still belongs to ScrCmd_callnative
.Lbail:
    bx      lr                      @ not where we thought: do nothing at all

    .align 2
    .global p_sb1ptr, p_magic, p_entry
p_sb1ptr: .word 0x03004228          @ &gSaveBlock1Ptr [rom_map.GSAVEBLOCK1PTR]
p_magic:  .word 0x00003620          @ patched: SaveBlock1 -> ramScript.data.magic
p_entry:  .word 0x00000001          @ patched: magic byte -> the payload, | 1
