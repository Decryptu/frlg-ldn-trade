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

# EVERY OFFSET IN THIS MODULE IS PIA 5.27-5.45's. Sword/Shield registers the same protocol number
# under Pia version 4 and its connection request is a DIFFERENT message: a flag byte at [3] shifts
# the constant id to 4, the variable id to 0xC and the protocol count to 0x10. Building one from
# here would put every field a byte early. `docs/pia.md` "The version-4 Mesh Station Protocol".
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

# The console's own enum is wider than the wiki's four values. These were read off the caller of
# the deserializer, main.bin 0x0154f5e8, which maps an internal error code to the result byte it
# answers with: 0x6470 -> 3, 0x646f -> 2, 0xc24 -> 4, 0xc25 -> 1, 0x11c0f -> 7. The count mismatch
# (0x11c26) is in none of those branches, which is why a wrong protocol count is silence.
RESULT_VERSIONS_MATCHED = 7

RESULT_NAMES = {
    0: "accepted",
    1: "denied",
    2: "version too low",
    3: "version too high",
    4: "refused after parsing (0xc24)",
    5: "refused before the station lookup",
    7: "parsed and versions matched, refused by the second stage (0x11c0f)",
}

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


# What the console's InetAddress parser (main.bin 0x0153ac10) will accept as a size: it builds
# `1 << size` and tests it against 0x00040044, so the ONLY legal values are 2, 6 and 18. The size
# therefore counts the PORT as well as the address - 2 is a bare port, 6 is IPv4, 18 is IPv6.
INET_SIZES = (2, 6, 18)
INET_IPV4 = 6


def inet_address(ip, port):
    """The IPv4 form: four address bytes then a big-endian port, six bytes, which is size 6."""
    octets = bytes(int(p) for p in ip.split("."))
    if len(octets) != 4:
        raise ValueError(f"not an IPv4 address: {ip}")
    return octets + struct.pack(">H", port)


