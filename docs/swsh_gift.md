---
title: The Mystery Gift menu
parent: Sword and Shield
nav_order: 4
---

# The local-wireless branch of the Mystery Gift menu

Sword and Shield's Mystery Gift menu has a local-wireless branch. The menu and gift-format sections
are read out of Shield 1.3.2's `main` and its RomFS; the sections on what the console does on the
air are measured against a retail console on that screen.

## The menu

The receive-method chooser is `StateSelectReceiveDataBase` and it has five siblings, one per menu
button (`L_mystery_top_btn_00` .. `_04`):

| state | method |
|---|---|
| `StateSelectReceiveDataInternet` | over the network |
| `StateSelectReceiveDataSerial` | a serial code or password |
| `StateSelectReceiveDataLocal` | local wireless |
| `StateSelectReceiveDataFromBall` | the Poke Ball Plus |
| `StateSelectReceiveDataRankMatch` | ranked-battle rewards |

and the receive states are `StateReceiveBase`, `StateReceiveInternet`, `StateReceiveSerial`,
`StateReceiveLocal` (`0x01004938`), `StateReceiveFromBall`, `StateReceiveRankMatch`, plus
`StateReceiveNews` and `StateReceiveComplete`.

The game also counts what it received by channel: the play-record keys are `fushigi_net`,
`fushigi_serial` and `fushigi_p2p`, beside `yy_battle_single_p2p` / `_net` in the same table.

`/bin/message/French/common/mystery.dat` in the base game's RomFS, decoded with
`scratchpad/gfl_text.py`, gives the receive menu:

| line | text |
|---|---|
| 63 | `Via Internet` |
| 64 | `Via un code ou mot de passe` |
| 69 | `Via communication sans fil locale` |
| 65 | `Voir vos Cadeaux Mystère` |

with the top menu above it at 72-75 (`Recevoir un Cadeau Mystère`, the Wild Area news, the Poké Ball
Plus, the Battle Stadium rewards).

## The console advertises on that screen

On the Mystery Gift local-wireless screen the console advertises an LDN network: local
communication id `0x0100ABF008968000`, version 4, scene id 65535, accept policy ALL, one of two
participants, 384 bytes of application data. The Link Trade screen advertises the same comm id under
scene id 60001; the scene id separates the two features on the air.

The screen's text is a receiver's: line 42 `Communication sans fil locale activée.`, parallel to
line 39's `Connexion à Internet activée.`; line 9 `Recherche de cadeau en cours...`; line 11
`Aucun cadeau n'a été trouvé.` The console holds the network open and looks for a gift over it; the
distributor joins.

Two bytes of the game's application data separate the two sessions. Across five trade
advertisements and four gift ones from the same console and player, everything else in the 384
bytes is either identical or random per session:

    app data offset   gift   trade
    0x97              0xFF   0x0D
    0xB9              0x00   0xAA

Both sit in the game's own data, which starts at 0x18 of the advertisement. What they carry is
unread. The password CRC is zero on both; neither session is password-gated.

## The session accepts and the mesh refuses

The transport line that reaches the game on the trade scene runs on the gift scene as far as the
station handshake. The console answers the connection request on 0x14, sends its type 2 station
record of 840 bytes and accepts the station, then answers the mesh join request on 0x18 with a
refusal:

    02 00 ff ff 01        JOIN_RESPONSE, refused, reason 1

Two of two associations refused identically, one in the join phase and one in the hold phase that
followed it. Nothing on 0x58, 0x7C or 0x80 follows a refusal; no application data has been exchanged
on this scene.

The same command line against scene 60001, the Link Trade, is accepted five times out of five with a
148-byte join response.

Reason 1 comes from the game's approval callback. The addresses in this section are Sword's `main`,
the image the mesh addresses elsewhere in these pages are read from; the menu and gift-format
addresses above are Shield's. `ProcessJoinRequestJob` runs `InitialStep`,
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
"no objection" and 0, 2, 4 or 5 otherwise. Reason 1 is reachable only through the application
callback.

