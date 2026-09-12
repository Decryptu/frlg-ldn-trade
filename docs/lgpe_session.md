---
title: The Let's Go cartridge and session
parent: Let's Go Pikachu and Eevee
nav_order: 1
---

# The cartridge, its keys, and the session

Addresses are offsets into Let's Go Pikachu 1.0.2's decompressed `main` as `tools/switch/nso_read.py`
lays it out: text `0..0xd32ba8`, rodata from `0xd33000`, data from `0x1527000`.

## What the title is built from

The update NSP carries the Program NCA `2b7730a9e56498bbafac2002d4908c6b` (title `010003f003a34000`,
rights id `010003f003a348000000000000000007`, key generation 6). Its exefs holds `main` (13.0 MB
compressed), `rtld`, `sdk`, `subsdk0` and `subsdk1`. Every `nn::pia` and `gflnet3` reference is in
`main`; the three sdk modules carry none.

    ./.venv/bin/python tools/switch/xci_read.py "<the .nsp>" --keys prod.keys \
        --nca 2b7730a9e56498bbafac2002d4908c6b --exefs 0 --extract main
    ./.venv/bin/python tools/switch/nso_read.py main main.bin
    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0xd32ba8

Pia is statically linked: 269 `nn::pia` classes and 2112 named virtual methods. The `nn::pia::local`
namespace carries both the `Ldn*` and the `Local*` class families (`LdnCreateNetworkJob`,
`LdnCreateSessionSetting`, `LdnJoinSessionSetting`, `LocalProtocol`). `nn::ldn` is imported from
nnSdk: `CreateNetwork`, `Connect`, `Scan`, `SetAdvertiseData`, `GetSecurityParameter` and the
`*Private` variants all have GOT slots at `0x15fa1e0..0x15fa2a8`.

Above Pia the game uses protocol buffers through `gflnet3`: the build paths name
`lib/gflnet3/external/include/google/protobuf/`.

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

64 bytes at `0xf73a50`, used raw, byte for byte the passphrase Sword and Shield use. Two call sites
hand it to Pia with a literal length of `0x40`: the create-session setting at `0x4db6c8` and the
join-session setting at `0x4dbbbc`.

    0x004db6b4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004db6c4  mov  w2, #0x40
    0x004db6c8  bl   #0x5c0fb0              LdnCreateSessionSetting passphrase setter

    0x004dbba4  adrp x1, #0xf73000 ; add x1, x1, #0xa50
    0x004dbbb0  mov  w2, #0x40
    0x004dbbbc  bl   #0x5c1280              LdnJoinSessionSetting passphrase setter

`nn::pia::local::LdnCreateNetworkJob` keeps the passphrase at +0xC4 and its length at +0x104, and
builds the `nn::ldn::SecurityConfig` from them before `nn::ldn::CreateNetwork` (`0x5ce988`, through
the PLT stub at `0xd31c78`). The job's constructor is `0x5ce640`; the same offsets Sword's job uses.

## The Pia game key

    p1frXqxmeCZWFv0X

