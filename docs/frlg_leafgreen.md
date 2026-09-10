---
title: LeafGreen
parent: FireRed and LeafGreen
nav_order: 6
---

# LeafGreen, and the two cartridges' offset map

Everything else in this section was read off French FireRed, cartridge BPRF, software version
0x0A. The second console is **French LeafGreen, BPGF, 0x0A**, read off its own cartridge header
(`POKEMON LEAF`). Every payload works there unchanged; the ROM addresses do not.

All of this work happens inside the Mystery Gift menu, so the console never leaves its save point.

## The measured addresses

| symbol | LeafGreen | FireRed |
|---|---|---|
| `gDecompressionBuffer` | 0x0201C000 | same |
| Mystery Gift call site | 0x08148C50 | 0x08148C74 |
| `Random` | 0x080486B0 | same |
| `SeedRng` | 0x080486D0 | same |
| `gRngValue` | 0x03004220 | same |
| `gPlayerParty` | 0x02024280 | same |
| `gPlayerPartyCount` | 0x02024025 | same |
| `gEnemyParty` | 0x02024028 | same |
| `gSpeciesInfo` | 0x0824CDD8 | 0x0824CDFC |
| `CreateMon` | 0x08041150 | same |
| `sEasyChatGroups` | 0x083E353C | 0x083E3700 |
| `gSpecialVar_0x8000` | 0x020370B4 | same |
| `gSpecialVars` | 0x08163984 | 0x081639A8 |
| `gSaveBlock1Ptr` | 0x03004228 | same |
| `gSaveBlock2Ptr` | 0x0300422C | same |

`rom_map.LEAFGREEN` holds these with their evidence. `rom_map.leafgreen(symbol)` raises for
anything not in the table rather than falling back to the FireRed value.

RAM agrees; ROM does not. Every IWRAM and EWRAM address measured is identical between the two
builds, they are link-time globals of the same code. Every ROM address above 0x080486C8 differs. That
is a pattern with an explanation, not a law: it holds for fifteen symbols and the next one is still
measured rather than assumed.

## The delta is a property of a region

The offset from a FireRed address to its LeafGreen twin is piecewise constant, and there are at least
eight segments:

    +0x0   -0x2C   -0x28   -0x24   -0x20   -0x1C4   -0x124C   -0x1240   -0x12D8

It is not monotonic. The four low segments step −0x2C, −0x28, −0x24, −0x20, each four bytes *less*
divergent than the one below it, and only then does it jump. A less divergent segment further up is not
a mistake.

`rom_map.leafgreen_guess(firered_address)` answers inside a measured segment and refuses the gaps,
where a boundary is known to exist and its position is not. It is a place to point a dump, never an
answer, the delta says nothing about *content*.

`pokeldn/frlg/rom/leafgreen_twins.py` holds 738 distinct pairs, each read off its own cartridge, and
`leafgreen_twins.leafgreen(address)` answers exactly where it has a pair and falls back to
`leafgreen_guess` everywhere else. About 200 of them are functions this project can name.

### The boundaries

    step             span                          what is in it
    0     -> -0x2c   644 B, 0x0807CF68..0x0807D1EC  title_screen.o
    -0x2c -> -0x28    62 B, 0x080DE2E4..0x080DE322  mystery_event_script.o
    -0x28 -> -0x24    90 B, 0x081480CE..0x08148128  mystery_gift.o
    -0x24 -> -0x20    31 B, 0x08251D8E..0x08251DAD  pokemon.o rodata
    -0x20 -> -0x1c4 1209 B, 0x083B7B47..0x083B8000  title_screen.o rodata
    -0x1c4 -> -0x124c  30 KB, 0x0843AFFF..0x08442800  graphics
    -0x124c -> -0x1240 17 KB, 0x08442BFF..0x08447000  graphics
    -0x1240 -> -0x12d8 63 KB, 0x0844F3FF..0x0845F000  graphics

A boundary is not a line: it is the divergent region itself. Where the two builds hold
version-specific code, no delta describes anything. The span recorded is the last window that still
matches at the old delta and the first that matches at the new one. `rom_map.LEAFGREEN_DELTA_BOUNDARIES`
holds them, and a test asserts that the boundary table and the segment table are two readings of the
same measurement.

