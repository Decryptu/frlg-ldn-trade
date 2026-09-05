---
title: The species table, and the first function worth calling
parent: Inside the console
nav_order: 4
---

# gSpeciesInfo, and finding CreateMon

Calling into the ROM was missing a reason, not a mechanism: `rng-trace` had called `Random` 96 times
and checked the result by the LCG's own arithmetic (bs15), but the thirteen functions in
`rom_map.py` were the Mystery Gift state machine we already drive from outside. bs37-bs42 are the
six runs that found something worth calling.

The target was `CreateMon`, which builds a Pokemon from a species, a level and a personality value.
The personality carries the Gen 3 shiny check together with the trainer ids bs01 read (TID 57189,
SID 58811), and nothing reachable from the Mystery Event VM lets us choose one.

## bs37: the full 16 MB scan, and a clean negative

`memory-scan` had only ever been pointed at 4 MB. bs37 ran it across the whole cartridge -
`0x08000000..0x09000000`, 1024 frames, about 17 seconds with the link held open - and came back
`0 match(es) ... the whole range was scanned`. The primitive works at full range; that is settled
and need not be re-proved.

The needle was wrong, and the way it was wrong is the useful part. It was built from
`friendship`, `growthRate` and `eggGroups` at a **26-byte** entry stride, which is what ISO
alignment gives for `struct SpeciesInfo` as the decomp declares it - its widest member is `u16`,
so the struct's alignment is 2 and its size 26.

Two hypotheses explain a zero, and they had to be separated before spending another run:

1. the French cartridge's species data differs from the English decomp's, or
2. the data is identical and the **layout** assumption is wrong.

**This was settled offline, with no hardware run.** `CalculateMonStats` [pokemon.c:2095] derives
every stored stat from the base stats plus level, IVs, EVs and nature, and bs06's party dump
carries all of them. Recomputing the five party mons' six stats each reproduced what the console
had stored, **30 out of 30**, across five species spread through the dex. Hypothesis 1 is dead: the
cartridge holds the decomp's values exactly.

## bs38: a fingerprint that survives every layout

If the stride is 28 rather than 26, then with a 4-aligned table bs37's needle at entry offset 18
is *never* word-aligned - and `memory-scan` reads with `ldmia`, so it only ever sees word-aligned
matches. Zero was the only answer it could have given.

The fix is a needle that cannot be defeated by the layout. Exactly one qualifies: **Mew, Celebi and
Jirachi all have their six base stats at 100**, so bytes `0x00..0x05` of those three entries are
`0x64` and the word `0x64646464` appears at entry offset 0 *and* at offset 2. One of the two is
word-aligned whatever the stride and whatever the table's own alignment. All four hypotheses were
executed offline against the real payload under unicorn before the run.

    scan: 3 match(es) for 0x64646464 in 0x08000000..0x08400000
       0x0824DE80   0x0824E970   0x0824FAB8

No false positives in 4 MB. The gaps are 2800 and 4424, which are 100 and 158 entries at **28**
bytes - the stride is a measurement now, not an assumption. `gSpeciesInfo = 0x0824CDFC`.

The link order predicted this a third time, after `src/random.o` in bs13 and `src/easy_chat.o` in
bs16: `src/pokemon.o` is the 26th `.rodata` entry in `ld_script.ld` and `src/easy_chat.o` the
104th, so the table had to sit early in rodata and below the word data bs17 measured at
`0x083DE2C8`. It does.

## bs39: reading it

A dump 60 bytes before the base, so the answer did not depend on the ±2 the gaps leave open (both
alignments produce identical gaps). **34 of 34 entries byte-identical to the decomp**, 884 bytes
compared. The two extra bytes are `00 00` on every entry, so the ROM pads the struct to 28 rather
than carrying fields the decomp is missing.

Four apparent mismatches on the first pass were all bugs in the model built from the decomp, not
in the console: `[SPECIES_NONE] = {0},` is a one-line block a multi-line regex swallows,
`genderRatio` is the macro `PERCENT_FEMALE(x)`, `noFlip` is a bitfield that is not always set, and
constants defined in hex are missed by a decimal-only `#define` regex. The console was right every
time.

## bs40: the address as the needle

Scanning for `0x0824CDFC` itself finds every function carrying `&gSpeciesInfo` in its literal pool.
31 hits in `0x08028000..0x08048800`, a range bounded above by `Random` at `0x080486B0`.

The hits are not one pool per function - five of them sit exactly `0x14` apart, which is one large
function emitting the constant in several pools. Counting is therefore not evidence; the object
boundaries are.

## bs41: a refuted guess

The largest gap (37 KB) looked like the `pokemon.o` boundary, so the first hit above it was dumped.
It disassembles as `battle_ai_switch_items.c:88`:

    movs r0, #1          @ TRUE
    bl   0x0803CD94      @ HasSuperEffectiveMoveAgainstOpponents(TRUE)
    bl   0x080486B0      @ Random
    movs r1, #3
    bl   0x081E2D00      @ % 3

Not `pokemon.o`. The run is what makes the next boundary trustworthy rather than a second guess:
the gap above it is 15.6 KB and is explained - `src/battle_controller_link_opponent.o` sits there
in link order and references `gSpeciesInfo` nowhere, which is exactly why no hits fall in it.

## bs42: CreateMon

A dump at the first hit of `pokemon.o`'s block gives a function matching [pokemon.c:1755] line for
line, and identified by two constants the decomp fixes independently - `SetMonData` with field 56
(`MON_DATA_LEVEL`), then field 64 (`MON_DATA_MAIL`) carrying 255 (`MAIL_NONE`), between
`CreateBoxMon` and `CalculateMonStats`:

| symbol | address | how |
| --- | --- | --- |
| `CreateMon` | `0x08041150` | disassembled, matches pokemon.c:1755 instruction for instruction |
| `CreateBoxMon` | `0x080411C0` | the call CreateMon makes between ZeroMonData and SetMonData |
| `ZeroMonData` | `0x08041090` | CreateMon's first call |
| `SetMonData` | `0x08043A78` | called with MON_DATA_LEVEL then MON_DATA_MAIL |
| `CalculateMonStats` | `0x08041B78` | CreateMon's last call |

`CreateMon` takes eight arguments; the first four arrive in `r0..r3` and the rest on the stack.
`fixedPersonality` is the one that matters - it is the value the shiny check runs on.

## Calling it

The payload exists: `asm/create-mon.s`, `--buffer-script create-mon`, written against the prologue
above rather than against a calling convention taken on trust, and proven offline against two
models of the callee. It answers the destination problem by not having one - the mon is built
inside the payload's own 1024 bytes, where nothing but the payload can be hurt, and read back from
there; `--create-mon-destination` copies it onward afterwards and needs `--write-unsafe`.
[Native code on the console](buffer_script.md) has the whole of it, including bs43 and bs44, which
ran it on hardware with all eight arguments and got 13/13 predicted fields back.
