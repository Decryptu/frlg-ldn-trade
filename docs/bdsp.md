---
title: Brilliant Diamond and Shining Pearl
nav_order: 4
has_children: true
---

# Brilliant Diamond and Shining Pearl

The first **native** Switch title this project has spoken to, and a different shape of problem from
FireRed/LeafGreen. There is no GBA ROM and no emulator in the middle: Pia is the game's own
transport, and above it sits Unity/IL2CPP game code written by ILCA.

## Where it stands

**Proven on retail hardware.** A Linux box associates with a Shining Pearl Union Room session and is
given a seat - participant 1 of 8, with its own IP - using nothing but `prod.keys` and the title's
LDN passphrase. The console accepts it and does not drop it.

**Not yet done.** Pia's payloads are still encrypted to us. The session-key derivation has been read
out of the console's own code, but one input - the 16-byte game key - has not been located, so no
datagram has been decrypted and no Pia handshake has been completed.

## The pages

- [Joining the session](bdsp_ldn.md) - the advertisement, the passphrase, and taking a seat.
- [Pia, and the game key](bdsp_pia.md) - the packet format, the key hierarchy, and exactly what is
  still missing.

## Reading the game

Both pages lean on being able to read the title's own binary. The method is general to any Unity
Switch game and is written up separately under
[Reverse-engineering a Switch title](switch_re.md) - extracting the executable from an NSP without
unpacking it, the IL2CPP metadata that names the C# surface, and the C++ RTTI that names Pia's 279
classes.
