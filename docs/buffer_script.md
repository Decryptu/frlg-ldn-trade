---
title: Native code on the console
parent: Inside the console
nav_order: 2
---

# CLI_RUN_BUFFER_SCRIPT: native code on the console

`CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands our bytes to a 17-opcode interpreter.
`CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the CPU.

## What the console does

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
[decomp:src/mystery_gift_client.c:237,276]

Five facts follow from those nine lines, and every payload here rests on them.

- **1024 bytes**, copied whole (`MG_LINK_BUFFER_SIZE`) whatever we actually sent, so a payload runs
  with the tail of the previous receive behind it and must be self-contained.
- **Three arguments**: `r0 = &client->param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr`. Both
  save blocks, by pointer, readable and writable.
- **A return channel.** `client->param` is what `CLI_LOAD_TOSS_RESPONSE` ships back as
  `MG_LINKID_RESPONSE` [mystery_gift_client.c:204], the same channel the Mystery Event VM's status
  uses. Whatever the payload leaves in `*param` reaches us.
- **Called once per frame until it returns 1.** A payload that returns anything else is re-entered
  next frame; one that never returns 1 hangs the Mystery Gift menu with no way out.
- **ARM state, not THUMB.** The caller reaches it with a `bx` through a function pointer, which
  takes the state from bit 0 of a word-aligned address.

`gDecompressionBuffer` is at **0x0201C000**. That started as a deduction from `ld_script.ld`, which
puts `ewram` at 0x2000000 under `ALIGN(4)`, reserves `gHeap` for 0x1C000, then links
`src/main.o(ewram_data)` first, whose first `EWRAM_DATA` is `gDecompressionBuffer` [src/main.c:87].
`anchors` later measured it. Payloads are position independent either way.

## Our side

- `asm/*.s` - one ARM source per payload, assembled by `scripts/gen_buffer_scripts.py` into
  `frlgsim/buffer_payloads.py`. The machine code is committed so a live host needs no GBA
  toolchain; `tests/test_buffer_script.py` re-assembles and compares whenever `arm-none-eabi-as` is
  installed, which keeps the two honest.
- `frlgsim/buffer_script.py` - the payload registry, the validation, and `emulate()`, which runs a
  payload under unicorn on the GBA memory map with the console's three arguments. A payload that
  faults, or never returns 1, is caught there and never reaches the air.
- `frlgsim/mg_script.py` - `CLIENT_SCRIPT_RUN_BUFFER` (recv, run, load the return channel, send it,
  recv the next script) and `CLIENT_SCRIPT_BUFFER_SUCCESS`.
- `frlgsim/mg_server.py` - `SCRIPT_RUN_BUFFER_SCRIPT`. No card, no toss prompt, no branch on what
  the console holds: a buffer script is not a gift, so a console carrying any card takes the same
  path and keeps it.
- Both simulated consoles execute the payload for real: `frlgsim/mg_client.py` and
  `ConsoleClientModel` in `tests/test_mystery_gift_flow.py`, which is written from the decomp
  independently and models the once-per-frame re-entry.

## Running it

Offline first, every time:

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v

On hardware (tags `bsNN`; FireRed or LeafGreen, no Pokemon Center involved):

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  ./scratchpad/run_mg_fast.sh bsNN --buffer-script --version firered
    (them) join PkCamp when it appears

There is no replace-card prompt and no card: a console holding any Wonder Card keeps it.

## `trainer-id-probe`: does native code run at all

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```

24 bytes, reads only. It is a probe chosen so one run decides everything, because the answer is a
value we already know by another route: the console put its own `playerTrainerId` into the
`MysteryGiftLinkGameData` it sent us seconds earlier [mystery_gift.c:337]. Our ARM code reads the
save directly and the host compares the two.

- The two agree: the payload ran, in ARM state, with the arguments the decomp promises, against the
  real `gSaveBlock2Ptr`, and returned 1.
- A different value: it ran, but the arguments or the offsets are not what we think.
- No `Buffer script status:` line at all: the client script shape is wrong, or the console never
  reached the call.

One nuisance is handled: a 7-character player name's terminator overwrites `playerTrainerId[0]` on
the way into the game data [mystery_gift.c:364], so with a name that long the host compares the top
three bytes and says so. The save read is unaffected.

The console is told the verdict in a message we compose. `CLI_MSG_BUFFER_SUCCESS` on a match sets
`successMsg`, so the console saves; `CLI_MSG_BUFFER_FAILURE` returns it to the menu. Both print
`data->clientMsg`, our own 64 bytes [mystery_gift_menu.c:943,1353].

**bs01 (2026-09-04), reproduced by bs03:**

    Console identified itself: 'PLAYER' (TID 57189) on FireRed, holding card flagId 1009
    Buffer script status: 0xE5BBDF65 MATCHES 0xE5BBDF65 (the trainer id from the console's own game data)

0xE5BBDF65's low half is 0xDF65 = 57189, the trainer ID on the player's own card, so the value
checks a third way. The console carried card flagId 1009 in and out with no replace-card prompt.

**Trap, from bs01: `charmap.encode` drops every character it does not know, newline included.** The
console printed `ly. code ran and read yourTRAINER IDc`: a 47-character line overflowed window 1's
pixel buffer and wrapped inside it. The game's line break is 0xFE. `mg_server`'s encoder splits on
`\n` and joins on 0xFE, and refuses offline both a third line and a line wider than the ROM's own
longest string in that window - "A WONDER CARD has been received", 31 characters
[decomp:src/strings.c:1291]. Window 1 is 28 tiles by 4 [mystery_gift_menu.c:97,524], so two lines
were always fine; only the missing 0xFE was not.

## Reading memory: `save-dump` and `memory-dump`

`r0` is `&client->param`, so the whole of `struct MysteryGiftClient`
[decomp:include/mystery_gift_client.h:71] sits at fixed offsets from it:

| field | from `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

