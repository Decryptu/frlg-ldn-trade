"""Pia's Mesh Protocol - protocol 0x18, the membership layer above the station handshake.

The order a joiner goes through, and each step is a different protocol:

    LDN association            a seat on the radio; the game sees nothing
    Local Protocol   0x24      the host's update session, and the ack that stops it
    Station Protocol 0x14      the connection request, and the acceptance that names the host
    Mesh Protocol    0x18      THIS: the join request that puts a station IN the mesh

BDSP advertises mesh protocol version 3 in its connection response, which the wiki pins to Pia
5.30-5.45 - so the version numbers themselves date the library, and every structure here is the
5.31-5.45 one.

The join request is six bytes and says almost nothing: a type, the station index 253 that means
"not in a mesh yet", and an ack id. It is retransmitted every 500 ms until acknowledged, and Pia
gives up after ten seconds. The response carries the whole mesh - every station's location and
index, possibly split across fragments.

**A MESH MESSAGE IS ACKNOWLEDGED ON THE STATION PROTOCOL, NOT ON THIS ONE.** The wiki's type table
has no ack, and BDSP's own code has no builder for one: the mesh's handlers read the ack id and then
hand it to a MeshStationProtocol method, so what goes on the air is the station protocol's eight-byte
type-5 ack on protocol 0x14. `ack_for()` is that rule; `docs/bdsp_pia.md` "Acking a mesh message"
carries the addresses.
"""

import struct

from pokeldn.ldn import station_protocol as stp

PROTOCOL = 0x18
PORT_UNRELIABLE = 0
PORT_RELIABLE = 1                 # update mesh travels here; the join request does not

JOIN_REQUEST = 0x01
JOIN_RESPONSE = 0x02
LEAVE_REQUEST = 0x04
LEAVE_RESPONSE = 0x08
DESTROY_MESH = 0x10
DESTROY_RESPONSE = 0x11
UPDATE_MESH = 0x20
KICKOUT_NOTICE = 0x21
DUMMY_MESSAGE = 0x22
DUMMY_ACK = 0x23
CONNECTION_FAILURE_NOTICE = 0x24
INCONSISTENT_NOTICE = 0x25
GREETING = 0x40
MIGRATION_FINISH = 0x41
GREETING_RESPONSE = 0x42
MIGRATION_START = 0x44
MIGRATION_RESPONSE = 0x48
MULTI_MIGRATION_START = 0x49
MULTI_MIGRATION_RANK_DECISION = 0x4A
CONNECTION_REPORT = 0x80
RELAY_ROUTE_DIRECTIONS = 0x81

TYPE_NAMES = {v: k for k, v in list(globals().items()) if isinstance(v, int) and k.isupper()}

STATION_INDEX_INVALID = 253       # a console that has not joined a mesh yet
STATION_INDEX_HOST = 254
STATION_INDEX_BROADCAST = 255

STATION_INFO_SIZE = 68            # 5.31-5.45: a 64-byte location, an index, a join order, a pad
LOCATION_FIELD = 64
ACK_PROTOCOL = stp.PROTOCOL       # 0x14 - a mesh message is acked on the STATION protocol