Sixteen ASCII bytes at `0xefd659`, the key the wiki lists for Sword/Shield, Legends: Arceus and
Scarlet/Violet. One call site, `0x11a374`, loads it with a single `ldp` and stores it into a crypto
setting with an enabled flag, conditional on a mode field:

    0x0011a364  ldr  w9, [x19, #0x98]
    0x0011a368  orr  w9, w9, #2 ; cmp w9, #2 ; b.ne   (mode 0 or 2 takes the key)
    0x0011a374  adrp x9, #0xefd000 ; add x9, x9, #0x659
    0x0011a380  ldp  x10, x9, [x9]
    0x0011a384  stp  x10, x9, [x8]          x8 = setting + 0x24c

No version substitution: the key is the literal.

## The Pia header

Version 3, which the NintendoClients wiki places at Pia 5.11-5.17. The header initializer at
`0xd122d4` writes magic and version as one 64-bit store, `0x00000003_32AB9864`; the validator at
`0xd12400` checks the magic and `(byte & 0x7f) == 3`.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 3
    0x05  1  connection id
    0x06  2  packet id
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, not truncated
    0x20     ciphertext

The layout is the wiki's 5.11-5.21 table, the one Sword's version 4 uses; only the version byte
differs. `pokeldn/ldn/pia4.py` implements it.

## The message framing

Pia 5.11-5.12: a fixed 22-byte message header, not the presence-flagged one of 5.18 and later.
`nn::pia::transport::ProtocolMessageAccessor::Header`'s deserializer at `0x5ae870` refuses fewer
than `0x16` bytes and copies field by field; the writer at `0x5aeb00` stores a literal 1 at byte 1.

    0x00  1  message flags: 1 = destination is a bitmap, 2 = relay needed, 4 = relayed, 8 = unbundled
    0x01  1  version, always 1
    0x02  2  payload size, big-endian
    0x04  1  protocol type
    0x05  1  protocol port
    0x06  8  destination, big-endian: a constant id, or a station bitmap when flag 1 is set
    0x0E  8  source constant id, big-endian
    0x16     payload, then padding to a multiple of 4

`pokeldn/ldn/pia3.py` implements it over pia4's header.

## The session key

`LocalProtocol`'s derivation at `0x5cd560` is the one BDSP and Sword use: seed a SEAD xorshift128
from one 32-bit value (`0x57cfc0`, the recurrence around `0x6C078965`), take four draws into sixteen
bytes, AES-128-ECB them under the game key kept at `LocalProtocol+0x49c` (enabled flag at +0x498).
`pokeldn.ldn.pia5.ldn_session_key` implements it.

The advertisement's application data for Pia 5.9-5.18 opens with a 24-byte header:

    0x00  4  network id, random per session
    0x04  4  CRC32 of the user password
    0x08  1  system communication version, 4 for 5.11-5.17
    0x09  1  header size, 0x18
    0x0A  2  padding
    0x0C  4  session param
    0x10  8  zero
    0x18     the game's application data

The seed is the session param at application-data +0x0C. A Let's Go Pikachu host broadcast 392
datagrams while a seat was held in its session; every one authenticated under
`ldn_session_key(game key, session param)` with the version-3 header and the pia4 IV (three bytes of
`crc32(network id little-endian || the host MAC)`, a source-id byte of 0, the eight-byte header
nonce). Header version 3, tag sixteen bytes, not truncated.

## The Local Protocol, measured

The console broadcasts its session state on Pia protocol 0x24 (Local Protocol, 36), port 0, the same
protocol BDSP and Sword carry it on. The message is the wiki's 5.7-5.45 update-session message, and
`pokeldn.ldn.local_protocol.parse_update_session` reads it without change: a 12-byte local header
(version 1, type 0x11), a sequence id, the random local network id, the host variable id, service
variable id and constant id, an allow-participating byte, and a list of eight local nodes, each an
IPv4 address, a port and a host-migration ranking. The held session read back host
`169.254.105.1` ranking 0 and the joiner `169.254.105.2` ranking 1, the rest empty at ranking 255.

The host constant id in the Local Protocol body is `000048f120229beb`, little-endian, which is
`station_protocol.ldn_constant_id` over the host MAC `48:f1:eb:20:9b:22`. The same id rides the Pia
message header as the big-endian source `eb9b2220f1480000`. The two fields carry the same value in
opposite byte orders, as they do on Sword.

## The station protocol, for a mesh join

Reaching the game means joining the mesh: a connection request on protocol 0x14, then a mesh join on
protocol 0x18. The connection-request handler at `0x5b8800` reads the wiki's 5.10-5.18 layout,
station-protocol version number 9:

    [0]     message type            1
    [1]     connection id
    [2]     version number          must be 9 (`cmp w8, #9` at 0x5b8848; 5.27-5.45 checks a platform)
    [3]     is inverse connection request; rejected above 1
    [4]     target constant id      big-endian u64, compared against the console's own at 0x5b6830
    [0xC]   target variable id      big-endian u32, checked only when [3] is 1 (0x5b6840)
    [0x10]  inverse connection id   compared against the station's own record at +0xA0
    [0x11]  station location        the 5.11-5.45 layout, unchanged from Sword
    [...]   ack id                  u32, the message size minus four

This is neither Sword's version-4 request (a platform byte at [2], a shift flag at [3]) nor the
repo's 5.29-5.45 module (a protocol list at [1]). It is the classic station protocol with a version
byte, so a version-4 or a 5.29 request sent here lands every field in the wrong place. The target
constant id is the console's own, derived from its MAC; the joiner's own location carries the
joiner's constant id, variable id and service variable id.

The handshake, measured on a retail Let's Go Pikachu, completes the full version-9 sequence (the
inverse connection request the 5.27 simplification later removed):

    ->  our connection request (type 1, is_inverse 0, target the host constant id, our location)
    <-  the host's type-5 ack, then its inverse connection request (type 1, is_inverse 1),
        addressed to our constant id and the variable id we sent, carrying its own location and a
        trailing ack id
    ->  our type-5 ack of that ack id, then our connection response (type 2, result 0, the host's
        constant id at [5] and variable id at [0xD], gate byte 1 at [0x37], padded to 0x38)
    <-  the host's connection response (type 2, result 0, 840 bytes, platform 4, carrying our ids,
        a network id and one player info), which it repeats until we ack it
    ->  our type-5 ack of that response