`MysteryGiftLink_InitSend` stores the **pointer** it is given [mystery_gift_link.c:59], and the CRC
is taken later, at send time, over `link->sendBuffer` for `link->sendSize` bytes
[mystery_gift_link.c:166]. So a payload running between the InitSend and the send can point the
console's own outgoing message at any address, and the console reads that region out and CRCs it
for us. The client script order is the whole trick:

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

Swap the middle two and the payload patches fields the InitSend is about to overwrite.

`memory-dump` takes an absolute address. `save-dump` needs none: the console hands the payload
`gSaveBlock2Ptr` in r1 and `gSaveBlock1Ptr` in r2, so it reads either save block at any offset on
any console and any build. Up to 1024 bytes a run - `MGL_Receive` rejects more
[mystery_gift_link.c:102].

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-dump --dump-block sav2 \
        --dump-size 256 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script memory-dump --dump-address 0x0201C000 \
        --version firered

The evidence line is `Buffer script dump: N bytes of console memory, head ...`. Both simulated
consoles honour a repointed send, so the session is proven offline first, including that the host
accepts 1024 bytes on an ident that normally carries 4:

    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script save-dump \
        --dump-block sav1 --dump-offset 0x38 --dump-size 608

What this reaches that nothing else does: `SaveBlock1.playerParty` at 0x0038 (the whole party's PIDs
and IVs), `money` at 0x0290 XORed with `SaveBlock2.encryptionKey` at 0xF20 [money.c], the bag, flags
and vars, and through `memory-dump`, IWRAM where `gRngValue` lives. None of it is reachable by any
Mystery Event opcode or link message. [Reading the save](reading_the_save.md) is the how-to;
`tools/dump_read.py` decodes what comes back.

Runs: bs04 read SaveBlock2 (256 bytes, struct SaveBlock2 exactly as [global.h:327] lays it out -
`PLAYER` at 0x00, gender 0 at 0x08, trainerId 0xE5BBDF65 at 0x0A, playTimeHours 148 at 0x0E).
bs06 read the whole party at 608 bytes. bs07 read 1024 bytes of the cartridge at 0x08000000:

    entry      b 0x08000204
    title      POKEMON FIRE          [0xA0]
    game code  BPRF                  [0xAC]  BPR = FireRed, F = French
    version    0x0a                  [0xBC]
    header checksum 0x5d, recomputed 0x5d -> VALID

**The Switch release ships software version 0x0A**, read off the cartridge rather than inferred, so
the `REVISION >= 0xA` branches this project reads are confirmed to be the ones running.

## The mirror rule, and why bs05 died

This governs every activity, not just Mystery Gift, and it is the first thing to check on any stall
while the console is *sending*.

`MGL_Send` chunks at 252 bytes and waits on `MGL_HasReceived(link->sendPlayerId)` before each chunk
and once more before it finishes [mystery_gift_link.c:176,205]. `sendPlayerId` is **1, the console's
own multiplayer id** - `MysteryGiftClient_Init(sClient, 1, 0)` [mystery_gift_client.c:33]. So
`MGL_HasReceived(1)` is `gRfu.blockReceived[1]`, and on a child that is set only when the console's
own block comes back complete through **row one of the parent's gRecvCmds table, the copy we
mirror**. `RfuHandleReceiveCommand` runs the block reassembler over every player including the child
itself [link_rfu_2.c:1125], and `RfuMain1_Child` fills gRecvCmds from the parent's table, its own row
included [:970]. The console's RFU block sender waits on the same mirror: `HandleBlockSend` holds
the INIT until it sees the INIT mirrored, `SendLastBlock` repeats the last fragment until it sees
that mirrored, then re-queues every fragment missing from the mirrored bitmask
[HandleSendFailure, link_rfu_2.c:1366-1416]. The console cannot name the fragment it is missing; it
can only notice its own bitmask is short and send everything again.

Our leader used to bound that mirror at the newest two commands (`ECHO_MAX = 2`, added after lg122
where an unbounded FIFO fell 0.5 s behind). bs05's console emitted a 21-fragment chunk partly in
bursts - two commands in one frame, four in the next - and the bound ate four of them:

    scratchpad/echo_gaps.py scratchpad/bs05.pcap
    [  4] t=  10.992 count= 21 sent= 21/21 mirrored= 20/21 never=[13] repaired_by_console=[13, 16, 17, 18]

13, 16, 17 and 18 are exactly what the console then re-sent. The repair for 13 was dropped a second
time and the console declared link loss. Every block of bs01, bs03 and bs04 reads `never=[]`; across
five captures the only run that died is the only run with a fragment we never gave back. So 608
bytes was never a ceiling and 256 was never a safe number - three chunks are three times the
exposure of one, and bs04 got lucky.

**`rfu_leader.ChildEcho` is the fix, and it is two rules:**

