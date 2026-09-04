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

## Left

`CLI_RUN_BUFFER_SCRIPT` is the general case of every other opcode, so what is left is what to write,
not whether it runs. In rough order of value once the probe lands: reading `gSaveBlock1Ptr` (bag,
party, flags, vars - the things no Mystery Event opcode reaches), writing them, and calling into the
ROM, which needs a real address and therefore a way to identify the build the console is running.
