"""Pia's Local Protocol - protocol 36, the session bookkeeping an LDN network runs on.

This is what a Union Room actually says on the wire once the payloads are decrypted: the host
broadcasts an *update session* message listing every seat, and repeats it every 100 ms until each
station acknowledges it. Answering that ack is the cheapest possible proof that a console accepts
our packets, because the rebroadcast stops.

BYTE ORDER IS MIXED, and it is the trap here. The Pia message header around these is BIG-endian
(`pia5.parse_messages`); the Local Protocol's own fields are LITTLE-endian; and a local address
inside them is BIG-endian again. Each of the three is what the captured session reads back with.

Read against a real Shining Pearl session and the NintendoClients wiki's
"Local Protocol" page. docs/bdsp_session.md "What the console is saying".
"""

import struct
from dataclasses import dataclass, field

PROTOCOL = 36                     # the Pia protocol number these messages travel under

UPDATE_SESSION = 0x11
DESTROY_NETWORK = 0x12
START_HOST_MIGRATION = 0x13
UPDATE_SESSION_ACK = 0x21

# What the Pia message around ANY of these carries. LocalProtocol has exactly one send path
# (main.bin 0x016af22c) and all four message types reach it with the same options, so an ack is
# framed exactly like the update session it answers - and the captured update session reads
# `7f 11 0079 24 000000 0000000000000000` on the wire. 0x11 is "destination is a bitmap" (0x01)
# plus "may not be bundled" (0x10); the bitmap is `1 << station_index`, and 0 means broadcast.
MESSAGE_FLAGS = 0x11
BROADCAST = 0                     # the destination bitmap the console itself sends

HEADER_SIZE = 12                  # the local message header
UPDATE_SESSION_FIXED = 0x30       # before the node list
NODE_SIZE = 9
NODE_COUNT = 8
RANKING_EMPTY = 255               # an unused seat, with its address zeroed


@dataclass
class LocalNode:
    """One seat: an IPv4 address and port, plus how long it has been in the network."""
    ip: str
    port: int
    ranking: int                  # 0 is the oldest node; 255 means the seat is empty

    @property
    def occupied(self):
        return self.ranking != RANKING_EMPTY


@dataclass
class UpdateSession:
    sequence_id: int
    network_id: int               # random per network, NOT the advertisement's network id
    host_variable_id: int
    host_service_variable_id: int
    host_constant_id: bytes
    allow_participating: bool
    nodes: list = field(default_factory=list)
    host_migration_state: int = 0

    @property
    def occupied(self):
        return [n for n in self.nodes if n.occupied]


def parse_header(data):
    """-> (message_type, payload_size). Raises if the version byte is not 1."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a local message header is {HEADER_SIZE} bytes, got {len(data)}")
    version, message_type, size = struct.unpack_from("<BBH", data, 0)
    if version != 1:
        raise ValueError(f"local message version {version}, expected 1")
    return message_type, size


def _address(raw):
    """A local address: 6-byte IPv4 InetAddress, BIG-endian, then 2 bytes of extension."""
    return ".".join(str(b) for b in raw[:4]), struct.unpack_from(">H", raw, 4)[0]


def parse_update_session(data):
    """Parse a 0x11 update-session message body (the whole message, header included)."""
    message_type, size = parse_header(data)
    if message_type != UPDATE_SESSION:
        raise ValueError(f"message type {message_type:#04x}, expected {UPDATE_SESSION:#04x}")
    if len(data) < UPDATE_SESSION_FIXED + size:
        raise ValueError(f"truncated: {len(data)} bytes for {UPDATE_SESSION_FIXED + size}")
    seq, network_id, host_var, host_svc = struct.unpack_from("<4I", data, 0x0C)
    constant_id = data[0x20:0x28]
    allow = bool(data[0x28])
    nodes = []
    for i in range(NODE_COUNT):
        off = UPDATE_SESSION_FIXED + i * NODE_SIZE
        if off + NODE_SIZE > len(data):
            break
        ip, port = _address(data[off:off + 8])
        nodes.append(LocalNode(ip, port, data[off + 8]))
    tail = UPDATE_SESSION_FIXED + NODE_COUNT * NODE_SIZE
    state = data[tail] if tail < len(data) else 0
    return UpdateSession(seq, network_id, host_var, host_svc, constant_id, allow, nodes, state)


def build_ack(sequence_id):
    """The 0x21 acknowledgement of an update session, 20 bytes.

    The host repeats its update session until every station acknowledges it, so sending this and
    watching the rebroadcast stop is a pass/fail that needs nothing on the console's screen.

    Read off the console's own serializer (main.bin 0x016bc0f4, built at 0x016bc0c8): version 1,
    the type byte, then the header's payload-size field - which the constructor leaves at ZERO for
    an ack, `str w8, [x0, #0x14]` with w8 = 0x14 writing the 20-byte total and clearing the size
    halfword at +0x16. An update session sets that field; an ack does not.
    """
    return (struct.pack("<BBH", 1, UPDATE_SESSION_ACK, 0) + b"\0" * 6 + b"\0" * 2
            + struct.pack("<I", sequence_id) + b"\0" * 4)


def parse_ack(data):
    """-> the sequence id a 0x21 message acknowledges."""
    message_type, _size = parse_header(data)
    if message_type != UPDATE_SESSION_ACK:
        raise ValueError(f"message type {message_type:#04x}, expected {UPDATE_SESSION_ACK:#04x}")
    if len(data) < 0x14:
        raise ValueError(f"an ack is 20 bytes, got {len(data)}")
    return struct.unpack_from("<I", data, 0x0C)[0]
