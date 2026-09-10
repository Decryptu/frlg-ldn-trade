---
title: Code on the console
parent: FireRed and LeafGreen
nav_order: 3
---

# Running code on the console

The Mystery Gift client runs code sent to it through two interpreters.

`CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands the bytes to the game's 17-opcode Mystery Event VM.
`CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the **CPU**: 1024 bytes copied into
`gDecompressionBuffer` and called as `func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr)`
[mystery_gift_client.c:276]. There is no glitch, no prepared save and nothing for the player to set
up; the console sits on its own Mystery Gift menu the whole time.

Addresses on this page were measured on French FireRed, cartridge BPRF, software version 0x0A.
LeafGreen's are on [LeafGreen](frlg_leafgreen.md); the tables and how they were found are on
[The ROM map](frlg_rom_map.md).

# The Mystery Event VM

A separate interpreter [src/mystery_event_script.c] with its own 17-command table
[data/mystery_event_script_cmd_table.s], distinct from the ordinary field-script VM that a Wonder
Card's delivery script compiles to.

## The command table

| # | command | operands after the opcode byte | returns | effect |
|---|---|---|---|---|
| 0 | `nop` |  | FALSE | nothing |
| 1 | `checkcompat` | u32 base, u16, u32, u16, u32 | **TRUE** | the compatibility gate |
| 2 | `end` |  | **TRUE** | `StopScript` |
| 3 | `setmsg` | u8 selector, ptr | FALSE | `StringExpandPlaceholders(gStringVar4, str)` when the selector is `0xFF` or equals the status |
| 4 | `setstatus` | u8 | FALSE | `ctx->data[2] = value` |
| 5 | `runscript` | ptr | FALSE | `RunScriptImmediately` on a field script |
| 6 | `initramscript` | u8 group, u8 map, u8 object, ptr, ptr | FALSE | `InitRamScript` bound to any map and object |
| 7 | `setenigmaberry` | ptr | FALSE | writes `gSaveBlock1Ptr->enigmaBerry` |
| 8 | `giveribbon` | u8 index, u8 ribbonId | FALSE | a gift ribbon onto every non-egg party mon |
| 9 | `givenationaldex` |  | FALSE | `EnableNationalPokedex()` |
| 10 | `addrareword` | u8 | FALSE | `EnableRareWord` (an Easy Chat trendy saying) |
| 11 | `setrecordmixinggift` |  | **TRUE** | dead: `SetIncompatible` |
| 12 | `givepokemon` | ptr | FALSE | a whole `struct Pokemon` plus attached Mail into the party |
| 13 | `addtrainer` | ptr | FALSE | a 188-byte `BattleTowerEReaderTrainer` |
| 14 | `enableresetrtc` |  | **TRUE** | dead: `SetIncompatible` |
| 15 | `checksum` | u32, ptr, ptr | **TRUE** | status 1 if `CalcByteArraySum` over the range does not match |
| 16 | `crc` | u32, ptr, ptr | **TRUE** | the same with `CalcCRC16` |

`pokeldn/frlg/rom/mystery_event.py` assembles all of them; `MysteryEventScript.blob()` holds the data
and the assembler resolves the pointers.

Every opcode has been run on retail hardware.

## `checkcompat` is optional, and skipping it removes two unknowns

`checkcompat` looks mandatory, it is the first command of every official script and it gates the
language and version masks, whose `LANGUAGE_MASK` is the English decomp's value. It can be skipped,
because of the loop structure:

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

`RunScriptCommand` [script.c:107] already loops *inside one call*, executing commands until one
returns TRUE, and only six commands return TRUE. So a script with no `checkcompat` runs every command
up to the first TRUE-returning one in a single pass, and the outer `while` then stops because
`data[3]` is 0. That first TRUE-returning command is the end of the script, and `end` is the ordinary
way to write it.

Two consequences:

- `checkcompat` never runs, so its masks never matter. The French `LANGUAGE_MASK` question is
  removed rather than answered.
- Pointer operands become plain offsets. Every pointer is relocated as
  `operand - ctx->data[1] + ctx->data[0]`. `data[1]` is set only by `checkcompat`, so it stays 0, and
  `data[0]` is the address of the script itself, the console's 1024-byte `client->recvBuffer`. An
  operand of N means "N bytes from the start of what was sent", with no virtual base to guess.

`checkcompat` exists only to let execution *resume* after itself. It is the one command the assembler
allows code after.

## The return channel

`MEventScript_Run` writes the script's status into `client->param`
[mystery_event_script.c:75], and `CLI_LOAD_TOSS_RESPONSE`, named for the replace-card prompt but not
specific to it, loads exactly `client->param` into `MG_LINKID_RESPONSE`
[mystery_gift_client.c:204]:

    CLI_RECV MG_LINKID_RAM_SCRIPT
    CLI_RUN_MEVENT_SCRIPT
    CLI_LOAD_TOSS_RESPONSE
    CLI_SEND_LOADED

Those four commands are a return channel from the console carrying a u32 of the sender's choosing.
`setstatus` sets it to anything; the stock statuses report outcomes nothing else on this link shows:

| status | meaning |
|---|---|
| 0 | no command set one |
| 1 | `setenigmaberry` could not validate the berry, or a `checksum`/`crc` mismatch |
| 2 | success, every opcode that did its job sets this |
| 3 | `SetIncompatible`, or `givepokemon` found a full party |

`CLI_COPY_RECV_IF` and `CLI_COPY_RECV_IF_N` branch the *client script* on `client->param`
[mystery_gift_client.c:170], so a status can steer what the console does next without another round
trip. Not yet used.

