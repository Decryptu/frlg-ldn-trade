---
title: Home
nav_order: 1
---

# frlg-ldn-trade

A Linux box speaks Nintendo Switch local wireless (LDN) to a real Switch running Pokemon
FireRed/LeafGreen: it trades Pokemon, distributes Mystery Gift Wonder Cards, and holds Union Room
link battles. These pages are the working notes behind it — what the console actually does on the
wire, with the decompilation citations and the hardware runs that established each finding.

The code, the install instructions and the CLI reference live in the
[repository README](https://github.com/Decryptu/frlg-ldn-trade#readme).

## Protocol findings

- [Console protocol notes](joiner_protocol_notes.md) — the big one. What the console needs from a
  host and from a peer: the child's frame cadence, the seat barrier, the 3-second wall and the
  802.11 rate set that closed it, the emulator's `svc_51` link close, the Union Room (greeting,
  trading board, chat, battle), and the link-battle gate rules found on hardware.
- [Trade-host design](frlgtrade_host_design.md) — component boundaries, protocol flow, timing
  ownership, trainer propagation, and the shutdown sequence.
- [JoySpot discovery](joyspot_discovery_findings.md) — why the Wireless Communication path is not
  reachable, what was tested, and what would reopen it.

## Hardware setup

- [TP-Link Archer T3U](tplink_archer_t3u.md) — the USB 3 mode switch, NetworkManager, and the
  interface state a run needs. Read this before blaming the adapter.
- [Raspberry Pi host](raspberry_pi.md) — deploying the Mystery Gift host to a Pi 4.
- [Switch keys on the Pi](switch_keys.md) — installing `prod.keys` without it touching a shell
  history or a repository.

## Mystery Gift authoring

- [Composing gifts](mystery_gift_composer.md) — building a new event from validated delivery
  stages, rewards, messages, sprites, battles and stamp slots.
- [Legendary-beast gift](legendary_beast_gift.md) — the starter-dependent Suicune/Entei/Raikou
  cutscene, its binary export and save injection.
- [Stamp rally](stamp_rally.md) — the two-card Solrock and Lunatone event, its saved state and
  reward sequence.
- [Porygon TM gift](porygon_tm_gift.md) — a composed event delivering TM29 and TM46 with a
  Clefairy delivery scene.
- [Wonder News](wonder_news.md) — the other column of the console's Mystery Gift menu: the 444-byte
  struct, the activity byte that makes the host visible on that screen, and the one gift path where
  the console answers back.
- [What the gift link can still carry](mystery_gift_untried.md) — the whole capability surface of
  the Mystery Gift session: what has been sent, what is closed with evidence, and what is left.

## Credits

Built on [kinnay's LDN library](https://github.com/kinnay/LDN) and the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki), and read against
[pret/pokefirered](https://github.com/pret/pokefirered), the FireRed/LeafGreen decompilation.
