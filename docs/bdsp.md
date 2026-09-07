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

**How a message lands.** The reliable sequence id is shared with the console's OWN sends, and
anything below the number its acknowledgement names is discarded in silence. The proof is
arithmetic: one run's ack sat at 13, twenty messages went out numbered 1 to 20, and exactly the
eight from 13 up became avatars. Read the id fresh immediately before each send.

**What the screen said and the capture could not.** The twelve points in a `NetPosData` message are
meant to span the movement since the last one - sending twelve near-identical points makes the
avatar stutter. A character that stops receiving position updates is dropped after about twenty
seconds, so the one being moved was properly owned while the crowd that never moved was not.

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
today, and `room.answer()` already returns it.

**So one of the two messages the console has been repeating at us for every run of this project is a
question addressed to us, and nothing we have ever sent has answered it.** Building the answer from
the table reproduces the console's own four bytes exactly, which is the check that the reading is
right before any run is spent on it. `bin/bdsp_connect.py --answer-requests` sends it; the counter
to read afterwards is whether the request keeps being asked.

On the unreliable protocol the console sends a five-byte keepalive `04 00 02 00 00` every two
seconds while nothing happens, and a **trail** while an avatar moves: three bytes of head and then
triples of little-endian halfwords, twelve of them in the 75-byte form, stepping smoothly from one
to the next. Their units are not the position message's, and calling them anything more than a
trail would be a guess. `pokeldn/bdsp/room.py`.

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
