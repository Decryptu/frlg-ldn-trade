---
title: Home
nav_order: 1
---

# pokeldn

pokeldn is a Linux implementation of Nintendo Switch local wireless (LDN) that speaks to Pokemon
games running on retail Switch hardware. These pages document the protocols involved, with the
decompilation citations, disassembly addresses and hardware measurements behind each finding.

Installation, the command-line reference and the code layout are in the
[repository README](https://github.com/Decryptu/pokeldn#readme).

## Targets

Two kinds of title share one wireless layer.

FireRed and LeafGreen run as a GBA ROM inside an emulator on the Switch, so two protocol layers
are stacked: the console's LDN/Pia wireless underneath, and the ROM's own GBA link above it. Proven
on retail hardware: Mystery Gift in both directions, trade host and joiner, every Union Room
activity including link battles, Wonder News, the cable-club colosseum, a visiting Battle Tower
trainer, and arbitrary ARM code on the console: its memory read and written, its ROM mapped, its
own functions called, and a Pokemon built by its own `CreateMon`.

Brilliant Diamond and Shining Pearl and Sword and Shield are native Switch titles. Pia is the
game's own transport, with Unity/IL2CPP (BDSP) or native C++ with protobuf messages (Sword/Shield)
above it. Both have completed a trade with a retail console.

## Sections

| section | contents |
|---|---|
| [The wireless layer](ldn.md) | LDN and Pia: advertisements, association, packet formats by version, session-key derivation. Game-independent. |
| [Reverse-engineering a Switch title](switch_re.md) | Reading a retail game's own code: NCA/RomFS extraction in place, IL2CPP metadata, C++ RTTI. General method. |
| [FireRed and LeafGreen](frlg.md) | The GBA link, Mystery Gift, code execution on the console, the RNG, the two cartridges. |
| [Brilliant Diamond and Shining Pearl](bdsp.md) | Pia 5.27-5.45, the Union Room, and the trade flow. |
| [Sword and Shield](swsh.md) | Pia 4, the sync framework, trading, and the Mystery Gift local branch. |
| [Hardware and setup](hardware.md) | Adapters, Raspberry Pi deployment, Switch keys. |

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.
