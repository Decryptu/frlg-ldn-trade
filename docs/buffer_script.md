---
title: Native code on the console
parent: Inside the console
nav_order: 2
---

# CLI_RUN_BUFFER_SCRIPT: native code on the console

The last unopened door in the Mystery Gift client. `CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands our
bytes to a 17-opcode interpreter; `CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the CPU.

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

FACTS that follow from those nine lines:

- **1024 bytes**, copied whole (`MG_LINK_BUFFER_SIZE`) whatever we actually sent, so a payload runs
  with the tail of the previous receive sitting behind it and must be self-contained.
- **Three arguments**: `r0 = &client->param`, `r1 = gSaveBlock2Ptr`, `r2 = gSaveBlock1Ptr`. Both
  save blocks, by pointer, readable and writable.
- **A return channel already proven.** `client->param` is exactly what `CLI_LOAD_TOSS_RESPONSE`
  ships back as `MG_LINKID_RESPONSE` [mystery_gift_client.c:204], which is the same channel the
  Mystery Event VM's status uses (mev01-mev06). Whatever the payload leaves in `*param` reaches us.
- **Called once per frame until it returns 1.** A payload that returns anything else is re-entered
  next frame; one that never returns 1 hangs the Mystery Gift menu with no way out.
- **ARM state, not THUMB.** The caller reaches it with a `bx` through a function pointer, which
  selects the state from bit 0 of the address, and the address is word aligned.

DEDUCTION, not needed by anything here: `gDecompressionBuffer` is at **0x0201C000**. `ld_script.ld`
puts `ewram` at 0x2000000 under `ALIGN(4)`, reserves `gHeap` for 0x1C000, then links
`src/main.o(ewram_data)` first, whose first `EWRAM_DATA` is `gDecompressionBuffer` [src/main.c:87].
Every payload we send is position independent, so this is recorded rather than relied on.

## Our side

- `asm/*.s` - one ARM source per payload, assembled by `scripts/gen_buffer_scripts.py` into
  `frlgsim/buffer_payloads.py`. The machine code is committed: a live host must not need a GBA
  toolchain. `tests/test_buffer_script.py` re-assembles and compares whenever `arm-none-eabi-as` is
  installed, which is what keeps the two honest.
- `frlgsim/buffer_script.py` - the payload registry, the validation, and `emulate()`, which runs a
  payload under unicorn on the GBA memory map with the console's three arguments. A payload that
  faults, or that never returns 1, is caught there and never reaches the air.
- `frlgsim/mg_script.py` - `CLIENT_SCRIPT_RUN_BUFFER` (recv, run, load the return channel, send it,
  recv the next script) and `CLIENT_SCRIPT_BUFFER_SUCCESS`.
- `frlgsim/mg_server.py` - `SCRIPT_RUN_BUFFER_SCRIPT`. No card, no toss prompt, no branch on what
  the console holds: a buffer script is not a gift, so a console carrying any card takes the same
  path and keeps it.
- Both simulated consoles execute the payload for real: `frlgsim/mg_client.py` (our receive client)
  and `ConsoleClientModel` in `tests/test_mystery_gift_flow.py`, which is written from the decomp
  independently and models the once-per-frame re-entry.

## The first payload: `trainer-id-probe`

```arm
    ldrh    r3, [r1, #0x0A]         @ SaveBlock2.playerTrainerId[0..1]
    ldrh    ip, [r1, #0x0C]         @ SaveBlock2.playerTrainerId[2..3]
    orr     r3, r3, ip, lsl #16
    str     r3, [r0]                @ *param
    mov     r0, #1
    bx      lr
```

24 bytes. Reads only; writes nothing but `*param`. It is a probe chosen so that **one run decides
everything**, because the answer is a value we already know by another route: the console put its
own `playerTrainerId` into the `MysteryGiftLinkGameData` it sent us seconds earlier
[mystery_gift.c:337]. Our ARM code reads the save directly. The host compares the two.

- The two agree: the payload ran, in ARM state, with the arguments the decomp promises, against the
  real `gSaveBlock2Ptr`, and returned 1. Native code execution is proven.
- A different value: it ran but the arguments or the offsets are not what we think.
- No `Buffer script status:` line at all: the client script shape is wrong, or the console never
  reached the call.

The one nuisance is already handled: a 7-character player name's terminator overwrites
`playerTrainerId[0]` on the way into the game data [mystery_gift.c:364], so when the name is that
long the host compares the top three bytes and says so. Our ARM code reads the save, which is not
affected.

The console is told the verdict in a message we compose: `CLI_MSG_BUFFER_SUCCESS` on a match
(`successMsg` is set, so the console then saves), `CLI_MSG_BUFFER_FAILURE` otherwise (no save, back
to the menu). Both print `data->clientMsg`, our own 64 bytes [mystery_gift_menu.c:943,1353]. The
failure half of that is not new: it is the same exit the questionnaire refusal used on hardware in
mev04.

## Running it

Offline first, every time:

    ./.venv/bin/python -m pytest tests/test_buffer_script.py -q
    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script -v

On hardware (tags `bsNN`; FireRed or LeafGreen - no Pokemon Center is involved):

    (them) Mystery Gift -> Wonder Cards (Recevoir) -> Friend (Ami), wait on the search screen
    (you)  ./scratchpad/run_mg_fast.sh bsNN --buffer-script --version firered
    (them) join PkCamp when it appears

There is no replace-card prompt and no card: a console holding any Wonder Card keeps it.

## bs01: it runs (2026-09-04, first try)

