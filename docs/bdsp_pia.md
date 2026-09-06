---
title: "BDSP: the Pia layer"
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

    seed  = a session value held by LocalProtocol
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key).encrypt(rnd)

and that key is then installed into the transport, where a further HMAC step can re-key from it.

## What is missing

**The 16-byte game key.** It is held at `LocalProtocol+0x5bc` and handed in by
`nn::pia::local::LocalMatchMeshLayerController` from its setting object, guarded by a check that it
is not sixteen zero bytes. It is **not** derived from the LDN passphrase - that string's only
destination is `nn::ldn::CreateNetwork` - and it is not a literal anywhere in the executable or in
the IL2CPP metadata.

The most likely home is a Unity asset in romfs: the game's own settings class,
`INL1.IlcaNetSessionSetting`, has a `[Serializable]` field named **`cryptoKeyDataSeed`** of type
`byte[]`, sitting immediately beside its `wirelessCryptoKey` string. `[Serializable]` Unity fields
are configured from assets, not code, which is exactly why no literal key appears in the binary.

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
- **Passive decryption may be the wrong goal anyway.** This project did not solve FireRed by
  decrypting its traffic from outside; it joined and spoke the protocol, and the keys fell out. The
  seat is already held.

## A constraint worth keeping

A retail Switch joining this session knows only the advertisement, the LDN layer's own values, and
the game's key material. The key is therefore derivable from those - the problem is open, not
closed.
