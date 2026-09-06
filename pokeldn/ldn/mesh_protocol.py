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

STATION_INFO_SIZE = 68            # 5.31-5.45: a 64-byte location, an index, three bytes of pad
LOCATION_FIELD = 64


def build_join_request(ack_id, station_index=STATION_INDEX_INVALID):
    """Six bytes. 253 is what a station that is not yet in a mesh calls itself."""
    return bytes([JOIN_REQUEST, station_index & 0xFF]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def parse_join_response(data):
    """-> dict. A refusal is `02 00 ff ff <reason>`; a success carries the mesh.

    The refusal is recognised by its two 0xFF bytes where a success has the fragment counts, which
    is the only thing that tells the two apart.
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
    infos, off = [], 16
    for _ in range(out["entries"]):
        if off + STATION_INFO_SIZE > len(data):
            break
        blob = data[off:off + STATION_INFO_SIZE]
        entry = {"station_index": blob[LOCATION_FIELD]}
        try:
            entry["location"] = stp.parse_station_location(blob[:LOCATION_FIELD])
        except ValueError as exc:
            entry["location_error"] = str(exc)
        infos.append(entry)
        off += STATION_INFO_SIZE
    out["station_info"] = infos
    out["ack_id"] = struct.unpack_from(">I", data, len(data) - 4)[0]
    return out


def parse_message(data):
    """-> (message type, name). Every mesh message opens with its type."""
    if not data:
        raise ValueError("empty mesh protocol message")
    return data[0], TYPE_NAMES.get(data[0], f"unknown {data[0]:#04x}")
