---
title: LeafGreen
parent: Inside the console
nav_order: 6
---

# LeafGreen: BPGF, and what does and does not transfer from FireRed

Everything else in this section was read off **French FireRed, cartridge BPRF, software version
0x0A**. The second console is **French LeafGreen, BPGF, 0x0A** - lg163 read that off the cartridge
header, `POKEMON LEAF`. The payloads work there unchanged; the addresses do not.

Sixteen runs, lg160-lg175, every one of them inside the Mystery Gift menu. That matters practically:
the console never leaves its save point, so this can be done while the player is in the middle of
something else.

## The addresses, each with the run that measured it

| symbol | LeafGreen | FireRed | run |
|---|---|---|---|
| `gDecompressionBuffer` | 0x0201C000 | same | lg160 |
| Mystery Gift call site | 0x08148C50 | 0x08148C74 | lg160 |
| `Random` | 0x080486B0 | same | lg162 |
| `SeedRng` | 0x080486D0 | same | lg162 |
| `gRngValue` | 0x03004220 | same | lg162 |
| `gPlayerParty` | 0x02024280 | same | lg164 |
| `gPlayerPartyCount` | 0x02024025 | same | lg164 |
| `gEnemyParty` | 0x02024028 | same | lg164 |
| `gSpeciesInfo` | 0x0824CDD8 | 0x0824CDFC | lg165 |
| `CreateMon` | 0x08041150 | same | lg166 |
| `sEasyChatGroups` | 0x083E353C | 0x083E3700 | lg168/lg169 |
| `gSpecialVar_0x8000` | 0x020370B4 | same | lg171 |
| `gSpecialVars` | 0x08163984 | 0x081639A8 | lg171 |
| `gSaveBlock1Ptr` | 0x03004228 | same | lg175 |
| `gSaveBlock2Ptr` | 0x0300422C | same | lg175 |

`rom_map.LEAFGREEN` holds these with their evidence. `rom_map.leafgreen(symbol)` **raises** for
anything not in the table rather than falling back to the FireRed value.

**RAM agrees; ROM does not.** Every IWRAM and EWRAM address measured so far is identical between the
two builds - they are link-time globals of the same code. Every ROM address above 0x080486C8
differs. That is a pattern with an explanation, not a law: it holds for fifteen symbols and the next
one is still measured, not assumed.

## The ROM delta is a property of a region, not of the ROM

lg161 scanned LeafGreen for `RAND_MULT` and bs13 had scanned FireRed for the same constant. Eleven
hits each, in the same order, so they pair one to one and give the delta at eleven points across
1.3 MB - **for no hardware run at all**, out of two logs that already existed:

| FireRed | delta |
|---|---|
| 0x080486C8 | 0 |
| 0x0807D238 … 0x080AFC00 | −0x2C |
| 0x080F1EA0 … 0x08122518 | −0x28 |
| 0x0814CBFC | −0x24 |

So there are at least three differences, and LeafGreen *gains* four bytes at each of the upper two
boundaries. Higher still, the Easy Chat region is a fifth segment at **−0x1C4**, seven times the
delta immediately below it.

`rom_map.leafgreen_guess(firered_address)` answers inside the measured segments and **refuses the
gaps**, where a boundary is known to exist and its position is not. It is a place to point a dump,
never an answer - the delta says nothing about *content*.

### The mistake that exposed all of this

The first version of this model read a constant −0x24 off two points (lg160 and lg165), called one
36-byte insertion a hypothesis, and predicted a delta of zero at `CreateMon`. lg166 confirmed that
prediction byte for byte. The prediction was right and the model was wrong: **both −0x24 points sit
above every difference**, so they agreed with each other and said nothing about the range between.

lg167 then carried −0x24 upward to `sEasyChatGroups` and the dump came back as nothing at all. That
failure is worth more than the confirmations. Two agreeing measurements are one measurement repeated
when they share a blind spot.

