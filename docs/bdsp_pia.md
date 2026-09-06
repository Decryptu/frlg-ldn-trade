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

### The seed is not the key: four bytes are overwritten

`cryptoKeyDataSeed` is not handed to Pia as it stands. The game builds the key at
base_main.bin 0x1e3f404, and the array it pins is a *modified copy*:

    n    = PiaPluginUtil.GetCryptoKeySize()
    key  = new byte[n]
    Array.Copy(setting.cryptoKeyDataSeed, key, seed.Length)
    key[1]  = (v >> 8) & 0xFF        ; each guarded by a length check,
    key[3]  = (v >> 4) & 0xFF        ; so all four land for a 16-byte key
    key[7]  = (v >> 1) & 0xFF
    key[12] = (v >> 0) & 0xFF
    cryptoSetting = { mode = Aes128 (1), pKeyData = GCHandle.AddrOfPinnedObject(key) }

`v` is one u32 read from a live object, and the four shifts take only its low sixteen bits - so
**the key is the measured seed plus a 16-bit unknown**, a space of 65,536. That the mode constant is
`PiaPlugin.CryptoSetting.Mode.Aes128 = 1` is also what the `type == 1` guard in
`LocalProtocol::SetKey` is testing.

The chain from there down is now read rather than inferred:

    IlcaNetBase (C#)  builds the key above, pins it, stores {mode, pKeyData}
      -> LocalMatchMeshLayerController::vfunc2 (0x16c40c4) refuses a setting whose +0xb8 is
         sixteen zero bytes, then passes setting+0xb4 = {u32 mode; u8 key[16]}
      -> LocalFacade's key setter (0x16ab93c)
      -> LocalProtocol::SetKey (0x16b1cb8): mode -> +0x5b8, the sixteen bytes -> +0x5bc

So the sixteen bytes at `LocalProtocol+0x5bc` are `cryptoKeyDataSeed` with bytes 1, 3, 7 and 12
replaced. Sweeping all 65,536 of them against the capture - for every session value the advertisement
carries, twenty IV layouts built from a header field and the nonce, and both plausible block-counter
origins - has not authenticated a packet. So the IV is not "a field the receiver already has,
concatenated with the header nonce", and the nonce is the last unread piece rather than the key.

## What is still missing

**The GCM nonce construction.** The IV buffer is memset to twelve zero bytes and then filled by a
virtual call - `PacketReader+0xc8`->vfunc3(buf, 12, packet) on receive, `PacketWriter+0x948` on
send. Naming that object's class is the open thread; it is not `LocalProtocol`, whose slot 3 is only
a getter.
