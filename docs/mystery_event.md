---
title: The Mystery Event VM
parent: Inside the console
nav_order: 1
---

# The Mystery Event VM

FireRed/LeafGreen carry two bytecode interpreters that a Mystery Gift session can reach. One is the
ordinary field-script VM: that is what a Wonder Card's delivery script is, and everything in
[Composing gifts](mystery_gift_composer.md) compiles to it. The other is the **Mystery Event VM**, a
separate 17-command table [`data/mystery_event_script_cmd_table.s`] with its own interpreter
[`src/mystery_event_script.c`], and it is what `CLI_RUN_MEVENT_SCRIPT` runs.

Until now this project touched it exactly once, in six bytes: the stamp rally's activation script,
`05 06 00 00 00 02` + an embedded field script - `runscript`, `end`. This page is the rest of it.

Everything here is a decompilation fact unless it is marked otherwise.

## The command table

| # | Command | Operands after the opcode byte | Returns | What it does |
|---|---|---|---|---|
| 0 | `nop` | - | FALSE | nothing |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | **TRUE** | the compatibility gate; see below |
| 2 | `end` | - | **TRUE** | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | `StringExpandPlaceholders(gStringVar4, str)` when the selector is `0xFF` or equals the status |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | `RunScriptImmediately` on a **field** script |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | `InitRamScript` bound to any map and object |
| 7 | `setenigmaberry` | ptr | FALSE | writes `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | a gift ribbon onto every non-egg party mon |
| 9 | `givenationaldex` | - | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord` (an Easy Chat trendy saying) |
| 11 | `setrecordmixinggift` | - | **TRUE** | dead: `SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | a whole `struct Pokemon` **plus attached Mail** into the party |
| 13 | `addtrainer` | ptr | FALSE | a 188-byte `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` | - | **TRUE** | dead: `SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | **TRUE** | status 1 if `CalcByteArraySum` over the range does not match |
| 16 | `crc` | u32, ptr, ptr | **TRUE** | the same with `CalcCRC16` |

`frlgsim/mystery_event.py` assembles all of them; `MysteryEventScript.blob()` holds the data and the
assembler resolves the pointers.

## Why `checkcompat` is optional

`checkcompat` looks mandatory. It is the first command of every official script, it gates the
language and version masks, and `LANGUAGE_MASK` is the English decomp's value - which we cannot
check against two French consoles. Skipping it removes an unknown we have no way to solve.

It can be skipped, and the reason is the loop structure:

```c
bool32 RunMysteryEventScriptCommand(struct ScriptContext *ctx)
{
    if (RunScriptCommand(ctx) && ctx->data[3])   // data[3] is set only by checkcompat
        return TRUE;
    return FALSE;
}
...
while (MEventScript_Run(&ret));
```

`RunScriptCommand` [`src/script.c:107`] already loops **inside one call**, executing commands until
one returns TRUE. Only six commands return TRUE. So a script with no `checkcompat` still runs every
command up to the first TRUE-returning one, in a single pass; the outer `while` then stops because
`data[3]` is 0. That first TRUE-returning command is the end of the script, and `end` is the
ordinary way to write it.

Two consequences follow, and they are the reason the VM is usable at all:

- **`checkcompat` never runs, so its masks never matter.** The French `LANGUAGE_MASK` question is
  not answered; it is removed.
- **Pointer operands become plain offsets.** Every pointer is relocated as
  `operand - ctx->data[1] + ctx->data[0]`. `data[1]` is set only *by* `checkcompat`, so it stays 0,
  and `data[0]` is the address of the script itself - the console's 1024-byte `client->recvBuffer`.
  An operand of N therefore means "N bytes from the start of what we sent", with no virtual base to
  guess. This is already hardware-proven: the stamp rally's `runscript 6` has been landing on both
  French consoles since session 22.

`checkcompat` exists only to let execution *resume* after itself. It is the one command the
assembler will let you emit code after.

## The console answers

```c
static u32 Client_RunMysteryEventScript(struct MysteryGiftClient * client)
{
    ...
    case 1:
        if (!MEventScript_Run(&client->param))      // *a0 = ctx->data[2]
```

