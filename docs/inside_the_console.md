---
title: Inside the console
nav_order: 4
has_children: true
---

# Inside the console

The Mystery Gift client will run code we send it, through two interpreters.

`CLI_RUN_MEVENT_SCRIPT` (opcode 15) hands our bytes to the game's 17-opcode Mystery Event VM.
`CLI_RUN_BUFFER_SCRIPT` (opcode 21) hands them to the CPU: 1024 bytes copied into
`gDecompressionBuffer` and called as
`func(&client->param, gSaveBlock2Ptr, gSaveBlock1Ptr)` [decomp:src/mystery_gift_client.c:276].
No glitch, no prepared save, nothing for the player to set up; the console sits on its own Mystery
Gift menu the whole time.

What that has established on retail hardware: the console's memory read and written (the write
reaches flash), its ROM mapped into named functions for the build it actually runs, a search
primitive that sweeps megabytes in one run because the payload is re-entered once a frame, the
first call into its ROM, and `gRngValue`.

Three rules hold across everything here.

**A payload is executed offline before it is ever sent.** `buffer_script.emulate` and
`emulate_repeating` run it under unicorn on a model of the GBA memory map, and the simulated
consoles run it too. A payload that faults, or that never returns 1, hangs the Mystery Gift menu
with no way out.

**Nothing is inferred from the decompilation's addresses.** The console runs the French build, game
code BPRF, software version `0x0A`, read out of its own cartridge header. `frlgsim/rom_map.py`
records how each address was obtained. The decomp's *link order* is fair evidence and has been used
twice; its addresses never are.

**Nor from the other cartridge's.** The second console is French LeafGreen, BPGF `0x0A`. Every
payload here works on it unchanged and every RAM address measured so far is the same, but its ROM is
not FireRed's. [LeafGreen](leafgreen.md) has the measured deltas and the two runs that were lost to
assuming one.
