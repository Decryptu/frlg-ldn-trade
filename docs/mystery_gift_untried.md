---
title: What the gift link can still carry
nav_order: 12
---

# What the Mystery Gift link can still carry

A survey of the FireRed/LeafGreen Mystery Gift session read off the decompilation, kept as a working
list: what the link is capable of, what this project has actually sent, and what is left. Everything
here is a decomp fact unless it is marked otherwise; nothing on the open list has been on the air.

Read with [Console protocol notes](joiner_protocol_notes.md), which holds the per-finding detail and
the hardware runs.

## The three execution primitives

The client script the host pushes has 22 instructions [`include/mystery_gift_client.h:18`]. Three of
them execute something on the console, and we use one:

| Instruction | What the console does | Sent? |
|---|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) | stores a **field script**; it runs on the next NPC interaction | every gift we ship |
| `CLI_RUN_MEVENT_SCRIPT` (15) | runs a **Mystery Event bytecode script** — a second VM with its own 17-opcode table [`data/mystery_event_script_cmd_table.s`] | assembler and gift path built, session 24; see [The Mystery Event VM](mystery_event.md) |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)` — up to 1024 bytes of our own ARM/THUMB executed with both save-block pointers [`mystery_gift_client.c:274`] | never |

## Done

- **Wonder Cards + field scripts** — items, Pokemon, eggs, sprites, legendary battles, stamp rallies.
  See [Composing gifts](mystery_gift_composer.md).
- **The visiting trainer** (`--gift visiting-trainer`, session 22, hardware run `vt01`) — a 188-byte
  `BattleTowerEReaderTrainer` as ident 26, battled in the house on Seven Island. Detail in the
  protocol notes.

- **Wonder News on the Friend path** (`--news`, session 23, hardware run `wn01`) — the whole second
  column of the console's menu: `ACTIVITY_WONDER_NEWS` in the advertisement,
  `SCRIPT_SEND_WONDER_NEWS`, and the `MG_LINKID_RESPONSE` the console sends back to say whether it
  kept the news — the only gift path where the console answers us. Delivered to a French FireRed
  first try; the news displayed correctly and the man in Cerulean City handed over the berry. Full
  write-up in [Wonder News](wonder_news.md).

## Closed — do not re-open

- **Mystery Gift → Wonder Cards → Wireless Communication.** Blocked at the serial-number gate: the
  Switch's LDN bridge synthesizes `serialNo == 0x0002` and nothing in the advertisement changes it,
  so `Rfu_GetWonderDistributorPlayerData` zeroes our candidate before any other gate runs. 21
  controlled advertisements, three stages, Friend positive control listed every time. Full record in
  [JoySpot discovery](joyspot_discovery_findings.md). This also puts the 4x "big" Wonder News reward
  out of reach — that reward is exactly the one keyed to a non-Friend source.
- **The e-Reader itself** (Trainer Tower sets, `CEReaderTool_SaveTrainerTower`). `ereader_screen.c`
  opens `gLinkType = LINKTYPE_EREADER_FRLG` over the GBA **serial** link, not the wireless adapter.
  Not an LDN surface.
- **The Aurora and Mystic Tickets.** Real distribution scripts exist verbatim in
  `data/mystery_event_msg.s:200`, but the Switch release grants both tickets and both
  `FLAG_RECEIVED_*` flags on the first Hall of Fame entry [`post_battle_event_funcs.c:52`, inside
  `#if REVISION >= 0xA`]. On a completed save every guard in the script trips and it is a no-op. The
  Old Sea Map is Emerald-only (`sReceivedGiftFlags` comment, `mystery_gift.c:30`).
- **`MEScrCmd_setrecordmixinggift` and `MEScrCmd_enableresetrtc`** — both call `SetIncompatible` in
  FRLG [`mystery_event_script.c:227`, `:291`]. Dead opcodes.

## Open, roughly in order of value

### 1. The Mystery Event VM — built, awaiting its first hardware run

