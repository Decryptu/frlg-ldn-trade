---
title: Mystery Gift on Sword
parent: Sword and Shield
nav_order: 5
---

# The local-wireless branch of the Mystery Gift menu

The menu branch that made this title a target in the first place, and the shape of what it
carries. Nothing here has been spoken to a console yet.

## Mystery Gift has a local branch

FACT, from the game's own state names. The receive-method chooser is
`StateSelectReceiveDataBase` and it has five siblings, one per menu button
(`L_mystery_top_btn_00` .. `_04`):

| state | what it is |
|---|---|
| `StateSelectReceiveDataInternet` | over the network |
| `StateSelectReceiveDataSerial` | a serial code / password |
| **`StateSelectReceiveDataLocal`** | **local wireless** |
| `StateSelectReceiveDataFromBall` | the Poke Ball Plus |
| `StateSelectReceiveDataRankMatch` | ranked-battle rewards |

and the receive states themselves are `StateReceiveBase`, `StateReceiveInternet`,
`StateReceiveSerial`, **`StateReceiveLocal`** (`0x01004938`), `StateReceiveFromBall`,
`StateReceiveRankMatch`, plus `StateReceiveNews` and `StateReceiveComplete`.

The game also counts what it received by channel: the play-record keys are `fushigi_net`,
`fushigi_serial` and **`fushigi_p2p`**, sitting beside `yy_battle_single_p2p` / `_net` in the same
table. A record key per channel is a channel the game expects to use.

And the menu is not a developer leftover - it is a line the player reads, in their own language.
`/bin/message/French/common/mystery.dat` in the base game's RomFS, decoded, gives the whole receive
menu:

| line | text |
|---|---|
| 63 | `Via Internet` |
| 64 | `Via un code ou mot de passe` |
| **69** | **`Via communication sans fil locale`** |
| 65 | `Voir vos Cadeaux Mystère` |

with the top menu above it at 72-75 (`Recevoir un Cadeau Mystère`, the Wild Area news, the Poké Ball
Plus, the Battle Stadium rewards).

**DEDUCTION: on that screen the console SEARCHES, so a distributor hosts and we would be the host.**
Line 42 is `Communication sans fil locale activée.`, exactly parallel to line 39's
`Connexion à Internet activée.`; line 9 is `Recherche de cadeau en cours...` and line 11
`Aucun cadeau n'a été trouvé.` That is a receiver scanning, not one advertising - which means
`--scan-only` seeing nothing on that screen is the expected result and not a failure.

The archive is the Gen 6/7/8 message container and `scratchpad/gfl_text.py` reads it. Its key was
solved out of the file rather than looked up: every line ends in a `0x0000` terminator, so rotating
the last ciphertext halfword back by three per character gives that line's starting key, and the
values across lines came out an arithmetic sequence - `0x7C89 + line * 0x2983`, rotating left by 3
within a line.

UNKNOWN: what `StateReceiveLocal` actually speaks. **There is no static call path** from the
Mystery Gift app to the LDN session setup - checked over the whole app to depth 10 with a
function-level call graph. That is not evidence the branch is dead: the game reaches its network
layer through vtables and delegates, which a static walk cannot follow, and the same search finds no
path from the Union Room's own code either.

A first attempt at this DID report a path, and it was an artefact worth recording: the walker
bounded each function by "the first 0x1000 bytes after its entry", walked through the `ret` into the
next function's body, and stitched two unrelated bodies into one edge. Both of the hops it produced
turned out to be refcounted-pointer setters that call nothing. `scratchpad/swsh_reach.py` builds a
real function-level graph now.

So the cheap decisive test is the air, not more reading: open the Mystery Gift local-wireless screen
on the console and see whether it advertises a network or is scanning for one.

## A gift is a multiple of 0x2D0 bytes

FACT, and it is the game checking rather than us measuring. At `0x00ff22d8` the Mystery Gift code
divides a received length by **0x2D0** - as a reciprocal multiply, `umulh` then `lsr #7` - takes the
remainder with `msub`, and **branches to the error path if it is non-zero**:

    0x00ff22e4  umulh x8, x21, x8        ; x21 = the length
    0x00ff22e8  lsr   x28, x8, #7        ; x28 = length / 0x2d0, the record COUNT
    0x00ff22ec  mov   w8, #0x2d0
    0x00ff22f0  msub  x8, x28, x8, x21   ; the remainder
    0x00ff22f4  cbnz  x8, #0xff272c      ; not a whole number of records -> refuse

So a gift payload is *n* records of 0x2D0 bytes and nothing else will be accepted. The same app
allocates a 0x2D0 object at `0x00feba7c`, which is one record. 0x2D0 is the size PKHeX gives a Gen 8
Wonder Card, so the two agree - but the number here came out of the game's own length check, which
is the one that matters when we are the side building the payload.
