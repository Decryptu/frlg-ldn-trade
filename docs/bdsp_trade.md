---
title: The Union Room trade
parent: Brilliant Diamond and Shining Pearl
nav_order: 3
---

# The BDSP trade

A retail Shining Pearl has opened its trade screen for a character pokeldn invented, sent its own
trainer record and one of its Pokemon, accepted a Pokemon pokeldn assembled, and written its save.

Getting to the trade screen — the emote, the approach and the greeting — is on
[The game protocol](bdsp_protocol.md).

## The message sequence

    NetDataTransitionData{transitionType: 18}     entering the trade
    NetDataTradeTranerData        32 B            who they are
    NetTradePokeData             328 B            the Pokemon
    NetDataTradePokeCheckOkData    1 B, value 1   "yours is fine"
    NetDataTradeReadyOkData        2 B            the last message before the exchange

Each is answered with one of the client's own. `NetDataTradePokeCheckOkData` is the console reporting
that it looked at a Pokemon the client built and found it acceptable.

## The trade state machine

`UnionTradeManager.currentState` is
`TradeFlowState {NONE 0, SELECT_WINDOW 1, SECURIY_TRADE 2, PLAY_DEMO 3, END 4}`, the field at +0x88
that every handler reads:

    UnionTradeManager$$RecivePokeData          0x1dd2800   currentState == SELECT_WINDOW only
    UnionTradeManager$$SetTargetTranerParam    0x1dd2130   TargetTranerParam{uint id, string name}
    UnionTradeManager$$ReciveTradeReadyOkData  0x1dd2a70   routed on the same field

A Pokemon is taken only in SELECT_WINDOW, stored as `tradeSelectModel.targetPokemonParam` with
`isRecivePokeParam` set. A `NetDataTradeReadyOkData` (0x21) is routed in SELECT_WINDOW to
`TradeSelectPokeModel$$ReciveReadyOk`, in SECURIY_TRADE to `TradeSecurityController$$ReciveState`
(creating the controller if it is null), and dropped anywhere else.

