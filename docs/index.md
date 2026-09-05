---
title: Home
nav_order: 1
---

# frlg-ldn-trade

A Linux box speaks Nintendo Switch local wireless (LDN) to a real Switch running Pokemon
FireRed/LeafGreen: it trades Pokemon, distributes Mystery Gift Wonder Cards, holds Union Room link
battles, and runs native code on the console. These pages are the working notes behind it: what the
console does on the wire, with the decompilation citations and the hardware runs behind each
finding.

The code, the install instructions and the CLI reference are in the
[repository README](https://github.com/Decryptu/frlg-ldn-trade#readme).

## What works on retail hardware

Both directions of Mystery Gift, trade host and joiner, every Union Room activity including full
link battles, Wonder News, and a visiting Battle Tower trainer. Through the gift link's two
interpreters, arbitrary code on the console: its memory read and written, its ROM mapped, and its
Easy Chat vocabulary read word by word.

## The sections

### [The link protocol](protocol.md)

What the console needs to hear before it will talk, across the two layers that fail differently: the
emulator's LDN/Pia wireless layer and the ROM's own GBA link. The 3-second wall and the rate set
that closed it, the seat barrier, the Union Room, the link-battle gate rules.

### [Mystery Gift](mystery_gift.md)

Authoring and delivering gifts: composing an event from validated stages, the legendary-beast
cutscene, the stamp rally, Wonder News, and the survey of what the gift link is known to carry.

### [Inside the console](inside_the_console.md)

The two interpreters the gift link will run, the Mystery Event bytecode VM and native ARM handed
straight to the CPU, and what they have read back: the save, the ROM, `gRngValue`, and all 1006
words of the French Easy Chat vocabulary.

### [Hardware and setup](hardware.md)

The adapter, the Raspberry Pi deployment, and installing Switch keys. Read the adapter page before
blaming the adapter.

## Start here

- [Console protocol notes](joiner_protocol_notes.md) - the big one. What a host must give the
  console, and what a peer must.
- [Native code on the console](buffer_script.md) - `CLI_RUN_BUFFER_SCRIPT`: how 1024 bytes of ARM
  get called on a retail Switch with no glitch and no prepared save, and the payloads built on it.
- [Reading the save](reading_the_save.md) - the secret ID, and the party's PIDs, IVs and natures,
  in one run.
- [The random number generator](rng.md) - reading the console's seed in the overworld, predicting
  what it will build, and the staged stub that makes a wild Pokemon shiny for one A press.
- [What the gift link can still carry](mystery_gift_untried.md) - what has been sent, what is
  closed with evidence, what is left.

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.
