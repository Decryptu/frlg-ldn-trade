---
title: The random number generator
parent: Inside the console
nav_order: 5
---

# gRngValue: reading it, predicting it, and what cannot be done with it

Everything here was measured on the console (French FireRed, BPRF software version 0x0A), not taken
from the decomp's English build. Run tags in brackets.

## The generator

```c
u16 Random(void) { gRngValue = 1103515245 * gRngValue + 24691; return gRngValue >> 16; }
void SeedRng(u16 seed) { gRngValue = seed; }
```
[decomp:src/random.c, include/random.h:18]

| symbol | address | how it was obtained |
|---|---|---|
| `gRngValue` | `0x03004220` | `Random`'s literal pool [bs14] |
| `Random` | `0x080486B0` | found by scanning 4 MB for RAND_MULT [bs13] |
| `SeedRng` | `0x080486D0` | its pool names gRngValue a second time [bs14] |

`Random` returns only the **top half** of the state. That is what makes recovery non-trivial and
also what makes it possible: two draws give 32 bits, but the low half of the first state stays
unconstrained, so a personality alone leaves 2<sup>16</sup> candidate states.

`frlgsim/lcg.py` is the arithmetic. `distance(a, b)` is exact at any range via baby-step/giant-step
on the affine map — 2<sup>17</sup> operations instead of up to 2<sup>32</sup>. **The map is a
permutation of all 2<sup>32</sup> states, so a distance ALWAYS exists**; it is only evidence when it
is small (odds N / 2<sup>32</sup>).

## The rate: exactly two turns per frame

Measured three times, in three contexts, never assumed:

| context | measurement | run |
|---|---|---|
| Mystery Gift link menu | exactly 2, on 95 of 95 frame gaps | bs15 |
| overworld, standing still | 43,702 turns over 365.8 s = **2.000/frame** | bs55 |
| overworld, walking + 2 battles | 18,900 turns over 128.0 s = 2.472/frame | bs52 |

Standing still costs the same as anything else: **~119 turns a second, unconditionally**. Battles
add draws on top of that baseline. There is no idle state in which the RNG stops.

## Where the seed comes from, and why it cannot be carried

`SeedRng` has exactly four call sites. Two are unused debug screens [link.c:318,
link_rfu_2.c:2670]. The third is the title screen:

```c
void SeedRngAndSetTrainerId(void) { u16 val = REG_TM1CNT_L; SeedRng(val); gTrainerId = val; }
```
[decomp:src/main.c:264], called from `Task_TitleScreenMain` once the fade completes, immediately
before `SetMainCallback2(CB2_InitMainMenu)` [src/title_screen.c:735]. `StartTimer1` runs at
`CB2_InitTitleScreen` [:351], so the seed is a free-running hardware timer sampled at the moment
the player presses START — a 16-bit value, unpredictable, but **only 65536 possible**.

**THE TRAP, and it closed an entire line of work.** Backing out of Mystery Gift runs
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` → `CB2_InitTitleScreen`
[decomp:src/mystery_gift_menu.c:463]. Pressing START then re-runs the seeding. **There is no route
from the Mystery Gift menu to the overworld that does not reseed**, so a value set or read during a
link cannot reach an encounter. bs50 seeded `gRngValue` to `0xC0DE` and bs51's encounter was
**1,898,278,119 turns** away from it.

## The Switch-only reseed hook, and why it never fires

The Switch build carries a reseed that no GBA build has:

```c
if ((svc_4b() & SVC4B_RESEED_RNG) != 0)
    SeedRng(ReadU16(&GetHostRfuGameData()->compatibility.playerTrainerId));
```
[decomp:src/link_rfu_2.c:2114, inside `#if REVISION >= 0xA`]

`svc_4b` is `swi 0x4b`, a Sloop **emulator** syscall [src/sloopsvc.c:135], so the emulator decides
when it fires. `GetHostRfuGameData()` returns the console's own advertised data, whose
`playerTrainerId` comes from `gSaveBlock2Ptr->playerTrainerId` [src/link_rfu_3.c:854] — `0xDF65` on
this console.

**It does not fire**, for either activity that was tested:

- **Mystery Gift** [bs15]: `RfuMain1` runs every frame, so a set bit would pin the state near
  `0xDF65` continuously; the samples free-ran with gaps of exactly 2, and the state is
  1,374,895,295 turns from `0xDF65`.
