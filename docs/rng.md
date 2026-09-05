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

## The rate: exactly 2 turns per frame, and how a wrong number got in here

**This section was wrong until the user challenged it, and the correction matters more than the
number.** Separate what is exact from what is a wall clock:

- **The turn COUNTS are exact.** 43,702 and 18,900 are `lcg.distance()` between two states each
  established independently - baby-step/giant-step, exact arithmetic, no timing anywhere.
- **Every "per frame" rate is `turns / (seconds x 59.7275)`, and the seconds were hand-supplied.**
  `rng_chain.py --elapsed` is an argument typed in by the operator.

| context | measurement | clock? | run |
|---|---|---|---|
| Mystery Gift link menu | gaps of exactly 2, on 95 of 95 consecutive frames | **none** | bs15 |
| overworld, standing still | 43,702 turns, elapsed not independently measured | circular | bs55 |
| overworld, walking + 2 battles | 18,900 turns over a hand-timed 128 s | hand-timed | bs52 |

**bs15 is the only real rate measurement, and it is the one with no clock in it.** `rng-trace`
sampled `gRngValue` once a frame and took the difference between adjacent samples: the gaps were
exactly 2, 95 times out of 95. No stopwatch, no frame-rate constant, no assumption. It is also the
narrowest: it was taken at the Mystery Gift link menu, where the game is running the RFU link loop
and nothing else.

**bs55's row was circular and is retracted as evidence.** 43,702 / 2 / 59.7275 = 365.84 s, and
365.8 s is what this document used to quote as the *measured* elapsed time. That number was
`lcg.seconds(43702)` - the tool's own output, computed by assuming 2 turns per frame - printed back
into the table and then used to confirm the assumption it came from. The session notes describe the
same run as "five minutes of standing still"; at 300 s the same 43,702 turns give 2.44/frame.

bs52's 128.0 s *is* independent (2 turns/frame would predict 158.2 s), but it is a hand-timed 128
seconds, and a 30-second error in it is entirely ordinary. So **"walking adds draws" does not
follow from these numbers either** - 2.47 and "2.44 if the five minutes was really five minutes"
are the same figure within the error of the clock that produced them.

**The answer, measured afterwards with no clock at all, is exactly 2 turns per frame** - see
"Measuring the rate with the clock removed" below (mev09, mev10) and the four press trials, whose
turn counts are all even. The same rate bs15 found at the link menu. So the retracted figures were
not a different rate in a different situation; they were a stopwatch being wrong.

**The lesson outlives the number, which is why this section stays.** One turn is ~8 ms, so nothing
downstream may rest on a hand-timed elapsed. The two clocks that need no seconds at all are the ones
everything here is built on:

- **two seed readings** give the exact turns between them, by `distance()`; that also measures the
  overworld rate properly, for the first time, whenever we want the number for its own sake;
- **the mon that appears** is an exact position fix, via `recover_wild_state`.

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
| Magikarp (scripted) | 0 | 0 | 1 | mev19 |
| Magikarp (scripted) | 1 | 0 | 2 | mev20 |
| Magikarp (scripted) | 0 | 0 | 1 | mev21 |

Searching only the first gap finds the Weedle and **silently misses the other three** — they come
back as "no state builds this mon", which reads like a broken recovery rather than an incomplete
search. The stray draw is in no line of `CreateBoxMon`; it comes from outside the generation and is
recorded here as measured and unexplained.

The half-order of `Random32()` — `(Random() | (Random() << 16))`, whose operand order C does not
define — is **low half first**, at both call sites, on every mon in the table.

**A SCRIPTED ENCOUNTER IS NOT IMMUNE, and mev20 is where that was learned.** bs53's Ditto and
mev19's Magikarp were both Method 1, which had made it reasonable to treat `setwildbattle` as the
clean path. mev20 asked for shiny + Jolly + SPEED ≥ 20 and the console produced a shiny **Jolly**
Magikarp with SPEED **10**. The state is not in doubt — exactly one state in 2<sup>32</sup> has
that PID on its next two draws:

    state 0x429D2189
      draws 3,4 -> 15/0/12/25/7/14      what the stub tested: SPEED 25, passes
      draws 4,5 -> 25/7/14/10/10/30     the mon that appeared

So the search was correct and one `Random()` ran between the personality and the IVs. On a scripted
encounter the stray draw is **intermittent, not absent**, which is worse than always-present: a
one-placement search is right most of the time and silently wrong the rest.

### Searching so the stray draw cannot move the answer

