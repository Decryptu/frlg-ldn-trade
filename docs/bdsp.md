---
title: Brilliant Diamond and Shining Pearl
nav_order: 4
has_children: true
---

# Brilliant Diamond and Shining Pearl

The first **native** Switch title this project has spoken to, and a different shape of problem from
FireRed/LeafGreen. There is no GBA ROM and no emulator in the middle: Pia is the game's own
transport, and above it sits Unity/IL2CPP game code written by ILCA.

## Where it stands

**Proven on retail hardware.** A Linux box associates with a Shining Pearl Union Room session, is
given a seat, decrypts every packet, completes the Local, Mesh Station and Mesh handshakes, is a
station in the console's mesh, answers its round-trip timer, and **talks to its reliable transport
in both directions** - the console acknowledges data we send it, and an acknowledgement from us
stops it retransmitting. Nothing but `prod.keys` and the title's LDN passphrase is needed to start.

**And the game itself is now readable.** All 65 messages BDSP speaks are named from its own source,
and every payload either stream has ever carried is a whole, well-framed one: the reliable stream
carries the console's arrival and a request addressed to us, and the unreliable stream carries its
character's state every two seconds, another request, and its position while it walks.

**And the game draws what we send it.** Messages of our own put avatars in the Union Room on a
retail console - four of them from four corners, then twenty in a line through the walls. They are
the default model with no name, no collision and no dialogue.

**A character we created has walked.** sp57 sent fifteen joins at one spot and then sixty
`NetPosData` messages: two avatars appeared and one of them moved across the room until it stopped
at a wall. Spawning and moving a player in a retail game's Union Room, from a Linux box, is done.

**And a join the transport accepts is not a join the game acts on.** Four runs sent exactly one
join each and all four were acknowledged on the first try; one produced a character and three
produced nothing. sp57 had measured the rate without anyone noticing - fifteen joins, two
characters - so a single join is roughly a one-in-eight shot, and a run built on one cannot support
a comparison. Burst them.

**How a message lands.** The reliable sequence id is shared with the console's OWN sends, and
anything below the number its acknowledgement names is discarded in silence. The proof is
arithmetic: one run's ack sat at 13, twenty messages went out numbered 1 to 20, and exactly the
eight from 13 up became avatars. Read the id fresh immediately before each send.

**How fast a player walks, measured off the console's own messages.** Over eighty of them, a
`NetPosData` arrives every 0.410 s and spans 0.935 units - 2.28 units a second. This project's walks
sent 0.1 units every 0.35 s, an eighth of that, which is the whole of what the screen kept showing
as a stutter: twelve points crossing a tiny distance, then a pause. Those two numbers are the
defaults now.

**A moved character belongs to the station that moved it.** It is cleaned up when that station
leaves the mesh, while the ones that never moved leak and stay until the game is restarted - seen
twice. What is **not** established is a timeout: session 47 recorded a moved character vanishing
seconds after the movement stopped, and two later runs in that same configuration kept theirs for
159 seconds. One observation, not reproduced.

**One avatar appears per message, because every message was a JOIN.** `UnionOpcManager` calls
`CreateCharacter(joinData)` on each one, so forty joins are forty arrivals and the game is behaving
correctly; the mistake was ours. What those avatars have no owner for, though, is real: they
**survive the scene**. The player walked out of the Union Room and down to the Poke Center floor, into
a shop, and the whole crowd came along, still through the walls. Only restarting the game cleared
them. A remote player created without a session behind it is never cleaned up.

**What an avatar is missing has a name now.** `OpcManager.CharaData` is
`{int stationIndex, string assetName, int colorId, int avatarId, int sexId, int cassetVersion}` and
`RemoveCharacter(int stationIndex)` takes the same key, so **a character is keyed by the station it
came from** - and a `JoinData` carries an appearance and a place but no name, which is why every
avatar we have spawned is the default model. The messages that would carry the rest are in the
table: `NetPlayerNameData` (0x42) is a nickname, a gender and a language, and
`NetDataTranerCardData` (0x05) is a fashion id, a body type and a whole trainer card, 75 bytes and
entirely blittable.

**Not yet done.** `NetPlayerNameData`'s framing - the twelve messages whose struct holds a string or
an array have no layout the source decides. And the **Session Protocol (0x94)**, which sits above
the reliable transport, has never carried a byte in any capture.

## The game's own protocol, above Pia