- **Union Room** [ur01/bs54]: a full session — LinkPlayer exchange, trainer cards, a greeting, 199 s
  of RFU — then a Mankey on Route 22, whose state is 2,098,390,873 turns from `0xDF65`.

## Reading a Pokemon back into the state that made it

`GenerateWildMon` calls `CreateMonWithNature(..., USE_RANDOM_IVS, Random() % NUM_NATURES)`
[decomp:src/wild_encounter.c:233], which rolls the personality until it matches that nature, then
the IVs are drawn. A wild Pokemon is **four draws**: personality low, personality high, HP/ATK/DEF,
SPEED/SPATK/SPDEF.

The personality alone leaves 2<sup>16</sup> candidates; the two IV draws are 30 more bits of check
on the draws that follow, and exactly one state survives. `lcg.recover_wild_state`, and
`scratchpad/rng_encounter.py` on the command line.

**THERE ARE TWO GAPS AND BOTH MUST BE SEARCHED.** The console does not use one layout:

| Pokemon | gap before IVs | gap between IVs | method | run |
|---|---|---|---|---|
| Weedle | 1 | 0 | 2 | bs51 |
| Caterpie | 0 | 1 | 4 | bs52 |
| Weedle #2 | 0 | 1 | 4 | bs52 |
| Mankey | 0 | 1 | 4 | bs54 |
| Ditto (scripted) | 0 | 0 | 1 | bs53 |

Searching only the first gap finds the Weedle and **silently misses the other three** — they come
back as "no state builds this mon", which reads like a broken recovery rather than an incomplete
search. The stray draw is in no line of `CreateBoxMon`; it comes from outside the generation and is
recorded here as measured and unexplained.

The half-order of `Random32()` — `(Random() | (Random() << 16))`, whose operand order C does not
define — is **low half first**, at both call sites, on all five mons.

The mon's identity is established before any RNG claim is made: its PID and IVs predict the six
stats the console prints on its own summary screen. bs51's Weedle read 24/10/9/9/8/13 and nature
DOUX (MILD, 16); the recovery reproduced all seven.

## The scripted battle: choosing the Pokemon outright

```
setptr b0..b3 -> 0x03004220      gRngValue = seed          (opcode 0x11)
setwildbattle <species> <level>  CreateMon rolls PID, PID, IV, IV   (0xB6)
dowildbattle                     the battle starts          (0xB7)
```

`ScrCmd_setptr` writes an immediate byte to an absolute address, both read from the script
[decomp:src/scrcmd.c:300]. `setwildbattle` calls `CreateScriptedWildMon` →
`CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)`
[decomp:src/script_pokemon_util.c:128]: USE_RANDOM_IVS, no fixed personality, and **no nature
rejection loop**, so it is plain four-draw Method 1.

**There is no drift between the seed and the roll.** Both commands return `FALSE`, and the field
engine runs commands until one returns `TRUE`, so all four `setptr`s and the generation happen back
to back in a single frame. Nothing may be emitted between them that yields — a `playse` there would
break it silently, and a test asserts none is.

`gRngValue` may be named as a constant because it does **not** move: it is a link-time IWRAM global.
A save-block address may not — `SetSaveBlocksPointers` re-rolls a 4-aligned offset on every battle
and load [decomp:src/load_save.c:75], measured moving 76 bytes between two runs [bs45, bs46]. That
is why `setptr` is the right command here and `callnative` (0x23), though more powerful, would need
an address hunt and a sled.

Delivered as a RAM script bound to a map object by `initramscript`; it ends with `end` (0x02), not
`endram` (0x0d), so the binding survives being used and can be re-triggered.

**mev07 / bs53, first try.** Predicted offline before the console had seen the seed:

```
PREDICTED   PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
ACTUAL      PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
```

A wild shiny Lv50 DITTO appeared in PALLET TOWN and was caught. `setwildbattle` needs no grass and
no encounter roll: it is the code path a scripted battle uses, so it fires wherever the script runs.

## What cannot be done

**Read the RNG and hit a target by hand.** The state advances 2 turns every frame with no idle
state, roughly 1 frame in 4096 produces a shiny, and nothing signals which. That is a property of
the game, not of this tooling. The only actor fast enough to act on a reading is the console itself,
which means a script — one that reads `gRngValue` once a frame and fires at the right instant would
alter nothing, but it is still code installed in the save.

Pure observation does work as far as it goes: from one caught Pokemon the exact state is recovered,
and walking it back gives the 16-bit value the console booted on (`0x8E94` [bs52], `0x1376` [bs54]).
Those are readings, not levers.
