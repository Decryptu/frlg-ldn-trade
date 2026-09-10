---
title: The random number generator
parent: FireRed and LeafGreen
nav_order: 5
---

# gRngValue: reading it, predicting it, and aiming it

Everything here was measured on French FireRed, BPRF software version 0x0A, not taken from the
decomp's English build.

## The generator

```c
u16 Random(void) { gRngValue = 1103515245 * gRngValue + 24691; return gRngValue >> 16; }
void SeedRng(u16 seed) { gRngValue = seed; }
```

[src/random.c, include/random.h:18]

| symbol | address | how it was obtained |
|---|---|---|
| `gRngValue` | `0x03004220` | `Random`'s literal pool |
| `Random` | `0x080486B0` | found by scanning 4 MB for `RAND_MULT` = 0x41C64E6D |
| `SeedRng` | `0x080486D0` | its pool names `gRngValue` a second time |
| `gSpecialVars` | `0x081639A8` | the only twelve-word run rising by 2 in 2.75 MB |
| `gSpecialVar_0x8000` | `0x020370B4` | that run's first entry, read out by the same run |

`RAND_MULT` cannot be encoded by any ARM or THUMB instruction, so it sits in `Random`'s literal pool
next to `&gRngValue`. A scan for it returned eleven hits across 4 MB; the decomp's link order
picked the right one without a run, `grep -rl 'ISO_RANDOMIZE1\|RAND_MULT' src/` gives eight files, and
`ld_script.ld` puts `src/random.o` at #86 with the next user, `src/title_screen.o`, at #123, so the
lowest hit is random.o's pool. Dumping it gives `Random` instruction for instruction
[random.c:9-13], and `SeedRng` follows with the same pool word, two independent functions naming
`gRngValue` in one dump.

`Random` returns only the top half of the state. That is what makes recovery non-trivial and also what
makes it possible: two draws give 32 bits, but the low half of the first state stays unconstrained, so
a personality alone leaves 2<sup>16</sup> candidate states.

`pokeldn/frlg/rom/lcg.py` is the arithmetic. `distance(a, b)` is exact at any range via
baby-step/giant-step on the affine map, 2<sup>17</sup> operations instead of up to 2<sup>32</sup>. The
map is a permutation of all 2<sup>32</sup> states, so a distance always exists; it is evidence only
when it is small (odds N / 2<sup>32</sup>).

`gRngValue` and `gSpecialVar_0x8000` are link-time globals that do not move, so hardcoding them is
sound. A save-block address is not: `SetSaveBlocksPointers` re-rolls a 4-aligned offset on every battle
and load [load_save.c:75], measured moving 76 bytes between two runs.

## The rate: exactly 2 turns per frame

`ScrCmd_delay` yields and resumes after exactly that many frames [scrcmd.c:651], so
`--gift rng-rate-probe` reads `gRngValue`, delays N frames, reads it again and prints both.
`lcg.distance` gives the numerator exactly and N is the denominator exactly, so
`rng_script.measure_rate` divides them with no clock anywhere.

| frames (exact) | turns (exact) | 2N + 2 |
|---|---|---|
| 600 | 1,202 | 1202 |
| 3000 | 6,002 | 6002 |

Two runs five times apart in N, byte-identical scripts but for the `delay` operand, both landing on
`2N + 2` to the turn. The competing model (2.003333 per frame, which fits N=600 just as well) predicts
6010 at N=3000 and is refuted. The constant +2 is one extra frame of consumption around the `delay`.

`rng-trace` measured the same 2 at the Mystery Gift link menu by a different route: sampling `gRngValue`
once a frame gave gaps of exactly 2, 95 times out of 95, with no stopwatch in it. That second answer is
about the console rather than the tool, between a call in one frame and a read in the next, the game
had turned the RNG exactly twice, which is FRLG's own Random consumption while it sits in the Mystery
Gift link menu.

So the state n frames after a reading is `advance(S, 2n)`, with no estimated constant in it.

The probe measures the rate while a field script is *delaying*, with the player locked; `lock=False`
measures the unlocked case. Four independent press trials (below) give turn counts that are all even,
which extends the result to ordinary overworld play.