`sEasyChatGroups` was then found the way bs16 found FireRed's: groups 8, 9 and 10 each hold 69 words
with 69 enabled, so `0x00450045` appears three times exactly 8 bytes apart. Three hits, at
0x083E3580/3588/3590 - the count fields of entries 8, 9 and 10.

## The French vocabulary transfers, and a console said so

lg169 read the group table: 22 entries, every pointer in ROM, every count equal to FireRed's, and
all 18 word-list pointers exactly −0x1C4 from theirs. That was evidence. lg170 is the confirmation -
`string-gather` on LeafGreen's group 1 returned 26/26 words identical to bs20's FireRed reading, in
the same slots: CE SERA TOI, JE T'AI EU, ECHANGER, SAPHIR … ARGENT.

So the 1006 words of [the French Easy Chat table](easy_chat_french.md) do not need reading again,
and `easychat_french` answers for both consoles.

## A dumped region must not move, and lg172/lg173 paid for it

lg172 pointed a `memory-dump` at 0x03004220 and the console died mid transmission with *erreur de
connexion*. `acklag.py` read 0 stalls and `echo_gaps.py` read `never=[]` on every block, so it was
neither the hold nor our own mirror. lg173 repeated the run **unchanged** and failed
identically with a different CRC pair - the signature of a region that moves, not one that is
corrupted. lg174 then dumped the same 32 bytes from ROM and got lg166's bytes back exactly, which
rules out the size.

```c
case 0:  header.crc = CalcCRC16WithTable(link->sendBuffer, link->sendSize);   // one frame
case 1:  SendBlock(0, link->sendBuffer + blocksize, ...);                     // the next
case 2:  if (CalcCRC16WithTable(...) != link->sendCRC) LinkRfu_FatalError();  // the one after
```
[decomp:src/mystery_gift_link.c:155]

0x03004220 is `gRngValue`, which advances two turns every frame, so the header can never match the
payload it describes. `buffer_script.build_memory_dump` refuses any range overlapping it now and
says what to do instead: dump around it, or use `rng-trace`, which returns it through the 4-byte
channel rather than the block. It is the only address named, because it is the only one *guaranteed*
to move; anything else volatile has to be found the way this was.

lg175 read the save-block pointers by starting 4 bytes higher, and they verify themselves: both
values had moved by exactly 12 since lg160's `anchors`, one shared 4-aligned offset inside the 0..124
range `SetSaveBlocksPointers` rolls [decomp:src/load_save.c:75]. Two pointers cannot agree on the
size of a re-roll neither could have faked alone.

## All three boundaries, for two runs, with the table's own address as the needle

The eleven RAND_MULT points above pair the two consoles wherever the LCG multiplier happens to sit.
Nothing says those places are near a boundary, and none of the three was bracketed by them.

**A pointer is a better needle than a constant, because every reference to it is a paired point.**
lg176b scanned LeafGreen's whole ROM for LeafGreen's own `gSpeciesInfo` (0x0824CDD8) and bs68b
scanned FireRed's for FireRed's own (0x0824CDFC). Each console answered with **56 hits** - every
literal-pool reference to the species table, which is code that reads a Pokemon's base stats and so
is spread across the whole game. Equal counts, ascending, so they pair one to one:

| delta | FireRed span | paired hits |
|---|---|---|
| 0 | 0x080001BC .. 0x0805359C | 42 |
| −0x2C | 0x080CBFB0 .. 0x080CE36C | 2 |
| −0x28 | 0x080EBA14 .. 0x0813E8CC | 9 |
| −0x24 | 0x0815A3F4 .. 0x0815A630 | 3 |

Four segments, three steps, and each step is bracketed by the last hit below it and the first above
it. Combined with the RAND_MULT points, which reach into two of the same segments:

