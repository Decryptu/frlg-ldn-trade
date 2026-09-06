---
title: "BDSP: joining the session"
parent: Brilliant Diamond and Shining Pearl
nav_order: 1
---

# BDSP: joining the session

Proven on a French Shining Pearl, 1.3.0, sitting in the Union Room (Pokemon Center 2F, the left
attendant, the plain "yes" - not the password or group options).

## What it advertises

    local_communication_id  0100000011d90000
    scene_id                4352  (0x1100)
    version                 4
    channel                 6, band 2 (2.4 GHz)
    accept_policy           ALL
    participants            1/8
    application_data        17 bytes

Two things are worth knowing before reading that.

**The comm id is Brilliant Diamond's title id**, and the console was running Shining Pearl
(`010018e011d92000`). Paired versions advertise one shared `local_communication_id` so they can find
each other, so it does not identify which version is hosting.

**Discovery costs nothing.** The advertisement is decrypted with `prod.keys` alone - no passphrase
and no game key. `tools/ldn_scan.py` sees the session before anything about the game is known.

## The application data

The 17 bytes parse against Pia's LDN advertisement layout, and two fields check the parse rather
than being taken on trust:

    +0x00  4  network id      (random per session)
    +0x04  4  CRC32 of the user password   -> 0, and the room was opened with no password
    +0x08  1  system communication version -> 8
    +0x09  1  header size                  -> 16, and the blob is 17 bytes, so 1 byte of app data
    +0x0a  2  padding
    +0x0c  4  session parameter (random per session)
    +0x10     application data

## The passphrase

    WirelessStrongCryptoKey2021

Used **raw - 27 bytes, not padded to 32 or 64**. That is the whole value; the LDN layer accepts any
passphrase from 16 to 64 bytes and stores the byte string with an explicit length.

It is the **LDN** passphrase and nothing more. The game hands it straight to
`nn::ldn::CreateNetwork` inside an `nn::ldn::SecurityConfig`, and it never reaches Pia's own crypto -
see [BDSP: the Pia layer](bdsp_pia.md).

## Taking a seat

`bin/bdsp_join.py` scans for the session, associates, and reports the participant table:

    participant 0: ip=169.254.54.1  mac=48f1eb209b22                 <- the console
    participant 1: ip=169.254.54.2  mac=58d8122149a2  name=b'PkCamp'  <- us

The console assigns the IP and leaves us in the session for as long as the seat is held. The
Union Room's eight seats are the LDN `max_participants`, so the participant count is directly the
room's population.

**Nothing appears on the console's screen, and that is correct.** LDN association is below the game;
a seat in the LDN session is not a seat in the Pia session, and the game has not seen the joiner.
Do not read the quiet screen as a failure.

## What the console ignores

`bin/bdsp_pia_probe.py` holds the seat and sends unencrypted Pia datagrams - header-only, header
aimed at the console's own variable id, and header plus payload, to both the host and the broadcast
address. In 70 seconds the console sent 630 packets, every one 176 bytes and every one addressed to
`dst_var = 0`, and **not one addressed to us**. It did not answer, did not error, and did not drop
the seat.

Unauthenticated Pia is discarded before it reaches anything that would reply.

One trap for anyone writing a receiver on this interface: our own broadcast loops back on the tap,
so a receiver that does not filter its own source address will count its own packet as an answer.
