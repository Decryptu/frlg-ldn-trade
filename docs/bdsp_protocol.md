---
title: The game protocol
parent: Brilliant Diamond and Shining Pearl
nav_order: 2
---

# BDSP's own protocol, and controlling a character

Inside the Pia payloads BDSP runs a typed protocol of its own. It does not have to be guessed:
`TeamLumi/opendpr` is a decompiled C# recreation of the game, and `Dpr.NetworkUtils.NetDataParser`
lists every message it speaks. Each is an `ANetData<T>` with a one-byte `DataID`, and each `T` is a
plain struct.

## Framing

    0x0  1  data id
    0x1  2  payload length, BIG-endian
    0x3  .  the struct, little-endian, as C# lays it out

**The layout is packed.** `JoinData` is `byte, byte, byte, short, Vector3`: seventeen bytes packed,
twenty with C#'s default alignment, because an aligned `short` would sit at offset 4 rather than 3.
The console's own message is seventeen bytes and its length field says `0x0011`. Every payload in
every capture agrees with the packed reading.

`NetDataParser` registers **65** messages and `pokeldn/bdsp/netdata.py` holds all of them, generated
from an `opendpr` checkout by `scripts/gen_bdsp_netdata.py`. 53 have a layout the source decides; the
other twelve carry a C# string, an array or a list, are listed in `netdata.OPAQUE`, and have no
layout, because the source does not decide one.

Three of the twelve have a layout anyway, measured from the wire and named in `room.MEASURED`, and
they are the only three of the twelve that any capture holds. What decides them is that a payload is
the **marshalled** struct: `ANetData<T>.ConvertStructToBytes` [main.bin 0x27bb0e0] goes through
`Marshal.SizeOf`, `Marshal.AllocHGlobal` and `Marshal.StructureToPtr`, so a string and an array
become fixed-size fields rather than references.

    0x02  NetPosData             72 B   twelve PosData, no count
    0x13  NetTradePokeData      328 B   one encrypted PB8 at stored size, no length prefix
    0x24  NetDataTradeTranerData 32 B   a 26-byte name, then uint, byte, byte

The marshaller does not clear what it allocates, so a fixed field carries heap residue past the
value it holds — ten bytes of it in `NetDataTradeTranerData`, on
[the trading page](bdsp_trade.md).

The ids are nibble-grouped — 0x01 to 0x09, 0x10 to 0x19, 0x20 to 0x29 and so on, no low nibble ever
reaching 0xA — so a gap in the numbering is the grouping rather than a missing message.

## What has been on the air

Four of the 65 have appeared in a capture. The receiver drops looped-back broadcasts before
recording, so all of these are the console talking:

| id | class | reliable | unreliable | size | runs |
|---|---|---|---|---|---|
| 0x01 | `NetJoinData` | 2070 | 0 | 17 | 19 |
| 0x02 | `NetPosData` | 0 | 60 | 72 | 5 |
| 0x12 | `NetRequestData` | 4333 | 55 | 1 | 19 |
| 0x23 | `NetDataIsMatchWaitData` | 229 | 0 | 1 | 13 |

Every payload in the archive is a well-formed game message declaring a length that exactly accounts
for its bytes, over six thousand messages and nineteen runs.

`NetPosData` shows what a capture settles that the source cannot: its struct is an array, so it is one
of the twelve with no decidable layout, and yet 72 bytes is 12 points of 6 and nothing else divides.

## The messages the console repeats

**`NetJoinData`** is a player's arrival — the whole of `JoinData` and nothing else:

| offset | size | field |
|---|---|---|
| 0x00 | 1 | `avatarId`, 8 in every capture |
| 0x01 | 1 | `colorId`, 0 |
| 0x02 | 1 | `cassetVersion`, 0x31 |
| 0x03 | 2 | `InitRotY`, the facing in **degrees**, little-endian and unaligned |
| 0x05 | 12 | `InitPos`, three little-endian floats: x, y, z |

Four captures of four different places on the Union Room floor gave angles of 0, 90, 90 and 225 —
every one a multiple of 45, which is what an eight-direction facing is. `y` is 0.0 in three of them
and 1.5e-08 in the fourth, so it is a height on a flat room rather than a constant.

**`NetRequestData`** is one byte, `RequestDataID`, and names the message it wants;
`OpcManager._RequestNetDataCallback` is an `Action<byte>`. **`NetDataIsMatchWaitData`** is the console
answering its own request: `{isMatchWait = 0}`, "I am not waiting to be matched".

The console asks for two different things:

| asked for | times | in which runs |
|---|---|---|
| `NetDataIsMatchWaitData` (0x23) | 4333 | all nineteen |
| `NetCharacterStateData` (0x04) | 55 | four runs |