Where it stops is not a matter of more runs. Above 0x0843C800 the two cartridges hold *different
bytes*, not the same bytes somewhere else, version-specific graphics. No shift matches at any offset a
block can see, so the delta there is undefined by content rather than unmeasured.

## The methods, in order of cost

Five methods were used, and the last one is the one to reach for.

### Paired constants

The same constant scanned for on both cartridges gives paired hits wherever it happens to sit. Scanning
both for `RAND_MULT` gave eleven hits each, in the same order, pairing one to one across 1.3 MB, for no
hardware run at all, out of two logs that already existed.

Its reach is wherever the constant happens to be, and nothing says those places are near a boundary.

### A pointer as the needle

A pointer is a better needle than a constant, because every reference to it is a paired point.
Scanning LeafGreen for LeafGreen's own `gSpeciesInfo` and FireRed for FireRed's own gave 56 hits each,
every literal-pool reference to the species table, which is code that reads a Pokemon's base stats and
so is spread across the whole game. Equal counts, ascending, pairing one to one:

| delta | FireRed span | paired hits |
|---|---|---|
| 0 | 0x080001BC .. 0x0805359C | 42 |
| −0x2C | 0x080CBFB0 .. 0x080CE36C | 2 |
| −0x28 | 0x080EBA14 .. 0x0813E8CC | 9 |
| −0x24 | 0x0815A3F4 .. 0x0815A630 | 3 |

Any address measured on both consoles is a needle whose every reference is a paired point. Its reach is
the reach of those references: no hit here is above 0x0815A630, so this says nothing about the Easy Chat
region or anything past it.

### Making a needle where there is no symbol

Above 0x083E3700 nothing on either console has a name, so the needle has to be made rather than found.

Dump 1 KB off one console and take a word out of it. Any word that occurs exactly once in that
kilobyte and has four distinct bytes is a fingerprint of a place, and scanning the other console for it
over a window answers with the address that place has there. The difference is the delta. Two runs a
point, anywhere in the ROM, needing no symbol, no decomp and no guess about content:

| FireRed | LeafGreen | needle | delta |
|---|---|---|---|
| 0x086003E0 | 0x085FF108 | 0xE1926F4D | −0x12D8 |
| 0x086803FC | 0x0867F124 | 0xC35D61AE | −0x12D8 |

Each scan returned exactly one match in a 2 MB window.

Use two points and a control, never one. An earlier reading carried a single delta upward from two
agreeing measurements and predicted a place; the dump came back empty. The two agreeing points sat above
every difference, so they agreed with each other and said nothing about the range between them. Two
agreeing measurements are one measurement repeated when they share a blind spot.

The five needle scans that mapped the script layer show what a control looks like:

| needle | taken from | found on LeafGreen at | delta |
|---|---|---|---|
| 0x49050B80 | inside `ScrCmd_special` | 0x0806D7F4 | 0 |
| 0x4831D940 | the top of the handler block | 0x080701C0 | 0 |
| 0x49040A00 | inside the flag/var workers | 0x08071E1C | 0 |
| 0x47708008 | above `FlagGet` | 0x08071FC4 | 0 |
| 0x18210094 | inside `AddBagItem` | **0x0809DA80**, FireRed 0x0809DAAC | **−0x2C** |

The last row is the control: delta 0 is also what this scan answers against the *wrong console*, so the
zeros need a needle from above the boundary, where the delta is known to be −0x2C, to come back shifted.

### Literal pools, which are free pointer tables

A literal pool is a pointer table that costs nothing to obtain, and it reaches places no table
indexes: every compiled function keeps the addresses it touches in a pool immediately after its body, so
a 1 KB window of code is a few dozen pointers to wherever that code works. The only cost is placing the
same window on both cartridges, which is free where the *code* sits in a segment whose delta is already
known.

m4a is that case: its code is in `lib_text`, whose start is measured, and `lib_text` is inside the −0x24
segment. Its pools point at the sound data, which lives at the top of the ROM, in the largest gap. Two
1 KB dumps gave 24 pool words each, 13 identical (the RAM addresses and the constants), and every one of
the five cartridge pointers moved by the same amount:

| FireRed | LeafGreen | delta |
|---|---|---|
| 0x0847DCF8 | 0x0847CA20 | −0x12D8 |
| 0x0847DDAC | 0x0847CAD4 | −0x12D8 |
| 0x0847DF10 | 0x0847CC38 | −0x12D8 |
| 0x0849758C (`gMPlayTable`) | 0x084962B4 | −0x12D8 |
| 0x084975BC (`gSongTable`) | 0x084962E4 | −0x12D8 |

