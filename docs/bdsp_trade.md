---
title: The Union Room trade
parent: Brilliant Diamond and Shining Pearl
nav_order: 3
---

# The BDSP trade

A retail Shining Pearl has opened its trade screen for a character pokeldn invented, sent its own
trainer record and one of its Pokemon, accepted a Pokemon pokeldn assembled, and written its save.

Getting to the trade screen (the emote, the approach and the greeting) is on
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

`ReciveReadyOk` is three instructions:

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
source in the game, the peer's 0x21. The console cannot leave SELECT_WINDOW on its own; that byte
moves it into the security phase.

## The security phase

Past that gate the flow is `TradeSecurityController` -> `CreateTradeStateModel` -> `TradeStateModel`,
which owns the save. Its state enum puts the save after the handshake:

    TradeStateModel.TradeState
    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

`TradeStateModel$$InitState` calls `PlayerSave` in its first instruction after the prologue.
`WriteSaveData` tail-calls `ReplacePoke`; neither has a direct caller (the state handlers are
registered as delegates). `FirstSave` arms the disconnect penalty, `UnionWork$$SetPenartyCounter(30)`,
before it writes.

The security phase's Pokemon message is a trigger. `UnionRoomManager$$RecivePokeData` drops the
decoded Pokemon when the manager is in SECURIY_TRADE and calls `SetSecurityTradeParam()` with no
arguments, which feeds `manager.targetPokemonParam` (+0x48, set when the player confirms on the
full-screen view) into the security controller. If the player has not confirmed, the field is null
and WAIT_POKE never ends whatever is sent.

`BoxWindow.NetTradePhase.WaitSave` writes nothing. The phase enum reads `None, WaitSave,
PlayerSelecting, ...` and `ToNextPhase(0)` walks it by increment; the coroutine that phase runs,
`BoxWindow.<WaitTradeSave>d__203$$MoveNext`, reads `FieldCommonParam[0xEB]`, multiplies it by 0.001f
and counts it down against `Time.deltaTime`: a timed on-screen wait.

Send one message per reliable sequence id. `their_ack_id` only moves when the console acknowledges,
so several messages under one sequence id make all but the first look like retransmits and be
discarded. `bdsp_connect` keeps its own counter.

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

The 29 seconds between WAIT_READYOK and that last message are the trade; nothing is asked of the
peer in them. The console sends fifteen game messages across that window, every one
`NetCharacterStateData`; START_WRITE_SAVE, WRITEING_SAVE, the animation and `ReplacePoke` are
console-side. The station must not leave: a drop in this window lands the console between
`FirstSave` and `SecondSave`, the state the penalty punishes.

Leaving WAIT_READYOK needs a message to arrive inside a window the console opens on its own clock
(`waitRndTime` counts down first). The once-a-second repeat of the client's own state covers it;
that the repeat is what trips it is inferred, not measured. The window was 28.9 s and 28.3 s in two
completed trades.

`NetDataReturnSelectData` (id 69) appears only after a completed trade and is repeated once a second
until the peer's station leaves:

    data_id 69 (0x45)   payload 45 00 01 00   {'isReturnSelect': 0}

the same `<id> 00 01 <value>` shape as the check-ok. Nothing builds an answer.

## The Pokemon

