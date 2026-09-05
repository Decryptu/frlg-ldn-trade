---
title: What the gift link can still carry
parent: Mystery Gift
nav_order: 7
---

# What the Mystery Gift link can still carry

A survey of the FireRed/LeafGreen Mystery Gift session read off the decompilation: what the link is
capable of, what this project has sent, and what is left. Everything here is a decomp fact unless it
is marked otherwise.

## The three execution primitives

The client script the host pushes has 22 instructions [`include/mystery_gift_client.h:18`]. Three of
them execute something on the console, and all three are now proven on retail hardware.

| Instruction | What the console does | Where |
|---|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) | stores a **field script**; it runs on the next NPC interaction | every gift we ship - [Composing gifts](mystery_gift_composer.md) |
| `CLI_RUN_MEVENT_SCRIPT` (15) | runs a **Mystery Event bytecode script**, a second VM with its own 17-opcode table [`data/mystery_event_script_cmd_table.s`] | [The Mystery Event VM](mystery_event.md) |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)` - up to 1024 bytes of our own ARM executed with both save-block pointers [`mystery_gift_client.c:274`] | [Native code on the console](buffer_script.md) |

## Done

- **Wonder Cards + field scripts** - items, Pokemon, eggs, sprites, legendary battles, stamp
  rallies. [Composing gifts](mystery_gift_composer.md).
- **The visiting trainer** (`--gift visiting-trainer`, vt01) - a 188-byte
  `BattleTowerEReaderTrainer` as ident 26, battled in the house on Seven Island.
  [Console protocol notes](joiner_protocol_notes.md).
- **Wonder News on the Friend path** (`--news`, wn01) - the whole second column of the console's
  menu, and the only gift path where the console answers us. [Wonder News](wonder_news.md).
- **The Mystery Event VM, every opcode** (mev01-mev17). The last three ran in one card and all three
  effects were read back off the console at bs61; see below.
- **Native code** (`--buffer-script`, bs01 onward) - the console's memory read and written, its ROM
  mapped, ROM functions called with up to eight arguments, and a Pokemon built by the console's own
  `CreateMon` landing in the player's party. [Native code on the console](buffer_script.md).
- **The questionnaire as a password gate** (`--questionnaire`, mev04 refused and mev06 delivered).
  [The Mystery Event VM](mystery_event.md).

## Closed - do not re-open

- **Mystery Gift → Wonder Cards → Wireless Communication.** Blocked at the serial-number gate: the
  Switch's LDN bridge synthesizes `serialNo == 0x0002` and nothing in the advertisement changes it,
  so `Rfu_GetWonderDistributorPlayerData` zeroes our candidate before any other gate runs. 21
  controlled advertisements, three stages, Friend positive control listed every time. Full record in
  [JoySpot discovery](joyspot_discovery_findings.md). This also puts the 4x "big" Wonder News reward
  out of reach - that reward is exactly the one keyed to a non-Friend source.
- **The e-Reader itself** (Trainer Tower sets, `CEReaderTool_SaveTrainerTower`). `ereader_screen.c`
  opens `gLinkType = LINKTYPE_EREADER_FRLG` over the GBA **serial** link, not the wireless adapter.
  Not an LDN surface.
- **The Aurora and Mystic Tickets.** Real distribution scripts exist verbatim in
  `data/mystery_event_msg.s:200`, but the Switch release grants both tickets and both
  `FLAG_RECEIVED_*` flags on the first Hall of Fame entry [`post_battle_event_funcs.c:52`, inside
  `#if REVISION >= 0xA`]. On a completed save every guard in the script trips and it is a no-op. The
  Old Sea Map is Emerald-only (`sReceivedGiftFlags` comment, `mystery_gift.c:30`).
- **`MEScrCmd_setrecordmixinggift` and `MEScrCmd_enableresetrtc`** - both call `SetIncompatible` in
  FRLG [`mystery_event_script.c:227`, `:291`]. Dead opcodes.

## The Mystery Event opcode table, exercised

mev17 ran the last three untried opcodes in one card:

    addrareword 0; setstatus 41; addtrainer <188 bytes>; setstatus 42; setenigmaberry <28 bytes>; end

One status comes back and `setstatus` writes the same field every opcode writes (`ctx->data[2]`), so
the order is the experiment: markers after each opcode, and `setenigmaberry` last because its own
status separates success (2) from a berry that would not validate (1). The console answered **2**.
Two of the three effects are invisible in game by design, which is why bs61 read them back rather
than assuming them:

- **`addtrainer`** - RED was waiting in the house on Seven Island. Visible in game, no dump needed.
- **`addrareword`** - `gSaveBlock1Ptr->additionalPhrases` (SaveBlock1 + 0x2F10) read back `01`, bit 0
  set, which is the id the card sent. Nothing changes on screen: the bit makes one more word
  *selectable* in the Easy Chat editor, it does not rewrite a phrase the player already set.
- **`setenigmaberry`** - `gSaveBlock1Ptr->enigmaBerry` (+0x30EC) read back the name the card sent
  where it had held `ENIGMA`, with maxYield 2 and stageDuration 24, and a checksum of 0x9DB where it had been
  0x9B9, recomputed by `SetEnigmaBerry` itself. There is nothing to see in the Berry Pouch: the
  record defines what the Enigma Berry *is*, and the player still has no such item.
  `VAR_ENIGMA_BERRY_AVAILABLE`, which the opcode sets, is read nowhere else in FRLG; the record is
  only consulted in battle and by `GetBerryInfo`.

The two ROM description pointers in `struct Berry2` were read off the cartridge first (bs59) and sent
back unchanged. They live in the save for ever and the Berry Pouch dereferences them to print the
description, so an invented pointer would render garbage on every future look at the berry.

Two limits worth recording:

- `setenigmaberry` cannot set the item effect. The `itemEffect`/`holdEffect` tail sits at offset
  0x516 of `struct ReceivedEnigmaBerry`, past the console's 1024-byte buffer.
- `giveribbon` runs, but FRLG has no ribbon UI, so it is invisible on this console; the effect only
  appears after a transfer.

## Open

### Event mons that look like event mons

The official Surf Pichu script pairs `giveegg` with `setmonmodernfatefulencounter` (opcode `0xCD`),
`setmonmetlocation` (`0xD2`, with the fateful-encounter constant from the generated
`region_map_sections.h`) and `setmonmove` [`data/mystery_event_msg.s:69`]. Our composer emits
`giveegg` and `setmonmove` but neither of the first two, so nothing we have sent is flagged as a
fateful encounter. Two opcodes and a composer action.

### `initramscript` in the composer

Proven on hardware (mev03, mev15 onward) and reachable through `--gift mystery-event-npc` and the
RNG hunts, but `gift_composer` has no action for it: a card that wants an NPC-bound script has to
assemble the Mystery Event by hand. Note the trap that governs it - a Wonder Card and an NPC-bound
script are mutually exclusive.

### The player's own data, carried and ignored

`MysteryGiftLinkGameData` brings the player's Easy Chat profile and their Wonder Card stats
(`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`) on every session. The host logs
them; nothing reads them.

### The smaller official scripts

Verbatim in `data/mystery_event_msg.s`, none recreated:

- **Altering Cave** - `addvar VAR_ALTERING_CAVE_WILD_SET, 1` rotates the cave's wild set, read at
  `wild_encounter.c:192`; ten sets exist.
- **Battle Count Card** - a card that tracks wins, losses and trades against other holders of the
  same card, with a prize at three wins. Needs `MysteryGift_TryEnableStatsByFlagId`, which only arms
  the counters while the console holds exactly that flag id [`mystery_gift.c`].
