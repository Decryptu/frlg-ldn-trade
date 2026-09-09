---
title: The trade
parent: Sword and Shield
has_children: true
nav_order: 4
---

# Trading with a retail Sword and Shield

**A retail Sword and Shield has completed a trade with this project.** It took our Pokemon, gave
us its own, wrote its save and returned the player to the overworld. The three pages under this one
are the road there, in the order the layers sit:

- [The trade screen](swsh_trade_screen.md) - what the game shows the player, the message ids, and
  the box state machine that drives the screen.
- [The content framework](swsh_trade_contents.md) - the sync framework the trade rides on: what a
  content is, when each one is constructed, and how a message is routed to a handler.
- [The confirmation ladder](swsh_trade_confirmation.md) - the last phase, rung by rung, and the
  run that completed the trade.

The run line that completes a trade is in the repository's notes, not here; this is the reading it
rests on.