`asm/field/mon-seek-both.s` tests the floors at **two** placements, and two cover all three methods.
Let d3, d4, d5 be the draws after the personality:

| method | first triple (HP/ATK/DEF) | second triple (SPE/SPATK/SPDEF) |
|---|---|---|
| 1 (clean) | d3 | d4 |
| 2 (mev20) | d4 | d5 |
| 4 (bs52, bs54) | d3 | d5 |

Word A is `d3 | d4<<15` and word B is `d4 | d5<<15`. Requiring both puts the first triple's floors
on d3 *and* d4, and the second triple's on d4 *and* d5 — so Method 4 passes without its word ever
being built. The proof is the four placements, not the two words.

The cost is search and not iteration: the hot loop is the same fifteen instructions and the IV
block is reached by 1 state in 8192, so only the IV term is squared — shiny + Jolly + SPEED ≥ 20
goes from 1 state in 546,000 to 1 in 1,456,000, about 4 s of frozen overworld typically. The cap
is set at 95% rather than 99% on purpose: the script ends in `end`, so the binding survives and a
miss costs one more A press, while a 99% cap costs 18 s of stare on the unlucky run.

**This stub is 232 bytes and could not have been staged.** `setptr` allowed 162. It exists because
the payload moved into the RAM script body — see below.

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

## mev11 + bs58: a mon predicted from a seed WE DID NOT SET

mev07 predicted a shiny Ditto and got it, but it *wrote* `gRngValue` first. This one writes nothing
to the RNG at all. The script read the live state the console had chosen for itself, printed it,
generated a mon from it, and printed the state again:

```
BEFORE  0x9A4F5DAA        (read off the console, not set by us)
AFTER   0x8EEB8648
```

Predicted offline from `BEFORE` alone, then checked against the caught mon dumped out of
`gPlayerParty` [bs58]:

| field | predicted | actual |
|---|---|---|
| PID | 0x0BF87DD1 | 0x0BF87DD1 |
| nature | 13 Jolly | 13 Jolly |
| shiny | no | no |
| IVs | 25/10/28/9/19/3 | 25/10/28/9/19/3 |

**Seven fields, all of them.** That closes the read-only chain end to end: the address, the atomic
read, the draw order, and the offset between a reading and the generation - which is **zero**. The
four draws start at the state that was read.

### The draw count, and the code disagreeing with the console

`distance(BEFORE, AFTER)` is **6**, and `CreateBoxMon` says **4**: `Random32()` for the personality
(2), no draws for the OT because the player is the OT [decomp:src/pokemon.c:1796], and 2 for the IVs
[`:1836,1845`]. `CreateScriptedWildMon` adds none [src/script_pokemon_util.c:128].

The extra 2 land **after** the generation, not before it - which is what the seven matching fields
prove, since a mon built from `advance(BEFORE, 2)` would have had a different PID. Two turns is
exactly one frame of overworld consumption, the same constant the rate probe measured as the `+2` in
`2N + 2`.

This is the same family as the stray draw recorded above for wild encounters, and it is worth
stating plainly: **the decomp is authoritative for what the code does, and it is not the last word
on what this cartridge does.** Deriving the 4 first is what makes the 6 a finding rather than a
number.

## How precisely a human can press A: measured, not guessed

Four trials against a chosen target 30.00 s ahead, read off the seed-printing NPC (mev14):

| trial | frames elapsed | error vs 1791.8 |
|---|---|---|
| 1 | 1801 | +9.2 |
| 2 | 1807 | +15.2 |
| 3 | 1800 | +8.2 |
| 4 | 1796 | +4.2 |

**Mean +9.2 frames, standard deviation 4.5 frames, whole range 11 frames.** The mean is a fixed
offset - the gap between the numbers appearing on screen and the script's read, plus press to read -
and it cancels. The **spread** is what matters: presses land within about +/- 6 frames of where they
are aimed.

Every one of the four turn counts is **even**, which it has to be if the state only moves 2 per
frame. That is a check passing on data taken for another purpose, and it extends the rate result to
ordinary overworld play with the player standing in a room - not just to a script that is delaying.

A fifth trial, discarded, read +39.2 frames: it was taken against the wandering Pallet Town NPC and
most of the error was the player chasing him. That is why the scripts bind to the mother now.

**What that makes the hand-aimed hunt.** A shiny frame arrives every ~8192 frames (~137 s), and a
press with a 4.5-frame spread lands on one chosen frame about 9% of the time - roughly 1 attempt in
11. So a shiny costs on the order of 25 minutes of waiting, against about 23 hours of random
encounters for the same odds. A miss costs one A press and is measured exactly, because the script
prints the state it generated from.