`NetTradePokeData` carries 328 bytes, Gen 8 `SIZE_STORED`: an encrypted PB8. The format is the Gen
6+ one: an LCG seeded with the encryption constant XORs every 16-bit word from 0x08, and the four
80-byte blocks are permuted by `(EC >> 13) & 31`. The full format is on
[the Sword/Shield page](swsh_protocol.md#the-pk8); `pokeldn/gen8.py` is the shared implementation
and `pokeldn/bdsp/pokemon.py` the PB8 view.

The checksum sits in the clear at 0x06 and sums the decrypted body, so a Pokemon the client
assembles verifies itself by decoding it back before it is sent. It cannot catch a wrong block order:
permuting whole 80-byte blocks does not change a sum of 16-bit words.

`NetDataTradeTranerData` is the marshalled C# struct, in declaration order and packed.
`ANetData<T>.ConvertStructToBytes` [main.bin 0x27bb0e0] sizes it with `Marshal.SizeOf`, allocates
with `Marshal.AllocHGlobal` and writes it with `Marshal.StructureToPtr`: `string tranerName; uint
tranerId; byte cassetVersion; byte langId`, 26 + 4 + 1 + 1 = 32 bytes.

    0x00  26  tranerName, UTF-16LE, NUL-terminated
    0x1a   4  tranerId, the full 32-bit id, secret id in its high half
    0x1e   1  cassetVersion
    0x1f   1  langId

Check against the encrypted Pokemon of the same trade: 0x1a is 0x0FF0ADB2, that Pokemon's trainer
id 44466 and secret id 4080; 0x1e is 49, its `version`; 0x1f is 3, its `language`.

The ten bytes between the name's terminator and the id are heap residue: `AllocHGlobal` does not
clear its block and marshalling a string into a fixed field writes the characters and one
terminator. The word at 0x14 was 107540 in nine runs, 44 in one and 60 in another while every
declared field held still. `room.build_trade_traner` carries the console's own residue, so the
record it builds is byte-identical to the console's.

The offer is a real Pokemon with named fields changed. The 328 bytes hold met data, ribbons, handler
records and the language byte, none of it zero on a console's own. `pokemon.build_from` rewrites the
fields it is given and re-encrypts.

## What the console does to a received Pokemon

### When the receiver is the Pokemon's original trainer

Two bytes differ across a round trip of 328:

    0x08F   14 -> 94    IV32 bit 31, IsNicknamed: clear -> SET
    0x007   2b -> ab    the checksum at 0x06, following that change

The console set `IsNicknamed` itself; the name string is untouched. Everything else (handler,
friendship, met date and location, moves, PP) survives byte for byte.

### When the receiver is not the original trainer

Eleven bytes change:

    0x0A8..0x0B2   00 -> 47 75 72 76 61 6e     HandlingTrainerName, UTF-16LE
    0x0C3          00 -> 03                    HandlingTrainerLanguage, French
    0x0C4          00 -> 01                    CurrentHandler
    0x0C8          00 -> 32                    HandlingTrainerFriendship, 50
    0x006..0x007   the checksum, following them

The game writes a handler record only when the receiver is not the OT; `ot_name` is never touched.

0xC6 stayed zero. PKHeX carries `HandlingTrainerID` there with a `// unused?` comment; in BDSP it is
unused.

PKHeX defines `IsUntraded` as `Data[0xA8] == 0`, an empty handler name. A traded Pokemon crosses that
line: `is_untraded` true on the way out, false on the way back.

### Duplicate detection

A Pokemon built from a capture of the same console's own Pokemon carries the same PID as one already
in that save's boxes. After several such trades the game refused to trade it at all:
*"Un probleme avec votre Pokemon rend tout echange impossible."*

`opendpr` names the machinery: `PokeDupeChecker` with `CheckDuplicate`,
`IsDuplicatedPokemonParam(pp0, List<PokemonParam>)`, `UpdateIllegalFlagAll` and
`IsLocalKoukanPokemonParam` (*koukan* = trade). Every body is stubbed, and `PokeDupeChecker` is a
1.3.0 addition absent from the base-game dump.

A locally traded Pokemon that duplicates one the save already holds gets an illegal flag, and a
flagged Pokemon cannot be traded. The player can release it; `ClearIllegalFlagAll` exists.

Never build an offer from a capture of the same console's own Pokemon without changing the PID.

## The disconnect penalty

Dropping out mid-trade earns *"vous ne pouvez pas faire d'echange en reseau pour le moment"*, and the
console then refuses to advertise; a run against it sees `their advertising state seen 0`. Three
methods hold all of it:

    TradeStateModel$$FirstSave    0x1cd4fc0   SetPenartyCounter(30); SetPenartyTime(now)
    TradeStateModel$$SecondSave   0x1cd5030   SetPenartyCounter(0)
    UnionFrontDeskStateController$$CheckPenarty  0x1fcc400   counter >= 1 AND not CheckDateTime()

The penalty is armed by the first save and cleared by the second; a trade that completes clears it.
A penalty means `FirstSave` ran and the console wrote.

`UnionWork$$CheckDateTime` [0x1dd3e30] takes `DateTime.Now` and adds the fields together with no
weighting:

    w8 = Year + Month + Day + Hour + Minute + Second
    cset w0, mi            ... on  (stored + 30.0) < w8

`SetPenartyTime` [0x1dd32d0] stores the same sum. The sum is not monotonic: it rises by 1 a second,
then falls by 58 when the minute wraps and again when the hour does. Armed at 18:45:20 it is 2125;
at 19:20:00 it is 2081. Only the Day field carries forward, at +1 a day. If the penalty is armed at
a moment whose Hour+Minute+Second is already high, no later time that day beats `stored + 30`, and
the wait runs to the next day or beyond. There is no duration in the code.

A non-monotonic counter has no typical wait. `Hour+Minute+Second` spans 0..141, so a stable gain has
to beat `30 + 141`.

Never change the console's clock or any system setting to clear an in-game gate. Moving the clock
forward clears this counter, and BDSP detects the change and locks time-based features for a day. A
console set forward by 31 years was still refused (the same arithmetic). Moving the clock back
restores the penalty; only `SecondSave` zeroes the counter.