Nothing here may rest on a hand-timed elapsed. One turn is about 8 ms. Earlier figures on this
subject were wrong because they divided an exact turn count by a hand-timed elapsed, and one of them
divided by a number the tool had itself computed by assuming the answer. The two clocks that need no
seconds at all are two seed readings (`distance`) and the mon that appears (`recover_wild_state`).

## Where the seed comes from, and why it cannot be carried

```c
void SeedRngAndSetTrainerId(void) { u16 val = REG_TM1CNT_L; SeedRng(val); gTrainerId = val; }
```

[main.c:264], called from `Task_TitleScreenMain` once the fade completes, immediately before
`SetMainCallback2(CB2_InitMainMenu)` [title_screen.c:735]. `StartTimer1` runs at `CB2_InitTitleScreen`
[:351], so the seed is a free-running hardware timer sampled at the moment the player presses START:
unpredictable, but only 65536 possible values.

This closes the whole idea of setting the seed during a link. Backing out of Mystery Gift runs
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` → `CB2_InitTitleScreen` [mystery_gift_menu.c:463],
and pressing START there re-runs the seeding. There is no route from the Mystery Gift menu to the
overworld that does not reseed. Seeding `gRngValue` to `0xC0DE` and then taking an encounter gave a
state 1,898,278,119 turns away from it.

`SeedRng` has exactly four call sites and three of them cannot happen during a link:

| site | when |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] | the title screen |
| `LinkTestScreen` [link.c:318] | unused debug screen |
| `Debug_RfuIdle` [link_rfu_2.c:2670] | unused debug screen |
| `RfuMain1` [link_rfu_2.c:2116] | Switch-only, gated on a Sloop syscall |

The Switch-only reseed does not fire:

```c
if ((svc_4b() & SVC4B_RESEED_RNG) != 0)
    SeedRng(ReadU16(&GetHostRfuGameData()->compatibility.playerTrainerId));
```

[link_rfu_2.c:2114, inside `#if REVISION >= 0xA`]. `RfuMain1` runs every frame while RFU is up, so a
set bit would pin the state near the console's own advertised `playerTrainerId` (`0xDF65` here)
continuously. It does not: sampled at the Mystery Gift menu the state free-ran with gaps of exactly 2
and its first sample was 1,374,895,295 turns from `0xDF65`, and after a full Union Room session an
encounter was 2,098,390,873 turns from it. Keep that as a control on any run that reads the RNG: a
state that turns out to descend from `0xDF65` names the hook instead of leaving a run unexplained.

Hitting a chosen seed by timing the START press does not work either. Timer 1 runs at F/1 and a
frame is 280,896 cycles, so a frame-aligned read would make every seed a multiple of
`gcd(280896 mod 65536, 65536) = 64`. Recovered seeds are `0xB8C0` (mod 64 = 0), `0x3742` (2), `0x8E94`
(20), `0x1376` (54), three of four are not multiples, so `REG_TM1CNT_L` is sampled with sub-frame
jitter and the press frame does not determine the seed.

## Reading a Pokemon back into the state that made it

`GenerateWildMon` calls `CreateMonWithNature(..., USE_RANDOM_IVS, Random() % NUM_NATURES)`
[wild_encounter.c:233], which rolls the personality until it matches that nature, then draws the IVs. A
wild Pokemon is four draws: personality low, personality high, HP/ATK/DEF, SPEED/SPATK/SPDEF.

The personality alone leaves 2<sup>16</sup> candidates; the two IV draws are 30 more bits of check on
the draws that follow, and exactly one state survives. `lcg.recover_wild_state`, and
`scratchpad/rng_encounter.py` on the command line. The half-order of `Random32()`,
`(Random() | (Random() << 16))`, whose operand order C does not define, is low half first, at both call
sites, on every mon measured.

There are two gaps and both must be searched. The console does not use one layout:

| Pokemon | gap before IVs | gap between IVs | method |
|---|---|---|---|
| Weedle | 1 | 0 | 2 |
| Caterpie | 0 | 1 | 4 |
| Weedle #2 | 0 | 1 | 4 |
| Mankey | 0 | 1 | 4 |
| Ditto (scripted) | 0 | 0 | 1 |
| Magikarp (scripted) | 0 | 0 | 1 |
| Magikarp (scripted) | 1 | 0 | 2 |
| Magikarp (scripted) | 0 | 0 | 1 |
| Magikarp (scripted) | 0 | 1 | 4 |

Searching only the first gap finds the Weedle and silently misses the others: they come back as "no
state builds this mon", which reads like a broken recovery rather than an incomplete search. The stray
draw is in no line of `CreateBoxMon`. It comes from outside the generation and is recorded here as
measured and unexplained.

A scripted encounter is not immune, and it is worse there than an always-present draw would be: on
a scripted encounter the stray draw is intermittent, so a one-placement search is right most of the
time and silently wrong the rest. One run asked for shiny + Jolly + SPEED >= 20 and the console produced
a shiny Jolly Magikarp with SPEED 10. The state is not in doubt, exactly one state in 2<sup>32</sup>
has that PID on its next two draws:

    state 0x429D2189
      draws 3,4 -> 15/0/12/25/7/14      what the stub tested: SPEED 25, passes
      draws 4,5 -> 25/7/14/10/10/30     the mon that appeared

So the search was correct and one `Random()` ran between the personality and the IVs.

The mon's identity is established before any RNG claim is made: its PID and IVs predict the six stats
the console prints on its own summary screen.

## The scripted battle

```
setptr b0..b3 -> 0x03004220      gRngValue = seed          (opcode 0x11)
setwildbattle <species> <level>  CreateMon rolls PID, PID, IV, IV   (0xB6)
dowildbattle                     the battle starts          (0xB7)
```

`ScrCmd_setptr` writes an immediate byte to an absolute address, both read from the script [scrcmd.c:300].
`setwildbattle` calls `CreateScriptedWildMon` →
`CreateMon(&gEnemyParty[0], species, level, 32, 0, 0, OT_ID_PLAYER_ID, 0)` [script_pokemon_util.c:128]:
`USE_RANDOM_IVS`, no fixed personality, and no nature rejection loop, so it is plain four-draw Method 1.

There is no drift between the seed and the roll. Both commands return FALSE, and the field engine
runs commands until one returns TRUE, so all four `setptr`s and the generation happen back to back in a
single frame. Nothing that yields may be emitted between them (a `playse` there would break it silently), and a
test asserts none is.

Delivered as a RAM script bound to a map object by `initramscript`, ending in `end` (0x02) rather than
`endram` (0x0d), so the binding survives being used and can be re-triggered.

Predicted offline before the console had seen the seed:

```
PREDICTED   PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
ACTUAL      PID 0x026F38B2   nature 17   IVs 31/23/27/18/30/30   shiny
```

A wild shiny Lv50 Ditto appeared in Pallet Town and was caught. `setwildbattle` needs no grass and no
encounter roll: it is the code path a scripted battle uses, so it fires wherever the script runs.

### A mon predicted from a seed nobody set

A second script writes nothing to the RNG at all: it reads the live state the console had chosen for
itself, prints it, generates a mon from it, and prints the state again.

```
BEFORE  0x9A4F5DAA        (read off the console, not set by us)
AFTER   0x8EEB8648
```

Predicted offline from `BEFORE` alone and checked against the caught mon dumped out of `gPlayerParty`:
PID 0x0BF87DD1, nature 13 Jolly, not shiny, IVs 25/10/28/9/19/3, seven fields, all of them. That closes
the read-only chain end to end: the address, the atomic read, the draw order, and the offset between a
reading and the generation, which is zero. The four draws start at the state that was read.

`distance(BEFORE, AFTER)` is 6 where `CreateBoxMon` says 4: `Random32()` for the personality (2), no
draws for the OT because the player is the OT [pokemon.c:1796], and 2 for the IVs [:1836,1845]. The
extra 2 land *after* the generation, not before it, which is what the seven matching fields prove,
since a mon built from `advance(BEFORE, 2)` would have had a different PID. Two turns is exactly one
frame of overworld consumption. Deriving the 4 first is what makes the 6 a finding rather than a number.