The pair proves its own alignment. `gMPlayTable` and `gSongTable` came back 0x30 apart on both
cartridges, and 0x30 is four `struct MusicPlayer` of twelve bytes, which is exactly what
`sound/music_player_table.inc` holds.

A 16-block dump is 16 KB of literal pools instead of one. Two such pairs gave 550 and 288 paired sites
and moved three boundaries at once, including finding the **−0x20 segment**, which nothing had seen: the
delta does not go −0x24 straight to −0x1C4, it stops at −0x20 for more than a megabyte on the way.

Pair by code offset, not by index. Two pools of 552 and 550 words, the builds do not emit quite the
same literals, pair in order until the first mismatch and then invent deltas (−0x53BADA0 and similar).
Keyed on the site, minus the segment's own delta, 550 sites appear in both.

A `bl` is a relative call, so the same instruction on the two cartridges resolves to two different
addresses whose difference is the delta *at the target*. A 16 KB window of handlers holds 834 of them.
`tools/frlg/cartridge_pair.py` reads both kinds out of every window this project holds on both
cartridges, 1592 points from dumps that were already on disk, taken for other reasons.

What says the pairing is real is that every site pairs (734 of 734, 834 of 834) and the deltas come
out quantised: four values per window, no outliers, nothing "nearly". A window placed wrongly does not do
that, the first version of the tool computed the LeafGreen offsets off the FireRed base and answered
with 64 different deltas, none of them repeated. Two further confirmations came from runs that knew
nothing about the method: the pairing puts LeafGreen's `AddBagItem` exactly where a needle scan measured
it, and `Random` where a literal-pool read did.

### Dumping both cartridges at the same address

This is the method that closed the map, and it needs no needle at all. Dump both cartridges at the
*same* address. If the delta there is *d*, the LeafGreen block holds what the FireRed block holds shifted
by *d*, and any |*d*| under a kilobyte leaves hundreds of bytes of overlap. Cross-correlating the two
blocks reads *d* straight off.

That is exactly what a bisection cannot do when the delta is the unknown, because aiming the LeafGreen
dump at the twin requires the delta. `memory-dump-scatter` sends the same 27 addresses to both consoles
and every block answers.

    ./.venv/bin/python scratchpad/direct_delta.py       # the delta at each paired block
    ./.venv/bin/python scratchpad/boundary_bytes.py     # and, inside a block, where it steps

Two boundaries fell *inside* a block, and inside a block the step is readable to the byte by asking,
window by window, which delta still matches. 346 KB of unmeasured boundary became 2036 bytes across the
five code steps, and every one of the 272 specials now has a LeafGreen address.

A wide gap between two deltas is not evidence that the delta steps once. What had been read as one
step from −0x1C4 to −0x12D8 across 421 KB is three: a block at 0x08442800 matches the LeafGreen block
a page below it at −0x124C, 436 of 436 bytes, and two further points 32 KB apart read −0x1240 before
−0x12D8 resumes.

Graphics can resemble itself, so each reading was checked against its neighbours rather than taken on its
own. At 0x08442800: −0x124C is 436/436, −0x1240 is 6.9%, −0x12D8 is 2.7%. At 0x08457000 the best is 74.7%
against 57.3% for the next candidate, and that one is recorded as not a verdict.

## Reading a LeafGreen dump against FireRed's tables

Every table this project holds was read off FireRed, so reading LeafGreen's dumps against those addresses
is coherent below the split and quietly wrong above it. `tools/frlg/rom_functions.py --console leafgreen`
moves the whole view, the entries, the bodies and the names, through the measured twins, and drops an
entry whose address falls inside a boundary rather than reading it at a guess. 184 of the 213 field
bodies and 33 of the 252 placeable specials come back, with the same three unnamed call targets FireRed
has, at LeafGreen's addresses.

The script layer is identical on both cartridges below 0x0807AF04
(`rom_map.SHARED_WITH_LEAFGREEN_THROUGH`): the `gScriptCmdTable` handler block (0x0806D7C0..0x080700B8),
the script engine (`ScriptContext_Stop`, `ScriptJump`, `ScriptCall`, `ScriptReturn`, the native-pointer
setter `callnative` uses), `GetVarPointer`, `VarGet`, `FlagSet`, `FlagClear`, `FlagGet`, and the
`_call_via_r0` veneer.

