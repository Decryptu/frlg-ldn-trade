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

Its Pia is not silent. The moment a node joins at the LDN layer the console broadcasts a Local
Protocol update session about six times a second, listing the joiner as seat 1; 238 of them decoded
and authenticated in one run, against a control with no node joined that sends nothing on that port
for five minutes. An earlier reading of silence here was a socket losing the race for broadcast
delivery against the emulator's own wildcard socket on 12345, and only an external capture sees them.
The update session is acknowledged, and has been on every run. With the ack on, one arrives and the
rebroadcast stops after 1.6 seconds; with `--no-ack-update` against the same screen and the same
patch, 612 arrive and are still coming at six a second after 100 seconds. A run reporting one update
session is the acknowledgement working, not a run that missed them. The six a second seen in a
capture is the console calling an LDN node that has not taken the Pia seat.

Nothing else is on the wire. A capture of every port in both directions, a listener bound across
48,123 UDP ports for ten minutes, and the emulator's own socket table agree: the only flows between
the two nodes are Pia on 12345 and ldn_mitm's control channel on 11452. The transfer is not raw
traffic between LDN nodes.

Once seated, the scene's transport traffic matches the trade scene's: RTT probes, reliable-window
opens on two ports, and mesh updates. Above the transport it says nothing: no application payload in
180 seconds of holding the mesh, and none in a further 180 seconds while being sent the trade scene's
ping. Nothing ever opens on 0x84. The scene does accept application data, acking 96 pings on 0x7C in
sequence. It is a receiver that waits to be pushed at.

## On this screen the console is looking, not waiting

Four measurements put the console on the joining side of a distribution, not the hosting side:

- it calls `Scan` continuously on the gift screen, 33 times in one 40-second IPC trace, interleaved
  with `SetAdvertiseData` and `GetNetworkInfo` and never with `Connect` or `CreateNetwork`;
- the network it advertises there is the always-on local-play one it creates about 16 seconds after
  boot, carrying scene id 65535 where a link trade carries 60001;
- its participant maximum is 0, so it offers no seat to anybody;
- forced into its mesh with that maximum patched, it registers no message listener and sends no
  application data.

Zero probe requests over the air, which this page previously read as "it hosts and does not scan",
is what a passive scan looks like and does not decide the question.

Its scan filter asks only for the local communication id and network type, both `SessionId` and
`SceneId` unfiltered, so a network carrying `0x0100ABF008968000` is returned to the game whatever
else it holds. Six advertisement variants built from the console's own sessions were each returned by
the scan and none drew a `Connect`, so what the game requires is above the filter, in the
advertisement's own contents.

## The gift screen runs the mode that creates no session

One field is the mode, `session_config+0x70`, and it drives both the scene id and the advertisement.
`0x01096730` turns it into a scene id and a participant count through a jump table at `0x02066C14`,
and `0x010961a8` turns the same mode into the advertisement byte through a table at `0x02066C40`:

| mode | scene id | participants | advertisement `0x97` |
|---|---|---|---|
| 0 | none, the creator returns false at `0x01096764` | | 0xFF |
| 1 | 60021 | 2 | 0x01 |
| 2 | 60001 | 2 | 0x0D |
| 3 | 60002 | 2 | 0x0E |
| 4 | 60003 | 2 | 0x0F |
| 5 | 60004 | 4 | 0x10 |
| 6 | 60005 | 2 | 0x1E |

The last column is measured independently: the advertisement carries 0x0D on the link trade and 0xFF
on the Mystery Gift search screen, which are the table's entries for modes 2 and 0. The byte sits at
`0xAF` of the advertisement and `0x97` of the game's own data, which starts at `0x18` of it. A Max
Raid host advertises `0x11` there, which is not one of the table's values; where that comes from is
unread. Diffing every advertisement captured from this console, it is the only byte of the 384 that
differs stably between screens. Mode 2 is
therefore the link trade, its scene id 60001 matching the advertised one, and **the Mystery Gift
search screen runs mode 0, which creates no session at all**. That is why its scene id is 65535,
why its participant maximum is 0, and why a station seated in its mesh by force finds no listener.

The Mystery Gift app does not merely fail to create a session, it suppresses one. Entering it reads
the current mode with `0x01096d20`, saves it at `app+0xFE8`, and sets mode 0 (`0x01022f08`); leaving
writes the saved value back (`0x01023198`). Mode 0 holds for the app's whole lifetime, and the
advertisement byte was watched for 717 seconds across idle, leaving and re-entering the search, and
never left `0xFF`. Leaving and re-entering touches LDN not at all: the network stays the one built 31
seconds after the game loaded.

