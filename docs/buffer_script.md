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
host accepts 1024 bytes on an ident that normally carries 4.

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
printed "erreur de connexion, rapprochez-vous" during transmission and left. FACTS:

- `MGL_Send` chunks at 252 bytes and, before EACH chunk and again before it finishes, waits on
  `MGL_HasReceived(link->sendPlayerId)` = `GetBlockReceivedStatus()` - a block WE sent
  [mystery_gift_link.c:155-213,77]. 256 bytes is header + 2 chunks = 3 handshakes; 608 is
  header + 3 chunks = 4.
- bs05's log shows `SEND_BLOCK_INIT` rising by exactly 3 and then stopping: the console sent the
  header and two chunks and waited for a handshake that never came, until the game timed out.
- `acklag.py`: 1 stall, worst inbound gap 37 ms. NOT the hold.
- The payload ran. The console repointed its own outgoing message and began transmitting a
  608-byte message with a valid header. The primitive is sound; the transport is the limit.

HYPOTHESIS (not yet confirmed): our host sends nothing while receiving - `_drain_recv_blocks`
returns as soon as a chunk leaves the message incomplete - so those handshakes have been satisfied
by accident, out of the spare copies of our own blocks (`ram_script_block_repeat` 3, so our 2-block
payload goes out 6 times and 4 land during the console's send window). That supply runs out at four
chunks. Confirm it before building on it.

PROVEN SAFE TODAY: a dump of 256 bytes or less. The party (600 bytes at SaveBlock1 0x38) can be
taken in three runs of 200 without any of this being fixed.

## Left

**1. The multi-chunk receive (the next job).** `ConsoleClientModel` in tests/test_mystery_gift_flow.py
does not model the per-chunk handshake at all, which is why 608 passed offline and failed on the
console: both simulated sides shared our own optimistic assumption. Make the model faithful to
`MGL_Send` - it may only hand over its next chunk after the host has sent it a block - watch the
608-byte test fail exactly as bs05 did, then fix the host to answer each chunk, and 1024 should
follow. Do not chase this on hardware; it reproduces offline once the model is honest.

2. Writing, rather than reading: the same offsets take a `str` as easily as a `ldr`.

3. Calling into the ROM, which needs a real address and therefore a way to identify the build the
console is running - which the dump can now answer, by reading the ROM header at 0x080000A0.