The connection-response parser at `0x5b9270` reads `[1]` the result, `[5]` a big-endian u64 against
its own constant id, `[0xD]` a big-endian u32 against its own variable id, and `[0x37]` a gate byte
the result-0 path drops when 5 or more. `station9.build_connection_response` writes exactly those.

### The connection response a station sends

A Let's Go station answers a connection request with 0x348 bytes, not the 0x3C the station protocol
needs to be accepted. The body carries the network the station joined and who is playing:

    0x00  1  message type 2
    0x01  1  result
    0x02  1  version 9
    0x03  1  platform 4
    0x05  8  the receiver's constant id, big-endian
    0x0D  4  the receiver's variable id, big-endian
    0x31  4  the network id, big-endian: the advertise data's first u32, read little-endian
    0x35  2  01 01
    0x37  0xC3  a PlayerInfo: the station name "username", then the Switch profile's nickname,
             then the language. Its first byte is the gate the parser drops when 5 or more
    0x344 4  the ack id

A retail Let's Go Pikachu sends the same layout with its own profile name. The PlayerInfo is the
same 195-byte structure `station_protocol.player_info` builds.

A Let's Go joiner's station location, in the connection request, leaves the public address empty
(two bytes, a port of zero) and sends zero for the NAT flags and the NAT location, which makes it
36 bytes rather than 40. `station_location(..., public=False, nat_flags=0, nat_location=0)`.
`station9.build_connection_response(..., network_id=N, player_name=B)` builds it, and
`bin/lgpe_join.py --player-name NAME` sends it (`--short-response` sends the 0x3C body instead).

## Joining the mesh

With the station connected, a mesh join request on protocol 0x18 (`mesh_protocol.build_join_request`,
type 1, local station index 253, a trailing ack id) draws the host's join response: type 2, 148
bytes, two stations, host index 0, joining index 1, one fragment, two station infos, max active 2,
max total 8, carrying both stations' locations. The host then broadcasts an update mesh (type 0x20,
524 bytes, update counter 1). The join response is acknowledged with a type-5 ack on protocol 0x14,
not with a mesh message (`mesh_protocol.ack_for`). The joiner is then station index 1 in the mesh.

Once in the mesh the host streams its Local Protocol update-session (0x24, acked with a 0x21), RTT
requests (0x58), the Sync Clock Protocol (0x1C) and the Pia Clone Protocol (0x73). A real joiner
answers every one of them and sends its own RTT and sync clock requests from the moment it is
seated.

## The RTT Protocol (0x58), version 3

Sixteen bytes, as Sword's, but the kind is a big-endian u32 at [0] rather than a byte, and the
timestamp is the sender's own system tick at 19.2 MHz in a u64 at [8]. A response copies the
timestamp and sets the kind to 1. Each station sends its own requests about once a second and
answers the other's.

    00000000 00000000 0000000049845557     request
    00000001 00000000 0000000049845557     the answer to it

`rtt_protocol.build_v3` and `response_for_v3`; `bin/lgpe_join.py --connect` runs both directions
(`--no-rtt` turns them off).

## The Sync Clock Protocol (0x1C)

