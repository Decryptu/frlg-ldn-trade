---
title: The cartridge and the session
parent: Sword and Shield
nav_order: 1
---

# The cartridge, its keys, and taking a seat

## What the title is built from

Sword and Shield statically link the whole of Pia into `main` (252 `nn::pia` classes and 2036
virtual methods out of the binary's RTTI) and import `nn::ldn` from nnSdk. The stack is LDN, Pia
above it, and the game's own layer on top.

Above Pia the game uses protocol buffers. `main` carries the
`FileDescriptorProto` for every P2P message set it uses: `gflnet.p2p.framework.pb`,
`gflnet.p2p.block.pb`, `gflnet.p2p.sync.pb`, and one package per content (trade, battle, camp, raid).
`scratchpad/swsh_proto.py` extracts all 78 of them.

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes, used raw. The game calls Pia's `nn::pia::local::LdnCreateSessionSetting` passphrase setter
with a literal length of `0x40` and a rodata pointer:

    0x006c3eb4  adrp x1, #0x203f000        ; the 64-byte literal
    0x006c3eb8  add  x1, x1, #0xf04
    0x006c3ec0  add  x0, sp, #0x10         ; the LdnCreateSessionSetting
    0x006c3ec4  mov  w2, #0x40             ; 64, not a NUL-terminated length
    0x006c3ec8  bl   #0x1790450

The binary holds two identical copies (`0x203ff04` and `0x203ff45`).

The NintendoClients wiki's LDN passphrases page has no Sword/Shield row. This string is byte-for-byte
the one that page gives for Scarlet/Violet, and differs from its Legends: Arceus row in one character
(`HGhG` here, `HGHG` there).

### Where the passphrase goes

`nn::pia::local::LdnCreateNetworkJob`'s object keeps the passphrase at **+0xC4** and its length at
**+0x104**, and builds the `nn::ldn::SecurityConfig` from them immediately before calling
`nn::ldn::CreateNetwork`:

    0x01797280  add  x1, x19, #0xc4        ; the passphrase
    0x01797284  ldrb w2, [x19, #0x104]     ; its length
    0x01797284  bl   memcpy                ; -> SecurityConfig +4
    0x017972bc  bl   nn::ldn::CreateNetwork

The same object holds the `NetworkConfig`'s intent at +0xB8 (the local communication id, a u64) and
+0xC0. `nn::pia::local::LdnBackgroundProcessJob` validates the passphrase length as 16..64 before any
of this runs.

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0x01c3dc87`, referenced from three call sites and used unchanged, with no
version substitution. The site at `0x006ca91c`:

    0x006ca914  mov  w8, #1 ; str w8, [sp, #0x18]     crypto enabled
    0x006ca91c  adrp x8, #0x1c3d000 ; add x8, x8, #0xc87
    0x006ca924  ldp  x9, x8, [x8]                     the 16 bytes, raw ASCII
    0x006ca938  stur x9, [sp, #0x1c]                  -> the setting's key field
    0x006ca93c  bl   #0x183fd10                       create/join, with the setting

The value matches the wiki's Pokemon Sword/Shield row.

## Reading the cartridge

The XCI is 13.3 GB and nothing is unpacked. `tools/switch/xci_read.py` walks the HFS0 partitions and
decrypts each NCA header in place:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program
    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca 87e41bc8 --exefs 0 --extract main

then `nso_read.py` decompresses `main` (text 0..0x1900fc0, rodata to 0x24da168, data to 0x2635f38)
and `rtti_names.py` names the middleware:

    ./.venv/bin/python tools/switch/nso_read.py main
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0x1900fc0 --rodata 0x1901000:0x24da168

The method, including the traps, is on [Reverse-engineering a Switch title](switch_re.md).

### Message archives

`/bin/message/<Language>/common/*.dat` in the base game's RomFS are the Gen 6/7/8 message container.
`scratchpad/gfl_text.py` decodes one and `scratchpad/swsh_find_text.py <substring>` walks the base
RomFS in place and greps every decoded archive.

The container's key: every line ends in a `0x0000` terminator, so rotating the last ciphertext
halfword back by three per character gives that line's starting key. The values across lines are
`0x7C89 + line * 0x2983`, rotating left by 3 within a line.

The `.tbl` beside each `.dat` is an `AHTB` index and entry *i* is line *i*; a `strings` dump of the
archive is not in line order.

## Pia 4

Sword/Shield's Pia header carries version 4, a different header shape from the two bands
[The Pia layer](pia.md) documents for the other titles. Below the header, version 4 is 5.27's LDN
family: the same session key, the same IV and the same message framing with one extra field.
`pokeldn/ldn/pia4.py` implements the header; `pia_connect.py` (6.32+) and `pia5.py` (5.27-5.45) do
not parse it.

### The session key

`pokeldn.swsh.session_keys` is BDSP's derivation with no version substitution:

    session key   = ldn_session_key(GAME_KEY, application_data[12:16] little-endian)
    IV            = crc32(application_data[0:4] || the sender's MAC)[0:3] || source id || nonce
    tag           = sixteen bytes, checked in full

Measured: 484 of 484 of a retail Sword's packets authenticated, source id 0 on every one.

The session parameter and the network id both change per session, so a derivation run against a
different session's advertisement fails on every packet.

A second path exists in the binary: `0x0179bff0` -> `0x01774f40` computes a seed as AES-GCM over the
session's own two 64-bit values, keyed by them. For a console hosting a local trade the
advertisement is sufficient.

## Taking a seat

`bin/swsh_join.py` scans, reports and associates. It carries the passphrase; the local communication
id is filled at runtime:

    sudo -E ./.venv/bin/python bin/swsh_join.py --scan-only

writes every advertisement seen to `scratchpad/swsh_net_facts.json`.

Point the scan at a screen where the console hosts: a Link Trade over local communication or the
Mystery Gift local-wireless screen. The comm id is per application, so the id read off any
local-wireless feature is the id the gift path uses.

`--pw-mode` defaults to `raw`; the length is the instruction's `mov w2, #0x40`.

The advertisement reports local communication id `0x0100ABF008968000` (Sword's), version 4, scene
60001, app version 7. The Mystery Gift local-wireless screen advertises the same comm id and version
under scene id 65535.

The 384 bytes of application data open with the Pia header the wiki records for system communication
version 5, and the game's own data starts at 0x18:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password; 0 on both scenes, so neither is password-gated
    0x08  1  system communication version, 5
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param, random per session
    0x10  8  zero
    0x18     the game's application data

Association succeeds about one attempt in two; `ConnectionError: Connect failed with status code 1`
is a retry. The console's advertisement disappears within about a minute of a seat being released;
the player re-opens the trade screen between runs.

`Connect failed with status code 1` with no auth frame in dmesg is cfg80211 refusing a BSS it has
never seen: the LDN scan reads beacons in monitor mode, CONNECT needs the kernel's own table, and the
console re-hosts under a new SSID whenever the player re-enters the search.
`scratchpad/run_swsh_retry.sh <tag> <tries> [flags]` primes the table with an `iw scan` and retries.
Use `--dwell 2.5`; a lower dwell finds nothing where `tools/ldn/ldn_scan.py --dwell 2.0` finds the
console in the same minute.

Nothing appears on the console's screen. From the moment of association the console broadcasts Pia
to `169.254.x.255:12345` about ten times a second.

## What the console says first

The console's broadcast is Pia's Local Protocol, protocol 0x24, the same one BDSP speaks, read field
for field by `pokeldn.ldn.local_protocol`: version 1, message type 0x11, 0x30 fixed bytes, eight
nine-byte seats, then the host-migration byte. Seat 0 is the console at ranking 0, seat 1 is the
joiner at ranking 1, and `allow_participating` is true: the console puts the new station in its own
mesh table before the joiner has spoken Pia.

    a9fe0e01 3039 ... 00      169.254.14.1:12345   station 0, the console
    a9fe0e02 3039 ... 01      169.254.14.2:12345   station 1, the seat

A host repeats an update session until every station acknowledges it; the pass signal for the 0x21
ack is the rebroadcast stopping. With the sequence id as the only variable: acking the sequence the
console sent stopped its rebroadcast 13 ms later for the remaining 26 seconds; acking a sequence it
never sent left it sending 261 update sessions and 148 acks. The field is inside the encrypted
payload, so the console decrypted the packet, walked the message header, dispatched on protocol 0x24
and compared the sequence id. `bin/swsh_connect.py --seq-delta` is the control.

The station byte at header 0x05 and the IV's source-id byte were both 0, mirroring the console's own;
`--station-sweep` walks other readings.

## Reaching the game layer

Every layer beneath the game works in both directions: LDN association, Local Protocol 0x24, the
station handshake 0x14, the mesh join 0x18, RTT 0x58, the reliable window 0x7C and the broadcast
reliable window 0x80. All are documented on [The Pia layer](pia.md).

With the transport up and nothing sent above it, the console repeats one six-byte application
payload, `61 00 00 00 0a 00`: 455 messages over 120 seconds with sequence ids 1..233. Both windows
wait for sequence 1: protocol 0x80 asks for ack id 1 in every filled slot once a second, and 0x7C is
silent because that protocol only answers application data.

`bin/swsh_connect.py --send-data HEX --send-protocol 0x7c` sends application data.
`reliable4.build_data_message` builds it and reproduces a console's own sequence 1 byte for byte;
`scratchpad/sw_validate_msg.py` runs the exact bytes through the five checks the receive path applies
in silence (listed under [Version 4's reliable header](pia.md#version-4)) before an association is
spent on them.

Pass signal per protocol: on 0x80 the ack id moves off 1; on 0x7C the console sends an ack at all.

## The ping handshake

The six repeated bytes are a four-byte little-endian message id and a protobuf body:

    61 00 00 00  = message 97     gflnet.p2p.sync.ping.pb.SyncPingDataHolder
        0a 00        field 1  ping {}
        12 00        field 2  pingReply {}
        1a 00        field 3  pingSynced {}
    60 ea 00 00  = message 60000  gflnet.p2p.block.pb.BlockDataHolder
        0a 00        field 1  result {}          Result { bool isBlocking }
        12 02 08 01  field 2  imReady { isReady: true }

Answering it walks the game through its own state machine in five steps, each reproduced twice:

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack EVERY reliable window      0x7C, 0x18 port 1, 0x80 - one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror must be PER PROTOCOL
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84

Constraints, measured with one variable each:

- A single message drew one `pingReply` and the game fell back to pinging; 400 messages, all acked,
  held the new state.
- Sending `pingReply` before the console had asked for it stopped the heartbeat after ten messages
  with nothing else all run.
- The mirror is per protocol. One "what it last said" across all protocols echoed `imReady` back on
  0x7C instead of `result{}` once the console spoke on 0x80, and no 0x84 transfer followed.

Across a whole such run a console sent five distinct application payloads and no others:

    0x7C  id 97     0a00        ping            x20
    0x7C  id 97     1200        pingReply        x2
    0x7C  id 97     1a00        pingSynced       x3
    0x7C  id 60000  0a00        result{}         x2
    0x80  id 60000  12020801    imReady{true}    x2

`bin/swsh_connect.py --sync-answers` answers `trade.SYNC_ANSWERS` where it has a rule, keeps the
proven per-protocol echo everywhere else, and prints every distinct payload it has no rule for.

## Operational notes

- Never pass `--verbose` to a live run. Its synchronous per-packet logging runs inside the
  frame-timed loop, floods the reliable window and the console deauthenticates. Use `--capture FILE`.
- `kill -9` as the normal user does not kill a client running under `sudo`, and a hard-killed run
  leaves the `ldnclient` vif behind, after which every attempt fails in a way that reads like the
  console refusing the connection. `./scratchpad/kill_swsh.sh` must report clean before any launch
  and must leave the base interface down: an interface that is up holds the radio's channel and the
  next scan fails with `Errno 16 Device or resource busy`.
- Launch through `scratchpad/run_swsh_retry.sh`, which reads the console's real channel from a kernel
  scan; the console has moved between channels 1 and 6 three times in one session.
- The launcher prints the answer before the "no rule" line for the same received payload, so a `.out`
  file reads as if a transmission preceded the reception that caused it. Read the ownerId, not the
  order.