Those four are exactly the runs where an avatar appeared on the console's screen. Every run that sent
game messages and drew nothing asked for 0x04 zero times, across 265 sends, and in all four positive
runs the first 0x04 arrives after the client's first send. **When the game creates a character from a
join, it asks the station that sent it for that character's state**, so a request for 0x04 in the
capture is a second signal that a character exists — the screen having been the only trustworthy one.
`bin/bdsp_connect.py` prints it as a verdict.

The match-wait request stops being asked at t = 9.4 in every run that acknowledges the reliable
window, answered or not; the run that did not acknowledge it was asked 487 times in 75 seconds. It is
the acknowledgement that stops the asking.

**The stream decides the reply's stream.** All 4333 requests for `NetDataIsMatchWaitData` arrived on
the reliable protocol and all 55 for `NetCharacterStateData` on the unreliable one, with no crossover
in nineteen runs, and each is where the console puts its own answer.

The unreliable stream carries three messages and nothing else:

| bytes | times | message |
|---|---|---|
| `04 0002 00 00` | 853 | `NetCharacterStateData{state: NONE, isRecruiment: 0}`, every two seconds |
| `12 0001 04` | 55 | `NetRequestData` — "send me your `NetCharacterStateData`" |
| `02 0048 <72 B>` | 60 | `NetPosData`, twelve points, while the console's avatar walks |

`room.build_state()` produces the exact five bytes the console broadcasts and
`room.build_match_wait(False)` the exact four it answers itself with, so neither reply invents
anything.

## Sending messages the game acts on

**The reliable sequence id is shared with the console's own sends, and anything below the number its
acknowledgement names is discarded in silence.** One run's ack sat at 13, twenty messages went out
numbered 1 to 20, and exactly the eight from 13 up became avatars. Read the id fresh immediately
before each send.

**A join the transport acknowledges is not a join the game acts on.** Four runs sent exactly one join
each and all four were acknowledged on the first try; one produced a character and three produced
nothing. Fifteen joins in one run produced two characters, so a single join is roughly a one-in-eight
shot and a comparison cannot rest on one. `--room-pattern fixed` bursts them.

**One avatar appears per join message**, because `UnionOpcManager` calls `CreateCharacter(joinData)`
on each one. Forty joins are forty arrivals.

Avatars created this way **survive the scene**: the player walked out of the Union Room, down to the
Poke Center floor and into a shop, and the whole crowd came along, through the walls. Only restarting
the game cleared them. A remote player created without a session behind it is never cleaned up. A
character that has been *moved* is cleaned up when the station that moved it leaves the mesh.

## The character record

`OpcManager.CharaData` is
`{int stationIndex, string assetName, int colorId, int avatarId, int sexId, int cassetVersion}` and
`RemoveCharacter(int stationIndex)` takes the same key, so a character is keyed by the station it came
from.

### The model

`OpcManager.CreateCharaData(ANetData<JoinData>)` builds the record out of the join message, and
`avatarId` picks who appears:

    NetJoinData.avatarId  ->  CreateCharaData  ->  CharaData.avatarId
                          ->  UnionCharacterTable.SheetSheet1{ID, AssetName}
                          ->  OpLoadCharacter("persons/field/" + assetName)

`GetSexId(id)` and `GetNpcColorId(avatarId)` read the same value. `avatarId = 8` is a girl and 0 a boy
in a blue cap, with the sex changed as the binary predicts. `bin/bdsp_connect.py --join-avatar N`.

`NetDataTranerCardData` (0x05) is 75 blittable bytes whose first fields are `fashionId`, `bodyType`
and `genderid`, which reads like appearance and is not: `UnionOpcManager.CreateTranerCard()` builds
the trainer-card UI. Sending one is acknowledged and changes nothing on screen.

### The state byte

`StateData` is `{byte state, byte isRecruiment}`, and `state` is an `OpcState.OnlineState`:

| value | name | value | name |
|---|---|---|---|
| 0 | `NONE` | 5 | `RECRUITMENT_RECORD` |
| 1 | `DIG_FOSILL` | 6 | `RECRUITMENT_GREETINGS` |
| 2 | `SECRETBASE_ACTION` | 7 | `RECRUITMENT_BALL_DECORATION` |
| 3 | `RECRUITMENT_BATTLE` | 8 | `COMMUNICATE` |
| 4 | `RECRUITMENT_TRADE` | | |

`OpcController.ShowEmoticon(OnlineState)` and `GetEmoticonType(state)` read it, and the
`RECRUITMENT_*` values raise the speech bubble over a player advertising what they want. Answering
the console's standing request with `StateData{RECRUITMENT_TRADE, 1}` puts a trade bubble on a retail
console's screen.

Two earlier runs answered the same request with `StateData{NONE, 0}` and nothing happened. The
message, the stream and the bytes were all correct and the payload meant "I am doing nothing": a
negative result measured with a no-op payload is not a negative result.

### Walking

