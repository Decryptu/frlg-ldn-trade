---
title: Pia, and the game key
parent: Brilliant Diamond and Shining Pearl
nav_order: 2
---

# BDSP: the Pia layer

What the console sends once a seat is held, what it is encrypted with, and the one input that is
still missing.

## What is on the wire

A hosting console broadcasts to `169.254.x.255:12345` at about 9 datagrams a second, every one
**176 bytes**, every one carrying Pia's magic, every one addressed to `dst_var = 0`. The constant
size across hundreds of packets says this is one fixed-shape periodic announcement rather than a
conversation.

The header is Pia 5.27-5.45 - version byte `0x89`, so encrypted, version 9 - and the layout is on
[The Pia layer](pia.md). `pokeldn/ldn/pia5.py` parses and rebuilds it; against 674 captured packets it
round-trips byte-identically.

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext

The nonce is a monotonic counter: consecutive packets differ only in its low bytes and in everything
after it.

## The session key

Read out of `nn::pia::local::LocalProtocol` - the **LDN** implementation, which is the one a Union
Room session uses:

    seed  = a u32 session value held at LocalProtocol+0x5b0
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key at LocalProtocol+0x5bc).encrypt(rnd)

That generator is **SEAD's**, Nintendo's own standard library RNG, and it is the one input here
that is not in doubt: it was read instruction by instruction off the console and then found to
match the NintendoClients wiki's published SEAD RNG exactly - the same init multiplier, the same
11/8/19 shifts, the same state rotation. `pokeldn/ldn/sead.py` holds it and
`pokeldn.ldn.pia5.ldn_session_key` is the derivation above. A failed derivation is therefore a
wrong key or a wrong nonce, never a wrong xorshift.

and that key is then installed into the transport, where a further HMAC step can re-key from it.

## The game key, measured

**`cryptoKeyDataSeed = 9918bd0f dcfa6577 9918bd0f dcfa6577`** - one eight-byte pattern, twice.

It is read off the cartridge, and it proves itself. `INL1.IlcaNetSessionSetting` is a plain
`[Serializable]` class rather than a Unity asset, so its defaults come from its **constructor**:

    IlcaNetSessionSetting..ctor
      byte[16] cryptoKeyDataSeed  <- RuntimeHelpers.InitializeArray(array, fieldHandle)
      string   wirelessCryptoKey  <- the "WirelessStrongCryptoKey2021" literal
      ulong    localCommunicationId = 0x0100000011d90000

The field handle resolves to `<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`,
and **a C# compiler names those fields after the SHA-1 of their own initial data**. So reading the
blob out of the metadata's field-default-value table and hashing it back to that name is a closed
loop: SHA-1 of the sixteen bytes above IS `33F804...7517F`. The `localCommunicationId` in the same
constructor is BDSP's, which is what says it is the right constructor.

This is why five sessions of searching missed it. An `InitializeArray` blob lives in
`global-metadata.dat`'s field-default-value section, not in code and not in an asset, so neither a
scan of the executables nor a scan of the 4.2 GB RomFS could find it.

### The published key is this seed, derived

    seed (metadata)   9918bd0f dcfa6577 9918bd0f dcfa6577
    published key     9900bd0c dcfa6563 9918bd0f c7fa6577
                        ^^   ^^         ^^         ^^        bytes 1, 3, 7, 12

Those are exactly the four bytes the game overwrites from the **local communication version**, which
for 1.3.0 is **199** - the same `app_version: 199` the advertisement carries. So the published row is
correct, and it is a *derived* value for one game version; the seed is the part that does not move.
`ldn_game_key(seed, 199)` reproduces it byte for byte.

This is worth stating plainly because it is a trap: a published key and a measured seed differ in
precisely these four positions, which reads as a corrupt transcription. Session 45 concluded exactly
that, and spent a day of exhaustive sweeps on the consequences.

## The session, decrypted

All 674 packets of the sp4 capture authenticate:

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d

## What the console is saying

With the session key in hand the payloads parse. Every one of the 674 packets carries exactly one
message, and all of them are the same thing:

    presence 0x7f  flags 0x11  size 121  protocol 36  port 0  destination 0

`parse_messages()` does the framing: Pia 5.27-6.30 messages open with a byte saying which header
fields are present, absent fields **inherit from the previous message**, each message is padded to a
multiple of four bytes, and the packet tail is 0xFF. Sizes and ids are big-endian.