BDSP runs a typed protocol of its own inside the Pia payloads, and it does not have to be guessed:
`TeamLumi/opendpr` is a decompiled C# recreation of the game, and `Dpr.NetworkUtils.NetDataParser`
lists **every message the game speaks** - `NetJoinData`, `NetPosData`, `NetPlayerNameData`,
`NetEmotionData`, `NetDataTranerCardData`, `NetTradePokeData` and about forty more. Each is an
`ANetData<T>` with a one-byte `DataID`, and each `T` is a plain struct.

The framing fits every payload ever captured:

    0x0  1  data id
    0x1  2  payload length, BIG-endian
    0x3  .  the struct, little-endian, as C# lays it out

| seen | id | class | meaning |
|---|---|---|---|
| `01 0011 08 00 31 5a00 <x><y><z>` | 1 | `NetJoinData` | a player has joined, here |
| `02 0048 <12 x 6 bytes>` | 2 | `NetPosData` | where a player has been moving |
| `12 0001 23` | 0x12 | `NetRequestData` | "send me your data id 0x23" |
| `23 0001 00` | 0x23 | `NetDataIsMatchWaitData` | "I am not waiting to be matched" |

`NetDataParser` registers **65** of these and `pokeldn/bdsp/netdata.py` holds all of them, generated
from the checkout by `scripts/gen_bdsp_netdata.py` rather than typed. The ids are nibble-grouped -
0x01 to 0x09, 0x10 to 0x19, 0x20 to 0x29 and so on, no low nibble ever reaching 0xA - so a gap in
the numbering is the grouping and not a message the table is missing.

**The layout is PACKED, and the wire is what says so.** `JoinData` is `byte, byte, byte, short,
Vector3`: seventeen bytes packed, twenty with C#'s default alignment, because an aligned `short`
would sit at offset 4 rather than 3. The console's own message is seventeen, and its length field
says `0x0011`. Every payload in every capture agrees with the packed reading, so the whole table
decodes on it and 53 of the 65 messages have a layout that is decided rather than guessed.

The other twelve carry a C# string, an array or a list, and their size is **not** in the source.
`NetPlayerNameData` is one of them - `string nickName, byte genderid, byte languageId` - so the
message that would give an avatar a name is exactly the one whose framing still has to be measured.
`netdata.OPAQUE` names all twelve; writing a layout for one of them without measuring it is the
mistake this table exists to prevent.

`JoinData` is `byte avatarId, byte colorId, byte cassetVersion, short InitRotY, Vector3 InitPos`,
and a real console sends avatar 8, colour 0, casset 0x31. `PosData` is `ushort posX, ushort posZ,
short rotY` with the game's own conversion `pos = (-posX * 0.05, posZ * 0.05)` - a twentieth of a
unit, and **x negated**. A captured trail decodes to the same place its join message named, which is
what says the two are one player.

**Reading that beat guessing by a wide margin.** This project first called `NetJoinData`'s leading
bytes "a fixed head" and its rotation "an angle", and only the decompile showed that the six bytes
were three struct fields and a length - and, more to the point, that the twenty-byte message is a
JOIN and not a position update at all.

## What the room says

The twenty bytes the console repeats on the reliable protocol until they are acknowledged are its
own arrival - `NetJoinData`, the whole of `JoinData` and nothing else:

| offset | size | field |
|---|---|---|
| 0x00 | 1 | `avatarId`, 8 in every capture |
| 0x01 | 1 | `colorId`, 0 |
| 0x02 | 1 | `cassetVersion`, 0x31 |
| 0x03 | 2 | `InitRotY`, the facing in **degrees**, little-endian and unaligned |
| 0x05 | 12 | `InitPos`, three little-endian floats: x, y, z |

Four runs caught four different places on that floor, and the angle was 0, 90, 90 and 225 - every
one a multiple of 45, which is what an eight-direction facing is. `y` is 0.0 in three of them and
1.5e-08 in the fourth, so it is a height on a flat room and not a constant.

### The other two messages are a question and its own answer

Since the very first join the console has been repeating two four-byte messages, and reading them
against the table settles both at once. `12 0001 23` is `NetRequestData`, whose entire struct is
`byte RequestDataID` - and 0x23 is **itself a data id**. `OpcManager` holds the other half:
`_RequestNetDataCallback` is an `Action<byte>`, so a request names the message it wants. `23 0001 00`
is the console answering its own question: `NetDataIsMatchWaitData{isMatchWait = 0}`, "I am not
waiting to be matched".