The callback installed at `MeshProtocol+0x60` is Pia's own trampoline `0x0157fcfc`, put there by
`0x0171a0b4` from the pointer slot `0x04c513f8`. It reads the field at offset `0xb0` of the object
the global `0x04c4b848` points to, tail-calls it, and returns 1 (approve) when that field is null:

    0x0157fcfc  adrp x8, #0x4c4b000 ; ldr x8, [x8, #0x848] ; ldr x8, [x8]
    0x0157fd08  ldr  x1, [x8, #0xb0]
    0x0157fd0c  cbz  x1, #0x157fd14      ; null -> mov w0, #1 ; ret
    0x0157fd10  br   x1

A refusal means that field holds a function on the gift scene.

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

Both are reached from the mode switch `0x006a9af0`, whose byte argument selects between them: the
game turns its join filter on and off per activity.

The installed callback is `0x006b41c0`. It takes the joining station's identity (16 bytes, staged to
two stack slots from the request) and refuses unless the identity clears both of these:

| gate | fields | refuses when |
|---|---|---|
| a block list | enabled by `[manager+0x21c]`, list at `[manager+0x1c0]`, walked by `0x006be4a0` in 16-byte entries | the identity is in the list |
| a participant allow list | enabled by the flag `[session+0x4f5]`, list at `[session+0x4c0]` with the count at `[session+0x4c8]`, walked by `0x006b8230` | the flag is set and the identity is not in the list |

`manager` is the object at `[0x02610000 + 0x4b0]` and `session` is `[manager+0x58]`. `0x006b8230`
also refuses when the station count `[session+0x1a8]` has reached the maximum `[session+0x1f0]`, and
approves outright when the allow-list flag is clear. A match in either walk, or a clear flag,
returns 1 and Pia sends the join response.

The flag at `[session+0x4f5]` is set by `0x006b86c4` and `0x006cc7bc`; entries are appended through
`0x006b5c80` -> `0x006b9920` and the list is emptied by `0x006b5c70` -> `0x006b9910`.

A third gate follows. The callback reads the halfword at offset 0x10 of the identity and approves
outright when it is zero (`0x006b4248`, `cbz w8`); otherwise it looks for it in a list at
`[manager+0x2b0]` with the count at `[manager+0x2b8]`, and compares it against the halfword
`[manager+0x220]`.

### What the identity is

The object the callback receives is built by `0x0177b7b0` and filled by `0x017b1bd0`, which finds the
mesh station-location table entry for the joining station (the one whose `+0x448` is that station
and whose `+0x440` is 3) and copies 32 bytes from that entry's `+0x10` to the identity's offset
zero:

    0x017b1c50  add x1, x23, #0x10 ; mov w2, #0x20 ; mov x0, x20 ; bl 0x18fde50

Those 32 bytes are the station location as the joiner sent it; every field the callback filters on
is a field the connection request carries. The three qwords the callback reads are the entry's
`+0x10`, `+0x18` and `+0x20`.

Version 4's location deserializer stores the identifying fields past that window: `0x0185eff8`
onward writes the relay port to `this+0x60`, the constant id to `+0x68`, the variable id to `+0x70`,
the service variable id to `+0x74` and the nat quad to `+0x78`..`+0x7b`, the same layout as the
5.11-5.45 reading. The copied 32 bytes are the location's address region; the lists the callback
walks are keyed on the joiner's address. The same constant id `0x1249a221d8580000` is refused on the
gift scene and accepted on the trade scene; the variable id is fresh per run and both readings were
refused alike. Which field the halfword at identity `+0x10` is has not been read.

### The three gates

The halfword gate approves. `nn::pia::common::InetAddress` is laid out by its deserializer
(`0x01767a10`) as a 16-byte address field at `+0x08`, zero-filled before use and carrying a 4-byte
big-endian IPv4 at `+0x08` unless the size byte is 0x12, and the port at `+0x18`. The location keeps
its public address at `+0x00` and its private one at `+0x28`, so the identity's 32 bytes lie inside
the public address, and the halfword the callback reads at identity `+0x10` is address-field byte 8:
zero for every IPv4 station. `cbz` on it is taken.