The scene ids are Pia's own and never reach the air. The LDN `SceneId` field reads 0 on every network
this console advertises, the link trade included, and no value of the 60001 family appears anywhere
in the advertisement.

A beacon offered to that screen carrying any of 60001 through 60021 draws nothing: those scene ids
belong to the game's other session modes, and none of them is a distribution. Six of them were swept
one per run against a live gift screen, with the console answering about fifty of our scans per run
and parking our network's communication id at `pia_obj+0x3C0` each time, and none produced a
`Connect`, an `OpenStation`, or any movement in the maximum or the registration table.

The setter that would raise the maximum on a running session, `0x006b9900`
(`str w1, [x0, #0x1f0]`), is reached only through the thunk `0x006b5c00`, which nothing calls and
which no relocated data slot holds. The count comes from session creation, not from a setter.

## The app's state machine

The Mystery Gift app is one state machine of seventeen states. Its dispatcher (`0x00FE6F80`) reads a
request object held at `app+0x718`: a ready flag at `+0x60`, the next state's id at `+0x64`. When the
flag is set and the id is at most 16 it jumps through the table at `0x020641A4` and builds that
state. `0x00FF0DE0` is the setter, `SetNextState(id)`, which writes the id and raises the flag; 63
sites call it.

| id | state | id | state |
|---|---|---|---|
| 0 | TopMenu | 9 | SelectReceiveDataSerial |
| 1 | ReceiveMenu | 10 | SelectReceiveDataRankMatch |
| 2 | **ReceiveLocal** | 11 | SelectReceiveDataFromBall |
| 3 | ReceiveInternet | 12 | ConfirmGift |
| 4 | ReceiveSerial | 13 | ReceiveNews |
| 5 | ReceiveRankMatch | 14 | ReceiveComplete |
| 6 | ReceiveFromBall | 15 | ConnectPalma |
| 7 | **SelectReceiveDataLocal** | 16 | (default, TopMenu) |
| 8 | SelectReceiveDataInternet | | |

The local-wireless path is 2 then 7: the search, then the screen that picks from what a distributor
offers. What advances 2 to 7 is unread; `StateReceiveLocal` sets no next state itself, and the sites
that do are in the shared base.

The state can be forced. `0x00FE700C` is `mov w8, w21`, the register the dispatcher indexes its jump
table with, and writing `mov w8, #N` there makes the next transition build state N whatever the app
asked for. Done for state 7 on a running console, it draws that screen's furniture with no list and
an empty bar, and **touches the network in no way at all**: the participant maximum stays 0 with
nothing patched, the registration table stays empty, the advertisement byte does not move, and the
LDN trace shows no `Connect`, no `OpenStation` and no session creation. Seated inside that state with
the maximum patched and held for 100 seconds, it behaves exactly as the search screen does. The state
expects its list to be in hand when it is entered, so whatever fills it runs earlier.

There is no static path to the app object: the class's primary vtable is at `0x025737C8`, its group
base `0x025737B8` is held only in `main+0x2624698`, and the constructor that loads it
(`0x00FE5D60`) has no caller, the applet framework building the app through a vtable. Nothing in
`main` holds a pointer to the app, so its fields are reachable only by scanning the heap for the
vtable value.

The image carries no Mystery Gift protocol-buffer module. Every `.pb.cc` path in it belongs to
`gflnet3`'s own p2p framework or to one of the game's features: trade, the three battle modules, the
raid dens, the underground, the camp, `comp_organize` and `btl_spot`. The card is therefore not
carried the way a traded Pokemon is. The Mystery Gift app is a state machine of ten states, named by
the strings its constructors take, of which `StateReceiveLocal` (`0x01004938`) is local wireless; its
own code references only its progress-bar layout, so the transfer is delegated.

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

## The card arrives as gflnet3 application data

The card transfer is a gflnet3 message flow, the same library that carries trade and battle. There
is no bespoke Mystery Gift network module because the app reuses gflnet3, reached through the global
gfl net manager at `0x0261CBA8` (`read_u64` of it is the manager; a null there is the no-session
guard on every send stub). This resolves the earlier "no Mystery Gift protobuf module": the module
is gflnet3.

`StateReceiveLocal`'s driver `0x01004C80` (a case machine on `state+0x2A0`) does two things when it
enters the local-wireless case:

- it builds a receive job through `0x010B7100` (job ctor `0x010B73E0`, vtable group `0x0257DD88`,
  poll `0x010B74D0`) and links it into the gfl net manager's job list at `manager+0x68`;
- it installs a receive delegate at `state+0xB0` (`0x0100504C` group) and a per-record sink whose
  entry is `0x01005BC0`.

The job's poll `0x010B74D0` reads each inbound gflnet3 packet's four-field header, `{u32 id @0,
u16 @4, u8 @6, u16 @8}` (accessors `0x010F7A40..0x010F7A80`), and matches it against the handlers
registered on the job at `job+0x160` (`0x010F7550`, all four fields must be equal). A match invokes
the sink at `receiver+0x60`, which reaches `0x01005BC0`.

`0x01005BC0` tail-calls `0x00FF0E00 -> 0x00FF1FB0 -> 0x00FF2170`, the card importer. `0x00FF2170`
requires the body be a whole multiple of `0x2D0` (720, the Wonder Card size; the reciprocal-multiply
gate above), then loops over the *n* records: it filters each through `0x01449820` and materialises it
with `0x00FF3EC0`. Where the materialised card is kept is unresolved; `manager+0x80`, named here in an
earlier revision, is the per-frame update's clock stamp.

The send half hands the message to the gflnet3 core (`0x006C2840`, queue at `core+0xF8`); the core
manager is `read_u64(read_u64(main+0x02616B80))`. A distributor is a joiner: it seats on the console's
hosted gift network, then sends the card as a gflnet3 core message the receive job's drain picks up.

Confirmed live. The receive job is the object at `manager+0x68` (vtable group `0x0257DD88`): it
appears when the local-wireless search screen opens and is freed on leaving it, and nothing in it
moved through a seated 200-second hold with no message sent. The manager is one
dereference past the app global: `read_u64(main+0x0261CBA8)` is a static object whose first qword is
the heap manager (vtable `0x025819A0`); the job hangs off that manager's `+0x68`.

The job carries no pre-registered handler list: `job+0x160`/`job+0x168` (the poll's compare range) are
zero, seated or not. The poll `0x010B74D0` builds a handler entry from each message it receives, adds
it to that list, and dispatches, so the list is empty only because nothing has arrived. The job holds
two `std::function` slots instead: the data sink at `job+0x60`, whose target is `0x01005BC0` (the
importer path), and a progress callback at `job+0xE0` (`0x01005C70`).

Each `0x2D0` record the importer walks (`0x00FF2354`) carries a region mask at record `+0x0E` (u16,
tested against a region bit the game derives at entry; `0xFFFF` intersects any) and a flag at record
`+0x13`. When `+0x13` is zero the importer imports the record unconditionally; when it is non-zero it
first calls `0x01449820`, which walks the player's held-card table (0x1662-byte stride) and skips a
duplicate. Where an accepted record is kept is unresolved.

Confirmed from the consuming end. Forcing `StateConfirmGift` (12) crashes on entry reading `+0x1AC`
of a null card object (`0x015C9230 ldrb w8,[x0,#0x1AC]`, x0 = 0, from the confirm controller
`0x015BFFA0` reached via app `0x00FFA458`), and `StateReceiveComplete` (14) draws an empty panel:
nothing is resident until a transfer runs `0x00FF2170`.

The gift manager is a separate gflnet3 consumer, not the trade sync framework. The trade pump's
registration array (`0x006db3b0`, manager `read_u64(read_u64(main+0x02616750))`) is empty on the gift
screen, and the gift manager (`read_u64(read_u64(main+0x0261CBA8))`, vtable `0x025819A0`) has no entry
array at `+0xD0`/`+0xD8`. The receive job's message source is the session object at `job+0x08` (vtable
`0x0250DAE0`); the job's poll `0x010B74D0` reads a message the manager feeds it, so the Pia
protocol/port binding lives in the manager's drain, not in the job.

A `0x2D0` record sent on every Pia reliable channel a joiner can address, `0x7C` ports 0 and 1 and
`0x80` ports 0 and 1, each with the driver's 4-byte `u16 id, u8 disc, u8 zero` header plus the record,
is acknowledged by the console's reliable layer and reaches the job on none of them:
`job+0x160`/`job+0x168` stay `0`, the job bytes are unchanged, no fault. The
console sends no reliable data of its own on this screen, so there is no channel to mirror.