`MEventScript_Run` writes the script's **status** into `client->param`
[`src/mystery_event_script.c:75`]. And `CLI_LOAD_TOSS_RESPONSE` - named for the replace-card prompt,
but it is not specific to it - loads exactly `client->param` into `MG_LINKID_RESPONSE`
[`src/mystery_gift_client.c:204`]:

```
CLI_RECV MG_LINKID_RAM_SCRIPT
CLI_RUN_MEVENT_SCRIPT
CLI_LOAD_TOSS_RESPONSE
CLI_SEND_LOADED
```

Those four commands are a **return channel from the console to us**, carrying a u32 we choose. The
Wonder News path answers TRUE/FALSE and was until now the only place the console said anything back;
this is the same channel with 256 values in it, and `setstatus` sets it to whatever we like.

The stock statuses report an outcome nothing else on this link would show:

| Status | Meaning |
|---|---|
| 0 | no command set one |
| 1 | `setenigmaberry` could not validate the berry, or a `checksum`/`crc` mismatch |
| 2 | success - every opcode that did its job sets this |
| 3 | `SetIncompatible`, or **`givepokemon` found a full party** |

`CLI_COPY_RECV_IF` and `CLI_COPY_RECV_IF_N` branch the *client script* on `client->param`
[`src/mystery_gift_client.c:170`], so a status of 0 or 1 can also steer what the console does next
without another round trip. Not yet used.

## What the console shows, and whether it saves

The Mystery Gift menu prints its own result text from the client script's `CLI_RETURN` value
[`GetClientResultMessage`, `src/mystery_gift_menu.c:884`], not from `gStringVar4`, so `setmsg` is
invisible on this path. What matters is that only a **success** message reaches
`MG_STATE_SAVE_LOAD_GIFT` [`:1379`] - and without that save, everything the event wrote is lost at
the next reset. `CLIENT_SCRIPT_MEVENT_DONE` therefore returns `CLI_MSG_CARD_RECEIVED`, which is a
success message even on the branch where no card was sent.

`CLI_MSG_BUFFER_SUCCESS` (13) is the other success exit: it prints `data->clientMsg`, the 64 bytes
pushed by `CLI_COPY_MSG`, so an arbitrary on-screen message with a save is available. Not yet used.

## Traps

- **`setenigmaberry` cannot set the item effect.** `struct ReceivedEnigmaBerry` [`src/berry.c:944`]
  is 1322 bytes: the 28-byte `Berry2` at offset 0, then `u8 unk_001C[0x4FA]`, then `itemEffect[18]`,
  `holdEffect` and `holdEffectParam` at offset 0x516 - 1302 bytes into a buffer that is only 1024.
  The name, flavours, size, firmness and growth data all land; the tail is read from whatever
  follows `recvBuffer` on the console's heap. `build_enigma_berry_blob` lays the struct out and the
  simulator reports the overrun as a `read_past_buffer` effect.
- **`giveribbon` index 7..10.** `GiveGiftRibbonToParty` [`src/pokemon_size_record.c:193`] accepts
  `index < 11`, but `sGiftRibbonsMonDataIds` has seven entries copied into a `u8[8]`; 7..10
  `SetMonData` a field id read from uninitialised stack. The assembler refuses anything above 6.
- **FRLG has no ribbon UI.** Nothing in `src/pokemon_summary_screen.c` mentions ribbons, so
  `giveribbon` is invisible on this console - the effect only shows up after a transfer.
- **A script with no terminal command runs on.** The console keeps decoding the rest of its
  zero-filled 1024-byte buffer as opcodes. `assemble()` refuses a script that does not end in one,
  and so does the server.
- **`setrecordmixinggift` and `enableresetrtc` are dead.** Both call `SetIncompatible` and stop the
  chain [`src/mystery_event_script.c:227`, `:291`]. The composer rejects them.

## How it is wired

- `frlgsim/mystery_event.py` - opcodes, the assembler, a disassembler (`describe`), and `run()`, a
  simulator of the console's execution used by the offline client.
- `frlgsim/mg_script.py` - `CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT` (no card held: card, delivery
  script, then the event), `CLIENT_SCRIPT_RUN_MEVENT` (the console already holds this card: the
  event alone, nothing tossed) and `CLIENT_SCRIPT_MEVENT_DONE`, the shared success tail.
