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

## The console advertises on that screen

A scan pointed at the Mystery Gift local-wireless screen finds the console advertising an LDN
network: local communication id `0x0100ABF008968000`, version 4, scene id 65535, accept policy ALL,
one of two participants, 384 bytes of application data. The Link Trade screen advertises the same
comm id under scene id 60001, so the scene id is what separates the two features on the air.

The screen's own text is a receiver's. The same archive carries, at line 42, `Communication sans fil
locale activée.`, parallel to line 39's `Connexion à Internet activée.`; line 9 is `Recherche de
cadeau en cours...` and line 11 `Aucun cadeau n'a été trouvé.` The console holds the network open
and looks for a gift over it, so the distributor joins.

Two bytes of the game's application data separate the two sessions. Against five trade
advertisements and four gift ones from the same console and the same player, everything else in the
384 bytes is either identical or random per session:

    app data offset   gift   trade
    0x97              0xFF   0x0D
    0xB9              0x00   0xAA

Both sit in the game's own data, which starts at 0x18 of the advertisement. What they carry is
unread. The password CRC is zero on both, so neither session is password-gated.

A 70-second monitor capture of the console's own channel while it sat on that screen holds 339
beacons and 435 LDN advertisement action frames from it and no probe request at all. It is not
scanning the channel it hosts on. A scan of the other channels would not appear in a capture parked
on one, so this does not exclude one.

## The session accepts and the mesh refuses

The transport line that reaches the game on the trade scene runs on the gift scene as far as the
station handshake and no further. The console answers the connection request on 0x14, sends its
type 2 station record of 840 bytes and accepts the station, then answers the mesh join request on
0x18 with a refusal:

    02 00 ff ff 01        JOIN_RESPONSE, refused, reason 1

Two of two associations refused identically, one with the refusal in the join phase and one in the
hold phase that followed it. Nothing on 0x58, 0x7C or 0x80 follows a refusal, so no application data
has been exchanged on this scene.

The same command line against scene 60001, the Link Trade, is accepted five times out of five with a
148-byte join response, so the refusal is a property of the gift scene and not of the flags.

Reason 1 is the game refusing the join, not the transport. The addresses in this section are
Sword's `main`, the image the mesh addresses elsewhere in these pages are read from; the menu and
gift-format addresses above are Shield's. `ProcessJoinRequestJob` runs `InitialStep`,
`CheckApprovalJoin`, `SendJoinRefused`, `SendJoinResponse`, `WaitResponseAck` and `JoinSucceeded`,
and its state names are strings at `0x03ad0f4e`..`0x03ad1010`. `CheckApprovalJoin`
(`0x01553d20`) loads the function pointer at offset `0x60` of the `nn::pia::mesh::MeshProtocol`
object held in the global at `0x04c4db60` and calls it:

    0x01553cc0  ldr  x8, [x8, #0x60]      ; the approval callback
    0x01553cc4  cbz  x8, #0x1553d34       ; no callback installed -> accept
    0x01553d2c  blr  x8
    0x01553d30  tbz  w0, #0, #0x1553d4c   ; bit 0 clear -> refuse
    0x01553d54  mov  w9, #1
    0x01553d58  strb w9, [x19, #0xbc]     ; the refusal reason, byte for byte on the wire

The reason byte is not translated on the way out. `SendJoinRefused` (`0x01553d80`) passes it to
`0x0154cd00`, which writes the word `0xFFFF0002` and then the reason at offset 4.

The other refusal reasons come from the transport check at `0x0154806c`, which returns `0xFF` for
"no objection" and 0, 2, 4 or 5 otherwise; that check passed. Reason 1 is reachable only through the
application callback.

The callback installed at `MeshProtocol+0x60` is Pia's own trampoline `0x0157fcfc`, put there by
`0x0171a0b4` from the pointer slot `0x04c513f8`. It reads the field at offset `0xb0` of the object
the global `0x04c4b848` points to, tail-calls it, and returns 1 — approve — when that field is null:

    0x0157fcfc  adrp x8, #0x4c4b000 ; ldr x8, [x8, #0x848] ; ldr x8, [x8]
    0x0157fd08  ldr  x1, [x8, #0xb0]
    0x0157fd0c  cbz  x1, #0x157fd14      ; null -> mov w0, #1 ; ret
    0x0157fd10  br   x1

A refusal therefore means that field holds a function on the gift scene. Which function, and what it
inspects, is unread. The two-instruction setter `0x0157fcf4` (`str x1, [x0, #0xb0] ; ret`) has no
call site anywhere in the image, so the field is written by some other route.

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
