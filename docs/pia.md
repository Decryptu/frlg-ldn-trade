---
title: The Pia layer
parent: The wireless layer
nav_order: 1
---

# The Pia layer

Pia is Nintendo's peer-to-peer session middleware. It runs directly on UDP — port **12345** in every
title examined — and every datagram begins with the magic `32 AB 98 64`, big-endian on the wire.

The Pia version decides the header layout. Three bands appear in the titles covered here:

| | FireRed/LeafGreen (the GBA app) | Brilliant Diamond / Shining Pearl | Sword / Shield |
|---|---|---|---|
| Pia version byte | 15/16 (6.32+) | 9 (5.27–5.45) | 4 |
| header size | 0x1D | 0x20 | 0x20 |
| variable ids | 2 bytes each | 4 bytes each | 1 byte + a halfword |
| GCM tag on the wire | | 8, truncated from 16 | all 16 |
| module | `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py` | `pokeldn/ldn/pia4.py` |

Addresses given below as `0x01…` are offsets into Shield 1.3.2's decompressed `main`, as
`tools/switch/nso_read.py` lays it out; addresses given as `main.bin 0x01…` are BDSP 1.3.0's.

## Packet headers

### Version 9 (Pia 5.27–5.45)

Read field by field out of `nn::pia::common::Packet::Header`; the parser byte-swaps three fields
with `rev`, which is what fixes the byte order.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F)
    0x05  4  destination variable id, big-endian   (0 = broadcast to the mesh)
    0x09  4  source variable id, big-endian
    0x0d  2  packet id, big-endian
    0x0f  1  footer size
    0x10  8  AES-GCM nonce, a monotonic counter
    0x18  8  AES-GCM tag, truncated from 16
    0x20     ciphertext: the plaintext padded to a multiple of 16

`pokeldn/ldn/pia5.py` round-trips real captured packets byte-identically.

### Version 4

Read out of the deserializer at `0x01774730`, which requires more than 0x1f bytes
(`cmp w2, #0x1f; b.hi`) and then copies field by field:

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  a station index
    0x06  2  big-endian halfword, a session or protocol id
    0x08  8  AES-GCM nonce, a monotonic counter
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

The widths, the endianness, the 0x20 total and the version byte are measured. The initializer at
`0x017748bc` writes magic and version as one 64-bit store, `0x00000004_32AB9864`, and zeroes exactly
8 bytes at the nonce and 16 at the tag; three validators (`0x017749f0`, `0x01774b60`, `0x01774d00`)
each check `(byte & 0x7f) == 4`. BDSP's binary carries the same three validators against 9 and the
same initializer writing 9.

The meanings of the byte at 0x05 and the halfword at 0x06 are unconfirmed. `0x017beb74` and
`0x017beb78` write them, taking the byte from the caller and the halfword from a session object.
Both were zero in every captured packet, so the capture agrees with the widths and says nothing
about the meanings.

Below the header, version 4 is version 9's LDN family unchanged: the same session key, the same IV,
and the same message framing with one extra field. `pokeldn/ldn/pia4.py` is fifty lines rather than
a second stack.

## Message framing

A Pia payload carries one or more messages. Each opens with a presence byte saying which header
fields follow. The walk stops at `0xFF` and at nothing else (`0x01852da0`), so **`0x00` is a legal
one-byte header** stating no field at all. A field the presence byte omits is inherited from the
previous message in the same packet (`0x01853050`, bit by bit): flags at +9, size at +0xA,
protocol|port at +0xC, destination at +0x10 and source at +0x18. An inherited size is bounds-checked
against 0x589.

The header size is computed inline at eighteen sites in the version-4 Pia band, always as the same
five conditional adds over a base of one:

    tst w9, #1    -> +1       message flags
    tst w9, #2    -> +2       payload size, big-endian
    tst w9, #4    -> +4       protocol id and a 3-byte port
    tst w9, #8    -> +8       destination
    tst w9, #0x10 -> +8       the sender's station constant id

