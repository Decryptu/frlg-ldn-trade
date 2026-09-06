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

The capture holds nothing else because the game never had anything else to say: we joined, held a
seat, and never spoke, so the host simply repeated its session state.

## The send path, proven offline

Re-encrypting each captured plaintext with the derived session key and IV reproduces **the
console's own ciphertext and its tag, byte for byte, for all 674 packets**, and the parsed header
re-packs byte-identically. So the packets this project can now build are the packets the console
builds - which is the last thing that can be checked without spending a hardware run.

`pad_payload` (0xFF to a multiple of 16), `build_message`, `encrypt_payload` and `PiaHeader5.pack`
assemble one; `decrypt_payload` returns `None` rather than raising on a bad tag, because sweeping
candidates against it is a normal thing to do.

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
