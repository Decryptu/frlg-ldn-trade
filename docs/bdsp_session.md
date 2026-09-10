---
title: Joining and the Pia layer
parent: Brilliant Diamond and Shining Pearl
nav_order: 1
---

# Joining a BDSP session, and what is under the encryption

## The advertisement

    local_communication_id  0100000011d90000
    scene_id                4352  (0x1100) in the Union Room; 12608 (0x3140) in the Grand Underground
    version                 4
    channel                 6, band 2 (2.4 GHz)
    accept_policy           ALL
    participants            1/8
    application_data        17 bytes

The comm id is **Brilliant Diamond's title id** and the console was running Shining Pearl
(`010018e011d92000`). Paired versions advertise one shared `local_communication_id` so they can find
each other, so it does not identify which version is hosting.

Discovery costs nothing: the advertisement decrypts with `prod.keys` alone, no passphrase and no
game key. `tools/ldn/ldn_scan.py` sees the session before anything about the game is known.

The 17 bytes of application data parse against Pia's LDN advertisement layout
([The wireless layer](ldn.md)), with the CRC32 field reading 0 (the room was opened with no password)
and the header size reading 16 against a 17-byte blob, so one byte is application data.

## The passphrase

    WirelessStrongCryptoKey2021

Used raw — 27 bytes, neither padded to 32 or 64 nor hashed. The LDN layer accepts any passphrase from
16 to 64 bytes and stores the byte string with an explicit length.

It is the **LDN** passphrase and nothing more. The game hands it straight to `nn::ldn::CreateNetwork`
inside an `nn::ldn::SecurityConfig`; it never reaches Pia's own crypto.

## Taking a seat

`bin/bdsp_join.py` scans, associates and reports the participant table:

    participant 0: ip=169.254.54.1  mac=48f1eb209b22                 <- the console
    participant 1: ip=169.254.54.2  mac=58d8122149a2  name=b'PkCamp'  <- the client

The console assigns the IP and holds the seat for as long as it is held. The Union Room's eight seats
are the LDN `max_participants`, so the participant count is the room's population.

**Nothing appears on the console's screen, and that is correct.** LDN association is below the game;
a seat in the LDN session is not a seat in the Pia session.

LDN association succeeds roughly one attempt in two: `Connect failed with status code 1` with no
`authenticate` line in dmesg is the known baseline, so retry before diagnosing. The console can also
stop advertising while the player never leaves the Union Room — the screen does not change and scans
across all three channels find nothing. Leaving and re-entering the room brings it back on a new
channel, SSID and session parameter, all of which the key derivation handles live.

A receiver on the LDN interface must filter its own source IP: broadcasts loop back on the tap, and a
receiver that does not filter counts its own packet as an answer.

Unauthenticated Pia is discarded before it reaches anything that would reply. Holding the seat and
sending unencrypted Pia datagrams — header-only, header aimed at the console's variable id, and
header plus payload, to both the host and the broadcast address — drew nothing: over 70 seconds the
console sent 630 packets, every one 176 bytes and every one addressed to `dst_var = 0`, and none of
them to the sender. It did not answer, did not error and did not drop the seat.

## What is on the wire

A hosting console broadcasts to `169.254.x.255:12345` at about nine datagrams a second, every one
176 bytes, every one addressed to `dst_var = 0`:

    32ab9864 89 00000000 11bac90d 0000 00 f5a83bd383ce712d 59baa5cbc320cb56 <144 bytes>
    magic    v  dst=0    src      pid  f  nonce (a counter) tag              ciphertext

Version byte `0x89` is encrypted, version 9 — Pia 5.27–5.45. The header layout, message framing and
transport protocols are on [The Pia layer](pia.md). `pokeldn/ldn/pia5.py` round-trips 674 captured
packets byte-identically.

The reliable protocol's version 3 pins Pia to 5.31–5.43, which is narrower than the mesh protocol's
version 3 (5.30–5.45).

## The key hierarchy

    cryptoKeyDataSeed  9918bd0fdcfa65779918bd0fdcfa6577    from global-metadata.dat
    game key           9900bd0cdcfa65639918bd0fc7fa6577    = seed derived with version 199
    session param      0x36dee059                          advertisement +0x0c, little-endian
    session key        7b182cb087eeabd228a2efd91a8be147    = AES-ECB(game key) over 16 SEAD bytes
    network id         b4c85cf8                            advertisement +0x00, little-endian
    source MAC         48:f1:eb:20:9b:22
    crc32(netid||MAC)  0xda291352
    IV (first packet)  da29130df5a83bd383ce712d

All 674 packets of one capture authenticate on that. Re-encrypting each captured plaintext with the
derived key and IV reproduces the console's own ciphertext and tag, byte for byte, for all 674.

### Where the seed lives

`cryptoKeyDataSeed` is `9918bd0f dcfa6577` twice — one eight-byte pattern repeated.

