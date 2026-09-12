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

## Joining the mesh

With the station connected, a mesh join request on protocol 0x18 (`mesh_protocol.build_join_request`,
type 1, local station index 253, a trailing ack id) draws the host's join response: type 2, 148
bytes, two stations, host index 0, joining index 1, one fragment, two station infos, max active 2,
max total 8, carrying both stations' locations. The host then broadcasts an update mesh (type 0x20,
524 bytes, update counter 1). The join response is acknowledged with a type-5 ack on protocol 0x14,
not with a mesh message (`mesh_protocol.ack_for`). The joiner is then station index 1 in the mesh.

Once in the mesh the host streams, per second, its Local Protocol update-session (0x24, acked with a
0x21), RTT requests (0x58; a silent station is not dropped, only left without a timing sample), and
the Pia Clone Protocol on 0x73.

## The Clone Protocol (0x73)

Protocol 0x73 is `nn::pia::clone::CloneProtocol` (GetProtocolId at `0x158aab8` returns 0x73). The
game's partner sync runs on it. The message type byte is `0xAB`: the high nibble the structure, the
low nibble a variant. The host streams clock requests (type 0x11) addressed to the joiner's station
bitmap and expects clock replies (type 0x21); until the clock syncs the game drops the partner with
"la connexion avec votre partenaire a ete interrompue".

Read off the console's serializers. ClockRequestMessage (`0x51f9b0`), 18 bytes:

    [0]   1  version 3
    [1]   1  type 0x11
    [2]   2  field A, big-endian        increments ~0xD per request
    [4]   4  count, big-endian          +1 per request
    [8]   2  participant bitmap, big-endian
    [0xA] 8  clock, big-endian          a rising tick value

ClockReplyMessage (`0x51fab0`), 22 bytes, the same fields plus an extra u32 at [0xA] before the
clock. `pokeldn.ldn.clone` builds it. A reply that echoes the request's field A, count, participant
and clock with the extra u32 zeroed is sent and reaches the console (the same send path the station
handshake and mesh join used), but the console keeps sending clock requests and the session drops:
echoing the host's clock is not what the reply must carry.

The clone protocol is a synchronized-object system, not a request/reply pair. A participant
announces itself with a participate message (type 0x31, 10 bytes, serializer `0x51fbd0`), a clock is
agreed, and clone elements are retransmitted on that clock. The handlers to read:

    0x51ab20  CloneProtocol::vfunc9, the receive dispatch (splits the 0xAB type byte)
    0x51b010  the reply/ack state machine, a jump table at 0xf76674 on (type - 0x21)
    0x51b1d0  the clock-driven element retransmit scheduler (the 0x11 request side)

`pokeldn.ldn.clone` builds the clock reply and the participate message. Sending the clock reply
(echoing the request's clock), a participate (type 0x31), and both framings (directed constant-id
and the console's own bitmap to the host station bit) all leave the console sending only clock
requests and dropping the partner; none converges the clone clock.

The clock is a per-element state machine, not a request/reply pair. `CloneProtocol::vfunc9`
(`0x51ab20`) runs each clone element on every receive: it reads the element's station at +0x34 and
computes the current clock into +0x50 as `now / ticks_per_ms`, then steps the element state at
+0x40 through a jump table at `0xf76674` indexed by `state - 0x21`. State 0x21 (`0x51b04c`) gates on
a counter in [2,4] and advances to 0x22; state 0x22 (`0x51b074`) measures elapsed time since a
send-time stored at element+0x7a0 and writes the result at +0x32c. The element lifecycle advances on
its own clock, so a participant must hold a clone element in the matching state, not merely answer a
message. The clock reply's extra u32 at wire [0xA] (element+0x14, absent from the request) is the
field a real joiner fills with its own clock. The wall is the clock-agreement
math, the host's offset computation on a reply, in the Clock class (`nn::pia::clone::Clock` /
`RtcClock`), and/or the game-level clone element sync. The CloneProtocol receive vtable is
`0x158aa98`; the clock reply's [0xA] extra u32, unread, is the likely carrier of the replier's own
clock.
