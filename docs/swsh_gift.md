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

A refusal therefore means that field holds a function on the gift scene.

## The callback is the game's participant filter

The field is written by the game's own network code, and the whole chain reads out of Shield 1.3.2
(`scratchpad/swsh/main.bin`). The Shield addresses for the Sword ones above are `CheckApprovalJoin`
`0x017cc450`, its reason-1 store `0x017cc59c` (`strb w9, [x19, #0xba]`), and the Pia trampoline
`0x018414b0`, which reads offset `0xb0` of the object the global `0x02616a30` points to:

    0x018414b0  adrp x8, #0x2616000 ; ldr x8, [x8, #0xa30] ; ldr x8, [x8]
    0x018414bc  ldr  x1, [x8, #0xb0]
    0x018414c0  cbz  x1, #0x18414c8      ; null -> mov w0, #1 ; ret
    0x018414c4  br   x1

Two one-line accessors sit beside it: `0x01841490` (`str x1, [x0, #0xb0] ; ret`) installs a callback
and `0x018414a0` (`str xzr, [x0, #0xb0] ; ret`) clears it. Both have call sites in the game:

| address | what it does |
|---|---|
| `0x006b47b0` | installs the callback, `bl 0x01841490` with the constant `0x006b41c0` out of the pointer slot `0x02616a38` |
| `0x006b5340` | clears the field, `bl 0x018414a0`, leaving Pia to approve every join |

Both are reached from the mode switch `0x006a9af0`, whose byte argument selects between them, so the
game turns its own join filter on and off per activity. That is the difference the two scenes show on
the air.

The installed callback is `0x006b41c0`. It takes the joining station's identity — 16 bytes, staged to
two stack slots from the request — and refuses unless the identity clears both of these:

| gate | fields | refuses when |
|---|---|---|
| a block list | enabled by `[manager+0x21c]`, list at `[manager+0x1c0]`, walked by `0x006be4a0` in 16-byte entries | the identity is in the list |
| a participant allow list | enabled by the flag `[session+0x4f5]`, list at `[session+0x4c0]` with the count at `[session+0x4c8]`, walked by `0x006b8230` | the flag is set and the identity is **not** in the list |

`manager` is the object at `[0x02610000 + 0x4b0]` and `session` is `[manager+0x58]`. `0x006b8230`
also refuses when the station count `[session+0x1a8]` has reached the maximum `[session+0x1f0]`, and
approves outright when the allow-list flag is clear — an empty list is only a refusal once the flag
is set. A match in either walk, or a clear flag, returns 1 and Pia sends the join response.

The flag at `[session+0x4f5]` is set by `0x006b86c4` and `0x006cc7bc`; entries are appended through
`0x006b5c80` -> `0x006b9920` and the list is emptied by `0x006b5c70` -> `0x006b9910`.

A third gate follows the other two. The callback reads the halfword at offset 0x10 of the identity
and **approves outright when it is zero** (`0x006b4248`, `cbz w8`); otherwise it looks for it in a
list at `[manager+0x2b0]` with the count at `[manager+0x2b8]`, and compares it against the halfword
`[manager+0x220]`.

### What the identity is

The object the callback receives is built by `0x0177b7b0` and filled by `0x017b1bd0`, which finds the
mesh station-location table entry for the joining station — the one whose `+0x448` is that station
and whose `+0x440` is 3 — and copies **32 bytes from that entry's `+0x10`** to the identity's offset
zero:

    0x017b1c50  add x1, x23, #0x10 ; mov w2, #0x20 ; mov x0, x20 ; bl 0x18fde50

Those 32 bytes are the station location as the joiner sent it, so every field the callback filters on
is a field the connection request carries. The three qwords the callback reads are the entry's
`+0x10`, `+0x18` and `+0x20`.

Version 4's location deserializer stores the identifying fields well past that window — `0x0185eff8`
onward writes the relay port to `this+0x60`, the constant id to `+0x68`, the variable id to `+0x70`,
the service variable id to `+0x74` and the nat quad to `+0x78`..`+0x7b`, which is the same layout the
5.11-5.45 reading gives. The copied 32 bytes are therefore the location's **address region**, not its
ids, so the lists the callback walks are keyed on the joiner's address rather than on its constant or
variable id. That agrees with the same constant id being accepted on one scene and refused on the
other. Which field the halfword at identity `+0x10` is has not been read.

### What the refusal is not

The same constant id `0x1249a221d8580000` is refused on the gift scene and accepted on the trade
scene, so the refusal is not keyed on the joiner's identity and the block-list branch does not
explain it. The variable id is fresh per run and both readings were refused alike.

The participant maximum is a second candidate — `0x006b8230` refuses when the station count
`[session+0x1a8]` has reached `[session+0x1f0]` — and the two sites that lock that maximum to the
current count (`0x00bd9b30` and `0x01031c74`, both `SetMax(GetCount())`) belong to the raid den and
the rental-multi matching paths, not to Mystery Gift. Nothing arms it on the gift scene.

### Two of the three gates cannot be what refuses

The halfword gate approves. `nn::pia::common::InetAddress` is laid out by its deserializer
(`0x01767a10`) as a 16-byte address field at `+0x08`, zero-filled before use and carrying a 4-byte
big-endian IPv4 at `+0x08` unless the size byte is 0x12, and the port at `+0x18`. The location keeps
its public address at `+0x00` and its private one at `+0x28`, so the identity's 32 bytes lie inside
the public address, and the halfword the callback reads at identity `+0x10` is address-field byte 8 —
zero for every IPv4 station. `cbz` on it is taken and the callback approves.

The allow list is not consulted either. The flag at `session+0x4f5` is cleared (`strb wzr`) at
`0x006ca848`, immediately before the same function builds its `LdnCreateSessionSetting` at
`0x006ca86c`, and `0x006b8230` approves outright when that flag is clear.

That leaves the participant maximum. `0x006b8230` refuses when the Pia station count
`[pia_session+0x1a8]` is not below `[session+0x1f0]`, and the only route that writes `+0x1f0` is the
accessor `0x006b9900`, reached through one wrapper `0x0110e5e0` with exactly two call sites —
`0x00bd9b30` and `0x01031c74`, the raid den and rental-multi matching paths. A store scan for that
offset over the whole game band finds no other writer on either LDN session-creation path. So on the
Mystery Gift scene the maximum is left at whatever the session was constructed with, and the
comparison is unsigned: a maximum of zero refuses every join, at any station count.

Whether that field is zero at runtime is not read, and the console's own behaviour argues it is not:
the distributor joins, so some join has to be acceptable. What is measured is that nothing on the
gift path sets it, and that the two activities installing this same filter both set it first.

## The console announces on every channel and never scans

Monitor captures taken while the console sits on the Mystery Gift local-wireless screen, one per
2.4 GHz channel, with the console hosting on channel 6:

| channel | beacons from it | LDN advertisement action frames | probe requests |
|---|---|---|---|
| 1 | 0 | 153 in 90 s | 0 |
| 6, the one it hosts on | 339 in 70 s | 435 in 70 s | 0 |
| 11 | 0 | 95 in 90 s | 0 |

Each capture holds hundreds of beacons from unrelated access points on that channel, so the radio was
tuned where it was asked and the absences are real. The console beacons only on the channel it hosts,
and sends its LDN advertisement — the same network, the same SSID — on the two channels it does not.
It sends no probe request anywhere.

So the console is announcing itself across the band rather than searching. A distributor finds it
without scanning and joins it, which fixes the direction of the link: on this screen the console
hosts and the distributor is the joiner.

## Unresolved

Which gate refuses is not settled. All three return the same zero to `CheckApprovalJoin` and the
reason byte is 1 in every case, so no join distinguishes them.

The participant maximum is the gate the static reading points at, and the direction measurement
argues against it: a maximum of zero would refuse the real distributor too. Either the field is
non-zero from construction, or the gift session is built by the path whose allow-list flag state has
not been read — `0x006ca848` clears that flag ahead of one of the two `LdnCreateSessionSetting`
sites, and which of the two the gift screen uses is unknown.

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
