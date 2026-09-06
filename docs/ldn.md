---
title: The wireless layer
nav_order: 2
has_children: true
---

# The wireless layer

Everything below the game, and the part that does not care which game it is.

A Nintendo Switch talks to other consoles over **LDN** - Nintendo's local wireless - and, above that,
over **Pia**, Nintendo's peer-to-peer session middleware. Both are the console's, not the game's, so
the work here carries from one title to the next. A Linux box that can associate with one game's LDN
session can associate with any of them; what changes above is which Pia version is speaking and what
the game does with it.

Two secrets gate the two layers, and they are not the same secret:

| layer | secret | what it does |
|---|---|---|
| LDN | the title's **LDN passphrase**, 16-64 bytes | authenticates the 802.11 association |
| Pia | the title's **game key**, 16 bytes | derives the session key that encrypts every datagram |

Confusing the two costs days. In Brilliant Diamond the passphrase is an ASCII string the game hands
straight to `nn::ldn::CreateNetwork` and it never touches Pia's crypto
([BDSP: the Pia layer](bdsp_pia.md)).

## Discovery is free

Reading an advertisement needs only `prod.keys`. No passphrase, no game key: the LDN beacon's
payload is decrypted with console key material, so any title's session can be *seen* - its
`local_communication_id`, `scene_id`, version, channel, accept policy, participant count and
application data - before anything is known about the game. `tools/ldn/ldn_scan.py` does exactly that.

Association is the first thing that needs a secret, and the passphrase is used **verbatim**: the
byte string as published, not padded and not hashed.

## The pages

- [The Pia layer](pia.md) - packet header formats by version, and the two families of session-key
  derivation.
- [JoySpot discovery](joyspot.md) - what a real Switch advertises, read off the
  air.

## Per-game work lives elsewhere

- [FireRed and LeafGreen](frlg_link.md) - a GBA ROM inside an emulator, so there is a second link
  layer above Pia: the GBA's own.
- [Brilliant Diamond and Shining Pearl](bdsp.md) - a native Switch title, so Pia is the game's own
  transport and there is nothing between it and the game logic.