The gift transfer rides the gflnet3 core, not the reliable windows the driver sends on. The core
manager is `read_u64(read_u64(main+0x02616B80))`, separate from the trade sync pump
(`main+0x02616750`); the trade completes because it uses the sync pump, which drains `0x7C`/`0x80`
directly with a 4-byte header, while the gift is a core consumer. The core send `0x006C2840` queues to
`core+0xF8` and its Pia protocol and port are runtime fields rather than constants, and the core
message header is 10 bytes (`0x010F7C08`: u32 id at 0, u16 at 4, u8 at 6, u8 at 7, u16 at 8), not the
4-byte header. So no send on a reliable window with the 4-byte header reaches the gift job.

The core transport is not a Pia mesh at all. The core manager `read_u64(read_u64(main+0x02616B80))`
names itself `BeaconCommunication` (the string is at `0x02068858`, and again in its connection object
at `conn+0x278` and `conn+0x308`), and it drives `nn::ldn::Scan`, `nn::ldn::GetNetworkInfo`,
`nn::ldn::SetAdvertiseData` and `nn::ldn::OpenAccessPoint` (the import wrappers at `0x017978F0`,
`0x01794C3C`/`0x01799BE0`, `0x017961B0`, `0x01794CF0`). The connection object at `core+0x50` exists
before any peer, its send gate `+0x2FA` never arms, and a Pia mesh join changes nothing in the core
except the LDN node count it mirrors. The transfer rides the LDN beacon advertise data: the
distributor advertises a network whose 0x180-byte advertise data carries the card, framed by the
core's header, and the receiver's core reassembles it from `Scan` results. This is consistent with the
console scanning and setting advertise data every ~1.5 s forever on this screen, and with a
synthesised beacon reaching the beacon store while no `Connect` or `OpenStation` call is made.

The whole Pia-mesh seating result, deterministic seating and the `game_session+0x1F0` gate, is the
trade transport and the wrong layer for a Mystery Gift card. A distributor does not join; it
advertises. This also removes the need for the emulator's `+0x1F0` patch on the gift path, so a
beacon-borne card is a candidate against a retail console, not only the emulator.

## The beacon body frame

The 0x180 bytes of LDN advertise data are a 0x18-byte header and a 0x168-byte body. The body is
framed by the beacon core; everything above it is opaque application payload.

| offset in the body | size | field |
|---|---|---|
| `+0x00` | 2 | CRC-16/ARC over `body[2:0x168]`, init 0, no final xor |
| `+0x02` | 12 bits | network id, low 8 bits in `body[2]`, high 4 in the low nibble of `body[3]` |
| `+0x03` high nibble | 4 bits | zero on every capture |
| `+0x04` | 1 | zero on every capture |
| `+0x05` | up to 0x163 | application payload |

The network id is `0xD70` on every captured beacon, on the Mystery Gift, link trade and Max Raid
screens alike. The payload bound is the `cmp x2, #0x163` at `0x006c2174` guarding the `memcpy` whose
destination is `body+5` (`add x0, x8, #5`, `0x006c2148`), and `0x005 + 0x163` is the whole 0x168 body.

The checksum routine is `0x0065dcb0`, a table-driven CRC-16 whose 256-entry table is built lazily by
`0x0065def0` behind the pointer at `0x02615fd8`. The table is the standard reflected CRC-16/ARC table
for polynomial `0xA001`, and the update is `crc = T[(crc ^ byte) & 0xFF] ^ (crc >> 8)` from init 0.
Forty advertise-data captures taken off the wire reproduce their own stored checksum under this
definition, and each one rebuilds byte for byte from its decoded fields, so no byte of the frame is
unaccounted for.

The builder is `0x006c1fa0`: it zeroes the 0x168 body, writes the network id at `body+2` through the
bit-packed field writer `0x006c1830`, copies the payload to `body+5`, then computes the checksum over
`body+2` for `0x166` bytes and stores it at `body+0`. When the payload is missing or too long it
stores `0xFFFF` there instead (`0x006c21d4`).

## The gate a received beacon passes

`0x006c1be0` is the gate. It takes one entry object and returns 1 to accept it, and it runs on both
sides of the core. On the build path it checks a body the game has just made, before
`SetAdvertiseData` (`0x006b5ba8` builds then validates at `0x006b5bb0`; `0x006c3de4` and `0x006c42c4`
validate the advertise object at `conn+0x360` before the 0x168 copy at `0x017760e0`). On the ingestion
path it decides whether a received body is kept: `0x006bb9d4`, `0x006c4b38` and `0x006ca0dc` each copy
the received advertisement into a stack entry object through `0x006c2360`, call the gate, and offer
the entry to the store at `0x006c53b0` only when bit 0 of the result is set.