Protocol 36 is the **Local Protocol**, and the message is its `0x11` *update session*, which the
host rebroadcasts every 100 ms until every station acknowledges it. Decoded:

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, and NOT the advertisement's network id
    host variable id      11bac90d        the same value as the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0                169.254.54.1:12345          the console
    node 1                169.254.54.2:12345   01     us
    nodes 2-7             empty, marked 0xff
    host migration state  0

Eight nine-byte node slots then one byte, which is the Union Room's eight seats. **That is sp3's
"participant 1 of 8" seen from inside the encrypted channel** - the seat the LDN layer granted is
visible to the game's own session protocol, holding an address the console is broadcasting to.

`pokeldn.ldn.local_protocol` parses it. The whole capture reads back as:

    674 update-session messages, sequence id 4 in EVERY ONE
    network id 0x223b4a8b   host variable id 0x11bac90d   allow participating yes
    seat 0  169.254.54.1:12345  ranking 0      the console, the oldest node
    seat 1  169.254.54.2:12345  ranking 1      us
    seats 2-7  empty, ranking 255

The sequence id never moving across 674 messages is the point: the host repeats an update session
**until every station acknowledges it**, so this is a console asking the same question 674 times
and never being answered. We are in its node table with a ranking, and we never replied.

Watch the byte order. The Pia message header around these is big-endian, the Local Protocol's own
fields are little-endian, and a local address inside them is big-endian again. All three are
wrong-able in ways that still parse.

## The send path, proven offline

Re-encrypting each captured plaintext with the derived session key and IV reproduces **the
console's own ciphertext and its tag, byte for byte, for all 674 packets**, and the parsed header
re-packs byte-identically. So the packets this project can now build are the packets the console
builds - which is the last thing that can be checked without spending a hardware run.

`pad_payload` (0xFF to a multiple of 16), `build_message`, `encrypt_payload` and `PiaHeader5.pack`
assemble one; `decrypt_payload` returns `None` rather than raising on a bad tag, because sweeping
candidates against it is a normal thing to do.

## The ack, read off the console

The console is waiting for one 20-byte message. Every field of it, and of the Pia message around it,
is now read off BDSP's own code rather than guessed - `main.bin` addresses throughout.

**The 20 bytes.** `LocalAckMessage::Serialize` at `0x016bc0f4` writes `1` at offset 0, the message
type at 1, the object's payload-size halfword at 2, six zero bytes at 4, then the sequence id at
0x0C and four zero bytes at 0x10. The constructor at `0x016bc0c8` is what settles the size field:
it does `mov w8, #0x14; str w8, [x0, #0x14]`, a WORD store that writes the 20-byte total into the
halfword at +0x14 and **zeroes the payload size at +0x16**. So an update session sets that field to
73 and an ack leaves it at 0, and the whole message is 20 bytes either way.

**The framing.** `LocalProtocol` has exactly ONE send path, `0x016af22c`, and all four of its
message types - `0x11` update session, `0x12` destroy network, `0x13` start host migration, `0x21`
ack - reach it with the same destination object and the same options struct. So an ack is framed
exactly like the update session it answers, and the capture reads that framing off the wire:
presence `0x7F`, message flags `0x11`, protocol 36, port 0, destination 0.

`0x11` is "destination is a bitmap" (`0x01`) plus "may not be bundled" (`0x10`). The bitmap is
built at `0x0159a15c`: zero four bytes, look the destination up to a station, read its station index
from `station+0x38`, and if it is below 32 set `1 << index`. A destination that resolves to no
single station leaves the bitmap at 0, which is the broadcast the console itself sends.

**Presence is 0x7F, not 0x0F.** Only bits 1/2/4/8 name a field in Pia 5.27-6.30, and the console's
message carries exactly those four fields - but it sets three more bits that name nothing. This is
the one byte this project's send path had wrong: `7f 11 0079 24 000000 00*8` on the wire against
`0f ...` from `build_message`. Everything after it already matched.

**Who an ack is attributed to.** `0x016af96c` handles a received `0x21`: it requires the protocol's
own two station ids to be valid and equal (the receiver must be the host), deserialises the ack,
checks the length, and then calls `0x016aec94` with the sender's identity. That function walks nine
node slots at `this+0x188` in steps of 0x40 and compares each with `0x0153b15c`, which is a memcmp
of **16 bytes of address at +8 plus the port halfword at +0x18**. Only if a slot matches does the
sequence id reach the "this node has acknowledged" bookkeeping.

