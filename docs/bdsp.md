---
title: Brilliant Diamond and Shining Pearl
nav_order: 5
has_children: true
---

# Brilliant Diamond and Shining Pearl

Brilliant Diamond and Shining Pearl are native Switch titles built in Unity by ILCA. There is no ROM
and no emulator: Pia is the game's own transport and IL2CPP game code sits directly on it.

Measured against a **French Shining Pearl, version 1.3.0**, in the Union Room (Pokemon Center 2F,
the left attendant, the plain "yes" — not the password or group options).

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

## Pages

| page | contents |
|---|---|
| [Joining and the Pia layer](bdsp_session.md) | the advertisement, the passphrase, the seat, the packet format, the key hierarchy, and the mesh handshakes |
| [The game protocol](bdsp_protocol.md) | the 65 messages BDSP speaks, the Union Room, and controlling a character |
| [Trading](bdsp_trade.md) | the trade flow, the PB8, the save, and the disconnect penalty |

## Unresolved

- **`NetPlayerNameData`'s framing**, and eight others. Twelve of the 65 message structs hold a C#
  string, an array or a list, and the source decides no layout for them; `netdata.OPAQUE` names all
  twelve. Three are decided from the wire and listed in `room.MEASURED`, and they are the only three
  any capture holds — the remaining nine have never been on the air, so there is nothing to measure
  them against.
- **The Session Protocol (0x94)**, which sits above the reliable transport and has never carried a
  byte in any capture.
- **Whether the console reads a `NetCharacterStateData` answer at all.** The answers are accepted by
  the transport, land on the right stream with the right bytes, and have no observable effect.
- **`NetDataReturnSelectData`** (id 69), which appears only after a completed trade and is repeated
  once a second until the peer's station leaves. By its name it offers the select window again, i.e.
  a second trade inside the same association. Nothing builds an answer.
- **The name the game shows for a talked-to character.** It is not a value pokeldn sent — no
  `NetPlayerNameData` and no trainer card went out in the run that produced it.
- **Whether the console sets `IsNicknamed` on every received Pokemon** or only when the name differs
  from the species name. One run with a name equal to the species name separates those.
- **`NetDataSelectData`'s index.** The two runs that swept it were declining the conversation before
  the index could matter, so it is unmeasured rather than shown not to matter.