`INL1.IlcaNetSessionSetting` is a plain `[Serializable]` class rather than a Unity asset, so its
defaults come from its constructor:

    IlcaNetSessionSetting..ctor
      byte[16] cryptoKeyDataSeed  <- RuntimeHelpers.InitializeArray(array, fieldHandle)
      string   wirelessCryptoKey  <- the "WirelessStrongCryptoKey2021" literal
      ulong    localCommunicationId = 0x0100000011d90000

The field handle resolves to
`<PrivateImplementationDetails>.33F804682DF9E210AABDC4D939CBCD380EC7517F`, and a C# compiler names
those fields after the SHA-1 of their own initial data — SHA-1 of the sixteen bytes above is that
name. The `localCommunicationId` in the same constructor is BDSP's, which identifies the constructor.

An `InitializeArray` blob lives in `global-metadata.dat`'s field-default-value section, not in code
and not in an asset, so neither a scan of the executables nor a scan of the 4.2 GB RomFS finds it.
The general method is on [Reverse-engineering a Switch title](switch_re.md).

### The published key is the seed, derived

    seed (metadata)   9918bd0f dcfa6577 9918bd0f dcfa6577
    published key     9900bd0c dcfa6563 9918bd0f c7fa6577
                        ^^   ^^         ^^         ^^        bytes 1, 3, 7, 12

Those four bytes are what the game overwrites from the **local communication version**, which for
1.3.0 is 199 — the `app_version: 199` the advertisement carries. `ldn_game_key(seed, 199)` reproduces
the published row byte for byte. A published key and a measured seed therefore differ in exactly
those four positions, which reads as a corrupt transcription.

### The session key

Read out of `nn::pia::local::LocalProtocol`, the LDN implementation:

    seed  = a u32 session value held at LocalProtocol+0x5b0
    state = for i in 1..4:  prev = ((prev ^ (prev >> 30)) * 0x6C078965 + i)
    rnd   = four consecutive xorshift128 draws (shifts 11, 8, 19) -> 16 bytes, little-endian
    key   = AES-128-ECB(game key at LocalProtocol+0x5bc).encrypt(rnd)

That generator is SEAD's, Nintendo's standard-library RNG. `pokeldn/ldn/sead.py` implements it and
matches the wiki's published SEAD RNG exactly — the same init multiplier, the same 11/8/19 shifts, the
same state rotation. A failed derivation is therefore a wrong key or a wrong nonce, not a wrong
xorshift.

### The GCM nonce

The IV is built by the **stream** object, one per network family — neither the Protocol nor the
PacketHandler, and its RTTI name says nothing about crypto:

    nn::pia::local::LdnOutputStream::vfunc3     0x16b39c4      the LDN sender
    nn::pia::local::LocalOutputStream::vfunc3   0x16bca80
    nn::pia::lan::LanOutputStream::vfunc3       0x16a0f80
    nn::pia::nex::NexOutputStream::vfunc3       0x16eca0c

Each opens with `cmp w2, #0xb; b.hi` — the buffer must hold twelve bytes — and takes
`(this, buf, buflen, packet)`. The sender calls it on the object at `PacketWriter+0x948` just before
encrypting; the receiver memsets twelve zero bytes and calls the same slot on `PacketReader+0xc8`.

    IV[0..3]  = u32be( crc32(ten bytes) )
    IV[3]     = overwritten with (packet.source_variable_id & 0xFF)
    IV[4..11] = the eight-byte header nonce, copied from packet+0x1b

so only three bytes of the CRC reach the IV. The hash at `0x1719204` is ordinary CRC32 (its
table-building fallback spells out `0xEDB88320`). The ten bytes are the **network id
(little-endian) followed by the source MAC address**: read statically, a u32 from the network object
at +0x450, which the joiner copies out of advertisement +0x00, followed by six bytes of a station
record.

The source MAC is the field that cannot be recovered from the packet being decrypted. An exhaustive
2^40 sweep of the three CRC bytes against every possible key found nothing because it was run with a
different input pinned wrong; one `gh search code` on the seed constant found the wiki page that
states the input.

## The Local Protocol, decoded

Every one of the 674 packets carries exactly one message, and all of them are the same:

    presence 0x7f  flags 0x11  size 121  protocol 36  port 0  destination 0

Protocol 36 is the Local Protocol and the message is its `0x11` update session, rebroadcast every
100 ms until every station acknowledges it:

    local message header  version 1, type 0x11, size 73
    sequence id           4
    network id            8b4a3b22        random, and NOT the advertisement's network id
    host variable id      11bac90d        the same value as the packet header's source variable id
    host constant id      0000 48f1 2022 9beb
    allow participating   1
    node 0                169.254.54.1:12345          the console
    node 1                169.254.54.2:12345   01     us
    nodes 2-7             empty, marked 0xff
    host migration state  0

