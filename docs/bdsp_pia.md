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

## What is still missing

**The GCM nonce construction.** With the measured key in hand the capture still does not
authenticate, and the seed is no longer a suspect: a sweep of all 2^32 session-parameter values,
against six captured packets and both twelve-byte IV layouts, produced nothing. What is read so far:

- the per-packet crypto is `nn::pia::common::Packet::Header::vfunc3` - encrypt and decrypt are two
  entries into one function, and both take a `{u32 type; void* iv; u32 ivlen; void* key; u32 keylen}`
  parameter struct built by the caller;
- the IV is **twelve bytes**, and the key is sixteen at `PacketWriter+0xc` / `PacketReader+0xc`;
- the plaintext is memset to `0xFF` and then overwritten by a shorter payload, so the tail of the
  last block is padding - which is a free known-plaintext oracle, and is what makes a 2^32 sweep
  cost minutes instead of hours;
- the eight-byte header nonce is a **monotonic 64-bit counter**, written big-endian to `header+0x1b`,
  which is what the wire always showed;
- the IV buffer is filled by a virtual call on an object held at `PacketWriter+0x948`, passed in as
  the third argument of `PacketWriter::Initialize`. Naming that object's class is the open thread.

## What was ruled out, with evidence

Recorded because each cost real time:

- **The passphrase is not the game key.** `SetWirelessCryptoKey` validates 16-64 bytes and memcpys
  the raw string into an `nn::ldn::SecurityConfig`. No truncation, hash, or fold of
  `WirelessStrongCryptoKey2021` produces a working key, because the code never performs one.
- **The HMAC derivation is the LAN one.** Every HMAC-SHA256 function belongs to
  `nn::pia::lan::LanProtocol`. Applying it to an LDN capture cannot work; roughly half of one
  session's failed attempts were structurally incapable of succeeding for this reason.
- **There is no AES-GCM import.** The game's dynamic symbol table imports SHA-256, SHA-1, MD5,
  BigNum and random bytes from `nn::crypto`, and no AES at all. Pia carries its own software AES,
  found by its S-box.
- **MD5 and SHA-1 are not the reduction.** Both are imported but every call site is in the game's
  own code, nowhere near Pia.
- **The seed is not the missing input.** Every one of the 2^32 possible session parameters was
  tried with the measured game key; none authenticates a packet. Whatever is still wrong is in the
  nonce or in what reaches `LocalProtocol+0x5bc`, not in the seed.
- **Passive decryption may be the wrong goal anyway.** This project did not solve FireRed by
  decrypting its traffic from outside; it joined and spoke the protocol, and the keys fell out. The
  seat is already held.

## A constraint worth keeping

A retail Switch joining this session knows only the advertisement, the LDN layer's own values, and
the game's key material. The key is therefore derivable from those - the problem is open, not
closed.
