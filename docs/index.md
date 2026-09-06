---
title: Home
nav_order: 1
---

# Speaking Nintendo Switch local wireless to Pokemon games

A Linux box joins a Nintendo Switch's local wireless (LDN) session and talks to the Pokemon game
running on it. These pages are the working notes behind that: what the console does on the wire,
with the decompilation citations, the disassembly and the hardware runs behind each finding.

The code, the install instructions and the CLI reference are in the
[repository README](https://github.com/Decryptu/pokeldn#readme).

## Two kinds of target

**FireRed and LeafGreen** are a GBA ROM running inside an emulator on the Switch, so there are two
protocol layers: the console's LDN/Pia wireless underneath, and the ROM's own GBA link above it.
This is where the project has gone deepest, and everything below works on retail hardware:

> both directions of Mystery Gift, trade host and joiner, every Union Room activity including full
> link battles, Wonder News, the cable-club colosseum, and a visiting Battle Tower trainer. Through
> the gift link's two interpreters, arbitrary code on the console: its memory read and written, its
> ROM mapped, its own functions called, and a Pokemon we chose built by its own `CreateMon`.

**Brilliant Diamond and Shining Pearl** are a native Switch title. There is no ROM and no emulator;
Pia is the game's own transport, and above it sits Unity/IL2CPP game code. Here the project has an
LDN seat in a real Union Room session and a decoded Pia packet format, and the payloads are still
encrypted.

The wireless layer underneath is the same for both, and is the part that carries to the next game.

## The sections

### [The wireless layer](ldn.md)

LDN and Pia: what any Switch title advertises, what it takes to associate, the Pia packet formats by
version, and the two families of session-key derivation. Game-independent, and the part that carries
to the next title.

### [FireRed and LeafGreen](frlg.md)

The deepest section. The [link protocol](frlg_link.md), [Mystery Gift](frlg_gift.md), and
[inside the console](frlg_rom.md) - the Mystery Event VM, native ARM code, the ROM's own function
tables, the save, and the RNG - plus [the second cartridge](frlg_leafgreen.md).

### [Brilliant Diamond and Shining Pearl](bdsp.md)

A native Switch title: no ROM, no emulator, Pia as the game's own transport. An LDN seat in a real
Union Room session, a decoded packet format, and an honest account of what is still encrypted.

### [Reverse-engineering a Switch title](switch_re.md)

How to read a retail game's own code on a machine too small to hold it, and the two naming layers -
IL2CPP metadata and C++ RTTI - that turn guesswork into reading. General to any Unity Switch title.

### [Hardware and setup](hardware.md)

The adapter, the Raspberry Pi deployment, and installing Switch keys. Read the adapter page before
blaming the adapter.

## Start here

- [Console protocol notes](frlg_link_notes.md) - the big one. What a host must give a FireRed
  console, and what a peer must.
- [Native code on the console](frlg_rom_buffer_script.md) - how 1024 bytes of ARM get called on a
  retail Switch with no glitch and no prepared save.
- [The random number generator](frlg_rom_rng.md) - reading the console's seed, and the staged stub
  that makes a wild Pokemon shiny for one A press.
- [Joining the session](bdsp_ldn.md) - a Linux box holding a seat in a native Switch game's Union
  Room.
- [Reverse-engineering a Switch title](switch_re.md) - the method, if you are pointing this at a
  game that is not here yet.

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.
