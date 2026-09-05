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

### Event mons that look like event mons - mev24, bs73

`GivePokemon(..., fateful_encounter=True)` and the same on `GiveEgg` emit the pair the official Surf
Pichu script emits: `setmonmodernfatefulencounter` (`0xCD`) and `setmonmetlocation` (`0xD2`,
`METLOC_FATEFUL_ENCOUNTER` = 0xFF) [decomp:data/mystery_event_msg.s:71]. Opt-in, so every card built
before it is byte-identical.

**The slot is the whole difficulty.** `ScrCmd_setmonmodernfatefulencounter` does NOT bounds-check its
index - a plain `SetMonData(&gPlayerParty[VarGet(...)], ...)` [decomp:src/scrcmd.c:2239] - unlike
`setmonmove`, whose helper clamps anything above PARTY_SIZE to the last mon
[ScriptSetMonMoveSlot, src/script_pokemon_util.c:144]. So the composer's `LAST_PARTY_MON_INDEX` of 7
must not reach it. The real index is the party count read BEFORE the give, which is what the official
script reads with `specialvar ... CalculatePlayerPartyCount`, and the full-party guard is what holds
it inside 0..5: a party of 6 jumps to the failure label, so a mon sent to the PC is never marked.

mev24 sent the Celebi card to a party of three. The summary screen read *"Rencontré dans un
evenement special au N.50"* - but that string is driven by the met LOCATION alone
[src/pokemon_summary_screen.c:2665], and the two conditions are ORed at `:2799`, so the screen cannot
tell the bit from the location. bs73 dumped all 600 bytes of `gPlayerParty` and decoded them:

    slot 0: DRAGONITE lv77  metLocation=0x5E  modernFatefulEncounter=0
    slot 1: CHANSEY   lv26  metLocation=0x88  modernFatefulEncounter=0
    slot 2: CHANSEY   lv26  metLocation=0x88  modernFatefulEncounter=0
    slot 3: CELEBI    lv50  metLocation=0xFF  modernFatefulEncounter=1

Slot 3 is exactly the party count before the give, the three mons the script never touched carry the
bit clear, and `0xCD` is confirmed on its own rather than through the screen. `mon.decode_mon` grew
the Misc substruct to read it: `modernFatefulEncounter` is BIT 31 of the ribbon word at Misc+0x08,
not a byte of its own [decomp:include/pokemon.h:40-82].

### `initramscript` in the composer

`gift_composer.build_bound_script(actions)` compiles composer actions into the standalone field
script `initramscript` binds, and `build_mevent_npc_script(actions=...)` takes them directly. Until
now a bound script could only be built out of Messages, so an NPC could talk and nothing else; it is
the same bytecode in the same interpreter out of the same `gSaveBlock1Ptr->ramScript.data.script`, so
giving an item, giving a mon, showing a sprite and starting a battle all work there.

**What is deliberately absent is the stage cursor and the receipt flag.** A delivery plan is
resumable because the delivery man can be talked to again part-way through and must not repeat what
he already gave. A bound script has no such contract - it ends in `end` rather than `endram`, the
binding survives, and the player is meant to be able to run the whole thing again. Anything that
must happen only once needs its own flag, written as an explicit `SetVar` or a condition, rather
than inheriting one by accident.

The trap that governs it is unchanged: a Wonder Card and an NPC-bound script share one RAM script
slot, so installing this takes the card's slot and the console then reports it holds no card. Any
ordinary card sent afterwards takes the slot back - which is also how mev23's Mewtwo binding was
reverted.

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

### The player's own data: kept now, and only useful as a difference

`MysteryGiftLinkGameData` brings the player's Easy Chat profile and their Wonder Card stats
(`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`) on every session, free, whether
or not anything reads them [`src/mystery_gift.c:361`].

`--game-data-log PATH` on `bin/frlgmg_host.py` appends one record per session to a jsonl ledger
(`frlgsim/game_data_log.py`), and the host prints what moved since the last session of that same
console. `tools/game_data_read.py PATH` reads the ledger back; `--session N` re-parses one session's
raw bytes, so a question asked later costs no run.

Why the ledger rather than the log line: **a counter is only evidence as a difference**. "3 battles
won" is a number. "3, where the session before said 2, on the same card flag id" is the observation
that the console maintains the counters a Battle Count Card is built on - and no single session can
show it. The ledger reports a counter that moved across a card change with the change beside it, so
it cannot be read as the first thing.

The word ids are the other half. Anything the player typed arrives as a slot id, and the ledger
names every id `easychat_french` has never seen rendered: each one is a single question to the
player and then ground truth for every card composed afterwards
[The French Easy Chat vocabulary](easy_chat_french.md).

UNKNOWN, and what the ledger is for: whether the counters move at all on this build. Nothing has
been observed changing yet.

### The smaller official scripts

Verbatim in `data/mystery_event_msg.s`, one recreated (Altering Cave, below):

- **Battle Count Card** - a card that tracks wins, losses and trades against other holders of the
  same card, with a prize at three wins. Needs `MysteryGift_TryEnableStatsByFlagId`, which only arms
  the counters while the console holds exactly that flag id [`mystery_gift.c`]. The counters it
  would be built on are the ones the ledger above now watches.

### Altering Cave - sent and proven, bs74/fr42/bs75

`--gift altering-cave` (flag id 1004) is the official script ported command for command
[`data/mystery_event_msg.s:325`]: `addvar VAR_ALTERING_CAVE_WILD_SET, 1`, a wrap, and a message.
It is repeatable, because the script ends with `end` and not `endram`, so each talk to the delivery
man advances the cave one set.

Two decomp facts shape it. The encounter reader does `i += alteringCaveId` against
NUM_ALTERING_CAVE_TABLES = 9 consecutive wild headers and clamps anything at or above 9 to 0
[`src/wild_encounter.c:192`], while **the official script wraps at 10, not at 9**
[`:328`] - so one step of a full cycle is an id the reader turns back into table 0. Ported as
written rather than corrected: the card is what the event was.

The run does not need Six Island. `VAR_ALTERING_CAVE_WILD_SET` (0x4024) lives in
`SaveBlock1.vars[0x24]`, at **SaveBlock1 + 0x1048** (`buffer_script.sav1_var_offset`), so the
evidence is a save dump before and after:

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x1048 --dump-size 2

**FACT, three runs.** bs74 read the var at **0**. fr42 sent the card, the player accepted it over
the one the console held (flagId 1003 -> 1004) and talked to the delivery man three times; he said
"Thank you for using the MYSTERY GIFT System. There are rumors of rare POKEMON in ALTERING CAVE."
all three times, which is the binding surviving `end`. bs75 read the var back at **3** - one per
talk, nothing else in the sixteen bytes moved:

    bs74  0x1048: 0000 f401 0d00 cb30 ...
    bs75  0x1048: 0300 f401 0d00 cb30 ...

So the whole event works on this build: the card installs, the script is repeatable, `addvar`
writes the player's save, and the count is exactly the number of conversations.

UNKNOWN: whether the cave's wild set follows the var on screen. That needs a player who can reach
Outcast Island (Six Island), and it is the game reading the var, not the event writing it.