Over 80 of the console's own `NetPosData`: one message every 0.410 s spanning 0.935 units, which is
**2.28 units per second**. `room.POS_PERIOD` and `room.POS_STRIDE` are those numbers;
`--room-walk-stride` and `--room-walk-period` override them. Sending 0.1 units every 0.35 s — an
eighth of that — renders as a stutter: twelve points crossing a tiny distance, then a pause.

A walk has to be bounded. Sixty messages at the console's own speed is 55.8 units and crosses the
whole room: the character hits a wall, is pushed back by the game's own collision, keeps its facing
at the angle sent while the position moves, and leaves through the far wall. `--room-walk-steps 8`
stops inside the room. Two properties fall out: the game applies collision to a remote character's
movement, and it takes `rot_y` literally rather than deriving facing from the direction of travel.
The player has no collision against a remote character.

`PosData` is `{ushort posX, ushort posZ, short rotY}` with the game's own conversion
`pos = (-posX * 0.05, posZ * 0.05)` — a twentieth of a unit, with **x negated**. A captured trail
decodes to the same place its join message named.

## Being talked to

An emote **locks a player in place waiting to be interacted with**, so a console showing a trade
emote cannot start anything: someone has to walk up to it. The console broadcasts its own state, so
the moment the emote goes up is visible on the wire:

    NetCharacterStateData{state: 4, isRecruiment: 1}     the trade emote, up
    NetCharacterStateData{state: 0, isRecruiment: 0}     and down again

`isRecruiment` is the flag to gate on rather than "state is non-zero": state 18 is a console already
inside a trade, and approaching that is refused.

The approach is `NetDataTalkReserveData` (0x63), `63 00 01 00`, byte-for-byte what the console sends
when its own player walks up to someone. `bin/bdsp_connect.py --initiate-talk` sends it; it was
answered in 40 ms.

The exchange, with the client approaching:

    t=37.47  us  ->  64 0003 00 01 04   NetDataTalkReserveResultData{IsCanTalk, IsRecruitment, emoticonStateType}
    t=37.67  con ->  06 0005 00 01000000  NetDataTalkData{talkOpcSexId: 0, talkState: GREETING}
    t=80.68  con ->  10 0002 01 04      NetDataTalkCancelEndData{IsRecruitment: 1, emoticonStateType: 4}

**The talk is a request/response and the console blocks on the answer.** Unanswered, the player's own
character freezes until the game is rebooted. Answered with `NetDataTalkReserveResultData` (0x64), the
game runs its whole greeting: a greeting line, a name and an offer to trade, ending in "one second!"
while it waits. The player can leave that with B.

**`IsCanTalk` reads backwards from its name: 0 keeps the conversation alive, 1 makes the character
decline.** Four runs, one variable each:

| `IsCanTalk` | what followed | what the screen did |
|---|---|---|
| 0 | nothing | the greeting runs and parks on "one second!" |
| 1 | nothing | "sorry, I have other plans" and the chat closes |
| 1 | `NetDataSelectData{0}` | the same refusal |
| 1 | `NetDataSelectData{1}` | the same refusal |

The two runs that swept the select index were therefore refusing before the index could matter.

**A parked conversation is not reliably escapable.** B released the player in one run and did nothing
in another; killing the run — dropping the station — is the lever to try first and a reboot is the
fallback. Say so before a run that parks the talk.

### talkState, and the value that crashes the game

`TalkState` is `{CHECK = 0, GREETING = 1, NONE = 2}`, and the console is parked in `GREETING` waiting
to be advanced. `UnionStateController$$SwitchSpokenStateMine` is the handler and its whole shape is
one branch:

    0x1fd5e6c  cbz  w21, 0x1fd5e84    talkState == CHECK -> below
    0x1fd5e80  b    0x1fd85e0         anything else -> StartOpenGreetingMsgWindow

    0x1fd5e84  ldr  x0, [x0, #0x10]   systemController->msgWindow
    0x1fd5e88  cbz  x0, 0x1fd5f00     ... and when it is NULL:
    0x1fd5f00  mov  x19, xzr            x19 = 0
    0x1fd5ec0  ldr  x20, [x19, #0x10]   dereferences it. No guard anywhere.

CHECK is only meaningful to a console that already has a message window open. A player standing with
an emote up has none, so sending CHECK takes the game down — twice, before the handler was read.
GREETING takes the branch that opens the window. `pokeldn/bdsp/room.py` refuses to send CHECK at all.

**A state value read out of a sender is not safe to send until the receiver's handler has been
read.** CHECK really is what the initiator sends, in a state the console was not in.

The messages that advance a parked greeting are `NetDataSelectData{index}` (0x08) and
`NetDataTransitionData{transitionType, isRecruitment}` (0x07). Both are sent by the game as tail
calls, so a BL-only caller scan reports them as never sent; see
[finding callers](switch_re.md#finding-callers).