- `frlgsim/mg_server.py` - `SCRIPT_SEND_MYSTERY_EVENT`, with `SVR_LOAD_MEVENT` and
  `SVR_READ_MEVENT_STATUS`; the status lands in `server.mevent_status` and in the host log.
- `frlgsim/gift_composer.py` - `WonderGift.mevent` takes assembled bytes and validates them.

## `givepokemon`: the only Pokemon on this link that can carry Mail

`frlgsim/mevent_pokemon.py` builds the payload - a 100-byte encrypted party mon followed by the
34-byte `struct Mail` the console reads at `pointer + sizeof(struct Pokemon)`. `--gift
mystery-event-celebi` ships one.

Three things it does that the field-script `givemon` our delivery scripts compile to cannot:

- **Mail.** Nothing else on the gift link can attach any. `ItemIsMail` gates it, so the mon's held
  item must be one of the twelve mail items [`src/mail_data.c:167`], and `GiveMailToMon2` then
  copies our whole struct into `gSaveBlock1Ptr->mail` verbatim [`:100`] - words, sender name,
  trainer id, species and item are all ours.
- **It writes the Pokedex itself**, `FLAG_SET_SEEN` and `FLAG_SET_CAUGHT` on the national number,
  before the player ever sees the mon.
- **It lands at the Mystery Gift menu**, not at the delivery man. The mon is in the party the moment
  the menu closes, with no Pokemon Center visit - which is also how you tell the event apart from
  the card's own delivery script.

The status is the outcome: **2** for success, **3** for a full party, in which case nothing is
written at all. Do not put a `setstatus` after `givepokemon` - that answer is the point.

Traps the builder enforces:

- the mon's `mail` byte must be `MAIL_NONE` (0xFF) going in; a zero there is mail slot 0, which the
  console reads as real mail the player never received;
- `personality == otId` makes the encryption key 0, and a mon then validates both shuffled and
  unshuffled, so an unshuffled one could ship;
- the party tail must be derived, not zeroed - a zero tail reads back as level 0;
- the mon's held item and the mail's `itemId` must agree, because `GiveMailToMon2` sets the held
  item *from the mail*.

### mev02: Celebi with mail, and an Easy Chat divergence

`mev02`, French FireRed, first try. Status **2** came back, and the player found a level 30 CELEBI
in the party holding ORANGE MAIL - without going anywhere near a Pokemon Center. `givepokemon` is
proven.

The mail read:

    SALUT AMIS / JE SUIS LA / MERCI STRESSE

We sent `hello, friend, i_ve_arrived, thank_you, enjoy`. Four of the five slots printed the word the
English table promised. `EC_WORD_ENJOY` (FEELINGS/42) printed **STRESSE**.

An Easy Chat word id is `(group << 9) | index` - a *slot*, not a word - and every localized ROM
carries its own `gEasyChatGroup_*` tables. `frlgsim/easychat_words.py` is generated from the English
decompilation, so it is mostly right and occasionally wrong, with nothing to warn you. That applies
to every Easy Chat phrase this project composes: mail, the trainer card profile quote, and the
visiting trainer's three six-word lines. `frlgsim/easychat_french.py` records what has actually been
seen on the French console; compose from that.

The cheapest fix is a channel we already had and never read. The Poke Mart questionnaire stores four
Easy Chat words in `gSaveBlock1Ptr->mysteryGift.questionnaireWords` [`src/mystery_gift.c:84`] and
**every** Mystery Gift session ships them to us inside `MysteryGiftLinkGameData` [`:361`]. A player
who fills the questionnaire in French hands us four exact ids on the next run of anything. The host
now logs them, along with the Easy Chat battle profile and the Wonder Card stats - three things the
console volunteers that nothing in the game ever reads back.

### mev03: `initramscript`, and what it costs

`initramscript 3, 0, 2` bound a two-line field script to the fat man in the south of Pallet Town.
Status 55 came back, and after a reboot he said our lines - `{PLAYER}` expanded and all.