**Counted over every capture this project holds, that request is by a long way the commonest thing
the console says.** Four of the 65 message types have ever been on the air, and the receiver drops
our own looped-back broadcasts before recording, so all of these are the console talking:

| id | class | reliable | unreliable | size | runs |
|---|---|---|---|---|---|
| 0x01 | `NetJoinData` | 2070 | 0 | 17 | 19 |
| 0x02 | `NetPosData` | 0 | 60 | 72 | 5 |
| 0x12 | `NetRequestData` | 4333 | 55 | 1 | 19 |
| 0x23 | `NetDataIsMatchWaitData` | 229 | 0 | 1 | 13 |

**Not one payload in the whole archive fails to be a well-formed game message** - every one declares
a length that exactly accounts for its bytes - which is the framing confirmed over six thousand-odd
messages and nineteen runs from a direction that is not the source. And `NetPosData` shows what a
capture can settle that source cannot: its struct is an array, so it is one of the twelve with no
decidable layout, and yet 72 bytes is 12 points of 6 and nothing else divides.

### The request that says the game made a character out of us

The console asks for two different things, and the second one is a measurement nobody was reading:

| asked for | times | in which runs |
|---|---|---|
| `NetDataIsMatchWaitData` (0x23) | 4333 | all nineteen |
| `NetCharacterStateData` (0x04) | 55 | sp47, sp48, sp53, sp57 - and no others |

Those four are **exactly** the runs where an avatar of ours appeared on the console's screen. Every
run that sent game messages and drew nothing asked for 0x04 zero times, across 265 sends, and in all
four positive runs the first 0x04 arrives after our first send. **When the game creates a character
from a join, it asks the station that sent it for that character's state** - and no run has ever
answered.

That closes a gap this project had written down as permanent. Ack ids move for the console's own
reasons, so every run judged on them was ambiguous and the screen was the only trustworthy signal;
a request for 0x04 is a second trustworthy signal, it is in the capture, and it separates four runs
from nine with no exceptions either way. `bin/bdsp_connect.py` prints it as a verdict, so a run is
readable without anyone watching the television.

`StateData` is `byte state, byte isRecruiment` - two blittable bytes - so the answer is buildable
today, and `room.answer()` already returns it. The `state` byte is an `OpcState.OnlineState`, 23
values from `NONE` to `_NULL`, and `OpcState.IsCanTalkState()` reads that same field - so the
avatars that "cannot be talked to" may simply be characters whose state has never been reported.
The neutral answer is `NONE`, which is what a character standing still is; the `RECRUITMENT_*`
values are what a player advertising itself for a battle or a trade sends.

**So one of the two messages the console has been repeating at us for every run of this project is a
question addressed to us, and nothing had ever answered it.**

### It was answered, and nothing happened - because the answer said nothing

**Read the correction below before this section.** The finding is real and the runs were clean; what
was wrong is the conclusion drawn from them. Both runs answered `StateData{NONE, 0}` - a character
reporting that it is doing nothing - so the probe measured a well-formed no-op. The `state` byte is
an enum, and the value that means something is not the one that was sent.

sp63 and sp64 are the same run with one variable moved - the same fifteen joins, the same fourteen
state requests at the same times, the same walk - and one answered nineteen requests while the other
answered none. **They came out identical.** Both drew avatars; both left the walked character
standing through 159 seconds of silence; in both, she went only when our station left the mesh.

The match-wait request behaves the same way. It stops being asked at t = 9.4 in every run that
acknowledges the reliable window, answered or not; the run that did **not** acknowledge it was asked
487 times in 75 seconds. It is the acknowledgement that stops the asking, not the answer.

So: the answers are accepted by the transport, land on the right stream with the right bytes, and
have no effect anything can see. Whether the game reads them at all is unknown. It is written down
here so the probe is not run a second time. Building the answer from
the table reproduces the console's own four bytes exactly, which is the check that the reading is
right before any run is spent on it. `bin/bdsp_connect.py --answer-requests` sends it; the counter
to read afterwards is whether the request keeps being asked.

### The unreliable stream is not a keepalive and a trail - it is three messages

Every one of the 968 unreliable payloads in the archive is a whole game message, and there are three
of them:

