---
title: Brilliant Diamond and Shining Pearl
nav_order: 5
has_children: true
---

# Brilliant Diamond and Shining Pearl

Brilliant Diamond and Shining Pearl are native Switch titles built in Unity by ILCA. Pia is the
game's own transport and IL2CPP game code sits directly on it.

Measured against a French Shining Pearl, version 1.3.0, in the Union Room (Pokemon Center 2F, the
left attendant, the plain "yes") and in the Grand Underground.

## Status

Proven on retail hardware, end to end:

- LDN association and a seat in the console's session, needing only `prod.keys` and the title's LDN
  passphrase.
- Every packet decrypted, and the send path proven byte-exact against the console's own ciphertext.
- The Local Protocol, Mesh Station Protocol and Mesh Protocol handshakes; a station in the console's
  mesh; its round-trip timer answered; its reliable transport acknowledged in both directions.
- A character of pokeldn's own choosing walking in a retail Union Room, showing a trade emote, and
  running the game's own greeting dialogue with the player.
- A complete trade: the console opened its trade screen for that character, offered a Pokemon,
  accepted one pokeldn assembled, wrote its save, and offered the select window again.
- Record mixing, ball capsules and a battle lobby driven to the point where the console sends its
  record, its capsule and its six chosen Pokemon.
- A character walking on the Grand Underground floor, and the console's secret base read out.

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, and the mesh handshakes |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- One payload never on the wire. Twelve of the 65 message structs hold a C# string, an array or a
  list; `netdata.OPAQUE` names them. The executable's `Il2CppTypeDefinitionSizes` decides the size
  and packing of all twelve; eleven have been on the wire and match (`room.MEASURED`). The twelfth,
  `NetDigGroupIdData` (0x29), has no sender in 1.3.0 ([the protocol page](bdsp_protocol.md)).
- The Session Protocol (0x94) sits above the reliable transport and has never carried a byte in any
  capture.
- Whether the console reads a `NetCharacterStateData` answer. The answers are accepted by the
  transport, land on the right stream with the right bytes, and have no observable effect.
- `NetDataReturnSelectData` (id 69) appears only after a completed trade and is repeated once a
  second until the peer's station leaves. By its name it offers the select window again (a second
  trade inside the same association). Nothing builds an answer.
- The name the game shows for a talked-to character. No `NetPlayerNameData` and no trainer card
  went out in the run that produced it.
- Whether the console sets `IsNicknamed` on every received Pokemon or only when the name differs
  from the species name. One run with a name equal to the species name separates those.
- `NetDataSelectData`'s index. The two runs that swept it declined the conversation before the index
  could matter; it is unmeasured.