`ReciveReadyOk` is three instructions and they say which byte matters:

    ldrb w8, [x1, #0x11]      the message's SECOND byte, tradeState
    str  w8, [x0, #0x78]      TradeSelectPokeModel.targetTradeState
    ret                       isTradeOk is never read

The console then runs `UnionTradeManager.<WaitBoxWindowComplete>d__24`, whose whole condition is that
both trade states are `WAIT`:

    ldr w8, [x0, #0x74]   cmp w8, #2   b.ne  keep waiting     myTradeState
    ldr w8, [x0, #0x78]   cmp w8, #2   b.ne  keep waiting     targetTradeState
    str w8, [x20, #0x88]                                      currentState = SECURIY_TRADE
    bl  TradeSelectPokeModel$$Clear
    ... NetDataTradeReadyOkData$$.ctor; strb wzr, [x19, #0x11]; SendReliableData

`myTradeState` is set to `WAIT` by the player's own `MyReadyOk`. `targetTradeState` has exactly one
source in the whole game, and it is the peer's 0x21. **The console cannot leave SELECT_WINDOW on its
own**: it is parked waiting for one byte, and that byte moves it into the security phase.

## The security phase

Past that gate the flow is `TradeSecurityController` → `CreateTradeStateModel` → `TradeStateModel`,
and `TradeStateModel` owns the save. Its own state enum puts the save after the handshake:

    TradeStateModel.TradeState
    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

`TradeStateModel$$InitState` calls `PlayerSave` in its first instruction after the prologue.
`WriteSaveData` tail-calls `ReplacePoke`; neither has a direct caller, because the state handlers are
registered as delegates rather than branched to. `FirstSave` arms the disconnect penalty —
`UnionWork$$SetPenartyCounter(30)` — before it writes.

**The security phase's Pokemon message is a trigger, not a payload.**
`UnionRoomManager$$RecivePokeData` drops the decoded Pokemon when the manager is in SECURIY_TRADE and
calls `SetSecurityTradeParam()` with no arguments, which feeds `manager.targetPokemonParam` (+0x48,
set when the player confirms on the full-screen view) into the security controller. If the player has
not confirmed, the field is null and WAIT_POKE never ends whatever is sent.

**`BoxWindow.NetTradePhase.WaitSave` is not a save.** The phase enum reads
`None, WaitSave, PlayerSelecting, ...` and `ToNextPhase(0)` walks it by increment, so a console at the
box picker has passed through `WaitSave` — but the coroutine that phase runs,
`BoxWindow.<WaitTradeSave>d__203$$MoveNext`, reads `FieldCommonParam[0xEB]`, multiplies it by 0.001f
and counts it down against `Time.deltaTime`. It is a timed on-screen wait and writes nothing.

**Send one message per reliable sequence id.** `their_ack_id` only moves when the console
acknowledges, so several messages under one sequence id make all but the first look like retransmits
and be discarded. `bdsp_connect` keeps its own counter.

## The completed trade

Walked in order, six states in 630 ms:

    t=79.41  their READY-OK {isTradeOk 0, tradeState 2}  ->  OUR READY-OK
    t=79.82  INIT          ->  WAIT
    t=80.03  WAIT          ->  WAIT
    t=80.05  SEND_POKE     ->  SEND_POKE, and our Pokemon
    t=80.24  WAIT_POKE     ->  WAIT_POKE
    t=80.44  SEND_READYOK  ->  SEND_READYOK
    t=80.45  WAIT_READYOK  ->  SEND_READYOK
    t=109.31 NetDataReturnSelectData

**The 29 seconds between WAIT_READYOK and that last message are the trade, and nothing is asked of
the peer in them.** The console sends fifteen game messages across that window and every one is
`NetCharacterStateData`; START_WRITE_SAVE, WRITEING_SAVE, the animation and `ReplacePoke` are entirely
console-side. What a host must do there is not leave: a station that drops in this window drops the
console between `FirstSave` and `SecondSave`, which is exactly the state the penalty punishes.

Leaving WAIT_READYOK needs a message to arrive inside a window the console opens on its own clock
(`waitRndTime` counts down first), so nothing sent in reply to something else is guaranteed to land in
it. The once-a-second repeat of the client's own state is what covers it; that the repeat is what
tripped it is inferred rather than measured. The window was 28.9 s and 28.3 s in two completed trades.

`NetDataReturnSelectData` (id 69) appears only after a completed trade and is repeated once a second
until the peer's station leaves:

    data_id 69 (0x45)   payload 45 00 01 00   {'isReturnSelect': 0}

the same `<id> 00 01 <value>` shape as the check-ok. Nothing builds an answer.

## The Pokemon

`NetTradePokeData` carries **328 bytes**, which is Gen 8 `SIZE_STORED` exactly: an ordinary encrypted
PB8. The format is the Gen 6+ one unchanged — an LCG seeded with the encryption constant XORs every
16-bit word from 0x08, and the four 80-byte blocks are permuted by `(EC >> 13) & 31`. The full format,
including the two ways it is easy to misread, is on [the Sword/Shield page](swsh_protocol.md#the-pk8);
`pokeldn/gen8.py` is the shared implementation and `pokeldn/bdsp/pokemon.py` the PB8 view.

The checksum sits in the clear at 0x06 and sums the *decrypted* body, so a Pokemon the client
assembles verifies itself by decoding it back before it is sent. It cannot catch a wrong **block
order**: permuting whole 80-byte blocks does not change a sum of 16-bit words.

`NetDataTradeTranerData` has no generated layout — its C# struct holds a string — so it is read off
the wire, and the reading checks itself: the trainer and secret ids in the clear at 0x1a and 0x1c are
the same pair carried inside the encrypted Pokemon of the same trade.

    0x00  name, 8 UTF-16LE code units      0x18  u16, varies between sessions
    0x10  u32, unidentified                0x1a  trainer id
    0x14  u32, unidentified                0x1c  secret id

**What is offered is a real Pokemon with named fields changed**, not one built from nothing. Those 328
bytes hold far more than the dozen identified fields — met data, ribbons, handler records, the
language byte — and none of it is zero on a console's own. `pokemon.build_from` rewrites the fields it
is given and re-encrypts.

## What the console does to a received Pokemon

### When the receiver is the Pokemon's original trainer

Two bytes differ across a round trip of 328:

    0x08F   14 -> 94    IV32 bit 31, IsNicknamed: clear -> SET
    0x007   2b -> ab    the checksum at 0x06, following that change

The console set `IsNicknamed` itself; the name string is untouched. Everything else survives byte for
byte — not the handler, not friendship, not the met date or location, not the moves or PP.

### When the receiver is not the original trainer

Eleven bytes change:

    0x0A8..0x0B2   00 -> 47 75 72 76 61 6e     HandlingTrainerName, UTF-16LE
    0x0C3          00 -> 03                    HandlingTrainerLanguage, French
    0x0C4          00 -> 01                    CurrentHandler
    0x0C8          00 -> 32                    HandlingTrainerFriendship, 50
    0x006..0x007   the checksum, following them

The game writes a handler record only when the receiver is not the OT, and `ot_name` itself is never
touched.

**0xC6 stayed zero.** PKHeX carries `HandlingTrainerID` there with a literal `// unused?` comment. The
console wrote the handler's name, language, flag and friendship and left 0xC6 alone, so in BDSP it is
unused.

**`IsUntraded` is a field rather than an inference.** PKHeX defines it as `Data[0xA8] == 0`, an empty
handler name, and a traded Pokemon crosses that line: `is_untraded` true on the way out, false on the
way back.

### Duplicate detection

A Pokemon built from a capture of the same console's own Pokemon carries the same PID as one already
in that save's boxes. After several such trades the game refused to trade it at all:
*"Un probleme avec votre Pokemon rend tout echange impossible."*

`opendpr` names the machinery — `PokeDupeChecker` with `CheckDuplicate`,
`IsDuplicatedPokemonParam(pp0, List<PokemonParam>)`, `UpdateIllegalFlagAll` and
`IsLocalKoukanPokemonParam` (*koukan* = trade), a check aimed specifically at locally-traded Pokemon.
Every body is stubbed, and `PokeDupeChecker` is a 1.3.0 addition absent from the base-game dump, so
there is no code to read.

From the names and one observation: a locally traded Pokemon that duplicates one the save already
holds gets an illegal flag, and a flagged Pokemon cannot be traded. It is not a permanent loss — the
player released it, and `ClearIllegalFlagAll` exists.

**Never build an offer from a capture of the same console's own Pokemon without changing the PID.**

## The disconnect penalty

Dropping out mid-trade earns *"vous ne pouvez pas faire d'echange en reseau pour le moment"*, and the
console then refuses to advertise at all — a run against it sees `their advertising state seen 0` and
nothing else. Three methods hold all of it:

    TradeStateModel$$FirstSave    0x1cd4fc0   SetPenartyCounter(30); SetPenartyTime(now)
    TradeStateModel$$SecondSave   0x1cd5030   SetPenartyCounter(0)
    UnionFrontDeskStateController$$CheckPenarty  0x1fcc400   counter >= 1 AND not CheckDateTime()

The penalty is armed by the first save and cleared by the second, so a trade that completes clears it
on its own. It also settles a question no screen can answer: a penalty means `FirstSave` ran, which
means the console really did write.

**`UnionWork$$CheckDateTime` [0x1dd3e30] is not a clock.** It takes `DateTime.Now` and adds the
fields together with no weighting:

    w8 = Year + Month + Day + Hour + Minute + Second
    cset w0, mi            ... on  (stored + 30.0) < w8

`SetPenartyTime` [0x1dd32d0] stores the same sum, so the two are in the same units — and that sum is
**not monotonic**. It rises by 1 a second, then falls by 58 when the minute wraps and again when the
hour does: armed at 18:45:20 it is 2125, and at 19:20:00 it is 2081, lower than when it started. Only
the Day field carries forward reliably, at +1 a day. If the penalty is armed at a moment whose
Hour+Minute+Second is already high, no later time that day can beat `stored + 30`, and the wait runs
to the next day or beyond — which is where the 24 hours players report comes from. There is no
duration in the code anywhere; it is this arithmetic.

A non-monotonic counter has no typical wait. Two readings of this function were stated here as fact
and were wrong — "the seconds carry it, so about 30 minutes" (the minute wrap considered and the hour
wrap not) and "+31 in one field, since the comparison is strict" — and a player sat through the first.
Work the worst case of every field that can fall: `Hour+Minute+Second` spans 0..141, so a stable gain
has to beat `30 + 141`.

**Never propose changing the console's clock or any system setting to clear an in-game gate.** Moving
the clock forward does clear this counter, and BDSP detects the change and locks time-based features
for a day. A console set forward by 31 years was still refused, which is the same arithmetic caught a
second time. Moving the clock back restores the penalty, because only `SecondSave` zeroes the counter.