The gate applies four tests in order, and any one of them rejects:

1. the core object behind `0x02616b80` exists;
2. the halfword at `body+0` equals the checksum recomputed over `body[2:0x168]`;
3. the body's 12-bit network id differs from the halfword behind `0x02616b88`, the identifier the
   builder falls back to when the core is absent;
4. the body's network id agrees with the core's own, nibble by nibble (`0x006c1cf0`). The low nibble
   must be equal or the entry is refused. If the second nibble differs the entry is accepted; failing
   that, the third nibble must be equal.

A wrong checksum therefore stops a body from ever being stored. Two beacons built from one capture,
differing only in the two checksum bytes, were served to a console on the Mystery Gift local-wireless
search screen. The body with the stale checksum was answered on 114 scans across two runs and never
reached the store, whose count stayed 0 through 6,597 samples; the body with the correct checksum was
in the store 0.21 s after the beacon started, and stayed.

`0x006c53b0` takes an accepted entry, walks the entries already in the store comparing each with
`0x006c1da0` (the 0x168 body and the id struct), and appends through `0x006c5460` only when the entry
is new, so a repeated beacon does not grow the store.

Reaching the store is not the same as being scanned. The 0x480-byte `NetworkInfo` scan-result slots,
`pia_obj+0x3C0` among them, take a full 0x180 wire copy of either body, header included, whatever the
checksum says. A marker in those slots measures only that a beacon was received.

`0x006c5460` appends a received body to a store: array base at `+0x40`, count at `+0x48`, capacity at
`+0x50` (0x32 entries), and the mutex at `+0x60`. Each entry is 0x180 bytes, a vtable pointer at `+0`
with the body at `+8`; the vtable is the one that also sits at `conn+0x360`, 8 bytes before the
console's own body at `conn+0x368`, so a station's own advertisement lives in an entry object of the
same shape. Two stores are held together and the consumer swaps between them through `0x006c5300`.

`0x010f6600` walks a store's entries, taking the network id through `0x006c1d50`, then the payload
pointer through `0x006c1f80`, the accessor that returns `body+5` and the only caller of which is
`0x010f66c4`. The payload goes to `0x010f8cf0`, which stores the pointer in a message object, and from
there to the handler at `[gfl_job+0x68]` vtable `+0x38`.

The station-information structure read out of a receiver's beacon is this payload, so its offsets sit
5 bytes past the body and 0x1d bytes past the start of the advertise data.

## What the payload carries

The first byte of the payload is a message type. `0x010f6600` builds a typed view of the payload for
each of the two types it knows and dispatches whichever one matches:

| payload `+0` | view built by | goes to |
|---|---|---|
| 0 | `0x010f8730` | `0x0110f270`, with the object behind `0x02610958` |
| 1 | `0x010f8830` | the job at `[manager+0x68]`, through its vtable slot `+0x38` |

Each view holds a pointer to `payload+1`, so the message begins one byte past the type. A receiver's
own beacon carries type 0, which is why the station-information structure starts there.

On the Mystery Gift local-wireless screen the job at `manager+0x68` is the receive job, and its vtable
slot `+0x38` is its poll `0x010b74d0` (the object's vtable pointer is the group address plus 0x10, so
slot `+0x38` is `0x0257dd88+0x48`). A type-1 beacon payload is therefore delivered straight to the
poll that feeds the Wonder Card importer.

The poll reads a ten-byte header from `payload+1` through `0x010f7bf0`, which packs it as `{u32 at 0,
u16 at 4, u8 at 6, u8 at 7}` in one register and returns the `u16 at 8` in another:

| header offset | size | note |
|---|---|---|
| `+0` | 4 | the poll returns without doing anything when this is not zero |
| `+4` | 2 | |
| `+6` | 1 | |
| `+7` | 1 | |
| `+8` | 2 | |

With the first field zero the poll walks the handler list between `job+0x160` and `job+0x168`, whose
entries are 0x88 bytes, comparing each against the header with `0x010f7550`. When nothing matches it
appends a new entry through `0x010f7360` and the list grows.

## The message the poll reassembles