This is no longer how a shiny is obtained - *The stub that does the search* below removes the aim
entirely - but it remains the route when the RAM script slot is holding a Wonder Card, and the
press-spread numbers are the measurement of the player, not of the method.

## What cannot be done, and what is still open

**Closed, and DONE: read-only prediction.** A live seed is readable in the overworld, the rate is
exact, the offset from a reading to the generation is zero, and mev11/bs58 predicted seven fields of
a mon the console built from a state it chose for itself.

**And aiming is closed too, which this section used to say it was not.** The sentence here read
"what is left is aiming, and aiming is a human pressing A". That was true of everything the field
bytecode could do and false of what the field engine can RUN: a staged native stub does the search
itself at the moment of the encounter. mev15 proved it on hardware, twice, and mev16 again. See
*The stub that does the search*.

**Closed: aiming with no live seed at all.** The state advances 2 turns every frame with no idle
state, ~1 frame in 8192 produces a shiny, and without a reading nothing signals which. That was the
original wall, and reading the seed is what went through it.

**CLOSED FOR FIELD BYTECODE, AND THAT TURNED OUT NOT TO BE THE LAST WORD.** The paragraph this
replaces said the script cannot be told where to aim, and every clause of it is still true: the
target has to be computed from a seed read at runtime, installing a script that knows the target
needs a Mystery Gift session, that session leaves through the title screen and **reseeds**, and
field bytecode has `compare` and `goto_if`, not an LCG walk and a shiny test. What it missed is
that the field engine can run something that is not bytecode. See *The stub that does the search*
below; `frlgsim/rng_countdown.py` and the hand-aimed countdown remain what you use when the RAM
script slot is holding a Wonder Card instead.

**Closed: hitting a chosen seed by timing the START press.** Timer 1 runs at F/1 and a frame is
280,896 cycles, so if the read were frame-aligned every seed would be a multiple of
`gcd(280896 mod 65536, 65536) = 64`. Recovered seeds are `0xB8C0` (mod 64 = 0), `0x3742` (2),
`0x8E94` (20), `0x1376` (54). Three of four are not multiples, so there is sub-frame jitter in when
`REG_TM1CNT_L` is sampled and the press frame does not determine the seed. (Those four are best
candidates from `predecessors`, not certainties, but the lattice model predicts all four would be
multiples.)

**BUILT: an NPC that reads the seed out** (`--gift rng-seed-reader`). With a live reading in the
overworld the countdown works. The six commands are:

```
copybyte gSpecialVar_0x8000+0, 0x03004220      (opcode 0x15, byte at any address to any address)
copybyte gSpecialVar_0x8000+1, 0x03004221
copybyte gSpecialVar_0x8001+0, 0x03004222
copybyte gSpecialVar_0x8001+1, 0x03004223
buffernumberstring 0, VAR_0x8000               (0x83)
msgbox                                          the NPC prints the value
```

Installed once as a RAM script by `initramscript`, ending in `end` (0x02) so the binding survives and
can be re-triggered. It alters nothing: `gRngValue` is only read.

**THE READ IS ATOMIC, AND THAT IS THE PART THAT COULD HAVE GONE WRONG SILENTLY.** The RNG never
idles, so four byte copies spread over four frames would TEAR - the halves would come from different
states and the reassembled word would be a value the console never held, which looks exactly like a
working script returning a plausible number. `copybyte` and `buffernumberstring` both return
`FALSE`, and the field engine runs commands until one returns `TRUE`, so all six run back to back
inside one frame. Nothing that yields may be emitted between them, and a test asserts none is.

**And the text pointer had to be relative.** A RAM script lives in `gSaveBlock1Ptr->ramScript`, and
`SetSaveBlocksPointers` re-rolls that base on every battle and load, so an absolute pointer to the
script's own message is wrong the moment anything happens. `setvaddress` (0xB8) sets
`sAddressOffset = addr2 - (ctx->scriptPtr - 1)` [decomp:src/scrcmd.c:171] - the difference between a
base we choose and the command's own runtime address - and `vmessage` (0xBD) subtracts it, so the
operand becomes a plain offset into our own body. The Mystery Event VM's relocation, in the field
engine.

`buffernumberstring` prints a **u16** [decomp:src/scrcmd.c:1678], which is why the 32-bit seed takes
two vars and the message two lines. It also takes a var ID rather than an address, so only
`copybyte`'s destination ever needed the address hunt.

