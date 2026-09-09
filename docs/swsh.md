---
title: Sword and Shield
nav_order: 5
has_children: true
---

# Sword and Shield

The second **native** Switch title this project has read, and the first one whose Mystery Gift
menu has a local-wireless branch - the same shape of target as FireRed's Wonder Card, one
generation of hardware later.

Measured on a **Shield 1.3.2 EUR cartridge image** (`01008db008c2c000`, update NCA, SDK 7.7.0.0),
against a **French Sword 1.3.2** on the console. The two builds share their network code; where a
finding could differ between the pair it says so.

The reading is split by layer, and each page below is self-contained:

| page | what |
|---|---|
| [The cartridge and its keys](swsh_cartridge.md) | what the title is made of, the passphrase, the Pia game key, opening the image |
| [Taking a seat in a Sword mesh](swsh_session.md) | Pia 4, the association, and the first application data |
| [The party and the PK8](swsh_pokemon.md) | the party on 0x84 and the record inside it |
| [The trade](swsh_trade.md) | three pages: the screen, the content framework, the confirmation ladder |
| [Mystery Gift on Sword](swsh_gift.md) | the local branch of the Mystery Gift menu |

## What this project has measured, and what it has borrowed

FACT, sw70's own capture (`scratchpad/sw_app_payloads.py` walks it): the console sent **five
distinct application payloads and no others** across the whole run -

    0x7C  id 97     0a00        ping            x20
    0x7C  id 97     1200        pingReply        x2
    0x7C  id 97     1a00        pingSynced       x3
    0x7C  id 60000  0a00        result{}         x2
    0x80  id 60000  12020801    imReady{true}    x2

Those five are ours. **Everything past the trade snapshot is not.** `pokeldn/swsh/trade.py` carries
`SYNC_ANSWERS`, a table of what to answer for the other sync holders, and it is `nxldn-lab`'s
reading of a console-to-console capture, reproduced with its source named. Its ids are real and its
bytes for 97 and 60000 agree with ours exactly, which is the only part of it we can check.

**THE MEASUREMENT THAT MAKES IT OURS COSTS NO EXTRA ASSOCIATION.** `bin/swsh_connect.py
--sync-answers` answers the table where it has a rule and keeps sw68/sw70's proven per-protocol
echo everywhere else, and it PRINTS every distinct payload it has no rule for. The console names
its own ids; the run is what asks it to.

Against sw70 that changes exactly two things: the first thing we say to `ping` becomes `pingReply`
rather than an echo, and `pingSynced` gains a `result{}` behind it. Nothing else about the run
moves, which is what one variable means here.

## Open questions

- ANSWERED, sw68/sw70, and it is the point of the project's next step. **What the game says once
  it is answered**: it walks ping -> pingReply -> pingSynced, asks for `result{}` on 0x7C and
  `imReady` on 0x80, and then sends its own party on 0x84. See the two sections above.
- ANSWERED, session 64, offline. **What the confirmation content accepts.** Content 40's
  10000-base holder takes `SyncSaveDataHolder{syncCommand{data:int32}}` and nothing else, its
  handler `0x010dbc90` has content 50's station-index gate and its own two-slot limit, and its state
  machine sends 0, 1, 2 and 3 as a handshake. See "The confirmation content takes a command, not a
  Pokemon". **PARTLY ANSWERED ON HARDWARE, sx52e/sx53**: command 0 reaches the receive event, and
  with the pair re-armed the console climbs a ladder rather than stalling - see "The confirmation
  content answers, and it climbs". **ANSWERED IN THE BINARY, session 65: each rung does want the
  next command.** The state field `delegate+0x5c` has three writers and only one is outside the
  machine - a phase-to-state map whose only caller is the pump - and a command announces the phase
  that unlocks the command after it. See "The ladder is a barrier, and every rung needs a command".
  What is still NOT known is what advances the content's phase `+0x17c`; `--confirm-commands
  0,1,2,3` is built, tested and has never been on the air.
- **Sending a party back.** Nothing of ours has ever been on 0x84. `pokemon_trade.proto` (package
  `net_contents.trade.common.pokemon_trade.protocol_buffers`) is `Pokemon { bytes
  serializePokemonParam }` and `PokemonTradeDataHolder { Pokemon pokemon }`, so a trade message is a
  serialised PK8 inside one protobuf field. `pokeldn/swsh/pokemon.py` builds and encrypts one;
  `build_from` edits a record the console itself sent, so every byte we have never read stays a real
  byte from a real save. What is NOT known is which message id carries it, and on which protocol.
- **The trailer of the 0x84 payload.** Six 24-byte records at 0xA00 and a raw-deflate stream at
  0xAF9 that carries the trainer name a third time. Nothing in the schemas has been matched to
  either yet, and the nine bytes that move between runs are all inside the deflate.
- **The two unnamed header fields**, the byte at 0x05 and the halfword at 0x06. What writes them is
  `0x017beb74`/`0x017beb78`; what they mean is a deduction until a capture agrees.
- ANSWERED, sw01. **What seeds the session key** is the advertisement's session parameter, twelve
  bytes in, little-endian - BDSP's offset exactly. The code at `0x0179bff0` -> `0x01774f40` computes
  a seed a different way (AES-GCM over the session's own two 64-bit values, keyed by them), so
  reading that path is what to do if a session ever turns up whose key this does not derive; for a
  console hosting a local trade, the advertisement is enough.
- ANSWERED, sw01. **The local communication id** is `0x0100ABF008968000` and the version is 4, scene
  60001, app version 7, read off the advertisement. That id is **Sword's**, and the binary this
  project reads is Shield - the first place the pair are known to differ.
- **What `StateReceiveLocal` actually sends**, and whether the console hosts or scans on that
  screen. A scan answers the second half in one run.
- **Sword against Shield.** Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version are now measured to hold across the pair - they
  associated and decrypted - and the local communication id is measured NOT to. Mystery Gift's
  states are still Shield-only readings.
- ANSWERED, session 56, offline. **The message header's presence bits.** Bit 0x10 owns the extra
  eight-byte field and bits 0x20/0x40 own nothing, read off the size arithmetic the library inlines
  at eighteen sites (`docs/pia.md` "Which presence bit owns which field"). No second message shape
  was needed - the capture could not have separated them, and the code states it outright.
- ANSWERED, sw02/sw03. **What protocol 0x24 is**: Pia's Local Protocol, BDSP's numbering exactly,
  and the console acts on what we send it there.
- ANSWERED, sw20/sw21/sw24. **The Mesh Station Protocol (0x14) request.** Version 4 puts a flag
  byte at [3] and every field after it moves; clearing it is what got a request answered, and the
  console then completed the handshake and accepted us as a station. `docs/pia.md` "The version-4
  Mesh Station Protocol" and `pokeldn/ldn/station4.py`. The loop at `0x0185c5c0` reads a 32-entry
  table of `{u8, u16be, u64be, u64be}` = 19 bytes each and is a station table, not the request.
- ANSWERED, session 57, offline. **The Mesh Protocol (0x18) join.** Its dispatcher is `0x017c0c80`
  off `MeshProtocol::vfunc9`, its message table is BDSP's without 0x22 and 0x23, its join-request
  handler (`0x017c1700`) checks the same six bytes we already send, and its join-response parser
  (`0x017b4830`) has the same sixteen-byte header over **64-byte** entries with the index at 0x3E.
  `docs/pia.md` "The version-4 Mesh Protocol". SENT AND ANSWERED at sw29: one request, one
  acceptance, `our_index` 1, and the console then opened seven protocols at us.
