---
title: FireRed and LeafGreen
nav_order: 3
has_children: true
---

# FireRed and LeafGreen

The Switch release of FireRed and LeafGreen is the **original GBA ROM running inside an emulator**,
so there are two link layers stacked on top of each other, and they fail differently:

| layer | whose | where it is documented |
|---|---|---|
| LDN and Pia | the emulator's, shared with every other Switch title | [The wireless layer](ldn.md) |
| the GBA link - RFU frames, seats, block sends | the ROM's | these pages |

That second layer is what a native Switch title does not have, and it is why almost everything this
project can do to a FireRed save has no equivalent in Brilliant Diamond yet. It is also the reason
[pret/pokefirered](https://github.com/pret/pokefirered) is authoritative here: the code the console
runs is the code in that decompilation, at `REVISION >= 0xA`.

## Where it stands

**Every activity the console offers has been hosted on retail hardware**, both cartridges: Mystery
Gift in both directions, trade as host and as joiner, the whole Union Room including full link
battles, Wonder News, the cable-club colosseum, and a visiting Battle Tower trainer.

Through the gift link's two interpreters the console will also run **code we send it** - its memory
read and written, its ROM mapped into named functions for the build it actually runs, its own
functions called with eight arguments, and a Pokemon we chose built by its own `CreateMon` and left
in the player's party. The RNG is closed end to end, so a shiny encounter costs one A press.

## The pages

- **[The link protocol](frlg_link.md)** - what the console needs to hear before it will talk, and
  what it does once it will. Start with the [console protocol notes](frlg_link_notes.md).
- **[Mystery Gift](frlg_gift.md)** - authoring and delivering gifts: Wonder Cards, Wonder News, the
  composer, and what the link can still carry.
- **[Inside the console](frlg_rom.md)** - the two interpreters, the ROM's own addresses and function
  tables, native ARM code, the RNG, and the save.
- **[LeafGreen](frlg_leafgreen.md)** - what the second cartridge shares with FireRed, and the
  measured offset map for what it does not.

## The two cartridges

LeafGreen is the same game with the same code at a different address. The offset is piecewise
constant - four low segments stepping -0x2C, -0x28, -0x24, -0x20, then -0x1C4 and -0x12D8 higher up
- and it is **not** monotonic, so a less divergent segment is not a mistake. What has actually been
measured lives in `pokeldn.frlg.rom.leafgreen_twins` (738 paired addresses, each read off its own
cartridge) and `rom_map.LEAFGREEN_DELTA_BOUNDARIES`. Never predict an address across the boundary
you have not bracketed.