## The seed-reading NPC

`--gift rng-seed-reader`, flag id 1015. Six commands, installed once as a RAM script by `initramscript`
and ending in `end` so the binding survives:

```
copybyte gSpecialVar_0x8000+0, 0x03004220      (opcode 0x15, byte at any address to any address)
copybyte gSpecialVar_0x8000+1, 0x03004221
copybyte gSpecialVar_0x8001+0, 0x03004222
copybyte gSpecialVar_0x8001+1, 0x03004223
buffernumberstring 0, VAR_0x8000               (0x83)
msgbox                                          the NPC prints the value
```

It alters nothing. `rng_script.seed_from_printed(low, high)` reassembles the word.

The read is atomic, and that is the part that could have failed silently. The RNG never idles, so
four byte copies spread over four frames would tear: the halves would come from different states and the
reassembled word would be a value the console never held, which looks exactly like a working script
returning a plausible number. `copybyte` and `buffernumberstring` both return FALSE and the field engine
runs commands until one returns TRUE, so all six run back to back inside one frame. A test asserts
nothing that yields is emitted between them.

The text pointer has to be relative. A RAM script lives in `gSaveBlock1Ptr->ramScript` and the base
is re-rolled on every battle and load, so an absolute pointer to the script's own message is wrong the
moment anything happens. `setvaddress` (0xB8) sets `sAddressOffset = addr2 - (ctx->scriptPtr - 1)`
[scrcmd.c:171] and `vmessage` (0xBD) subtracts it, so the operand becomes a plain offset into the
script's own body.

`buffernumberstring` prints a `u16` [scrcmd.c:1678], which is why the 32-bit seed takes two vars and the
message two lines. It takes a var id rather than an address, so only `copybyte`'s destination ever needed
an address hunt.

The proof is talking twice. The same NPC was asked twice, about twenty seconds apart:

```
reading 1   RNG HI 4685   RNG LO 26687   -> 0x124D683F
reading 2   RNG HI 54871  RNG LO 55616   -> 0xD657D940
distance    2,595 turns
```

Two unrelated 32-bit numbers sit about 2<sup>31</sup> apart; these are 2,595 apart, odds 1 in
1,655,093. A wrong address prints values that do not satisfy the recurrence at any plausible distance.
`rng_script.check_two_readings`.

Where to bind it. Both Pallet Town object events are `MOVEMENT_TYPE_WANDER_AROUND`
[data/maps/PalletTown/map.json], so an NPC there walks off mid-countdown and the player has to chase him
to press A. Everything binds to the player's mother now (group 4, map 0, object 1):
`MOVEMENT_TYPE_FACE_LEFT`, flag 0 so she is never hidden, indoors, a step from where the player stands.
Nothing in the script depends on the object standing still, the requirement comes from what the script
is *for*, which is why no test caught it.

## How precisely a human can press A

Four trials against a chosen target 30.00 s ahead, read off the seed-printing NPC:

| trial | frames elapsed | error vs 1791.8 |
|---|---|---|
| 1 | 1801 | +9.2 |
| 2 | 1807 | +15.2 |
| 3 | 1800 | +8.2 |
| 4 | 1796 | +4.2 |

Mean +9.2 frames, standard deviation 4.5, whole range 11. The mean is a fixed offset (screen to script
read, plus press to read) and cancels; the spread is what matters, and presses land within about ±6
frames of where they are aimed. Every one of the four turn counts is even, which it has to be if the
state only moves 2 per frame, a check passing on data taken for another purpose.

A fifth trial read +39.2 frames and is discarded: it was taken against the wandering NPC and most of the
error was the player chasing him.

A shiny frame arrives every ~8192 frames (~137 s), and a press with a 4.5-frame spread lands on one
chosen frame about 9% of the time, so a hand-aimed shiny costs on the order of 25 minutes against about
23 hours of random encounters. A miss costs one A press and is measured exactly, because the script
prints the state it generated from. `pokeldn/frlg/rom/rng_countdown.py` is the countdown and
`--aimed-at STATE` turns a missed press into a signed frame count.