**THE BLOCKER IS GONE (bs57, first try): `gSpecialVar_0x8000` = `0x020370B4`.**

It was found by SHAPE, not by any value. `gSpecialVars` is a ROM table of pointers, so it holds no
constant to search for — its entries *are* the addresses being looked for. But entries 0..11 point
at `gSpecialVar_0x8000..0x800B`, twelve `u16`s declared consecutively [decomp:src/event_data.c:16],
so each word sits exactly 2 above the last. `table-scan` (docs/buffer_script.md) searched
0x08140000..0x08400000 for a twelve-word run rising by 2, found **exactly one** in 2.75 MB, and the
run's first value is the answer:

| symbol | address | how |
|---|---|---|
| `gSpecialVars` | `0x081639A8` | the only twelve-word run rising by 2 in 2.75 MB [bs57] |
| `gSpecialVar_0x8000` | `0x020370B4` | that run's first entry, read out by the same run [bs57] |

Four checks, none a re-reading of the same measurement: `gScriptCmdTable` is 214 entries and opens
`script_data` with `gSpecialVars` right after it, putting the section at 0x08163650 — above the
highest address read as code (0x08148C74, bs08) by 106 KB, which is what the ~25 objects linked
after `mystery_gift_client.o` need; the pointer lands in EWRAM; it is above `gPlayerParty`
(0x02024280), as the EWRAM link order requires since `event_data.o` follows `pokemon.o`; and it is
`u16`-aligned.

It may be hardcoded for the same reason `gRngValue` may: it is `EWRAM_DATA`, a link-time global.
A save-block address may not.

**Still to confirm on the console**: only entry 0 was read. `gSpecialVar_0x8001` is +2 by the
declaration order, which the script needs and which a dump of `gSpecialVars` would settle — but
the script itself is the better test. Talk to the NPC twice and check that the two printed values
satisfy the LCG recurrence at a plausible distance apart: a wrong address prints something that
does not, which is the same proof bs15 used to settle `gRngValue` itself.

**mev08: IT WORKS, AND IT CONFIRMS THE ADDRESS.** The script was installed (status 55, the console
saved by itself), and the man in the south of Pallet Town was asked twice, about twenty seconds
apart:

```
reading 1   RNG HI 4685   RNG LO 26687   -> 0x124D683F
reading 2   RNG HI 54871  RNG LO 55616   -> 0xD657D940
distance    2,595 turns
```

Two unrelated 32-bit numbers sit ~2**31 apart; these are **2,595** apart, odds 1 in 1,655,093. So
0x020370B4 is `gSpecialVar_0x8000`, the read does not tear, and there is now a live seed readout in
the overworld. (~130 turns/second against the user's own estimate of twenty seconds - which is an
estimate, and is NOT recorded here as the overworld rate. That is what the rate probe below is for.)

**WHERE TO BIND IT, learned the hard way.** mev08 through mev13 used the Pallet Town man mev03 had
used. Both Pallet Town object events are `MOVEMENT_TYPE_WANDER_AROUND`
[decomp:data/maps/PalletTown/map.json], so he walks off mid-countdown and the player has to chase
him to press A - which is the one thing a timed press cannot afford; the first calibration trial
read +39 frames, most of it the chase. Everything binds to the **player's mother** now (group 4, map
0, object 1): `MOVEMENT_TYPE_FACE_LEFT`, flag 0 so she is never hidden, indoors, a step from where
the player stands. Nothing in the script depends on the object standing still - the requirement
comes from what the script is FOR, which is why no test caught it.

## Measuring the rate with the clock removed instead of improved

Every earlier attempt at the overworld rate divided an exact turn count by a hand-timed elapsed, and
one divided by a number computed from the answer it was checking. The fix is not a better stopwatch.

```
bool8 ScrCmd_delay(struct ScriptContext * ctx)
{
    sPauseCounter = ScriptReadHalfword(ctx);
    SetupNativeScript(ctx, RunPauseTimer);
    return TRUE;
}
```
[decomp:src/scrcmd.c:651]

`delay` yields and resumes after **exactly** that many frames. So `--gift rng-rate-probe` reads
gRngValue, delays N frames, reads it again and prints both: `lcg.distance` gives the numerator
exactly and N is the denominator exactly, and `rng_script.measure_rate` divides them. No clock, no
rounding to argue about. 600 frames at ~2 turns each is ~1200 turns, twenty million times below the
2**32 point where a distance stops being unique.