- **Never drop a distinct command.** A dropped fragment is a repair round the console runs blind.
- **Coalesce a repeat that is still waiting.** `SendLastBlock` re-sends the same fragment every
  frame while it waits; mirroring each repeat is what put lg122's row one 0.5 s behind. One entry
  is enough. A repeat arriving after the mirror has gone out is a new question and is answered.

The child sends exactly one command per parent frame it receives [`childSendCount` increments only
on `recv.newDataFlag`, link_rfu_2.c:600], so mirror in and mirror out are 1:1 and the queue cannot
grow on its own. Nothing extra goes on the air - the same parent frames carry the same rows.
`ConsoleClientModel` models the mirror rather than a fixed `echo_delay`. Measured over a 608-byte
dump with bursts of four every frame: the old bound dropped 628 echoes and caused 156 console
repairs; `ChildEcho` drops none and causes none.

bs06 confirmed it on hardware first try: thirteen console blocks, four of them full 21-fragment
chunks, `never=[]` on all of them, `row-one echo backlog 1 (peak 3), 85 repeat(s) folded, none
dropped`.

**On any stall while the console is sending, run `scratchpad/echo_gaps.py <host capture>` first.**
`never=[]` on every block, or nothing else in the capture matters.

One thing that was in the evidence all along: the console's READY_END (ident 20) is a 1024-byte
message, which MGL_Send splits into a header plus five chunks, and `echo_gaps.py` finds it in bs01
as blocks 5-10. The console had been completing five-chunk sends since the first buffer-script run,
so "the handshake supply runs out at four chunks" was dead on evidence already in hand.

## `anchors`: asking the machine where it is

Every other payload works from the two pointers the console hands us. `anchors` asks the CPU for the
addresses nothing else can supply: it writes eleven words into `client->sendBuffer` and widens
`link->sendSize` to 44. It repoints nothing, because CLI_LOAD_TOSS_RESPONSE has already aimed
`link->sendBuffer` at `client->sendBuffer` [MysteryGiftClient_InitSendWord,
mystery_gift_client.c:91]. (Both simulated consoles honour a resized send as well as a repointed
one - `ClientState.send_changed` - because MGL_Send reads both fields at send time.)

| word | what | bs08 read |
| --- | --- | --- |
| 0 | `sub ip, pc, #8`: where the console put our code | 0x0201C000 |
| 1 | `lr`: the ROM address of the instruction after the call [mystery_gift_client.c:276], bit 0 set because the caller is THUMB | 0x08148C75 |
| 2 | `sp` | 0x03007DB8 |
| 3 | `r0` = `&client->param`, so where AllocZeroed put the client in gHeap | 0x020020D4 |
| 4-5 | gSaveBlock2Ptr, gSaveBlock1Ptr | 0x02024598, 0x0202553C |
| 6-9 | the four AllocZeroed buffers: send, recv, script, msg | 0x02006510 .. 0x02007140 |
| 10 | `link->sendBuffer` as InitSend left it; must equal word 6 | 0x02006510 |

Word 1 is the point: an absolute ROM address of a code site we can name in the decomp, so anything
whose distance from that call site is known becomes reachable. bs07 identified the build; this
locates it. Word 0 turned the `ld_script.ld` deduction into a measurement. Word 10 equalling word 6
confirms every struct offset this project computes from r0 against the console rather than against
the header file. The four buffers are 0x410 apart - 1024 bytes plus a 16-byte block header - so
gHeap's allocator behaves exactly as `malloc.c` describes.

`buffer_script.describe_anchors` prints the eleven words with every consistency check it can make,
because an address that looks plausible but is not self-consistent is worse than no address.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script anchors --version firered

## `save-write`: writing to the live save

A pointer takes a `strb` as readily as a `ldrb`. `save-write` copies its payload tail into the block
and then points `link->sendBuffer` **at the destination**, so what comes back over the air is what
is now in the console's save rather than a copy of what we asked for. One run writes and proves the
write. The session ends in CLI_MSG_BUFFER_SUCCESS, which sends the console to
MG_STATE_SAVE_LOAD_GIFT, so the write reaches flash.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-write --dump-block sav2 \
        --dump-offset 0xB20 --write-text "FRLG-LDN bs09" --version firered

**The guard is the important part.** This is the player's real save and the console commits it to
flash. `build_save_write` refuses by default any span that is not inside a region the game never
reads: `filler_90[8]` at 0x090 and `filler_B20[0x400]` at 0xB20 in struct SaveBlock2
[decomp:include/global.h:345,357], neither referenced anywhere in `src/`. A write ending four bytes
past `filler_B20` lands in `encryptionKey`, which money is XORed with, so getting this wrong
scrambles a game rather than failing a run. `--write-unsafe` is the deliberate override.

bs09 wrote 13 bytes and read back `46524c472d4c444e2062733039` = "FRLG-LDN bs09", from
`link->sendBuffer` pointed at the destination inside SaveBlock2 - the console reading out its own
save after our ARM code wrote there, not an echo of what we sent. bs10 then reloaded the game from
the title screen, so SaveBlock2 came from flash rather than RAM, and a plain `save-dump` of the same
offset still returned it.

## The ROM, read as code

bs08 gave one address inside the cartridge; two read-only dumps turned it into a symbol map.
`scratchpad/rom_read.py` is the loop: dump a caller, disassemble, read its literal pool and `bl`
targets, dump any pointer table it names, then check every entry lands on a prologue the
disassembly already showed.

