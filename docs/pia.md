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

DEDUCTION, not yet confirmed on the wire: that the byte at 0x05 is a destination station index and
the halfword at 0x06 a session or protocol id. What writes them is `0x017beb74`/`0x017beb78`, which
takes the byte from its caller and the halfword from a session object. Where 5.27-5.45 spends
eleven bytes on a 4-byte destination id, a 4-byte source id, a 2-byte packet id and a footer size,
version 4 spends three - which is what an older Pia in a smaller mesh looks like.

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