**What it measures, stated precisely, because this distinction is what made the old numbers wrong:**
the rate while a field script is DELAYING, with the player locked. That is not self-evidently the
rate while the player is walking, and it will not be reported as if it were. It *is* exactly the
rate a script that waits for a target state would run at - the design where the game does the aiming
instead of a human with a stopwatch - so it is the number that design needs. `lock=False` measures
the unlocked case, one variable at a time.

### The answer: exactly 2 turns per frame, settled

| run | frames (exact) | turns (exact) | 2N + 2 |
|---|---|---|---|
| mev09 | 600 | 6002 -> no; **1,202** | 1202 |
| mev10 | 3000 | **6,002** | 6002 |

Two runs, five times apart in N, byte-identical scripts but for the `delay` operand. Both land on
`2N + 2` to the turn. The competing model - a rate of 2.003333/frame, which fits mev09's single
point just as well - predicts 6010 at N=3000 and is **refuted**.

So the overworld consumes **exactly 2 turns per frame**, the same rate bs15 measured at the Mystery
Gift link menu, and the constant +2 is one extra frame of consumption around the `delay` (2 turns),
not a difference in rate. There is no clock anywhere in this: `lcg.distance` is exact arithmetic and
the frame counts are what `delay` was told to wait.

**This retires the last of the hand-timed numbers.** "Walking adds draws" (2.472/frame) and the
"2.44 if the five minutes was really five minutes" reading were both measurement error in a
stopwatch, exactly as suspected. The rate was 2 all along.

**And it makes the countdown arithmetic exact**: the state n frames after a reading is
`advance(S, 2n)`, with no estimated constant in it.

Why the countdown then works, with numbers: the state at any future frame is `advance(S, 2n)`, ~1 in
8192 is shiny, so a target arrives roughly every 8192 frames (~137 s). A miss costs **nothing** -
unlike Emerald, where every attempt costs a reset and a new unknown seed - because the same NPC can
be asked again and the target recomputed. Shininess is visible the moment the battle starts, so the
mon need not even be caught.

The trigger can be the same NPC: `setwildbattle` + `dowildbattle` **read** the RNG (four draws, like
any encounter) and write nothing, so one A press replaces menu-and-Sweet-Scent navigation and is the
most precise input the game offers.

What remains a judgement call, not a technical question: installing that script is a write to the
save, though never to the RNG.


## The stub that does the search

`--gift rng-shiny-hunt`, `frlgsim/native_script.py`, `asm/field/shiny-seek.s`.
**PROVEN ON HARDWARE, mev15, first try - and then a second time.** The card installed, the player
talked to their MOM in PALLET TOWN, and the Ditto that appeared was SHINY. They fled and talked
again: shiny again, from a different state, which is the part that makes it a mechanism rather than
a coincidence - a one-in-8192 event does not happen twice in two attempts. One run settles
`callnative` on this build, the `setptr` staging, execution out of gDecompressionBuffer, the Thumb
entry through bit 0, the trainer id read out of gSaveBlock2Ptr, and the draw model of
CreateScriptedWildMon, all at once.

**A battle moves the save block the script lives in, and that is a trap, not a detail.**
`CB2_InitBattle` and `InitOverworldBgs` both call `MoveSaveBlocks_ResetHeap`
[decomp:src/battle_main.c:614, src/overworld.c:1337], which re-rolls gSaveBlock1's address by a
multiple of 4 in 0..124 (`SAVEBLOCK_MOVE_RANGE` 128, src/load_save.c:75). A RAM script lives in
`gSaveBlock1Ptr->ramScript.data.script` and the engine runs it **through a pointer into that block**
[GetRamScript, decomp:src/script.c:514] which it keeps across the battle. So the field engine
resumes at an address the script no longer occupies, and **nothing written after `dowildbattle` is
reachable**. One mechanism, three symptoms already recorded here: mev11's stray second battle (the
landing hit a 0xB6/0xB7), mev15/mev16 walking away clean (it hit the zero fill, which is `nop`), and
**mev18 freezing the overworld dead** - no A, no B, no START, the app had to be killed - because the
bigger stub pushed the resume point to byte 972 of 995, where a negative shift lands inside the
six-byte `setptr` records and decodes a command that waits for ever. `releaseall` + `end` was never
a fix.

**The fix is to start the battle from outside the save block**, in ten bytes
[`rng_script.battle_and_exit`]:

    setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02  =  dowildbattle ; end
    goto   0x020370B4