The allow list is not consulted. The flag at `session+0x4f5` is cleared (`strb wzr`) at
`0x006ca848`, immediately before the same function builds its `LdnCreateSessionSetting` at
`0x006ca86c`, and `0x006b8230` approves outright when that flag is clear.

The participant maximum: `0x006b8230` refuses when the Pia station count `[pia_session+0x1a8]` is
not below `[session+0x1f0]`. The only route that writes `+0x1f0` is the accessor `0x006b9900`,
reached through one wrapper `0x0110e5e0` with exactly two call sites, `0x00bd9b30` and
`0x01031c74` (both `SetMax(GetCount())`), in the raid den and rental-multi matching paths. A store
scan for that offset over the whole game band finds no other writer on either LDN session-creation
path. On the Mystery Gift scene the maximum is left at whatever the session was constructed with;
the comparison is unsigned, so a maximum of zero refuses every join at any station count. Whether
the field is zero at runtime is not read; the distributor joins, so some join is acceptable.

## The console announces on every channel and never scans

Monitor captures taken while the console sits on the Mystery Gift local-wireless screen, one per
2.4 GHz channel, with the console hosting on channel 6:

| channel | beacons from it | LDN advertisement action frames | probe requests |
|---|---|---|---|
| 1 | 0 | 153 in 90 s | 0 |
| 6, the one it hosts on | 339 in 70 s | 435 in 70 s | 0 |
| 11 | 0 | 95 in 90 s | 0 |

Each capture holds hundreds of beacons from unrelated access points on that channel. The console
beacons only on the channel it hosts, and sends its LDN advertisement (the same network, the same
SSID) on the two channels it does not. It sends no probe request on any channel. On this screen the
console hosts and the distributor is the joiner.

Sending no probe request is not the same as not scanning. Shield 1.3.2 read live in an emulator
calls `nn::ldn::Scan` about forty times a minute on this screen, and passes an advertisement of its
own with `SetAdvertiseData` at the same cadence, on top of a single access point it created once at
boot. The network is the game's always-on local-play network (`LocalCommunicationId`
`0x0100ABF008968000`, shared by both titles; `NodeCountMax` 2, accept-all), not one the gift screen
creates: entering or leaving Mystery Gift adds no LDN call and never tears the network down. The
gift screen only sets its advertise data and installs the Pia join filter. The console never calls
`Connect` while no peer network is present, so whether it would join a distributor it found in a
scan is open. The scan is passive at the 802.11 layer, which is why the air capture above records no
probe request.

## The mesh join is the only way in

Held on the gift scene with no join request sent, the console runs the whole station handshake on
0x14 (its connection request, a result-0 response, its type-5 ack, its 840-byte type-2 acceptance)
and then sends nothing: no message on 0x18, no RTT, nothing on the reliable window, nothing on 0x80,
no application data. It broadcasts its update session throughout, listing the joiner as seat 1 with
`allow_participating` set. No layer below the mesh carries the gift.

## The join is approved when the maximum is not zero

The callback `0x006b41c0` runs four gates in order. Against the values read live on the Mystery Gift
search screen, exactly one refuses:

| order | site | what it tests | live value | verdict |
|---|---|---|---|---|
| 1 | `0x006b4204` | the block list is enabled (`manager+0x21C`) and non-empty (`+0x1C0`) | enabled, empty | passes |
| 2 | `0x006b8260` | `pia_obj+0x1A8` against `game_session+0x1F0`, unsigned `b.lo` | count 1, max 0 | refuses |
| 3 | `0x006b827c` | the recruiting predicate `session+0xB0`, `ldrb w0, [x0, #0x4F5]` | flag 0 | returns 0, which skips the allow-list walk and approves |
| 4 | `0x006b4248` | the halfword at identity `+0x10` | 0 for any IPv4 station | approves |

`count < 0` cannot hold, so gate 2 returns 0, `CheckApprovalJoin` stores 1, and that byte is the
refusal reason on the wire. The allow-list walk at `0x006b8290` is reached only when the recruiting
predicate returns non-zero, so an empty allow list refuses nobody while the flag is 0.

