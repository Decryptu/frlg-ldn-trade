"""Pia's Mesh Station Protocol - protocol 0x14, the handshake that actually joins a mesh.

The Local Protocol (`local_protocol.py`) is only membership bookkeeping: answering its update
session makes the host stop asking, and changes nothing the game can see. THIS is the layer a
station joins on. A joiner sends a connection request; the host accepts it, denies it, or says
nothing at all.

EVERY OFFSET HERE IS READ OFF THE CONSOLE'S OWN PARSER, main.bin 0x0154ebd0, reached from the
protocol's receive dispatcher 0x0154e848 through a jump table at 0x3e6b38f (message type minus one,
seven entries). The parser is worth reading in the order it checks things, because the order is
what makes a probe possible:

    size                    must be 15..949            cmp #0x3b6 b.hs / cmp #0xe b.ls
    [0]    message type     1 = connection request     the jump table's own index
    [1]    connection result
    [2]    platform id      4 = Switch
    [3]    target constant id, BIG-endian u64          `ldur x8,[x26,#3]` then `rev`
    [0xB]  target variable id, BIG-endian u32          `ldur w29,[x26,#0xb]` then `rev`
                                                       BOTH are compared against the console's own
                                                       and a mismatch drops the message silently
    [0xF]  number of protocols N                       compared against the console's OWN count,
                                                       and a mismatch is error 0x11c26 - silence
    [0x10] N x (protocol id, protocol version)         each version compared against what the
                                                       console registers for that id; lower is
                                                       connection result 2, higher is 3, and BOTH
                                                       of those get a connection response back
    then   station location size, BIG-endian u16, 0x20..0x40
    then   the station location, 32 ASCII token bytes, network id, player counts, ack id

**An id the console does not register has expected version 0** (0x0159b850 returns 0 when its walk
of the registered protocols falls off the end), so a version of 1 on an unknown id is a guaranteed
"version is too high". That is what makes the count knowable without knowing the list: sweep N, and
the N that draws a reply is the console's own protocol count.
"""

import struct
import zlib

PROTOCOL = 0x14                   # MeshStationProtocol, Pia 5.29-5.45
PORT_UNRELIABLE = 0               # the reliable port has not been used by Pia since 5.6

CONNECTION_REQUEST = 1
CONNECTION_RESPONSE = 2
DISCONNECTION_REQUEST = 3
DISCONNECTION_RESPONSE = 4
ACK = 5
RELAY_CONNECTION_REQUEST = 6
RELAY_CONNECTION_RESPONSE = 7

PLATFORM_WII_U = 3
PLATFORM_SWITCH = 4

MIN_SIZE = 15                     # `cmp w8, #0xe; b.ls` - strictly greater than 14
MAX_SIZE = 949                    # `cmp w8, #0x3b6; b.hs` - strictly less than 950

RESULT_ACCEPTED = 0
RESULT_DENIED = 1
RESULT_VERSION_TOO_LOW = 2
RESULT_VERSION_TOO_HIGH = 3

RESULT_NAMES = {0: "accepted", 1: "denied", 2: "version too low", 3: "version too high"}

STATION_LOCATION_MIN = 0x20       # `sub w10, w25, #0x20; cmp w10, #0x21; b.hs`
STATION_LOCATION_MAX = 0x40


def ldn_constant_id(mac):
    """A station's constant id in LDN mode, from its MAC. Never changes, even across sessions.

    `mac[2]<<56 | mac[4]<<48 | mac[5]<<40 | mac[3]<<32 | mac[1]<<24 | mac[0]<<16`, from the
    NintendoClients wiki. The captured Shining Pearl host advertises 000048f120229beb in its update
    session, which is this rule run over 48:f1:eb:20:9b:22 - the MAC the scan recorded for it. Three
    independent things agree there: the formula, the field's little-endian byte order, and the scan.
    """
    m = bytes(mac)
    if len(m) != 6:
        raise ValueError(f"a MAC is six bytes, not {len(m)}")
    return (m[2] << 56) | (m[4] << 48) | (m[5] << 40) | (m[3] << 32) | (m[1] << 24) | (m[0] << 16)


def ldn_service_variable_id(mac):
    """A station's service variable id in LDN mode: the CRC-32 of its MAC."""
    m = bytes(mac)
    if len(m) != 6:
        raise ValueError(f"a MAC is six bytes, not {len(m)}")
    return zlib.crc32(m) & 0xFFFFFFFF


def inet_address(ip, port):
    """The 4-byte IPv4 form. A station location says how long each address is, so this is a choice
    the sender makes, not a fixed layout."""
    octets = bytes(int(p) for p in ip.split("."))
    if len(octets) != 4:
        raise ValueError(f"not an IPv4 address: {ip}")
    return octets + struct.pack(">H", port)