A type-1 payload reaches the poll only when the first header field is zero. Serving one beacon with
that field set to 1 and then one with it zero, to a console that had received no beacon of any kind,
left `job+0x160` null for the first and moved it from null to an allocated vector 1.77 s into the
second, with `manager+0x80` taking its first clock stamp in the same sample. The field is causal.

The poll treats the list between `job+0x160` and `job+0x168` as reassembly contexts of 0x88 bytes, one
per message in flight, not as a registry of handlers. `0x010f7550` matches an arriving fragment to a
context, `0x010f7430` accumulates it, and a second pass erases each context that has become complete
and hands the reassembled bytes on. So an empty list after a beacon is what a message that completed
in one pass leaves behind, and is not evidence that nothing was appended.

`0x010f7430` accepts a fragment only when every field of its header except the index equals the
context's, so those fields are the message key:

| header offset | size | meaning |
|---|---|---|
| `+0` | 4 | zero, or the poll returns at once |
| `+4` | 2 | total message length in bytes |
| `+6` | 1 | total fragment count |
| `+7` | 1 | this fragment's index, refused unless below the count |
| `+8` | 2 | message key |

The context constructor `0x010f7360` writes those fields to `context+0`, `+8`, `+0x10` and `+0x18`
and sizes two things from them: the buffer at `context+0x20` from the length at `+4` (through
`0x010f6fa0`) and the arrival bitmap behind the pointer at `context+0x58` from the count at `+6`. A
message therefore holds at most 65535 bytes and 256 fragments.

`0x010f7100` copies a fragment to `index * 300` in that buffer, 300 bytes for every fragment except
the last, which takes only the remainder, and drops a fragment whose index is not below the buffer's
capacity in 300-byte units. So the reassembled buffer is exactly the length the header declared, and
a 720-byte Wonder Card is three fragments of 300, 300 and 120. A fragment whose bitmap bit is already
set is dropped, so a repeated beacon is harmless, and `0x010f7610` reports the message complete when
every bit below the count is set.

`0x010f7550` decides whether an arriving fragment belongs to a context by comparing exactly those four
header fields. The index is not among them, which is what lets the fragments of one message meet.

## The message checksum, and why a context never looked complete

The halfword at header `+8` is a CRC-16/ARC over the reassembled message, not a key. `0x010f7680`
builds the message that goes to the sink: it walks the arrival bitmap, and when every bit below the
count is set it takes `context+0x18`, the stored `+8`, computes `0x010f71e0` over the buffer at
`context+0x20` and compares the two. `0x010f71e0` is the length of the buffer passed to `0x0065dcb0`,
the same checksum the beacon body carries. On a mismatch the function returns null.

A null return skips the sink, because the poll loads the built message and branches past the call when
it is zero (`0x010b77fc`), and the context is erased either way. All of that happens inside one poll,
so a message whose checksum is wrong leaves no trace: the completing fragment is accepted, the bitmap
briefly shows every bit, the message is discarded without reaching the importer, and the context
disappears.

That is what a run with the wrong checksum looks like from outside, and it was measured before the
cause was known. Fragments accumulate: watching the arrival bitmap, which is the low bits of the byte
behind the pointer at `context+0x58`, a context was seen going from `001` to `011`, from `100` to
`101` and from `010` to `110`. No context was ever sampled with every bit set, at a two-second offer
cycle or at a third of a second; a context stood one fragment short for 11.1 seconds while the missing
fragment was offered about 44 times, and was then discarded still one short. A breakpoint on the sink
`0x01005bc0` was never reached in 25 seconds while the same session's controls were reached in
0.027 s, and the importer's result at `bound+0x2C0`, `bound` being `job+0x80`, never moved off the
value its error path leaves. The number of fragments a context appeared to hold was always one below
the declared count, at counts of both two and three, which is the count-shaped signature of a context
that completes and is thrown away rather than one that refuses a fragment.

## What a record must carry

The region bit is one of two. The importer calls `0x007d4270` at entry and forms `1 << 1` when the
byte it returns is `0x2D` and `1 << 0` otherwise (`0x00ff2330`), so a record whose mask at `+0x0E` has
both low bits set, `0xFFFF` among them, intersects either console, and a record whose mask is zero is
skipped.

A record that passes the mask is filtered again when its byte at `+0x13` is non-zero: `0x01449820`
walks fifty four-byte entries in the save from `0x1660`, each a halfword card id and a byte, and
reports a match when the id equals the record's halfword at `+8` and the byte equals the record's
`+0x13`. So `+8` is the card id, `+0x13` selects both whether the duplicate check runs and which table
entry it matches, and a record with `+0x13` zero is imported every time.

