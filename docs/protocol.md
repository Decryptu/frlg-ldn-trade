---
title: The link protocol
nav_order: 2
has_children: true
---

# The link protocol

What the console needs to hear before it will talk to anything, and what it does once it will.

The Switch release runs the original GBA ROM inside an emulator, so there are two layers here and
they fail differently. Beneath the game is the LDN/Pia wireless layer, which is the emulator's own
and is reimplemented by `vendor/LDN` and `frlgsim/pia_connect.py`. Above it is the GBA link - RFU
frames, the seat barrier, block sends - which is the ROM's, and for which
[pret/pokefirered](https://github.com/pret/pokefirered) is authoritative.

Almost every hard bug in this project has come from mistaking one layer for the other. The 3-second
wall looked like a game-level timeout and was an 802.11 rate set. The "hold" looks like a kernel TX
problem and crosses a userspace hop. Read the console protocol notes before assuming where a
failure lives.
