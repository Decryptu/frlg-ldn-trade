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

## Credits

The packet-header version table comes from the
[NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki/Pia-Protocol); everything
about which derivation belongs to which network type was read out of a retail title's own code.