An accepted record is copied into a `0x338`-byte structure whose leading `0x68` bytes the importer
zeroes, the record following at `+0x68` (`0x00ff2380`), and that structure and the record are handed
with the length `0x2D0` to `0x010b5de0`. The card object it builds is `0x3A8` bytes and keeps the
structure at its own `+0x70`.

`0x010b5de0` validates the record before anything is built from it. It copies the 0x2D0 bytes to its
own stack, takes the halfword at `+0x2CC` and zeroes it, then runs a CRC-16/CCITT-FALSE over the whole
record: the table is built MSB-first from polynomial `0x1021` (`0x010b5e60`), the running value starts
at `0xFFFF`, and each byte updates it as `T[(byte ^ (crc >> 8)) & 0xFF] ^ (crc << 8)` (`0x010b5f54`).
A record whose stored halfword differs returns `0x80000001`, which the importer recognises
(`0x00ff23d0`) and reports as 1. **So `+0x2CC` is the record's own checksum over itself with that
field zeroed.**

Past the checksum the routine fills the `0x68`-byte header from the record: the card id at `+0x08`
goes to header `+8`, the byte at `+0x15` to header `+0xa`, the byte at `+0x11` to header `+0xc`, and
the byte at `+0x1C` to header `+0xf`.

The byte at `+0x11` is the gift kind. One through five dispatch through the table at `0x02067620`;
anything else returns success with nothing built. Kinds 3 and 5 take the shortest path
(`0x010b5fd8`), which keeps the word at record `+0x20` in header `+0x30` and returns, building no
sub-object. Kind 1 goes to `0x010b58f0` and kinds 2 and 4 to routines of their own.

## The Pokemon a kind-1 record carries

`0x010b58f0` reads the gift out of the record. Two arrays of nine entries, one per language and
`0x1C` bytes each, come first: the nicknames at `0x030`, each `0x1A` bytes of UTF-16 with a language
byte at `+0x1A`, and the original trainer names at `0x12C`, each `0x1A` bytes of UTF-16. The language
is chosen through the table at `0x02067650`, which maps the game's language to an index from 0 to 8.
A delivered Pokemon carried the string from `0x030` as its displayed name and the string from `0x12C`
as its original trainer.

The Pokemon itself follows:

| record offset | size | field |
|---|---|---|
| `+0x22E` | 2 | kept in header `+0x10` |
| `+0x230` | 2 | first move |
| `+0x232` | 2 | second move |
| `+0x234` | 2 | third move |
| `+0x236` | 2 | fourth move |
| `+0x240` | 2 | species |
| `+0x242` | 1 | form |
| `+0x243` | 1 | kept in header `+0x64` |
| `+0x245` | 1 | kept in header `+0x12`, and not the level |
| `+0x25C` | 1 | kept in header `+0x63` |
| `+0x272` | 1 | language, used when it is 2 or more, otherwise the game's own |

Run against the game's own parser under emulation, a record built to this map reads back with its
species, four moves, nickname, card id and kind in the header the parser fills.

A record carrying species 25 was delivered to a console and the Pokemon it produced was species 25, so
the species field holds an ordinary Pokedex index.

The level is rolled at claim time. One record was claimed twice, from a byte-identical file, and
produced level 20 once and level 35 the other time. A record differing only at `+0x245` produced level
73, which looked like that byte mattering until the repeat showed both were draws, so `+0x245` has no
demonstrated effect on the level. The experience always matches the species' own growth group: a
cube-curve species arrived with 8000 at level 20, and a slower-curve species with 96 at level 4.

Every record sent so far carries zero wherever the level belongs, and every claim reports the Pokemon
as met at level 0, so the rolling is most likely the ordinary rule that a level of zero means choose
one. Which field holds it is unresolved: nothing outside the parser reads the record's species, and
the code that reads the parsed copy is the display path, so the routine that builds the Pokemon has
not been located. The trainer id is not in the record either.

Move legality is not checked. A record gave a species the four moves of an unrelated one, none of them
learnable by it, and the game accepted all four.

Run against the game's own validator under emulation, a record carrying the checksum is accepted and
reaches the kind-3 path with the word from `+0x20` in place, while the same record with the checksum
zeroed, and an all-zero record, both return `0x80000001`.

## A card delivered by beacon, end to end

