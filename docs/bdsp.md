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

**One avatar appears per message, because every message was a JOIN.** `UnionOpcManager` calls
`CreateCharacter(joinData)` on each one, so forty joins are forty arrivals and the game is behaving
correctly; the mistake was ours. What those avatars have no owner for, though, is real: they
**survive the scene**. The player walked out of the Union Room and down to the Poke Center floor, into
a shop, and the whole crowd came along, still through the walls. Only restarting the game cleared
them. A remote player created without a session behind it is never cleaned up.

**Not yet done.** The **Session Protocol (0x94)**, which sits above the reliable transport, has
never carried a byte in any capture: the game has not opened it, and it is what would make those
avatars one player instead of a crowd.

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
| `12 0001 23` | 0x12 | - | one byte |
| `23 0001 00` | 0x23 | - | one byte |

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

The twenty bytes the console repeats on the reliable protocol until they are acknowledged are the
first thing this project has read that the GAME wrote rather than the middleware:

| offset | size | field |
|---|---|---|
| 0x00 | 6 | a fixed head, `01 00 11 08 00 31` in every capture |
| 0x06 | 2 | facing angle in **degrees**, little-endian |
| 0x08 | 4 | x, little-endian float |
| 0x0c | 4 | y, little-endian float - the floor |
| 0x10 | 4 | z, little-endian float |

Four runs caught four different places on that floor, and the angle was 0, 90, 90 and 225 - every
one a multiple of 45, which is what an eight-direction facing is. `y` is 0.0 in three of them and
1.5e-08 in the fourth, so it is a height on a flat room and not a constant.

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
