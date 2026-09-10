---
title: The wireless layer
nav_order: 2
has_children: true
---

# The wireless layer

A Nintendo Switch communicates with nearby consoles over **LDN**, Nintendo's local wireless, and
above that over Pia, Nintendo's peer-to-peer session middleware. Both belong to the console, so
an implementation carries from one title to the next. What changes per title is the Pia version and
what the game does with the payloads.

## The two secrets

| layer | secret | purpose |
|---|---|---|
| LDN | the title's LDN passphrase, 16-64 bytes | authenticates the 802.11 association |
| Pia | the title's game key, 16 bytes | derives the session key that encrypts every datagram |

In Brilliant Diamond the passphrase is an ASCII string handed straight to `nn::ldn::CreateNetwork`;
it never reaches Pia's crypto.

Known values:

| title | LDN passphrase | Pia game key |
|---|---|---|
| Brilliant Diamond / Shining Pearl | `WirelessStrongCryptoKey2021` (27 bytes, raw) | derived from `cryptoKeyDataSeed`; see [BDSP](bdsp_session.md) |
| Sword / Shield | `W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL` (64 bytes, raw) | `p1frXqxmeCZWFv0X` |

The Sword/Shield passphrase is byte-for-byte the string the NintendoClients wiki lists for
Scarlet/Violet, and differs from its Legends: Arceus row in one character (`HGhG` against `HGHG`).

## Discovery

Reading an advertisement needs only `prod.keys`. The LDN beacon payload is decrypted with console
key material, so any title's session can be seen with nothing known about the game:
`local_communication_id`, `scene_id`, version, channel, accept policy, participant count and
application data. `tools/ldn/ldn_scan.py` does this.

Association is the first step that needs a title secret. The passphrase is used verbatim, neither
padded nor hashed. `nn::pia::local::LdnBackgroundProcessJob` validates the length as 16-64 before
use.

## The advertisement's application data

Pia's LDN advertisement layout, as parsed from a Shining Pearl session:

    +0x00  4  network id                     random per session
    +0x04  4  CRC32 of the user password     0 when the room has no password
    +0x08  1  system communication version
    +0x09  1  header size                    16
    +0x0a  2  padding
    +0x0c  4  session parameter              random per session; seeds the Pia session key
    +0x10     application data

The network id and the session parameter both change per session. A key derivation tested against a
capture from a different session fails on every packet with no distinguishing symptom. Match the
advertisement and the capture before doubting the derivation.

## Channels

LDN allows 5 GHz channels 36/40/44/48 and a host may use them; the FireRed/LeafGreen application
scans 2.4 GHz only. A console re-hosting picks a new channel. Read the frequency out of the kernel
before a run:

    sudo iw dev <managed iface> scan | grep -A3 <console MAC>

## Pages

- [The Pia layer](pia.md): packet header formats by version, message framing, the transport
  protocols, and the session-key derivations.