A 720-byte record built here, split into three fragments and served from a synthesised beacon, reaches
the importer on an unmodified console with no memory patch and no code patch. Two records differing
only in their region mask produced two different verdicts, in the result at `bound+0x2C0` and on the
screen:

| region mask | result | the console's message |
|---|---|---|
| `0x0000` | 2 | a gift was received but cannot be obtained in this game |
| `0xFFFF` | 1 | receiving the gift failed |

Those match the two paths. `0x00ff1fb0` returns the importer's value when it is non-zero, and
otherwise returns 2 when the card list is left empty. A record filtered out by the region mask is the
second case: the importer ran and succeeded, and nothing was materialised. A record the mask accepts
goes on to `0x010b5de0`, which refused to build a card from a record whose fields beyond the card id,
the region mask and the flag at `+0x13` are all zero, and the importer passed that refusal back as 1.

The refusal is clean. Nothing faulted, no crash, no save prompt and no new error line from the
emulator, so the importer validates a record before materialising it and a malformed record is
rejected rather than run. The remaining unknown between here and a card the game keeps is the layout
of the 720-byte record itself.

The receive job is rebuilt whenever the search screen is re-entered: both `manager+0x68` and the
object the sink is bound to move. Anything holding those addresses across a screen exit is reading a
dead object.

## The first card the game kept

A sealed record of kind 3 was accepted, shown in the gift list, confirmed, and written to the save.
The whole envelope works: the beacon, the body checksum, the type byte, the fragmentation and its
300-byte seams, the message checksum, the reassembly, the sink, the record checksum, the region mask,
the gift kind, the importer, the gift list, the confirmation screen and the save write, from a beacon
built here against an unmodified console.

Three record fields were read back off the screen. The title came from the kind at `+0x11`, the
quantity came from the word at `+0x20`, which was set to 1, and the date rendered as 1 January 2070,
which is what the game's epoch makes of zeroed date fields.

The card delivered nothing, which is what a kind-3 record with an empty payload should do: that path
builds no sub-object, and the identifier of what to give was zero. The save nonetheless changed in 29
regions totalling 671 bytes, clustered around `0x062000`, and gained a 789-byte `poke_trade` file.

The album does not keep the wire record. Neither the 720 bytes nor any string in them appears in the
save, so the card is re-encoded on the way in, and the stored form is its own question.

## The store is not drained on the Mystery Gift screen

Nothing above runs there. `0x010f65a0` is the gfl net manager's per-frame update, reached with the
manager from `0x0261cba8` as its argument. It takes a steady-clock reading on entry, drains the
receiver at `manager+0x60` through the swap `0x006c5300`, walks the entries, and writes that reading
to `manager+0x80` on every pass that finds a non-empty store.

A session can reach a state where it does neither. In one, three bodies accepted from three beacons
sat in the store with its count climbing 1, 2, 3 and never falling, the first still in place 27
minutes later through 24,651 consecutive samples, while `manager+0x80` held one constant value and
`job+0x160` stayed null. Nothing measured on such a session says anything about the payload, since the
type byte is never read there. Two later sessions drained normally, so the condition is a property of
the session rather than of the screen, and what causes it is unresolved. Check that the update is live
before reading any beacon result: `manager+0x80` advancing is the cheapest proof.

This also settles what `manager+0x80` is. It is where the update stamps its clock reading, not the
Wonder Card list an earlier revision of this page called it; the `+0x80` accesses around the importer
`0x00ff2170` are the thread-local guard stack that `nn::os::GetTlsValue` returns, the same push and
pop that surrounds the store append at `0x006c54a4`.

What ticks the update is unresolved. Its only caller is `0x01109240`, a sequence of per-subsystem
updates, and the function holding that call, `0x00f1df30`, has neither a `bl` caller nor a vtable
slot, so it is reached through a registered callback.

A 0x2D0 Wonder Card record does not fit in one payload, which holds at most 355 bytes, so a card
spans several beacons. How the header's `+6` and `+7` bytes index the pieces is unresolved.

Unresolved: the layout of the payload a distributor sends, the gflnet3 message header inside it (10
bytes at `0x010F7C08` on the send path: u32 id at 0, u16 at 4, u8 at 6, u8 at 7, u16 at 8), and how a
720-byte record fragments across beacons when the payload holds at most 355 bytes. `0x136`, named a
channel in an earlier revision, is a `memset` length at `0x010F7E00`; the message id comes from the
getter `0x010F7050`.
