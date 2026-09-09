---
title: Mystery Gift
parent: FireRed and LeafGreen
nav_order: 2
---

# Mystery Gift

The Mystery Gift menu is the widest door into a retail FireRed/LeafGreen save, and unlike trading it
needs no Pokemon Center. A console sitting on the Wonder Cards screen accepts a Wonder Card, a
delivery script, a Wonder News item, a visiting trainer for the Battle Tower, and a Pokemon straight
into the party.

This page covers the session and what can be sent over it. What the link can *execute* — the Mystery
Event bytecode VM and native ARM code — is on [Code on the console](frlg_rom.md).

## The session

**The console does not decide the flow.** Its Mystery Gift client boots with a two-instruction script
[mystery_gift_scripts.c:15]:

```c
{CLI_RECV, MG_LINKID_CLIENT_SCRIPT}
{CLI_COPY_RECV}
```

It connects, asks for instructions, and then executes whatever `MysteryGiftClientCmd` array it is sent
[mystery_gift_client.c:87]. That is why a Linux host can drive flows a real cartridge cannot: FireRed
carries two server scripts in ROM, but the client understands the whole opcode set.

    console joins  ->  SEND_PLAYER_IDS  ->  LinkPlayer block exchange  ->  one standby barrier
                                                                              |
      server -> CLIENT_SCRIPT (sClientScript_SendGameData, 32 B)
      client -> GAME_DATA     (MysteryGiftLinkGameData, 96 B)   -- validated, card flag compared
      server -> CLIENT_SCRIPT (sClientScript_SaveCard, 48 B)
      server -> CARD          (struct WonderCard, 332 B)
      server -> RAM_SCRIPT    (1024 B: the delivery bytecode, zero-padded)
      client -> READY_END     (1024 B)
                                                                              |
                                              close-link handshake  ->  disconnect

The LDN/Pia/Reliable/RFU stack below is shared with the trade host. The LinkPlayer ordering is
Mystery-Gift-specific: the host issues one block request, waits for the console's valid block, then
sends its own block and waits for the standby barrier.

### Two framing rules that are easy to get wrong

**Size 0 means 1024, not empty.** `MysteryGiftLink_InitSend` [mystery_gift_link.c:55] expands a zero
size to `MG_LINK_BUFFER_SIZE`. `SVR_COPY_SAVED_RAM_SCRIPT` never sets `ramScriptSize`
[mystery_gift_server.c:275], so the RAM script goes out as a full 1024-byte message, as does
`CLI_SEND_READY_END`. The CRC covers the padded buffer, not the meaningful prefix.

**Block pacing has no acknowledgement.** `SEND_BLOCK_INIT` is silently ignored unless the receiver's
slot is `RECV_STATE_READY` [link_rfu_2.c:1146], and the slot only returns to READY when the console's
`MGL_ResetReceived` runs. Nothing on the wire reports that, and the sender's own flow control does not
help: `MGL_Send` waits on `MGL_HasReceived(sendPlayerId)`, which for the parent is its own slot 0, and
`Rfu_SetBlockReceivedFlag` [link_rfu_2.c:1044] sets the parent's own flag immediately — the four-VBlank
`numBlocksReceived` countdown [link_rfu_2.c:1220] applies only to blocks arriving *from* a child. A
native parent paces blocks about a frame apart and relies on the console keeping up.
`MysteryGiftTiming.inter_block_gap_frames` (36) buys far more: measured against the console model, the
console may take 13 frames to consume a block with nothing dropped and 16 before the transfer dies.
Losing that race leaves the console waiting forever for a block that was dropped without an error.