The Mystery Gift menu prints its own result text from the client script's `CLI_RETURN` value
[`GetClientResultMessage`, mystery_gift_menu.c:884], not from `gStringVar4`, so `setmsg` is invisible
on this path. Only a success message reaches `MG_STATE_SAVE_LOAD_GIFT` [:1379], and without that save
everything the event wrote is lost at the next reset, which is why `CLIENT_SCRIPT_MEVENT_DONE`
returns `CLI_MSG_CARD_RECEIVED` even on the branch where no card was sent.
`CLI_MSG_BUFFER_SUCCESS` (13) is the other success exit and prints `data->clientMsg`, the 64 bytes
pushed by `CLI_COPY_MSG`.

### The probe script

`--gift mystery-event-probe` is deliberately incapable of losing the player anything:
`givenationaldex` is a strict upgrade and a no-op on a save that already has the National Dex, and
`checksum` only reads.

    givenationaldex; setstatus 42; checksum 1026, 16, 31

and the returned status is self-diagnosing:

| status | what it proves |
|---|---|
| 42 | the chain ran to the end and pointer operands are offsets into the sent buffer |
| 1 | the chain ran, but the relocated pointers did not land on the probe bytes |
| 2 | `givenationaldex` ran and nothing after it did |
| 0 | the VM was entered but no command executed |
| nothing | the client script shape is wrong, not the VM |

`checksum` goes last precisely because it is terminal: it reports on the relocation without disturbing
the status the commands before it left. The console answers 42.

## `givepokemon`

`pokeldn/frlg/save/mevent_pokemon.py` builds the payload, a 100-byte encrypted party mon followed by
the 34-byte `struct Mail` the console reads at `pointer + sizeof(struct Pokemon)`.
`--gift mystery-event-celebi` ships one.

Three things it does that the field-script `givemon` cannot:

- Mail. Nothing else on the gift link can attach any. `ItemIsMail` gates it, so the mon's held item
  must be one of the twelve mail items [mail_data.c:167], and `GiveMailToMon2` then copies the whole
  struct into `gSaveBlock1Ptr->mail` verbatim [:100], words, sender name, trainer id, species and item.
- It writes the Pokedex itself, `FLAG_SET_SEEN` and `FLAG_SET_CAUGHT` on the national number,
  before the player sees the mon.
- It lands at the Mystery Gift menu, not at the delivery man. The mon is in the party the moment
  the menu closes, with no Pokemon Center visit.

The status is the outcome: 2 for success, 3 for a full party, in which case nothing is written. Do not
put a `setstatus` after `givepokemon`.

Traps the builder enforces:

- the mon's `mail` byte must be `MAIL_NONE` (0xFF) going in; a zero there is mail slot 0, which the
  console reads as real mail the player never received;
- `personality == otId` makes the encryption key 0, and a mon then validates both shuffled and
  unshuffled, so an unshuffled one could ship;
- the party tail must be derived, not zeroed, a zero tail reads back as level 0;
- the mon's held item and the mail's `itemId` must agree, because `GiveMailToMon2` sets the held item
  *from the mail*.

## `initramscript`

`initramscript 3, 0, 2` binds a field script to a named map object, group 3, map 0, object 2 is the
fat man in the south of Pallet Town. After a reboot he says the script's lines, with `{PLAYER}`
expanded.

It works because it puts the script on the *other* dispatch path. `CLI_SAVE_RAM_SCRIPT` calls
`InitRamScript_NoObjectEvent`: MAP_UNDEFINED, object 0xFF [script.c:578]. Those never satisfy
`GetRamScript`'s map and object checks [:514]; they exist for `GetSavedRamScriptIfValid` [:554], the
delivery man's own script command, which also requires a valid Wonder Card. Real coordinates land on
`GetRamScript(gSpecialVar_LastTalked, script)` in the field [field_control_avatar.c:458], which runs
the given script instead of the object's own and never consults the card. `gSpecialVar_LastTalked`
is the object's *local* id, assigned in `map.json` order from 1.