Eight nine-byte node slots then one byte — the Union Room's eight seats, seen from inside the
encrypted channel. The sequence id never moves across 674 messages: the host is asking the same
question 674 times and never being answered.

The captured host constant id, read as the little-endian field it is, unpacks by the wiki's LDN rule
(`mac[2] << 56 | mac[4] << 48 | mac[5] << 40 | mac[3] << 32 | mac[1] << 24 | mac[0] << 16`) to
`48:f1:eb:20:9b:22`, the MAC the scan recorded.

The byte order changes three times inside one message and each is wrong-able in a way that still
parses: the Pia message header is big-endian, the Local Protocol's own fields are little-endian, and a
local address inside them is big-endian again.

### The ack

The 20-byte ack, its framing, and how the console attributes it are documented on
[The Pia layer](pia.md#the-local-protocol-0x24). The framing that works is a **broadcast** to the
network broadcast address with packet `dst_var` 0 and message destination 0, which is what the host
itself sends; the three unicast framings queued behind it in the first run never ran.

Measured: 42 update sessions about 100 ms apart, the last at t=5.969, the first ack at t=6.003, and
zero packets from the console for the remaining 78 seconds. Nothing appeared on the console's screen,
and nothing should have.

That run was a *fresh* session — a different SSID, network id, session parameter, host variable id and
sequence id from the capture everything had been derived against — and every key was built live from
the advertisement, with none of the 42 packets failing to authenticate. The derivation is general
rather than fitted to one capture.

**The message presence byte is 0x7F, not 0x0F.** Only bits 1/2/4/8 name a field in Pia 5.27–6.30 and
the console's message carries exactly those four fields, but it sets three more bits that name
nothing.

## Joining the mesh

The three handshakes and the ack rule are on [The Pia layer](pia.md#joining-a-mesh). BDSP-specific
addresses and results:

| what | where |
|---|---|
| station protocol receive dispatcher | `0x0154e848`, table `0x3e6b38f` |
| connection request deserializer | `0x0154ebd0` |
| result mapping from internal errors | `0x0154f5e8` |
| protocol version lookup by id | `0x0159b850`, returns 0 for an unregistered id |
| read a mesh message's ack id | `0x01542db8` (`size - 4`, big-endian) |
| send the ack (8 bytes, on 0x14) | `0x01550324`, `mov w3, #8` |
| join REQUEST handler, host side | `0x0154b790`, `0x0154b868` |
| join RESPONSE handler | `0x0154b984`, `0x0154b9a4` |

`0x01550324` is a method of the object at `session + 0xa0`, and that object is the
MeshStationProtocol: its field `0x120` holds the `0x2710` its constructor writes at `0x0154e614`,
where `MeshProtocol`'s constructor zeroes the same offset. The join response handler is identified by
the pointer it reads at `MeshProtocol + 0x128`, which `JoinMeshJob` stores through `0x0154e5c4`
immediately after sending the join request at `0x0155cb8c`.

The console's protocol count is **9**, measured by sweeping the count against a console that answers
only on a match; the sweep drew a connection response at N=9 and at no other N. Its nine protocols,
read off its own acceptance:

    0x14 Station v2   0x18 Mesh v3      0x1c SyncClock v0
    0x24 Local v0     0x58 RTT v3       0x68 Unreliable v1
    0x7c Reliable v3  0x94 Session v1   0xa4 MonitoringData v0

Five of the nine answer a version probe; the other four are registered at version 0, which the probe
cannot tell from unregistered because both expect 0. The wiki gives the Local Protocol version 0 for
5.19–5.45, which is where they are.

The join response for a two-station mesh:

    stations 2, host index 0, our index 1, max_active 8, update counter 0
    station 0   the console
    station 1   us - our own station location read back, with the ids we sent

`max_active` 8 is the Union Room's eight seats seen from a third layer. Within a second of the join
the console begins sending RTT (0x58) and reliable (0x7c) traffic.

**Use a fresh `--src-var` every run.** Result 7 means "this variable id is already one of my
stations"; re-using the previous run's id minutes later is refused, and changing one digit is
accepted. Leaving and re-entering the room also clears them.

## Two measurement methods worth keeping

**A check that refuses you is a measurement instrument.** The console compares the protocol count
against its own and replies only when it matches, so sweeping the count measured a number that is not
otherwise visible. An unregistered protocol id expects version 0, so a version of 1 against it is a
guaranteed verdict, and bisection then reads any protocol's version. Neither needs one of the
console's protocols to be known in advance.

**Check whether the target says yes some other way.** The equality signal here is a *reply*, not
silence — reading silence as a match would have invented a version out of a lost packet. Four runs
were spent sweeping a reliable-window ack against silence, learning nothing from any of them, because
the probe had no positive answer available; a window that accepts application data must acknowledge
it, so sending data and sweeping only the sequence id replaced the whole search.
