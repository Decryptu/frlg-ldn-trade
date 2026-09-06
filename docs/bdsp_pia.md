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

### The NintendoClients wiki row is wrong for this game

    measured   9918bd0f dcfa6577 9918bd0f dcfa6577
    wiki       9900bd0c dcfa6563 9918bd0f c7fa6577

Four bytes differ. The wiki value is a garbled transcription of the same underlying pattern, not a
different key and not a different version: its sixteen bytes appear **nowhere** in the game's
executables or in any of the 16,630 files of its RomFS. Treat that row as unverified.

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
table-building fallback spells out `0xEDB88320`. The ten bytes are a u32 from the network object at
+0x450 followed by six bytes of a station record; CRC32 of the obvious addresses (either MAC, either
IP, either order) is not the answer, so they are not simply address bytes.

That does not block the search. Three CRC bytes and the key's sixteen unknown bits are 2^40
together, which is exhaustive in under an hour - the first search here that covers everything still
unknown instead of a list of guesses.

## What is still missing

Whether that sweep finds the pair. If it does not, the remaining candidates are the block-counter
origin, the session parameter the seed is taken from, and the possibility that the game update
changed `cryptoKeyDataSeed` - the value here is read from the base NSP's metadata, and the console
runs 1.3.0, whose `global-metadata.dat` sits behind BKTR in the patch NCA and has not been read.