# ---------------------------------------------------------------------------
# Version 4 (Sword/Shield), read off the retail binary in session 57. Addresses are
# scratchpad/swsh/main.bin, and docs/swsh.md "The Mesh Protocol" carries the disassembly.
#
# The MESSAGE TABLE IS THE SAME TABLE. The version-4 dispatcher is `MeshProtocol::vfunc9`
# (0x017bfc30) -> 0x017c0c80: `type - 1`, a 0x80 bound, and the jump table at 0x02081564. Its
# nineteen live entries are exactly the constants above MINUS 0x22 and 0x23 - version 4 has no
# DUMMY_MESSAGE and no DUMMY_ACK, and those two fall to the default case.
#
# THE JOIN REQUEST NEEDS NO CHANGE. The version-4 handler for type 1 is 0x017c1700: it reads the
# ack id as the message's last four bytes (0x017d5750, `size - 4` then a big-endian load) and
# compares byte [1] against 0xFD at 0x017c1800 - the same six bytes `build_join_request` already
# sends. It answers on 0x14 with the eight-byte ack built at 0x017c6dd0, so `ack_for` holds too.
#
# WHAT DID CHANGE IS THE ENTRY STRIDE: 64 bytes, not 68, and the index sits at 0x3E inside it
# rather than after a 64-byte location. The parser at 0x017b4830 is self-proving on this - it
# rejects a response longer than 0x810 bytes, and 0x810 is exactly 0x10 + 32 * 0x40 against the
# 32-station bound at 0x017bfa34. The loop is `add x20, x20, #0x4e` (0x10 + 0x3E), then
# `ldrb w8, [x20], #0x40` per entry.
MESH_TYPES_V4 = frozenset([
    JOIN_REQUEST, JOIN_RESPONSE, LEAVE_REQUEST, LEAVE_RESPONSE,
    DESTROY_MESH, DESTROY_RESPONSE, UPDATE_MESH, KICKOUT_NOTICE,
    CONNECTION_FAILURE_NOTICE, INCONSISTENT_NOTICE,
    GREETING, MIGRATION_FINISH, GREETING_RESPONSE, MIGRATION_START,
    MIGRATION_RESPONSE, MULTI_MIGRATION_START, MULTI_MIGRATION_RANK_DECISION,
    CONNECTION_REPORT, RELAY_ROUTE_DIRECTIONS,
])
STATION_INFO_SIZE_V4 = 0x40
INDEX_FIELD_V4 = 0x3E
MAX_STATIONS_V4 = 32
JOIN_RESPONSE_MAX_V4 = 0x810      # 0x10 + MAX_STATIONS_V4 * STATION_INFO_SIZE_V4, checked inline


