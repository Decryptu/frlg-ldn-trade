---
title: Taking a seat in a Sword mesh
parent: Sword and Shield
nav_order: 2
---

# Pia 4, the seat, and the first application data

Everything between the radio and the game's own messages: the transport version, the
association, and the five steps that end with a retail Sword handing over its party.

## Pia here is version 4, and it decrypts

`docs/pia.md` had two bands, 6.32+ (version byte 15/16) and 5.27-5.45 (version byte 9). Sword and
Shield are **neither**: their header carries **4**, and the header is a different shape.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  a station index
    0x06  2  big-endian halfword
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, NOT truncated to 8 the way 5.27-5.45 truncates it
    0x20     ciphertext

Read out of the game's own deserializer (`0x01774730`, which requires more than 0x1f bytes and then
copies field by field), its initializer (`0x017748bc`, one 64-bit store of `0x00000004_32AB9864`)
and three validators that each check `(byte & 0x7f) == 4`. **BDSP's binary has the identical three
validators against 9**, which is what makes this a comparison rather than a guess - see
`docs/pia.md` "The version-4 header".

So neither `pia_connect.py` nor `pia5.py` parses this header as it stands. **But the header is the
whole difference.** Underneath it, version 4 is 5.27's LDN family exactly - same session key, same
IV, same message framing - which is why `pokeldn/ldn/pia4.py` is fifty lines rather than a second
stack. See "What the console says" below, and `docs/pia.md` "The version-4 header".

## Taking a seat

`bin/swsh_join.py` scans, reports and associates. It carries the passphrase above and nothing else
game-specific, because nothing else is settled: the local communication id is filled at runtime, so
the first run is a scan that writes every advertisement it sees to `scratchpad/swsh_net_facts.json`
and names the ones this project already knows.

    sudo -E ./.venv/bin/python bin/swsh_join.py --scan-only

**Point it at a screen where the console HOSTS, not at the Mystery Gift one.** A Link Trade over
local communication puts the console on the air; the Mystery Gift local screen looks like a receiver
searching, and a searching station has no advertisement to read. The comm id is per application, so
the id read off any local-wireless feature is the id the gift path uses too.

`--pw-mode` defaults to `raw` rather than to BDSP's sweep of readings, because the length here is an
instruction (`mov w2, #0x40`) rather than the length of a wiki string. If raw fails, the reading is
what to doubt last.

**A seat was taken on 2026-09-07 (sw01).** The passphrase read out of the binary associates with a
retail Sword on the first reading tried, `raw`, 64 bytes. Association is about one in two, the same
coin flip BDSP has - a `ConnectionError: Connect failed with status code 1` is a retry, not a
finding - and the console's advertisement disappears within a minute or so of the seat being
released, so the player has to re-open the trade screen between runs.

The seat is an LDN seat and the console's screen does not react to it. What reacts is the air: from
the moment we associate, the console broadcasts Pia to `169.254.x.255:12345` about ten times a
second, and the derivation below reads it.

## What the console says