## The overworld, and a shiny Mewtwo

`gRngValue`, `gSaveBlock1Ptr` and `gSaveBlock2Ptr` are link-time IWRAM words at the same addresses as
FireRed's, and every literal in [the seek stubs](frlg_rng.md) is one of them, so the stubs needed no
porting. What was missing was somewhere to put a RAM script, since the player has to talk to a map object
and this save sits in Cerulean Cave B1F.

The binding went on Mewtwo. `initramscript` takes a map group, a map number and an object id, and
`GetRamScript` runs the given script *instead of* that object's own [field_control_avatar.c:458].
Cerulean Cave B1F is group 1 map 74 [data/maps/map_groups.json] and Mewtwo is object 3
[data/maps/CeruleanCave_B1F/map.json].

`rng-mon-hunt-both` was installed there with `setwildbattle` set to species 150 at level 70. Mewtwo's own
script did not run, the battle started immediately, and the Mewtwo that appeared was shiny.

Three things that were not certain before:

- The stray-draw search works on the second cartridge. The first attempt missed and the ones after it
  hit, both being the first talk after a load, so the miss is a placement miss rather than a wrong
  constant: the stub reads `TID ^ SID` off `gSaveBlock2Ptr` at run time [asm/field/mon-seek-both.s:73].
- The binding survives a power cycle. The player reset and talked to Mewtwo cold, and the script still
  ran. `gSaveBlock1Ptr` is re-rolled on every load, so that is the trampoline's run-time pointer read
  being right rather than lucky.
- A buffer script does not take the RAM script slot back, because it sends no card. Only a Wonder Card
  session does, and an ordinary card restored Mewtwo's own script through
  `InitRamScript_NoObjectEvent`.