**bs11** dumped 1024 bytes at 0x08148A00, which disassembles as `Client_RunBufferScript` exactly as
[decomp:src/mystery_gift_client.c:274] writes it, with `cmp r0,#1` at 0x08148C74 - the anchor bs08
measured from the CPU. Its THUMB literal pool holds:

    0x08148C88 -> 0x0201C000   gDecompressionBuffer
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` follows at 0x08148C94, copying eight words onto the stack from
0x0845DBD0 indexed by `client->funcId` at [r0,#8], which names **sClientFuncs** and re-confirms
CLIENT_FUNC_ID = 8 from the machine code.

**bs12** dumped that table: eight THUMB pointers, every one landing on a `push {r4, lr}` bs11 had
already shown, entry 7 reading 0x08148C61 - the function bs08 measured from the other end. Three
runs, three routes, one answer. The five-entry table after it is `sFuncTable` from
mystery_gift_server.c, named by what its code does rather than by position: 0x08148DF0 is
Server_Init's `svr->funcId = FUNC_RUN; return SVR_RET_INIT`, and 0x08148DF8 is Server_Done returning
SVR_RET_END = 3.

`frlgsim/rom_map.py` holds the result with its evidence and `tests/test_rom_map.py` checks it
against the dumps. Nothing in it is inferred from the decomp's English rev-10 build; a symbol that
has not been read off the console does not belong in that file.

## `memory-scan`: searching instead of reading

Every payload above reads a window named in advance, 1024 bytes at a time. The cartridge is 16 MB -
16384 runs - which is why `rom_map.py` grew from one anchor rather than from a search.

The line that changes it had been quoted here from the start and never used:

```c
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)
    {
        client->funcId = FUNC_RUN;      // only then does the client move on
```
[decomp:src/mystery_gift_client.c:276-280]

A payload that returns anything but 1 is called again next frame. `MysteryGiftClient_Run` is reached
from `Task_MysteryGift` [mystery_gift_menu.c:1245], an ordinary task, so "again" means the next
frame, sixty times a second. And the `memcpy` that loads us runs once, at the
`CLI_RUN_BUFFER_SCRIPT` command [:239], not per call. The payload's own image, code and data alike,
is exactly as it left it: **a payload can keep state across frames and resume.**

`asm/memory-scan.s` takes a 32-bit needle and a range. Each call scans its budget of 32-byte blocks,
writes the cursor back into its own image and returns 0; the call that reaches the end repoints
`link->sendBuffer` at its result block and returns 1, like every dump. The image opens with a branch
over its own parameter block, so every offset is fixed by construction rather than recovered from a
disassembly:

| offset | |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | cursor: the start address, advanced by the payload |
| 0x008 | end |
| 0x00C | needle |
| 0x010 | blocks per call |
| 0x014 | max_calls, the watchdog |
| 0x018 | result: matches found, final cursor, calls used, matches stored |
| 0x028 | result: 64 x (address, value) |
| 0x228 | the code |

**The budget is the design.** The console is holding an RFU link open while this runs, so a call
that overruns its frame costs frames the link needs. The inner loop is an `ldmia` of eight words and
eight chained `cmpne`s, about 14 ARM instructions per eight words; the default 512 blocks is 7703
instructions a call, measured under unicorn. Out of EWRAM (a 16-bit bus, ~6 cycles an ARM fetch)
that is roughly 60000 of a frame's 280896 cycles. The whole 16 MB cartridge is 1024 calls, about 17
seconds, one run. `--scan-blocks` is the dial.

**The watchdog is not optional.** This is the first payload whose stopping condition is arithmetic
rather than a straight line, and a payload that never returns 1 hangs the menu. `max_calls` is
patched in beside the range and defaults to what the range needs plus two; a watchdog stop still
answers, with a cursor short of the end saying where to resume.

The answer is a fixed 528 bytes however many matches there are, so the host's length check
(`len(dump) == buffer_dump_size`) stays the proof that the payload repointed the send. `found` counts
every match; `hits` holds the first 64.

Offline, `buffer_script.emulate_repeating` calls a payload until it returns 1 the way the console
does, and `ConsoleClientModel` does the same. What the harness does not model is the frames
themselves; the frame cost is the arithmetic above, not a measurement.

**bs13** searched 4 MB for `RAND_MULT` = 0x41C64E6D [decomp:include/random.h:18], which no ARM or
THUMB instruction can encode, so it sits in `Random`'s literal pool next to `&gRngValue`:

    scan: 11 match(es) for 0x41C64E6D, 256 call(s) = frames, stopped at 0x08400000
       0x080486C8  0x0807D238  0x0807F25C  0x08086AB0  0x080AFC00  0x080F1EA0
       0x080F2378  0x080F2438  0x08122284  0x08122518  0x0814CBFC

256 calls is exactly what the arithmetic said (4 MB / (512 x 32)). `never=[]` on all 13 console
blocks, and the host's status lines read ~60 child frames a second throughout, so ~3 ms of every
frame cost the link nothing.

**Which hit, without spending a run.** `grep -rl 'ISO_RANDOMIZE1\|RAND_MULT' src/` gives eight
files, and `ld_script.ld` puts `src/random.o` at #86 with the next user, `src/title_screen.o`, at
#123. Hits come back in address order and the link order is the address order, so the lowest hit is
random.o's pool. That is an inference from the decomp's *order*, not from its addresses.

**bs14** dumped it. 0x080486B0 disassembles as `Random`, instruction for instruction
[decomp:src/random.c:9-13]:

```
4A04  ldr r2, [pc, #16]   -> 0x080486C4 = 0x03004220   &gRngValue
6811  ldr r1, [r2]
4804  ldr r0, [pc, #16]   -> 0x080486C8 = 0x41C64E6D   RAND_MULT
4348  mul r0, r1
4904  ldr r1, [pc, #16]   -> 0x080486CC = 0x00006073   24691
1840  add r0, r0, r1
6010  str r0, [r2]
0C00  lsr r0, r0, #16
4770  bx  lr
```

`SeedRng` follows at 0x080486D0 and its pool word is 0x03004220 again. Two independent functions
name **gRngValue = 0x03004220** in one dump.

## `rng-trace`: calling into the ROM

An address that was only ever read is a hypothesis. `asm/rng-trace.s` samples a word once a frame
and, between the two reads of each sample, calls a ROM function.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script rng-trace --trace-address 0x03004220 \
        --trace-call 0x080486B1 --trace-samples 96 --version firered

**bs15**, the first call into the console's ROM:

    rng-trace: 96 sample(s) of 0x03004220 over 96 call(s) = frames, calling 0x080486B1
       the LCG recurrence after == before * 1103515245 + 24691 holds on 96/96 samples
       between frames the word changed 95/95 times; the game's own Random calls per frame:
          min 2, max 2, total 190

`after == before * RAND_MULT + RAND_ADD` on 96 of 96 settles three things no single read could: the
address is gRngValue, our ARM payload can `bx` into THUMB ROM and be returned to by the callee's own
`bx lr`, and the function at 0x080486B0 is Random. The call is `mov lr, pc; bx r2` - pc reads as
that instruction + 8, which is the instruction after the `bx`, with bit 0 clear so the callee
returns us to ARM state.

The second answer is about the console rather than us: between our call in one frame and our read in
the next the game had turned the RNG exactly twice, on all 95 gaps. That is FRLG's own Random
consumption while it sits in the Mystery Gift link menu.

The payload was proven offline first by executing the console's own Random - the twenty bytes bs14
read off the cartridge, put back at 0x080486B0 under unicorn.

With `--trace-call 0` it is a plain per-frame sampler. It is a general "call this and watch what it
changes" harness, not an RNG tool.

## `string-gather`: following a pointer array

A dump reads a window, so a table of pointers costs one run for the pointers and another for every
kilobyte they point at, most of it padding. `sEasyChatGroups`' 22 word arrays and their text span
21560 bytes [bs17], two thirds of it `struct EasyChatWordInfo`'s `alphabeticalOrder` and `enabled`
[decomp:include/easy_chat.h:11], neither of which says anything about what the console prints.

This payload dereferences. Given the address of the first pointer, a stride and a count, it copies
each string it points at - bytes up to and including the 0xFF terminator - into one contiguous
answer, and reports where a following run should resume. A whole Easy Chat group a run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script string-gather \
        --gather-address 0x083E0D54 --gather-count 69 --gather-stride 12 --version firered

`--gather-stride` is 12 for `struct EasyChatWordInfo`, whose `text` is at offset 0; a plain array of
`const u8 *` is 4. The answer is a fixed 776 bytes - four header words then up to 760 bytes of
strings - so the host's length check stays the proof that the payload repointed the send. The
evidence line is `gather:`.

**It never truncates.** A string that does not fit in what is left ends the run before it, and
`next` names the entry to resume from. A half-copied word would be indistinguishable from a French
word that really is that short. bs35 took that path on hardware - 83 of STATUS' 109 words, 760 bytes
exactly - and bs36 resumed from the address it reported with nothing lost or repeated.

**`--gather-maxlen` bounds the walk** (64 by default). A pointer that is not a string would
otherwise be copied until it happened to meet an 0xFF. Hitting the bound ends the run and says so
rather than hanging the menu.

Reads only. Proven on hardware bs18-bs36, eighteen runs, all first try;
[the French Easy Chat vocabulary](easy_chat_french.md) is what they read.

## `create-mon`: a ROM call taking eight arguments

`rng-trace` proves the *mechanism* of a ROM call and nothing about passing anything to one.
`CreateMon` is the other end of the range:

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```

Four arguments in `r0..r3` and four on the stack. `asm/create-mon.s` is written against the
console's own prologue rather than against a convention taken on trust - bs42's dump reads:

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)

so the four go at `sp+0..sp+12` in whole words at the moment of the call. The callee does not pop
them, so the payload takes the 16 bytes back itself - and returning at all is the proof that it did,
because a payload that forgot would pop a garbage `lr`.

**The destination is our own image.** `CreateMon` writes 100 bytes wherever it is pointed, and the
only interesting address on the console is the player's live save. So the mon is built inside the
1024 bytes we were copied into, with 32 bytes of guard between it and the first instruction, and
read back out of there. `--create-mon-destination ADDR` copies the finished 100 bytes onward
afterwards - a plain byte copy we can see, rather than aiming a ROM function at a save block - and
needs `--write-unsafe`.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` defaults to `CreateMon | 1` from `rom_map.py`; `--create-mon-call 0` calls
nothing and answers the zeroed buffer, which checks the send path with the ROM left out. The answer
is a fixed 116 bytes - four header words then the 100-byte `struct Pokemon` - evidence line
`create-mon:`, and `*param` comes back as the mon's personality.

**The answer verifies itself.** The 48-byte substruct region is encrypted with `personality ^ otId`
and checksummed, so a valid checksum means those two words are the ones the ROM used.
`check_create_mon` then checks species, level and the IVs out of the decrypted substructs, and
`scratchpad/verify_create_mon.py` predicts the thirteen fields the ROM *derives*: exp from
`gExperienceTables[growthRate][level]`, friendship and the ability slot from `gSpeciesInfo`, the
initial moveset and its PP from the level-up learnset, and all six stats from `CalculateMonStats`.
bs39 read the species table off the console byte-identical to the decomp's, so predicting from the
decomp is sound for everything except text.

**The nickname is deliberately not predicted.** `CreateBoxMon` fills it from `gSpeciesNames`
[pokemon.c:1810], the French table on this cartridge, so whatever comes back is a *reading* of it -
one species a run, by the same route the Easy Chat vocabulary was read.

With TID 57189 / SID 58811, `buffer_script.shiny_personality(57189, 58811)` gives a
`fixedPersonality` that makes the mon shiny for this console, which is possible only because the
secret ID was read out of the save.

### Offline models

The emulated cartridge is a header and zeros, so a payload that calls a ROM function has nothing to
land on. Two THUMB stubs stand in for `CreateMon` at whatever address the payload was built to call,
placed with `memory={address: stub}`:

- `CREATE_MON_ARG_MODEL` writes `r0..r3` and the four stack arguments into the destination as eight
  words, so the answer names each one. It pushes nothing, so `[sp,#0]` *is* the caller's first stack
  argument.
- `create_mon_copy_model(source)` copies 100 bytes a caller prepared over the destination, so a mon
  built in Python travels the whole path a real one would and the host's decode runs for real.

What the models do not model is the ROM's own arithmetic. That is what the hardware run is for.

### bs43, bs44 on hardware

    create-mon: 1 call(s), built at 0x0201C038, calling 0x08041151
       personality 0x3ADF0001  otId 0xE5BBDF65  checksum VALID  SHINY
       species 59 ARCANINE  Lv30  nickname 'ARCANIN'  OT 'PLAYER'  moves [44, 46, 52, 316]
       IVs (HP ATK DEF SPE SPA SPD) [31, 31, 31, 31, 31, 31]
       stats (maxHP ATK DEF SPE SPA SPD) [103, 80, 68, 63, 74, 62]

Every value was written down before the run. The species and personality were chosen so the answer
would check itself:

- `nickname 'ARCANIN'` is the French `gSpeciesNames`, which bs06's party dump had already read off
  this console by a completely different mechanism.
- `moves [44, 46, 52, 316]` and the six stats were not sent by us. The moves are Arcanine's level-up
  learnset walked to 30 by `GiveBoxMonInitialMoveset`; the stats are `CalculateMonStats`, and they
  depend on nature 7, which the ROM derived from the personality we put at `[sp+4]`. **The stack
  argument reached the arithmetic, not just the struct.**
- `0x3ADF0001` exercises three derived branches at once: shiny for this TID/SID, bit 0 making
  `abilityNum` 1, and nature 7 rather than the neutral 20, which visibly moves five of six stats.

bs43 left one gap: `otIdType 0` makes the OT the player and ignores `fixedOtId`, so `[sp+12]` was
never read. bs44 changed exactly that one variable (`--create-mon-ot-id-type 1 --create-mon-ot-id
0xE5BBDF65`) and the same value had to arrive from the stack instead. It did, 13/13 predictions
holding.

Three fields the payload could not predict are measurements of this console:

| field | value | what it says |
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` is LANGUAGE_FRENCH [global.h:22] |
| `metGame` | 4 | `gGameVersion` is VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | `GetCurrentRegionMapSectionId()` [overworld.c:1265] - MAPSEC_CERULEAN_CITY, where the player was standing |

`CreateMon` reads live game state that no link message carries, and writes it where we can read it
back.

### `--create-mon-append`: into the player's party

**It writes `gPlayerParty`, not the save block's party, and bs46 is why that sentence exists.**

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```

bs46 appended into the save block, the payload correctly reported `APPENDED` at slot 2 with the
count raised, and the mon was gone - the console saved seconds later and copied the live array
straight back over it [load_save.c:160,196]. **A successful-looking answer from our own payload is
not confirmation that anything happened: ask what writes a field before writing it.** Writing
`gPlayerParty` makes the same call carry the write to flash instead of erasing it.

**The slot is always the first free one.** It writes at `slot == playerPartyCount` and then raises
the count, which is what the game does when a mon is caught. An occupied slot is never touched, so
the write cannot destroy a Pokemon however wrong everything else is - structural, not a check that
could be got past. A full party writes nothing and says so. The answer grew a fifth word past the
mon for this (`countBefore | slot << 8 | status << 16`, status 0 not asked / 1 appended / 2 party
full / 3 dry run), so the first 116 bytes are still what bs43 and bs44 returned.

**Where an address may be hardcoded, and where it may not.** What decides it is whether the thing
moves:

| | moves? | so |
| --- | --- | --- |
| `gSaveBlock1Ptr` | yes - a random 4-aligned offset re-rolled on every battle and load [SetSaveBlocksPointers, load_save.c:75] | take it from `r1`/`r2` every call |
| `gPlayerParty` | no - a link-time EWRAM global; bs42 read it as a literal in `ZeroPlayerPartyMons`' pool | an address is legitimate |

bs45 and bs46 measured the first one moving: `gSaveBlock1Ptr` was 0x0202559C and then 0x02025550 six
minutes apart with no reboot, 76 bytes, inside the 0..124 the mask allows.

bs47 found `gPlayerParty` = 0x02024280 and `gPlayerPartyCount` = 0x02024025 by finding a **Pokemon**
rather than by looking where predicted. `scratchpad/find_party.py` walks every 4-aligned window of a
dump and reports the ones that decode as a `struct Pokemon` with a valid checksum, which nothing
passes by accident. Exactly one did, and the species, level, nickname and OT in it were things only
the player's console knew - the OT was not the player's own, so the mon had been traded to them.
Two independent deductions had predicted the same address: bs42's pool, and `gEnemyParty[6]` being
declared immediately before `gPlayerParty[6]` [pokemon.c:61-62], exactly 600 bytes apart.

    # dry run first: the same code with the two stores left out
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --version firered

The dry run reports the party count and the address it *would* write, and reads that slot's current
100 bytes back in place of the mon it built, so the answer says what a real run would overwrite. It
is the only thing that would catch a `playerPartyCount` disagreeing with what is actually in the
party, and it catches it before a store. Two more refusals are built in: an append together with an
absolute `--create-mon-destination` is two answers to the same question, and an append with
`--create-mon-call 0` would put a hundred zero bytes in the party.

**An empty party slot is not a hundred zero bytes.** bs45 came back with `0xFF` at offset 85 and the
log printed `DO NOT APPEND`. The console was right and the check was wrong: `ZeroMonData` zeroes
everything and then ends `arg = MAIL_NONE; SetMonData(mon, MON_DATA_MAIL, &arg)` [pokemon.c:1737],
and `mail` is at offset 0x55. That is better evidence than a hundred zeros would have been -
unclaimed memory does not happen to carry MAIL_NONE in the one byte that means it.
`buffer_script.EMPTY_PARTY_SLOT` is that shape and `is_empty_party_slot` is the check.

bs48 was the dry run at the measured address, saying it would write 0x020242E4 = gPlayerParty + 100.
bs49 ran it for real with the two stores back in and nothing else changed, wrote that same address,
and the player saw the Pokemon in their party after the save. A Pokemon chosen by us, built by the
console's own ROM from eight arguments we passed, delivered over a Mystery Gift link and surviving
the save.

## `call`: any ROM function, with arguments we choose

`rng-trace` calls a function with whatever happens to be in the registers; `create-mon` calls the
one function it was written around. `call` is the general form: an address, up to eight argument
words, the `r0` that comes back, and one address read either side of the call.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script call \
        --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220 --version firered

The convention is measured, not guessed: bs42 disassembled `CreateMon`'s prologue, bs43 and bs44
called it on hardware with eight arguments. `asm/call.s` pushes the sixteen bytes for every call
whatever `argc` says, because the callee never pops them and a function taking fewer simply does not
read them.

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  result      calls used, function, argc, r0, *watch before, *watch after

**`watch` is what makes the answer evidence.** `SeedRng` returns nothing at all -
`void SeedRng(u16 seed) { gRngValue = seed; }` [decomp:src/random.c:15] - so a return value would
prove only that *something* ran. Reading `gRngValue` immediately before and after the call is the
only thing that says the call did what it was called for. The payload writes nothing itself; what
the callee writes is the whole risk, so an address that has not been read as code first has no
business here.

The console's own `SeedRng` as bs14 read it at 0x080486D0 is the offline fixture:
`tests/test_buffer_script.py` executes those exact bytes under unicorn through the payload, so the
round trip is proven before a run is spent. The eight-argument path is checked with powers of two as
the arguments, so the returned sum names exactly which slots arrived.

**What it was built for, and what happened.** `CLI_RUN_BUFFER_SCRIPT` only runs while the Mystery
Gift link is up, so native code cannot watch the RNG at an encounter. Setting it looked like the way
round that: fix `gRngValue` during the link and read the result out of the grass afterwards.
`SeedRng` has exactly four call sites, and three of them cannot happen during a link:

| site | when |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] | the title screen |
| `LinkTestScreen` [link.c:318] | unused debug screen |
| `Debug_RfuIdle` [link_rfu_2.c:2670] | unused debug screen |
| `RfuMain1` [link_rfu_2.c:2116] | Switch-only, gated on a Sloop syscall |

**bs50 and bs51 killed the plan, and the title screen is why.** bs50 seeded `gRngValue` to `0xC0DE`
and bs51's encounter came back 1,898,278,119 turns away from it. Backing out of Mystery Gift runs
`MainCB_FreeAllBuffersAndReturnToInitTitleScreen` -> `CB2_InitTitleScreen`
[decomp:src/mystery_gift_menu.c:463], and pressing START there re-runs the seeding. There is no
route from the Mystery Gift menu to the overworld that does not reseed, so nothing set or read
during a link reaches an encounter. [The RNG page](rng.md) is what went through that wall instead,
by staging code the field engine runs.

`call` keeps its value as the general ROM-call harness; the seeding it was written for is closed.

The Switch-only reseed site is not firing, and that took no hardware run to establish. `RfuMain1`
has a `REVISION >= 0xA` block gated on `swi 0x4b`, one of the syscalls the Sloop emulator adds
[src/sloopsvc.c:135], which would reseed from the console's own advertised `playerTrainerId`
[link_rfu_3.c:854] - 0xDF65 here. `RfuMain1` runs every frame while RFU is up, so a set bit would
pin `gRngValue` near 0xDF65 continuously; bs15's 96 samples free-ran with gaps of exactly 2 on all
95, and bs15's first sample is 1,374,895,295 turns from 0xDF65, an unrelated state rather than a
near miss. Keep that check as a control on any run that reads the RNG: if a state turns out to
descend from 0xDF65, the answer names the hook instead of leaving a run unexplained.

What a caught Pokemon says about `gRngValue`, and how a state is recovered from one, is
[on the RNG page](rng.md).

## `table-scan`: finding a table by its shape

Every address found by searching so far rested on a constant that only one place could hold:
RAND_MULT in `Random`'s literal pool [bs13], `0x00450045` in `sEasyChatGroups` [bs16], `0x64646464`
in `gSpeciesInfo` [bs38]. `memory-scan` answers "where is this word", which requires knowing the
word first.

**A table of pointers carries no such constant.** `gSpecialVars` is 21 words holding the addresses
of the special script variables [decomp:data/event_scripts.s:51], and every one of those addresses
is what we are trying to find out.

What it does have is a relation between its entries. `gSpecialVar_0x8000` through `0x800B` are
twelve `u16`s declared consecutively [decomp:src/event_data.c:16] and `gSpecialVars` lists them in
var-id order, so its first twelve words each sit exactly 2 above the one before. A shape can be
searched for while knowing none of the values.

`table-scan` finds every maximal run of `runlen` words where each is exactly `delta` above its
predecessor, and answers with where the run starts **and what value it starts with**. For
`gSpecialVars` that first value *is* `&gSpecialVar_0x8000`, so locating and reading are one run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script table-scan --table-delta 2 \
        --table-runlen 12 --table-start 0x08140000 --table-end 0x08400000 --version firered

**Why the run is exactly twelve.** `gSpecialVars` continues past entry 11, but entry 12 is
`gSpecialVar_Facing`, declared after `Result` and `LastTalked`, so it is +6 from entry 11 and the
ascending run stops dead. Asking for 13 finds nothing against the real table, and a test asserts
that: it is the check that the fingerprint matches the shape rather than merely "some pointers".

**Why the range.** `script_data` follows every `.text` object in the link order
[ld_script_rev10.ld:318], and `gScriptCmdTable` (214 entries, 856 bytes) opens the section with
`gSpecialVars` immediately after it. Text reaches at least 0x08148C74 (bs08's return address) and
`.rodata` starts below `gSpeciesInfo` at 0x0824CDFC, so `gSpecialVars` lies between them.
0x08140000..0x08400000 is that bracket with margin: 939 frames, about 16 seconds.

**The frame budget is not memory-scan's.** A shape test is ~7 ARM instructions a word where a value
test is ~1.75, so the same block count would be 2.5x the load on a frame the console needs.
`TABLE_SCAN_DEFAULT_BLOCKS` is 192 blocks of 16 bytes, ~6.7k instructions a call, which is what
`memory-scan`'s 512 blocks of 32 actually cost.

**The new mechanic is run state.** A value search is memoryless; a run has to be carried across the
`ldmia` boundary *and* the frame boundary, because the table may straddle either. So `run`,
`runstart` and `expect` live in the image at 0x22C..0x234 beside the cursor and are saved on the way
out of every yield. A test runs the search at one block per call, so the frame boundary falls inside
the table itself, and gets the same answer.

**One documented edge.** `expect` starts at 0, so if the first word of the range happens to be 0 it
is credited to a run whose `runstart` was never written and reads back as 0. `read_table_scan`
discards any hit outside the range that was asked for; starting the range a block before anything of
interest removes it entirely.

**bs57: `gSpecialVars` = 0x081639A8, `gSpecialVar_0x8000` = 0x020370B4.** 939 frames, ~23 s, 2.75 MB
searched, exactly one twelve-word run rising by 2 in all of it. The console held its link throughout.
The four consistency checks are in `frlgsim/rom_map.py` beside the symbols.

`gSpecialVar_0x8000` is `EWRAM_DATA`, a link-time global that does not move, so naming it as a
constant is sound in a way naming a save address never is. [The RNG page](rng.md) is what wanted it.

**Trap, and it cost bs56: a new payload has to be added to lists it cannot see.** bs56 ran the same
search and got the same answer, and we threw it away: the payload returned 1 with its run count in
the 4-byte channel, but ident 19 came back with 4 bytes instead of 528, because `config.py` carried
the answer shape as two hand-maintained tuples (`is_dump` and the `buffer_decode` list) and
`table-scan` was in neither. The offline harness passed every time because it builds its
distribution directly, so the one path the hardware uses was the one never exercised offline. Both
tuples are now a single set beside the payloads (`buffer_script.DUMP_SCRIPTS`, `DECODED_SCRIPTS`)
with `DECODED <= DUMP <= SCRIPT_REGISTRY` asserted at import, and a test walks `DUMP_SCRIPTS`
building each payload's real distribution. Same family as the `run_mg_fast.sh --dump-file` trap.
**When adding a payload, grep for its siblings by name.**

## What is left

1. **Which function to call next.** Calling into the ROM is done; what is missing is a reason. The
   scan finds a function by any constant only it uses, and `call` / `rng-trace --trace-call` invoke
   it.
2. **Writing a live field rather than scratch.** `--write-unsafe` exists; what it needs is a field
   whose effect the player can check on the console's own screen.