So a presence byte of 0x7F gives a 24-byte header and bits 0x20/0x40 add nothing, the same way
version 9's 0x7F adds nothing past 0x0F. Version 9's header is 16 bytes; version 4 adds the eight-byte
constant id. That id is `station_protocol.ldn_constant_id` over the sender's MAC — the same integer
the Local Protocol's `host_constant_id` carries, big-endian in the Pia header and little-endian in
the Local Protocol body.

Each message is padded to a multiple of four, and the packet tail is `0xFF`.

`pia4.parse_packet()` resolves the inheritance; `pia4.parse_messages()` returns each header as sent.
The check that a walk is correct is that consumed bytes plus `0xFF` padding account for the whole
plaintext of every packet in a capture.

### Compression

A message's payload may be a zlib stream, flagged in the message flags:

| Pia version | zlib flag |
|---|---|
| 5.27–5.45 | 0x20 |
| 4 | 0x10 |

The version-5 reliable stream has a flag of its own, 0x10 in its own header; BDSP has set it on one
23-byte game message, sent as a 20-byte zlib stream with a 4 KB window
([BDSP's protocol](bdsp_protocol.md)).

It is not negotiated and not per-protocol: BDSP switches it on mid-session the moment there is
anything worth compressing. Read raw, a compressed 31-byte message parses into a header claiming a
payload of 0x6260 — well-formed-looking and meaningless. Over 2835 version-4 messages in two
captures, `flags & 0x10` predicts zlib-decompressibility exactly: 256 set and every one a valid
stream, 2579 clear and none decompressing. A zlib stream is recognisable by hand as well: its first
two bytes read as a big-endian halfword are a multiple of 31.

### The footer

A packet sent to more than one console carries a footer: one big-endian halfword per recipient, the
low half of each station's variable id. Its length is the header field at offset 0x0f, and **it is
not covered by the GCM tag**. Including it in the ciphertext makes the packet fail to authenticate
with no other symptom. The correct boundary is `data[0x20 : len(data) - footer_size]`;
`pokeldn/ldn/pia5.ciphertext()` reads the size off the packet. A capture where some packets
authenticate and some do not is the signature — group the failures by footer size before doubting
the key or the IV.

## Session keys

Pia carries a separate session-key implementation per network type, in separate classes:

| network type | class | derivation |
|---|---|---|
| **LDN** (local wireless) | `nn::pia::local::LocalProtocol` | AES-128-ECB under the game key, over 16 bytes drawn from an xorshift128 seeded from a session value |
| LAN | `nn::pia::lan::LanProtocol` | first 16 bytes of HMAC-SHA256(game key, a 32-byte parameter whose last byte is incremented) |
| NEX (internet) | `nn::pia::nex::*` | session key from the matchmaking server |

A Union Room or any local-wireless session is LDN, so the first row applies. Published prose that
describes a game as encrypting "the SSID or random values seeded with the session parameter" is
describing two implementations; only the class name says which a capture used.

### The game key

The game key is not a fixed constant of a title. It is a constant plus the game version:

    key = cryptoKeyDataSeed                     the game's own 16-byte constant
    key[1]  = (version >> 8) & 0xFF
    key[3]  = (version >> 4) & 0xFF             version = the local communication version,
    key[7]  = (version >> 1) & 0xFF                       which the advertisement carries
    key[12] = (version >> 0) & 0xFF

A published per-game key is therefore a derived value for one game version, and it differs from the
game's own seed in exactly bytes 1, 3, 7 and 12 — which is indistinguishable from a corrupt
transcription without this rule. `ldn_game_key()` implements it.

Sword/Shield is the exception: its key is a 16-byte ASCII literal loaded with a single `ldp` and
handed over unchanged, with no seed and no version substitution.

### The LDN session key

For Pia 5.9–5.45:

    rnd = four SEAD draws, seeded with the SESSION PARAMETER from the advertisement (+0x0c),
          packed little-endian into 16 bytes
    session key = AES-128-ECB(game key).encrypt(rnd)

SEAD is Nintendo's standard-library RNG: the state is seeded by the recurrence
`s[i] = (prev ^ (prev >> 30)) * 0x6C078965 + i` and run as an xorshift128 with shifts 11, 8 and 19.
`pokeldn/ldn/sead.py` is the generator and `pia5.ldn_session_key()` the derivation.

For Pia 6.16+ the session key is instead AES of the network SSID under the game key, which is what
FireRed uses.

### The AES-GCM IV

For Pia 5.27–5.45, and unchanged in version 4:

    IV[0..2]  = first three bytes of crc32( network id (LITTLE-endian) || SOURCE MAC ADDRESS )
    IV[3]     = source variable id & 0xFF        both from the packet header
    IV[4..11] = the packet's 8-byte header nonce

`ldn_nonce_crc()` and `gcm_iv()`. The source MAC is the field that cannot be read off the packet
being decrypted; everything else comes from the capture or the advertisement.

The plaintext is padded with `0xFF` to a multiple of 16 before encryption. That padding is free
known-plaintext: a candidate key can be tested with one AES block rather than a whole GHASH.

## The protocols

Read off `GetProtocolId`, which is vfunc4 on every `nn::pia` protocol object and whose body is two
words, so one pass over the RTTI vtables names the whole numbering.

| id | class | notes |
|---|---|---|
| 0x14 | MeshStationProtocol | the connection handshake; also carries every mesh acknowledgement |
| 0x18 | MeshProtocol | join, update mesh, host migration |
| 0x1c | SyncClockProtocol | |
| 0x24 | LocalProtocol | the update session a host rebroadcasts |
| 0x54 | BandwidthCheckProtocol | |
| 0x58 | RttProtocol | round-trip timing |
| 0x68 | UnreliableProtocol | |
| 0x77 | ClockProtocol | |
| 0x7c | ReliableProtocol | the reliable sliding window |
| 0x80 | BroadcastReliableProtocol | |
| 0x84 | ReliableBroadcastProtocol | a different class from 0x80 |
| 0x94 | SessionProtocol | |
| 0xa4 | MonitoringDataProtocol | |

BDSP registers nine of these and advertises versions 0x14 v2, 0x18 v3, 0x1c v0, 0x24 v0, 0x58 v3,
0x68 v1, 0x7c v3, 0x94 v1, 0xa4 v0. Mesh protocol version 3 pins the library to Pia 5.30–5.45 and
reliable version 3 narrows it to 5.31–5.43.

### Joining a mesh

A station reaches a mesh through three protocols in order — the Local Protocol's update session
(0x24), the Mesh Station Protocol's connection request (0x14), and the Mesh Protocol's join request
(0x18) — and each retransmits every 500 ms until acknowledged.

**A mesh message is acknowledged on the station protocol.** The Mesh Protocol's type table has no
ack in it and a 5.31–5.43 binary has no builder for one: each of the four sites that acknowledges a
mesh message reads the ack id and then calls a `MeshStationProtocol` method, so what goes on the air
is the station protocol's eight-byte type-5 ack on 0x14 — `05 00 00 00` and the ack id, big-endian.
The ack id is the **last four bytes of the message**, whatever its length; the reader is `size - 4`
with a borrow check and answers 0 for anything shorter than four bytes.
`pokeldn/ldn/mesh_protocol.ack_for()`.

A host also acknowledges an incoming join *request* before it sends the join *response*, so a join
loop that breaks on any reply has no response in hand when it goes to acknowledge one. The ack
belongs in the receiver, on every copy.

## The Local Protocol (0x24)

The host broadcasts an **update session** (message type 0x11) about every 100 ms and repeats it
until every station acknowledges it. Its body:

    local message header  version 1, type 0x11, size 73
    sequence id
    network id            random, and NOT the advertisement's network id
    host variable id      the same value as the packet header's source variable id
    host constant id
    allow participating
    node 0..7             address:port and a ranking byte each
    host migration state

Eight nine-byte node slots and one byte. The byte order changes twice inside one message: the Pia
message header around it is big-endian, the Local Protocol's own fields are little-endian, and a
local address inside them is big-endian again.

`pokeldn/ldn/local_protocol.py` parses it and the same parser reads version 4's unchanged.

### The ack

The 20-byte ack (type 0x21) is built by `LocalAckMessage::Serialize` (`main.bin 0x016bc0f4`): `1` at
offset 0, the message type at 1, the payload-size halfword at 2, six zero bytes at 4, the sequence
id at 0x0C and four zero bytes at 0x10. The constructor (`0x016bc0c8`) does `mov w8, #0x14; str w8,
[x0, #0x14]`, a word store that writes the 20-byte total into the halfword at +0x14 and zeroes the
payload size at +0x16, so an ack's payload size is 0 and the whole message is 20 bytes.

`LocalProtocol` has exactly one send path (`0x016af22c`), and all four of its message types reach it
with the same destination object and options, so an ack is framed exactly like the update session it
answers: presence `0x7F`, message flags `0x11`, protocol 36, port 0, destination 0. Flags `0x11` is
"destination is a bitmap" plus "may not be bundled"; the bitmap (`0x0159a15c`) is `1 << station
index`, or 0 for broadcast.

**An ack is attributed by the sender's address, not by any id.** `0x016af96c` handles a received
0x21 and calls `0x016aec94`, which walks nine node slots at `this+0x188` in steps of 0x40 and
compares each with a memcmp of 16 bytes of address at +8 plus the port halfword at +0x18. The
client's own Pia variable id still reaches the IV as the low byte of the source variable id, so it
must be stable within a run and non-zero.

A client broadcasts its ack the way the host broadcasts the question — a broadcast to the network
broadcast address with packet `dst_var` 0 and message destination 0, which is what the host itself
sends. The pass signal is that the rebroadcast stops.

## The Mesh Station Protocol (0x14)

The receive dispatcher reads the message type from byte 0, subtracts one, bounds it at six and jumps
through a seven-entry table (version 4: `0x017c5f50`, table `0x02081804`; BDSP: `0x0154e848`, table
`0x3e6b38f`). The seven types are connection request, connection response, disconnection request,
disconnection response, ack, relay connection request, relay connection response.

### The version-9 connection request

Checked in this order, which is what a probe can exploit:

| offset | field | a failure gives |
|---|---|---|
| | size 15..949 | drop |
| 0x0 | message type, connection result, platform id | drop |
| 0x3 | target constant id, big-endian u64, compared with the console's own | silence |
| 0xB | target variable id, big-endian u32, compared with the console's own | silence |
| 0xF | number of protocols, compared with the console's own count | silence (error 0x11c26) |
| 0x10 | that many (id, version) pairs | version low → result 2, high → result 3, both replied |
| | station location size, big-endian u16, 0x20..0x40 | drop |
| | the station location | drop |

`0x0159b850` looks a protocol version up by id by walking the registered list and returns 0 when it
finds nothing, so an unregistered id expects version 0 and a version of 1 against it is always "too
high" — a reply rather than a drop. That makes the protocol count and every protocol's version
measurable without knowing any protocol in advance: send N pairs of `(0xFF, 1)` for each N in turn,
and the N that draws a denial is the console's own count.

The result byte maps from internal errors at `0x0154f5e8`:

| error | result | meaning |
|---|---|---|
| 0x646f | 2 | our version too low |
| 0x6470 | 3 | our version too high |
| 0xc24 | 4 | |
| 0xc25 | 1 | |
| 0x11c0f | 7 | the request parsed and every version matched; the second stage refused it |
| 0x11c26 | *(none)* | the protocol count mismatch, which is why that one is silence |

The parser checks that our count equals the console's and that each of our entries carries the right
version; it never checks that our ids are its ids. Nine entries of `(0xFF, 0)` therefore pass the
whole negotiation.

Result 7 also means "this variable id is already one of my stations". Leaving and re-entering the
room clears it, and so does a fresh id.

**The station location's address-size byte counts the port.** The InetAddress parser builds
`1 << size` and tests it against `0x00040044`, so only 2, 6 and 18 pass. The connection-request
parser throws the location's error away, so a malformed location still reads as a well-formed
request whose variable id is 0 — and every variable id then draws the same refusal because none of
them was ever read.

Related sizes, each read off the binary: the station protocol's ack is 8 bytes (`0x0154fa2c`), its
denial 15 (`0x015501ec`), its disconnection response 1 (`0x0154ea60`).

### The version-4 connection request

The same protocol number carries a different message. The handler at `0x017c62a0` reads:

    [0]     message type            1
    [1]     a byte compared against the station's own byte at +0x79
    [2]     platform id             must be 9   (5.27-5.45 checks 4)
    [3]     0 or 1; anything higher is rejected. 1 means the request also names a target variable id
    [4]     target constant id      big-endian u64, compared against the console's own
    [0xC]   target variable id      big-endian u32, checked ONLY when [3] is 1
    [0x10]  protocol count          compared against the console's own count at +0x78
    [0x11]  the sender's station location

which is version 9's layout shifted one byte from offset 3 onwards, plus the flag byte that causes
the shift. Sending version 9's request at a version-4 console puts every field one byte early.

There is no protocol list: everything from 0x11 is the station location, written by one serializer
call capped at 0x40 bytes. The location itself is unchanged from version 9 — the deserializer at
`0x0185ee20` stores to the same offsets in the same order and its address-size byte still admits only
2, 6 and 18 — which names the two bytes at [1] and [0x10] as the location's own **nat flags** and
**nat location**.

Setting [3] to 0 is what gets a request answered. With [3] = 1, asking the console to check a target
variable id, 96 requests drew nothing; with [3] = 0 the console answered with a connection request of
its own, carrying its location, its constant id, the variable id the update session had already
given us, a service variable id, a nat quad, and then four bytes that are not part of the location:
an **ack id**, a counter that increments once per message. `0x017d5750` reads it as the message size
minus four.

The platform byte is a useful instrument. Its check sits above every other one (`0x017c62e8`) and a
mismatch is *answered* rather than dropped: it tail-calls the connection-response sender
(`0x017c6c30`), which allocates 17 bytes and writes `[0] = 2`, `[1] = the result code`, `[2] = 9`,
`[3] = 0`. Everything below the platform byte is silence on mismatch, so a deliberately wrong
platform separates "the packet never reached the handler" from "it reached the handler and failed a
later check". Sent with platform 4, a retail Sword answered
`02 02 09 00 00 00 00 00 00 00 00 00 00 00 00 00 00` — result 2, version too low.

The whole handshake, once [3] is cleared:

    ->   the console's connection request
    <-   our connection response, result 0, carrying its constant and variable ids
    ->   `05 00 00 00 <ack id>` - a type-5 ack, eight bytes
    ->   its own connection response, result 0, accepted, ~600 bytes, carrying our constant id,
         our variable id and the player's name in plain ASCII

and it repeats that response until acknowledged. The u32 in an ack is the acked message's own
trailing counter.

## The Mesh Protocol (0x18)

The dispatcher is reached through `MeshProtocol::vfunc9` — vfunc9 is the receive slot on every Pia
protocol object — and reads the message type from byte [0], subtracts one, bounds it at 0x80 and
jumps through a table (version 4: dispatcher `0x017c0c80`, table `0x02081564`). Nineteen of the 129
entries are live. Version 4's table is BDSP's minus 0x22 DUMMY_MESSAGE and 0x23 DUMMY_ACK.

**The join request is six bytes**: type 1, the station index 253 meaning "not in a mesh yet", and an
ack id. The version-4 handler (`0x017c1700`) compares byte [1] against 0xFD and takes the ack id with
`0x017d5750`, then acks on 0x14 with the eight bytes built at `0x017c6dd0`. Pia gives up after ten
seconds of retransmission.

**The join response header is sixteen bytes** in both bands. The version-4 parser is `0x017b4830`: it
reads the refusal shape first (`[1] == 0`, `[2] == 0xFF`, `[3] == 0xFF`, reason at [4]), then the
station count at [1] against its own maximum, packs [8] [9] [0xA] into one big-endian 24-bit value,
and loads the update counter big-endian at 0xC.

**The station entry stride differs.** 5.31–5.45 uses 68 bytes: a 64-byte station location, the
station index, and a big-endian halfword join order. Version 4 uses **64 bytes with the index at
0x3E** and no join order. Three numbers agree on that reading and only that reading: the loop starts
its cursor at `0x10 + 0x3E` and reads `ldrb w8, [x20], #0x40`; the parser refuses a response longer
than 0x810; and `0x810 = 0x10 + 32 * 0x40` against the 32-station bound at `0x017bfa34`. A 68-byte
entry would make the bound 0x890.

Version 4 also reads the entry count from a different field in each path. An unfragmented response
(`fragments == 1`, `0x017b48f4`) walks `stations` entries from base 0 and never touches [6] or [7]; a
fragmented one (`0x017b4b6c`) walks [6] entries into slot [7] and checks [1]–[4] against the first
fragment. At most three fragments are allowed. The 5.31–5.45 reading takes [6] in both cases, so a
host that leaves it zero on a single-fragment response would hand that reading an empty mesh.
`parse_join_response(version4=True)` follows both paths.

Two message lengths confirm the version-4 stride without the disassembly:

    join response   148 B  =  0x10 + 2 * 0x40 + 4        68-byte entries would give 156
    update mesh     524 B  =  12   + 8 * 0x40            BDSP's eight 68-byte seats give 556

**UPDATE_MESH (0x20)** is the host's periodic statement of who is in the mesh, sent about once a
second. In BDSP it is always the full 556 bytes with unused seats zeroed, so the length says nothing
and the `entries` byte is what to walk. `mesh_protocol.parse_update_mesh()`.

The 5.31–5.45 join order counts joins rather than seats: after three successive connections from the
same machine it reads 0 for the host and 3 for the client at station index 1.

### Host migration

The mesh migrates the host role, and a station named as the next host has to answer.

Port 1 of the mesh protocol is the reliable port, so a payload on 0x18 port 1 arrives under the
reliable header and the mesh message is inside it.

**MIGRATION_START (0x44) is three bytes.** The handler `0x017c1f00` refuses the message unless

    size == 3                                     0x017c1f54
    [1] == the mesh's HOST index, byte 0xAB       0x017c1f64, getter 0x017bbfe0
    [2] <= 0x1F                                   0x017c1f78, the 32-station bound
    [2] != that host index                        0x017c1f8c

and the sender builds exactly those three at `0x017c31b8`: `[0x44, host index, new host index]`.

**The answer is two bytes: `[0x48, our own station index]`.** The MIGRATION_RESPONSE handler
`0x017c10ac` refuses anything but `size == 2`; the builder `0x017c3310` writes `[0x48, w22]` where
w22 came from `0x017bc430`. The two index getters are one byte apart and are different fields:
`0x017bbfe0` is `ldrb w0, [x0, #0xAB]`, the host's index, and `0x017bc430` is `ldrb w0, [x0, #0xAC]`,
the station's own. In a two-station mesh they hold the same number.

MIGRATION_FINISH (0x41) closes it: three bytes, `[0x41, host index, flag & 1]` (`0x017c2ef0`), with
its handler `0x017c0fb0` checking `size == 3` and [1] against the host index.

`pokeldn/ldn/mesh_protocol.py` has `parse_migration_start`, `build_migration_response` and
`parse_migration_finish`. None of the four published Sword/Shield clients handles migration, because
in a console-to-console capture the second console answers it invisibly.

## The RTT protocol (0x58)

The host starts timing a station the moment it is in the mesh. There is no wiki page for this
protocol.

Version 9's message is thirteen bytes and always thirteen:

    u8   kind        0 = request, 1 = response; anything else is dropped
    u64  timestamp   big-endian, the sender's own clock
    u32  target      big-endian, whose reply this is - and zero is accepted by everyone

Version 4 keeps the protocol number (vfunc4 at `0x0185d590` returns 0x58) but its parser
(`0x0185d2a0`) reads a flat 0x10 — **sixteen bytes**. A thirteen-byte answer is three short and reads
exactly like being ignored. Bytes 1..7 are zero in every request observed and their meaning is
unknown, so `rtt_protocol.response_for_v4()` echoes them and sets only the kind.

A station answers with kind 1 and the timestamp echoed unchanged; the receiver's first test on the
target field is "if zero, accept". The host computes `(now - echoed) / ticks per ms` into a
nine-sample ring per station, whose median becomes that station's RTT once the ring is full.
BDSP timestamps advance at about 31.36 MHz.

**Nothing in this protocol drops a station for staying silent.** A station that never answers simply
never gets a sample. Answering does change the host's behaviour measurably: BDSP's request period
moves from 410 ms to 508 ms — the branch taken once every sample ring is full — and its reliable
retransmit interval collapses accordingly.

BDSP addresses: protocol id and version at `0x015ada10`/`0x015ada18`, message size
(`mov w0, #0xd`) at `0x015adab4`, serialise/parse at `0x015ada24`/`0x015ad54c`, the update at
`0x015acd90`, the answer builder at `0x015ad024`, the target check at `0x015ad000`, the sample ring
at `0x015ad058`.

## The reliable sliding window (0x7c)

### Version 9 (Pia 5.29–5.43)

    0x0  1  flags     1 application data, 2 message start, 4 message end, 8 is initialized,
                      16 zlib, 32 reset, 64 reset ack
    0x1  1  stream id
    0x2  2  payload size, big-endian
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  number of destination bits (N)
    0x9  4 * ceil(N / 32)  destination bitmap words, big-endian
            payload

The header is 9 or 13 bytes: `GetSize` is `9 + (((N + 0x1f) >> 3) & 0x3c)`. N is refused at 0x20 or
more, and a payload of 0x5a1 or more is refused.

When the application-data flag is clear the payload is a bulk acknowledgement, two bytes then `n`
entries of 21:

    0x0  1   a bitfield; 0 in every captured ack. Its bit 0 sets a flag on the receiver
    0x1  1   entry count, refused at 0x21 or more
    0x2  21 * n  entries: u8 stream id, u16be ack id, u16be `ack id - 1`, 16-byte ack mask

A retail console's ack to two application messages, sequences 0 and 1:

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16

No flags at all, stream 0, sequence id 0xFFFF (a control message carries no sequence of its own), and
the lowest id the sender is still waiting on. `ack id` is one more than the highest sequence
received. `pokeldn/ldn/reliable5.build_ack_message()` reproduces it byte for byte.

A window that accepts application data must acknowledge it, so sending data and sweeping only the
sequence id measures the ack format directly. Sequence 0 draws nothing and sequence 1 draws the ack.

### Version 4

Version 4 uses **one header class for both reliable protocols**, 0x7C and 0x80 alike:
`nn::pia::transport::ReliableSlidingWindow::MessageHeader` (GetSize `0x0184e480`, Deserialize
`0x0184e390`, Serialize `0x0184e230`).

    0x0  1  flags
    0x1  1  stream id
    0x2  2  payload size, big-endian    refused at 0x589 and above (0x0184e3cc)
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  destination COUNT           refused at 0x20 and above (0x0184e404)
    0x9  8 * count  station constant ids, big-endian

**The byte at 0x8 is a count of eight-byte ids, not version 9's bitmap width.** `GetSize` is
`9 + 8 * count`. The two rules agree at count 0 and nowhere else, and count 0 is every 0x7C message
either side sends, which is why version 9's parser reads 221887 version-4 messages without a field
out of place.

The receive path (`0x01859338`) refuses five things in silence:

    0x0185952c   payload size <= 0x57F - 8 * count     tighter than the deserialiser's own bound
    0x0185954c   the Pia message length must EQUAL 9 + 8 * count + size, exactly
    0x0185956c   the stream id must be the window's own for this station, [w + 0x18*st + 0x46]
    0x01859578   a count above 0 is a list the receiver must find itself in; count 0 is unfiltered
    0x01859ca0   the first message on a stream must carry FLAG_IS_INITIALIZED

It then dispatches on the flags at `0x01859734`: bit 5 RESET, bit 6 RESET_ACK, bit 0
APPLICATION_DATA, and everything else falls through to the ack handler `0x01859a70` — so a message
with no flags at all is an ack.

**The first data message opens the stream and chooses where it starts.** While the per-station byte
at `[window + 0x18*station + 0x47]` is zero the stream does not exist; the handler requires
FLAG_IS_INITIALIZED and only then adopts the message's stream id into `+0x46` and its sequence id
into `+0x40`. A console's own traffic shows this: flags 0x0F on its first message and 0x07 on every
one after it.

`reliable4.build_data_message(bytes.fromhex("610000000a00"))` reproduces a console's own sequence 1
byte for byte: `0f0000060001000100610000000a00`.

**Version 4's ack payload is exactly 0x260 bytes**, 32 entries of 19, with nothing in front of them:

    5.29-5.43   1 unknown byte, 1 count, then `count` x 21 bytes
                    u8 stream id, u16be ack id, u16be the window's field 0x50, 16-byte mask
    version 4   32 entries of 19 bytes, ALWAYS
                    u8 stream id, u16be ack id, 16-byte mask

This is the wiki's original "Ack Data", which 5.29 replaced with a counted list. The handler
`0x01859a84` opens `ldrh w8, [x2, #0xa]; cmp w8, #0x260; b.ne` and answers error 0x2c03 without
reading the body; the serialiser `0x0185bfb0` bounds the buffer at 0x260, loops 0x20 times, and
writes per entry a stream id, an ack id big-endian into [1] and [2], and sixteen mask bytes as two
big-endian u64 halves.

Which of the 32 slots is read is a station index, and the site does not say whose — the handler
indexes the table with its fourth argument and requires that slot's stream id to match the window's
own (`0x01859c1c`). `reliable4.build_ack_payload` fills every slot with the same entry, which is
correct under either reading.

**A window that is not sliding looks like one that is.** Sequence ids can grow while
`lowest_pending` stays fixed: that is a longer hold and a bigger backlog, not progress. The
distinguishing measurement is `lowest_pending`, which is in every message, and the retransmit count
per sequence id — a sliding window sends *fewer* copies of old ids.

## Protocol 0x80, the broadcast reliable window

`nn::pia::transport::BroadcastReliableProtocol` (vfunc4 `0x0184d880` returns 0x80). The similarly
named `ReliableBroadcastProtocol` is **0x84** and is a different class.

Its messages are compressed (version-4 flag 0x10). Read raw, 42 bytes parse into a header claiming a
payload of 0x6260. Decompressed they are 625 bytes: the reliable header above with a destination
count of 1 and one eight-byte station constant id, over the same 0x260 ack payload. The length settles
the header shape without the disassembly — version 9's bitmap rule gives 621 and the message is 625.

The ack names its own 32 slots: a console fills 0..7 with the real ack id and leaves 8..31 at zero,
and 8 is `max_total` from the join response. One entry per station the mesh can hold, indexed by
station index.

## Protocol 0x84, the reliable broadcast transfer

`nn::pia::transport::ReliableBroadcastProtocol`. Used by Sword/Shield to move the trade snapshot. Its
message kinds:

| kind | meaning |
|---|---|
| 0x11 / 0x12 | a data fragment; a counter at [4] and a capacity at [10] |
| 0x19 | the transfer is complete |
| 0x21 | an ack carrying a contiguous base and a bitmask of what arrived early |
| 0x28 | the answer to 0x19 |

A receiver that never answers never sees the last three, and the sender retransmits indefinitely.
The total at offset [10] of a data message is a **capacity**, not the payload length.
`pokeldn/ldn/broadcast4.py`.

The two directions do not share a Pia port: a console sends its own transfer on port 0 and
acknowledges the peer's on port 1.

## Searching the published sources first

The reference material is searchable and searching it takes minutes.

    gh search code "<a constant you have>" --limit 20
    gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
    gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

The NintendoClients wiki is a *repository*, so code search reaches inside it, and it holds per-game
pages that the summary tables do not link. `Pokemon-Brilliant-Diamond.md` states the key derivation
above; the `Pia-Game-Keys` table lists only the derived result.

Published values are transcriptions and can be stale, wrong, or correct in a way that looks wrong.
Read the binary to verify a published value and to obtain what nobody published; search first so you
know what you are verifying.

## Credits

The packet-header version table, the session-key derivations and the nonce layouts come from the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol). Which derivation
belongs to which network type, the `cryptoKeyDataSeed` value, and the version rule that turns it into
the published key were read out of retail titles' own code.
