---
title: Mystery Gift
nav_order: 3
has_children: true
---

# Mystery Gift

The console's Mystery Gift menu is the widest door this project has found into a retail save, and
unlike trading it needs no Pokemon Center. A console sitting on the Wonder Cards screen will accept
a Wonder Card, a delivery script, a Wonder News item, a visiting trainer for the Battle Tower, and a
level 30 Celebi holding mail straight into the party.

These pages cover authoring and delivering gifts. What the link can *execute* - the Mystery Event
bytecode VM and native ARM code - is under [Inside the console](inside_the_console.md).

One trap governs everything here: **a Wonder Card and an NPC-bound script are mutually exclusive.**
There is one RAM script slot, and `ValidateSavedWonderCard` requires `ValidateRamScript`
[decomp:src/mystery_gift.c:186], which passes only for `MAP_UNDEFINED` / object `0xFF`. After an
`initramscript` the card is intact in the save but the menu reports none. Any later Wonder Card
takes the slot back.
