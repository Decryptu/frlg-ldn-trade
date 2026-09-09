---
title: Sword and Shield
nav_order: 6
has_children: true
---

# Sword and Shield

Pokemon Sword and Shield are native Switch titles. Pia is the game's own transport and the game's
code sits directly on it, written in C++ with protocol-buffer messages above a generic
publish/subscribe framework.

The static reading is taken from a **Shield 1.3.2 EUR** cartridge image (`01008db008c2c000`, update
NCA, SDK 7.7.0.0). Hardware measurements are against a **French Sword 1.3.2**. The two builds share
their network code; where a finding differs between the pair it is marked.

**A retail Sword has completed a trade with pokeldn**: it accepted a Pokemon, gave one of its own,
wrote its save and returned the player to the overworld.

## Pages

| page | contents |
|---|---|
| [The cartridge and the session](swsh_session.md) | what the title is built from, the LDN passphrase and Pia game key, reading the image, Pia 4, and the association through to the first application data |
| [The sync framework](swsh_protocol.md) | message ids, contents and holders, the routing path from the radio to a handler, and the party payload |
| [Trading](swsh_trade.md) | the trade screen, the box state machine, and the confirmation ladder |
| [Mystery Gift](swsh_gift.md) | the local-wireless branch of the Mystery Gift menu |

## What is measured and what is borrowed

Every message id, structure offset and address on these pages is read out of Shield's `main` or
measured on the air, except where a section names an external client.

`pokeldn/swsh/trade.py` carries `SYNC_ANSWERS`, a table of what to answer for sync holders this
project has not exercised. It is `andyjusa/nxldn-lab`'s reading of a console-to-console capture,
reproduced with its source named. Its ids for messages 97 and 60000 agree with pokeldn's own capture
byte for byte.

Four published clients read this game's LAN mode and were found by searching its Pia game key:
`kwsch/PokePiaSWSH`, `lincoln-lm/swsh-lan-client`, `andyjusa/nxldn-lab` and `Slashcash/PSD`. They
share the payload layouts from the Pia station handshake upward; the LDN link layer below is not
covered by any of them, and none of them handles Pia host migration.

## Unresolved

- **The two unnamed Pia header fields**, the byte at 0x05 and the halfword at 0x06. Written by
  `0x017beb74`/`0x017beb78`; both were zero in every packet captured.
- **The 660-byte tail of the 0x84 party payload** at offset 0xAEC. No published client names it
  either. Three bytes of it change between runs, one per 17-byte record in a run of three otherwise
  identical ones; within a run the byte decrements by one down the three. Two captures 19 minutes
  apart differ by 19 in that byte, which is consistent with a minute counter and rests on one data
  point.
- **What `StateReceiveLocal` speaks**, and whether the console hosts or scans on the Mystery Gift
  local-wireless screen.
- **How a partner's command reaches a sub-element's body word.** The receive handler `0x010dbc90`
  does not write it; that a command arriving is what lets the shared value move is inferred from a
  per-station flag and from every run so far.
- **The elementId-10000 hash inputs.** The formula is read (a CRC-32 quorum over the sub-elements'
  clocks); an inversion search over every clock in the observed window finds no two-station solution,
  so either the channel's list holds more than two stations or the hashed clock is not the envelope
  clock. Recorded so the search is not repeated.
- **Sword against Shield.** Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version hold across the pair. The local communication id does
  not: `0x0100ABF008968000` is Sword's. Mystery Gift's state names are Shield-only readings.
- **A third sub-element kind takes two-byte bodies** (`0x006d69f0`, `cmp x2,#2`). Which element field
  carries it is unknown; the confirmation element's update touches only `+0xd0`, `+0xf0` and `+0x110`
  and all three are accounted for.
