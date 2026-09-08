---
title: The Pia layer
parent: The wireless layer
nav_order: 1
---

# The Pia layer

Pia is Nintendo's peer-to-peer session middleware. It sits directly on UDP - port **12345** in every
title looked at so far - and every datagram begins with the magic `32 AB 98 64`, big-endian on the
wire.

Pia's version decides the header layout, and titles of different ages speak different versions. Two
are implemented here:

| | FireRed/LeafGreen (the GBA app) | Brilliant Diamond / Shining Pearl | Sword / Shield |
|---|---|---|---|
| Pia version byte | 15/16 (6.32+) | **9** (5.27-5.45) | **4** |
| header size | 0x1D | **0x20** | **0x20** |
| variable ids | 2 bytes each | **4 bytes each** | 1 byte + a halfword |
| GCM tag on the wire | | 8, truncated from 16 | **all 16** |
| module | `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py` | none yet |

Three bands, and the third was found by comparing the two titles' own parsers rather than by
assuming the older game used the older of the two headers we had.

## The 5.27-5.45 header

Read field by field out of the console's own parser rather than from documentation
(`nn::pia::common::Packet::Header`), which is why the byte order is known rather than assumed - the
parser byte-swaps three fields with `rev`:

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F)
    0x05  4  destination variable id, big-endian   (0 = broadcast to the mesh)
    0x09  4  source variable id, big-endian
    0x0d  2  packet id, big-endian
    0x0f  1  footer size
    0x10  8  AES-GCM nonce (a monotonic counter)
    0x18  8  AES-GCM tag, truncated from 16
    0x20     ciphertext, the plaintext padded to a multiple of 16

`pokeldn/ldn/pia5.py` implements it and round-trips real captured packets byte-identically; the fixture
in `tests/test_pia5.py` is one of them.

## The version-4 header (Sword/Shield)