| bytes | times | message |
|---|---|---|
| `04 0002 00 00` | 853 | `NetCharacterStateData{state: NONE, isRecruiment: 0}`, every two seconds |
| `12 0001 04` | 55 | `NetRequestData` - "send me your `NetCharacterStateData`" |
| `02 0048 <72 B>` | 60 | `NetPosData`, twelve points, while the console's avatar walks |

The five-byte one was called a keepalive here for several sessions, and it is the console
broadcasting its own character's state. It was named before the message table existed.

**The stream decides the stream.** All 4333 requests for `NetDataIsMatchWaitData` arrived on the
reliable protocol and all 55 for `NetCharacterStateData` on the unreliable one, with no crossover in
nineteen runs - and each is where the console puts its own answer, so a reply goes back on the
protocol its request came in on.

Which makes the answer free of invention twice over: `room.build_state()` produces `04 0002 0000`,
the exact five bytes the console broadcasts 853 times, and `room.build_match_wait(False)` produces
the exact four the console answers itself with. Neither reply is anything the console has not
already said.

## The character is ours to choose, and the game will talk to her

Everything above stops at "the game draws a body and has no record to hang on it". That reading is
retired. There **is** a record, it is `OpcManager.CharaData`, we populate it, and once it says the
right thing the game runs its own Union Room dialogue against it.

### The model is a field in the join message

`OpcManager.CreateCharaData(ANetData<JoinData>)` builds a
`CharaData{stationIndex, assetName, colorId, avatarId, sexId}` out of the join we already send, and
`avatarId` is what picks who appears:

    NetJoinData.avatarId  ->  CreateCharaData  ->  CharaData.avatarId
                          ->  UnionCharacterTable.SheetSheet1{ID, AssetName}
                          ->  OpLoadCharacter("persons/field/" + assetName)

`GetSexId(id)` and `GetNpcColorId(avatarId)` read the same value. Every run this project had ever
done sent `avatarId = 8`, which is the whole reason every character it had ever created was the same
girl. sp69 sent `0` and a boy in a blue cap appeared, with the sex changed as the binary predicts.
`bin/bdsp_connect.py --join-avatar N`.

### The state byte is what makes a character approachable

`StateData.state` is `OpcState.OnlineState`:

| value | name | value | name |
|---|---|---|---|
| 0 | `NONE` | 5 | `RECRUITMENT_RECORD` |
| 1 | `DIG_FOSILL` | 6 | `RECRUITMENT_GREETINGS` |
| 2 | `SECRETBASE_ACTION` | 7 | `RECRUITMENT_BALL_DECORATION` |
| 3 | `RECRUITMENT_BATTLE` | 8 | `COMMUNICATE` |
| 4 | `RECRUITMENT_TRADE` | | |

`OpcController.ShowEmoticon(OnlineState)` and `GetEmoticonType(state)` read it, and the
`RECRUITMENT_*` values are what put the speech bubble over a Union Room player advertising what they
want. sp70 answered the console's standing request with `StateData{RECRUITMENT_TRADE, 1}` and the
character showed a trade bubble on a retail console.

**This is why the earlier probe read as a dead end.** sp63 and sp64 answered the same request with
`StateData{NONE, 0}` and nothing happened, and that was written up as "answering does nothing". The
message was right, the stream was right, the bytes were right, and the payload meant "I am doing
nothing". A negative result measured with a no-op payload is not a negative result.

### Pressing A on our character is a request, and it blocks on our answer

With the bubble showing, the player walked up and pressed A, and the console sent a message no
capture in this project had ever held:

    t=37.47  us  ->  64 0003 00 01 04   NetDataTalkReserveResultData{IsCanTalk, IsRecruitment, emoticonStateType}
    t=37.67  con ->  06 0005 00 01000000  NetDataTalkData{talkOpcSexId: 0, talkState: GREETING}
    t=80.68  con ->  10 0002 01 04      NetDataTalkCancelEndData{IsRecruitment: 1, emoticonStateType: 4}

`NetDataTalkReserveData` (0x63) is "I want to talk to your character". In sp70 nothing answered it
and **the player's own character froze until the game was rebooted** - the talk is a
request/response and the console blocks on ours. sp71 answered with `NetDataTalkReserveResultData`
(0x64) and the game ran its whole greeting on screen: a Japanese greeting, a name, and an offer to
trade, ending in "one second!" while it waits. The player can leave it with B; no reboot.

