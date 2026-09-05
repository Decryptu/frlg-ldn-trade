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
- **0x083E3700 .. 0x086003E0 is a gap, and a big one.** The delta goes from −0x1C4 to −0x12D8
  across it, a difference of 0x1114, so there are many boundaries in there and none is located. The
  make-a-needle method above costs two runs per point and would bisect it.
- **Nothing between 0x086803FC and the end of the data has been measured.**