It works because it puts the script on the *other* dispatch path. `CLI_SAVE_RAM_SCRIPT`, which every
gift before this used, calls `InitRamScript_NoObjectEvent`: MAP_UNDEFINED, object 0xFF
[`src/script.c:578`]. Those never satisfy `GetRamScript`'s map and object checks [`:514`]; they
exist for `GetSavedRamScriptIfValid` [`:554`], the delivery man's own script command, which also
requires a valid Wonder Card. Real coordinates land on
`GetRamScript(gSpecialVar_LastTalked, script)` in the field [`src/field_control_avatar.c:458`],
which runs our script **instead of** the object's own and never consults the card.
`gSpecialVar_LastTalked` is the object's *local* id, assigned in `map.json` order from 1.

**And it costs the Wonder Card.** The player noticed the Mystery Gift menu reporting no card
straight afterwards. That is by design:

```c
bool32 ValidateSavedWonderCard(void)
{
    if (cardCrc != CALC_CRC(card)) return FALSE;
    if (!ValidateWonderCard(&card)) return FALSE;
    if (!ValidateRamScript()) return FALSE;      // MAP_UNDEFINED / object 0xFF only
    return TRUE;
}
```

There is one RAM script slot, and the card's validity depends on what is in it. Bind real
coordinates and the card is still in the save, byte for byte, with a good CRC - but the menu will
not show it and `MysteryGift_LoadLinkGameData` reports `flagId` 0 [`src/mystery_gift.c:349`], so the
next session sees `HAS_NO_CARD`. **A Wonder Card and an NPC-bound script are mutually exclusive.**
It is fully reversible: the next Wonder Card takes the slot back and the card returns.

## The questionnaire, as a password

`SVR_CHECK_QUESTIONNAIRE` compares all four words, in order, exactly
[`MysteryGift_DoesQuestionnaireMatch`, `src/mystery_gift.c:422`], and puts the verdict in the
server's `param` where `SVR_GOTO_IF_EQ` can branch on it. No native server script uses it - the idea
survives only in the official Visiting Trainer card, whose phrase was "GIVE ME AWESOME TRAINER" - so
the flow is ours to build.

`mg_server.gate_on_questionnaire(script)` splices the check between the shared game-data prefix and
whatever the script does next, so any distribution can be gated:

    MysteryGiftServer(card, ram_script, questionnaire=phrase,
                      denied_message="Say the words.")

or from the command line, where a word may be an English name, `species:N`, `move:N`,
`GROUP/INDEX`, or a raw id - the last three because the English names are only a guess outside the
species and move groups, and a phrase read off a real console arrives as ids:

    bin/frlgmg_host.py --gift ... --questionnaire species:55,FEELINGS/60,move:177,why

A console that says the wrong phrase gets our 64-byte message through `CLIENT_SCRIPT_DYNAMIC_ERROR`
and the session returns `SVR_MSG_NOTHING_SENT`; nothing is sent and nothing is tossed.

The phrase itself cannot come from the decompilation. Four French word ids are four slots in a table
the English decomp does not have, so the phrase is read off a real console first and only then
required. mev03 did that at no cost: the console volunteered

    questionnaire: POKEMON/55  done [FEELINGS/60]  MOVE_1/177  why [MISC/37]

for a player who had typed **AKWAKWAK FURAX AEROBLAST POURQUOI**. That is
`easychat_french.CONSOLE_QUESTIONNAIRE`, and it settled three separate questions:

- **`EC_GROUP_POKEMON` indexes by species number.** AKWAKWAK is Golduck, species 55; the slot is
  POKEMON/55.
- **`EC_GROUP_MOVE_1` indexes by move id.** AEROBLAST is move 177; the slot is MOVE_1/177.
- **The English table was right about MISC/37 (`why` = POURQUOI) and wrong about FEELINGS/60**
  (`done`, but the console prints FURAX). Second known divergence, and both are in FEELINGS.

The first two matter beyond this phrase. `CopyEasyChatWord` prints EC_GROUP_POKEMON, POKEMON_2,
MOVE_1 and MOVE_2 out of `gSpeciesNames` / `gMoveNames` [`src/easy_chat.c:155`] rather than from a
per-language word table - so those 807 words are the same word in every language *by construction*
and need no verification at all. `easychat.species_word(55)` and `easychat.move_word(177)` build
them, and they reproduce `0x2a37` and `0x24b1` exactly. Compose from those wherever you can.

