---
title: Let's Go Pikachu and Eevee
nav_order: 7
has_children: true
---

# Let's Go Pikachu and Eevee

Pokemon Let's Go Pikachu and Let's Go Eevee are native Switch titles from 2018. Pia is the game's
own transport, statically linked into `main` (269 `nn::pia` classes in the RTTI), and the game's
code sits on it in C++ with protocol-buffer messages through `gflnet3`, the same middleware Sword and
Shield use a year later.

The static reading is taken from Let's Go Pikachu 1.0.2 (`010003f003a34000`, update NSP
`v131072`, SDK 5.4.151.0). Hardware measurements are against a French Let's Go Pikachu.

Local trading and battling ask both players for a link code: three Pokemon chosen in order from a
fixed set. The sessions here use Pikachu, Pikachu, Pikachu.

## Pages

| page | contents |
|---|---|
| [The Let's Go cartridge and session](lgpe_session.md) | what the title is built from, the LDN passphrase and Pia game key, Pia header version 3, the session key, and the link code |

## What works

Confirmed on a retail Let's Go Pikachu, end to end up to the mesh: association with the 64-byte
passphrase, the session key, the version-3 Pia header, the 22-byte message framing, the full
version-9 station connection handshake, and a mesh join that makes the joiner station index 1 in
the host's mesh. The console then drives the Local Protocol, RTT, and a protocol 0x73 game layer.
`docs/lgpe_session.md`.

## Unresolved

- How the three-Pokemon link code becomes the password. Its CRC32 at application-data +4 was 0 on a
  session hosted with the code Pikachu, Pikachu, Pikachu, so the code does not reach the Pia
  password field. Where the game checks it is unread.
- The protocol 0x73 game layer above the mesh. The console streams it once the mesh forms; it is
  unread. A mesh that answers nothing on 0x73 ends with the game showing the partner-interrupted
  message.
- Holding the mesh open: the join response is now acked and the session updates answered, but
  whether that alone keeps the seat until the game layer starts is not yet measured.