`TalkState` is `{CHECK = 0, GREETING = 1, NONE = 2}`, so the console is parked in `GREETING` waiting
to be advanced. The messages that would advance it are `NetDataSelectData{index}` (0x08) and
`NetDataTransitionData{transitionType, isRecruitment}` (0x07). The `NetDataTalkCancelEndData` at the
end is the B press.

**`IsCanTalk` decides whether the conversation survives, and `0` is the value that keeps it alive.**
Four runs, one variable at a time:

| `IsCanTalk` | what follows the answer | what the screen does |
|---|---|---|
| 0 | nothing | the greeting runs and parks on "one second!" |
| 1 | nothing | "sorry, I have other plans" and the chat closes |
| 1 | `NetDataSelectData{0}` | the same refusal |
| 1 | `NetDataSelectData{1}` | the same refusal |

So the name reads backwards from its behaviour: a **1** is what makes the character decline. It also
means the two runs that swept the select index never tested the select at all - they were refusing
before it could matter, and the index is unmeasured rather than shown not to matter.

**One thing is UNKNOWN and must not be written down as settled.** The name the game showed is not
one we sent - no `NetPlayerNameData` and no trainer card went out in that run - so where it comes
from is unmeasured.

### The trainer card is the card, not the character

`NetDataTranerCardData` (0x05) is 75 blittable bytes whose first fields are `fashionId`, `bodyType`
and `genderid`, which reads like appearance and is not. `UnionOpcManager.CreateTranerCard()` builds
the trainer-card UI - what you see when you look at another player's card - and nothing in it
touches the field model. sp68 sent one, the console acknowledged it on the first try
(`landed at seq 21`), and nothing on screen changed. The appearance lives in the join message.

### A walk has to be at the console's own speed, and has to end in the room

Over 80 of the console's own `NetPosData`: one message every 0.410 s spanning 0.935 units, which is
2.28 units/s. Every run before sp65 sent 0.1 units every 0.35 s - an eighth of that - and the screen
called it a stutter every time. At the console's own numbers the walk is smooth, confirmed on a
retail console.

The first run at that speed walked 60 messages, which is **55.8 units** and crosses the whole room:
the character hit a wall, was pushed back by the game's own collision, moonwalked - facing held at
the angle we sent while the position kept moving - and left through the far wall out of sight.
`--room-walk-steps` bounds it; eight steps stops inside the room. Two things fall out of that: the
game applies collision to a remote character's movement, and it takes our `rot_y` literally rather
than deriving facing from the direction of travel. The player has no collision against our character
at all.

## The trade: the game handed us a Pokemon, and took one back

A retail console opened its trade screen for a character we invented, sent its own trainer record
and one of its Pokemon, and then **accepted a Pokemon we assembled**. The run stops one message
short of the exchange itself, deliberately - that message is where the console writes its save.

### The roles are the other way round from what we assumed

For fifty runs our character advertised itself and waited to be approached. That is backwards.
**Picking an emote locks a player in place waiting to be interacted with**, so a console showing a
trade emote cannot start anything; someone has to walk up to it. The console broadcasts its own
state, so the moment the emote goes up is visible on the wire:

    NetCharacterStateData{state: 4, isRecruiment: 1}     the trade emote, up
    NetCharacterStateData{state: 0, isRecruiment: 0}     and down again

`isRecruiment` is the flag to gate on, not "state is non-zero" - state 18 is a console already
inside a trade, and approaching that is refused. The approach itself is `NetDataTalkReserveData`,
`63 00 01 00`, which is byte-for-byte what the console sends when its player walks up to someone.
It was answered in 40 ms with `NetDataTalkReserveResultData{IsCanTalk: 0, ...}` - and `IsCanTalk`
reads backwards from its name, 0 accepting and 1 declining.

### talkState decides, and one of its three values crashes the game

