---
title: The ROM map
parent: FireRed and LeafGreen
nav_order: 4
---

# The ROM map

Every address here was read off the console's own cartridge through the Mystery Gift link, never taken
from the decompilation. `pokeldn/frlg/rom/rom_map.py` records how each one was obtained and
`tests/test_rom_map.py` checks it against the dumps. The mechanism — `memory-dump`, `memory-scan`,
`table-scan`, `call-chain` — is on [Code on the console](frlg_rom.md).

Addresses are French FireRed, cartridge BPRF, software version 0x0A. LeafGreen's are on
[LeafGreen](frlg_leafgreen.md).

## The first anchor

The `anchors` payload returns the ROM address of the instruction after
`Client_RunBufferScript`'s call, `0x08148C75`. Everything else grew from there by dumping a caller,
disassembling it, reading its literal pool and `bl` targets, dumping any pointer table it names, and
checking that every entry lands on a prologue the disassembly already showed
(`scratchpad/rom_read.py`).

A dump at 0x08148A00 disassembles as `Client_RunBufferScript` exactly as [mystery_gift_client.c:274]
writes it, with `cmp r0,#1` at 0x08148C74. Its THUMB literal pool holds:

    0x08148C88 -> 0x0201C000   gDecompressionBuffer
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` follows at 0x08148C94, copying eight words onto the stack from 0x0845DBD0
indexed by `client->funcId` at `[r0,#8]`, which names **sClientFuncs**. Dumping that table gives eight
THUMB pointers, every one landing on a `push {r4, lr}` the earlier dump already showed, and entry 7
reading 0x08148C61 — the function `anchors` measured from the other end.

A cartridge dump at 0x08000000 reads the header directly:

    entry      b 0x08000204
    title      POKEMON FIRE          [0xA0]
    game code  BPRF                  [0xAC]  BPR = FireRed, F = French
    version    0x0a                  [0xBC]
    header checksum 0x5d, recomputed 0x5d -> VALID

so the `REVISION >= 0xA` branches this project reads are confirmed to be the ones running.

## The four function tables

    gScriptCmdTable              0x08163650   214 entries   the field script commands
    gSpecialVars                 0x081639A8    21 entries
    gSpecials                    0x081639FC   444 entries   gSpecialsEnd 0x081640EC
    gStdScripts                  0x081640EC    10 entries
    gMysteryEventScriptCmdTable  0x081DE144    17 entries

`script_data` runs from 0x08163650 to 0x081DE188, and `lib_text` starts there.

### `gSpecialVars`, found by shape

`gSpecialVars` carries no constant to search for: every one of its entries is an address that is itself
unknown. What it has is a relation — its first twelve words each sit exactly 2 above the one before,
because `gSpecialVar_0x8000` through `0x800B` are twelve consecutive `u16`s [event_data.c:16] listed in
var-id order. `table-scan` finds the run and answers with its start *and its first value*, so locating
and reading are one run: `gSpecialVars` = 0x081639A8, `gSpecialVar_0x8000` = 0x020370B4, exactly one
twelve-word run rising by 2 in 2.75 MB.

The range came from the decomp's **link order** rather than its addresses: `script_data` follows every
`.text` object [ld_script_rev10.ld:318] and `.rodata` starts below `gSpeciesInfo`, which brackets it.

`gSpecialVar_0x8000` is `EWRAM_DATA`, a link-time global that does not move, so naming it as a constant
is sound in a way naming a save address never is.

### `gScriptCmdTable`, derived rather than searched

`script_data` opens with `gScriptCmdTable` and puts `gSpecialVars` immediately after it
[ld_script_rev10.ld:318], the table is 214 entries of four bytes, and `gSpecialVars` was already
measured — so the table starts at **0x08163650** and one 856-byte dump reads the whole thing.

All 214 words came back THUMB pointers into a 10488-byte span, and the read is self-proving: the only
two entries sharing an address are 0 and 213, exactly the two the decomp names `ScrCmd_nop`, with
`ScrCmd_nop1` distinct between them at index 1. A table read one entry off cannot produce that pattern.

    0x23 callnative   0x0806D854      0x44 additem      0x0806DED0
    0x25 special      0x0806D7EC      0x79 givemon      0x0806F834
    0x29 setflag      0x0806E0EC      0x90 addmoney     0x0806F998

The index is the opcode, so `pokeldn/frlg/rom/scrcmd_names.py` names every entry from the decomp's own
table order and `scrcmd_names.handler("additem")` answers offline.

### `gSpecials` and `gStdScripts`

`ScrCmd_special` indexes `gSpecials` with a u16, bounds-checks it against `gSpecialsEnd` and calls
through a veneer [scrcmd.c:101]. Both ends are in that handler's literal pool: `gSpecials` = 0x081639FC,
`gSpecialsEnd` = 0x081640EC. The span is 0x6F0 = 444 × 4 and `data/specials.inc` has 444 entries; the
table starts at `gSpecialVars + 21 * 4`; and the call goes through 0x081E2224, four bytes below the
`_call_via_r1` veneer already on file.

Dumping the table gives 444 THUMB cartridge pointers, with the 171 `NullFieldSpecial` indices all one
address across two independent dumps. `rom_map.SPECIAL_ADDRESSES` holds them and
`rom_map.special_function("HealPlayerParty")` resolves one by name.

`gStdScripts` needed no run either: `data/event_scripts.s` puts it immediately after the
`.include "data/specials.inc"` that ends `gSpecials`, under an `.align 2` that `gSpecialsEnd` already
satisfies. So it is at **0x081640EC**, and dumping it gives ten words pointing into
0x081A76xx..0x081AB5xx, with the five msgbox scripts within forty bytes of each other.

### `gMysteryEventScriptCmdTable`, via a live struct

This table carries no constant and its 17 entries are unrelated addresses, so neither scan matches it
directly. Its *address*, however, is kept somewhere easier to find:

```c
static void InitMysteryEventScript(struct ScriptContext *ctx, u8 *script)
{
    InitScriptContext(ctx, gMysteryEventScriptCmdTable, gMysteryEventScriptCmdTableEnd);
```

[mystery_event_script.c:52]. `struct ScriptContext` keeps those two as **adjacent words** at +0x5C and
+0x60 [include/script.h], the table is 17 entries so they are exactly **68 apart**, and the context is
not a local:

    EWRAM_DATA static struct ScriptContext sMysteryEventScriptContext = {0};

[mystery_event_script.c:27]. So once any Mystery Event script has run, that pair sits in EWRAM for the
rest of the boot — `table-scan --table-delta 0x44 --table-runlen 2` over EWRAM. **The scan must follow a
Mystery Event gift in the same boot**, because the context is zero until a script runs and 0 and 0 are
not 68 apart.

Scanning all 256 KB of EWRAM in 86 calls gave **one hit and no false positives**, at 0x0203AA94 with the
value 0x081DE144: `sMysteryEventScriptContext` is at 0x0203AA38 and the table at 0x081DE144, inside the
bracket the link order predicts.

Dumping the table gives 17 entries, every one odd (a `ScrCmdFunc` pointer is THUMB), all distinct, all
inside `.text`, spanning 1084 bytes — one object file's worth of functions — and in exactly the order
`mystery_event.OPCODE_NAMES` was written from behaviour on the console over many sessions:

| # | command | handler | | # | command | handler |
|---|---|---|---|---|---|---|
| 0 | `nop` | 0x080DE451 | | 9 | `givenationaldex` | 0x080DE61D |
| 1 | `checkcompat` | 0x080DE401 | | 10 | `addrareword` | 0x080DE641 |
| 2 | `end` | 0x080DE3F5 | | 11 | `setrecordmixinggift` | 0x080DE66D |
| 3 | `setmsg` | 0x080DE465 | | 12 | `givepokemon` | 0x080DE681 |
| 4 | `setstatus` | 0x080DE455 | | 13 | `addtrainer` | 0x080DE78D |
| 5 | `runscript` | 0x080DE49D | | 14 | `enableresetrtc` | 0x080DE7D5 |
| 6 | `initramscript` | 0x080DE5B5 | | 15 | `checksum` | 0x080DE7E9 |
| 7 | `setenigmaberry` | 0x080DE4B9 | | 16 | `crc` | 0x080DE831 |
| 8 | `giveribbon` | 0x080DE581 | | | | |

Free with it: `data/mystery_event_script_cmd_table.o(script_data)` is the **last** member of
`script_data` with `lib_text` immediately after [ld_script_rev10.ld:318-330], and a dump read
`0x4C41B510` at 0x081DE188 — `push {r4, lr}`, the THUMB prologue of `libgcnmultiboot`, the first object
in `lib_text`.

## From a table entry to the function behind it

A handler is an entry point, not the function worth calling: each takes a `struct ScriptContext *` and
reads its arguments out of the script stream. **A body's `bl` targets, in address order, are the
decomp's calls for that same function, in source order** — the decomp's body is
`VarGet(ScriptReadHalfword(ctx))` per argument and then one call [scrcmd.c:463-590] — so one dump of
handlers names their workers by position:

    ScriptReadHalfword   0x0806D1E8      AddBagItem           0x0809DA70
    VarGet               0x08071DDC      RemoveBagItem        0x0809DBC4
    GetVarPointer        0x08071CC8      CheckBagHasSpace     0x0809D9EC
    FlagSet              0x08071EF4      CheckBagHasItem      0x0809D92C
    FlagClear            0x08071F1C      AddPCItem            0x0809DDB4
    FlagGet              0x08071F44      IncrementGameStat    0x080587A4

`ScrCmd_additem` matches the decomp instruction for instruction, down to the `(u8)quantity` cast
appearing as `lsls r1, #24; lsrs r1, #24`, and it stores its result through a literal reading
0x020370CC — `gSpecialVar_Result`.

**The alignment check is that already-measured targets land where they should.** `ScrCmd_random`'s third
call is 0x080486B0, which is `Random`, found independently out of its own literal pool by a completely
different route.

`scratchpad/handler_workers.py` automates it: for every handler inside a dump it walks the THUMB `bl`
pairs and prints their absolute targets in order, naming any target already measured.
`tools/frlg/rom_functions.py --table specials|field|mystery-event|callable` does the same across any of
the four tables, bounding each body by the next entry **and** by its own epilogue, and finishes by
printing the next run's plan: the entries not held, clustered into `--dump-address` windows and ranked
by how many one run would catch.

**Bounding by the epilogue matters**, and this ROM is agbcc-built: it does **not** end a THUMB function
with `pop {..., pc}`. It ends it `pop {r4,r5,r6}; pop {r1}; bx r1` (BC70 BC02 4708). A reader looking
only for 0xBDxx walks straight past that into the next function and reports its calls as this one's,
which is how one 4-call handler first came back with 25 `bl` targets. `pokeldn/frlg/rom/thumb.py` looks
for `bx Rn` as well and only treats a return as a boundary when the next function's prologue follows it.

### Naming 300 workers offline

`scripts/gen_worker_names.py` does that zip over every body the dumps hold, all four tables at once, and
writes `pokeldn/frlg/rom/worker_names.py`. Four checks decide whether a name is evidence:

| check | what it rules out | what it cost |
|---|---|---|
| **length** | inlining, `__umodsi3`, a macro read as a call | 22 bodies dropped |
| **anchor** | a misaligned body: every address already measured must land back on its own name | 1 body dropped |
| **agreement** | a target named differently by two of its callers | 0 |
| **link order** | a name in the wrong place in the ROM entirely | 1 address dropped |

The anchor check is also a re-measurement: across the 164 aligned bodies it lands on 68 distinct
already-measured names, 557 times, every one back on its own address.

The link-order check is free and strong. agbcc emits a translation unit in definition order and
`ld_script_rev10.ld:53` lists the objects in the order they are laid down, so all the names and every
anchor beside them form one ascending sequence, and a name out of place is out of the chain. It takes
the **longest** ascending chain rather than the first break, or one misplaced name throws out the
correct ones behind it.

One relaxation of the length rule is safe: a gap **between** two anchors holding exactly one unnamed
target and exactly one source call is forced whatever the compiler did elsewhere in the body, because
there is one way to fill it. An **open** gap, before the first anchor or after the last, is not forced
and names nothing.

Reading the source needs the same care as reading the code. `firered_switch` is
`GAME_VERSION=FIRERED GAME_REVISION=10 MODERN=0` [Makefile:227], so the 203 `#if REVISION >= 0xA` blocks
are live and the `#else` beside them is not. Evaluation order is post-order:
`VarGet(ScriptReadHalfword(ctx))` is `bl ScriptReadHalfword` then `bl VarGet`. **And a macro is not a
call** — `#define ScriptReadByte(ctx) (*(ctx->scriptPtr++))` [include/script.h:24] put a phantom `bl` in
151 bodies until it was taken out, which was the difference between 136 names and 180.

`NDEBUG` is a measurement rather than a build flag: `ScrCmd_special`'s body on the cartridge makes
exactly two calls, and the assert branch would add a third, so the asserts compile to nothing here.

Four names this project coined turned out to have one of the decomp's own behind them, each confirmed by
every body that reaches the address; `rom_map.DECOMP_NAMES` is the join:

| this project | the decomp | bodies agreeing |
|---|---|---|
| `GET_MON_DATA` | `GetMonData3` | 15 |
| `SCRIPT_CONTEXT_SET_NATIVE` | `SetupNativeScript` | 11 |
| `SET_RESPAWN` | `SetLastHealLocationWarp` | 1 |
| `SCRIPT_MOVEMENT_START` | `ScriptMovement_StartObjectMovementScript` | 2 |
| `CHANGE_AMOUNT_MONEY_BOX` | `ChangeAmountInMoneyBox` | 2 |
| `ME_CHECK_COMPATIBILITY` / `ME_SET_INCOMPATIBLE` | `CheckCompatibility` / `SetIncompatible` | 1 / 3 |

`GetMonData` is not a symbol at all: it is a macro that dispatches on the argument count
[include/pokemon.h:343] and `GetMonData2` is `__attribute__((alias("GetMonData3")))` [pokemon.c:2970] —
one address, three names.

**The caller count is the check.** A worker named off one caller is a guess; a worker reached by exactly
as many commands as the decomp declares call it is a measurement. `Compare` came back with exactly the
eight `compare_*` commands, `StringCopy` with the seven `buffer*` ones and with the two specials that
build a name out of `gText_BigGuy` — from a different table entirely.

One name was corrected this way. `0x0806D0EC` was called `SCRIPT_CONTEXT_STOP` from `ScrCmd_end`'s one
call, but the decomp gives that call as `StopScript(ctx)` [script.c:76] and `ScriptContext_Stop(void)`
[:360] is a **different** function; twelve handlers call 0x0806D418 instead, and `ScrCmd_waitstate` is
`ScriptContext_Stop(); return TRUE;` and nothing else. The declaration order settles it at no cost.

### Two mixed-image hazards

**Do not read two cartridges' dumps as one image.** Placing every dump by its `--dump-address` puts a
LeafGreen dump at a FireRed address (LeafGreen keeps that code −0x2C away), and the reader then answers
with whichever cartridge's copy it placed there. `gSpecials[54]` is `Script_HasTrainerBeenFought`, whose
body is `FlagGet(GetTrainerAFlag())` — and a mixed image gave a body calling `FlagSet`, which is
`SetBattledTrainerFlag2` at +0x2C, the static the decomp marks "not used" and the ROM emits anyway.
`script_read.every_dump` takes **one** cartridge, FireRed by default, read from the run's own
`--expect-console` and falling back to the tag for older runs.

**Read every dump at once, not one at a time.** `scrcmd.Memory` takes every dump together — overlapping
and adjacent regions merged, so a block straddling two runs still walks — and
`tools/frlg/script_read.py --with-every-dump` places all of them. One dump at a time proposes runs for
bytes an earlier run already holds.

### What is measured

Every body behind every table is off the cartridge: 213 field commands, 17 Mystery Event opcodes, 27
callable functions and 272 specials. `gen_worker_names` names the surface as it arrives.

A few results from the specials' bodies that were not what any run was aimed at:

- **`NullFieldSpecial` is two bytes**: `bx lr`, at 0x080CE8DC.
- **The special-var sequence is settled.** `ShakeScreen` [310] takes four arguments and loads
  0x020370BC, BE, C0 and C2 — four consecutive halfwords in one body — and the decomp's `ShakeScreen`
  reads `gSpecialVar_0x8004..0x8007`. `GetPlayerXY` [143] writes the first two and `GetPartyMonSpecies`
  [327] reads the first. The vars are in id order, two bytes each.
- **`GetLeadMonIndex` at 0x080CE818** is not in the table at all; four lead-mon specials call it.
- **A special whose body is one load names a global for free.** `GetBattleOutcome` [180] is
  `ldr; ldrb; bx lr` and a pool word, so that word is `gBattleOutcome`. The same reading gave
  `gStringVar1` and `gStringVar4`, and `ShowFieldMessageStringVar4` [141] names in its own symbol the
  global its pool holds.
- **The tables name each other's entries.** The specials table calls 0x08081CC8 `DoDiveWarp` and
  0x08081DA0 `DoFallWarp`, which the warp family's own workers also produce; `CalculatePlayerPartyCount`
  is special 131 and `ScrCmd_getpartysize`'s one call; `GetPlayerFacingDirection` is special 287 and
  `ScrCmd_faceplayer`'s first. None of that comes out right if the index-to-name mapping is off by one.

The Mystery Event VM's workers, read the same way:

| worker | address | how it names itself |
|---|---|---|
| `StringExpandPlaceholders` | 0x0800CADC | every handler that leaves a message ends on it |
| `RunScriptImmediately` | 0x0806D438 | `runscript` is `ScriptReadWord` then this, and nothing else |
| `InitRamScript` | 0x0806D5F0 | `initramscript` |
| `GiveGiftRibbonToParty` | 0x080A43B0 | `giveribbon`, first of two |
| `EnableRareWord` | 0x080C1658 | `addrareword`, first of two |
| `CheckCompatibility` | 0x080DE300 | `checkcompat`'s test, before the branch |
| `SetIncompatible` | 0x080DE330 | `checkcompat`'s else, and the only call either dead opcode makes |
| `memcpy` | 0x081E44F4 | `addtrainer`'s second call |
| `CalcCRC16` | 0x080489A0 | `crc`, its only worker |
| `StringCopyN` | 0x0800C8CC | `setenigmaberry` twice, `givepokemon` twice |
| `StringCompare` | 0x0800C938 | `setenigmaberry` |
| `SetEnigmaBerry` | 0x080A01B0 | `setenigmaberry` |
| `SpeciesToNationalPokedexNum` | 0x08046994 | `givepokemon` |
| `GetSetPokedexFlag` | 0x0808C860 | `givepokemon`, twice: SEEN then CAUGHT |
| `ItemIsMail` | 0x0809BB18 | `givepokemon` |
| `GiveMailToMon2` | 0x0809B964 | `givepokemon` |
| `CompactPartySlots` | 0x080971FC | `givepokemon` |
| **`VarSet`** | **0x08071DF8** | `setenigmaberry`, its last call |

`memcpy` at 0x081E44F4 checks the `script_data`/`lib_text` boundary from a direction that knew nothing
about it: memcpy comes from libgcc, which is in `lib_text`, and 0x081E44F4 is above the 0x081DE188 the
prologue read gave.

**`VarSet` is reachable only from here.** No ScrCmd body calls it — `setvar`'s worker is `GetVarPointer`
and a store through what it returns, which is why `call-chain` needed its `prev` mechanism. The Mystery
Event VM's `setenigmaberry` ends `VarSet(VAR_ENIGMA_BERRY_AVAILABLE, 1)`. The layout check needs no run:
`event_data.c` declares `GetVarPointer`, `VarGet`, `VarSet` in that order and the console has them at
0x08071CC8 < 0x08071DDC < 0x08071DF8, with 0x1C between the last two, which is the whole of `VarGet`'s
body.

Two call veneers came out of a **rejection**: the aligner proposed a `game_clear.c` function at
0x081E2234 and the whole-ROM link order threw it out, because nothing from that translation unit can sit
among the call veneers. The veneers are `bx rN` plus alignment, four bytes each, and r0 0x081E2224 and
r1 0x081E2228 are measured, so 0x081E2234 is `_call_via_r4` and 0x081E223C `_call_via_r6`, with the
measured r3 0x081E2230 agreeing in between.

# Reading the console's scripts as scripts

With `gScriptCmdTable` measured and the operand widths generated from the decomp's own macros
(`scripts/gen_scrcmd_args.py` → `pokeldn/frlg/rom/scrcmd_args.py`: each `.macro` emits its opcode as a
`.byte` and then a `.byte`/`.2byte`/`.4byte` per argument), a `memory-dump` plus `scrcmd.disassemble`
reads any script in the cartridge.

    0x081A7624  6A  lock
    0x081A7625  5A  faceplayer
    0x081A7626  67  message 0x00000000
    0x081A762B  66  waitmessage
    0x081A762C  6D  waitbuttonpress
    0x081A762D  6C  release
    0x081A762E  03  return

which is `Std_MsgboxNPC` [data/scripts/std_msgbox.inc], command for command.

**What makes it proof is where each script stops.** `gStdScripts` gives entry points, and disassembling
from each one has to end on a terminator at the byte immediately before the next. An operand width wrong
by one anywhere desynchronises the walk and lands in the middle of an instruction.

## The conditional macros

The generator originally read each `.macro` as a flat list of directives, and **eleven macros have
conditional bodies**, so a flat read concatenates every branch. 31 of the 214 commands were measured
wrong and 4 were missing entirely:

| command | read as | actually | why |
|---|---|---|---|
| `applymovement` | 14 bytes | 7 | the `.ifb \map` else-branch was appended, opcode byte and all |
| `waitmovement`, `removeobject`, `addobject` | 6 | 3 | the same |
| `applymovementat`, `waitmovementat`, `removeobjectat`, `addobjectat` | absent | 9, 5, 5, 5 | they **are** that else-branch: a second opcode the flat read never reached |
| `warp` and the eight other warps | 1 | 8 | the operands are all in `formatwarp`, a sub-macro the read dropped |
| the ten `buffer*` commands | 3 | 4 | the `stringvar` sub-macro's byte, dropped |
| `showobjectat`, `hideobjectat`, `resetobjectsubpriority` | 3 | 5 | the two bytes of the `map` sub-macro, dropped |
| `trainerbattle` | 114 | 6 + 4..16 | all ten type branches concatenated |

The generator now walks each macro's branches separately, and an unknown sub-macro **raises**, because
silently dropping emitted bytes is how the stream drifted in the first place.

Two shapes of macro have to be told apart. `warp` is `.byte 0x39` then `formatwarp` — one instruction
whose operands live in the callee, so the callee must be inlined. `giveitem` is `loadword` then
`callstd` — two instructions, and inlining it would register opcode 0x0F with a tail belonging to the
next command. **A macro is a command macro only when every route through it starts with a literal opcode
byte of its own and it reaches no other command macro.**

`trainerbattle` is the one command whose length is not fixed: a head of type, trainer and localId, then
one to four pointers chosen by the type. It is `scrcmd_args.VARIABLE`, and a type outside the decomp's
ten makes `scrcmd.shape` answer `None` rather than walk on at a guessed length.

The proof is a re-read of the console's own bytes. 0x081A7699..0x081A77A3 is
`data/scripts/trainer_battle.inc`. Before:

    0x081A76A8  4F  applymovement 0x800F, 0x081A77B0, 0x51, 0x0000, 0x36800D26
    0x081A76B6  00  nop
    0x081A76B7  21  compare_var_to_value 0x800D, 0x0000

After:

    0x081A76A8  4F  applymovement 0x800F, 0x081A77B0     @ VAR_LAST_TALKED, Movement_RevealTrainer
    0x081A76AF  51  waitmovement 0x0000
    0x081A76B2  26  specialvar 0x800D, 0x0036            @ VAR_RESULT, Script_HasTrainerBeenFought

which is `EventScript_TryDoNormalTrainerBattle` [data/scripts/trainer_battle.inc:8], command for
command. The old walk desynchronised by seven bytes at that first `applymovement` and never recovered:
it invented a `nop`, and further on a `pokemartdecoration` in the middle of a trainer script.

That region gives seven boundary tests rather than the five standard scripts' — the whole file is labels
laid end to end. `goto` joined `end` and `return` as a terminator to make it exact: control never falls
through an unconditional jump, and the decomp puts `EventScript_NoTrainerBattle` on the byte immediately
behind one [:17].

**A generated table is a hypothesis until something reads real bytes back through it**, and the five
standard scripts were too small to be that proof: between them they use seven commands, all fixed-width
and none conditional in the decomp's macros. All 266 bytes of the trainer-battle region are a fixture in
`tests/test_script_cmd_table.py`.

## Naming the operands

`tools/frlg/script_read.py DUMP.bin --base ADDR` is the reader:

    0x081A76A8  4F  applymovement 0x800F (VAR_LAST_TALKED), 0x081A77B0
    0x081A76B2  26  specialvar 0x800D (VAR_RESULT), 0x0036 (Script_HasTrainerBeenFought)
    0x081A76BC  06  goto_if 0x05 (!=), 0x081A76CD
    0x081A76C2  25  special 0x0038 (PlayTrainerEncounterMusic)

Three things put those names in, and the first needs no table at all:

**An operand of 0x4000 or more is a variable reference, in any command.** Every ScrCmd body passes its
arguments through `VarGet`, which returns the number unchanged below `VARS_START` and reads the variable
at or above it [event_data.c:235, `GetVarPointer`:214]. So `additem 0x8004` is not item 0x8004, it is
the item id held in `VAR_0x8004` — and this holds for a command nothing else is known about.
`pokeldn/frlg/rom/symbol_names.py` has the 274 var and 1470 flag names, generated from
`include/constants/vars.h` and `flags.h`, whose values are arithmetic on other constants and are
evaluated rather than transcribed.

**Which table an index reaches comes from the decomp's own parameter name.** `scrcmd_args.PARAMS` names
every operand with the macro parameter that emits it, read per operand off the emit line, so `special`'s
operand is `function` and `setflag`'s is `flag`. Two tables share the name `function` — `ScrCmd_special`
reads a u16 index into `gSpecials`, `ScrCmd_callstd` a u8 into `gStdScripts` — and the width says which.

**`goto_if 0x05` is `!=`** because `sScriptConditionTable`'s rows are <, =, >, <=, >=, !=
[scrcmd.c:65].

The generated table met a hardware measurement on the way in: the Altering Cave counter moves at
SaveBlock1 + 0x1048, and `GetVarPointer` is `vars[idx - VARS_START]`, so that offset is var 0x4024 —
which is the id the decomp gives `VAR_ALTERING_CAVE_WILD_SET`. `tests/test_script_symbols.py` holds
them to it.

## Following a script to what it reaches

`scrcmd.follow` chases every `goto`, `call`, `goto_if` and `call_if` from a set of entry points,
disassembles every block inside the dump, and collects every address the scripts reach for that the dump
does **not** hold. A data pointer (`text`, `movements`, a multichoice list) is reported and never
followed — disassembling movement bytes as commands prints nonsense with confidence.

`scrcmd.dump_plan` turns that into `--dump-address` lines, biggest catch first. **An address a script
asked for is not a guess**, which is the difference between this and scanning.

Reading the text as well needs `charmap.decode_message`: `charmap.decode` is for a *name* — fixed width,
no control codes, unknown bytes become `.` — and run over dialogue it turns a string into
`'Obtenu: .A!'`. A message's placeholders and line breaks are most of its meaning.
`scrcmd.data_pointers` and `scrcmd.read_string` report and decode what the scripts reach for that the
dumps **do** hold, which was silently dropped for a while.

All ten standard scripts are read off the console end to end, code and text.

Two reader behaviours worth keeping:

- **A dump ending mid-command is not "no shape here".** A known command whose operands run past the end
  means the *dump* is short, and the message says which it is; the other reading sends you hunting a bug
  in the width table.
- **`run_mg_fast.sh` records its launch line to `scratchpad/launcher_logs/`** rather than only echoing
  it: that line is the only pairing of `--dump-address` with `<tag>_dump.bin`, and a foreground run used
  to lose it.

# The species table

`gSpeciesInfo` = **0x0824CDFC**, stride **28**.

The first search for it used a needle built from `friendship`, `growthRate` and `eggGroups` at a
**26-byte** entry stride, which is what ISO alignment gives for `struct SpeciesInfo` as the decomp
declares it — its widest member is `u16`, so the struct's alignment is 2 and its size 26. A full 16 MB
scan returned zero matches.

Two hypotheses explain a zero, and they had to be separated before another run: the French cartridge's
species data differs from the English decomp's, or the data is identical and the **layout** assumption is
wrong. **The first was settled offline**: `CalculateMonStats` [pokemon.c:2095] derives every stored stat
from the base stats plus level, IVs, EVs and nature, and a party dump carries all of them. Recomputing
five party mons' six stats each reproduced what the console had stored, 30 out of 30, across five
species spread through the dex.

The fix was a needle that no layout can defeat. Exactly one qualifies: **Mew, Celebi and Jirachi all have
their six base stats at 100**, so bytes 0x00..0x05 of those three entries are `0x64` and the word
`0x64646464` appears at entry offset 0 *and* at offset 2. One of the two is word-aligned whatever the
stride and whatever the table's own alignment.

    scan: 3 match(es) for 0x64646464 in 0x08000000..0x08400000
       0x0824DE80   0x0824E970   0x0824FAB8

No false positives in 4 MB. The gaps are 2800 and 4424, which are 100 and 158 entries at 28 bytes, so
the stride is a measurement.

A dump 60 bytes before the base — so the answer does not depend on the ±2 the gaps leave open — read
**34 of 34 entries byte-identical to the decomp**, 884 bytes compared. The two extra bytes are `00 00` on
every entry, so the ROM pads the struct to 28 rather than carrying fields the decomp is missing.

Four apparent mismatches on the first pass were all bugs in the model built from the decomp:
`[SPECIES_NONE] = {0},` is a one-line block a multi-line regex swallows, `genderRatio` is the macro
`PERCENT_FEMALE(x)`, `noFlip` is a bitfield that is not always set, and constants defined in hex are
missed by a decimal-only `#define` regex.

## Finding `CreateMon` from it

Scanning for the address `0x0824CDFC` itself finds every function carrying `&gSpeciesInfo` in its
literal pool — 31 hits in `0x08028000..0x08048800`, bounded above by `Random` at 0x080486B0.

The hits are not one pool per function: five of them sit exactly `0x14` apart, which is one large
function emitting the constant in several pools. **Counting is therefore not evidence; the object
boundaries are.** The largest gap (37 KB) looked like the `pokemon.o` boundary and was not — the first
hit above it disassembles as `battle_ai_switch_items.c:88`. That run is what makes the next boundary
trustworthy rather than a second guess: the gap above it is 15.6 KB and is explained, because
`src/battle_controller_link_opponent.o` sits there in link order and references `gSpeciesInfo` nowhere.

A dump at the first hit of `pokemon.o`'s block gives a function matching [pokemon.c:1755] line for line,
identified by two constants the decomp fixes independently — `SetMonData` with field 56
(`MON_DATA_LEVEL`), then field 64 (`MON_DATA_MAIL`) carrying 255 (`MAIL_NONE`), between `CreateBoxMon`
and `CalculateMonStats`:

| symbol | address | how |
| --- | --- | --- |
| `CreateMon` | `0x08041150` | disassembled, matches pokemon.c:1755 instruction for instruction |
| `CreateBoxMon` | `0x080411C0` | the call CreateMon makes between ZeroMonData and SetMonData |
| `ZeroMonData` | `0x08041090` | CreateMon's first call |
| `SetMonData` | `0x08043A78` | called with MON_DATA_LEVEL then MON_DATA_MAIL |
| `CalculateMonStats` | `0x08041B78` | CreateMon's last call |

# The French Easy Chat vocabulary

**All 1006 language-dependent Easy Chat words are read out of the console's own ROM.**
`pokeldn/frlg/text/easychat_french_words.py` is the table and `easychat_french.french(id)` answers from
it.

## The problem

An Easy Chat id is `(group << 9) | index` — a **slot**, not a word. `pokeldn/frlg/text/easychat_words.py`
is generated from the English decompilation, so it names what the *English* ROM keeps in that slot. Every
localized ROM carries its own `gEasyChatGroup_*` tables, and nothing in the decomp can say what the
French one holds. Every phrase composed for a French console — mail, the trainer card quote, the visiting
trainer's lines, `--denied-message`, the questionnaire gate — went out on the strength of the English
table.

Three slots had been caught diverging before this work, one at a time, by putting an id somewhere the
console would render it and having the player read the screen: `EC_WORD_ENJOY` printed STRESSE,
`EC_WORD_DONE` printed FURAX, `SPEECH/12` printed LES.

## Finding the table

`sEasyChatGroups[]` is 22 entries of
`struct EasyChatGroup { const void *wordData; u16 numWords; u16 numEnabledWords; }`
[src/data/easy_chat/easy_chat_groups.h:26], 8 bytes each. Groups 8, 9 and 10 (Endings, Feelings,
Conditions) all hold 69 words with 69 enabled, so the word `0x00450045` appears **three times, exactly 8
bytes apart**. One hit anywhere is a coincidence; three on that stride is the table.
`--buffer-script memory-scan --scan-word 0x00450045` over 0x08000000..0x08480000 returned exactly three
hits and no false positives in 4.5 MB.

The range came from the decomp's link order and never its addresses: `src/easy_chat.o(.rodata)` is object
#99 in `ld_script.ld` and `src/mystery_gift_client.o(.rodata)` is #182, whose `sClientFuncs` was already
read off the console — so the table is below it. It is, at **0x083E3700**.

All 22 entries then read back with sane ROM pointers and **counts identical to the English build's**, so
the French ROM bins the same number of words per group, an id is the same slot in both languages, and the
two tables can be compared index for index. The 22 word arrays and their text span
0x083DE2C8..0x083E3700 — 21560 bytes, contiguous, with each group's strings between its array and the
next.

The words were then read one group per run with `string-gather`. The first group read was self-verifying
the moment it landed: index 42 came back STRESSE and index 60 FURAX, which two earlier runs had read off
the console's own screen by a completely different route. Nine more slots were confirmed the same way as
the sweep went on. `tests/test_easychat_french.py` requires the render evidence and the ROM evidence to
agree wherever they overlap.

It caught one error in the render evidence: `TRAINER/11` had been recorded as DRESSEURS from a phrase on
screen; the ROM holds **DRESSEUR**, singular, and no DRESSEURS exists anywhere in the 1006. A phrase read
by eye is weaker than the table the game indexes.

## What the table says

**How far the English table diverges depends entirely on the group.**

`EC_GROUP_STATUS` is nearly exact, because its 109 words are Ability names with official French
translations: `stench`→PUANTEUR, `thick_fat`→ISOGRAISSE, `rain_dish`→CUVETTE, `drizzle`→CRACHIN,
`arena_trap`→PIEGE, `rock_head`→TETE DE ROC, `air_lock`→AIR LOCK (untranslated in French too).

`EC_GROUP_FEELINGS` is almost entirely re-binned. The English group is a grab-bag that includes verbs —
meet, play, eat, drink, see, hear, got, goes, go home — while the French one is purely emotional states
from end to end. Slot 13, English `disappoints`, holds RAVI (delighted). Slot 44, `eat`, holds HUMILIE.
Slot 51, `drink`, holds HONTEUX.

The mechanism is visible in `EC_GROUP_SPEECH`: `but`→MAIS, `however`→CEPENDANT, `how`→COMMENT and
`the`→LE all line up, but French needs three forms of the article where English needs one, so LES and L'
took the neighbouring slots English spends on `case` and `miss`. The localization kept each group's theme
and **displaced its neighbours** wherever the target language needed a different number of words for a
concept. Where a group is a list of proper nouns it barely moved; where it is ordinary vocabulary it
moved a lot. There is no shortcut and no way to tell by looking at an id.

**807 slots needed no reading.** `EC_GROUP_POKEMON`, `POKEMON_2`, `MOVE_1` and `MOVE_2` print from
`gSpeciesNames` / `gMoveNames` indexed by species number and move id [easy_chat.c:155], so the console
prints its own localized name and the slot means the same thing in every language.
`easychat.species_word(55)` and `easychat.move_word(177)` build them and `easychat.is_language_safe`
recognises them.

## Using it

```python
from pokeldn import easychat, easychat_french
easychat_french.french(easychat.WORDS["enjoy"])     # 'STRESSE', not 'enjoy'
easychat_french.render(ids)                          # the line as the console will print it
easychat_french.check(ids, strict=True)              # raises on anything unread
```

`check` no longer flags real words, so what it catches is an id that is not a word at all, such as an
index past the end of its group.

Reproducing or extending:

    ./scratchpad/ec_sweep.sh <tag> GREETINGS 0x083DF5C0 42        # chain runs without prompting
    ./.venv/bin/python scratchpad/ec_words.py --group 4 --tag <tag> scratchpad/<tag>_dump.bin
    ./.venv/bin/python scratchpad/ec_words.py --report

`scratchpad/ec_locate.py` finds the table in a scan answer and checks a dump of it against the decomp's
counts. The addresses of all 22 word arrays are in `scratchpad/ec_words.py`.

**LeafGreen does not need the whole sweep again.** Every address here is FireRed's and none is valid on
LeafGreen, but the whole Easy Chat region is a single uniform shift of **−0x1C4**, so every address maps
by subtraction and the vocabulary itself is identical: LeafGreen's group table has 22 entries with every
count equal, and a `string-gather` of one group returned 26/26 words in the same slots. `easychat_french`
answers for both consoles.