So the ack is matched by the sender's **address**, not by its variable id and not by its constant
id. Our own Pia variable id - which the console has never been told, because we never sent a
Station Protocol connection request - therefore cannot be what decides whether the ack lands. It
still reaches the IV, as the low byte of the source variable id, so it has to be stable within a
run and it must not be zero.

**A free confirmation of all of it.** The wiki's LDN rule for a constant id is
`mac[2] << 56 | mac[4] << 48 | mac[5] << 40 | mac[3] << 32 | mac[1] << 24 | mac[0] << 16`. The
captured host constant id `0000 48f1 2022 9beb`, read as the little-endian field it is, unpacks by
that rule to `48:f1:eb:20:9b:22` - which is exactly the MAC the scan recorded for the console. The
byte order, the formula and the capture all agree, from three directions.

**What is still not read off the console** is whether a client broadcasts its ack the way the host
broadcasts the question, or unicasts it with the host's variable id in the packet header. The
protocol's destination object lives at `LocalProtocol+0x130` and its initialiser has not been
found. `bin/bdsp_ack.py` sends the phases in order and the rebroadcast either stops during one of
them or it does not.

## The ack, on hardware

Session 46 sent it. The console accepted the **first** framing tried - a broadcast to the network's
broadcast address with packet `dst_var` 0 and message destination 0, which is exactly what the host
itself sends - and stopped rebroadcasting on the spot:

    42 update sessions, ~100 ms apart, the last at t=5.969
    first ack at t=6.003
    zero packets from the console for the remaining 78 s of the capture

So a client's Local Protocol broadcasts its ack the way the host broadcasts the question; the three
unicast framings the run had queued behind it never ran. Nothing appeared on the console's screen,
and nothing should have - this is below the game.

The larger result was not the ack. That session was a **fresh** one - a different SSID, network id,
session parameter, host variable id and sequence id from the capture everything had been derived
against - and every key was built live from the advertisement. **None of the 42 packets failed to
authenticate.** The derivation is general.

## The mesh station protocol

Answering the update session is bookkeeping, and the game sees none of it. The layer a station
joins on is the **Mesh Station Protocol, 0x14**. Its receive dispatcher is `0x0154e848` - payload
byte 0, minus one, bounded at 6, through a seven-entry jump table at `0x3e6b38f` - and a connection
request lands in the deserializer at **`0x0154ebd0`**, which is worth reading in the order it
checks, because the order is what a probe can exploit:

| offset | field | what a failure does |
|---|---|---|
| | size 15..949 | drop |
| 0x0 | message type, connection result, platform id | drop |
| 0x3 | target constant id, **big-endian** u64 | compared with the console's own; **silence** |
| 0xB | target variable id, **big-endian** u32 | compared with the console's own; **silence** |
| 0xF | number of protocols | compared with the console's **own count**; error 0x11c26, **silence** |
| 0x10 | that many (id, version) pairs | version low -> result 2, high -> result 3, **both reply** |
| | station location size, big-endian u16, 0x20..0x40 | drop |
| | the location, a 32-byte ASCII token, network id, three counts, player infos, ack id | drop |

`0x0159b850` looks a protocol version up by id by walking the registered list, and **returns 0 when
it finds nothing**. So an id the console does not register has an expected version of 0, and a
version of 1 against it is always "too high" - a reply, not a drop. That makes the protocol count
measurable without knowing any of the protocols: send N pairs of `(0xFF, 1)` for each N in turn, and
the N that draws a denial is the console's own count.

The same reading confirmed three more structures in passing, each against the wiki: the station
protocol's ack is 8 bytes (`0x0154fa2c`), its denial 15 (`0x015501ec`), its disconnection response
1 (`0x0154ea60`).

`pokeldn/ldn/station_protocol.py` builds and parses these; `bin/bdsp_connect.py` runs the sweep,
acking first so that the console's silence makes any later packet unambiguously an answer.

## What the console answers

Four runs took this from "the console has never spoken to us" to "the console parses everything we
send and refuses one thing".

**The protocol count is 9, and the sweep measured it without knowing a protocol.** The count sweep
drew a connection response at N=9 and at no other N - 52 ms after the N=9 request, 1.25 s after
N=8, silence for every N below. The reply is fifteen bytes,
`020300000000000000000000000000`, with the constant-id and variable-id fields zeroed.

