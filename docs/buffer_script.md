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

## Left

1. ~~bs06: bs05's own command again~~ DONE, above. Next: **bs07, 1024 bytes of the cartridge at 0x08000000**: the
   GBA header names the build the Switch release ships (0xA0 title, 0xAC game code, 0xBC version),
   which is what calling into the ROM needs, and it proves 1024 bytes on hardware at the same time.
   `buffer_script.emulate` now maps ROM, so such a payload is checked offline like any other. `echo_gaps.py` on the capture afterwards: every block
   must read `never=[]`. That single line is the whole verdict.

2. Writing, rather than reading: the same offsets take a `str` as easily as a `ldr`.

3. Calling into the ROM, which needs a real address and therefore a way to identify the build the
   console is running - which the dump can now answer, by reading the ROM header at 0x080000A0.