`TalkState` is `CHECK = 0, GREETING = 1, NONE = 2`. `UnionStateController$$SwitchSpokenStateMine`
is the handler, and its whole shape is one branch:

    0x1fd5e6c  cbz  w21, 0x1fd5e84    talkState == CHECK -> below
    0x1fd5e80  b    0x1fd85e0         anything else -> StartOpenGreetingMsgWindow

    0x1fd5e84  ldr  x0, [x0, #0x10]   systemController->msgWindow
    0x1fd5e88  cbz  x0, 0x1fd5f00     ... and when it is NULL:
    0x1fd5f00  mov  x19, xzr            x19 = 0
    0x1fd5ec0  ldr  x20, [x19, #0x10]   dereferences it. No guard anywhere.

CHECK is only meaningful to a console that already has a message window open. A player standing
with an emote up has none, so sending it takes the game down - twice, before the handler was read.
GREETING takes the branch that *opens* the window, and the game answers it with its greeting, its
name, and an offer to trade. **A state value read out of a sender is not safe to send until the
receiver's handler has been read**: CHECK really is what the initiator sends, in a state the
console was not in.

### The messages, in order

    NetDataTransitionData{transitionType: 18}     entering the trade
    NetDataTradeTranerData        32 B            who they are
    NetTradePokeData             328 B            the Pokemon
    NetDataTradePokeCheckOkData    1 B, value 1   "yours is fine"
    NetDataTradeReadyOkData        2 B            the last message before the exchange

Each is answered with our own. `NetDataTradePokeCheckOkData` is the one worth naming: it is the
console reporting that it looked at a Pokemon we built and found it acceptable.

### The Pokemon is an ordinary encrypted PB8

328 bytes is Gen 8 `SIZE_STORED` exactly, and the format is the Gen 6+ one unchanged: an LCG seeded
with the encryption constant XORs every 16-bit word from 0x08, and the four 80-byte blocks are
permuted by `(EC >> 13) & 31`. **The checksum is the proof** - it sits in the clear at 0x06 and sums
the *decrypted* body, so a wrong key, order or offset cannot produce a match, and a Pokemon we
assemble is verified by decoding it back before it is ever sent. `pokeldn/bdsp/pokemon.py`.

`NetDataTradeTranerData` has no generated layout - its C# struct holds a string - so it is read off
the wire instead, and the reading checks itself: the trainer and secret ids in the clear at 0x1a and
0x1c are the same pair carried inside the encrypted Pokemon of the same trade.

    0x00  name, 8 UTF-16LE code units      0x18  u16, varies between sessions
    0x10  u32, unidentified                0x1a  trainer id
    0x14  u32, unidentified                0x1c  secret id

**What we offer is a real Pokemon with named fields changed**, not one built from nothing. Those 328
bytes hold far more than the dozen fields identified here - met data, ribbons, handler records, the
language byte - and none of it is zero on a console's own. What the game validates on receipt is
unknown: it accepted a near-copy of its own Pokemon, which is not the same as accepting any.

### The gate is one byte, and it is ours

`NetDataTradeReadyOkData` (0x21, `<BB` isTradeOk/tradeState) is not sent, and no option makes one.
Reading the three handlers that a reply has to satisfy says exactly what it would do, and it is
sharper than "the trade completes":

    UnionTradeManager$$RecivePokeData          0x1dd2800   currentState == SELECT_WINDOW only
    UnionTradeManager$$SetTargetTranerParam    0x1dd2130   TargetTranerParam{uint id, string name}
    UnionTradeManager$$ReciveTradeReadyOkData  0x1dd2a70   the switch below

`UnionTradeManager.currentState` is `TradeFlowState {NONE 0, SELECT_WINDOW 1, SECURIY_TRADE 2,
PLAY_DEMO 3, END 4}` and it is the field at +0x88 that every one of them reads. A Pokemon we send is
taken only in SELECT_WINDOW, stored as `tradeSelectModel.targetPokemonParam` with
`isRecivePokeParam` set. A 0x21 is routed on the same field: in SELECT_WINDOW to
`TradeSelectPokeModel$$ReciveReadyOk`, in SECURIY_TRADE to `TradeSecurityController$$ReciveState`
(creating the controller if it is null), and anywhere else it is dropped.

`ReciveReadyOk` is three instructions and they say which byte matters:

    ldrb w8, [x1, #0x11]      the message's SECOND byte, tradeState
    str  w8, [x0, #0x78]      TradeSelectPokeModel.targetTradeState
    ret                       isTradeOk is never read

The console then runs `UnionTradeManager.<WaitBoxWindowComplete>d__24`, and its whole condition is
that **both** trade states are `WAIT`:

    ldr w8, [x0, #0x74]   cmp w8, #2   b.ne  keep waiting     myTradeState
    ldr w8, [x0, #0x78]   cmp w8, #2   b.ne  keep waiting     targetTradeState
    str w8, [x20, #0x88]                                      currentState = SECURIY_TRADE
    bl  TradeSelectPokeModel$$Clear
    ... NetDataTradeReadyOkData$$.ctor; strb wzr, [x19, #0x11]; SendReliableData

`myTradeState` is set to `WAIT` by the player's own `MyReadyOk`, which is what sp87 saw arrive as
`{isTradeOk 0, tradeState 2}`. `targetTradeState` has one source in the whole game and it is our
0x21. **The console cannot leave SELECT_WINDOW on its own**: it is parked waiting for one byte from
us, and that byte is what moves it into the security phase.

### The save, located

Past that gate the flow is `TradeSecurityController` -> `CreateTradeStateModel` -> `TradeStateModel`,
and it is `TradeStateModel` that owns the save. Its own state enum puts the save after the
handshake, not before:

    TradeStateModel.TradeState
    NONE 0, INIT 1, WAIT 2, SEND_POKE 3, WAIT_POKE 4,
    SEND_READYOK 5, WAIT_READYOK 6, START_WRITE_SAVE 7, WRITEING_SAVE 8

and `TradeStateModel$$InitState` calls `PlayerSave` in its first instruction after the prologue.
`WriteSaveData` tail-calls `ReplacePoke`; neither has a direct caller, because the state handlers are
registered as delegates rather than branched to. `FirstSave` arms the disconnect penalty -
`UnionWork$$SetPenartyCounter(30)` - before it writes.

**`BoxWindow.NetTradePhase.WaitSave` is not a save.** The phase enum reads `None, WaitSave,
PlayerSelecting, ...` and `ToNextPhase(0)` walks it by increment, so a console at the box picker has
passed through WaitSave - but the coroutine that phase runs,
`BoxWindow.<WaitTradeSave>d__203$$MoveNext`, reads `FieldCommonParam[0xEB]`, multiplies it by
0.001f and counts it down against `Time.deltaTime`. It is a timed on-screen wait and writes nothing.
The save the box window is waiting *for* is `TradeStateModel.PlayerSave`, which needs a
`TradeStateModel`, which needs the security phase, which needs our byte.

That was read offline, no run spent, and **sp92 then sent the byte and the console did every one of
those things** - see "The trade completes" below. Until then no run in this project had written a
console's save, sp82 and sp87 included.

### The trade completes, and the console writes its save

sp92 answered the 0x21 and a retail Brilliant Diamond went the whole way. `TradeStateModel`'s own
enum, walked in order, six states in 630 ms:

    t=79.41  their READY-OK {isTradeOk 0, tradeState 2}  ->  OUR READY-OK
    t=79.82  INIT          ->  WAIT
    t=80.03  WAIT          ->  WAIT
    t=80.05  SEND_POKE     ->  SEND_POKE, and our Pokemon
    t=80.24  WAIT_POKE     ->  WAIT_POKE
    t=80.44  SEND_READYOK  ->  SEND_READYOK
    t=80.45  WAIT_READYOK  ->  SEND_READYOK
    t=109.31 NetDataReturnSelectData

**The 29 seconds between WAIT_READYOK and that last message are the trade, and nothing is asked of
us in them.** The console sends fifteen game messages across that window and every one is
`NetCharacterStateData` - no trade opcode at all. START_WRITE_SAVE, WRITEING_SAVE, the animation and
`ReplacePoke` are entirely console-side. What a host must do there is simply not leave: a station
that drops in this window drops the console mid-save, between `FirstSave` and `SecondSave`, which is
exactly the state the penalty exists to punish.

**Leaving WAIT_READYOK needs a message to arrive inside a window the console opens on its own
clock** (`waitRndTime` counts down first), so nothing sent in reply to something else is guaranteed
to land in it. The once-a-second repeat of our state is what covers it. FACT that the trade
completed; DEDUCTION that the repeat is what tripped it.

#### `NetDataReturnSelectData`, the message on the far side

    data_id 69 (0x45)   payload 45 00 01 00   {'isReturnSelect': 0}

The same `<id> 00 01 <value>` shape as the check-ok (`46 00 01 01`). It appears only after a
completed trade, and the console repeated it **78 times, once a second, until our station left** -
it is waiting on an answer we do not yet build. By its name it offers the select window again, i.e.
a second trade inside the same association.

#### What was traded, and it is a Pokemon we built

Both runs logged `offering species 41, 'PKCAMP', OT 'Gurvan'`: the template was sp82's own capture
from this console, but `pokemon.build_from` rewrote the nickname before the radio was touched, so
what the player received is **not** the Zubat they gave. It is that Zubat with a field of ours in
it, re-encrypted and re-checksummed by us, and the console took it through `check-ok`, the security
phase and `ReplacePoke` without complaint. **So a PB8 this project assembles is accepted into a
retail save.** That is the claim sp82 and sp87 could not make.

What the console offered is a separate fact and a duller one: sp82, sp91 and sp92's captures share
a sha1, differ in zero of 328 bytes and decode to pid 2329222868 - the player picked the same Zubat
out of the same box three times. **It is not a round trip**; nothing we sent has ever come back to
us. Whether that mon can still be offered now that sp92 traded it away is the cheap thing to check
on the next run.

### The disconnect penalty, and what it proves

Dropping out mid-trade earns "vous ne pouvez pas faire d'echange en reseau pour le moment", and the
console then refuses to advertise at all - a run against it sees `their advertising state seen 0`
and nothing else. Three methods hold all of it:

    TradeStateModel$$FirstSave    0x1cd4fc0   SetPenartyCounter(30); SetPenartyTime(now)
    TradeStateModel$$SecondSave   0x1cd5030   SetPenartyCounter(0)
    UnionFrontDeskStateController$$CheckPenarty  0x1fcc400   counter >= 1 AND not CheckDateTime()

**So the penalty is armed by the FIRST save and cleared by the SECOND** - the classic "you
disconnected between the two writes" design, and a trade that completes clears it on its own. That
also settles a question no screen could answer: **a penalty means `FirstSave` ran, which means the
console really did write.**

**`UnionWork$$CheckDateTime` [0x1dd3e30] is the timer, and it is a sloppy one.** It takes
`DateTime.Now` and adds the fields together with no weighting at all:

    w8 = Year + Month + Day + Hour + Minute + Second
    cset w0, mi            ... on  (stored + 30.0) < w8

`SetPenartyTime` [0x1dd32d0] stores the same sum, so the two are in the same units - and **that sum
is not monotonic**. It rises by 1 a second, then FALLS by 58 when the minute wraps and again when
the hour does: armed at 18:45:20 it is 2125, and at 19:20:00 it is 2081, lower than when it started.
Only the DAY field carries it forward reliably, at +1 a day. So if the penalty is armed at a moment
whose Hour+Minute+Second is already high, no later time that day can beat `stored + 30` at all and
the wait runs to the next day or beyond - **which is where the 24 hours players report comes from**.
It is not a duration in the code anywhere; it is this arithmetic.

FIRST READING, WRONG, AND WORTH KEEPING: "the seconds carry it, so about 30 minutes". That was the
minute wrap considered and the hour wrap not, from the same disassembly, and a player sat through it.
A non-monotonic counter has no "typical" wait - work the worst case.

Nothing else in the check is time-shaped, so raising a field on the console's own clock clears it -
but **the amount has to survive the same non-monotonicity**. `Hour+Minute+Second` spans 0..141, so
between the arming and the check it can fall by as much as 141, and a stable gain has to beat
`30 + 141`: **a year moved forward by 172 or more always clears it**, a smaller one only clears it
if the time of day happens to cooperate. A console set forward by 31 years was still refused on
hardware, which is this same arithmetic caught a second time. Moving the clock back restores the
penalty, because only `SecondSave` zeroes the counter - so it has to stay forward until a trade
completes.

SECOND WRONG READING, and it is the SAME error: "+31 in one field, since the comparison is strict".
Both mistakes came from treating a sum of calendar fields as a clock. It is not one, and every
statement about how long it lasts has to carry the worst case of every field that can fall.

## The pages

- [Joining the session](bdsp_ldn.md) - the advertisement, the passphrase, and taking a seat.
- [Pia, and the game key](bdsp_pia.md) - the packet format, the key hierarchy, and exactly what is
  still missing.

## Reading the game

Both pages lean on being able to read the title's own binary. The method is general to any Unity
Switch game and is written up separately under
[Reverse-engineering a Switch title](switch_re.md) - extracting the executable from an NSP without
unpacking it, the IL2CPP metadata that names the C# surface, and the C++ RTTI that names Pia's 279
classes.
