---
title: Inside the console
nav_order: 4
has_children: true
---

# Inside the console

The Mystery Gift client will run code we send it. There are two interpreters behind that door and
this section is both of them, plus what they have read back out.

`CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands our bytes to the game's 17-opcode Mystery Event VM.
`CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the CPU: 1024 bytes copied into
`gDecompressionBuffer` and **called** as
`func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr)` [decomp:src/mystery_gift_client.c:276].
No glitch, no prepared save, nothing for the player to set up — the console is sitting on its own
Mystery Gift menu the whole time.

What that has established, on retail hardware: the console's memory read **and written** (the write
reaches flash), its ROM mapped into named functions for the build it actually runs, a search
primitive that sweeps megabytes in one run because the payload is re-entered once a frame, the
first call into its ROM, and `gRngValue`.

Two rules hold across everything here:

- **A payload is executed offline before it is ever sent.** `buffer_script.emulate` and
  `emulate_repeating` run it under unicorn on a model of the GBA memory map, and the simulated
  consoles run it too. A payload that faults or never returns 1 hangs the Mystery Gift menu with
  no way out.
- **Nothing is inferred from the decompilation's addresses.** The console runs the FRENCH build,
  game code BPRF, software version `0x0A`, read out of its own cartridge header. `frlgsim/rom_map.py`
  records how each address was obtained. The decomp's *link order* is fair evidence and has now
  been used twice; its addresses never are.