gSpecialVar_0x8000 is 0x020370B4 [bs57] and does not move; nothing in the battle or overworld code
writes it (`gSpecialVar_0x8000` appears only in event_data.c's table and scrcmd.c's var commands,
and no field script runs during a battle). `ScriptContext_RunScript` calls
`UnlockPlayerFieldControls()` the moment a script stops [decomp:src/script.c:335], so the `end`
beside it is what gives the player back. **mev19 confirmed it on hardware**: caught the mon, walked
away, saved.

**The human is out of the loop entirely.** There is no press to time, no frame to aim at and no
countdown to recompute; talking to the NPC is the whole procedure, and it is repeatable because the
binding survives (`end`, not `endram`).

The two commands that matter are in the field script table beside the ones this document already
uses:

```c
bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
{ u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
{ void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
```
[decomp:src/scrcmd.c:300, :120]

`setptr` writes one arbitrary byte to one arbitrary address, and this document already used four of
them to set gRngValue. The bytes it writes can be **code**, and `callnative` runs them. So a RAM
script can stage a payload into EWRAM and execute it - in the overworld, which is the one place
`CLI_RUN_BUFFER_SCRIPT` could never reach.

**This came from outside the project.** notblisy/RUBYSAPPHIREDLC does exactly this on
Ruby/Sapphire: `SOURCE/*/eonticket.asm` stages sixteen bytes with sixteen `writebytetoaddr` and
`callasm`s them, and `SOURCE/*/celebirng.txt` is an LCG loop that runs until the PID would be
shiny. Different game, different delivery (dot codes over the e-Reader's link cable, which the
Switch release does not expose at all), not one usable address. The technique transfers.
REFERENCES.local.md has the reading.

**Why there is no aiming left.** `CreateScriptedWildMon` is
`CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)`
[decomp:src/script_pokemon_util.c:128], so `hasFixedPersonality` is 0 and the personality is
`Random32()` - two draws - while `OT_ID_PLAYER_ID` reads the save and draws nothing. Shininess is
decided by the **first two draws after the state at that instant**, and nothing else. `setptr`,
`callnative` and `setwildbattle` all return FALSE, so the field engine runs the whole script in one
pass without yielding a frame: the state the stub leaves in gRngValue is the state
`CreateScriptedWildMon` consumes two commands later. No press, no spread, no ~26 minutes.

**The budget, which is the only thing that binds.** A RAM script body is 995 bytes
[`struct RamScriptData.script`, decomp:include/global.h:439] and a staged byte costs six of them,
so at most ~163 bytes of code. That is why the stub is THUMB rather than ARM - `callnative` calls
through a function pointer, so bit 0 of the staged address selects the instruction set.
`shiny-seek` is 80 bytes; the whole hunt script is 492 of 995.

    setptr x80 -> 0x0201C000..0x0201C04F      gDecompressionBuffer [rom_map, bs08/bs11]
    callnative 0x0201C001 (THUMB)
    setwildbattle species 132 Lv50 item 0
    dowildbattle

**The stub reads the trainer id off the console** rather than being handed one: gSaveBlock2Ptr is a
pointer at a fixed IWRAM address even though the block it points at moves, and playerTrainerId is
at +0x0A. The same 80 bytes are therefore correct on FireRed and on LeafGreen, and no id has to be
known or kept in step. It writes exactly one word, gRngValue, and reads nothing else.

**It cannot hang, and that matters more here than in a buffer script.** A buffer script that loops
for ever freezes the Mystery Gift menu; a field stub that loops for ever freezes the overworld
inside a script, with no menu at all. The search is bounded, and on exhaustion gRngValue is left
untouched and the player gets an ordinary encounter. Every stub is run under unicorn before it can
be staged (`tests/test_native_script.py`), and the answer is checked against `rng_countdown` - the
model that predicted seven fields of a mon the console built for itself in mev11/bs58 - so the
search and the check are written from different directions.

**Cost on the console: not noticeable.** The estimate was ~1 frame typical and 5.2 frames worst of
40 emulated runs (15 instructions an iteration, ~8192 iterations, ~3 cycles an instruction out of
16-bit EWRAM, against 280,896 cycles a frame). mev15 reported nothing unusual either time - no
reported hitch between the A press and the battle - which is consistent with the estimate but does
not measure it.


## Choosing the nature and the IVs, not just the shine