This is no longer how a shiny is obtained, but it remains the route when the RAM script slot is holding a
Wonder Card.

## The stub that does the search

`--gift rng-shiny-hunt`, `pokeldn/frlg/rom/native_script.py`, `asm/field/shiny-seek.s`. Proven on
hardware twice in one session: the card installed, the player talked to their mother in Pallet Town, and
the Ditto that appeared was shiny; they fled, talked again, and it was shiny again from a different
state. A one-in-8192 event does not happen twice in two attempts.

Two commands make it possible:

```c
bool8 ScrCmd_setptr(struct ScriptContext * ctx)          // 0x11
{ u8 value = ScriptReadByte(ctx); *(u8 *)ScriptReadWord(ctx) = value; }
bool8 ScrCmd_callnative(struct ScriptContext * ctx)      // 0x23
{ void (*func)(void) = ((void (*)(void))ScriptReadWord(ctx)); func(); return FALSE; }
```

[scrcmd.c:300, :120]

`setptr` writes one arbitrary byte to one arbitrary address, and the bytes it writes can be code,
which `callnative` runs. So a RAM script can stage a payload into EWRAM and execute it in the overworld,
the one place `CLI_RUN_BUFFER_SCRIPT` cannot reach.

The technique came from outside the project: `notblisy/RUBYSAPPHIREDLC` does this on Ruby/Sapphire,
staging sixteen bytes with `writebytetoaddr` and `callasm`ing them, with an LCG loop that runs until the
PID would be shiny. Different game, different delivery, not one usable address; the technique transfers.

There is no aiming left. `hasFixedPersonality` is 0 in `CreateScriptedWildMon`, so the personality is
`Random32()` (two draws), and `OT_ID_PLAYER_ID` reads the save and draws nothing. Shininess is decided by
the first two draws after the state at that instant and nothing else. `setptr`, `callnative` and
`setwildbattle` all return FALSE, so the field engine runs the whole script in one pass without yielding:
the state the stub leaves in `gRngValue` is the state `CreateScriptedWildMon` consumes two commands
later.

The stub reads the trainer id off the console rather than being handed one: `gSaveBlock2Ptr` is a
pointer at a fixed IWRAM address even though the block it points at moves, and `playerTrainerId` is at
+0x0A. The same bytes are therefore correct on FireRed and on LeafGreen. It writes exactly one word,
`gRngValue`, and reads nothing else.

It cannot hang, and that matters more here than in a buffer script: a buffer script that loops
forever freezes the Mystery Gift menu, but a field stub that loops forever freezes the overworld inside a
script, with no menu at all. The search is bounded, and on exhaustion `gRngValue` is left untouched and
the player gets an ordinary encounter. Every stub runs under unicorn before it can be staged
(`tests/test_native_script.py`), and the answer is checked against `rng_countdown`, so the search and the
check are written from different directions.

### A RAM script may not come back from a battle

`CB2_InitBattle` and `InitOverworldBgs` both call `MoveSaveBlocks_ResetHeap` [battle_main.c:614,
overworld.c:1337], which re-rolls `gSaveBlock1`'s address by a multiple of 4 in 0..124
[`SAVEBLOCK_MOVE_RANGE` 128, load_save.c:75]. A RAM script lives in
`gSaveBlock1Ptr->ramScript.data.script` and the engine runs it through a pointer into that block
[`GetRamScript`, script.c:514], which it keeps across the battle. The field engine therefore resumes at
an address the script no longer occupies, and nothing written after `dowildbattle` is reachable.

One mechanism, three symptoms: a stray second battle (the landing hit a 0xB6/0xB7); walking away clean
(it hit the zero fill, which is `nop`); and a frozen overworld with no A, no B and no START, the app
killed from the Switch menu, because a bigger stub pushed the resume point to byte 972 of 995, where a
negative shift lands inside the six-byte `setptr` records and decodes a command that waits forever.
`releaseall` + `end` was never a fix.

