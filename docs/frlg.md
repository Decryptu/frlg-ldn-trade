---
title: FireRed and LeafGreen
nav_order: 4
has_children: true
---

# FireRed and LeafGreen

The Switch release of FireRed and LeafGreen is the **original GBA ROM running inside an emulator**,
so two link layers are stacked on top of each other and they fail differently:

| layer | whose | documented in |
|---|---|---|
| LDN and Pia | the emulator's, shared with every other Switch title | [The wireless layer](ldn.md) |
| the GBA link — RFU frames, seats, block sends | the ROM's | these pages |

Because the code the console runs is the code in the decompilation,
[pret/pokefirered](https://github.com/pret/pokefirered) is authoritative for the whole game-level
protocol at `REVISION >= 0xA`. The cartridge header confirms it: software version `0x0A`, game code
`BPRF` (FireRed, French) and `BPGF` (LeafGreen, French), read off both consoles.

Almost every hard bug in this project came from mistaking one layer for the other. The three-second
disconnection looked like a game timeout and was an 802.11 rate set; a stall in the transmit path
looks like a kernel problem and crosses a userspace hop.

## Status

Every activity the console offers has been hosted on retail hardware, on both cartridges: Mystery
Gift in both directions, trade as host and as joiner, the whole Union Room including full link
battles, Wonder News, the cable-club colosseum, and a visiting Battle Tower trainer.

Through the gift link's two interpreters the console also runs code sent to it: its memory read and
written, its ROM mapped into named functions for the build it actually runs, its own functions called
with eight arguments, and a Pokemon chosen by the host built by its own `CreateMon` and left in the
player's party. The RNG is closed end to end, so a shiny encounter costs one A press.

## Pages

| page | contents |
|---|---|
| [The link protocol](frlg_link.md) | the RFU link layer, the seat barrier, the Union Room, chat, link battles, and the cable-club colosseum |
| [Mystery Gift](frlg_gift.md) | the gift session, authoring gifts, Wonder News, the visiting trainer, and the blocked Wireless Communication path |
| [Code on the console](frlg_rom.md) | the Mystery Event VM, native ARM payloads, and reading and writing the live save |
| [The ROM map](frlg_rom_map.md) | how addresses were measured, the four function tables, the species table, and the French Easy Chat vocabulary |
| [The random number generator](frlg_rng.md) | reading and predicting `gRngValue`, and the field stubs that aim an encounter |
| [LeafGreen](frlg_leafgreen.md) | what the second cartridge shares, the measured offset map, and the English build as an instrument |
| [Host implementation](frlg_host.md) | the component boundaries of the trade and Mystery Gift hosts |

## The two cartridges

LeafGreen is the same game with the same code at a different address. The offset is piecewise
constant — four low segments stepping −0x2C, −0x28, −0x24, −0x20, then −0x1C4 and −0x12D8 higher up —
and it is **not** monotonic, so a less divergent segment further up is not a mistake. Measured pairs
live in `pokeldn.frlg.rom.leafgreen_twins` (738 addresses, each read off its own cartridge) and
`rom_map.LEAFGREEN_DELTA_BOUNDARIES`. Never predict an address across a boundary that has not been
bracketed.

## Rules that hold across all of it

**Nothing is inferred from the decompilation's addresses.** The decomp's *link order* is fair
evidence and has been used several times; its addresses never are.
`pokeldn/frlg/rom/rom_map.py` records how each address was obtained.

**A payload is executed offline before it is ever sent.** `buffer_script.emulate` and
`emulate_repeating` run it under unicorn on a model of the GBA memory map, and both simulated
consoles run it too. A payload that faults, or never returns 1, hangs the Mystery Gift menu with no
way out; a field stub that loops forever freezes the overworld with no menu at all.