`--gift rng-mon-hunt`, `asm/field/mon-seek.s`, flagId 1019. Same mechanism as above with all four
draws tested instead of the first two: the personality decides shininess **and** the nature
(`personality % 25` [decomp:src/pokemon.c:5020]), and draws 3 and 4 are the six IVs
[decomp:src/pokemon.c:1836, HP/ATK/DEF then SPE/SPATK/SPDEF]. Nothing between them draws, so one
state settles the whole mon.

**PROVEN ON HARDWARE, mev19 + bs62.** Asked for shiny + Jolly + Speed IV >= 20 on a level 5
MAGIKARP; the player talked to their MOM, caught it, and a party dump read back PID 0x01503B8A,
shiny value 4, **Jolly**, IVs 6/2/25/**28**/12/7. `lcg.recover_wild_state` puts the console at
0x7041F74F, which reproduces that PID and all six IVs through `rng_countdown` - so the stub found
the state it was asked for and the ROM did the rest. Level 5 Magikarp because the nature and the
IVs cannot be read off a screen: the mon has to be **caught** for the run to prove anything, and
catch rate 255 at level 5 is one Ultra Ball.

**The filter order is the cost model.** Shininess is tested in the hot loop, whose fifteen
instructions are the whole search rate; the division by 25 and the six IV comparisons sit in a
block only 1 state in 8192 reaches, so they cost nothing on average. A criterion never slows an
iteration down - it multiplies how many are needed:

| asked for | 1 state in | typical freeze | worst at the cap |
|---|---|---|---|
| shiny | 8,192 | 0.02 s | 0.10 s |
| shiny + one nature | 204,800 | 0.55 s | 2.5 s |
| shiny + nature + one IV >= 20 | 546,133 | 1.5 s | 6.7 s |
| shiny + two IVs = 31 | 8,388,608 | 22 s | refused |

`native_script.search_cost` computes this and the host refuses, on the command line, anything whose
worst case exceeds `--hunt-freeze-frames` (default 900, ~15 s), because the field engine has not
returned while it searches: the player sees a still frame with the music playing. **mev19 measured
the pause at about 1 second** against an estimate of 1.5 s typical, so the clock arithmetic is
close enough to quote.

**160 bytes of the 163 the budget allows**, and the margin shaped the code: the shiny value is its
own inverse so pidLo comes back in two instructions instead of being kept in a register; the
divisor is its own loop counter; the IV floors carry a terminator bit at 30 so the loop needs no
counter; both fields shift up to bits 27..31 so a five-bit comparison is an ordinary unsigned one.

    --hunt-nature adamant,jolly   --hunt-iv speed=31 --hunt-iv attack=20   --hunt-cap N

## The payload moved into the script body: 755 bytes instead of 162

Every stub above is staged by `setptr`, which writes **one** byte and spends **six** script bytes
saying so — an opcode, the immediate, and a 4-byte absolute address. Against a 995-byte RAM script
body that is ~162 bytes of code, and `asm/field/mon-seek.s` is at 160 of them. Every register in
that file is reused as hard as it is because of this one number.

The cap comes off, and the reason is one line of the decomp:

```c
const u8 *GetRamScript(u8 objectId, const u8 *script)
{ ... return scriptData->script; }
```
[decomp:src/script.c:514]

The field engine does **not** copy the body anywhere. It runs it **in place**, out of
`gSaveBlock1Ptr->ramScript.data.script`. So the whole body is already in EWRAM while the script
runs — and the bytes after the script's last command are never read by the engine at all. They are
storage that has already been delivered, at one script byte each.

The only thing that ever made that unusable was aiming at it. This document and
`frlgsim/rng_script.py` both said so: the save block "carries a random 4-aligned offset re-rolled on
every battle and load" [`SetSaveBlocksPointers`, decomp:src/load_save.c:75], measured 76 bytes apart
in bs45 vs bs46. **That argument is about a build-time constant.** The offset is re-rolled at a
battle or a load and is fixed for the whole frame our script runs in, and `&gSaveBlock1Ptr` is a
link-time IWRAM word at 0x03004228 that says what it currently is. Read the pointer at run time and
the target is exact — no sled, no search, no aiming.

`asm/field/ram-jump.s` is 36 bytes and is now the only thing that still pays six:

| | staged | body |
|---|---|---|
| cost per payload byte | 6 script bytes | 1 script byte |
| room in a 995-byte body | 162 bytes of code | **755 bytes** |

    setptr x36    the trampoline, into gDecompressionBuffer        216 bytes
    callnative    -> trampoline -> payload -> back                   5
    setwildbattle / setvar / goto                                   16
    pad to a multiple of four                                        3
    payload                                                        755