| boundary | somewhere in | span |
|---|---|---|
| 0 -> −0x2C | 0x0805359C .. 0x0807D238 | 171,164 B |
| −0x2C -> −0x28 | 0x080CE36C .. 0x080EBA14 | 120,488 B |
| −0x28 -> −0x24 | 0x0813E8CC .. 0x08148C74 | 41,896 B |

`rom_map.LEAFGREEN_DELTA_BOUNDARIES` holds these, and a test asserts that the boundary table and the
segment table are two readings of the same measurement. **None is located to the byte**, and
`leafgreen_guess` still answers only from the segments; what changed is that the gaps it refuses are
three named spans rather than "somewhere in the ROM".

The method costs two runs and generalises: any address measured on both consoles is a needle whose
every reference is a paired point. Its reach is the reach of those references - no hit here is above
0x0815A630, so this says nothing about the Easy Chat region or anything past it.

## The overworld, and a shiny Mewtwo (mev23)

`gRngValue`, `gSaveBlock1Ptr` and `gSaveBlock2Ptr` are all link-time IWRAM words at the same
addresses as FireRed's, and every literal in [the seek stubs](rng.md) is one of them - so the stubs
needed no porting at all. What was missing was somewhere to put a RAM script: the player has to talk
to a map object, and this save sits in Cerulean Cave B1F, in front of Mewtwo.

**So the binding went on Mewtwo himself.** `initramscript` takes a map group, a map number and an
object id, and `GetRamScript` runs our script INSTEAD of that object's own
[decomp:src/field_control_avatar.c:458]. Cerulean Cave B1F is group 1 map 74
[data/maps/map_groups.json] and Mewtwo is object 3 [data/maps/CeruleanCave_B1F/map.json].

mev23 installed `rng-mon-hunt-both` there with `setwildbattle` set to species 150 at level 70. The
console answered status 55, our marker past `initramscript`. What the player saw next is the whole
result: **Mewtwo's own "Miou!" script did not run** - the battle started immediately, which is ours -
and the Mewtwo that appeared was **shiny**.

Three things that were not certain before, and are now:

- The stray-draw search works on the second cartridge. The first attempt missed and the ones after
  it hit. Both were the first talk after a load, so the miss is a placement miss and not a wrong
  constant: the stub reads `TID ^ SID` off `gSaveBlock2Ptr` at run time
  [asm/field/mon-seek-both.s:73], so it uses whichever console it is running on.
- **The binding survives a power cycle.** The player reset and talked to Mewtwo cold, and the script
  still ran. `gSaveBlock1Ptr` is re-rolled on every load [SetSaveBlocksPointers], so that is the
  trampoline's run-time pointer read being right rather than lucky.
- A buffer script does NOT take the slot back. bs68 ran on this console between the two and changed
  nothing, because a buffer script sends no card. Only a Wonder Card session does, and lg177 - an
  ordinary card - restored Mewtwo's own script through `InitRamScript_NoObjectEvent`.

The mev03 trap held here too: while the RAM script was installed the console reported **holding no
Wonder Card**, in bs68's identity line, and the card was intact throughout.

## Above `sEasyChatGroups`, with no symbol up there at all

Every measurement so far started from a symbol. Above 0x083E3700 there is no symbol - nothing in
that region has a name on either console - so the needle has to be made rather than found.

**Dump 1 KB off one console and take a word out of it.** Any word that occurs exactly once in that
kilobyte and has four distinct bytes is a fingerprint of a place, and scanning the other console for
it over a window answers with the address that place has there. The difference is the delta. Two
runs a point, anywhere in the ROM, needing no symbol, no decomp and no guess about content:

| point | FireRed | LeafGreen | needle | delta |
|---|---|---|---|---|
| bs69 / lg178 | 0x086003E0 | 0x085FF108 | 0xE1926F4D | −0x12D8 |
| bs72 / lg179 | 0x086803FC | 0x0867F124 | 0xC35D61AE | −0x12D8 |

Each scan returned **exactly one match** in a 2 MB window, so neither address is ambiguous.