def station_location(ip, port, constant_id, variable_id, service_variable_id,
                     nat_flags=0x05, nat_location=1, probeinit=0, private_available=1,
                     public=True):
    """A Pia 5.11-5.45 station location with IPv4 public and private addresses: 40 bytes.

    Read off the console's own deserializer, `nn::pia::transport::StationLocation` vfunc3 at
    main.bin 0x015a3aac. Two size bytes, then the public and private addresses at those sizes, and
    then everything else at a fixed offset from wherever those two ended:

        +0x00  u32be  relay address        -> this+0x48
        +0x04  u16be  relay port           -> this+0x60
        +0x06  u64be  constant id          -> this+0x68
        +0x0E  u32be  variable id          -> this+0x70   the field the second stage reads
        +0x12  u32be  service variable id  -> this+0x74
        +0x16  u8     nat flags, nat location, probeinit, is-private-available

    40 bytes total, inside the 0x20..0x40 the connection-request parser accepts, or 36 when the
    public address is empty.
    """
    # A station with no route off the mesh sends an empty public address, two bytes carrying a
    # port of zero: what a Let's Go joiner sends on local wireless.
    public = inet_address(ip, port) if public else struct.pack(">H", 0)
    private = inet_address(ip, port)
    # The size byte includes the port. Writing len-2 here is refused, and the console's
    # parser rejects 4 outright (only 2, 6, 18 pass) - so the location never deserialised, its
    # variable id stayed 0, and every request came back with the same refusal no matter what we
    # varied. The connection-request parser THROWS AWAY the location's error, which is why a
    # malformed location looks like a working request that the game refuses.
    out = (bytes([len(public), len(private)]) + public + private
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


# The protocol ids Pia 5.29-5.45 defines, from the NintendoClients wiki's "Pia Protocols". A game
# registers a SUBSET, and BDSP registers exactly nine of them (measured on hardware). These
# are the candidates a version probe walks; an id outside this list is a fine filler.
KNOWN_PROTOCOL_IDS = (
    0x08,   # Keep Alive
    0x14,   # Station (MeshStationProtocol)
    0x18,   # Mesh
    0x1C,   # Sync Clock
    0x24,   # Local
    0x34,   # NAT
    0x44,   # LAN
    0x58,   # RTT
    0x65,   # Sync
    0x68,   # Unreliable
    0x73,   # Clone
    0x74,   # Clone (atomic)
    0x75,   # Clone (event)
    0x76,   # Clone (broadcast event)
    0x77,   # Clone (clock)
    0x7B,   # Voice
    0x7C,   # Reliable
    0x80,   # Broadcast Reliable
    0x81,   # Stream Broadcast Reliable
    0x94,   # Session
    0xA4,   # Monitoring Data
    0xB0,   # Reckoning 1D
    0xB4,   # Reckoning 3D
)

# An id the console does not register looks up as version 0 (0x0159b850 falls off its walk into
# `mov w0, wzr`), so this pair always matches and is what pads a probe out to the required count.
# Proven on hardware: nine entries of (0xFF, 1) drew "version too high", which is only
# possible if the expected version for 0xFF is 0.
FILLER = (0xFF, 0)


def version_probe(protocol_id, version, count):
    """The protocol list for a probe: the candidate FIRST, then filler to the console's own count.

    The console's loop reports the FIRST entry that disagrees, so putting the candidate first makes
    the reply describe that candidate and nothing else. -> a list of (id, version) pairs.
    """
    if count < 1:
        raise ValueError("a version probe needs at least one entry")
    return [(protocol_id, version)] + [FILLER] * (count - 1)


def read_version(result):
    """What a probe's outcome says about the registered version, given the version we sent.

    -> "higher", "lower" or "equal", and it raises on anything that says neither.

    The equality signal is a reply, not silence. A request whose
    versions all match gets past the deserializer entirely, and the SECOND stage (0x0154fcfc) then
    refuses it with 0x11c0f - which comes back as connection result 7. Every probe therefore has a
    definite answer, and silence means a lost packet rather than a match. Read as a match, this
    read silence as equality, which is the same shape of mistake as reading a wrong protocol count
    as a wrong identity.
    """
    if result == RESULT_VERSION_TOO_LOW:
        return "higher"                # ours was too low, so the console's is higher
    if result == RESULT_VERSION_TOO_HIGH:
        return "lower"
    if result is not None and result != RESULT_VERSION_TOO_LOW:
        return "equal"                 # it got past the version loop, whatever refused it after
    raise ValueError("silence says nothing about a version - the equality signal is a reply")


class VersionSearch:
    """Find a protocol's registered version from probes that only say higher, lower or equal.

    Driven rather than driving, so the search itself is testable without a radio: read
    `next_version()`, send a probe with it, and `feed()` back what came out of `read_version`.
    It opens at 1 because Pia's protocol versions are small, and falls back to bisection.

    `found` is None when the answers contradict each other, which is what a lost packet looks like
    - silence is the equality signal here, so a dropped reply reads as an equality that is not one.
    That is why `bin/bdsp_connect.py` re-probes both neighbours before believing a version.
    """

    def __init__(self, lo=0, hi=255, first=1):
        self.lo, self.hi = lo, hi
        self.pending = max(lo, min(hi, first))
        self.found = None
        self.done = False
        self.probes = 0

    def next_version(self):
        if self.done:
            return None
        return self.pending

    def feed(self, direction):
        """`direction` is what read_version() returned for the version next_version() gave."""
        if self.done:
            raise ValueError("this search has already finished")
        v = self.pending
        self.probes += 1
        if direction == "equal":
            self.found, self.done = v, True
            return
        if direction == "higher":
            self.lo = v + 1
        elif direction == "lower":
            self.hi = v - 1
        else:
            raise ValueError(f"a probe answered {direction!r}, which is not a direction")
        if self.lo > self.hi:
            self.done = True                # the answers contradict each other
            return
        self.pending = (self.lo + self.hi) // 2


def build_ack(ack_id):
    """The station protocol's own ack, eight bytes - the console builds one at 0x0154fa2c.

    A connection response is retransmitted every 500 ms until this comes back, so it is what turns
    an acceptance into a finished handshake rather than a message the console keeps repeating.
    """
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def parse_ack(data):
    """-> the ack id an 0x05 message acknowledges."""
    if len(data) < 8 or data[0] != ACK:
        raise ValueError(f"not an eight-byte station protocol ack: {data[:8].hex()}")
    return struct.unpack_from(">I", data, 4)[0]


def parse_station_location(loc):
    """-> dict, by the console's own deserializer (main.bin 0x015a3aac).

    The two size bytes decide where everything else starts, which is the whole trap: they count the
    PORT as well as the address, so only 2, 6 and 18 are legal, and a location whose sizes are
    wrong is silently left unparsed by a caller that discards the error.
    """
    if len(loc) < 4 or loc[0] not in INET_SIZES or loc[1] not in INET_SIZES:
        raise ValueError(f"address sizes {loc[:2].hex()} are not two of {INET_SIZES}")
    rest = 2 + loc[0] + loc[1]
    if len(loc) < rest + 0x1A:
        raise ValueError(f"a station location is {rest + 0x1A} bytes here, got {len(loc)}")

    def address(off, size):
        if size < 6:
            return None, struct.unpack_from(">H", loc, off + size - 2)[0]
        return (".".join(str(b) for b in loc[off:off + 4]),
                struct.unpack_from(">H", loc, off + 4)[0])

    public = address(2, loc[0])
    private = address(2 + loc[0], loc[1])
    return {
        "public": public, "private": private,
        "relay": (".".join(str(b) for b in loc[rest:rest + 4]),
                  struct.unpack_from(">H", loc, rest + 4)[0]),
        "constant_id": struct.unpack_from(">Q", loc, rest + 0x06)[0],
        "variable_id": struct.unpack_from(">I", loc, rest + 0x0E)[0],
        "service_variable_id": struct.unpack_from(">I", loc, rest + 0x12)[0],
        "nat_flags": loc[rest + 0x16], "nat_location": loc[rest + 0x17],
        "probeinit": loc[rest + 0x18], "private_available": loc[rest + 0x19],
    }


def parse_connection_response(data):
    """-> dict. A denial is fifteen bytes (the console builds one at 0x01550190); an acceptance
    carries the console's whole side of the handshake and is read in full here.

    An accepted response is the most informative message this project has ever had out of a native
    title: the host's complete protocol list with versions, its station location, its ids, the
    network id, the player's name, and the ack id that finishes the handshake.
    """
    if len(data) < 2:
        raise ValueError(f"a connection response is at least two bytes, got {len(data)}")
    if data[0] != CONNECTION_RESPONSE:
        raise ValueError(f"message type {data[0]:#04x}, expected {CONNECTION_RESPONSE:#04x}")
    out = {"result": data[1], "result_name": RESULT_NAMES.get(data[1], "?"), "size": len(data)}
    if data[1] != RESULT_ACCEPTED:
        if len(data) >= 15:
            out["constant_id"] = struct.unpack_from(">Q", data, 3)[0]
            out["variable_id"] = struct.unpack_from(">I", data, 11)[0]
        return out

    out["platform"] = data[2]
    out["target_constant_id"] = struct.unpack_from(">Q", data, 3)[0]
    out["target_variable_id"] = struct.unpack_from(">I", data, 11)[0]
    n = data[15]
    off = 16
    out["protocols"] = [(data[off + 2 * i], data[off + 2 * i + 1]) for i in range(n)]
    off += 2 * n
    size = struct.unpack_from(">H", data, off)[0]
    off += 2
    out["location"] = parse_station_location(data[off:off + size])
    off += size
    out["token"] = data[off:off + 32]
    off += 32
    out["network_id"] = struct.unpack_from(">I", data, off)[0]
    off += 4
    out["players"], out["participants"], infos = data[off], data[off + 1], data[off + 2]
    off += 3
    names = []
    for _ in range(infos):
        info = data[off:off + 0xC3]
        off += 0xC3
        if len(info) >= 0x51:
            names.append(info[1:0x51].split(b"\0")[0].decode("utf-8", "replace"))
    out["player_names"] = names
    out["ack_id"] = struct.unpack_from(">I", data, len(data) - 4)[0]
    return out


def parse_message(data):
    """-> (message type, the rest). Only the type byte is common to all seven."""
    if not data:
        raise ValueError("empty station protocol message")
    return data[0], data[1:]