**The result enum is wider than the wiki's, and result 7 is the useful one.** Reading the caller of
the deserializer (`0x0154f5e8`) maps internal errors to the result byte:

| error | result | meaning |
|---|---|---|
| 0x646f | 2 | our version too low |
| 0x6470 | 3 | our version too high |
| 0xc24 | 4 | |
| 0xc25 | 1 | |
| 0x11c0f | **7** | the request parsed and every version matched; the SECOND stage refused it |
| 0x11c26 | *(none)* | the protocol count mismatch - which is why that one is silence |

So **the equality signal is a reply, not silence**. A matching version gets past the deserializer
entirely, and the refusal that follows confirms the match. Reading silence as equality would invent
a version out of a lost packet; every probe now has a definite answer and silence is retried.

**The versions, each confirmed against both neighbours** (v-1 must answer "higher" and v+1
"lower"), from a sweep of all 256 ids with nothing unanswered:

    0x14  Station      version 2      - and the wiki gives exactly 2 for 5.27-5.45
    0x18  Mesh         version 3
    0x58  RTT          version 3
    0x68  Unreliable   version 1
    0x7c  Reliable     version 3
    0x94  Session      version 1

Five of nine answer, and the other four are not missing: they are registered at **version 0**, which
this probe cannot tell from unregistered because both expect 0. The wiki gives the Local Protocol
version 0 for 5.19-5.45, so that is where they are.

**None of which is needed to build a valid request.** The parser checks that our count equals the
console's and that each of *our* entries carries the right version; it never checks that our ids are
its ids. Nine entries of `(0xFF, 0)` therefore pass the whole negotiation.

## The one thing left

A minimal well-formed request, sent four times into a freshly re-entered Union Room as the first
station-protocol packet that session had ever seen, comes back **result 7** every time. The request
is parsed end to end and accepted at the protocol level.

Result 7 is produced at exactly one instruction, `0x0154fd98`, reached when the second stage
`0x0154fcfc` has already found a station for our location and a call to `0x1548bbc` - in
`nn::pia::mesh::MeshProtocol` code - returns true for our station location's variable id. That
function reads an array of `u32` at `mesh+0x3b8` with a count at `mesh+0x98`, wants the count to be
at least 2, and returns 1 on the first entry equal to its argument.

**That reading is wrong and is recorded as wrong.** Varying the station location's variable id
across five values, including the host's own and `0x7fffffff`, returns 7 for all of them, and a
list-membership test cannot match five arbitrary values. Either those fields are not a count and an
array, or the argument is not the variable id that `0x15a3728` appears to fetch. It is also not a
station left behind by an earlier run - the fresh-session test settled that.

## The GCM nonce

The IV is built by the **stream** object, one per family, and it is the reason naming it took so
long: it is neither the Protocol nor the PacketHandler, and its RTTI name says nothing about crypto.

    nn::pia::local::LdnOutputStream::vfunc3     0x16b39c4      the LDN sender
    nn::pia::local::LocalOutputStream::vfunc3   0x16bca80
    nn::pia::lan::LanOutputStream::vfunc3       0x16a0f80
    nn::pia::nex::NexOutputStream::vfunc3       0x16eca0c

Each opens with `cmp w2, #0xb; b.hi` - the buffer must hold twelve bytes - and each takes
`(this, buf, buflen, packet)`. The sender calls it on the object at `PacketWriter+0x948` just before
encrypting; the receiver memsets twelve zero bytes and calls the same slot on `PacketReader+0xc8`.

    IV[0..3]  = u32be( crc32(ten bytes) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce, copied from packet+0x1b

so only three bytes of the CRC reach the IV. The hash at `0x1719204` is ordinary CRC32 - its
table-building fallback spells out `0xEDB88320`. The ten bytes are the **network id (little-endian) followed by the source MAC address**. Read
statically they are a u32 from the network object at +0x450 - which the joiner copies out of
advertisement +0x00, so it is the network id - followed by six bytes of a station record, which is
that station's MAC.

That last field is the whole story of why this took so long. The key, the session key and the IV
layout were all correct while every sweep failed, because the CRC was being computed over IP
addresses and ports. An exhaustive 2^40 sweep of the three CRC bytes against every possible key
found nothing, for the same reason: it was run with the wrong session parameter endianness pinned
alongside. One `gh search code` on the seed constant found the wiki page that states the input.