def build_join_request(ack_id, station_index=STATION_INDEX_INVALID):
    """Six bytes. 253 is what a station that is not yet in a mesh calls itself."""
    return bytes([JOIN_REQUEST, station_index & 0xFF]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def read_ack_id(data):
    """-> the ack id a mesh message carries, which is its LAST four bytes, big-endian.

    BDSP's own reader is four instructions (main.bin 0x01542db8): `size - 4` with a borrow check,
    then a big-endian load at that offset. A message shorter than four bytes acks nothing and
    answers 0, which is what an unacknowledged type looks like from the same call.
    """
    if len(data) < 4:
        return 0
    return struct.unpack_from(">I", data, len(data) - 4)[0]


def ack_for(data):
    """-> (protocol, payload) that acknowledges a mesh message, or None if it carries no ack id.

    The mesh protocol never acks with a mesh message. Every one of the four sites that acknowledges
    one (main.bin 0x0154b790, 0x0154b868, 0x0154b984, 0x0154b9a4 - the join request and the join
    response handlers) reads the ack id with 0x01542db8 and calls 0x01550324, a MeshStationProtocol
    method that builds the same eight bytes as `station_protocol.build_ack` and sends them on that
    object - the one whose field 0x120 holds the 10000 ms its constructor writes, which is what says
    which protocol object it is. So the reply to a join response is `05 00 00 00 <ack id>` on 0x14.
    """
    kind = data[0] if data else None
    if kind not in (JOIN_REQUEST, JOIN_RESPONSE) or len(data) < 4:
        return None
    return ACK_PROTOCOL, stp.build_ack(read_ack_id(data))


def parse_join_response(data, version4=False):
    """-> dict. A refusal is `02 00 ff ff <reason>`; a success carries the mesh.

    The refusal is recognised by its two 0xFF bytes where a success has the fragment counts, which
    is the only thing that tells the two apart. The sixteen-byte header is the SAME header in
    version 4 - Sword's parser (main.bin 0x017b4830) reads [1] [2] [3] refusal-first in that order,
    packs [8] [9] [0xa] into one big-endian 24-bit value and loads the update counter at 0xC, all
    where 5.31-5.45 has them. `version4` changes the ENTRIES, not the header: see `_station_info`.

    WHICH FIELD COUNTS THE ENTRIES IS NOT THE SAME IN BOTH PATHS, and version 4 is read here the
    way its own parser reads it rather than the way 5.31-5.45's is written. An unfragmented
    response (`fragments == 1`, 0x017b48f4) walks `stations` entries from base 0 and never touches
    [6] or [7]; a fragmented one (0x017b4b6c) walks [6] entries into slot [7]. On 5.31-5.45 [6] is
    read in both cases, which is what this function did before.
    """
    if len(data) < 5 or data[0] != JOIN_RESPONSE:
        raise ValueError(f"not a mesh join response: {data[:8].hex()}")
    if data[1] == 0 and data[2] == 0xFF and data[3] == 0xFF:
        return {"refused": True, "reason": data[4]}
    if len(data) < 16:
        raise ValueError(f"a join response is at least sixteen bytes, got {len(data)}")
    out = {
        "refused": False,
        "stations": data[1],              # including the joining station
        "host_index": data[2],
        "our_index": data[3],
        "fragments": data[4],
        "fragment_index": data[5],
        "entries": data[6],
        "base_index": data[7],
        "max_active": data[8],
        "max_buffer": data[9],
        "max_total": data[10],
        "update_counter": struct.unpack_from(">I", data, 12)[0],
    }
    count, base = out["entries"], out["base_index"]
    if version4 and out["fragments"] == 1:
        count, base = out["stations"], 0
    out["entry_count"], out["entry_base"] = count, base
    out["station_info"] = _station_info(data, 16, count, version4=version4)
    out["ack_id"] = read_ack_id(data)
    return out


UPDATE_MESH_HEADER = 12
UPDATE_MESH_SIZE = UPDATE_MESH_HEADER + 8 * STATION_INFO_SIZE      # 556: always the full 8 seats


def parse_update_mesh(data, version4=False):
    """-> dict. The host's periodic statement of who is in the mesh.

    BDSP sends this about once a second and always at the FULL 556 bytes - twelve bytes of header
    and room for all eight seats, the unused ones left zero - so the length says nothing and
    `entries` is what to walk. sp45 caught 110 of them, every one identical, update counter 5.
    """
    if len(data) < UPDATE_MESH_HEADER or data[0] != UPDATE_MESH:
        raise ValueError(f"not a mesh update: {data[:12].hex()}")
    out = {
        "stations": data[1],
        "host_index": data[2],
        "update_counter": struct.unpack_from(">I", data, 4)[0],
        "fragments": data[8],
        "fragment_index": data[9],
        "entries": data[10],
        "base_index": data[11],
    }
    out["station_info"] = _station_info(data, UPDATE_MESH_HEADER, out["entries"],
                                        version4=version4)
    return out


def _station_info(data, off, count, version4=False):
    """The mesh table's entries. Two geometries, and the stride is the whole difference.

        5.31-5.45   68 bytes: a 64-byte location, the index, a big-endian join order, one pad
        version 4   64 bytes: the location, then the index at 0x3E

    Version 4's stride is `ldrb w8, [x20], #0x40` at main.bin 0x017b4a24 with the cursor started at
    0x10 + 0x3E, and it is confirmed by the length bound the same function applies: it refuses a
    response over 0x810 bytes, which is 0x10 + 32 * 0x40 against the 32-station limit. There is no
    join order in it - the byte at 0x3F is not read on either path.
    """
    size = STATION_INFO_SIZE_V4 if version4 else STATION_INFO_SIZE
    index_field = INDEX_FIELD_V4 if version4 else LOCATION_FIELD
    infos = []
    for _ in range(count):
        if off + size > len(data):
            break
        blob = data[off:off + size]
        entry = {"station_index": blob[index_field]}
        if not version4:
            entry["join_order"] = struct.unpack_from(">H", blob, index_field + 1)[0]
        try:
            entry["location"] = stp.parse_station_location(blob[:index_field])
        except ValueError as exc:
            entry["location_error"] = str(exc)
        infos.append(entry)
        off += size
    return infos


def parse_message(data):
    """-> (message type, name). Every mesh message opens with its type."""
    if not data:
        raise ValueError("empty mesh protocol message")
    return data[0], TYPE_NAMES.get(data[0], f"unknown {data[0]:#04x}")