**Two points, half a megabyte apart, agreeing - which is the whole reason there are two.** lg167 is
in this page already: a single carried-forward delta predicted a place and the dump came back empty.
One point here would have been that mistake again, and it would have looked just as convincing.

So there is a fifth segment at −0x12D8, and the divergence really does keep growing along the link
order: −0x24 at the species table, −0x1C4 at Easy Chat, −0x12D8 at 6 MB.

Incidentally, **FireRed's ROM data ends between 0x08680400 and 0x08800000**: bs71 read all 0xFF at
0x08800000 and bs70 all 0x00 at 0x08E00000, while 0x08680000 is high-entropy data. Two different
padding values, so those two reads are not the same thing and neither has been chased.

## What is left

- **The three low boundaries are bracketed but not located.** Halving one needs a needle known to
  sit inside that span; nothing needs it yet.
- **0x0841463E .. 0x0847DCF8 is the gap now**, 422 KB. It was 2163 KB this morning. The delta goes
  from −0x1C4 to −0x12D8 across it, a difference of 0x1114.
- **0x0824CDFC .. 0x083BEE74 is the other one**, 1480 KB, from gSpeciesInfo upwards, where the delta
  goes −0x24 to −0x1C4. Both its ends were measured long ago and the boundary itself was simply
  never written down; it is in `LEAFGREEN_DELTA_BOUNDARIES` now.
- **Nothing between 0x086803FC and the end of the data has been measured**, though bs118 read
  gSongTable and its song headers reach 0x086ABE68, so the data runs at least that far.

## bs117/lg190: a literal pool is a pointer table, and a free one

Bisecting a 2.2 MB gap with the make-a-needle method costs two runs a point and about 42 runs to
close. A POINTER TABLE dumped off both consoles is far better value - it pairs entry for entry, and
every entry is a delta measurement at wherever it points. lg169 already did this without naming it,
getting 18 points from the Easy Chat word-list pointers.

A **literal pool** is the same thing for free, and it reaches places no table indexes. Every
compiled function keeps the addresses it touches in a pool immediately after its body, so a 1 KB
window of code is a few dozen pointers to wherever that code works. The trick is placing the same
window on both cartridges, and that is the part which usually costs a run - except where the CODE
sits in a segment whose delta is already known.

m4a is exactly that case. Its code is in `lib_text`, whose start bs110 measured at 0x081DE188, and
lib_text is inside the −0x24 segment - so the same window on LeafGreen is at −0x24 exactly, with
no scan and no search. m4a is also the right code to pick: it works on the sound data, which lives
at the top of the ROM, in the gap.

bs117 dumped 0x081DF200 on FireRed and lg190 dumped 0x081DF1DC on LeafGreen. The two pools line up
word for word - 24 each, 13 identical, which are the RAM addresses and the constants - and every
one of the five that is a cartridge pointer moved by the same amount:

| FireRed | LeafGreen | delta |
|---|---|---|
| 0x0847DCF8 | 0x0847CA20 | −0x12D8 |
| 0x0847DDAC | 0x0847CAD4 | −0x12D8 |
| 0x0847DF10 | 0x0847CC38 | −0x12D8 |
| 0x0849758C (`gMPlayTable`) | 0x084962B4 | −0x12D8 |
| 0x084975BC (`gSongTable`) | 0x084962E4 | −0x12D8 |

Five points, not one - lg167 is what one costs. The −0x12D8 segment used to start at 0x086003E0;
it starts at 0x0847DCF8 now, and the gap below it is 3.5 times smaller for two runs.

**The pair proves its own alignment.** gMPlayTable and gSongTable came back 0x30 apart on BOTH
cartridges, and 0x30 is four `struct MusicPlayer` of twelve bytes, which is exactly what
`sound/music_player_table.inc` holds. A window read at the wrong offset does not produce that.