`pokeldn.swsh.session_keys` turns the advertisement into the keys, and it is BDSP's derivation with
one difference - **no version substitution**, because the game key here is a literal:

    session key   = ldn_session_key(GAME_KEY, application_data[12:16] little-endian)
    IV            = crc32(application_data[0:4] || the sender's MAC)[0:3] || source id || nonce
    tag           = sixteen bytes, checked in full

FACT, sw01: **484 of 484 packets authenticated**, source id 0 on every one. The session parameter
and the network id both move per session - a run against the wrong session's advertisement fails on
every packet, which is exactly what happened here for an hour before the two were matched up.

The payload is 5.27's presence-flagged message framing plus one field: a **24-byte** message header
rather than 16, body `size` bytes big-endian at offset 2, padded to a multiple of four, 0xFF to the
end of the packet. That arithmetic accounts for every payload in the capture exactly.

What it is saying, ten times a second, is a station announcement that already contains us:

    a9fe0e01 3039 ... 00      169.254.14.1:12345   station 0, the console
    a9fe0e02 3039 ... 01      169.254.14.2:12345   station 1, the seat we took

so the console has put our station in its own mesh table before anything of ours has spoken Pia.
`pokeldn.ldn.pia4` parses and builds the header; `tests/test_pia4.py` holds two of the packets as a
golden vector, and a sixteen-byte tag makes them impossible to satisfy by accident.

## Answering it, and the console going quiet

FACT, sw02/sw03 (session 56). The console's announcement is **Pia's Local Protocol, protocol 0x24,
the same one BDSP speaks** - `pokeldn.ldn.local_protocol` reads Sword's field for field with no
change: version 1, message type 0x11, 0x30 fixed bytes, eight nine-byte seats, then the
host-migration byte. Seat 0 is the console at ranking 0 and seat 1 is us at ranking 1, and
`allow_participating` is true. Sword's Pia agrees with BDSP's on the protocol numbers too, read off
the `GetProtocolId` vfuncs rather than the wire: `0x017c8460` returns 0x14 (MeshStationProtocol) and
`0x017c4280` returns 0x18 (MeshProtocol).

A host repeats that update session until every station acknowledges it, so the 0x21 ack is the
cheapest possible first packet out: the pass signal is the rebroadcast STOPPING, and it needs
nothing on the console's screen and nothing above Pia.

    sw02   ack seq 2, the sequence the console sent    44 update sessions, then its last one
                                                       13 ms after our first ack, then SILENCE
                                                       for the remaining 26 s
    sw03   ack seq 3, a sequence it never sent         261 update sessions, 148 acks, never stopped

One run would have proved nothing - a console that stops advertising on its own looks identical.
The control is what makes sw02 a measurement: the two runs differ in one field of one message, and
that field is inside the encrypted payload, so the console decrypted our packet, walked the message
header, dispatched on protocol 0x24 and compared the sequence id. `bin/swsh_connect.py`,
`--seq-delta` is the control.

The station byte at header 0x05 and the IV's source-id byte were both 0, mirroring the console's
own; `--station-sweep` walks other readings if one is ever needed. What we send is built by
`pia4.build_message` / `pia4.build_packet`, and `tests/test_pia4.py` checks it against the console's
own bytes: given the console's values it reproduces the console's 24-byte header exactly.

## The game layer, and the first application data

FACT, sw52 and the binary. Every layer beneath the game is closed in both directions - LDN
association, Local Protocol 0x24, the station handshake 0x14, the mesh join 0x18, RTT 0x58, the
reliable window 0x7C and the broadcast reliable window 0x80. Over 120 seconds the console sent
**455 application messages carrying one distinct payload**, six bytes, sequence ids 1..233:

    61 00 00 00 0a 00

That is a heartbeat, and the game is waiting for something we have never sent. **Nothing of ours
has ever been application data on either window**, and both of them are waiting for our sequence 1:

- **0x80 says so out loud.** Its ack asks for ack id 1 in every filled slot, once a second, in sw29
  and sw52 alike - 256 messages, never moving. A window that has received nothing.
- **0x7C says so by its silence.** The console has never sent us an ack on 0x7C, not one in 2092
  messages, because that protocol only answers application data and we had only ever acked.

`bin/swsh_connect.py --send-data HEX` is the first application data of the project, on either
protocol (`--send-protocol`), retransmitting until it is acknowledged the way a window does. What
it builds is `reliable4.build_data_message`, and the offline proof is that it reproduces the
console's own sequence 1 byte for byte. `docs/pia.md` "Version 4's reliable header" has the five
checks the receive path applies in silence; `scratchpad/sw_validate_msg.py` runs the exact bytes we
are about to send through all five before an association is spent on them.

**THE PASS SIGNAL IS DIFFERENT ON EACH PROTOCOL AND NEITHER NEEDS THE GAME TO AGREE WITH US.** On
0x80 the ack id moves off 1 for the first time; on 0x7C the console sends an ack at all. Either
says the console decrypted our packet, walked the message, found itself in the destination list and
accepted a sequence into its window - and a game that then keeps sending the same six bytes is a
finding about the game rather than the transport.

## Answering it: five steps, and the game hands over its party

FACT, sw68 and sw70, with sw69 as the control. Answer the heartbeat and the game walks its own
state machine, and **none of the message ids below is guessed**: `main` ships a `FileDescriptorProto`
for every P2P message set and `scratchpad/swsh_proto.py` extracts all 78 of them. The six bytes the
console repeated for 2092 messages are a four-byte little-endian message id and a protobuf body:

    61 00 00 00  = message 97     gflnet.p2p.sync.ping.pb.SyncPingDataHolder
        0a 00        field 1  ping {}
        12 00        field 2  pingReply {}
        1a 00        field 3  pingSynced {}
    60 ea 00 00  = message 60000  gflnet.p2p.block.pb.BlockDataHolder
        0a 00        field 1  result {}          Result { bool isBlocking }
        12 02 08 01  field 2  imReady { isReady: true }

It was pinging us. The five steps, all reproduced twice:

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack EVERY reliable window      0x7C, 0x18 port 1, 0x80 - one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror must be PER PROTOCOL
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84

**ONE MESSAGE IS NOT A STREAM.** sw61 sent a single message, saw `pingReply` once and watched the
game fall back to pinging; sw64 sent 400, all acked, and the game stayed in the new state. And the
bytes matter in the other direction too: sw62 sent `pingReply` FIRST, before the console had asked
for it, and the heartbeat stopped after ten messages with nothing else all run.

**STEP 3 IS NAMED BY A CONTROL RUN, WHICH IS THE ONLY REASON IT IS IN THE LIST.** sw69 did
everything sw68 did and got no 0x84 at all. The one difference was what we answered on 0x7C: the
mirror kept a single "what it last said" across all protocols, so once the console spoke on 0x80
the 0x7C mirror echoed `imReady` back on 0x7C instead of `result{}`. Made per protocol, sw70
answered `result{}` again and the transfer came back.