FACT. French FireRed, `--buffer-script`, the console on Mystery Gift -> Wonder Cards -> Friend:

    Console identified itself: 'GURVAN' (TID 57189) on FireRed, holding card flagId 1009
    Buffer script status: 0xE5BBDF65 MATCHES 0xE5BBDF65 (the trainer id from the console's own game data)
    Mystery Gift server finished: gift sent

Our 24 bytes of ARM ran on retail hardware and read the real save. 0xE5BBDF65's low half is 0xDF65 =
57189, the TRAINER ID printed on the player's trainer card, so the value is checkable a third way.
That settles, in one run, every assumption the payload rests on: ARM state and not THUMB, the three
arguments the decomp promises, `gSaveBlock2Ptr` pointing at the live save, the offset of
`playerTrainerId`, the once-per-frame call ending on a return of 1, and `client->param` reaching us
through CLI_LOAD_TOSS_RESPONSE.

Three things came with it:

- **CLI_MSG_BUFFER_SUCCESS prints our own 64 bytes and then saves.** The failure half of that
  message path was already proven (mev04's questionnaire refusal); this is the success half, and
  `successMsg` is what sent the console on to MG_STATE_SAVE_LOAD_GIFT.
- **A console holding a card is undisturbed.** It carried flagId 1009 in and out, with no
  replace-card prompt and nothing sent, because the server script never checks the flag.
- The run crashed AFTER the session, in the host's last printed line (`self.engine`, which never
  existed - the engine is `self.session.activity`). Fixed, with a test.

The message itself came out wrong, and that is worth keeping: the console printed
`ly. code ran and read yourTRAINER IDc`. `charmap.encode` drops every character it does not know,
**newline included**, so `"...your\nTRAINER ID..."` went out as one 47-character line, overflowed
window 1's pixel buffer and wrapped around inside it. The game's line break is 0xFE, and the repo
already had the convention (`split("\n")`, join on 0xFE) in two other places. `mg_server`'s message
encoder now uses it and refuses, offline, both a third line and a line wider than the ROM's own
longest string in that window - "A WONDER CARD has been received", 31 characters
[decomp:src/strings.c:1291]. Window 1 is 28 tiles by 4 [mystery_gift_menu.c:97,524] and the ROM
itself prints two lines in it, so two lines were always fine; only the missing 0xFE was not.

## bs02, bs03

bs02 is the 40-60% join baseline, not us: the console joined, took 6.5 s to send its Session join
(bs01 took 1.2 s), and left during RTT liveness before the RFU NI handshake, so it never reached the
Mystery Gift stage at all. `acklag.py` reported 0 stalls - not the hold. Open item 3, one more data
point.

bs03 repeated bs01 exactly - `0xE5BBDF65 MATCHES 0xE5BBDF65` - so native code execution is
reproduced and not a one-off, and it confirmed both fixes on hardware: the message printed on two
lines as written, and the host's own success line printed instead of crashing.

## The memory read primitive (built, offline only)

`r0` is `&client->param`, so the whole of `struct MysteryGiftClient`
[decomp:include/mystery_gift_client.h:71] is at a fixed offset from it:

| field | from `r0` |
| --- | --- |
| `client->sendBuffer` | 0x10 |
| `client->link.sendSize` | 0x34 |
| `client->link.sendBuffer` | 0x3C |

And `MysteryGiftLink_InitSend` stores the **pointer** it is given [mystery_gift_link.c:59], with the
CRC taken later, at send time, over `link->sendBuffer` for `link->sendSize` bytes
[mystery_gift_link.c:166]. So a payload that runs between the InitSend and the send can point the
console's own outgoing message at any address and set its length, and the console reads out that
region and CRCs it for us. The client script order is the whole trick:

    CLI_RECV -> CLI_LOAD_TOSS_RESPONSE -> CLI_RUN_BUFFER_SCRIPT -> CLI_SEND_LOADED

Swap the middle two and the payload patches fields the InitSend is about to overwrite.

Two payloads use it. `memory-dump` takes an absolute address. `save-dump` needs none: the console
hands the payload `gSaveBlock2Ptr` in r1 and `gSaveBlock1Ptr` in r2, so it reads either save block
at any offset on any console and any build. Up to 1024 bytes a run - `MGL_Receive` rejects more
[mystery_gift_link.c:102].

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-dump --dump-block sav2 \
        --dump-size 256 --version firered
    ./scratchpad/run_mg_fast.sh bsNN --buffer-script memory-dump --dump-address 0x0201C000 \
        --version firered

The evidence line is `Buffer script dump: N bytes of console memory, head ...`. Both simulated
consoles honour a repointed send, so the whole session is proven offline first, including that the
host accepts 1024 bytes on an ident that normally carries 4:

    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script save-dump \
        --dump-block sav1 --dump-offset 0x38 --dump-size 608

What this reaches that nothing else does: `SaveBlock1.playerParty` at 0x0038 (PIDs and IVs of the
whole party), `money` at 0x0290 XORed with `SaveBlock2.encryptionKey` at 0xF20 [money.c], the bag,
flags and vars - and, through `memory-dump`, IWRAM, where `gRngValue` lives. None of it is reachable
by any Mystery Event opcode or any link message.

## bs04, bs05: the primitive works, and the transport under it has a ceiling

**bs04 (save-dump, SaveBlock2, 256 bytes) landed first try.**

    Buffer script dump: 256 bytes of console memory, head c1cfccd0bbc8ffff008065dfbbe59400

which is struct SaveBlock2 exactly as [global.h:327] lays it out: playerName `GURVAN` at 0x00,
gender 0 at 0x08, trainerId 0xE5BBDF65 at 0x0A, playTimeHours 148 at 0x0E. The trainer id is a
third independent route to the same value (bs01 and bs03 computed it; this read it out of memory)
and the play time is checkable on the console's own save screen. save-dump did it WITHOUT KNOWING
ANY ADDRESS, off the pointers Client_RunBufferScript passes.

**bs05 (save-dump, SaveBlock1 0x34, 608 bytes) failed, and not in the payload.** The console
printed "erreur de connexion, rapprochez-vous" during transmission and left. The payload ran: the
console repointed its own outgoing message and began transmitting a 608-byte message with a valid
header, and `acklag.py` reported 1 stall with a worst inbound gap of 37 ms, so it was not the hold
either. The primitive was sound and the transport lost a byte of bookkeeping.

## What the handshake actually waits for (bs05, settled from the capture)

`MGL_Send` chunks at 252 bytes and waits on `MGL_HasReceived(link->sendPlayerId)` before each chunk
and once more before it finishes [mystery_gift_link.c:176,205]. The first reading of that - a block
WE sent - was WRONG, and the correction is the whole finding:

    MysteryGiftClient_Create -> MysteryGiftClient_Init(sClient, 1, 0)   [mystery_gift_client.c:33]
                                                       ^sendPlayerId

**sendPlayerId is 1: the console's OWN multiplayer id.** `MGL_HasReceived(1)` is
`gRfu.blockReceived[1]`, and on a child that is set only when the console's own block comes back
COMPLETE through row one of the parent's 70-byte gRecvCmds table - the copy WE mirror.
`RfuHandleReceiveCommand` runs the block reassembler over every player including the child itself
[link_rfu_2.c:1125], and `RfuMain1_Child` fills gRecvCmds from the parent's table, its own row
included [:970]. Its RFU block sender waits on the same mirror: `HandleBlockSend` holds the INIT
until it sees the INIT mirrored, and `SendLastBlock` repeats the last fragment until it sees THAT
mirrored, then re-queues every fragment missing from the mirrored bitmask - `HandleSendFailure`
[link_rfu_2.c:1366-1416]. The console cannot name the fragment it is missing. It can only notice its
own bitmask is short and send everything again.

Our leader bounded that mirror at the newest two commands and dropped the rest (`ECHO_MAX = 2`,
added after lg122, where an unbounded FIFO fell 0.5 s behind). bs05's console emitted its 21-fragment
chunk partly in bursts - two commands in its frame 283831, four in 283833 - and the bound ate them:

    scratchpad/echo_gaps.py scratchpad/bs05.pcap
    [  4] t=  10.992 count= 21 sent= 21/21 mirrored= 20/21 never=[13] repaired_by_console=[13, 16, 17, 18]

Fragments 13, 16, 17 and 18 were never mirrored, and 13, 16, 17, 18 are exactly what the console then
re-sent (11.626-11.663 s). Our echo of the repair for 16, 17 and 18 went out; the repair for 13 was
dropped a SECOND time, and the console declared link loss at 11.790. Run the same tool over bs01,
bs03 and bs04 and every block reads `never=[]` - bs04 had bursts of three and four too, and two
repairs, but each repair was mirrored and it recovered. Across five captures the only run that died
is the only run with a fragment we never gave back.

608 bytes is not a ceiling, then, and 256 is not a safe number: three 21-fragment chunks are simply
three times the exposure of one. bs04 got lucky.

## The fix (offline; hardware confirmation is bs06)

`rfu_leader.ChildEcho` replaces the bound. Two rules, and each answers one of the two failures:

- **Never drop a distinct command.** A dropped fragment is a repair round the console runs blind.
- **Coalesce a repeat that is still waiting.** SendLastBlock re-sends the same fragment every frame
  while it waits, and mirroring each of those repeats is what put lg122's row one 0.5 s behind. One
  entry is enough: the console is waiting to see that command once. A repeat that arrives after the
  mirror has gone out is a new question and is answered again.

Because the child sends exactly one command per parent frame it receives [MscCallback_Child
increments `childSendCount` only on `recv.newDataFlag`, link_rfu_2.c:600], mirror in and mirror out
are 1:1 and the queue cannot grow on its own; with repeats folded away it never held more than four
in any test. Nothing extra goes on the air - the same parent frames carry the same rows.

`ConsoleClientModel` (tests/test_mystery_gift_flow.py) now models the mirror rather than a fixed
`echo_delay`: an own-row receive slot with the decomp's block gate, `BlockSender` fed that slot as
its ack with no watchdog, and MGL_Send waiting on `blockReceived[1]` before each chunk and once at
the end. Its `_drive` relay is the real `ChildEcho`, and `child_burst`/`burst_every` reproduce the
console flushing its RfuSendQueue. Measured over a 608-byte dump, bursts of four every frame:

    policy                       echoes dropped   console repairs   frames
    max_backlog=2, no coalesce              628               156     1255
    ChildEcho (current)                       0                 0     1011

## bs06: 608 bytes, first try, and the party came out

FACT, 2026-09-04, French FireRed, bs05's own command with the echo policy as the only variable:

    [mg] received ident 19 (608 bytes)
    Buffer script dump: 608 bytes of console memory, head 05000000ca3a353065dfbbe5bbccbdbb

    scratchpad/echo_gaps.py scratchpad/bs06.pcap
    13 console block(s); bursts: 1x247, 2x16, 3x1
    ... every block never=[] repaired_by_console=[]
    0 block(s) had a fragment we never mirrored back.

Thirteen console blocks, four of them full 21-fragment chunks, bursts of two and three among them,
and not one fragment lost. The host's own status line said `row-one echo backlog 1 (peak 3), 85
repeat(s) folded, none dropped` throughout - the repeats it folded are lg122's failure mode, folded
away instead of mirrored. `scratchpad/dump_read.py` on the bytes:

    playerPartyCount 5
    slot 1: ARCANINE   Lv72  nick='ARCANIN'    OT='GURVAN' PID=0x30353ACA IVs=[18,17,20,31,2,10]
    slot 2: LUGIA      Lv77  nick='LUGIA'      OT='GURVAN' PID=0x91F854FF IVs=[21,9,11,31,28,21]
    slot 3: DRAGONITE  Lv77  nick='DRACOLOSSE' OT='GURVAN' PID=0x322EA657 IVs=[26,22,3,24,11,5]
    slot 4: ZAPDOS     Lv72  nick='ELECTHOR'   OT='GURVAN' PID=0x11CDE7D0 IVs=[5,14,1,22,4,6]
    slot 5: SNORLAX    Lv74  nick='RONFLEX'    OT='GURVAN' PID=0xB0898E84 IVs=[25,24,27,25,2,0]

Every checksum valid, every OT GURVAN, the nicknames French. The whole party in one run, PIDs and
IVs included - none of it reachable by any Mystery Event opcode or link message.

One more thing was in the evidence all along and is worth writing down so nobody re-derives it: the
console's READY_END (ident 20) is a 1024-byte message, which MGL_Send splits into a header plus FIVE
chunks, and `echo_gaps.py` finds it in bs01 as blocks 5-10 (count 1, then 21, 21, 21, 21, 2 =
4x252 + 16). The console had been completing five-chunk sends since the first buffer-script run. The
"the handshake supply runs out at four chunks" hypothesis was dead on evidence already in hand.

## bs07: 1024 bytes, and the cartridge names itself

FACT, 2026-09-04, French FireRed, `--buffer-script memory-dump --dump-address 0x08000000
--dump-size 1024`, first try. `[mg] received ident 19 (1024 bytes)`, head `7f0000ea24ffae51699aa221`
- an ARM branch followed by the start of the GBA Nintendo logo. So the payload can read the
cartridge, and a full 1024-byte dump works on hardware. `echo_gaps.py`: `never=[]` everywhere.

    entry      b 0x08000204
    title      POKEMON FIRE          [0xA0]
    game code  BPRF                  [0xAC]  BPR = FireRed, F = French
    maker      01   fixed 0x96
    version    0x0a                  [0xBC]
    header checksum 0x5d, recomputed 0x5d -> VALID

Three things follow:

- **The Switch release ships software version 0x0A**, read off the cartridge rather than inferred.
  That is the `REVISION >= 0xA` the decomp branches on, so the branches this project has been
  reading are confirmed to be the ones running. Until now that was an assumption.
- The header checksum recomputes over 0xA0..0xBC and matches the stored byte, so the 160 bytes are
  internally consistent: the read is real and not a buffer of stale bytes.
- ROM is readable at its real address, which is the last thing calling into it was missing. The
  build is identified; what remains is a symbol address for that exact build.

## `anchors`: asking the machine where it is (built, hardware run pending)

Every other payload works from the two pointers the console hands us. `anchors` asks the CPU for the
addresses nothing else can supply, writes eleven words into `client->sendBuffer` and widens
`link->sendSize` to 44. It does not repoint anything: CLI_LOAD_TOSS_RESPONSE has already aimed
`link->sendBuffer` at `client->sendBuffer` [MysteryGiftClient_InitSendWord, mystery_gift_client.c:91],
so filling that buffer is enough. (Both simulated consoles now honour a RESIZED send as well as a
repointed one - `ClientState.send_changed` - because MGL_Send reads both fields at send time.)

| word | what |
| --- | --- |
| 0 | `sub ip, pc, #8`: where the console put our code. gDecompressionBuffer = 0x0201C000 is a DEDUCTION from ld_script.ld; this measures it. |
| 1 | `lr`: **the address IN ROM of the instruction after the call** in Client_RunBufferScript [mystery_gift_client.c:276], bit 0 set because the caller is THUMB. |
| 2 | `sp`, so the stack, in IWRAM. |
| 3 | `r0` = `&client->param`, so where AllocZeroed put the client in gHeap. |
| 4-5 | gSaveBlock2Ptr, gSaveBlock1Ptr. |
| 6-9 | the four AllocZeroed buffers: sendBuffer, recvBuffer, script, msg. |
| 10 | `link->sendBuffer` as InitSend left it; it must equal word 6, or the offsets this project computes from r0 are wrong. |

Word 1 is the point. It is an absolute ROM address of a code site we can name in the decomp, so it
anchors the whole cartridge: anything whose distance from that call site is known becomes callable.
bs07 identified the build (BPRF version 0x0A); this locates it.

`buffer_script.describe_anchors` prints the eleven words and every consistency check it can make -
that the return address is inside the cartridge, that word 0 is the deduced 0x0201C000, that word 10
equals word 6 - because an address that looks plausible but is not self-consistent is worse than no
address. The host logs those lines itself.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script anchors --version firered

## bs08: the anchor, first try (2026-09-04)

FACT. `--buffer-script anchors` on French FireRed:

    code                0x0201C000
    return_address      0x08148C75
    stack_pointer       0x03007DB8
    client_param        0x020020D4
    save_block_2        0x02024598
    save_block_1        0x0202553C
    client_send_buffer  0x02006510
    client_recv_buffer  0x02006920
    client_script       0x02006D30
    client_msg          0x02007140
    link_send_buffer    0x02006510

Read in order:

- **gDecompressionBuffer IS 0x0201C000.** That was a deduction from ld_script.ld from the day the
  buffer script work started. It is now a measurement.
- **The ROM anchor is 0x08148C74**, THUMB (bit 0 set on lr): the instruction after the call in
  `Client_RunBufferScript` [mystery_gift_client.c:276] in the FRENCH rev-10 build the console runs.
  With bs07's header (BPRF version 0x0A) the build is identified and now located.
- `link_send_buffer` == `client_send_buffer`, so every struct offset this project computes from r0
  is confirmed against the console rather than against the header file.
- The four AllocZeroed buffers are 0x410 apart - 1024 bytes plus a 16-byte block header - so gHeap's
  allocator is behaving exactly as malloc.c describes, and the client sits at 0x020020D0.
- The save blocks are at 0x02024598 and 0x0202553C on this console, which is what a `memory-dump`
  would need and `save-dump` never has to know.

## `save-write`: writing, not just reading (built, hardware run pending)

A pointer takes a `strb` as readily as a `ldrb`, so the same two pointers give write access to the
live save. `save-write` copies its payload tail into the block and then points `link->sendBuffer`
**at the destination**, so what comes back over the air is what is now in the console's save, not a
copy of what we asked for. One run writes and proves the write. The session ends in
CLI_MSG_BUFFER_SUCCESS, which sends the console to MG_STATE_SAVE_LOAD_GIFT, so the write reaches
flash and a later `save-dump` of the same offset proves it survived.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script save-write --dump-block sav2 \
        --dump-offset 0xB20 --write-text "FRLG-LDN bs09" --version firered

**The guard is the important part.** This is the player's real save and the console commits it to
flash. `build_save_write` refuses, by default, any span that is not inside a region the game never
reads: `filler_90[8]` at 0x090 and `filler_B20[0x400]` at 0xB20 in struct SaveBlock2
[decomp:include/global.h:345,357], neither of which is referenced anywhere in src/. A write ending
four bytes past filler_B20 lands in `encryptionKey`, which money is XORed with, so the failure mode
of getting this wrong is a scrambled game rather than a failed run. `--write-unsafe` is the
deliberate override and exists for the day we mean to edit a live field.

## bs09: the console's save, written (2026-09-04, first try)

FACT. `--buffer-script save-write --dump-block sav2 --dump-offset 0xB20 --write-text "FRLG-LDN bs09"`:

    Buffer script dump: 13 bytes of console memory, head 46524c472d4c444e2062733039

`46524c472d4c444e2062733039` is "FRLG-LDN bs09", and it came back from `link->sendBuffer` pointed at
the DESTINATION inside SaveBlock2 - the console reading out its own save after our ARM code wrote
there, not an echo of what we sent. `echo_gaps.py`: `never=[]` on every block. The console then
saved. Reading and writing the live save on retail hardware are both proven.

**bs10 proved it reached FLASH.** The player closed the game and reloaded from the title screen, so
SaveBlock2 was re-read from flash rather than kept in RAM, and a plain `save-dump` of the same offset
returned `46524c472d4c444e2062733039000000` - "FRLG-LDN bs09" still there. Read, write and persistence
are all proven on retail hardware, over Mystery Gift, with no Pokemon Center and no trade.

## bs11, bs12: the ROM, read as code (2026-09-04, both first try)

bs08 gave one address inside the cartridge. Two read-only dumps turned it into a symbol map, and the
loop that did it is `scratchpad/rom_read.py`.

**bs11** dumped 1024 bytes at 0x08148A00 and it disassembles as `Client_RunBufferScript` exactly as
[decomp:src/mystery_gift_client.c:274] writes it - `adds r0,r4,#4` for &client->param, two `ldr`s
through pointers for the save blocks, and `cmp r0,#1` at 0x08148C74, which is the anchor bs08
measured from the CPU. The call is `bl 0x081E2230`, a `_call_via_r3` veneer, which is why lr comes
back pointing into the caller. Its THUMB literal pool holds:

    0x08148C88 -> 0x0201C000   gDecompressionBuffer   (bs08 read the same number from pc)
    0x08148C8C -> 0x0300422C   &gSaveBlock2Ptr
    0x08148C90 -> 0x03004228   &gSaveBlock1Ptr

`MysteryGiftClient_CallFunc` follows at 0x08148C94: `sub sp,#32`, eight words copied onto the stack
from 0x0845DBD0, indexed by `client->funcId` at [r0,#8], called through `_call_via_r1`. That names
**sClientFuncs and where it is**, and it re-confirms CLIENT_FUNC_ID = 8 from the machine code.

**bs12** dumped that table. Eight THUMB pointers, every one landing on a `push {r4, lr}` bs11's
disassembly already showed, and entry 7 reading 0x08148C61 - the function bs08 measured from the
other end. Three runs, three routes, one answer. The five-entry table right after it is
`sFuncTable` from mystery_gift_server.c, named by what its code does rather than by position:
0x08148DF0 is `movs r1,#4; str r1,[r0,#8]; movs r0,#0; bx lr`, which is Server_Init's
`svr->funcId = FUNC_RUN; return SVR_RET_INIT`, and 0x08148DF8 is Server_Done returning SVR_RET_END =
3 - both constants the ones this repo already used.

`frlgsim/rom_map.py` holds the result with its evidence, and `tests/test_rom_map.py` checks it
against the dumps. Nothing in it is inferred from the decomp's ENGLISH rev-10 build; a symbol that
has not been read off the console does not belong in that file.

## `memory-scan`: searching instead of reading (built, hardware run pending)

Every payload before this one reads a window we had to name in advance, 1024 bytes at a time. The
cartridge is 16 MB. At 1024 bytes a run that is 16384 runs, so the ROM has only ever been read where
some other measurement already pointed - which is why `frlgsim/rom_map.py` grew from one anchor
(bs08) rather than from a search.

**The line that changes it is one we have quoted from the start and never used:**

```c
    if (func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr) == 1)
    {
        client->funcId = FUNC_RUN;      // only then does the client move on
```
[decomp:src/mystery_gift_client.c:276-280]

A payload that returns anything but 1 IS CALLED AGAIN NEXT FRAME. `MysteryGiftClient_Run` is reached
from `Task_MysteryGift` [mystery_gift_menu.c:1245], which is an ordinary task, so "again" means the
next frame, sixty times a second. And the `memcpy` that loads us runs ONCE, at the
`CLI_RUN_BUFFER_SCRIPT` command [:239] - not per call. So the payload's own image, code and data
alike, is exactly as it left it: **a payload can keep state across frames and resume**.

That turns the 1024-byte window into a loop. `asm/memory-scan.s` is handed a 32-bit needle and a
range; each call scans its budget of 32-byte blocks, writes the cursor back into its own image and
returns 0; the call that reaches the end of the range repoints `link->sendBuffer` at its result
block and returns 1, the same way every dump does.

The image, all offsets fixed BY CONSTRUCTION - the payload opens with a branch over its own
parameter block, so nothing here is recovered from a disassembly:

| offset | |
|---|---|
| 0x000 | `b .Lcode` |
| 0x004 | cursor: the start address, advanced by the payload |
| 0x008 | end |
| 0x00C | needle |
| 0x010 | blocks per call |
| 0x014 | max_calls, the watchdog |
| 0x018 | RESULT: matches found, final cursor, calls used, matches stored |
| 0x028 | RESULT: 64 x (address, value) |
| 0x228 | the code |

**The budget is the design.** The console is holding an RFU link open while this runs, so a call
that overruns its frame costs frames the link needs. The inner loop is an `ldmia` of eight words and
eight chained `cmpne`s - about 14 ARM instructions per eight words, and the default 512 blocks is
7703 instructions a call, measured under unicorn. Out of EWRAM (a 16-bit bus, so ~6 cycles an ARM
fetch) that is roughly 60000 of a frame's 280896 cycles, about a fifth. The whole 16 MB cartridge is
1024 calls: **17 seconds of link, one run**. `--scan-blocks` is the dial.

**The watchdog is not optional.** A payload that never returns 1 hangs the Mystery Gift menu with no
way out, and this is the first payload whose stopping condition is arithmetic rather than a straight
line. `max_calls` is patched in beside the range and defaults to what the range needs plus two; a
watchdog stop still answers, with a cursor short of the end saying where to resume.

The answer is a FIXED 528 bytes however many matches there are, so the host's length check
(`len(dump) == buffer_dump_size`) stays the proof that the payload repointed the send. `found` counts
every match, `hits` holds the first 64.

Offline, the whole thing runs: `buffer_script.emulate_repeating` calls a payload until it returns 1
the way the console does, and `ConsoleClientModel` now does the same rather than refusing anything
that returns 0. What the harness does NOT model is the frames themselves - the frame cost is the
arithmetic above, not a measurement.

    ./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script memory-scan \
        --scan-start 0x08000000 --scan-end 0x08010000 --scan-blocks 64 -v
    # scan: 1 match(es) for 0x454B4F50, 32 call(s) = frames, stopped at 0x08010000
    #    0x080000A0  0x454B4F50          <- 'POKE', the cartridge title

**The first needle is `0x41C64E6D`**, `RAND_MULT` [decomp:include/random.h:18]. No ARM or THUMB
instruction can encode it, so it is in `Random`'s literal pool, and the same pool holds `&gRngValue`
- the seed this project has wanted since the party dump, because it makes encounters and shininess
predictable and it is reachable by no Mystery Event opcode and no link message. Two hits are
expected (`Random` and `Random2`, which share the multiplier [random.h:19-20]); a dump of either
address then reads the pool.

## bs13: the search works, on hardware, first try (2026-09-04)

    ./scratchpad/run_mg_fast.sh bs13 --buffer-script memory-scan --scan-word 0x41C64E6D \
        --scan-start 0x08000000 --scan-end 0x08400000 --version firered

    scan: 11 match(es) for 0x41C64E6D, 256 call(s) = frames, stopped at 0x08400000
       the whole range 0x08000000..0x08400000 was scanned
       0x080486C8  0x0807D238  0x0807F25C  0x08086AB0  0x080AFC00  0x080F1EA0
       0x080F2378  0x080F2438  0x08122284  0x08122518  0x0814CBFC

FACTS from the run, and the third is the one that matters beyond this payload:

- **256 calls, exactly as the arithmetic said.** 4 MB / (512 blocks x 32 bytes) = 256, and the
  payload reported 256. The multi-call mechanism works on retail hardware.
- `echo_gaps.py`: `never=[]` on all 13 console blocks. The session closed normally and the console
  saved, as every buffer-script run does.
- **The frame budget cost the console nothing.** The host's own status lines through the scan read
  `child frames 716 ... 837 ... 956` against `parent polls 720 ... 840 ... 960`: ~60 child frames a
  second while our code was running ~3 ms of every frame. There is room to raise `--scan-blocks`.

WHICH HIT, WITHOUT SPENDING A RUN: `grep -rl 'ISO_RANDOMIZE1\|RAND_MULT' src/` gives eight files,
and `ld_script.ld` puts `src/random.o` at #86 with the next user, `src/title_screen.o`, at #123.
Hits come back in address order and the link order is the address order, so the LOWEST hit is
random.o's pool. That is an inference from the decomp's ORDER, not from its addresses.

## bs14: Random, and gRngValue named twice (first try)

`--buffer-script memory-dump --dump-address 0x08048400`, and 0x080486B0 disassembles as:

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

which is `gRngValue = ISO_RANDOMIZE1(gRngValue); return gRngValue >> 16` [decomp:src/random.c:9-13]
instruction for instruction. The next function, 0x080486D0, is SeedRng - `lsl/lsr` for the u16 cast,
then `str r0, [r1]` through a pool word that is **0x03004220 again**. Two independent functions name
the same address inside one dump.

## `rng-trace`, and bs15: the first call into the console's ROM (first try)

An address that was only ever read is a hypothesis. `asm/rng-trace.s` samples a word once a frame
and, between the two reads of each sample, CALLS a ROM function:

    ./scratchpad/run_mg_fast.sh bs15 --buffer-script rng-trace --trace-address 0x03004220 \
        --trace-call 0x080486B1 --trace-samples 96 --version firered

    rng-trace: 96 sample(s) of 0x03004220 over 96 call(s) = frames, calling 0x080486B1
       the LCG recurrence after == before * 1103515245 + 24691 holds on 96/96 samples
          - THE ADDRESS IS gRngValue AND THE ROM CALL RAN
       between frames the word changed 95/95 times; the game's own Random calls per frame:
          min 2, max 2, total 190

`after == before * RAND_MULT + RAND_ADD` on 96 samples out of 96 settles three things at once that
no single read could: the address is gRngValue, our ARM payload can `bx` into THUMB ROM and be
returned to by the callee's own `bx lr`, and the function at 0x080486B0 is Random. The call is
`mov lr, pc; bx r2` - pc reads as that instruction + 8, which is the instruction after the `bx`, and
its bit 0 is clear, so the callee returns us to ARM state.

The second answer is a measurement of the console rather than of us: between our call in one frame
and our read in the next, the game had turned the RNG **exactly twice, on all 95 gaps**. That is
FRLG's own Random consumption while it sits in the Mystery Gift link menu.

The payload was proven offline first by executing the console's OWN Random - the twenty bytes bs14
read off the cartridge, put back at 0x080486B0 under unicorn (tests/test_buffer_script.py).

## Left

1. **Calling into the ROM is DONE (bs15): `mov lr, pc; bx address|1`, 96 times, checked by the
   callee's own arithmetic.** What is open is which function to call next. The scan is how they get
   found now - a function is reachable by any constant only it uses - and `rng-trace` with
   `--trace-call` is a general "call this and watch what it changes" harness, not an RNG tool.

2. **Writing a live field rather than scratch.** `--write-unsafe` exists; what it needs is a reason
   and a field whose effect the player can check on the console's own screen.

## `string-gather` — following a pointer array instead of reading a window

A dump reads a window, so a table of pointers costs one run for the pointers and another for every
kilobyte they point at, most of it whatever padding the struct carries. `sEasyChatGroups`' 22 word
arrays and their text span 21560 bytes of cartridge [bs17], and two thirds of that is
`struct EasyChatWordInfo`'s `alphabeticalOrder` and `enabled` [decomp:include/easy_chat.h:11],
neither of which says anything about what the console PRINTS. Twenty-two runs for eight kilobytes
of words.

This payload dereferences. Given the address of the first pointer, a stride and a count, it copies
each string it points at — bytes up to and including the 0xFF terminator — into one contiguous
answer, and reports where a following run should resume. A whole Easy Chat group a run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script string-gather \
        --gather-address 0x083E0D54 --gather-count 69 --gather-stride 12 --version firered

`--gather-stride` is 12 for `struct EasyChatWordInfo`, whose `text` is at offset 0; a plain array
of `const u8 *` is 4. The answer is a fixed 776 bytes — four header words then up to 760 bytes of
strings — so the host's length check stays the proof that the payload repointed the send. The
evidence line is `gather:`, and the words are logged decoded.

**It never truncates.** A string that does not fit in what is left of the budget ends the run
BEFORE it, and `next` names the entry to resume from. A half-copied word would be
indistinguishable from a French word that really is that short, which is exactly the kind of
silent wrong this project keeps paying for. bs35 hit that path on hardware — 83 of STATUS' 109
words, 760 bytes exactly — and bs36 resumed from the address it reported with nothing lost or
repeated.

**`--gather-maxlen` bounds the walk** (64 by default). A pointer that is not a string would
otherwise be copied until it happened to meet an 0xFF, and the answer would be garbage that looked
like data. Hitting it ends the run and says so, rather than hanging the menu.

Reads only; writes nothing outside its own image and the two link fields. Proven on hardware
bs18-bs36, eighteen runs, all first try. `docs/easy_chat_french.md` is what they read.


## `create-mon` — a ROM call that takes EIGHT arguments (built, hardware run pending)

`rng-trace` called `Random`: no arguments, a `u16` back, and the LCG's own recurrence to check it
by. That proves the *mechanism* of a ROM call and nothing about passing anything to one.
`CreateMon` is the other end of the range:

```c
void CreateMon(struct Pokemon *mon, u16 species, u8 level, u8 fixedIV,
               u8 hasFixedPersonality, u32 fixedPersonality, u8 otIdType, u32 fixedOtId)
```

Four arguments in `r0..r3` and **four on the stack**, which no payload here had passed. The
console's own prologue is what says where they go, and `asm/create-mon.s` is written against that
disassembly rather than against a calling convention taken on trust — bs42's dump reads

    08041150  push {r4,r5,r6,r7,lr}    ; sp -= 20
    08041152  mov  r7, r8
    08041154  push {r7}                ; sp -= 4
    08041156  sub  sp, #28             ; sp -= 28, so entry sp is now sp + 52
    0804115c  ldr  r4, [sp, #52]       -> entry sp +  0   hasFixedPersonality  (masked to u8)
    0804115e  ldr  r7, [sp, #56]       -> entry sp +  4   fixedPersonality     (NOT masked: u32)
    08041160  ldr  r5, [sp, #60]       -> entry sp +  8   otIdType             (masked to u8)
    08041184  ldr  r0, [sp, #64]       -> entry sp + 12   fixedOtId            (u32)

so the four go at `sp+0..sp+12` in whole words at the moment of the call. The callee does not pop
them (`add sp,#28; pop {r3}; pop {r4-r7}; pop {r0}; bx r0`), so the payload takes the 16 bytes
back itself — and *returning at all* is the proof that it did, because a payload that forgot would
pop a garbage `lr`.

### The destination is our own image

`CreateMon` writes 100 bytes wherever it is pointed, and the only interesting address on the
console is the player's real party — a live save. So the mon is **always built inside the 1024
bytes we were copied into**, where nothing but the payload can be hurt, and read back out of
there. There are 32 bytes of guard between the mon and the first instruction, so a struct bigger
than the 100 the decomp declares still cannot land on an instruction.

`--create-mon-destination ADDR` copies the finished 100 bytes onward afterwards. That is a plain
byte copy we can see, rather than aiming a ROM function at a save block, and it needs
`--write-unsafe` — the same deliberate override an out-of-scratch `save-write` takes.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon \
        --create-mon-species 151 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADE0000 --version firered

`--create-mon-call` defaults to `CreateMon | 1` from `rom_map.py`; `--create-mon-call 0` calls
nothing at all and answers the zeroed buffer, which checks the send path with the ROM left out of
it. The answer is a fixed 116 bytes — four header words then the 100-byte `struct Pokemon` — and
the evidence line is `create-mon:`. `*param`, the 4-byte channel, comes back as the mon's first
word, which for a real mon is its **personality**.

### Why the answer is self-verifying

A mon that decodes at all already agrees with two arguments: the 48-byte substruct region is
encrypted with `personality ^ otId` and checksummed, so a valid checksum means those two words are
the ones the ROM used. `check_create_mon` then checks species, level and the IVs out of the
decrypted substructs, and `scratchpad/verify_create_mon.py` goes further and predicts the fields
the ROM *derives* — exp from `gExperienceTables[growthRate][level]`, friendship and the ability
slot from `gSpeciesInfo`, the initial moveset and its PP from the level-up learnset, and all six
stats from `CalculateMonStats`. Thirteen predictions; bs39 read the table off the console
byte-identical to the decomp's, so predicting from the decomp is sound for everything except text.

    ./.venv/bin/python scratchpad/verify_create_mon.py scratchpad/bsNN_dump.bin \
        --species 151 --level 30 --iv 31 --personality 0x3ADE0000

**The nickname is deliberately not predicted.** `CreateBoxMon` fills it from `gSpeciesNames`
[pokemon.c:1810], which is the FRENCH table on this cartridge. Whatever comes back is a *reading*
of it — one species a run, by the same route the Easy Chat vocabulary was read.

And with bs01's TID 57189 / SID 58811, `fixedPersonality` is the whole Gen 3 shiny check:
`buffer_script.shiny_personality(57189, 58811)` is a value that makes the mon shiny for this
console, which is possible only because the SECRET id is printed nowhere in the game and was read
out of the save.

### Proven offline

The emulated cartridge is a header and zeros, so a payload that CALLS a ROM function has nothing
to land on. Two THUMB stubs stand in for `CreateMon` at whatever address the payload was built to
call, placed with `memory={address: stub}`, and each answers a different question:

- `CREATE_MON_ARG_MODEL` writes `r0..r3` and the four stack arguments into the destination as
  eight words, so the answer names each one. It pushes nothing, so `[sp,#0]` *is* the caller's
  first stack argument — which is the whole point.
- `create_mon_copy_model(source)` copies 100 bytes a caller prepared over the destination, so a
  mon built in Python travels the whole path a real one would and the host's decode runs for real.

Both are in `frlgsim/buffer_script.py` beside `_DEFAULT_ROM_HEADER`, the other model of the
console that lives there. `./.venv/bin/python scratchpad/mg_client_harness.py --buffer-script
create-mon` runs the whole Mystery Gift session with them.

What the models do NOT model is the ROM's own arithmetic. That is what the hardware run is for.

## bs43, bs44: the eight-argument call, on hardware, both first try (2026-09-04)

    ./scratchpad/run_mg_fast.sh bs43 --buffer-script create-mon \
        --create-mon-species 59 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADF0001 --create-mon-ot-id-type 0 --version firered

    create-mon: 1 call(s), built at 0x0201C038, calling 0x08041151
       personality 0x3ADF0001  otId 0xE5BBDF65  checksum VALID  SHINY
       species 59 ARCANINE  Lv30  nickname 'ARCANIN'  OT 'GURVAN'  moves [44, 46, 52, 316]
       IVs (HP ATK DEF SPE SPA SPD) [31, 31, 31, 31, 31, 31]
       stats (maxHP ATK DEF SPE SPA SPD) [103, 80, 68, 63, 74, 62]

Every value there was written down **before** the run. `echo_gaps.py` reads `never=[]` on all
eleven console blocks in both captures; one call each, no stalls.

The species and the personality were chosen so that the answer would check itself:

- **`nickname 'ARCANIN'`.** `CreateBoxMon` fills the nickname from `gSpeciesNames`
  [pokemon.c:1810], the FRENCH table. bs06's party dump had already read that same name off this
  console by a completely different mechanism — a save dump, not a ROM call — so the run was
  self-verifying the moment it landed, exactly as bs18 was.
- **`moves [44, 46, 52, 316]` and the six stats.** Neither was sent by us. The moves are
  Arcanine's level-up learnset walked to 30 by `GiveBoxMonInitialMoveset`, and the stats are
  `CalculateMonStats` — and those stats depend on nature 7, which the ROM derived from the
  personality we put at `[sp+4]`. **The stack argument reached the arithmetic, not just the
  struct.**
- **`0x3ADF0001` is one value exercising three derived branches**: it is shiny for TID 57189 /
  SID 58811 (shiny value 0), its bit 0 makes `abilityNum` 1, and its nature is 7 rather than the
  neutral 20, which visibly moves five of the six stats.
- **checksum VALID.** The 48-byte substruct region is encrypted with `personality ^ otId` and
  checksummed by the ROM itself, so a valid checksum means both of those words are the ones the
  ROM used — two arguments confirmed before any field is even read.

### bs44: the fourth stack argument

bs43 left one gap. `otIdType 0` makes the OT the player and ignores `fixedOtId`, so the argument
at `[sp+12]` was never read — and `otId 0xE5BBDF65` coming back only proved the *save* was read
(a third independent confirmation of bs01's TID/SID, but not of the argument). bs44 changed
exactly that one variable, `--create-mon-ot-id-type 1 --create-mon-ot-id 0xE5BBDF65`, so the same
value had to arrive from the stack instead. It did, and the answer is otherwise identical:

    otId: asked 0xE5BBDF65, got 0xE5BBDF65  OK

All four stack arguments are now proven on hardware. `verify_create_mon.py` on bs44's dump:

    13/13 predictions hold - CreateMon ran, with our eight arguments, on the real cartridge

### Three readings that were not predictions

The fields the payload could not predict are measurements of this console, and bs44's dump gives
three at no extra cost:

| field | value | what it says |
| --- | --- | --- |
| `language` | 3 | `gGameLanguage` is LANGUAGE_FRENCH [global.h:22], read off the console rather than inferred from the game code |
| `metGame` | 4 | `gGameVersion` is VERSION_FIRE_RED [global.h:11] |
| `metLocation` | 91 | `GetCurrentRegionMapSectionId()` [overworld.c:1265] — MAPSEC_CERULEAN_CITY, where the player was standing |

That last one is the shape worth keeping: `CreateMon` reads live game state that no link message
carries, and writes it somewhere we can read it back.

## `--create-mon-append`: the write into the player's party (built, hardware run pending)

bs43 and bs44 built a mon and read it back; nothing on the console was written. Putting it in the
party is a different thing — a write to a live save that the console then commits to flash — and it
needs two things `--create-mon-destination` does not do.

**It writes `gPlayerParty`, not the save block's party — and bs46 is why that sentence exists.**
`gSaveBlock1Ptr->playerParty` looks like the party and is not: it is only where the save copies
*to*.

```c
void SavePlayerParty(void)
{
    gSaveBlock1Ptr->playerPartyCount = gPlayerPartyCount;
    for (i = 0; i < PARTY_SIZE; i++)
        gSaveBlock1Ptr->playerParty[i] = gPlayerParty[i];
}
```

`SaveSerializedGame` is that call plus `SaveObjectEvents` [load_save.c:196]. So bs46 appended into
the save block, the payload correctly reported `APPENDED` at slot 2 with the count raised — and the
mon was gone, because the console saved seconds later and copied the live array straight back over
it. Writing `gPlayerParty` makes the *same* call carry the write to flash instead of erasing it.

**The slot is always the first free one.** It writes at `slot == playerPartyCount` and then raises
the count, which is exactly what the game does when a mon is caught. *An occupied slot is never
touched*, so the write cannot destroy a Pokemon however wrong everything else is — that is
structural, not a check that could be got past. A full party writes nothing and says so, the same
shape as `givepokemon` answering 3 instead of 2 (mev02).

The answer grew a fifth word past the mon for it — `countBefore | slot << 8 | status << 16`, where
status is 0 (not asked), 1 (appended), 2 (party full) or 3 (dry run) — so the first 116 bytes are
still exactly what bs43 and bs44 returned and their dumps still read.

### Where it is safe to hardcode an address, and where it is not

The payload *does* hardcode `gPlayerParty` and `gPlayerPartyCount`, having refused to hardcode a
save-block address — and the two are not in tension. What decides it is whether the thing **moves**:

| | moves? | so |
| --- | --- | --- |
| `gSaveBlock1Ptr` | yes — a random 4-aligned offset re-rolled on every battle and load [SetSaveBlocksPointers, load_save.c:75] | take it from `r1`/`r2` every call |
| `gPlayerParty` | no — a link-time EWRAM global; bs42 read it as a literal constant in `ZeroPlayerPartyMons`' pool | an address is legitimate |

bs45 and bs46 *measured* the first one moving: `gSaveBlock1Ptr` was 0x0202559C and then 0x02025550
six minutes apart with no reboot — 76 bytes, 4-aligned, inside the 0..124 the mask allows.

### bs47: finding gPlayerParty by finding a Pokemon

    ./scratchpad/run_mg_fast.sh bs47 --buffer-script memory-dump \
        --dump-address 0x02024000 --dump-size 1024 --version firered

    +0x280 = 0x02024280  CHANSEY (#113) Lv26 nick 'Cheemsey' OT 'Tops'
      slot 2: EMPTY, exactly as ZeroMonData leaves one
      0x02024025 = 1        <- gPlayerPartyCount

`scratchpad/find_party.py` does not look where the address was predicted. It walks every 4-aligned
window of the dump and reports the ones that decode as a `struct Pokemon` **with a valid
checksum** — the substruct region summed after decrypting with `personality ^ otId`, which nothing
passes by accident. Exactly one window did, and the species, level and nickname in it are things
only the player's console knew.

Two independent deductions had predicted 0x02024280 and both were right: bs42's dump holds it in
the literal pool of the first of two functions that zero six 100-byte structs
(`ZeroPlayerPartyMons` by source order), and the decomp declares `gEnemyParty[6]` immediately
before `gPlayerParty[6]` [pokemon.c:61-62], so they are exactly 600 bytes apart —
`0x02024028 + 600 = 0x02024280`.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append \
        --write-unsafe --create-mon-species 59 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADF0001 --create-mon-ot-id-type 0 --version firered

`--write-unsafe` is required, the same deliberate override an out-of-scratch `save-write` takes.
Two more refusals are built in: an append together with an absolute `--create-mon-destination` is
two answers to the same question, and an append with `--create-mon-call 0` would put a hundred zero
bytes in the party, so neither builds.

`playerPartyCount` coming back in the party word is also a reading in its own right — the console
says how many mons it was holding, which nothing else in a buffer-script run reports.

### The dry run, and why it is worth a run of its own

`--create-mon-append-dry-run` is the **same run with the two stores left out** — the same ROM call,
the same arithmetic on the same `gSaveBlock1Ptr`. It reports the party count and the address it
*would* have written, and reads that slot's current 100 bytes back in place of the mon it built,
so the answer says what a real run would overwrite. Nothing is written, so it needs no override.

What it settles is the *state* the append depends on — the party count, and whether the slot it
would write is really free. `r2 = gSaveBlock1Ptr` itself was already proven: `save-dump
--dump-block sav1` selects r2, and bs06 read the whole party through it. The dry run is the only
thing that would catch a `playerPartyCount` disagreeing with what is actually in the party, and it
catches it *before* a store rather than after.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script create-mon --create-mon-append-dry-run \
        --create-mon-species 59 --create-mon-level 30 --create-mon-iv 31 \
        --create-mon-personality 0x3ADF0001 --create-mon-ot-id-type 0 --version firered

### bs45: the dry run, on hardware, first try (2026-09-04)

    create-mon: 1 call(s), built at 0x0201C03C, calling 0x08041151,
                WOULD have written 0x02025638
       party: DRY RUN - nothing was written - the console held 1 mon(s), so a real run
              would write slot 2 of 6
       the slot a real run would write is EMPTY exactly as ZeroMonData leaves one

The count is **1**, matching the one Pokemon the player could see on their own screen, and the
slot is free. The implied `gSaveBlock1Ptr` is 0x0202559C — bs08's `anchors` had read 0x0202553C on
a different boot, and the two differing is the expected thing, not a discrepancy: the save blocks
move between save loads, which is exactly why the payload computes the address instead of taking
one.

**AN EMPTY PARTY SLOT IS NOT A HUNDRED ZERO BYTES, and the first version of this check said so
wrongly.** bs45 came back with one non-zero byte — `0xFF` at offset 85 — and the log printed `DO
NOT APPEND`. The console is right and the check was wrong: `ZeroMonData` zeroes everything and then
ends `arg = MAIL_NONE; SetMonData(mon, MON_DATA_MAIL, &arg)` [pokemon.c:1737], and `mail` is at
offset 0x55 of `struct Pokemon`. A slot the game itself zeroed looks exactly like that.

It is *better* evidence than a hundred zeros would have been. Unclaimed memory does not happen to
carry MAIL_NONE in the one byte that means it; a party slot the game emptied does. So the same
answer that looked like a refusal is a third confirmation that the computed address really is
`playerParty[1]`. `buffer_script.EMPTY_PARTY_SLOT` is that shape, and `is_empty_party_slot` is the
check.

### bs48, bs49: the append, on hardware (2026-09-04, both first try)

bs48 was the dry run at the measured address — the append's own code, not a dump, reading the count
off 0x02024025 and computing the slot:

    WOULD have written 0x020242E4        = gPlayerParty + 100
    the console held 1 mon(s), so a real run would write slot 2 of 6
    the slot ... is EMPTY exactly as ZeroMonData leaves one

bs49 then ran it for real, with the two stores back in and nothing else changed:

    create-mon: 1 call(s), calling 0x08041151, written to 0x020242E4
       party: APPENDED to the player's party, and the count was raised
              - the console held 1 mon(s) and this one is slot 2 of 6
       personality 0x3ADF0001  otId 0xE5BBDF65  checksum VALID  SHINY
       species 59 ARCANINE  Lv30  nickname 'ARCANIN'  OT 'GURVAN'

13/13 predicted fields, `never=[]` on every console block, one call. The address bs49 wrote is the
one bs48 said it would, which is what makes the dry run worth having: the two runs cannot disagree
without one of them being wrong, and they did not.

### What is left

Nothing in this line. A Pokemon chosen by us, built by the console's own ROM from eight arguments
we passed, lands in the player's party through a Mystery Gift link and survives the save.

The next questions are elsewhere: `gRngValue` in a context that matters — an encounter rather than
the gift menu — and LeafGreen, where every address in `rom_map.py` is FireRed BPRF v0x0A and none
of it transfers. `--create-mon-destination`, `--create-mon-append` and the
dry run are all proven offline, including that the dry run and the real append compute the *same*
address at every party size — if they could disagree the dry run would prove nothing — and that
the append writes nothing past `playerParty[6]`, which ends at 0x38 + 600 = 0x290, exactly where
`money` begins [global.h:774].

## `call` — any ROM function, with arguments we choose (built, hardware run pending)

`rng-trace` calls a function with whatever happens to be in the registers. `create-mon` calls the
one function whose signature it was written around. `call` is the general form both are special
cases of: an address, up to eight argument words, the `r0` that comes back, and **one address read
either side of the call**.

    --buffer-script call --call-address 0x080486D1 --call-arg 0xC0DE --call-watch 0x03004220

The calling convention is not new and is not guessed. bs42 disassembled `CreateMon`'s own prologue
and read its four stack arguments at entry `sp + 0, 4, 8, 12`; bs43 and bs44 then called it on
hardware with eight arguments and got 13/13 predicted fields back, bs44 existing only to prove the
fourth stack word that bs43's `otIdType 0` left unread. So `r0..r3` then `[sp+0..12]` is a
**measured** convention here. `asm/call.s` pushes the sixteen bytes for every call, whatever
`argc` says, because the callee never pops them and a function taking fewer simply does not read
them — which is exactly what `create-mon.s` does.

The image, all offsets from `_start`:

    0x000  b .Lcode
    0x004  function    THUMB pointer (bit 0 set), or 0 to call nothing
    0x008  argc        how many of the eight words below are meant
    0x00C  args[0..7]  r0, r1, r2, r3, then [sp+0], [sp+4], [sp+8], [sp+12]
    0x02C  watch       a word to read before and after the call, or 0
    0x030  RESULT  calls used, function, argc, r0, *watch before, *watch after

### `watch` is what makes the answer evidence

`SeedRng` returns nothing at all — `void SeedRng(u16 seed) { gRngValue = seed; }`
[decomp:src/random.c:15]. A return value would therefore prove only that *something* ran. Reading
`gRngValue` immediately before and immediately after the call is the only thing that says the call
did what it was called for, and it is the same idea as `rng-trace`'s two reads, which is what
turned 0x03004220 from a hypothesis into the address.

The console's own `SeedRng`, twelve bytes and its literal pool as bs14 read them off the cartridge
at 0x080486D0:

    0004  lsls r0, r0, #16        the u16 truncation the decomp's signature promises,
    000c  lsrs r0, r0, #16        made explicit by the compiler
    0149  ldr  r1, [pc, #4]       -> 0x03004220
    0860  str  r0, [r1]           gRngValue = seed
    7047  bx   lr
    .word 0x03004220

Those exact bytes are the offline fixture: `tests/test_buffer_script.py` executes them under
unicorn through the payload, so the round trip — our ARM code `bx`ing into THUMB ROM, the callee's
own `bx lr` bringing it back, the 24-byte answer on ident 19 — is proven before a run is spent.
The eight-argument path is checked with powers of two as the arguments, so the returned sum names
**exactly which slots arrived**; a missing or duplicated argument cannot cancel out.

### Why it is worth a run: seeding the RNG where our code cannot reach

The blocker on `gRngValue` has always been that `CLI_RUN_BUFFER_SCRIPT` only runs while the
Mystery Gift link is up, so native code cannot watch the RNG at an encounter the way bs15 watched
it at the menu. `SeedRng` inverts the problem: instead of watching the RNG in the grass, **fix it
during the link and read the result out of the grass afterwards**.

That rests on a fact settled offline, from the decomp's own call sites. `SeedRng` is called in
exactly four places, and three of them cannot happen here:

| site | when |
|---|---|
| `SeedRngAndSetTrainerId` [title_screen.c:735] | the title screen, **before** the main menu |
| `LinkTestScreen` [link.c:318] | unused debug screen |
| `Debug_RfuIdle` [link_rfu_2.c:2670] | unused debug screen |
| `RfuMain1` [link_rfu_2.c:2116] | Switch-only, and gated on a Sloop syscall |

Mystery Gift is reached *from* the main menu, so it runs downstream of the title screen's seeding,
and the player returns to the overworld the same way. **Nothing reseeds between our call and the
encounter** — the chain is unbroken until the player resets.

### The Switch-only reseed, and why it is not firing

`RfuMain1` has a `REVISION >= 0xA` block that exists in no GBA build:

```c
if ((svc_4b() & SVC4B_RESEED_RNG) != 0)
    SeedRng(ReadU16(&GetHostRfuGameData()->compatibility.playerTrainerId));
```
[decomp:src/link_rfu_2.c:2114]

`svc_4b` is `swi 0x4b`, one of the syscalls the Sloop emulator adds [src/sloopsvc.c:135], so the
*emulator* decides when this fires. `GetHostRfuGameData()` returns `&gHostRfuGameData`, the
console's **own** advertised game data, and `InitHostRfuGameData` fills its `playerTrainerId` from
`gSaveBlock2Ptr->playerTrainerId` [decomp:src/link_rfu_3.c:854] — so the value would be 0xDF65 on
this console, the visible TID 57189.

It is not firing during a Mystery Gift link, and that took no hardware run to establish. `RfuMain1`
runs every frame while RFU is up, so a set bit would pin `gRngValue` near 0xDF65 continuously —
and bs15's 96 samples free-ran with gaps of exactly 2 on all 95. The arithmetic agrees: bs15's
first sample is **1,374,895,295** turns from 0xDF65, which is not a near miss but an unrelated
state. `frlgsim/lcg.py` is what can say that exactly.

That check is worth keeping as a control on every seeded run, because bs15's samples rule the hook
out *during* the link and say nothing about the moment the link closes. If the encounter turns out
to descend from 0xDF65 rather than from the seed we set, the answer names the hook instead of
leaving a failed run unexplained.

## Reading a caught Pokemon back into the RNG

`GenerateWildMon` calls `CreateMonWithNature(&gEnemyParty[0], species, level, USE_RANDOM_IVS,
Random() % NUM_NATURES)` [decomp:src/wild_encounter.c:233], and `CreateMonWithNature` rolls the
personality until it matches that nature:

```c
do { personality = Random32(); } while (nature != GetNatureFromPersonality(personality));
CreateMon(mon, species, level, fixedIV, TRUE, personality, OT_ID_PLAYER_ID, 0);
```

Because `hasFixedPersonality` is TRUE and the OT is the player, `CreateBoxMon` draws nothing more
until the IVs — which are the very next two draws. So a wild Pokemon is **four consecutive draws**:

    d1, d2  the accepted personality      d3  HP/ATK/DEF      d4  SPEED/SPATK/SPDEF

and that is why a caught Pokemon is a reading of `gRngValue`. The personality alone leaves 2¹⁶
candidate states, because only the *top* half of each state is ever returned and the low half of
the first is unconstrained. The two IV draws are 30 more bits of check on the draws that **follow**,
and exactly one state survives — `lcg.recover_wild_state`, and `scratchpad/rng_encounter.py` is the
command-line form of it.

Which half of the personality is drawn first is **not** assumed. `Random32()` is
`(Random() | (Random() << 16))` [decomp:include/random.h:15] and C does not order the operands of
`|`, so it is the French build's compiler that decides. Both orders are tried and the IVs settle
it, so the answer is a reading rather than a convention taken on trust.

### What a distance means, and what it does not

`lcg.distance` is exact and always answers, because the map is a **permutation** of all 2³² states.
There is no such thing as "not on the orbit", and that is precisely why a distance is only evidence
when it is *small*: a random pair of states sits ~2³¹ apart, so a distance under N arises by chance
with probability N / 2³². `buffer_script.lcg_distance` walks one step at a time and gives up at a
limit — all a frame-to-frame gap needs, and useless at encounter range, where the answer is
thousands to millions. `frlgsim/lcg.py` uses baby-step/giant-step on the affine map instead: 2¹⁷
operations rather than up to 2³².

## `table-scan` — finding a table by its SHAPE (built, hardware run pending)

Every address this project has found by searching rested on a **constant that only one place could
hold**: RAND_MULT in `Random`'s literal pool [bs13], `0x00450045` in `sEasyChatGroups` [bs16],
`0x64646464` in `gSpeciesInfo` [bs38]. `memory-scan` answers "where is this word", which requires
knowing the word first.

**A table of pointers carries no such constant.** `gSpecialVars` is 21 words holding the addresses
of the special script variables [decomp:data/event_scripts.s:51], and every one of those addresses
is exactly what we are trying to find out. There is nothing in it to search for.

What it does have is a **relation between its entries**. `gSpecialVar_0x8000` through
`gSpecialVar_0x800B` are twelve `u16`s declared consecutively [decomp:src/event_data.c:16], and
`gSpecialVars` lists them in var-id order, so its first twelve words each sit exactly **2** above
the one before. That is a shape, and a shape can be searched for while knowing none of the values.

`table-scan` finds every maximal run of `runlen` words where each is exactly `delta` above its
predecessor, and answers with **where the run starts and what value it starts with**. For
`gSpecialVars` that first value *is* `&gSpecialVar_0x8000`, so the run does not merely locate the
table — it reads the answer out of it. Locating and reading are one run.

    ./scratchpad/run_mg_fast.sh bsNN --buffer-script table-scan --table-delta 2 \
        --table-runlen 12 --table-start 0x08140000 --table-end 0x08400000 --version firered

**Why the run is exactly twelve.** `gSpecialVars` continues past entry 11, but entry 12 is
`gSpecialVar_Facing`, which `event_data.c` declares *after* `Result` and `LastTalked` — so it is +6
from entry 11 and the ascending run stops dead. Asking for 13 finds nothing against the real table,
and a test asserts exactly that: it is the check that the fingerprint is matching the shape rather
than merely "some pointers".

**Why the range.** `script_data` follows every `.text` object in the link order
[ld_script_rev10.ld:318], and `gScriptCmdTable` (214 entries, 856 bytes) opens the section with
`gSpecialVars` immediately after it. Text reaches at least 0x08148C74 (the return address bs08
measured), and `.rodata` starts below `gSpeciesInfo` at 0x0824CDFC — so `gSpecialVars` lies between
them. 0x08140000..0x08400000 is that bracket with margin: 939 frames, about 16 seconds.

**The frame budget is NOT memory-scan's.** A shape test is ~7 ARM instructions a word where a value
test is ~1.75, so the same *block count* would be 2.5x the load on a frame the console needs for its
RFU link. `TABLE_SCAN_DEFAULT_BLOCKS` is 192 blocks of 16 bytes — 768 words, ~6.7k instructions a
call, which is what `memory-scan`'s 512 blocks of 32 actually cost. Matching the proven budget
matters more than covering ground.

**What is new in the payload, and it is the only genuinely new mechanic since `memory-scan`: run
state.** A value search is memoryless — a word matches or it does not. A run has to be carried
across the `ldmia` boundary *and* across the frame boundary, because the table may straddle either.
So `run`, `runstart` and `expect` live in the image at 0x22C..0x234 beside the cursor, and are
saved on the way out of every yield. A test runs the search at **one block per call** so the frame
boundary falls inside the table itself, and gets the same answer.

**One documented edge.** `expect` starts at 0, so if the very first word of the range happens to be
0 it is credited to a run whose `runstart` was never written, and it reads back as 0.
`read_table_scan` discards any hit outside the range that was asked for, which is exactly that case;
starting the range a block before anything of interest removes it entirely.

Proven offline before any hardware time, as every payload here is: assembled to 940 bytes, run under
unicorn against a synthetic cartridge carrying a real `gSpecialVars` (7 tests in
`tests/test_buffer_script.py`), and then through the whole Mystery Gift link in
`scratchpad/mg_client_harness.py --buffer-script table-scan`, which plants the table in the emulated
cartridge and reads `table at 0x08160000  first entry 0x02024C40` back off the link in 43 frames.

**Why this address is wanted.** It is the one blocker on the RNG-reading NPC (docs/rng.md): a RAM
script of `copybyte` x4 from 0x03004220..23 into `gSpecialVar_0x8000`/`0x8001`, then
`buffernumberstring` and `msgbox`. `gSpecialVar_0x8000` is `EWRAM_DATA`, a link-time global that
does not move — unlike a save block, which `SetSaveBlocksPointers` re-rolls on every battle — so
naming it as a constant is sound in a way naming a save address never is.