Writing 8 into `game_session+0x1F0` on the search screen makes the scene accept a mesh join on the
first attempt, with a 148-byte join response and the station count moving 1 to 2; reverting the field
to 0 brings reason 1 back. The maximum is the whole gate.

Once seated, the scene's transport traffic matches the trade scene's: RTT probes, reliable-window
opens on two ports, and mesh updates.

## The participant maximum is zero on this screen

Read live from Shield 1.3.2 held on the Mystery Gift search screen, the participant maximum
`session+0x1F0` is 0, the allow-list flag `session+0x4F5` is 0, its count is 0, and the block list
is enabled over an empty list. The join filter is armed (`MeshProtocol+0xB0` holds `0x006b41c0`).
The recruiting predicate the filter calls, the game session's vtable slot at `+0xB0`, is
`0x006ccb00`, which is `ldrb w0, [x0, #0x4f5]; ret`: it returns the allow-list flag, 0, which
approves.

In the static reading `0x006b8230` compares the Pia station count against `session+0x1F0` with an
unsigned `b.lo`, so a count fails `count < 0` and the recruiting predicate and allow list are never
reached. That predicted a maximum of 2 would let the join through, and it is wrong. A mesh join
driven end to end at the emulator, with `session+0x1F0` and `+0x1F4` patched to 2 and verified live,
is refused with a response byte-identical to the unpatched one. `session+0x1F0` is the game's session
configuration, not what governs Pia's mesh seat allocation. The `0xFA0` reading was also the wrong
construction path (`0xFA0` is the setting `0x006c3bd4` builds, not the gift session's), but the field
itself is a dead end for the join.

The live refusal is not the application callback. A join over the bridge draws `JOIN_RESPONSE`
`02 00 ff ff 00`: the short five-byte "no station index" form, reason 0, where a seated two-station
response is 148 bytes. Reason 0 is the transport check, not the application callback that returns
reason 1 on retail hardware. So the emulated console refuses the seat one layer below the callback,
at the mesh station table, before the maximum this section measured is ever consulted. A link-trade
host on the same emulator, which accepts joiners with a maximum of 2 and no patch, answers the same
join request with the same five bytes, so the refusal is not a property of the gift scene. The keys
and framing are proven, every packet authenticating across four sessions with four derived keys.

## The transport check counts stations against a maximum

The check the reason byte comes from is `0x017bb2e0`, called by `CheckApprovalJoin` before the
application callback. It returns `0xFF` for no objection and otherwise the reason byte, unchanged, on
the wire. Its first two tests both answer 0:

    0x017bb358  bl   0x017bab70        the live station count
    0x017bb35c  ldrh w9, [x19, #0xa8]  the maximum
    0x017bb368  b.hs 0x017bb380        count >= max, reason 0
    0x017bb370  bl   0x017bb5a0        the index of the first free station slot
    0x017bb378  cmp  w8, #0xfd         no free slot, reason 0

The object is `read_u64(read_u64(main + 0x0262F7B0))`, a third object beside `pia_obj`
(`main + 0x02616A30`) and `game_session`, which is why patching `game_session+0x1F0` changed nothing.

| field | width | what it holds |
|---|---|---|
| `+0xA8` | u16 | the maximum station count |
| `+0xAA` | u8 | an enable byte; zero returns 2 before any other test |
| `+0xAB` | u8 | selects which bitmask word the count reads |
| `+0xAC` | u8 | how many bits of the bitmask the count walks |
| `+0xC4` | u32 | the occupancy bitmask, read when `[0xAC] == [0xAB]` |
| `+0xC8` | u32 | the occupancy bitmask otherwise, and the only one the free-slot search reads |

A set bit is an occupied station. The count starts at 1 and adds one per set bit (`0x017bad94`), so a
mesh holding only the host counts 1 and a mesh holding the host and one other station counts 2. The
free-slot search returns the index of the first clear bit, or `0xFD` when every bit is set.

Read live on the emulator's link-trade screen, with no association and with one held and across 49
attempts, these fields do not move: max 8, enable 1, sel 0, bits 0, `+0xC4` zero, `+0xC8` `0x00000001`.
The count is 1 and the free-slot search returns slot 1, so both of the first two tests pass and the
ldn_mitm association seats nobody. The maximum here is 8, where `nodeCountMax` and
`game_session+0x1F0` both read 2.

Three more exits of the same function also answer 0, and which one fires is unmeasured:

| site | the test |
|---|---|
| `0x017bb380` | `count >= max`, or the free-slot search returns `0xFD`. Measured passing. |
| `0x017bb498` | the table at `mesh_obj+0x370`: its size against a u16 at `read_u64(main + 0x02616710) + 0x70`, then against its own capacity at `table+0x48`. A joiner already in the table skips both (`0x017bb41c`). |
| `0x017bb4d4` | the byte at `mesh_obj+0x132`, set by the handler at `mesh_obj+0x120` when the check hands it a type-0x18 event, and cleared as it is read. |

The same function returns 2 when `+0xAA` is zero or a preliminary predicate holds, and 4 when
`mesh_obj+0x131` is set by the type-0x19 event.

The maximum scales with the local-play mode, read live in three sessions of the same running game:
0 on the Mystery Gift search screen, 2 when hosting a link trade, 4 when hosting a Max Raid. The
join filter callback is the same armed pointer in all three, and the raid host admits four joiners
through it, so the callback is not the discriminator. The raid host also propagates its 4 into the
LDN advertisement's `NodeCountMax`, while the gift screen advertises `NodeCountMax` 2 at the LDN
layer with a Pia maximum of 0: the two counts are decoupled there, so the console tells the network
it has slots and then refuses internally.

One `game_session` byte tracks accept-versus-refuse alongside the maximum: `+0x3F8` is 1 on the gift
screen and 0 on both accepting sessions. Other bytes that looked like accept markers, `+0x365`,
`+0x33D` and advertisement `+0xF9`, are mode residue: after a raid they stay at their raid values
when the game returns to the gift screen, and the console advertises `+0xF9` set to 1 while refusing
every join, so `+0xF9` does not mark an accepting session. The `manager` object is byte-identical
between the gift screen and the trade host, so none of its state gates accepting. These bytes track
the game's session mode; they are not proven to gate Pia's mesh seat, which the join test above
refused one layer lower regardless of `session+0x1F0`.

A synthesised distributor does not move the console. A network carrying the Sword/Shield
communication id and a genuine accepting session's advertisement, served into the console's scan
while it sits on the gift screen, is received, parsed and filed in the Pia scan slot (`pia_obj+0x3C0`,
empty until then) and then ignored: no `Connect`, no `OpenStation`, no accept-policy call, no change
to the maximum or `+0x3F8`, against a no-beacon control. The console neither admits a joiner nor joins
a distributor here. This is measured only against advertisements synthesised from the console's own
sessions; a genuine distribution beacon was never in hand, so it bounds what a self-derived beacon
can do, not what any beacon could.

## A gift is a multiple of 0x2D0 bytes

At `0x00ff22d8` the Mystery Gift code divides a received length by 0x2D0 as a reciprocal multiply,
takes the remainder with `msub`, and branches to the error path if it is non-zero:

    0x00ff22e4  umulh x8, x21, x8        ; x21 = the length
    0x00ff22e8  lsr   x28, x8, #7        ; x28 = length / 0x2d0, the record COUNT
    0x00ff22ec  mov   w8, #0x2d0
    0x00ff22f0  msub  x8, x28, x8, x21   ; the remainder
    0x00ff22f4  cbnz  x8, #0xff272c      ; not a whole number of records -> refuse

A gift payload is *n* records of 0x2D0 bytes. The same app allocates a 0x2D0 object at
`0x00feba7c`. PKHeX gives a Gen 8 Wonder Card the same size.

## What `StateReceiveLocal` speaks

Unknown. There is no static call path from the Mystery Gift app to the LDN session setup, checked
over the whole app to depth 10 with a function-level call graph (`scratchpad/swsh_reach.py`). The
game reaches its network layer through vtables and delegates, and the same search finds no path from
the Union Room's code either.

A walker that bounds each function by "the first 0x1000 bytes after its entry" walks through the
`ret` into the next function's body and reports false edges; both hops such a walk produced here
were refcounted-pointer setters that call nothing.