The mesh carries a monotonic clock the host controls, and every station keeps its own estimate of
it (wiki Sync-Clock-Protocol). A station sends a request every two seconds and the host replies;
the station halves the round trip and adds it to the value it was given.

    request, 16 bytes   [0] u64 the sender's system tick (19.2 MHz), [8] u64 zero
    reply,   16 bytes   [0] u64 the tick copied back, [8] u64 the mesh clock in milliseconds

A joiner sends its first request 46 ms after the mesh join response; 436 of these carried a
seven-minute session between two Let's Go endpoints. The clocks in the Clone Protocol's messages
are this clock, not a station's own uptime: a Let's Go host that receives clone messages timed
against something else releases the clone and leaves. `pokeldn.ldn.sync_clock`, and
`bin/lgpe_join.py --connect` runs it from the mesh join (`--no-sync-clock` turns it off).

The keep-alive protocol is 0x08, a message with no body; each side answers one in kind.

## The Clone Protocol (0x73)

Protocol 0x73 is `nn::pia::clone::CloneProtocol` (GetProtocolId at `0x158aab8` returns 0x73; the
SDK string in `main` is `PiaCommon-5_11_4`). The game's partner sync runs on it. The message type
byte is `0xAB`: the high nibble the structure, the low nibble a variant. Every message starts with
the version byte 3, the type byte, and the sender's frame counter as a big-endian u16 (about 60 per
second, starting when the sender's Pia session started).

The exchange below is measured between two Let's Go Pikachu 1.0.2 endpoints (a Ryujinx host and a
Ryujinx joiner over ldn_mitm, link code Pikachu x3, one trade completed). Both sides run the same
state machine; nothing is host-only.

### Clock sync, the first two seconds

Both sides send clock requests (type 0x11, 18 bytes) at about 5 per second, and each side answers
the other's with a clock reply (type 0x21, 22 bytes). Serializers `0x51f9b0` and `0x51fab0`.

    clock request                              clock reply
    [0]   1  version 3                         [0]   1  version 3
    [1]   1  type 0x11                         [1]   1  type 0x21
    [2]   2  sender frame counter              [2]   2  sender frame counter
    [4]   4  sender message count              [4]   4  sender message count
    [8]   2  destination station bitmap       [8]   2  destination station bitmap
    [0xA] 8  sender system tick                [0xA] 4  sender clone clock, ms
                                               [0xE] 8  the request's system tick, echoed

- The message count is one counter per sender over its clock requests, replies and participate
  messages, starting at 1. Requests and replies alternate, so it runs 1, 2, 3 on each side.
- The station bitmap is the destination, `1 << station index`: the host (index 0) sends 0x0002 to
  the joiner (index 1), the joiner sends 0x0001 back. A reply is addressed to the requester.
- The system tick is `os::GetSystemTick`, 19.2 MHz, the sender's own. The reply echoes the
  request's tick unchanged; nothing else in the request is echoed.
- The clone clock is milliseconds since the sender's clone protocol started (element +0x14 in the
  reply serializer), about 60 ms before its first request.

A reply that copies the request's counter, count and bitmap, with the clock field zero, is what
the retail console received from this project; it is not what a peer sends, and the retail console
kept requesting.

### Participate

After ten of its own requests were answered (2.1 s), the joiner sent a participate (type 0x31,
10 bytes, serializer `0x51fbd0`): header, its message count, then the destination bitmap 0x0003,
every station. The host answered within 30 ms with type 0x33, same layout, bitmap 0x0002. The host
sent its own participate 1.1 s later (bitmap 0x0003) and the joiner acknowledged with 0x33 carrying
0x0001.
From the first participate onward each side's clock replies are type 0x22 instead of 0x21, same
layout.

### Clone elements

A clone is keyed by three fields every command message carries: a clone type (1 to 4), the owning
station (0xFD for one no single station owns) and a 32-bit clone id. Both stations publish their
own copy of a clone; the host creates ids 1, 2, 3 for the trade as the screens advance, and clone
type 3 id 0 exists from the moment both sides have participated.

    every command message   [0] version 3, [1] type, [2] u16 the sender's frame counter,
                            [4] u8 clone type, [5] u8 owning station, [6] u16 0,
                            [8] u32 clone id
    types 0x81 to 0xc4      [0xC] u32 the sender's message count, [0x10] u16 destination bitmap,
                            then the structure's own fields
    types 0xd1 to 0xf4      [0xC] the data, with no message count and no bitmap

