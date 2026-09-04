---
title: The Mystery Event VM
nav_order: 14
---

# The Mystery Event VM

FireRed/LeafGreen carry two bytecode interpreters that a Mystery Gift session can reach. One is the
ordinary field-script VM: that is what a Wonder Card's delivery script is, and everything in
[Composing gifts](mystery_gift_composer.md) compiles to it. The other is the **Mystery Event VM**, a
separate 17-command table [`data/mystery_event_script_cmd_table.s`] with its own interpreter
[`src/mystery_event_script.c`], and it is what `CLI_RUN_MEVENT_SCRIPT` runs.

Until now this project touched it exactly once, in six bytes: the stamp rally's activation script,
`05 06 00 00 00 02` + an embedded field script — `runscript`, `end`. This page is the rest of it.

Everything here is a decompilation fact unless it is marked otherwise.

## The command table

| # | Command | Operands after the opcode byte | Returns | What it does |
|---|---|---|---|---|
| 0 | `nop` | — | FALSE | nothing |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | **TRUE** | the compatibility gate; see below |
| 2 | `end` | — | **TRUE** | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | `StringExpandPlaceholders(gStringVar4, str)` when the selector is `0xFF` or equals the status |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | `RunScriptImmediately` on a **field** script |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | `InitRamScript` bound to any map and object |
| 7 | `setenigmaberry` | ptr | FALSE | writes `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | a gift ribbon onto every non-egg party mon |
| 9 | `givenationaldex` | — | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord` (an Easy Chat trendy saying) |
| 11 | `setrecordmixinggift` | — | **TRUE** | dead: `SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | a whole `struct Pokemon` **plus attached Mail** into the party |
| 13 | `addtrainer` | ptr | FALSE | a 188-byte `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` | — | **TRUE** | dead: `SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | **TRUE** | status 1 if `CalcByteArraySum` over the range does not match |
| 16 | `crc` | u32, ptr, ptr | **TRUE** | the same with `CalcCRC16` |

`frlgsim/mystery_event.py` assembles all of them; `MysteryEventScript.blob()` holds the data and the
assembler resolves the pointers.

## Why `checkcompat` is optional, and why that is the whole story

`checkcompat` looks mandatory. It is the first command of every official script, it gates the
language and version masks, and `LANGUAGE_MASK` is the English decomp's value — which we cannot
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
  and `data[0]` is the address of the script itself — the console's 1024-byte `client->recvBuffer`.
  An operand of N therefore means "N bytes from the start of what we sent", with no virtual base to
  guess. This is already hardware-proven: the stamp rally's `runscript 6` has been landing on both
  French consoles since session 22.

`checkcompat` exists only to let execution *resume* after itself. It is the one command the
assembler will let you emit code after.

## The console answers

This is the part that is worth more than any single opcode.

```c
static u32 Client_RunMysteryEventScript(struct MysteryGiftClient * client)
{
    ...
    case 1:
        if (!MEventScript_Run(&client->param))      // *a0 = ctx->data[2]
```

`MEventScript_Run` writes the script's **status** into `client->param`
[`src/mystery_event_script.c:75`]. And `CLI_LOAD_TOSS_RESPONSE` — named for the replace-card prompt,
but it is not specific to it — loads exactly `client->param` into `MG_LINKID_RESPONSE`
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

The stock statuses are worth knowing because they report an outcome we could not otherwise see:

| Status | Meaning |
|---|---|
| 0 | no command set one |
| 1 | `setenigmaberry` could not validate the berry, or a `checksum`/`crc` mismatch |
| 2 | success — every opcode that did its job sets this |
| 3 | `SetIncompatible`, or **`givepokemon` found a full party** |

`CLI_COPY_RECV_IF` and `CLI_COPY_RECV_IF_N` branch the *client script* on `client->param`
[`src/mystery_gift_client.c:170`], so a status of 0 or 1 can also steer what the console does next
without another round trip. Not yet used.

## What the console shows, and whether it saves

The Mystery Gift menu prints its own result text from the client script's `CLI_RETURN` value
[`GetClientResultMessage`, `src/mystery_gift_menu.c:884`], not from `gStringVar4`, so `setmsg` is
invisible on this path. What matters is that only a **success** message reaches
`MG_STATE_SAVE_LOAD_GIFT` [`:1379`] — and without that save, everything the event wrote is lost at
the next reset. `CLIENT_SCRIPT_MEVENT_DONE` therefore returns `CLI_MSG_CARD_RECEIVED`, which is a
success message even on the branch where no card was sent.

`CLI_MSG_BUFFER_SUCCESS` (13) is the other success exit: it prints `data->clientMsg`, the 64 bytes
pushed by `CLI_COPY_MSG`, so an arbitrary on-screen message with a save is available. Not yet used.