The fix is to start the battle from outside the save block, in ten bytes
[`rng_script.battle_and_exit`]:

    setvar 0x8000, 0x02B7      ->  0x020370B4: B7 02  =  dowildbattle ; end
    goto   0x020370B4

`gSpecialVar_0x8000` does not move, and nothing in the battle or overworld code writes it (it appears
only in `event_data.c`'s table and `scrcmd.c`'s var commands, and no field script runs during a battle).
`ScriptContext_RunScript` calls `UnlockPlayerFieldControls()` the moment a script stops [script.c:335],
so the `end` beside it gives the player back.

No RAM script may rely on an address inside the save block surviving a yield that involves a battle or
a map load.

## Choosing the nature and the IVs

`--gift rng-mon-hunt`, `asm/field/mon-seek.s`, flag id 1019. The same mechanism with all four draws
tested instead of the first two: the personality decides shininess and the nature
(`personality % 25` [pokemon.c:5020]), and draws 3 and 4 are the six IVs [pokemon.c:1836, HP/ATK/DEF then
SPE/SPATK/SPDEF]. Nothing between them draws, so one state settles the whole mon.

    --hunt-nature adamant,jolly   --hunt-iv speed=31 --hunt-iv attack=20   --hunt-cap N

Proven on hardware: asked for shiny + Jolly + Speed IV >= 20 on a level 5 Magikarp, the player talked to
their mother, caught it, and a party dump read back PID 0x01503B8A, shiny value 4, Jolly, IVs
6/2/25/28/12/7, which `lcg.recover_wild_state` puts at state 0x7041F74F and `rng_countdown`
reproduces field for field. Level 5 Magikarp because the nature and the IVs cannot be read off a screen:
the mon has to be caught for the run to prove anything, and catch rate 255 at level 5 is one Ultra Ball.

The filter order is the cost model. Shininess is tested in the hot loop, whose fifteen instructions
are the whole search rate; the division by 25 and the six IV comparisons sit in a block only 1 state in
8192 reaches, so they cost nothing on average. A criterion never slows an iteration down, it multiplies
how many are needed:

| asked for | 1 state in | typical freeze | worst at the cap |
|---|---|---|---|
| shiny | 8,192 | 0.02 s | 0.10 s |
| shiny + one nature | 204,800 | 0.55 s | 2.5 s |
| shiny + nature + one IV >= 20 | 546,133 | 1.5 s | 6.7 s |
| shiny + two IVs = 31 | 8,388,608 | 22 s | refused |

`native_script.search_cost` computes this and the host refuses, on the command line, anything whose worst
case exceeds `--hunt-freeze-frames` (default 900, about 15 s): the field engine has not returned while it
searches, so the player sees a still frame with the music playing.

`mon-seek.s` is 160 bytes of the 163 the staging budget allowed, and the margin shaped the code: the
shiny value is its own inverse so `pidLo` comes back in two instructions, the divisor is its own loop
counter, the IV floors carry a terminator bit at 30 so the loop needs no counter, and both fields shift
up to bits 27..31 so a five-bit comparison is an ordinary unsigned one.

## The payload in the script body

Every stub above is staged by `setptr`, which writes one byte and spends six script bytes saying so
(opcode, immediate, 4-byte absolute address). Against a 995-byte RAM script body that is about 162 bytes
of code.

The cap comes off because of one line:

```c
const u8 *GetRamScript(u8 objectId, const u8 *script)
{ ... return scriptData->script; }
```

[script.c:514]. The field engine does not copy the body anywhere. It runs it in place, out of
`gSaveBlock1Ptr->ramScript.data.script`, and never reads past the last command. Bytes appended after it
are storage that has already been delivered, at one script byte each.

The only obstacle was aiming at it, and that argument was about a *build-time* constant. The save-block
offset is re-rolled at a battle or a load and is then fixed for the whole frame the script runs in, and
`&gSaveBlock1Ptr` is a link-time IWRAM word at 0x03004228 that says what it currently is. Read the
pointer at run time and the target is exact, no sled, no search, no aiming.

`asm/field/ram-jump.s` is 36 bytes and is the only thing that still pays six per byte:

| | staged | body |
|---|---|---|
| cost per payload byte | 6 script bytes | 1 script byte |
| room in a 995-byte body | 162 bytes of code | 755 bytes |

    setptr x36    the trampoline, into gDecompressionBuffer        216 bytes
    callnative    -> trampoline -> payload -> back                   5
    setwildbattle / setvar / goto                                   16
    pad to a multiple of four                                        3
    payload                                                        755

It is a tail branch, not a call: `bx r0` with `lr` untouched, so the payload's own `pop {r4-r7, pc}`
returns straight to `ScrCmd_callnative`'s caller and the script carries on to the battle. ARMv4T has no
`blx <reg>` and does not need one here.

The guard is the whole safety argument. The trampoline checks that `ramScript.data.magic` is
`RAM_SCRIPT_MAGIC` = 51 [script.c:12] before it branches. If the save-block offset is not what the host
thinks, that byte is not 51 and the stub returns, the player gets an ordinary encounter, a miss rather
than a frozen overworld. There is no menu to back out of in the field, so a wrong address must not be
able to execute anything.

### Alignment must be a multiple of four, not merely even

A THUMB stub reaches its literal pool with `ldr rN, [pc, #imm]` and its own tail with `adr`, and both use
`Align(PC, 4)`. The assembler lays those immediates out believing the code begins word-aligned. Place the
same bytes two off and the branch still lands, the code still runs, and every pool word is read two bytes
past where it lives, for one stub that meant a filler length of `0x0433CF15` and a fault inside its own
checksum loop. An even offset is enough to branch, so the fault appears later and elsewhere.

Four is also sufficient, and provably: `offset = Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)`
[load_save.c:75] is `& 0x7C`, and `gSaveBlock1` is an EWRAM struct of u32 fields, so the base is
word-aligned and `RAMSCRIPT_BODY_OFFSET` (0x3624) keeps it that way.

`native_script.emulate_body_script` catches it, because it walks the real script bytes (the 36
`setptr`s, the `callnative`, the trampoline reading `gSaveBlock1Ptr`, the branch back into the body)
rather than running a stub at an address a harness chose.

### Proving the size rather than the jump

If the branch missed, nothing shiny appears, which proves the *jump* and says nothing about the *size*.
So `asm/field/mon-seek-far.s` is followed by non-zero filler out to the last byte of the 995, and the stub
sums it and refuses to search unless the sum matches. `InitRamScript` zero-fills what it was not given
[`ClearRamScript`, script.c:495], so a short delivery sums low and the stub leaves `gRngValue` alone.

Proven on hardware first try with `--gift rng-mon-hunt-far`: 995 bytes, 196 of stub and 559 of filler,
and the player caught a shiny Jolly Magikarp, which the console could only produce if the filler sum
matched.

## Searching so the stray draw cannot move the answer

`asm/field/mon-seek-both.s` (232 bytes, `--gift rng-mon-hunt-both`, flag id 1001) tests the floors at
two placements, and two cover all three methods. Let d3, d4, d5 be the draws after the personality:

| method | first triple (HP/ATK/DEF) | second triple (SPE/SPATK/SPDEF) |
|---|---|---|
| 1 (clean) | d3 | d4 |
| 2 | d4 | d5 |
| 4 | d3 | d5 |

Word A is `d3 | d4<<15` and word B is `d4 | d5<<15`. Requiring both puts the first triple's floors on d3
*and* d4, and the second triple's on d4 *and* d5, so Method 4 passes without its word ever being built.
The proof is the four placements, not the two words.

The cost is search and not iteration: the hot loop is the same fifteen instructions and the IV block is
reached by 1 state in 8192, so only the IV term is squared. Shiny + Jolly + SPEED >= 20 goes from 1 state
in 546,000 to 1 in 1,456,000, about 4 s of frozen overworld typically. The cap is set at 95% rather than
99% deliberately: the script ends in `end`, so the binding survives and a miss costs one more A press,
while a 99% cap costs 18 s of stare on the unlucky run.

This stub is 232 bytes and could not have been staged; it exists because the payload moved into the body.