### mev04 and mev06: both branches on hardware

Proven on the French FireRed, deliberately in that order - the refusal first, because a gate that
passes cannot be told apart from a gate that is not wired up at all.

**mev04**, requiring the player's phrase with the last word changed: the console read *"Those are
not the words."* and returned to the menu. Nothing sent, nothing saved, nothing tossed; the session
returned `SVR_MSG_NOTHING_SENT`. The host log shows the whole comparison:

    Questionnaire gate: console typed POKEMON/55 (language-safe) done [FEELINGS/60]
      MOVE_1/177 (language-safe) why [MISC/37]; we require ... hello [GREETINGS/15]
      -> no match, declining the gift

**mev06**, requiring the real phrase: `-> MATCH`, the card and the Mystery Event went out, status 42
came back, clean close.

**mev05**, between them, is the one intermittent failure. The gate matched and the entire gift went out - card,
delivery script, Mystery Event, status 42 returned - and then the console sent the RFU disconnect
1.4 s after our final client script instead of `READY_END`. That is the same *"erreur de connexion"*
the hold produces, so it was classified before being explained: `acklag.py` put the worst inbound gap
at **51 ms** against a 15 ms baseline, nowhere near the hold's 0.1-1.1 s. Ordinary intermittency, and
because the console never reached the success message it never saved. The retry went through.

These runs also confirmed the card/RAM-script coupling from the outside, in both directions. While
the Pallet Town script was installed every session logged `holding no Wonder Card` - that is
`MysteryGift_LoadLinkGameData` reporting `flagId` 0 because `ValidateSavedWonderCard` fails on
`ValidateRamScript`. And once mev06 delivered a card, the Pallet Town NPC went back to his own
dialogue: `CLI_SAVE_RAM_SCRIPT` took the slot back, exactly as predicted.

## Running it

    ./scratchpad/run_mg_fast.sh mevNN --gift mystery-event-probe --version firered

Offline first, as always:

    ./.venv/bin/python scratchpad/mg_client_harness.py --gift mystery-event-probe --flag-id 1009
    ./.venv/bin/python -m pytest tests/test_mystery_event.py -q

## The probe script (mev01)

`mystery-event-probe` was the first script on the air. It is deliberately incapable of losing the
player anything: `givenationaldex` is a strict upgrade and a no-op on a save that already has the
National Dex, and `checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

It is also self-diagnosing, because the status comes back:

| Status returned | What it proves |
|---|---|
| 42 | the chain ran to the end **and** pointer operands are offsets into our own buffer |
| 1 | the chain ran, but the relocated pointers did not land on our probe bytes |
| 2 | `givenationaldex` ran and nothing after it did - the chain does not continue past one command |
| 0 | the VM was entered but no command executed |
| nothing comes back | the client script shape is wrong, not the VM |

`checksum` goes last precisely because it is terminal: it reports on the relocation without
disturbing the status the commands before it left.

**The console answered 42.** Run `mev01`, French FireRed, 2026-09-04, first try: the card and its
delivery script went out, then the 31-byte event, and 2.2 s later `MG_LINKID_RESPONSE` came back
carrying 42. The console then saved by itself.

That single number settles four things:

1. A Mystery Event script with **no `checkcompat`** runs. The French `LANGUAGE_MASK` is not a
   question any more.
2. The chain **continues past the first command**. 42 can only come from `setstatus`, the second
   command; had execution stopped after one, the status would have been 2 - the value
   `givenationaldex` leaves behind.
3. **Pointer operands are offsets into our own buffer.** `checksum` recomputed `CalcByteArraySum`
   over the range its two relocated pointers named and it matched; a mismatch would have replaced
   the status with 1.
4. The **return channel works**. A u32 of our choosing crossed from the console to us.

One incidental bug the run caught: the card's icon showed an Aspicot (Weedle). `SPECIES_PORYGON` in
`wonder_card_events.py` was 13 - Weedle - where Porygon is 137. It was the `porygon-tms` card's icon
too. Fixed, and every other species constant was cross-checked against
`include/constants/species.h`.