It costs the Wonder Card, see [the one RAM script slot](frlg_gift.md#the-one-ram-script-slot).
While a bound script is installed, every session logs "holding no Wonder Card"; the next ordinary card
takes the slot back and the object gets its own script again.

`GetRamScript` replaces the object's script outright, so binding to a plot object suppresses that
object's own encounter script entirely. Binding to Mewtwo's object in Cerulean Cave B1F replaced
Mewtwo's script with a scripted encounter of this project's own.

## Traps

- `setenigmaberry` cannot set the item effect. `struct ReceivedEnigmaBerry` [berry.c:944] is 1322
  bytes: the 28-byte `Berry2` at offset 0, then `u8 unk_001C[0x4FA]`, then `itemEffect[18]`,
  `holdEffect` and `holdEffectParam` at offset 0x516, 1302 bytes into a buffer that is only 1024. The
  name, flavours, size, firmness and growth data all land; the tail is read from whatever follows
  `recvBuffer` on the console's heap. `build_enigma_berry_blob` lays the struct out and the simulator
  reports the overrun as a `read_past_buffer` effect.
- The two ROM description pointers in `struct Berry2` must be read off the cartridge and sent back
  unchanged: they live in the save forever and the Berry Pouch dereferences them to print the
  description, so an invented pointer renders garbage on every future look at the berry.
- `giveribbon` index 7..10, `GiveGiftRibbonToParty` [pokemon_size_record.c:193] accepts
  `index < 11`, but `sGiftRibbonsMonDataIds` has seven entries copied into a `u8[8]`; 7..10
  `SetMonData` a field id read from uninitialised stack. The assembler refuses anything above 6.
- FRLG has no ribbon UI, so `giveribbon` is invisible on this console; the effect only shows up
  after a transfer.
- A script with no terminal command runs on, decoding the rest of the zero-filled 1024-byte buffer
  as opcodes. `assemble()` refuses a script that does not end in one, and so does the server.
- `setrecordmixinggift` and `enableresetrtc` are dead. Both call `SetIncompatible` and stop the
  chain [mystery_event_script.c:227, :291]. The composer rejects them. Read off the console, each makes
  exactly one call and it is `SetIncompatible`.
- `addrareword` and `setenigmaberry` are invisible in game and have to be read back from the save.
  `addrareword` sets a bit in `gSaveBlock1Ptr->additionalPhrases` (SaveBlock1 + 0x2F10) that makes one
  more word *selectable* in the Easy Chat editor; `setenigmaberry` writes
  `gSaveBlock1Ptr->enigmaBerry` (+0x30EC), whose record defines what the Enigma Berry *is* while the
  player still has no such item. `VAR_ENIGMA_BERRY_AVAILABLE`, which the opcode sets, is read nowhere
  else in FRLG.

## How it is wired

- `pokeldn/frlg/rom/mystery_event.py`, opcodes, the assembler, a disassembler (`describe`), and
  `run()`, a simulator of the console's execution used by the offline client.
- `pokeldn/frlg/gift/mg_script.py`, `CLIENT_SCRIPT_SAVE_CARD_AND_MEVENT` (no card held: card,
  delivery script, then the event), `CLIENT_SCRIPT_RUN_MEVENT` (the console already holds this card:
  the event alone, nothing tossed) and `CLIENT_SCRIPT_MEVENT_DONE`, the shared success tail.
- `pokeldn/frlg/gift/mg_server.py`, `SCRIPT_SEND_MYSTERY_EVENT`, with `SVR_LOAD_MEVENT` and
  `SVR_READ_MEVENT_STATUS`; the status lands in `server.mevent_status` and in the host log.
- `pokeldn/frlg/gift/gift_composer.py`, `WonderGift.mevent` takes assembled bytes and validates them.

# Native ARM code

```c
case CLI_RUN_BUFFER_SCRIPT:
    memcpy(gDecompressionBuffer, client->recvBuffer, MG_LINK_BUFFER_SIZE);
    client->funcId = FUNC_RUN_BUFFER;
    ...
static u32 Client_RunBufferScript(struct MysteryGiftClient * client)
{
    u32 (*func)(u32 *, struct SaveBlock2 *, struct SaveBlock1 *) = (void *)gDecompressionBuffer;
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)
```

[mystery_gift_client.c:237,276]. Five facts follow, and every payload rests on them:

- 1024 bytes, copied whole (`MG_LINK_BUFFER_SIZE`) whatever was actually sent, so a payload runs
  with the tail of the previous receive behind it and must be self-contained.
- Three arguments: `r0 = &client->param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr`. Both save
  blocks, by pointer, readable and writable.
- A return channel. `client->param` is what `CLI_LOAD_TOSS_RESPONSE` ships back as
  `MG_LINKID_RESPONSE` [:204].
- Called once per frame until it returns 1. A payload that returns anything else is re-entered
  next frame; one that never returns 1 hangs the Mystery Gift menu with no way out. The `memcpy` that
  loads the payload runs once, at the `CLI_RUN_BUFFER_SCRIPT` command [:239], not per call, so a
  payload can keep state across frames and resume.
- ARM state, not THUMB. The caller reaches it with a `bx` through a function pointer, which takes
  the state from bit 0 of a word-aligned address.

`gDecompressionBuffer` is at **0x0201C000**, measured by the `anchors` payload. Payloads are position
independent either way.

## The build

- `asm/*.s`, one ARM source per payload, assembled by `scripts/gen_buffer_scripts.py` into
  `pokeldn/frlg/rom/buffer_payloads.py`. The machine code is committed so a live host needs no GBA
  toolchain; `tests/test_buffer_script.py` re-assembles and compares whenever `arm-none-eabi-as` is
  installed.
- `pokeldn/frlg/rom/buffer_script.py`, the payload registry, the validation, and `emulate()`, which
  runs a payload under unicorn on the GBA memory map with the console's three arguments. A payload
  that faults, or never returns 1, is caught there and never reaches the air.
  `emulate_repeating` calls a payload until it returns 1, the way the console does.
- `pokeldn/frlg/gift/mg_script.py`, `CLIENT_SCRIPT_RUN_BUFFER` (recv, run, load the return channel,
  send it, recv the next script) and `CLIENT_SCRIPT_BUFFER_SUCCESS`.
- `pokeldn/frlg/gift/mg_server.py`, `SCRIPT_RUN_BUFFER_SCRIPT`. No card, no toss prompt, no branch on
  what the console holds: a buffer script is not a gift, so a console carrying any card takes the same
  path and keeps it.
- Both simulated consoles execute the payload for real: `pokeldn/frlg/gift/mg_client.py` and
  `ConsoleClientModel` in `tests/test_mystery_gift_flow.py`, written from the decomp independently and
  modelling the once-per-frame re-entry.

Offline first, every time:

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v

On hardware there is no replace-card prompt and no card: a console holding any Wonder Card keeps it.

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  ./scratchpad/run_mg_fast.sh bsNN --buffer-script --version firered
    (them) join the host when it appears

Never SIGTERM the Mystery Gift host until the dump file exists. The host writes
`scratchpad/<tag>_dump.bin` when the session closes, several seconds *after* the
`Buffer script dump: N bytes` line prints:

    until ls scratchpad/<tag>_dump.bin >/dev/null 2>&1; do sleep 2; done

## Repointing the console's outgoing message

`r0` is `&client->param`, so the whole of `struct MysteryGiftClient`
[include/mystery_gift_client.h:71] sits at fixed offsets from it:

| field | from `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

`MysteryGiftLink_InitSend` stores the pointer it is given [mystery_gift_link.c:59], and the CRC is
taken later, at send time, over `link->sendBuffer` for `link->sendSize` bytes [:166]. So a payload
running between the InitSend and the send can point the console's own outgoing message at any address,
and the console reads that region out and CRCs it. The client script order is the whole trick:

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

Swapping the middle two makes the payload patch fields the InitSend is about to overwrite.

A repointed region must not move between the CRC frame and the send frame.

```c
case 0:  header.crc = CalcCRC16WithTable(link->sendBuffer, link->sendSize);   // one frame
case 1:  SendBlock(0, link->sendBuffer + blocksize, ...);                     // the next
case 2:  if (CalcCRC16WithTable(...) != link->sendCRC) LinkRfu_FatalError();  // the one after
```

[mystery_gift_link.c:155]. Aiming a dump at `gRngValue` (0x03004220), which advances two turns every
frame, kills the link mid-transmission with *erreur de connexion*, the same run repeated unchanged
fails identically with a different CRC pair, which is the signature of a region that moves rather than
one that is corrupted. `buffer_script.build_memory_dump` refuses any range overlapping it and says what
to do instead: dump around it, or use `rng-trace`, which returns it through the 4-byte channel. It is
the only address named because it is the only one *guaranteed* to move; anything else volatile has to
be found the same way.

## The payloads

### `trainer-id-probe`

24 bytes, reads only, and chosen so one run decides everything because the answer is already known by
another route: the console put its own `playerTrainerId` into the `MysteryGiftLinkGameData` it sent
seconds earlier [mystery_gift.c:337].

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```

- The two agree: the payload ran, in ARM state, with the arguments the decomp promises, against the
  real `gSaveBlock2Ptr`, and returned 1.
- A different value: it ran, but the arguments or the offsets are not what they were thought to be.
- No `Buffer script status:` line at all: the client script shape is wrong, or the console never
  reached the call.

A 7-character player name's terminator overwrites `playerTrainerId[0]` on the way into the game data
[mystery_gift.c:364], so with a name that long the host compares the top three bytes and says so. The
save read is unaffected.

### `save-dump` and `memory-dump`

`memory-dump` takes an absolute address. `save-dump` needs none: the console hands the payload
`gSaveBlock2Ptr` in r1 and `gSaveBlock1Ptr` in r2, so it reads either save block at any offset on any
console and any build. Up to 1024 bytes a run, `MGL_Receive` rejects more [mystery_gift_link.c:102].

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-dump --dump-block sav2 \
        --dump-size 256 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script memory-dump --dump-address 0x0201C000 \
        --version firered

What this reaches that nothing else does: `SaveBlock1.playerParty` at 0x0038, `money` at 0x0290 XORed
with `SaveBlock2.encryptionKey` at 0xF20, the bag, flags and vars, and through `memory-dump`, IWRAM
where `gRngValue` lives. None of it is reachable by any Mystery Event opcode or link message.

### `memory-dump-multi` and `memory-dump-scatter`

`MG_LINK_BUFFER_SIZE` caps a message, not a session. The client executes a *script* of commands out
of its 1024-byte receive buffer [mystery_gift_client.c:140], and the three that produce a dump,

    CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

can appear in it as many times as it has room for. At 8 bytes a command and three fixed commands
around the loop, that is 41 passes; `mg_script.MAX_DUMP_BLOCKS` holds it at 32, because a session that
dies halfway loses every block in it. 16 KB takes about 57 seconds, blocks arriving about 2.5 s apart.

The payload cannot remember anything. `CLI_RUN_BUFFER_SCRIPT` memcpys `recvBuffer` over
`gDecompressionBuffer` on every pass [:238], so the image is restored each time and a cursor kept
inside it would never advance. What survives is what the payload is handed a *pointer* to:
`client->param`. So the block index lives there, and each pass sends `base + index * 1024` and hands
the next index on. It self-initialises off a magic in the high half, if `param` does not carry
`0x5A5A0000`, this is pass zero.

`memory-dump-scatter` is the same payload with the cursor indexing a table of bases carried in the
payload instead of being multiplied by 1024:

    adr     r3, .Ltable
    ldr     r3, [r3, r1, lsl #2]    @ this block's own base
    str     r3, [r0, #0x3C]         @ client->link.sendBuffer

`adr` is PC-relative, which is what lets the table be read from wherever `gDecompressionBuffer` is.
Every slot of the 32-entry table is filled, the unused ones with the last address, so a pass the client
script never promised re-sends a block already held rather than pointing the console's outgoing message
at 0.

That matters because a plan does not ask for one long region. For 166 unread function bodies spread
over a megabyte:

| one join, 16 KB off the wire | bodies it catches |
|---|---|
| `memory-dump-multi`, sixteen consecutive blocks at the best base | 22 |
| `memory-dump-scatter`, the sixteen densest kilobytes | 83 |
| `memory-dump-scatter`, 32 blocks | 119 of 166 |

The readability guard is per block, not over the span. multi's blocks are one region; scatter's are
unrelated regions and each is checked.

A scattered session's blocks arrive end to end in one file, so the launcher line carries
`--dump-scatter A,B,C` and `script_read.dumps` splits the file and places each block at its own base,
tagging them `<run>[0]`, `<run>[1]`, …

`--dump-blocks 1` returns `CLIENT_SCRIPT_DUMP_MEMORY` itself, byte for byte, so the single-block path is
untouched.

### `anchors`

Asks the CPU for the addresses nothing else can supply. It writes eleven words into
`client->sendBuffer` and widens `link->sendSize` to 44; it repoints nothing, because
`CLI_LOAD_TOSS_RESPONSE` has already aimed `link->sendBuffer` at `client->sendBuffer`
[`MysteryGiftClient_InitSendWord`, mystery_gift_client.c:91].

| word | what | measured |
| --- | --- | --- |
| 0 | `sub ip, pc, #8`: where the console put the code | 0x0201C000 |
| 1 | `lr`: the ROM address after the call [mystery_gift_client.c:276], bit 0 set because the caller is THUMB | 0x08148C75 |
| 2 | `sp` | 0x03007DB8 |
| 3 | `r0` = `&client->param`, so where `AllocZeroed` put the client in `gHeap` | 0x020020D4 |
| 4-5 | gSaveBlock2Ptr, gSaveBlock1Ptr | 0x02024598, 0x0202553C |
| 6-9 | the four AllocZeroed buffers: send, recv, script, msg | 0x02006510 .. 0x02007140 |
| 10 | `link->sendBuffer` as InitSend left it; must equal word 6 | 0x02006510 |

Word 1 is the point: an absolute ROM address of a code site nameable in the decomp, so anything whose
distance from that call site is known becomes reachable. Word 10 equalling word 6 confirms every struct
offset computed from r0 against the console. The four buffers are 0x410 apart, 1024 bytes plus a
16-byte block header, so `gHeap`'s allocator behaves as `malloc.c` describes.
`buffer_script.describe_anchors` prints all eleven with every consistency check it can make.

### `save-write`

Copies its payload tail into the block and then points `link->sendBuffer` at the destination, so
what comes back over the air is what is now in the console's save rather than a copy of what was asked
for. One run writes and proves the write. The session ends in `CLI_MSG_BUFFER_SUCCESS`, which sends the
console to `MG_STATE_SAVE_LOAD_GIFT`, so the write reaches flash.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-write --dump-block sav2 \
        --dump-offset 0xB20 --write-text "some text" --version firered

The guard is the important part. `build_save_write` refuses by default any span that is not inside a
region the game never reads: `filler_90[8]` at 0x090 and `filler_B20[0x400]` at 0xB20 in
`struct SaveBlock2` [global.h:345,357], neither referenced anywhere in `src/`. A write ending four bytes
past `filler_B20` lands in `encryptionKey`, which money is XORed with, so getting this wrong scrambles a
game rather than failing a run. `--write-unsafe` is the deliberate override.

A write survives a reload from the title screen, so `SaveBlock2` really comes back from flash.

### `memory-scan`

Takes a 32-bit needle and a range. Each call scans its budget of 32-byte blocks, writes the cursor back
into its own image and returns 0; the call that reaches the end repoints `link->sendBuffer` at its
result block and returns 1. The image opens with a branch over its own parameter block, so every offset
is fixed by construction:

| offset | |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | cursor: the start address, advanced by the payload |
| 0x008 | end |
| 0x00C | needle |
| 0x010 | blocks per call |
| 0x014 | max_calls, the watchdog |
| 0x018 | result: matches found, final cursor, calls used, matches stored |
| 0x028 | result: 64 × (address, value) |
| 0x228 | the code |

The budget is the design. The console is holding an RFU link open while this runs, so a call that
overruns its frame costs frames the link needs. The inner loop is an `ldmia` of eight words and eight
chained `cmpne`s, about 14 ARM instructions per eight words; the default 512 blocks is 7703 instructions
a call, measured under unicorn. Out of EWRAM (a 16-bit bus, ~6 cycles an ARM fetch) that is roughly
60000 of a frame's 280896 cycles. The whole 16 MB cartridge is 1024 calls, about 17 seconds, one run.
`--scan-blocks` is the dial. In practice the host's status lines read ~60 child frames a second
throughout.

The watchdog is not optional. `max_calls` is patched in beside the range and defaults to what the
range needs plus two; a watchdog stop still answers, with a cursor short of the end saying where to
resume.

The answer is a fixed 528 bytes however many matches there are, so the host's length check
(`len(dump) == buffer_dump_size`) stays the proof that the payload repointed the send. `found` counts
every match; `hits` holds the first 64.

`memory-scan` reads with `ldmia`, so it only ever sees word-aligned matches. A needle at an entry
offset that is never word-aligned for the real stride returns zero and looks like a missing table.

### `table-scan`

Finds a table by its *shape* rather than by a constant it contains. `gSpecialVars` is 21 words holding
the addresses of the special script variables [data/event_scripts.s:51], and every one of those
addresses is the unknown, but `gSpecialVar_0x8000` through `0x800B` are twelve `u16`s declared
consecutively [event_data.c:16] and `gSpecialVars` lists them in var-id order, so its first twelve words
each sit exactly 2 above the one before.

`table-scan` finds every maximal run of `runlen` words where each is exactly `delta` above its
predecessor, and answers with where the run starts and what value it starts with, which for
`gSpecialVars` *is* `&gSpecialVar_0x8000`, so locating and reading are one run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script table-scan --table-delta 2 \
        --table-runlen 12 --table-start 0x08140000 --table-end 0x08400000 --version firered

The run is exactly twelve. `gSpecialVars` continues past entry 11, but entry 12 is
`gSpecialVar_Facing`, declared after `Result` and `LastTalked`, so it is +6 from entry 11 and the
ascending run stops. Asking for 13 finds nothing against the real table, which is the check that the
fingerprint matches the shape rather than merely "some pointers".

A shape test is ~7 ARM instructions a word where a value test is ~1.75, so
`TABLE_SCAN_DEFAULT_BLOCKS` is 192 blocks of 16 bytes, the same per-call load as `memory-scan`'s 512
blocks of 32.

Run state is the new mechanic. A value search is memoryless; a run has to be carried across the
`ldmia` boundary *and* the frame boundary, because the table may straddle either. `run`, `runstart` and
`expect` live in the image at 0x22C..0x234 beside the cursor and are saved on the way out of every
yield.

One edge: `expect` starts at 0, so if the first word of the range happens to be 0 it is credited to a
run whose `runstart` was never written and reads back as 0. `read_table_scan` discards any hit outside
the range that was asked for.

The same shape finds a live `struct ScriptContext` in EWRAM. `InitScriptContext` stores a command
table and its end as adjacent words at +0x5C and +0x60 [include/script.h], so a 17-entry table makes
them exactly 68 apart: `--table-delta 0x44 --table-runlen 2` over EWRAM answers with the context's
address and, as its value, the table's. The context is zero until a script has run, and 0 and 0 are not
68 apart, so the scan has to follow a Mystery Event gift in the same boot. The control costs
nothing: `--table-delta 0x358` (856 = 214 entries) finds the field script context instead, whose
`cmdTable` is `gScriptCmdTable`, an address already measured.

### `rng-trace`

Samples a word once a frame and, between the two reads of each sample, calls a ROM function.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script rng-trace --trace-address 0x03004220 \
        --trace-call 0x080486B1 --trace-samples 96 --version firered

The call is `mov lr, pc; bx r2`, pc reads as that instruction + 8, which is the instruction after the
`bx`, with bit 0 clear so the callee returns to ARM state. With `--trace-call 0` it is a plain per-frame
sampler; it is a general "call this and watch what it changes" harness rather than an RNG tool. See
[the RNG](frlg_rng.md) for what it settled.

### `string-gather`

Dereferences a table of pointers. Given the address of the first pointer, a stride and a count, it
copies each string pointed at, bytes up to and including the 0xFF terminator, into one contiguous
answer, and reports where a following run should resume.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script string-gather \
        --gather-address 0x083E0D54 --gather-count 69 --gather-stride 12 --version firered

`--gather-stride` is 12 for `struct EasyChatWordInfo`, whose `text` is at offset 0; a plain array of
`const u8 *` is 4. The answer is a fixed 776 bytes, four header words then up to 760 bytes of strings.

It never truncates. A string that does not fit ends the run before it, and `next` names the entry to
resume from; a half-copied word would be indistinguishable from a French word that really is that short.
`--gather-maxlen` bounds the walk (64 by default), because a pointer that is not a string would
otherwise be copied until it happened to meet an 0xFF.

### `create-mon`

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```

Four arguments in `r0..r3` and four on the stack. `asm/create-mon.s` is written against the console's
own prologue rather than against a calling convention taken on trust:

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)

so the four go at `sp+0..sp+12` in whole words at the moment of the call. The callee does not pop them,
so the payload takes the 16 bytes back itself, and returning at all is the proof that it did, because a
payload that forgot would pop a garbage `lr`.

The destination is the payload's own image. `CreateMon` writes 100 bytes wherever it is pointed, and
the only interesting address on the console is the player's live save, so the mon is built inside the
1024 bytes the payload was copied into, with 32 bytes of guard between it and the first instruction, and
read back from there. `--create-mon-destination ADDR` copies the finished 100 bytes onward afterwards
and needs `--write-unsafe`.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` defaults to `CreateMon | 1` from `rom_map.py`; `--create-mon-call 0` calls nothing
and answers the zeroed buffer, which checks the send path with the ROM left out. The answer is a fixed
116 bytes, four header words then the 100-byte `struct Pokemon`, and `*param` comes back as the mon's
personality.

The answer verifies itself. The 48-byte substruct region is encrypted with `personality ^ otId` and
checksummed, so a valid checksum means those two words are the ones the ROM used. `check_create_mon`
then checks species, level and the IVs out of the decrypted substructs, and
`scratchpad/verify_create_mon.py` predicts the thirteen fields the ROM *derives*: exp from
`gExperienceTables[growthRate][level]`, friendship and the ability slot from `gSpeciesInfo`, the initial
moveset and its PP from the level-up learnset, and all six stats from `CalculateMonStats`.

The nickname is deliberately not predicted. `CreateBoxMon` fills it from `gSpeciesNames`
[pokemon.c:1810], the French table on this cartridge, so whatever comes back is a *reading* of it.

Three fields the payload cannot predict are measurements of the console:

| field | value | what it says |
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` is LANGUAGE_FRENCH [global.h:22] |
| `metGame` | 4 | `gGameVersion` is VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | `GetCurrentRegionMapSectionId()` [overworld.c:1265], where the player was standing |

`buffer_script.shiny_personality(tid, sid)` gives a `fixedPersonality` that makes the mon shiny for a
console whose secret ID has been read out of its save.

Offline, two THUMB stubs stand in for `CreateMon` at whatever address the payload was built to call:
`CREATE_MON_ARG_MODEL` writes `r0..r3` and the four stack arguments into the destination as eight words,
so the answer names each one; `create_mon_copy_model(source)` copies 100 bytes a caller prepared, so a
mon built in Python travels the whole path.

#### `--create-mon-append`

It writes `gPlayerParty`, not the save block's party.

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```

Appending into the save block reports success, and the mon is gone: the console saves seconds later and
copies the live array back over it [load_save.c:160,196]. A successful-looking answer from a payload
is not confirmation that anything happened.

The slot is always the first free one. It writes at `slot == playerPartyCount` and then raises the
count, which is what the game does when a mon is caught. An occupied slot is never touched, so the write
cannot destroy a Pokemon however wrong everything else is, structural rather than a check that could be
got past. A full party writes nothing and says so. The answer grew a fifth word past the mon for this
(`countBefore | slot << 8 | status << 16`, status 0 not asked / 1 appended / 2 party full / 3 dry run).

Two refusals are built in: an append together with an absolute `--create-mon-destination` is two answers
to the same question, and an append with `--create-mon-call 0` would put a hundred zero bytes in the
party.

    # dry run first: the same code with the two stores left out
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --version firered

The dry run reports the party count and the address it *would* write, and reads that slot's current 100
bytes back in place of the mon it built, so the answer says what a real run would overwrite. It is the
only thing that catches a `playerPartyCount` disagreeing with what is actually in the party.

An empty party slot is not a hundred zero bytes. `ZeroMonData` zeroes everything and then ends
`arg = MAIL_NONE; SetMonData(mon, MON_DATA_MAIL, &arg)` [pokemon.c:1737], and `mail` is at offset 0x55,
so an empty slot carries `0xFF` there. `buffer_script.EMPTY_PARTY_SLOT` is that shape and
`is_empty_party_slot` is the check.

Where an address may be hardcoded, and where it may not:

| | moves? | so |
| --- | --- | --- |
| `gSaveBlock1Ptr` | yes, a random 4-aligned offset re-rolled on every battle and load [`SetSaveBlocksPointers`, load_save.c:75] | take it from `r1`/`r2` every call |
| `gPlayerParty` | no, a link-time EWRAM global | an address is legitimate |

Measured: `gSaveBlock1Ptr` was 0x0202559C and then 0x02025550 six minutes apart with no reboot, 76
bytes, inside the 0..124 the mask allows.

`gPlayerParty` = 0x02024280 and `gPlayerPartyCount` = 0x02024025 were found by finding a Pokemon
rather than by looking where predicted: `scratchpad/find_party.py` walks every 4-aligned window of a
dump and reports the ones that decode as a `struct Pokemon` with a valid checksum. Exactly one did, and
the species, level, nickname and OT in it were things only the player's console knew.

### `call`

The general form: an address, up to eight argument words, the `r0` that comes back, and one address
read either side of the call.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script call \
        --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220 --version firered

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  result      calls used, function, argc, r0, *watch before, *watch after

`asm/call.s` pushes the sixteen bytes for every call whatever `argc` says, because the callee never pops
them and a function taking fewer simply does not read them.

`SeedRng` returns nothing:
`void SeedRng(u16 seed) { gRngValue = seed; }` [random.c:15], so a return value would prove only that
*something* ran. Reading `gRngValue` immediately before and after is the only thing that says the call
did what it was called for. The payload writes nothing itself; what the callee writes is the whole risk,
so an address that has not been read as code first has no business here.

The console's own `SeedRng` bytes are the offline fixture: `tests/test_buffer_script.py` executes them
under unicorn through the payload. The eight-argument path is checked with powers of two as the
arguments, so the returned sum names exactly which slots arrived.

### `call-chain`

Up to sixteen steps in order in a single frame, one answer word per step. Every question about the
console's game state is *read it, change it, read it back*, and the expensive thing is the run rather
than the call.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script call-chain \
        --chain-step call:FlagGet,0x828 \
        --chain-step call:FlagSet,0x828 \
        --chain-step call:FlagGet,0x828 --version firered

A step is 24 bytes, an op word, a target, and four argument words, and the ops are `call`,
`read32`/`read16`/`read8` and `write32`/`write16`/`write8`. `--chain-step` takes them as
`OP:TARGET[,ARG]...`, where a call's target may be one of the functions this project has measured
(`rom_map.CALLABLE`) rather than an address. A name the decomp knows is not enough: the decomp's
addresses are a different build's.

`prev` exists for one shape. A step can take its target or its first argument from the previous
step's result:

    --chain-step call:GetVarPointer,0x4024      prev = the address the GAME computed
    --chain-step read16+keep:prev               the value before, prev untouched
    --chain-step write16:prev,7                 the store, read back by the payload itself
    --chain-step read16:prev                    the value after

There is no `VarSet` among the ScrCmd workers: `ScrCmd_setvar` writes through `GetVarPointer`'s return
[scrcmd.c:472], so setting a var the game's own way is a call followed by an indirect store. (The
Mystery Event VM does reach a real `VarSet`; see [The ROM map](frlg_rom_map.md).) Two rules keep the
sequence honest, and both live in the payload rather than the builder:

- a write never becomes `prev`, so a pointer survives the store made through it;
- a read does, unless the step carries `+keep`, which is exactly what a read *before* the write
  needs.

Every write reads itself back, and that read is what lands in the answer. A write whose value does
not come back is a refused write or a target that is not what it was thought to be, and there is no
other way to tell those apart from here.

    0x000  b .Lcode
    0x004  count       how many steps are meant, 0..16
    0x010  steps[16]   {op, target, a0, a1, a2, a3}, 24 bytes each
    0x190  result      calls, count, steps executed, the op word that stopped it
    0x1A0  values[16]  one word per step, in order

A chain cannot fail silently: an opcode the payload does not have stops the run and is named in the
answer beside everything that did run, and the step count is capped in the ARM as well as in the
builder.

What the builder refuses, all offline: an empty chain, more than sixteen steps, a call to an ARM
pointer or to an address outside the cartridge, a call whose target comes from `prev` (an address
computed on the console cannot be checked from here, and a wrong one hangs the menu), an unaligned or
unreachable read, more than four arguments, and any write at all without `--write-unsafe`. Unlike
`save-write` there is no scratch region to be safe in: a chain writes wherever the game keeps the thing
being changed, and the console commits its save to flash afterwards.

Measured examples:

    call GetVarPointer(0x4024)   -> 0x020265B4
    read16 [prev] keep           -> 0
    write16 [prev] = 3           -> 3        the store, read back by the payload
    read16 [prev]                -> 3
    call VarGet(0x4024)          -> 3        the game's own reader, same frame

and, in a later session with a third `gSaveBlock1Ptr` base, the var behind that pointer still read 3,
which is why a var write goes through `GetVarPointer` rather than a computed address.

Money is encrypted, `*moneyPtr ^ gSaveBlock2Ptr->encryptionKey` [money.c:14], and one chain reads both
sides with an address the host cannot know and an offset added on the console:

    read32 [0x03004228]              -> 0x02025554     gSaveBlock1Ptr
    read32 [prev + 0x290] keep       -> 0x93E78EEE     the ciphertext, before
    call GetMoney(prev + 0x290) keep -> 0x00034103     213251, the plaintext
    call AddMoney(prev + 0x290, 1234) keep
    call GetMoney(prev + 0x290) keep -> 0x000345D5     214485, exactly +1234
    read32 [prev + 0x290]            -> 0x93E78A38     the ciphertext, after

Both XOR pairs give **0x93E4CFED**, which reads back directly out of SaveBlock2 + 0xF20.
`rom_map.SAV1_MONEY`, `SAV2_ENCRYPTION_KEY` and `CALLABLE` hold all of it.

A special reads its operands out of the special vars, so calling one is write, call, read: setting
`gSpecialVar_Result` to `GET_CARD_BATTLES_WON` and calling special 390 answered 3, with the raw word at
`SaveBlock1 + 0x3434` reading 3 in the same frame.

None of the warp or message workers may be called from a buffer script: they run inside the Mystery
Gift menu, where there is no overworld. They belong to a [field stub](frlg_rng.md#the-payload-in-the-script-body).

# Reading the save

A Mystery Gift session reads the console's live save and prints what the game never shows: the secret
ID, and every party Pokemon's PID, IVs and nature. One run, the console never leaves its Mystery
Gift menu, nothing is written and no Wonder Card changes hands.

## Trainer ID and secret ID

SaveBlock2 offset 0 holds the player name, gender, the 32-bit trainer id and the play time
[global.h:327]. The low half is the TID printed on the trainer card; the high half is the secret ID,
which appears nowhere in the game and travels in no link message.

    sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
        --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

    ./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2

    dump.bin: 64 bytes from sav2 + 0x0
      playerName    'PLAYER'
      gender        boy
      trainerId     0xE5BBDF65  TID 57189  SID 58811
      playTime      148h 12m 30s

The TID is the check: it must match the number on the console's own trainer card. A dump that disagrees
is a bad read, whatever else it says.

## The party

SaveBlock1 0x34 is `playerPartyCount`, then `playerParty[6]` at 0x38, 100 bytes each [global.h:772]. Six
slots is 604 bytes, inside the 1024-byte per-run limit.

    sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
        --buffer-script save-dump --dump-block sav1 --dump-offset 0x34 \
        --dump-size 608 --dump-file party.bin

    ./.venv/bin/python tools/frlg/dump_read.py party.bin --block sav1 --offset 0x34 \
        --tid 57189 --sid 58811

    party.bin: 608 bytes from sav1 + 0x34
      playerPartyCount 5
      slot 1: ARCANINE  Lv72 nick='ARCANIN' OT='PLAYER' PID=0x30353ACA Lonely  IVs=[18,17,20,31,2,10] checksum ok
      slot 2: LUGIA     Lv77 nick='LUGIA'   OT='PLAYER' PID=0x91F854FF Relaxed IVs=[21,9,11,31,28,21] checksum ok

IVs read HP, ATK, DEF, SPE, SPA, SPD. Pass `--tid`/`--sid` to fill in the shiny column; without them it
is left blank rather than guessed. Every stored mon carries a checksum over its substructs, so
`checksum ok` on every slot means the dump is a real party rather than a stale buffer.

Party mons are stored exactly as a `.pk3`/`.ek3` stores them, which is why `pokeldn.frlg.save.mon`
decodes them unchanged: the 48 bytes at offset 0x20 are XORed with `PID ^ OTID`, and the four substructs
inside are ordered by `PID % 24`.

## Two things that will bite

The party the game plays with is not the party in the save block. `SavePlayerParty` copies
`gPlayerParty` into `gSaveBlock1Ptr->playerParty` when the console saves [load_save.c:160], so SaveBlock1
holds the party as of the last save. For the live one, dump `gPlayerParty` by address, 0x02024280 on
both measured cartridges, with `gPlayerPartyCount` at 0x02024025:

    --buffer-script memory-dump --dump-address 0x02024280 --dump-size 600

Save block addresses move. `SetSaveBlocksPointers` re-rolls them by a multiple of 4 in 0..124 on
every battle and every load [load_save.c:75]. Never carry an absolute save address from one run to the
next; `save-dump` takes the pointers fresh every call.

## What else the same payload reaches

Money at SaveBlock1 0x0290, XORed with `SaveBlock2.encryptionKey` at 0xF20; the bag; and the flags and
vars. `memory-dump` takes an absolute address instead of a save block and so reaches IWRAM, including
`gRngValue`, see [the random number generator](frlg_rng.md).