## Traps

- **`setenigmaberry` cannot set the item effect.** `struct ReceivedEnigmaBerry` [`src/berry.c:944`]
  is 1322 bytes: the 28-byte `Berry2` at offset 0, then `u8 unk_001C[0x4FA]`, then `itemEffect[18]`,
  `holdEffect` and `holdEffectParam` at offset 0x516 — 1302 bytes into a buffer that is only 1024.
  The name, flavours, size, firmness and growth data all land; the tail is read from whatever
  follows `recvBuffer` on the console's heap. `build_enigma_berry_blob` lays the struct out and the
  simulator reports the overrun as a `read_past_buffer` effect.
- **`giveribbon` index 7..10.** `GiveGiftRibbonToParty` [`src/pokemon_size_record.c:193`] accepts
  `index < 11`, but `sGiftRibbonsMonDataIds` has seven entries copied into a `u8[8]`; 7..10
  `SetMonData` a field id read from uninitialised stack. The assembler refuses anything above 6.
- **FRLG has no ribbon UI.** Nothing in `src/pokemon_summary_screen.c` mentions ribbons, so
  `giveribbon` is invisible on this console — the effect only shows up after a transfer.
- **A script with no terminal command runs on.** The console keeps decoding the rest of its
  zero-filled 1024-byte buffer as opcodes. `assemble()` refuses a script that does not end in one,
  and so does the server.
- **`setrecordmixinggift` and `enableresetrtc` are dead.** Both call `SetIncompatible` and stop the
  chain [`src/mystery_event_script.c:227`, `:291`]. The composer rejects them.

## How it is wired

- `frlgsim/mystery_event.py` — opcodes, the assembler, a disassembler (`describe`), and `run()`, a
  simulator of the console's execution used by the offline client.
- `frlgsim/mg_script.py` — `CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT` (no card held: card, delivery
  script, then the event), `CLIENT_SCRIPT_RUN_MEVENT` (the console already holds this card: the
  event alone, nothing tossed) and `CLIENT_SCRIPT_MEVENT_DONE`, the shared success tail.
- `frlgsim/mg_server.py` — `SCRIPT_SEND_MYSTERY_EVENT`, with `SVR_LOAD_MEVENT` and
  `SVR_READ_MEVENT_STATUS`; the status lands in `server.mevent_status` and in the host log.
- `frlgsim/gift_composer.py` — `WonderGift.mevent` takes assembled bytes and validates them.

## Running it

    ./scratchpad/run_mg_fast.sh mevNN --gift mystery-event-probe --version firered

Offline first, as always:

    ./.venv/bin/python scratchpad/mg_client_harness.py --gift mystery-event-probe --flag-id 1009
    ./.venv/bin/python -m pytest tests/test_mystery_event.py -q

## The probe script, and what it proved (mev01, first try)

`mystery-event-probe` was the first script on the air. It is deliberately incapable of losing the
player anything: `givenationaldex` is a strict upgrade and a no-op on a save that already has the
National Dex, and `checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

It is also self-diagnosing, because the status comes back:

| Status returned | What it proves |
|---|---|
| 42 | the chain ran to the end **and** pointer operands are offsets into our own buffer |
| 1 | the chain ran, but the relocated pointers did not land on our probe bytes |
| 2 | `givenationaldex` ran and nothing after it did — the chain does not continue past one command |
| 0 | the VM was entered but no command executed |
| nothing comes back | the client script shape is wrong, not the VM |

`checksum` goes last precisely because it is terminal: it reports on the relocation without
disturbing the status the commands before it left.

**The console answered 42.** Run `mev01`, French FireRed, 2026-09-04, first try: the card and its
delivery script went out, then the 31-byte event, and 2.2 s later `MG_LINKID_RESPONSE` came back
carrying 42. The console then saved by itself.

That single number settles four things at once:

1. A Mystery Event script with **no `checkcompat`** runs. The French `LANGUAGE_MASK` is not a
   question any more.
2. The chain **continues past the first command**. 42 can only come from `setstatus`, the second
   command; had execution stopped after one, the status would have been 2 — the value
   `givenationaldex` leaves behind.
3. **Pointer operands are offsets into our own buffer.** `checksum` recomputed `CalcByteArraySum`
   over the range its two relocated pointers named and it matched; a mismatch would have replaced
   the status with 1.
4. The **return channel works**. A u32 of our choosing crossed from the console to us.

One incidental bug the run caught: the card's icon showed an Aspicot (Weedle). `SPECIES_PORYGON` in
`wonder_card_events.py` was 13 — Weedle — where Porygon is 137. It was the `porygon-tms` card's icon
too. Fixed, and every other species constant was cross-checked against
`include/constants/species.h`.
