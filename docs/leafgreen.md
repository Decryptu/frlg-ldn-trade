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

## What is left

- **The gap boundaries are not bracketed.** Three of them are known to exist and none is located.
  Each bisection run halves a gap; nothing needs it yet.
- **Nothing above `sEasyChatGroups` has been measured.** The −0x1C4 segment ends at 0x083E3700.
- **The overworld is untouched here.** `gRngValue` and `gSaveBlock2Ptr` are both known, so
  [the shiny-seek stub](rng.md) would work on LeafGreen as written - but installing a RAM script
  means binding it to a map object and walking to it, which is the one thing the Mystery Gift menu
  cannot do for you.