The mirror rule that governs every stall while the console is sending is on
[The link protocol](frlg_link.md#row-one-of-the-parents-table-is-the-consoles-own-command-mirrored-back).

### Modules

| file | role |
|---|---|
| `pokeldn/frlg/gift/mg_link.py` | MysteryGiftLink framing: 6-byte `{ident, crc, size}` header block + ≤252-byte chunks |
| `pokeldn/frlg/gift/mg_script.py` | client-script assembler, the decomp's canned scripts, `MysteryGiftLinkGameData` reader |
| `pokeldn/frlg/gift/mg_server.py` | server-script interpreter (`SVR_*`) |
| `pokeldn/frlg/gift/host_mystery_gift.py` | the leader activity engine: `tick()` → parent gSendCmd, `feed_child_slot()` ← child row |
| `pokeldn/frlg/gift/host_mg_app.py` | Mystery Gift application hooks over the activity-neutral host runtime |
| `pokeldn/frlg/gift/wonder_card.py` | byte-exact Celebi and legendary-beast card/RAM-script builders |
| `pokeldn/frlg/gift/stamp_rally.py` | Stamp Rally card, stamps, activation wrappers, delivery script |
| `pokeldn/frlg/gift/gift_composer.py` | immutable action definitions, cursor-state validation, RAM-script compiler |
| `pokeldn/frlg/gift/gift_registry.py` | the catalog |
| `pokeldn/frlg/gift/gift_to_bin.py` | paired `.bin` exporter for external Gen-3 Mystery Gift tools |
| `pokeldn/frlg/save/save_inject.py` | save injection with card, RAM-script and sector checksums |
| `bin/frlg_mg_host.py` | the CLI |

## Running it

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py --live --gift beast-cutscene --flag-id 1005
    (them) join the host when it appears; YES on the replace-card prompt if one shows

Adapter profiles and flags are on [Hardware and setup](hardware.md). The checked-in `config/host.toml`
is the TP-Link Archer T3U profile, so the command above needs no Wi-Fi flags; the ALFA needs
`--phy phyN --skip-encryption --no-accept-decrypted-ccmp`.

Have the player back out of the search screen between runs or the console may join a stale SSID. After
two or three mixed failures on one console, restart the game.

Offline first, every time:

    ./.venv/bin/python scratchpad/mg_client_harness.py --gift mystery-event-probe --flag-id 1009
    ./.venv/bin/python -m pytest tests/test_mystery_gift_flow.py -q

`tests/test_mystery_gift_flow.py` models the RFU block-receive gate, `MGL_Receive`, and
one-command-per-frame client-script execution. `tests/test_mystery_gift_end_to_end.py` adds an impaired
Reliable/RFU path and a native-shaped ID16/ID17 framing fixture.

## What the link can carry

The client script has 22 instructions [include/mystery_gift_client.h:18]. Three of them execute
something on the console, and all three are proven on retail hardware:

| instruction | what the console does |
|---|---|
| `CLI_SAVE_RAM_SCRIPT` (17) | stores a **field script**; it runs on the next NPC interaction |
| `CLI_RUN_MEVENT_SCRIPT` (15) | runs a **Mystery Event bytecode script**, a second VM with its own 17-opcode table |
| `CLI_RUN_BUFFER_SCRIPT` (21) | `func = (void *)gDecompressionBuffer; func(&param, gSaveBlock2Ptr, gSaveBlock1Ptr)` — up to 1024 bytes of ARM executed with both save-block pointers |

The last two are on [Code on the console](frlg_rom.md).

## The one RAM script slot

**A Wonder Card and an NPC-bound script are mutually exclusive.** There is one RAM script slot, and the
card's validity depends on what is in it:

```c
bool32 ValidateSavedWonderCard(void)
{
    if (cardCrc != CALC_CRC(card)) return FALSE;
    if (!ValidateWonderCard(&card)) return FALSE;
    if (!ValidateRamScript()) return FALSE;      // MAP_UNDEFINED / object 0xFF only
    return TRUE;
}
```

[mystery_gift.c:186]. `CLI_SAVE_RAM_SCRIPT` calls `InitRamScript_NoObjectEvent`, giving MAP_UNDEFINED
and object 0xFF [script.c:578], which is what `ValidateRamScript` accepts; the Mystery Event VM's
`initramscript` writes real coordinates instead, and the card is then still in the save, byte for byte,
with a good CRC — but the menu will not show it and `MysteryGift_LoadLinkGameData` reports `flagId` 0
[mystery_gift.c:349], so the next session sees `HAS_NO_CARD`.

It is fully reversible: the next Wonder Card takes the slot back and the card returns. A *buffer*
script does not take the slot back, because it sends no card.

## The gift catalogue

`bin/frlg_mg_host.py --gift NAME`; `--help` lists them with their flag ids. Wonder Card flag ids are
1000..1019, and only the card the console currently holds matters
(`MysteryGift_CompareCardFlags`: the same id means "already has this card").

| gift | what it does |
|---|---|
| `beast-cutscene-share` | the repeatable legendary-beast cutscene; the default demo card |
| `celebi` | the composed level-50 Celebi card |
| `porygon-tm-gift` | a Porygon card, a Clefairy scene, TM29 Psychic then TM46 Thief |
| `solrock-stamp` / `lunatone-stamp` | the two halves of one Stamp Rally card |
| `altering-cave` | the official Altering Cave event, ported |
| `battle-count-card` | the official Battle Count Card |
| `visiting-trainer` | a Battle Tower trainer as ident 26 (FireRed only) |
| `mystery-event-probe` | `givenationaldex; setstatus 42; checksum` — the VM's own self-test |
| `mystery-event-celebi` | `givepokemon`: a Lv30 Celebi holding mail, straight into the party |
| `mystery-event-npc` | `initramscript`: binds a field script to the Pallet Town fat man |
| `rng-seed-reader`, `rng-rate-probe`, `rng-shiny-hunt`, `rng-mon-hunt`, `rng-mon-hunt-both`, `rng-mon-hunt-log` | see [the RNG](frlg_rng.md) |

The evidence line for a Mystery Event gift is `Mystery Event script status: N`. A console that already
holds the card takes the event alone with no card and no prompt, so those runs are repeatable.

### The legendary beast

A deliveryman cutscene that gives the Lansat Berry and the Liechi Berry, then a Master Ball, then
starts a wild legendary beast battle at level 65. The receiving save's starter chooses the encounter:

| starter | beast |
|---|---|
| Bulbasaur | Suicune |
| Squirtle | Entei |
| Charmander | Raikou |

Conditional stages show the matching beast, a shared stage gives the Master Ball, and a conditional
terminal battle stage starts the encounter. The saved script remains available, so the event can be
triggered again.

### Porygon TM gift

A Wonder Card with Porygon as its icon, a Clefairy overworld sprite three tiles to the player's right
facing west, TM29 Psychic followed by TM46 Thief, and separate delivery checkpoints so retrying Thief
cannot duplicate Psychic. The card defaults to flag id 1007, so the viewer shows `7` in its top-right
number (`flag_id % 100`).

### The Stamp Rally

Two events share one `SUN AND MOON RALLY` card with a Claydol icon, two stamp slots, a displayed card
number of `6` and default flag id 1006. Receive them in either order.

| state | meaning |
|---|---|
| `VAR_MYSTERY_GIFT_1` | Celebi completion cursor |
| `VAR_MYSTERY_GIFT_2 = 0/1/2` | Solrock absent / active / received |
| `VAR_MYSTERY_GIFT_3 = 0/1/2` | Lunatone absent / active / received |
| `FLAG_MYSTERY_GIFT_DONE` | rally completion |
| card receipt flag | synchronized when Celebi succeeds |

The deliveryman gives Solrock at level 30 for its stamp, Lunatone at level 30 for its stamp, and Celebi
at level 50 once both are received. All use standard `givemon`, so they receive the player's OT/TID,
default level-up moves, no held item and a normal random personality. A Pokemon sent to either the party
or the PC counts as success; if both are full nothing advances and the player can make room and retry.
If both stamps are pending, all three Pokemon are delivered in one visit.

Host-side decision procedure:

```text
matching =
    saved flag ID == distribution flag ID
    and max stamps == 2
    and metadata icon species == CLAYDOL

if no card:                install shared card + delivery script + selected stamp, run activation
else if not matching:      offer the toss prompt; on accept, install as above
else if stamp species or ID already exists:   HAS_STAMP, no activation
else if neither slot empty:                   NO_ROOM_STAMPS, no activation
else:                      save the stamp, run activation, STAMP_RECEIVED
```

The activation data is a Mystery Event wrapper containing `runscript` followed by an embedded ordinary
field script, sent only after the server has established that the stamp is new and that the metadata
contains a genuinely empty slot.

Rally slot entries are live-host-only: `gift_to_bin.py` and `save_inject.py` expose ordinary static
gifts, and a stamp is a stateful protocol exchange rather than a static card/script pair.

Related constraint, for any future stamp relay: `IsStampInMetadata` [mystery_gift.c:272] rejects a stamp
whose id **or** species collides with an existing one, so every station in a relay needs both unique.
Maximum 7. `CLI_SAVE_STAMP` writes only `cardMetadata.stampData` [mystery_gift.c:307] and never touches
the card, so a stamp-only client script adds stamps without the card wipe `CLI_SAVE_CARD` causes.

### Altering Cave

The official script ported command for command [data/mystery_event_msg.s:325]:
`addvar VAR_ALTERING_CAVE_WILD_SET, 1`, a wrap, and a message. It is repeatable because the script ends
with `end` rather than `endram`, so each talk advances the cave one set.

Two decomp facts shape it. The encounter reader does `i += alteringCaveId` against
`NUM_ALTERING_CAVE_TABLES = 9` consecutive wild headers and clamps anything at or above 9 to 0
[wild_encounter.c:192], while **the official script wraps at 10, not at 9** [:328] — so one step of a
full cycle is an id the reader turns back into table 0. It is ported as written.

`VAR_ALTERING_CAVE_WILD_SET` (0x4024) lives in `SaveBlock1.vars[0x24]`, at SaveBlock1 + 0x1048, so a
save dump reads it before and after:

    --buffer-script save-dump --dump-block sav1 --dump-offset 0x1048 --dump-size 2

Measured: 0 before the card, 3 after three conversations, with nothing else in the sixteen bytes moved.
The game's half is proven too — with the var at 3 the first encounter in GROTTE METAMO on Six Island was
a Houndour at level 16, and table 3 is `sSixIslandAlteringCave_4_FireRed`, all Houndour, whose first slot
is exactly level 16 [src/data/wild_encounters.json]. Houndour appears nowhere else in FireRed.

| var | species | | var | species |
|---|---|---|---|---|
| 0 | Zubat | | 5 | Aipom |
| 1 | Mareep | | 6 | Shuckle |
| 2 | Pineco | | 7 | Stantler |
| 3 | Houndour | | 8 | Smeargle |
| 4 | Teddiursa | | | |

### The Battle Count Card

`MysteryEventScript_BattleCard` [data/mystery_event_msg.s:162]: set `gSpecialVar_Result` to
`GET_CARD_BATTLES_WON`, read the counter back through `GetMysteryGiftCardStat` (special 390), and hand
over a POTION at exactly three. Ported with one deliberate change: the official card gates its prize on
`FLAG_MYSTERY_GIFT_DONE`, which the composer sets when a non-repeatable gift finishes, so it would stop
talking before the count reached three. This one is repeatable with a prize marker var of its own.

**The card does not arm the counters; the partner's trainer card does.** `Task_ExchangeCards` hands
`MysteryGift_TryEnableStatsByFlagId` the u16 that follows the 96-byte trainer card in the
`BLOCK_REQ_SIZE_100` buffer — the flag id the *partner* sent — and arms only if it equals the card the
console is holding [union_room.c:1777]. That exchange runs on the way into the trade centre and the
battle colosseum, both of which this project's host drives.
`frlg_trade_host.py --card-flag-id N` sets it.

Once armed:

| what increments | where | the rule |
|---|---|---|
| `numTrades` | a completed trade [trade_scene.c:2609] | a trainer id the card has not counted |
| `battlesWon` / `battlesLost` | the end of a **cable club** battle [cable_club.c:792] | the same, 5 ids remembered per stat |

`IncrementCardStatForNewTrainer` [mystery_gift.c:630] counts a trainer id once, so three wins need three
different host trainer ids. The in-room Union Room battle returns through `CB2_ReturnToField` and
increments nothing; only the colosseum path does. See
[the cable-club colosseum](frlg_link.md#the-cable-club-colosseum).

The counters live at SaveBlock1 + 0x3434 (`buffer_script.SAV1_CARD_METADATA`) and are read with no CRC
check [mystery_gift.c:490], so a save dump reads them and a save write sets them:

    0x3434: 0000 0000 0000 2300     battlesWon 0, lost 0, trades 0, icon 35 (CARD_TYPE_GIFT)
    0x3434: 0000 0000 0100 2300     trades 1                       (CARD_TYPE_LINK_STAT)

**The card type is what gates the counters.** Three runs read zero with every other condition already
right: both 100-byte exchange blocks carried the correct flag id at offset 96, so the console had run
`CreateTrainerCardInBuffer(TRUE)`, read the word and armed — the card was `CARD_TYPE_GIFT`.

Two facts worth keeping from that: `sizeof(struct TrainerCard)` is **96** on this build, measured
because the console writes its own held flag id at offset 96 of the block it sends; and the trade centre
reached through the wireless club is `union_room.c`'s `Task_StartActivity` path, not `cable_club.c`'s,
because the console's block carries the flag id and only the union-room builder writes it.

### The visiting trainer

`CLI_RECV_EREADER_TRAINER` (client instruction 18, link ident `MG_LINKID_EREADER_TRAINER` = 26) memcpys
the received buffer into `gSaveBlock2Ptr->battleTower.ereaderTrainer` and calls `ValidateEReaderTrainer`
[mystery_gift_client.c:233]. The struct is 188 bytes [global.h:286]:

    0x00 u8  unk0                  0x10 u16 greeting[6]            0x34 BattleTowerPokemon party[3]
    0x01 u8  trainerClass          0x1C u16 farewellPlayerLost[6]  0xB8 u32 checksum
    0x02 u16 winStreak             0x28 u16 farewellPlayerWon[6]
    0x04 u8  name[8]
    0x0C u8  trainerId[4]

**Validation is only that the first 46 words are not all zero and that the trailing u32 is their sum**
[battle_tower.c:1354, :1384]. A struct that fails is silently cleared. Nothing about the trainer, the
party or the levels is checked.

`SevenIsland_House_Room1` gates only on that validation. `ValidateEReaderTrainer` returning 0 sets
`TRAINER_VISITING`, opens the door in the map layout and moves the old woman; she offers a 3v3, warps to
Room2, and `StartSpecialBattle` case 2 builds the enemy party with `CreateBattleTowerMon` straight from
the struct [battle_tower.c:928]. The party is healed afterwards and the scene var resets, so the battle
is repeatable. The Battle Tower's level rule and banlist live on `ShouldBattleEReaderTrainer` [:232],
which this path never calls — **the levels sent are the levels that appear.**

`CreateBattleTowerMon` applies species, held item, four moves (PP filled from the move table), level,
ppBonuses, all six EVs, all six IVs, abilityNum, otId, personality, nickname and friendship. Personality
and otId therefore fix nature, gender and shininess. The three phrases are Easy Chat words, six per
line; `farewellPlayerWon` is what the trainer says when the *player* won. The name field is eight bytes
but FRLG displays five [`CopyEReaderTrainerName5`, battle_tower.c:1343].

`CLI_MSG_TRAINER_RECEIVED` (12) is "A new TRAINER has arrived." [strings.c:1296] and
`GetClientResultMessage` marks it a success, so the console saves afterwards. No Wonder Card is required.

`--gift visiting-trainer` sends the card and its RAM script as any other gift, then the trainer as ident
26 in the same session. Three server branches, all covered by tests: no card → card + script + trainer;
the same card already held → the trainer alone with no toss prompt (a free rematch); a different card →
the usual toss prompt, then all three.

## Wonder News

The Mystery Gift menu is two axes — {Wonder Cards, Wonder News} × {Wireless Communication, Friend}.
Wonder News is the second column.

`struct WonderNews` [global.h:646] is 444 bytes and, unlike a Wonder Card, carries no identity at all:

| offset | size | field | notes |
|---|---|---|---|
| 0x000 | 2 | `id` | the only thing `ValidateWonderNews` checks: it must not be 0 [mystery_gift.c:113] |
| 0x002 | 1 | `sendType` | `SEND_TYPE_DISALLOWED` hides the console's own "Send" option [mystery_gift.c:120] |
| 0x003 | 1 | `bgType` | not validated; `WonderNews_Init` clamps `>= NUM_WONDER_BGS` to 0 [mystery_gift_show_news.c:110] |
| 0x004 | 40 | `titleText` | centred in a 224 px window |
| 0x02C | 400 | `bodyText[10][40]` | eight lines are on screen; a non-empty line past index 7 arms the scroll indicator [:346] |

No `flagId`, no `WonderCardMetadata`, no delivery RAM script, no receipt event flag. Nothing on the News
path consults `sReceivedGiftFlags`, so none of the Wonder Card flag-id bookkeeping applies.

What decides whether a console keeps news is `IsWonderNewsSameAsSaved` [mystery_gift.c:140]: a
byte-for-byte compare of the whole 444-byte struct against the news already in the save. One different
byte anywhere makes old news new again, which is what `--news-id` exists for.

Two things differ from the Wonder Card host; everything below the server script is identical.

**The advertisement's activity byte.** The News accept list holds exactly one id
[`sAcceptedActivityIds_WonderNews`, src/data/union_room.h:406], so a host advertising
`ACTIVITY_WONDER_CARD` (21) is not listed on the News screen and vice versa.
`build_wonder_news_app_data` sets 22 and changes nothing else. The `hasNews` compatibility bit is not
the gate: `HasWonderCardOrNewsByLinkGroup` [union_room.c:3777] is reached only from
`Task_ListenForWonderDistributor`, the Wireless path.

**The console answers.** `MG_LINKID_RESPONSE` (ident 19) travels client → server, and this is the only
gift path where the console says anything back. `CLI_SAVE_NEWS` loads that response with the console's
own verdict [mystery_gift_client.c:210]:

* `FALSE` — the news differed from what was held, so it was saved.
* `TRUE` — the console already held exactly these 444 bytes and kept them.

`sServerScript_SendNews` [mystery_gift_scripts.c:126] branches on it: `TRUE` ends in `SVR_MSG_HAS_NEWS`;
`FALSE` falls through to `sClientScript_NewsReceived`, and only that path makes the console save and set
its reward. `SCRIPT_SEND_WONDER_NEWS` is that script minus its leading `SVR_COPY_SAVED_NEWS`, which reads
a save block the host does not have.

Not in the script: no `SVR_CHECK_EXISTING_CARD`, no toss prompt, no `SVR_LOAD_RAM_SCRIPT`. News cannot
displace a card, and a player is never asked to throw anything away to take it.

**The reward.** Receiving news from a Friend calls `WonderNews_SetReward(WONDER_NEWS_RECV_FRIEND)`
[mystery_gift_menu.c:1367], which rolls a random berry between `ITEM_RAZZ_BERRY` and `ITEM_NOMEL_BERRY`
into `WonderNewsMetadata.berry` [wonder_news.c:21]. The man in the house in Cerulean City
(`CeruleanCity_House4`) hands it over. Up to five rewards, then the player must walk 500 steps before the
counter resets [`MAX_REWARD`, `WonderNews_IncrementStepCounter`]. The four-berry "big" reward is
`NEWS_REWARD_RECV_BIG`, which needs `WONDER_NEWS_RECV_WIRELESS`, and that path is closed.

Running it:

    ./scratchpad/run_mg_news.sh wnNN            # or: run_mg_fast.sh wnNN --news --version firered
    (them) Mystery Gift -> the SECOND menu entry (Wonder News) -> "input one?" -> Friend (Ami)
    (them) pick the host from the list

A console that already holds news goes straight to the news display instead of the input prompt; press A
there and choose Receive. Re-sending identical news is a designed no-op — the console answers `TRUE` —
so `--news-id N` changes the id and the same text lands again.

A whole session takes about 18 seconds:

    ident 16  sClientScript_SendGameData
    ident 17  MysteryGiftLinkGameData
    ident 16  sClientScript_SaveNews
    ident 23  MG_LINKID_NEWS - 444 bytes in three blocks
    ident 19  MG_LINKID_RESPONSE - FALSE: the console saved it
    ident 16  sClientScript_NewsReceived
    ident 20  READY_END                              -> SVR_MSG_NEWS_SENT

with the advertisement carrying activity 22 throughout. The Wonder Card the console was holding is
untouched: news and cards do not displace each other.

## The questionnaire as a password gate

`SVR_CHECK_QUESTIONNAIRE` compares all four Poke Mart questionnaire words, in order, exactly
[`MysteryGift_DoesQuestionnaireMatch`, mystery_gift.c:422], and puts the verdict in the server's `param`
where `SVR_GOTO_IF_EQ` can branch on it. No native server script uses it; the idea survives only in the
official Visiting Trainer card, whose phrase was "GIVE ME AWESOME TRAINER".

`mg_server.gate_on_questionnaire(script)` splices the check between the shared game-data prefix and
whatever the script does next:

    MysteryGiftServer(card, ram_script, questionnaire=phrase, denied_message="Say the words.")

or on the command line, where a word may be an English name, `species:N`, `move:N`, `GROUP/INDEX`, or a
raw id:

    bin/frlg_mg_host.py --gift ... --questionnaire species:55,FEELINGS/60,move:177,why

A console that says the wrong phrase gets the host's 64-byte message through
`CLIENT_SCRIPT_DYNAMIC_ERROR` and the session returns `SVR_MSG_NOTHING_SENT`; nothing is sent and nothing
is tossed.

**Test the refusal first.** A passing gate cannot be told apart from a gate that is not wired up.

**The phrase cannot come from the decompilation.** Four French word ids are four slots in a table the
English decomp does not have, so the phrase has to be read off a real console first. Every Mystery Gift
session ships the console's four words inside `MysteryGiftLinkGameData` [mystery_gift.c:361], and the
host logs them. One reading gave:

    questionnaire: POKEMON/55  done [FEELINGS/60]  MOVE_1/177  why [MISC/37]

for a player who had typed **AKWAKWAK FURAX AEROBLAST POURQUOI**, and settled three things:
`EC_GROUP_POKEMON` indexes by species number (AKWAKWAK is Golduck, species 55); `EC_GROUP_MOVE_1`
indexes by move id (AEROBLAST is move 177); and the English table was right about MISC/37 and wrong
about FEELINGS/60. See [the French Easy Chat vocabulary](frlg_rom_map.md#the-french-easy-chat-vocabulary).

## What the console volunteers about itself

`MysteryGiftLinkGameData` carries the player's Easy Chat profile and their Wonder Card stats
(`CARD_STAT_BATTLES_WON` / `_LOST` / `_NUM_TRADES` / `_NUM_STAMPS`) on every session, whether or not
anything reads them [mystery_gift.c:361].

`--game-data-log PATH` appends one record per session to a JSONL ledger
(`pokeldn/frlg/gift/game_data_log.py`) and the host prints what moved since the last session of that
same console. `tools/frlg/game_data_read.py PATH` reads it back; `--session N` re-parses one session's
raw bytes.

**A counter is only evidence as a difference.** "3 battles won" is a number; "3, where the session
before said 2, on the same card flag id" is the observation that the console maintains the counters a
Battle Count Card is built on, and no single session can show it. The ledger reports a counter that
moved across a card change with the change beside it.

The word ids are the other half: anything the player typed arrives as a slot id, and the ledger names
every id the French Easy Chat table has never seen rendered.

## Authoring gifts

`pokeldn.frlg.gift.gift_composer` builds Wonder Cards and deliveryman scripts from immutable Python
definitions. Every composed event is a `WonderGift`:

```python
WonderGift(
    slug="event-slug",
    card=WonderCardSpec(...),
    intro_message="The deliveryman introduces the event.",
    event=GiftSpec() or StampRallySpec(...),
    delivery=DeliveryPlan(delivery=(...shared stages...)),
    completed_message="The event is already complete.",
)
```

`GiftSpec` contains only behaviour exclusive to an ordinary gift: whether it is repeatable and whether
the received Wonder Card may be shared onward. `StampRallySpec` contains only rally orchestration: slots
and completion hooks. Card presentation, dialogue and reward stages belong to `WonderGift`.

`DeliveryPlan` always has three immutable stage sequences, and their roles depend on where the plan
appears:

- `WonderGift.delivery` uses only `delivery`; it is the reusable middle of the event.
- `StampSlot.delivery` uses only `pre_stages` and `post_stages`.
- `StampRallySpec.completion` uses only `pre_stages` and `post_stages`.

The compiler rejects stages in an unsupported section rather than ignoring them.

```python
MEWTWO_GIFT = WonderGift(
    slug="mewtwo-encounter",
    card=WonderCardSpec(
        icon_species=150,
        title="MYSTERIOUS ENCOUNTER",
        subtitle="A powerful presence",
        body=("Visit the deliveryman.",),
        footer1="pokeldn",
        default_flag_id=1008,
    ),
    intro_message="A powerful presence is waiting!",
    event=GiftSpec(shareable="once"),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message("Take this before you go."),
            GiveItem(1),  # Master Ball
        ),
        DeliveryStage(
            ShowSprite(0, RelativeToPlayer(dx=1)),
            Message("Prepare yourself!"),
            BattleLegendary(150, level=70),
        ),
    )),
    completed_message="That mysterious encounter is over.",
)
```

The compiler shows `intro_message`, resumes the top-level stages using `VAR_MYSTERY_GIFT_1`, and sets
`FLAG_MYSTERY_GIFT_DONE` plus the card receipt flag on success. A later visit shows only
`completed_message`; `GiftSpec(repeatable=True)` resets the cursor instead.

### Stages and conditions

Each `DeliveryStage` is one checkpoint. If its fallible reward fails, that stage is offered again and
successful earlier stages are skipped. **Do not put two fallible rewards (`GiveItem`, `GivePokemon`,
`GiveEgg`) in one stage.**

`GiveEgg` accepts the same optional `moves=(...)` tuple as `GivePokemon`. A move-bearing egg must fit in
the active party so the compiler can apply its moves to the new slot; when the party is full the stage
retries later instead of sending the egg to the PC.

A stage may carry `condition=...`. When the condition is false the compiler skips that stage's actions
but still advances the cursor by one, which is useful for mutually exclusive branches that must not be
re-tested after a later stage fails. Supported expressions are `VarEquals`, `FlagSet`, `Not`, `AllOf`
and `AnyOf`:

```python
DeliveryStage(
    ShowSprite(142, RelativeToPlayer(dx=1)),
    condition=VarEquals(0x4031, 0),  # VAR_STARTER_MON == Bulbasaur
)
DeliveryStage(
    BattleLegendary(243, level=65),
    condition=Not(AnyOf((VarEquals(0x4031, 0), VarEquals(0x4031, 1)))),
)
```

`RequireSpecialResult(...)` is the other shape: it calls an FRLG field special into `VAR_RESULT`,
compares that result, and shows its failure message **without advancing the stage cursor**. A false
`condition` skips a stage and advances; `RequireSpecialResult` keeps the stage pending for a later visit.

```python
DeliveryStage(
    RequireSpecialResult(SPECIAL_HAS_ALL_KANTO_MONS, 1, "Finish the KANTO POKEDEX first."),
    GivePokemon(251, level=50),
)
```

### Writing the player's save

`SetVar(variable, value)` emits `setvar` (0x16) and `AddVar(variable, value)` emits `addvar` (0x17),
both restricted to a saved var (0x4000..0x40FF) or a special var (0x8000..0x8011).

### Battles

`BattleLegendary` is the terminal legendary encounter in a saved Wonder Card RAM script. It emits
`setwildbattle`, FRLG's `special StartLegendaryBattle`, and then `end` **without** `waitstate`, which
avoids resuming a suspended RAM-script pointer after the game relocates SaveBlock memory during the
battle transition — see [a RAM script may not come back from a battle](frlg_rng.md#a-ram-script-may-not-come-back-from-a-battle).
`BattlePokemon` remains available and emits the ordinary `dowildbattle`. Both must be the final action
in their stage.

Battles are prohibited in a stamp-slot path, including the shared middle used by a rally. Conditional
battle stages are allowed as terminal alternatives.

### Sharing

`GiftSpec.shareable` maps to the Wonder Card `sendType` bits:

| value | behaviour |
|---|---|
| `"never"` | cannot be shared onward |
| `"once"` | can be shared once; the receiving game flips the card to not shareable |
| `"always"` | can continue to be shared after receipt |

### Event mons that look like event mons

`GivePokemon(..., fateful_encounter=True)`, and the same on `GiveEgg`, emit the pair the official Surf
Pichu script emits: `setmonmodernfatefulencounter` (`0xCD`) and `setmonmetlocation` (`0xD2`,
`METLOC_FATEFUL_ENCOUNTER` = 0xFF) [data/mystery_event_msg.s:71]. It is opt-in, so every card built
before it is byte-identical.

**The slot is the difficulty.** `ScrCmd_setmonmodernfatefulencounter` does not bounds-check its index —
a plain `SetMonData(&gPlayerParty[VarGet(...)], ...)` [scrcmd.c:2239] — unlike `setmonmove`, whose helper
clamps anything above `PARTY_SIZE` to the last mon [`ScriptSetMonMoveSlot`, script_pokemon_util.c:144].
So the composer's `LAST_PARTY_MON_INDEX` of 7 must not reach it. The real index is the party count read
*before* the give, which is what the official script reads with
`specialvar ... CalculatePlayerPartyCount`, and the full-party guard holds it inside 0..5: a party of 6
jumps to the failure label, so a mon sent to the PC is never marked.

The summary screen cannot confirm the bit. It reads *"Rencontré dans un evenement special au N.50"* from
the met **location** alone [pokemon_summary_screen.c:2665], and the two conditions are ORed at :2799. A
party dump settles it: `modernFatefulEncounter` is **bit 31 of the ribbon word at Misc+0x08**, not a byte
of its own [include/pokemon.h:40-82], and `mon.decode_mon` reads it.

### `initramscript` in the composer

`gift_composer.build_bound_script(actions)` compiles composer actions into the standalone field script
`initramscript` binds, and `build_mevent_npc_script(actions=...)` takes them directly. It is the same
bytecode in the same interpreter out of the same `gSaveBlock1Ptr->ramScript.data.script`, so giving an
item, giving a mon, showing a sprite and starting a battle all work there.

**The stage cursor and the receipt flag are deliberately absent.** A delivery plan is resumable because
the delivery man can be talked to again part-way through and must not repeat what he already gave. A
bound script has no such contract: it ends in `end`, the binding survives, and the player is meant to be
able to run the whole thing again. Anything that must happen only once needs its own flag, written as an
explicit `SetVar` or a condition.

### Registration and validation

```python
from pokeldn.frlg.gift.gift_registry import GIFT_REGISTRY
GIFT_REGISTRY.register_definition(MEWTWO_GIFT)
```

Ordinary gifts support the live host, the `.bin` exporter and the save injector; rally slot entries are
live-host-only. Registration validates and compiles the default flag id immediately; a runtime
`--flag-id` is validated and compiled again.

Validation covers card text and flags, immutable plan structure, action ranges, stage cursor bounds,
unique stamp data, battle placement, virtual pointers, and the 995-byte saved RAM-script limit. Errors
identify the source section:

```text
example-rally.event.slots[1].delivery.post_stages[0].actions[1]: battles are not allowed in stamp-slot delivery plans
```

## Static tools

Export the paired `.bin` files for external Gen-3 Mystery Gift tools:

```bash
./.venv/bin/python -m pokeldn.frlg.gift.gift_to_bin --gift beast-cutscene --flag-id 1005 --out-dir exported-gift
```

writes a 336-byte Wonder Card file and a 1004-byte RAM-script file with the checksums and padding
`pokemon-gen3-mysterygift-tool` expects.

Inject into a save (always keep an untouched backup; by default it writes `<save>.gift.sav`):

```bash
./.venv/bin/python -m pokeldn.frlg.save.save_inject game.sav --gift beast-cutscene --flag-id 1005
```

The injector selects the active FRLG save slot, writes the card and RAM script, and rebuilds the card
CRC, RAM-script CRC and affected flash-sector checksum. `--in-place` overwrites the source.

`--make-artifact` writes a deterministic `.ram.lst` under `artifacts/` recording the exact compiled RAM
script bytes, decoded instructions, checksums, branch and message destinations, and the source
delivery-stage summary.

## Closed paths

### Wireless Communication (JoySpot)

**Blocked at the RFU serial-number gate.** FireRed can be handed a Wonder Card two ways, and both reach
the same gift conversation:

| | Friend | Wireless Communication |
|---|---|---|
| listener | `Task_ListenForCompatiblePartners` [union_room.c:3757] | `Task_ListenForWonderDistributor` [union_room.c:3799] |
| accepts RFU serial | `IsRfuSerialNumberValid` → `{0x0002, 0x7F7D}` | `== 0x7F7D` only [link_rfu_3.c:920] |
| selection | the player picks from a list | auto-connects, no button press |
| reachable from a Switch | yes | no |

`Task_CardOrNewsOverWireless` [union_room.c:2415] scans, waits 120 frames, then evaluates candidate slot
0 and associates with no button press. Its gates, in order:

1. `Rfu_GetWonderDistributorPlayerData` [link_rfu_3.c:917] populates the candidate **only** if
   `partner[idx].serialNo == RFU_SERIAL_WONDER_DISTRIBUTOR (0x7F7D)`; otherwise it zeroes the entry.
2. `groupScheduledAnim == UNION_ROOM_SPAWN_IN && !startedActivity`.
3. `HasWonderCardOrNewsByLinkGroup` — the advertised `hasCard` bit; failing it plays SE_BOO.
4. `CreateTask_RfuReconnectWithParent(...)`.

Because gate 1 zeroes the entry, gates 2–4 are unreachable while the serial is wrong, and no SE_BOO is
produced. Uniform silence is the exact signature of gate 1 failing.

**The Switch LDN bridge reports `serialNo == 0x0002` (`RFU_SERIAL_GAME`).** `sAcceptedSerialNos`
[link_rfu_2.c:240] is `{0x0002, 0x7F7D}`, and the Friend list shows only a candidate whose serial passes
`IsRfuSerialNumberValid`. The Friend positive control was listed in every stage of the sweep, so the
serial is one of those two; Wireless Communication was silent for all 21 sweep candidates, so it is not
`0x7F7D`. Therefore it is `0x0002`.

**The advertisement record carries no serial field.** A real FRLG host always sets serial `0x0002`, yet
in a captured native advertisement every byte outside the four known fields is zero:

```
50 10 | c1 cc bf bf c8 ff 00 00 | 65 ac | 00 00 00 00 | 84 15 | 00 00 00 00 00 00
TID   | uname                   | parent| UNEXPLAINED | search| UNEXPLAINED
```

If the bridge carried a serial in the 24-byte record, `02 00` or `00 02` would appear in one of those
regions. This is consistent with `svc_47` [sloopsvc.c:34], whose parameter block is
`{u8 HostRfuGameData[0x10]; u8 HostRfuUsername[8]}` — 24 bytes, no serial field — while the candidate list
is written by the bridge through `svc_45_rfu_link_status()`.

**What the sweep did establish is the record model.** 21 controlled advertisements across three stages,
each held live until the operator answered, varied: the scene id (0, 21, 0x7F7D), the LDN app version,
the Pia app version, and both byte orders of `0x7F7D` at every unexplained word of the record (offsets
12, 13, 14, 18, 19, 20, 22); the advertised activity (0, 4, 21) and the `hasCard` bit; and the search
word's bit 7. Every one drew zero 802.11 authentication attempts. The Friend control was listed in every
stage and completed an LDN join in two of them.

`0x1584 & 0x7F = 4 = ACTIVITY_TRADE` in the native capture, and activity 21 at the same offset produced
a Friend listing and a completed LDN join, so the search word at `record[16:18]` decomposes as
`activity:7 | bit7 | version:3 | language:3 | hasCard?:1 | startedActivity:1` (version 5 = LeafGreen,
language 2 = English in that capture). Everything except the serial works.

Constant across every sweep row: `local_communication_id = 0x01006fa0233f8000`, LDN version 4, channel
1, `max_participants = 2`, Pia `sysCommVer = 22`, scene 22287 except where a row varied it.

Deliberately not tested, with reasons: **`local_communication_id`**, because the console's scan almost
certainly filters on it and a different value makes the host invisible, which is indistinguishable from
the serial gate failing; **blind scene-id brute force**, 65536 values, where the Friend control already
proves scene 22287 is acceptable for Mystery Gift discovery generally; and **multi-variable
combinations**, which are only worth exploring once a single variable produces a reaction.

This would reopen on: direct evidence from the bridge showing a rule that assigns `partner[].serialNo`
from anything advertisable; a real Switch-era Wonder Card distribution existing (the evidence runs the
other way — Nintendo shipped the Mystic and Aurora Tickets on Switch as a Hall-of-Fame grant rather than
a distribution event); or a capture of any LDN advertisement a Switch itself treats as a wonder
distributor.

It blocks only the zero-button experience. It also puts the four-berry "big" Wonder News reward out of
reach, that reward being keyed to a non-Friend source.

### The e-Reader itself

Trainer Tower sets and `CEReaderTool_SaveTrainerTower`: `ereader_screen.c` opens
`gLinkType = LINKTYPE_EREADER_FRLG` over the GBA **serial** link, not the wireless adapter. Not an LDN
surface.

### The Aurora and Mystic Tickets

Real distribution scripts exist verbatim in `data/mystery_event_msg.s:200`, but the Switch release grants
both tickets and both `FLAG_RECEIVED_*` flags on the first Hall of Fame entry
[post_battle_event_funcs.c:52, inside `#if REVISION >= 0xA`]. On a completed save every guard in the
script trips and it is a no-op. The Old Sea Map is Emerald-only [mystery_gift.c:30].

### Serving consoles back to back

Not built: the host is restarted between consoles.

## Traps

- **`charmap.encode` drops every character it does not know, newline included.** The game's line break
  is 0xFE. `mg_server`'s encoder splits on `\n` and joins on 0xFE, and refuses offline both a third line
  and a line wider than the ROM's own longest string in that window — "A WONDER CARD has been received",
  31 characters [strings.c:1291]. Window 1 is 28 tiles by 4 [mystery_gift_menu.c:97,524].
- **A payload must be added to lists it cannot see.** `DUMP_SCRIPTS` and `DECODED_SCRIPTS` in
  `buffer_script.py`, and the launcher's `--dump-file` line. Grep for a sibling payload by name when
  adding one; an offline harness that builds its distribution directly will pass while the one path
  hardware uses is never exercised.
