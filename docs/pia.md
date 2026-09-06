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

| | FireRed/LeafGreen (the GBA app) | Brilliant Diamond / Shining Pearl |
|---|---|---|
| Pia version byte | 15/16 (6.32+) | **9** (5.27-5.45) |
| header size | 0x1D | **0x20** |
| variable ids | 2 bytes each | **4 bytes each** |
| module | `pokeldn/ldn/pia_connect.py` | `pokeldn/ldn/pia5.py` |

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