def station_location(ip, port, constant_id, variable_id, service_variable_id,
                     nat_flags=0x05, nat_location=1, probeinit=0, private_available=1):
    """A Pia 5.11-5.45 station location with IPv4 public and private addresses: 40 bytes.

    40 is inside the 0x20..0x40 the console's parser accepts. The relay address is always IPv4 and
    always zero here - there is no relay on a local network.
    """
    public = inet_address(ip, port)
    private = inet_address(ip, port)
    out = (bytes([len(public) - 2, len(private) - 2]) + public + private
           + inet_address("0.0.0.0", 0)
           + struct.pack(">Q", constant_id)
           + struct.pack(">I", variable_id)
           + struct.pack(">I", service_variable_id)
           + bytes([nat_flags & 0xFF, nat_location & 0xFF,
                    probeinit & 0xFF, 1 if private_available else 0]))
    if not STATION_LOCATION_MIN <= len(out) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location must be 0x20..0x40 bytes, this is {len(out)}")
    return out


def player_info(name="", account="", language=1, principal_id=0):
    """One 195-byte PlayerInfo, 5.27-5.45 (the order of string and encoding was swapped in 5.27)."""
    out = (bytes([1]) + name.encode("utf-8")[:80].ljust(80, b"\0")
           + bytes([1]) + account.encode("utf-8")[:40].ljust(40, b"\0")
           + bytes([language & 0xFF]) + b"\0" * 64
           + struct.pack("<Q", principal_id))
    assert len(out) == 0xC3, len(out)
    return out


def build_connection_request(target_constant_id, target_variable_id, protocols, location,
                             token=b"", network_id=0, players=1, participants=1, player_infos=(),
                             ack_id=1, platform=PLATFORM_SWITCH, result=RESULT_ACCEPTED,
                             message_type=CONNECTION_REQUEST):
    """The message the console's parser at 0x0154ebd0 reads, field for field.

    `protocols` is a sequence of (id, version). `location` is a station location of 0x20..0x40
    bytes. The target ids are the HOST's, and the console drops the message without a word if
    either fails to match its own.
    """
    if len(location) < STATION_LOCATION_MIN or len(location) > STATION_LOCATION_MAX:
        raise ValueError(f"station location is {len(location)} bytes, must be 0x20..0x40")
    out = bytearray()
    out += bytes([message_type & 0xFF, result & 0xFF, platform & 0xFF])
    out += struct.pack(">Q", target_constant_id)
    out += struct.pack(">I", target_variable_id)
    out += bytes([len(protocols) & 0xFF])
    for pid, version in protocols:
        out += bytes([pid & 0xFF, version & 0xFF])
    out += struct.pack(">H", len(location)) + bytes(location)
    out += bytes(token)[:32].ljust(32, b"\0")
    out += struct.pack(">I", network_id)
    out += bytes([players & 0xFF, participants & 0xFF, len(player_infos) & 0xFF])
    for info in player_infos:
        out += bytes(info)
    out += struct.pack(">I", ack_id)
    if not MIN_SIZE <= len(out) <= MAX_SIZE:
        raise ValueError(f"a connection request must be {MIN_SIZE}..{MAX_SIZE} bytes, "
                         f"this is {len(out)}")
    return bytes(out)


def parse_connection_response(data):
    """-> dict. The 5.27-5.45 denial is fifteen bytes and the console builds one at 0x01550190.

    An acceptance is longer and carries the whole station location back; only the head is read here,
    because the head is what says which of the two this is.
    """
    if len(data) < 2:
        raise ValueError(f"a connection response is at least two bytes, got {len(data)}")
    if data[0] != CONNECTION_RESPONSE:
        raise ValueError(f"message type {data[0]:#04x}, expected {CONNECTION_RESPONSE:#04x}")
    out = {"result": data[1], "result_name": RESULT_NAMES.get(data[1], "?"), "size": len(data)}
    if data[1] != RESULT_ACCEPTED and len(data) >= 15:
        out["constant_id"] = struct.unpack_from(">Q", data, 3)[0]
        out["variable_id"] = struct.unpack_from(">I", data, 11)[0]
    elif data[1] == RESULT_ACCEPTED and len(data) >= 15:
        out["constant_id"] = struct.unpack_from(">Q", data, 3)[0]
        out["variable_id"] = struct.unpack_from(">I", data, 11)[0]
    return out


def parse_message(data):
    """-> (message type, the rest). Only the type byte is common to all seven."""
    if not data:
        raise ValueError("empty station protocol message")
    return data[0], data[1:]