Read the same way, out of Sword/Shield's own deserializer at `0x01774730` in `main`, which refuses a
buffer of 0x20 bytes or less (`cmp w2, #0x1f; b.hi`) and then copies field by field:

    0x00  4  magic 0x32AB9864, big-endian          (rev'd into the object)
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  a station index
    0x06  2  big-endian halfword                   (rev'd; a session or protocol id)
    0x08  8  AES-GCM nonce (a monotonic counter)
    0x10  16 AES-GCM tag, NOT truncated
    0x20     ciphertext

FACT: the widths, the endianness, the 0x20 total and the version byte. The header initializer at
`0x017748bc` writes magic and version as one 64-bit store - `0x00000004_32AB9864` - and zeroes
exactly 8 bytes at the nonce and 16 at the tag, and three validators
(`0x017749f0`, `0x01774b60`, `0x01774d00`) each check `(byte & 0x7f) == 4`. BDSP's binary has the
same three validators against **9** and the same initializer writing 9, which is what makes the
comparison a reading rather than a guess.

DEDUCTION, not yet separated on the wire: that the byte at 0x05 is a destination station index and
the halfword at 0x06 a session or protocol id. What writes them is `0x017beb74`/`0x017beb78`, which
takes the byte from its caller and the halfword from a session object. Both were zero in all 484
packets of sw01, so the capture agrees with the widths and says nothing about the meanings. Where
5.27-5.45 spends eleven bytes on a 4-byte destination id, a 4-byte source id, a 2-byte packet id
and a footer size, version 4 spends three - which is what an older Pia in a smaller mesh looks like.

**AND UNDERNEATH THE HEADER IT IS 5.27.** Measured against a retail Sword, sw01, 484 of 484 packets
authenticated: the session key is `ldn_session_key` over the advertisement's session parameter at
offset 12, the IV is `gcm_iv` unchanged - three bytes of the station CRC, a source-id byte, then the
header's own nonce - and the message framing is the same presence-flagged walk with one extra
eight-byte field, so a message header is 24 bytes rather than 16. The version byte buys a header
(`pokeldn/ldn/pia4.py`), not a protocol stack. Reading "a third band" as "a third implementation"
is the mistake this paragraph exists to prevent.

### Which presence bit owns which field

FACT, read off the game's own code and no longer a deduction from one message shape. The header size
is computed inline at **eighteen** sites in the Pia band, always the same five conditional adds over
a base of one - the presence byte itself:

    ldrb w9, [x?, #0x38]      the presence byte
    tst w9, #1    -> +1       message flags
    tst w9, #2    -> +2       payload size, big-endian
    tst w9, #4    -> +4       protocol id and a 3-byte port
    tst w9, #8    -> +8       destination
    tst w9, #0x10 -> +8       THE EXTRA FIELD: the sender's station constant id

1 + 1 + 2 + 4 + 8 + 8 = 24, which is why a presence byte of 0x7F produces a 24-byte header: **bits
0x20 and 0x40 add nothing**, exactly as 5.27's 0x7F adds nothing past 0x0F. `0x017c5e24` is the site
inside MeshStationProtocol; `0x01785d1c`, `0x017a71b4`, `0x0184bf8c` and fourteen more are the same
five adds inlined elsewhere.

And the eight bytes are the sender's constant id - `station_protocol.ldn_constant_id` over its MAC.
Two independent fields agree in sw01: the message header's source and the Local Protocol update
session's own `host_constant_id`, which is the same integer written the other way round (the Pia
message header is big-endian, the Local Protocol's body little-endian).

### Sending one

sw02, session 56: a version-4 packet built by `pia4.build_packet` and sent from our seat was
accepted by a retail Sword. The console had been broadcasting its update session ten times a second
for six seconds; **its last one came 13 ms after our first ack and it went silent for the rest of
the run**. sw03 is the control - the same packet with a sequence id the console never sent - and it
answered with 261 update sessions and never stopped. The station byte and the IV's source-id byte
were both 0, mirroring what the console sends.

## The version-4 Mesh Station Protocol, and why BDSP's offsets do not carry

Protocol **0x14** on both bands - Sword's `GetProtocolId` is a one-instruction body at `0x017c8460`
returning 0x14, and MeshProtocol's at `0x017c4280` returns 0x18, so the numbering is shared. The
receive dispatcher is at `0x017c5f50`: it reads the message type from byte 0, subtracts one, bounds
it at six and jumps through a seven-entry table at `0x02081804`. The seven types are 5.27's, in
5.27's order - connection request, connection response, disconnection request, disconnection
response, ack, relay connection request, relay connection response.

**THE MESSAGE ITSELF IS NOT 5.27's.** The connection-request handler at `0x017c62a0` reads, in
order:

    [0]     message type            1
    [1]     a byte compared against the station's own byte at +0x79
    [2]     platform id             must be 9   (5.27-5.45 checks 4)
    [3]     0 or 1, and anything higher is rejected outright; 1 means the request also
            names a target variable id
    [4]     target constant id      big-endian u64, compared against the console's own
    [0xC]   target variable id      big-endian u32, checked ONLY when [3] is 1
    [0x10]  protocol count          compared against the console's own count at +0x78
    [0x11]  the protocol entries

which is 5.27's layout **shifted one byte from offset 3 onwards**, plus the flag byte that causes
the shift. `pokeldn/ldn/station_protocol.py` is the 5.27 reading (constant id at 3, variable id at
0xB, count at 0xF) and sending it at a version-4 console would put every field one byte early. A
protocol number that matches across versions says nothing about the message that travels on it.

There is no protocol list at all: everything from 0x11 is the sender's STATION LOCATION, written by
one serializer call capped at 0x40 bytes, and the message is `0x11 + that`. The location is 5.27's
unchanged - Sword's deserializer at `0x0185ee20` stores to +0x48, +0x60, +0x68, +0x70, +0x74 and
+0x78..+0x7b in the same order, and its address-size byte still admits only 2, 6 and 18
(`(1 << size) & 0x40044`). So `station_protocol.station_location` builds one for version 4 unchanged,
and the two bytes at [1] and [0x10] are a station location's own **nat flags** and **nat location**.

### The platform byte is an instrument

The handler checks the platform at `0x017c62e8`, ABOVE every other check, and a value that is not 9
is not dropped - it tail-calls the connection-response sender at `0x017c6c30`, which allocates 17
bytes and writes `[0] = 2`, `[1] = the result code`, `[2] = 9`, `[3] = 0`. Everything below the
platform byte is silence on mismatch, so a deliberately wrong platform separates "our packet never
reached the handler" from "it reached it and failed a later check".

FACT, sw15: sent with platform 4 and otherwise unchanged, a retail Sword answered

    02 02 09 00 00 00 00 00 00 00 00 00 00 00 00 00 00

17 bytes, connection response, result 2 (version too low), platform 9 - the sender's own reading
back byte for byte, including the length. That is the first word a Sword has said to us above the
Local Protocol, and it proves the whole path: our version-4 packet decrypts, its 24-byte message
header is walked, protocol 0x14 dispatches, and the handler reads our byte at offset 2.

### Clearing [3] is what gets a real request through

FACT, sw13 against sw20 - one byte changed, everything else identical (platform 9, message flags
0x09, station byte 0, nat 0/0, the same location builder). With [3] = 1, asking the console to check
a target variable id, 96 requests drew nothing. With [3] = 0 the console **answered with a
connection request of its own**, addressed to our constant id and to the variable id we had invented
that run:

    01 6a 09 01 1249a221d8580000 21e6dcd4 00 | 02 06 0000 a9fe0201 3039 | 00000000 0000
    | eb9b2220f1480000 | 75bf17e2 | 597bc2a3 | 00 00 00 01 | 7106cab5

Its own location, read with the same parser: a size-**2** address then a size-6 one
(169.254.2.1:12345), relay address and port zero, its constant id, the variable id the update
session had already given us, a service variable id, and a nat quad of `00 00 00 01` - so **the
console's own nat flags and nat location are both 0**. Then four bytes that are not part of the
location at all: an **ack id**, a counter that increments once per message (`7106cab5`, `b6`, `b7`).
That is what `0x017d5750` reads by taking the message size minus four, and our own requests had
never carried one.

### The whole handshake, and the console accepting

sw21 answered that request with the 17-byte connection response and the console completed the
exchange inside 350 ms:

    t=7.75   ->   its connection request
    t=7.75   <-   our connection response, result 0, carrying ITS constant and variable ids
    t=7.76   ->   `05 00 00 00 121a8113` - a type-5 ACK, eight bytes
    t=8.10   ->   its own connection response, **result 0, ACCEPTED**, ~600 bytes, carrying our
                  constant id, our variable id and the player's name in plain ASCII

and then it repeated that response until it was acknowledged, exactly as the Local Protocol repeats
an update session.

FACT, sw24 against sw21 - the ack is the only difference. sw21 had nothing to say and counted about
ten retransmits of the acceptance; sw24 echoed the response's **trailing counter** back as
`05 00 00 00 7106cab9` and the console sent it **once**: three messages on 0x14 for the whole run,
one request in, one response in, one ack out, then silence. So the u32 in an ack is the acked
message's own tail, and the Mesh Station Protocol is closed in both directions.

    LDN association  ->  Local Protocol ack  ->  connection request ([3] = 0)
                     ->  answer its request  ->  ack its acceptance   = a station in the mesh

## The version-4 Mesh Protocol (0x18), and the one field that moved

Read off a retail Sword binary in session 57, offline, no run. The station protocol was the
cautionary tale here - protocol 0x14 kept its number across versions and changed its message, and
sending BDSP's request at Sword would have put every field a byte early. So 0x18 was read the same
way before anything was sent, and this time **almost nothing had moved**.

**The message table is the same table, minus two.** The dispatcher is `MeshProtocol::vfunc9`
(`0x017bfc30`, reached through the receive slot the station protocol uses at the same index), and it
tail-calls `0x017c0c80`: message type at byte [0], `type - 1`, a bound of 0x80, and a jump table at
`0x02081564`. Nineteen of its 129 entries are live, and they are exactly BDSP's constants **except
that 0x22 DUMMY_MESSAGE and 0x23 DUMMY_ACK are absent** - version 4 has no dummy message and both
fall to the default case.

**The join request needs no change at all.** Version 4's handler for type 1 is `0x017c1700`. It
reads the ack id with `0x017d5750` - `size - 4`, then a big-endian load, the same four instructions
BDSP has - and compares **byte [1] against 0xFD** at `0x017c1800`. That is the six bytes
`mesh_protocol.build_join_request()` already builds. It answers with the eight-byte type-5 ack built
at `0x017c6dd0`, on 0x14, so "a mesh message is acknowledged on the station protocol" holds here too.

**The join response header is the same sixteen bytes.** The parser is `0x017b4830`. It reads the
refusal shape first - `[1] == 0`, `[2] == 0xFF`, `[3] == 0xFF`, reason at [4] - then the station
count at [1] against its own maximum, packs [8] [9] [0xA] into one big-endian 24-bit value, and
loads the update counter big-endian at **0xC**. Every field where 5.31-5.45 has it.

**WHAT MOVED IS THE ENTRY: 64 bytes, not 68, with the index at 0x3E.** The loop starts its cursor at
`0x10 + 0x3E` (`add x20, x20, #0x4e`) and reads `ldrb w8, [x20], #0x40` per station. There is no
join order - the byte at 0x3F is not read on either path.

That stride does not rest on reading one loop. The same function refuses a response longer than
**0x810** bytes, and `0x810 = 0x10 + 32 * 0x40` against the 32-station bound at `0x017bfa34`: the
header size, the entry stride and the station limit are three numbers that only agree on one
reading. A 68-byte entry would make the bound 0x890.

**AND THE ENTRY COUNT IS READ FROM A DIFFERENT FIELD IN EACH PATH.** An unfragmented response
(`fragments == 1`, `0x017b48f4`) walks `stations` entries from base 0 and never touches [6] or [7];
a fragmented one (`0x017b4b6c`) walks [6] entries into slot [7], and checks [1] [2] [3] [4] against
the first fragment before it accepts one. Version 4 allows at most **three** fragments. The
5.31-5.45 reading takes [6] in both cases, so a host that leaves it zero on a single-fragment
response would hand that reading an empty mesh - which is why `parse_join_response(version4=True)`
follows the binary's two paths rather than the one.

`pokeldn/ldn/mesh_protocol.py` carries all of it: `STATION_INFO_SIZE_V4`, `INDEX_FIELD_V4`,
`MESH_TYPES_V4` and the `version4` flag on both parsers. UNKNOWN until a run: nothing above has been
on the air, and the ORDER - that nothing is answered on 0x18 until the 0x14 handshake has closed -
is BDSP's finding carried over, not a version-4 measurement.

## Two families of session key

The session key is not one algorithm. Pia carries a separate implementation per network type, and
the binary keeps them in separate classes - which is the only reliable way to tell which one a
capture used:

| network type | class | derivation |
|---|---|---|
| **LDN** (local wireless) | `nn::pia::local::LocalProtocol` | AES-128-ECB under the game key, over 16 bytes drawn from an xorshift128 seeded from a session value |
| **LAN** | `nn::pia::lan::LanProtocol` | first 16 bytes of HMAC-SHA256(game key, a 32-byte parameter whose last byte is incremented) |
| NEX (internet) | `nn::pia::nex::*` | session key from the matchmaking server |

The xorshift128 is seeded by the recurrence `s[i] = (prev ^ (prev >> 30)) * 0x6C078965 + i` - the
Mersenne Twister's initialiser used to fill a four-word state - and then run with shifts 11, 8 and
19.

A Union Room or any local-wireless session is **LDN**, so it is the first row that applies. Reading
the wiki's prose instead of the class names is what sent this project down the LAN branch for
several sessions.

## The LDN session key and nonce, in full

Everything below is confirmed twice: read out of a retail title's ARM64, and matching the
NintendoClients wiki. Both matter - the binary is what makes it verified, the wiki is what makes it
quick.

**The game key is not a constant of the game. It is a constant plus the version.**

    key = cryptoKeyDataSeed                     the game's own 16-byte constant
    key[1]  = (version >> 8) & 0xFF
    key[3]  = (version >> 4) & 0xFF             version = the LOCAL COMMUNICATION VERSION,
    key[7]  = (version >> 1) & 0xFF                       which the advertisement carries
    key[12] = (version >> 0) & 0xFF

So **a published per-game key is a derived value for one game version**, and the seed is the part
that does not move. A published key and a measured seed differ in exactly bytes 1, 3, 7 and 12, and
that is indistinguishable from a corrupt transcription unless you know this rule. `ldn_game_key()`.

**The session key**, Pia 5.9 - 5.45:

    rnd = four SEAD draws, seeded with the SESSION PARAM from the advertisement (+0x0c),
          packed little-endian into 16 bytes
    session key = AES-128-ECB(game key).encrypt(rnd)

`pokeldn.ldn.sead.Sead` is the generator and `ldn_session_key()` the derivation. For Pia 6.16+ the
session key is instead AES of the network SSID under the game key, which is what FireRed uses.

**The 12-byte AES-GCM IV**, Pia 5.27 - 5.45:

    IV[0..2]  = first three bytes of crc32( network id (LITTLE-endian) || SOURCE MAC ADDRESS )
    IV[3]     = source variable id & 0xFF        both from the packet header
    IV[4..11] = the packet's 8-byte header nonce

`ldn_nonce_crc()` and `gcm_iv()`. The source MAC is the field worth remembering: everything else
here can be read off the capture or the advertisement, and a search that has the key, the session
key and the IV layout all correct still fails on that one input alone.

The plaintext is padded with `0xFF` to a multiple of 16 before encryption, and only the **first
eight bytes** of the GCM tag go on the wire. The 0xFF padding is useful beyond parsing: it is free
known-plaintext, so a candidate key can be tested with one AES block instead of a whole GHASH.

## A message payload can be zlib compressed, and nothing says so but one flag

Message flag **0x20** in 5.27-5.45 means the message's PAYLOAD is a zlib stream. It is not a
per-protocol setting and it is not negotiated: BDSP switched it on mid-session, the moment there was
anything worth compressing - sp46's answer to a position message was 31 bytes of zlib around a
32-byte reliable ack.

This is the same trap as the footer below, and worse, because it does not fail loudly. Read raw,
those 31 bytes parse into a header claiming a payload of `0x6260` - a well-formed-LOOKING message
full of nonsense. Check the flag, decompress, and carry a `compressed` marker so a log line says
which it was. `pokeldn/ldn/pia5.parse_messages()` does. A zlib stream is easy to recognise by hand
too: the first two bytes as a big-endian halfword are a multiple of 31.

## The footer is not part of the ciphertext

A packet sent to more than one console at once carries a **footer**: one big-endian halfword per
recipient, the low half of each station's variable id. Its length is a header field at offset 0x0f,
so nothing has to be guessed - and **it is not covered by the GCM tag**. Feeding it to the cipher as
if it were ciphertext makes the packet fail to authenticate, silently and with no other symptom.

sp36 lost 111 packets to exactly that, every one of them the game's own unreliable traffic, for as
long as the decode read `everything after the header`. The right boundary is
`data[0x20 : len(data) - footer_size]`, and `pokeldn/ldn/pia5.ciphertext()` reads the size off the
packet when it is not told. A capture where *some* packets authenticate and some do not is the
signature: group the failures by `footer size` before touching the key or the IV.

## Joining a mesh: 0x14, 0x18, and where the ack lives

A Pia 5.x station reaches a mesh through three protocols in order - the Local Protocol's update
session (0x24), the Mesh Station Protocol's connection request (0x14), and the Mesh Protocol's join
request (0x18) - and every one of them retransmits every 500 ms until it is acknowledged.

**A mesh message is acknowledged on the STATION protocol.** The Mesh Protocol's type table has no
ack in it and a 5.31-5.43 binary has no builder for one: each of the four sites that acknowledges a
mesh message reads the ack id and then calls a `MeshStationProtocol` method, so what goes on the air
is the station protocol's eight-byte type-5 ack on **0x14** - `05 00 00 00` and the ack id,
big-endian. The ack id itself is the **last four bytes of the message**, whatever its length; the
console's own reader is `size - 4` with a borrow check, and answers 0 for anything shorter than
four bytes.

`pokeldn/ldn/mesh_protocol.ack_for()` is that rule in one call, and `docs/bdsp_pia.md` carries the
addresses it was read at.

**UPDATE_MESH (0x20) is the host's periodic statement of who is in the mesh**, and BDSP sends it
about once a second. It is always the **full 556 bytes** - twelve of header and room for all eight
seats, the unused ones left zero - so the length says nothing and the `entries` byte is what to
walk. `pokeldn/ldn/mesh_protocol.parse_update_mesh()`.

The 5.31-5.45 station info entry is 68 bytes: a 64-byte station location, the station index, and a
**big-endian halfword join order** - the wiki calls the last two bytes padding for 5.27-5.29 and
names the join order only from 5.31. It counts JOINS and not seats: a capture taken after three
successive connections from the same machine reads 0 for the host and **3** for us, in station
index 1. That is the field naming itself.

## The RTT protocol (0x58)

The host starts timing a station the moment it is in the mesh, and there is no wiki page for this
protocol at all. A message is thirteen bytes and always thirteen:

    u8   kind        0 = request, 1 = response; anything else is dropped
    u64  timestamp   big-endian, the sender's own clock
    u32  target      big-endian, whose reply this is - and **zero is accepted by everyone**

The host broadcasts a request every ~410 ms with `target` 0. A station answers with kind 1 and the
**timestamp echoed unchanged**; the receiver's first test on the target field is `if zero, accept`,
so an answer needs no id it has not been told. What the host does with it is
`(now - echoed) / ticks per ms` into a nine-sample ring per station, whose median becomes that
station's RTT once the ring is full.

**Nothing in this protocol drops a station for staying silent.** A station that never answers simply
never gets a sample - which is worth knowing before spending a run on the theory that it does.

## The reliable sliding window (0x7c, and everything above it)

Pia 5.29-5.43 wraps a reliable message like this, and the payload of a reliable message on 0x7c is
the game's own data:

    0x0  1  flags     1 application data, 2 message start, 4 message end, 8 is initialized,
                      16 zlib, 32 reset, 64 reset ack
    0x1  1  stream id
    0x2  2  payload size, big-endian
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  number of destination bits (N)
    0x9  4 * ceil(N / 32)  destination bitmap words, big-endian
            payload

**The header is 9 or 13 bytes, not the wiki's 8 or 12** - the wiki's own field list runs through
offset 0x8, and the binary's `GetSize` is `9 + (((N + 0x1f) >> 3) & 0x3c)`. And N is refused at
**0x20 or more**, where the wiki says "may not be higher than 32". A payload of 0x5a1 or more is
refused too.

When the application-data flag is clear the payload is a bulk acknowledgement, and the 5.29-5.43
shape is not the 5.18 one the wiki gives. It is two bytes and then `n` entries of **21**:

    0x0  1   a bitfield; 0 in the only ack ever captured. Its bit 0 sets a flag on the receiver
    0x1  1   entry count, refused at 0x21 or more
    0x2  21 * n  entries: u8 stream id, u16be ack id, u16be `ack id - 1`, 16-byte ack mask

**The whole ack message, measured off a console rather than reasoned about:**

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16

No flags at all, stream 0, **sequence id 0xFFFF** - a control message carries no sequence of its own
- and the lowest id the sender is still waiting on. `ack id` is one MORE than the highest sequence
received. That is a real console's answer to two application messages, sequence 0 and 1, and
`pokeldn/ldn/reliable5.build_ack_message()` reproduces it byte for byte.

**HOW TO GET A WINDOW TO TALK, and it is the method not the answer:** four runs swept an ack against
silence - the two unread bytes, then five framings, then the reset counter - and every one of them
was judging a "no". A window that accepts APPLICATION DATA has to acknowledge it, so **send data and
read the acknowledgement**: one probe, sweeping only the sequence id, and the console hands over
every field the binary would not spell out. Sequence 0 drew nothing and sequence 1 drew the ack.

`pokeldn/ldn/reliable5.py` is the 5.29-5.43 window; `pokeldn/ldn/reliable.py` is the 6.32 one and
has a different header. Do not read one while holding the other.

## Before reverse-engineering any of this again

The reference material is searchable, and searching it is minutes against days.

    gh search code "<a constant you have>" --limit 20
    gh api repos/kinnay/NintendoClientsWiki/contents --jq '.[].name'
    gh api repos/kinnay/NintendoClientsWiki/contents/<Page>.md --jq .content | base64 -d

The wiki is a *repository*, so code search reaches inside it, and it holds per-game pages that the
summary tables do not link - `Pokemon-Brilliant-Diamond.md` states the key derivation above, while
the `Pia-Game-Keys` table lists only the derived result. Searching a 16-byte constant found the
right page in one query, after the whole scheme had been rebuilt from the binary instead.

Do the same for the game's own code: a decompiled C# dump of a Unity title may already be on GitHub
(`TeamLumi/opendpr` for BDSP), which is faster to read than IL2CPP output.

**This does not replace reading the binary.** Published values are transcriptions and can be wrong,
stale, or - as above - correct in a way that looks wrong. Read the binary to *verify* and to get
what nobody wrote down; search first so you know what you are verifying.

## Credits

The packet-header version table, the session-key derivations and the nonce layouts come from the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol). Which
derivation belongs to which network type, the `cryptoKeyDataSeed` value, and the version rule that
turns it into the published key were read out of a retail title's own code, and each of the wiki's
statements above was checked against it.
