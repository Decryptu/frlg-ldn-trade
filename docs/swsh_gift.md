---
title: The Mystery Gift menu
parent: Sword and Shield
nav_order: 4
---

# The local-wireless branch of the Mystery Gift menu

Sword and Shield's Mystery Gift menu has a local-wireless branch — the same shape of target as
FireRed's Wonder Card, one hardware generation later. Nothing on this page has been spoken to a
console; it is read out of Shield 1.3.2's `main` and its RomFS.

## The menu

The receive-method chooser is `StateSelectReceiveDataBase` and it has five siblings, one per menu
button (`L_mystery_top_btn_00` .. `_04`):

| state | method |
|---|---|
| `StateSelectReceiveDataInternet` | over the network |
| `StateSelectReceiveDataSerial` | a serial code or password |
| `StateSelectReceiveDataLocal` | **local wireless** |
| `StateSelectReceiveDataFromBall` | the Poke Ball Plus |
| `StateSelectReceiveDataRankMatch` | ranked-battle rewards |

and the receive states are `StateReceiveBase`, `StateReceiveInternet`, `StateReceiveSerial`,
`StateReceiveLocal` (`0x01004938`), `StateReceiveFromBall`, `StateReceiveRankMatch`, plus
`StateReceiveNews` and `StateReceiveComplete`.

The game also counts what it received by channel: the play-record keys are `fushigi_net`,
`fushigi_serial` and `fushigi_p2p`, beside `yy_battle_single_p2p` / `_net` in the same table.

The branch is a line the player reads. `/bin/message/French/common/mystery.dat` in the base game's
RomFS, decoded with `scratchpad/gfl_text.py`, gives the whole receive menu:

| line | text |
|---|---|
| 63 | `Via Internet` |
| 64 | `Via un code ou mot de passe` |
| 69 | `Via communication sans fil locale` |
| 65 | `Voir vos Cadeaux Mystère` |

with the top menu above it at 72–75 (`Recevoir un Cadeau Mystère`, the Wild Area news, the Poké Ball
Plus, the Battle Stadium rewards).

## The console is the receiver on that screen

The same archive carries, at line 42, `Communication sans fil locale activée.`, exactly parallel to
line 39's `Connexion à Internet activée.`; line 9 is `Recherche de cadeau en cours...` and line 11
`Aucun cadeau n'a été trouvé.` That is a receiver scanning rather than a host advertising, which
means a distributor hosts and `--scan-only` seeing nothing on that screen is the expected result.

This is inferred from the text; a scan pointed at that screen would settle it directly.

## A gift is a multiple of 0x2D0 bytes

At `0x00ff22d8` the Mystery Gift code divides a received length by 0x2D0 as a reciprocal multiply,
takes the remainder with `msub`, and branches to the error path if it is non-zero:

    0x00ff22e4  umulh x8, x21, x8        ; x21 = the length
    0x00ff22e8  lsr   x28, x8, #7        ; x28 = length / 0x2d0, the record COUNT
    0x00ff22ec  mov   w8, #0x2d0
    0x00ff22f0  msub  x8, x28, x8, x21   ; the remainder
    0x00ff22f4  cbnz  x8, #0xff272c      ; not a whole number of records -> refuse

So a gift payload is *n* records of 0x2D0 bytes and nothing else is accepted. The same app allocates
a 0x2D0 object at `0x00feba7c`. PKHeX gives a Gen 8 Wonder Card the same size.

## What `StateReceiveLocal` speaks is not known

There is **no static call path** from the Mystery Gift app to the LDN session setup, checked over the
whole app to depth 10 with a function-level call graph (`scratchpad/swsh_reach.py`). That is not
evidence the branch is dead: the game reaches its network layer through vtables and delegates, which a
static walk cannot follow, and the same search finds no path from the Union Room's own code either.

A first attempt did report a path and it was an artefact of the walker: it bounded each function by
"the first 0x1000 bytes after its entry", walked through the `ret` into the next function's body, and
stitched two unrelated bodies into one edge. Both hops it produced were refcounted-pointer setters
that call nothing.

The decisive test is a scan pointed at the Mystery Gift local-wireless screen: it says whether the
console advertises a network or searches for one.