It is a **tail branch**, not a call: `bx r0` with `lr` untouched, so the payload's own
`pop {r4-r7, pc}` returns straight to `ScrCmd_callnative`'s caller and the script carries on to the
battle. ARMv4T has no `blx <reg>` and does not need one here.

**The guard is the whole safety argument.** The trampoline checks `ramScript.data.magic` is
`RAM_SCRIPT_MAGIC` = 51 [decomp:src/script.c:12] before it branches. If the save-block offset is not
what the host thinks, that byte is not 51 and the stub **returns** — the player gets an ordinary
encounter, which is a miss and not a frozen overworld. There is no menu to back out of in the field,
so a wrong address must not be able to execute anything.

### The trap: a multiple of four, not merely an even offset

A Thumb stub reaches its literal pool with `ldr rN, [pc, #imm]` and its own tail with `adr`, and
**both use `Align(PC, 4)`**. The assembler lays those immediates out believing the code begins
word-aligned. Place the same bytes two off and the branch still lands, the code still runs, and
every pool word is read two bytes past where it lives — for `mon-seek-far` that is a filler length
of `0x0433CF15` and a fault inside its own checksum loop. An even offset is enough to *branch*,
which is exactly what makes the bug quiet.

Four is also **sufficient**, and provably: `offset = (Random()) & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)`
[decomp:src/load_save.c:75] is `& 0x7C`, and `gSaveBlock1` is an EWRAM struct of u32 fields, so the
base is word-aligned and `RAMSCRIPT_BODY_OFFSET` (0x3624) keeps it that way. Nothing checks it at
run time because nothing can make it false.

This was caught by `native_script.emulate_body_script`, which walks the **real** script bytes — the
36 `setptr`s, the `callnative`, the trampoline reading `gSaveBlock1Ptr`, the branch back into the
body — rather than running a stub at an address a harness chose. That is bs56's lesson applied
before the run instead of after it.

### Proving the size rather than the jump, on hardware

Moving the code proves itself: if the branch missed, nothing shiny appears. That would prove the
*jump* and say nothing about the *size*. So `asm/field/mon-seek-far.s` is followed by non-zero
filler out to the last byte of the 995, and the stub sums it and refuses to search unless the sum
matches. `InitRamScript` zero-fills what it was not given [`ClearRamScript`, decomp:src/script.c:495],
so a short delivery sums **low** and the stub leaves `gRngValue` alone.

**mev20, first try**: 995 bytes, 196 of stub and 559 of filler, `--gift rng-mon-hunt-far`. The player
talked to their MOM and caught a shiny Jolly Magikarp — which the console could only produce if the
filler sum matched, so the whole body arrived and ran from inside the save block. The overworld
paused 2–3 s, consistent with the three-criteria search and not with a search that skipped a test.

**mev21, first try**, `--gift rng-mon-hunt-both`: the 232-byte two-placement stub, same criteria.
Shiny, Jolly, **SPEED 22**. State 0xFCB5674F, and the point is the whole row:

| method | IVs | floors |
|---|---|---|
| 1 (clean) | 4/1/10/**22**/14/21 | ok — what the console made |
| 2 (mev20's) | 22/14/21/**25**/1/18 | ok |
| 4 (bs52, bs54) | 4/1/10/**25**/1/18 | ok |

**Stated precisely**: the console used Method 1 this time, so this run did not itself exercise a
stray-draw encounter. What it shows is that the search now accepts *only* states that are correct
whichever method fires, and that asking for that costs nothing but search. Method-independence is
established by the derivation above and by the offline tests; hardware has confirmed the stub
searches correctly and the mon comes out right. A run that catches Method 2 in the act would be
confirmation on top, not the basis of the claim.

Scripted encounters so far: bs53 Method 1, mev19 Method 1, mev20 **Method 2**, mev21 Method 1 —
one in four, on a path that had looked clean.

**The freeze, measured twice.** mev20 (one placement, expected 1.5 s) paused 2–3 s; mev21 (two
placements, expected 3.9 s) paused about 7 s. The RATIO is right — 2.8 observed against 2.6
predicted — so the cost model scales correctly. Both absolute figures run high, which would mean
`CYCLES_PER_INSTRUCTION_FROM_EWRAM = 3` is optimistic. HYPOTHESIS ONLY: a single search is
exponentially distributed, so two samples above the mean is unremarkable and settles nothing.