Full write-up in [The Mystery Event VM](mystery_event.md). `frlgsim/mystery_event.py` assembles all
17 commands, `mg_script`/`mg_server` carry them, and `--gift mystery-event-probe` is the first script
on the air. What is still open is what each opcode does on the console:

- `setenigmaberry` — the 28-byte `Berry2` (name, description pointers, size, firmness, flavours,
  growth data) lands; the `itemEffect`/`holdEffect` tail sits at offset 0x516 of
  `struct ReceivedEnigmaBerry`, past the console's 1024-byte buffer, so it cannot be set from this
  link. Note the player still needs the item itself.
- `givenationaldex` — `EnableNationalPokedex()`. In the probe script.
- `giveribbon` — a gift ribbon onto every non-egg party mon. FRLG has no ribbon UI, so it is
  invisible on this console; the effect only appears after a transfer.
- `addrareword` — unlocks an Easy Chat rare word.
- `givepokemon` — the MEvent version: a whole `struct Pokemon` **plus attached Mail**, and it sets
  the seen and caught dex flags itself [`mystery_event_script.c:234`]. Status 3 back means the party
  was full; status 2 means it landed.
- `addtrainer` — the same visiting trainer we now send, by another route.
- `initramscript` — a delivery script bound to **any** map group, map and object, not just the
  Mystery Gift delivery man. Not yet built into the composer.

Two findings came out of building it, both in the write-up. `checkcompat` is optional, which removes
the unknown French `LANGUAGE_MASK` and makes every pointer operand a plain offset into our own
buffer. And `CLI_RUN_MEVENT_SCRIPT` + `CLI_LOAD_TOSS_RESPONSE` + `CLI_SEND_LOADED` is a **return
channel**: `MEventScript_Run` writes the script's status into `client->param`, which is exactly what
`CLI_LOAD_TOSS_RESPONSE` ships back. The console can now report a u32 of our choosing.

### 2. `CLI_RUN_BUFFER_SCRIPT`

Arbitrary GBA code, 1024 bytes, called with pointers to both save blocks, returning 1 to continue.
The console reports `CLI_MSG_BUFFER_SUCCESS` or `CLI_MSG_BUFFER_FAILURE` from our own return value.
This is the mechanism the Berry Glitch fix distributions used. It needs a GBA toolchain and a
position-independent entry point; everything else is already in place.

### 3. The questionnaire — an input channel from the player

The player enters two Easy Chat words at a Poke Mart questionnaire tile; they are stored in
`gSaveBlock1Ptr->mysteryGift.questionnaireWords` and travel to us inside `MysteryGiftLinkGameData`,
where `SVR_CHECK_QUESTIONNAIRE` branches the server script on them
[`MysteryGift_DoesQuestionnaireMatch`, `mystery_gift.c:422`]. That is a password gate: a different
phrase can select a different gift. The official Visiting Trainer card used "GIVE ME AWESOME
TRAINER". Our parser already reads the field (`mg_script.LinkGameData.questionnaire_words`); nothing
uses it. The same struct also carries the player's Easy Chat profile and their Wonder Card stats
(`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`), all currently ignored.

### 4. Event mons that look like event mons

The official Surf Pichu script pairs `giveegg` with `setmonmodernfatefulencounter` (opcode `0xCD`),
`setmonmetlocation` (`0xD2`, with the fateful-encounter constant from the generated
`region_map_sections.h`) and `setmonmove` [`data/mystery_event_msg.s:69`]. Our composer emits
`giveegg` and `setmonmove` but neither of the first two, so nothing we have ever sent is flagged as
a fateful encounter. Two opcodes and a composer action.

### 5. The smaller official scripts

Also verbatim in `data/mystery_event_msg.s`, none recreated:

- **Altering Cave** — `addvar VAR_ALTERING_CAVE_WILD_SET, 1` rotates the cave's wild set, read at
  `wild_encounter.c:192`; ten sets exist.
- **Battle Count Card** — a card that tracks wins, losses and trades against other holders of the
  same card, with a prize at three wins. Needs `MysteryGift_TryEnableStatsByFlagId`, which only arms
  the counters while the console holds exactly that flag id [`mystery_gift.c`].