The structure is the type's high nibble and the command the low nibble, in the order the command
tokens report themselves (`SendClone::AnnounceCommandToken::vfunc0` at `0x522480` returns 0,
`ReceiveClone::RequestCommandToken` 1 at `0x520df0`, `SendClone::EndCommandToken` 2 at `0x522490`,
`AtomicSharingClone::LockCommandToken` 3 at `0x517820`): command = the low nibble minus one.

    0x81 announce   0x82 request   0x83 end   0x84 lock
    0x9N  + a u32 clock in ms at [0x12]                       ClockCloneCommandMessage, 22 bytes
    0xaN  + the clock, a u8 count at [0x16], a u8 and a u16   ClockAndCount, 26 bytes
    0xbN  + the clock and a u32 participant bitmap at [0x16]  ClockAndParticipant, 26 bytes
    0xcN  + the clock, the count and the bitmap at [0x1A]     ClockAndCountAndParticipant, 30
    0xeN  + a zlib stream at [0xD]                            the clone's state, acknowledging
    0xfN  + one byte at [0xD] and a zlib stream at [0xE]      the clone's state, with its data

The zlib streams inflate to a record that starts with the tag 0x20 and its own length:

    0x20 len  u16 clone id  0x03  u8 the station the data belongs to  u16 0
              u16 participant bitmap  u32 clock  then the clone's data
    0x20 0x0A u16 clone id  0x05  u8 the station being acknowledged   u32 clock

The deflate is one compress, a sync flush and a final empty block, at a level between 2 and 5:
every captured stream is reproduced byte for byte by `clone.pack_record`. The 0xfN header's two
bytes at [0xC] carry the record's participant bitmap and the 0xeN header's one byte the station
it acknowledges.

A station announces a clone with 0xa1 and the other answers 0x91; the owner then sends its data in
an 0xf3 and the other acknowledges with an 0xe3 carrying the same clock. 0x83 releases a clone and
0x84 acknowledges the release. Type 0x32 asks the other station to leave the clone session and
0x41 is its 14-byte acknowledgement, carrying the answering station's own bitmap at [0xA]; a host
whose 0x32 is never answered repeats it until the game gives up.

What the 0xaN messages carry after the clock is a u8 count and a three-byte value. For a clone
both stations hold, both sides send the same value (`01 2808ab` for clone type 4 id 1) and an
answering 0xa2 carries `01 000002`. For clone type 3 id 0 the two stations send different values
and neither matches its own announcement, so what the three bytes are computed from is
unresolved.

The full decode of a real session is `scratchpad/037_clone_parsed.txt`, its data messages
`scratchpad/lgpe_clone_data.py`. The decoders: `scratchpad/lgpe_pcap_decode.py` for an ldn_mitm
pcap, `scratchpad/lgpe_jsonl_clone.py` for a `--capture` log.

### What a host does with a joiner that holds no clone data

Measured against the retail Let's Go Pikachu, with a 0x3C-byte connection response that carries no
network id and no player. With the clock exchange and the sync clock both running, the console
answers the announcement of a clone, announces its own, and then releases it about five seconds
after the mesh join and sends 0x32. It sends no 0xb1 and no clone data. A real joiner reaches the
same point 1.1 seconds after its own participate and the host then sends the clone's data.

The handlers in `main`: `0x51ab20` CloneProtocol::vfunc9, the per-element receive; `0x51c100` the
protocol's receive dispatch, whose jump table `0xf7673c` on (type - 0x11) separates the clock
messages from the command messages and whose second table `0xf76800` on (type - 0x84) reaches the
command path; `0xf769c4` indexes the structure by the high nibble and `0xf769e4` the clone type.
`0x51b010` is the reply state machine, jump table `0xf76674` on (type - 0x21), and `0x51b1d0` the
clock-driven retransmit scheduler. The serializers are `0x51f9b0` clock request, `0x51fab0` clock
reply, `0x51fbd0` participate, `0x51f820` the command header, `0x51f4c0` ClockAndCount. A message
whose count at [0xC] does not exceed the last from that station is dropped (`0x51c1e0`). Element
offsets: +0x34 station, +0x40 state, +0x50 clock, +0x7a0 send time, +0x32c result.