On hardware, one run produced shiny, Jolly, SPEED 22 from state 0xFCB5674F, and the whole row is the
point:

| method | IVs | floors |
|---|---|---|
| 1 (clean) | 4/1/10/22/14/21 | ok, what the console made |
| 2 | 22/14/21/25/1/18 | ok |
| 4 | 4/1/10/25/1/18 | ok |

The console used Method 1 that run, so it did not itself exercise a stray draw; what it shows is that the
search accepts only states that are correct whichever method fires.

A later run with the logging stub caught one in the act. The console wrote the state it found into the
save and a dump read it back; the logged state predicts the caught mon's PID exactly, with no brute force
and no candidate ambiguity, and the IVs came from Method 4:

    logged found state 0x4FB97B07
      Method 1 (clean)  25/10/30/20/ 9/25
      Method 2 (stray)  20/ 9/25/21/ 3/ 1
      Method 4          25/10/30/21/ 3/ 1   <- the mon that appeared

SPEED 21 against a floor of 20, passed. Method 4 is the placement `mon-seek-both` never builds a word
for, so the derivation has been exercised on hardware by the very method it covers indirectly.

Across five scripted encounters the methods were 1, 1, 2, 1, 4, two in five carry a stray draw, on a
path that had looked clean.

## Where a hunt writes its report

`asm/field/mon-seek-log.s` (288 bytes, `--gift rng-mon-hunt-log`, flag id 1002) writes
`{marker, start, found, iterations, cap}` to `gSaveBlock1Ptr + 0x348C`, `u8 unused_348C[400]`
[include/global.h]. Two things had to be true before pointing native code at the save, and both were
checked rather than assumed:

- All 400 bytes read back as zero off this console before anything was written there, so the decomp's
  name for the block is true of the build the Switch runs. That dump was sized to 400 so it stopped one
  byte short of `ramScript` at 0x361C: a region that changes between the CRC frame and the send frame
  kills the link, and the RAM script is written during a session.
- It is outside `ramScript`, so `CalculateRamScriptChecksum` is untouched and the binding survives.
  The player can talk again and the log is simply overwritten.

It is in the save, so it survives the battle (`MoveSaveBlocks_ResetHeap` copies the blocks rather than
abandoning them) and reaches flash when the player saves. Read it back with

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x348C --dump-size 32

and `native_script.decode_hunt_log`. A miss is legible too: an exhausted search writes `found` 0 with the
marker present, which until then was indistinguishable from a stub that never ran.

The cost of an iteration, measured rather than modelled, from the first log read back:

| | |
|---|---|
| iterations | 603,745 |
| `lcg.distance(start, found)` | 603,745, difference 0 |
| instructions (15 each) | 9,056,175 |
| model at 3 cycles/instruction | 1.62 s |
| observed by the player | 2-3 s |
| implied | 3.7-5.6 cycles/instruction |

The distance check is worth stating on its own: the console's own counter and a discrete log over the LCG
computed here agree to the iteration, from opposite ends.

`CYCLES_PER_INSTRUCTION_FROM_EWRAM = 3` therefore looks low, consistent with two other runs pausing
longer than predicted. It is left at 3: the instruction count is exact but the other side of the division
is a person with a stopwatch, and a single search is exponentially distributed, so two samples above the
mean settle nothing. The freeze ceiling errs in the safe direction either way, a real cost above the
estimate means a search is refused sooner than it needs to be, never later.

## LeafGreen

The stubs need no porting. Every literal they use, `gRngValue`, `gSaveBlock1Ptr`, `gSaveBlock2Ptr`, the
LCG pair, is a link-time IWRAM word or a constant, all measured identical on LeafGreen, and `TID ^ SID`
is read off the console at run time.

What was missing was somewhere to put a RAM script, because the player has to talk to a map object. The
binding went on Mewtwo's own object in Cerulean Cave B1F (group 1, map 74, object 3), with
`setwildbattle` set to species 150 at level 70. `GetRamScript` replaces the object's script outright, so
Mewtwo's own script did not run, the battle started immediately, and the Mewtwo that appeared was
shiny. See [LeafGreen](frlg_leafgreen.md).
