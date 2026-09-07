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

**And the game itself is now readable.** The reliable stream carries the player's position - a
facing angle in degrees and three floats - and the unreliable stream carries a keepalive and a trail
of recent positions while an avatar walks.

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

### It was answered, and nothing happened

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