### bs120/lg191: the same trick with sixteen times the pool

A 16-block dump is 16 KB of literal pools instead of one, and that changes what a pair of joins is
worth. bs120 had already dumped 0x08081CC8 on FireRed for the warp and battle-start specials, so the
FireRed half cost nothing; lg191 dumped the SAME code on LeafGreen at −0x2C, the delta that segment
is measured to have.

**Pair by CODE OFFSET, not by index.** The two pools hold 552 and 550 words - the builds do not emit
quite the same literals - so pairing them in order drifts after the first mismatch and starts
inventing deltas (−0x53BADA0 and friends, all of them nonsense). Keyed on the site instead, minus
the segment's own 0x2C, 550 sites appear in both:

| | |
|---|---|
| identical words | 369 - the RAM addresses and the constants, which is the alignment proof |
| cartridge pointers 0x083BEE74..0x0841463E | **27, every one −0x1C4** |
| cartridge pointers at 0x082370FC | 2, both −0x24 |

The second row is the control, and it was free: 0x082370FC lies inside the measured −0x24 segment,
so a run answering anything else there would have been answering about the wrong console. The rule
from lg167 was to use two points and a control; a 16 KB pool hands you twenty-seven and the control.

**One needle moves one end of a segment. Twenty-seven moved both.** The −0x1C4 segment was
0x083DE528..0x083E3700, 21 KB, known from lg169's Easy Chat pointers. It is 0x083BEE74..0x0841463E
now, and the two gaps either side shrank to 1480 KB and 422 KB.

What did NOT work, and is worth recording so it is not tried again: gSongTable looked like the ideal
spreader - 347 entries of `{header, ms, me}` pointing into the largest blob in the ROM. bs118 dumped
it and the song HEADERS turn out to be packed together, 122 of them inside 9 KB. The pointers do not
spread, so the table measures one place, not many. A graphics pointer table would be the next thing
to try; the literal-pool trick above got there first and cost less.

## lg184-lg189: the script layer is the same on both cartridges

Method: take a word from a FireRed dump - four distinct bytes, occurring once - and scan LeafGreen
for it. Instructions are position independent, so where it comes back is the delta.

| needle | taken from | found on LeafGreen at | delta |
|---|---|---|---|
| 0x49050B80 | bs92, inside `ScrCmd_special` | 0x0806D7F4 | 0 |
| 0x4831D940 | bs103, the top of the handler block | 0x080701C0 | 0 |
| 0x49040A00 | bs105, inside the flag/var workers | 0x08071E1C | 0 |
| 0x47708008 | bs105, above `FlagGet` | 0x08071FC4 | 0 |
| 0x18210094 | bs106, inside `AddBagItem` | **0x0809DA80**, FireRed 0x0809DAAC | **-0x2C** |

**The last row is the control.** Delta 0 is also what this scan answers against the wrong console,
so the zeros need a needle from above the 0x0807D238 boundary, where the delta is known to be
-0x2C, to come back shifted. It did, one match in the window. Every run also had
`--expect-console leafgreen`.

So the delta-0 segment reaches **0x08071FC4** and the first gap is 0x08071FC4..0x0807D238, a 25x
narrowing. Everything below it is the same address on both cartridges:

- the `gScriptCmdTable` handler block, 0x0806D7C0..0x080700B8
- the script engine: `ScriptContext_Stop`, `ScriptJump`, `ScriptCall`, `ScriptReturn`, and the
  native-pointer setter `callnative` uses
- `GetVarPointer`, `VarGet`, `FlagSet`, `FlagClear`, `FlagGet`
- the `_call_via_r0` veneer `ScrCmd_special` and `ScrCmd_callnative` call through

`rom_map.SHARED_WITH_LEAFGREEN_THROUGH` is the boundary; `LEAFGREEN_ADD_BAG_ITEM` is 0x0809DA44.
The rest of the item and money block is -0x2C by segment, predicted.