While the RAM script was installed the console reported holding no Wonder Card, and the card was intact
throughout, see [the one RAM script slot](frlg_gift.md#the-one-ram-script-slot).

## A dumped region must not move

Pointing a `memory-dump` at 0x03004220 kills the link mid-transmission with *erreur de connexion*, because
that address is `gRngValue` and it advances two turns every frame while the CRC and the send happen on
different frames. Repeating the run unchanged fails identically with a *different* CRC pair, which is the
signature of a region that moves rather than one that is corrupted; dumping the same 32 bytes from ROM
returns the expected bytes and rules out the size. The mechanism and the guard are on
[Code on the console](frlg_rom.md#repointing-the-consoles-outgoing-message).

Reading the save-block pointers works by starting 4 bytes higher, and they verify themselves: both values
had moved by exactly 12 since an earlier reading, one shared 4-aligned offset inside the 0..124 range
`SetSaveBlocksPointers` rolls. Two pointers cannot agree on the size of a re-roll neither could have faked
alone.

## The English build as an instrument

`pret/pokefirered` builds a ROM, it builds both cartridges, and it builds them at REVISION 10, which
is the revision the Switch release runs:

    make firered_switch     -> pokefirered_switch.gba    baa452d0b24629dd7782cfc07a8984085dde1311
    make leafgreen_switch   -> pokeleafgreen_switch.gba  62b9fc77549dbc67032eb6cbd0ea6ad3b825690f

Both come out byte-identical to the sha1 the decomp pins, on a machine with binutils and `pret/agbcc`.
`scratchpad/build_decomp.sh` does it in about two minutes. The sha1 is the only reason any of this is
usable: a build that does not match is a build of something else. The ROM is never committed.

It is the English release, and at the same address a French console and the English build agree on
3.7% of their bytes: French text is a different length and everything after a string moves. Nothing
here reads as "the address in the build is the address on the console". What it is instead is a second
cartridge pair from the same source in the same link order, with every symbol, section and object known.

### The offset: French address to English address

Piecewise constant, stepping only where an object changes size between the languages, which in a code
region is rare, measured runs are tens of kilobytes long and one is 1.3 MB. Two independent readings
give it and they agree everywhere both speak:

- The tables, free. `gSpecials[i]`, `gScriptCmdTable[i]` and `gMysteryEventScriptCmdTable[i]` are the
  same function on both builds, so entry *i* on the console and entry *i* in the English ROM are an
  offset point. 675 of them, out of dumps already on disk.
- The dumps. A 16-byte window that occurs *exactly once* in the English ROM places any French bytes
  equal to it. A kilobyte of code carries a few hundred such windows, so one block votes hundreds of
  times for one offset, and a step inside a block shows up as two runs rather than a wrong answer.

      ./.venv/bin/python tools/frlg/english_build.py --offsets

### The control

The English build proposes a name for a French address: take the offset, add it, read the name off the
English ELF, which carries static functions, unlike the link map. Run against `worker_names`, every
name measured off the console's own function bodies, it comes back 232 agree, 0 disagree.

    ./.venv/bin/python tools/frlg/english_build.py --check

The one apparent disagreement was not one: `GetBoxMonData2` is
`__attribute__((alias("GetBoxMonData3")))` [pokemon.c:3332], one function with two symbols. The reader
keeps every name an address carries.

A name from here is a deduction. `rom_map.CALLABLE` means "called on hardware and something
happened"; `worker_names` means "the console's own body called it in the order the source says".
`pokeldn/frlg/rom/english_names.py` holds 7573 French function addresses named this way, generated by
`scripts/gen_english_names.py`, with the offset runs beside them.

`rom_functions` reads them last, marked `[english]`, so a deduction can fill a hole and never
overrule a body the console's own calls named. `gen_worker_names` passes `with_english=False`: a
deduction must not anchor the reading that produces it.

Of 177 call targets that had no name, two are left. 158 fall inside a measured offset run and are named
outright. The rest fall *between* two runs and get a weaker reading in `english_names.BRACKETED`: named
with one of the two offsets either side, accepted only when it lands exactly on a function start and only
one of the two does. An offset wrong by two bytes lands mid-instruction, which is what stands in for the
missing measurement; `rom_functions` marks them `[english?]`.

Three of those targets are reached from a dozen bodies each and had survived every other reading. The
English build reads them as `__divsi3`, `__modsi3` and `__umodsi3`, and the worker-naming pass, from a
direction that knew nothing about the English build, had already predicted the residue would be exactly
that: agbcc emitting a helper for a division nobody wrote.

### The English pair's own delta map

Comparing the two English ROMs to each other computes their delta map exactly, and it comes out as the
same six values the French cartridges measured, in the same order:

    +0x0   -0x2c   -0x28   -0x24   -0x20   -0x1c4

Each step happens inside a version-divergent object, not at its edge, which is why the link map's
symbols do not bracket it: the code inside `title_screen.o`, `mystery_event_script.o`, `mystery_gift.o`
and `pokemon.o` that differs between FireRed and LeafGreen carries no symbol common to both builds. Byte
comparison brackets each step to between 79 and 1606 bytes.

    ./.venv/bin/python tools/frlg/english_build.py --boundaries

Carried across by the offset map, that is a *prediction* of where the French boundary is, and every one
of the five landed inside the bracket measured on hardware, five independent agreements between two
methods that share nothing.

### Traps

- A `.gcc2_compiled.` symbol sits at the first symbol of its file and shadows the function name if the
  reader keeps only the first symbol at an address. Skip names beginning `.` or `$`.
- Padding matches at every delta. A window has to say something before its match means anything; 16
  distinct byte values is the threshold used here. Without it the 0xFF filler between objects reads as
  agreement with whatever was asked.
- The offset is not the delta. The offset is French → English on *one* cartridge; the delta is FireRed
  → LeafGreen on the console. They are related by
  `french delta = offsetFR - offsetLG + english delta`.
- Regenerate `english_names.py` with `scripts/gen_english_names.py` after any new dump.

## What did not work

`gSongTable` looked like the ideal spreader for the top of the ROM, 347 entries of `{header, ms, me}`
pointing into the largest blob in the cartridge. Dumping it showed the song *headers* packed together,
122 of them inside 9 KB, so the pointers do not spread and the table measures one place rather than many.
A graphics pointer table would be the next thing to try; the literal-pool method got there first and cost
less.

Incidentally, FireRed's ROM data ends between 0x08680400 and 0x08800000: 0x08800000 reads all `0xFF` and
0x08E00000 all `0x00`, while 0x08680000 is high-entropy data. Two different padding values, so those two
reads are not the same thing and neither has been chased. `gSongTable`'s song headers reach 0x086ABE68,
so the data runs at least that far.
