"""Pia version 4's Mesh Station Protocol - protocol 0x14, the layer a station JOINS on.

The protocol NUMBER crosses from 5.27-5.45 and the MESSAGE does not, which is the whole reason this
module exists next to `station_protocol.py` rather than inside it. Sword/Shield's own serializer at
`main` 0x017c7aa0 writes a connection request field by field, and its parser at 0x017c62a0 reads the
same bytes back:

    [0]     message type      1, or 6 for the relay variant (`csinc` on the caller's flag)
    [1]     the target's nat FLAGS byte, as the sender knows them
    [2]     platform id       9        - 5.27-5.45 checks 4
    [3]     0 or 1; 1 means a target variable id follows at 0xC. Anything higher is rejected
    [4]     target constant id      u64 big-endian, byte by byte at 4..0xB
    [0xC]   target variable id      u32 big-endian, CHECKED ONLY when [3] is 1
    [0x10]  the target's nat LOCATION byte
    [0x11]  the sender's station location, and nothing after it

So it is 5.27's header shifted one byte from offset 3 onwards, plus the flag that shifts it. Sending
5.27's layout here would put the constant id, the variable id and everything after them one byte
early, and a mismatched constant id is dropped in SILENCE - the most expensive possible failure to
read. `docs/pia.md` "The version-4 Mesh Station Protocol".

**AND THE STATION LOCATION IS UNCHANGED.** Sword's location deserializer (0x0185ee20) stores to
+0x48, +0x60, +0x68, +0x70, +0x74 and +0x78..+0x7b - the same object offsets, in the same order,
that `station_protocol.station_location` was written against on BDSP. Two addresses at their own
size bytes (2, 6 or 18 only: `(1 << size) & 0x40044`, the same three legal sizes), then relay
address, relay port, constant id, variable id, service variable id, and four bytes of nat state.
`station_protocol.station_location` builds one and is reused here unchanged.

THE TWO BYTES WE CANNOT KNOW YET, and why they are sweepable. [1] and [0x10] are the TARGET's own
nat flags and nat location, read out of the sender's record of it - and the receiver compares them
against its own. We have never seen the console's station location (it travels on the Mesh Protocol,
which has not spoken to us), so both are unknown; they are one byte each, a mismatch is silence, and
a match is the console's first word on 0x14. BDSP's own protocol count was measured exactly this
way. `bin/swsh_connect.py --connect` sweeps the pair.

A CURIOSITY WORTH RECORDING because it looks like a bug and changes nothing: the serializer writes
the target's +0x78 (nat flags) into [1] and its +0x79 (nat location) into [0x10], while the parser
compares [0x10] against its own +0x78 and [1] against its own +0x79. The two are crossed. In an LDN
session every station carries the same nat state, so both comparisons pass anyway - which is
presumably why nobody ever noticed.
"""

import struct

from pokeldn.ldn.station_protocol import (CONNECTION_REQUEST, CONNECTION_RESPONSE,
                                          RELAY_CONNECTION_REQUEST, RESULT_NAMES,
                                          STATION_LOCATION_MAX, STATION_LOCATION_MIN,
                                          inet_address, ldn_constant_id,
                                          ldn_service_variable_id, station_location)

PROTOCOL = 0x14                   # the same number 5.27-5.45 uses; NOT the same message
PLATFORM_SWITCH = 9               # 5.27-5.45 writes 4 here. Read off `mov w8, #9; strb w8, [x1,#2]`

HEADER_SIZE = 0x11                # everything before the station location
OFF_NAT_FLAGS = 1
OFF_PLATFORM = 2
OFF_HAS_VARIABLE_ID = 3
OFF_CONSTANT_ID = 4
OFF_VARIABLE_ID = 0xC
OFF_NAT_LOCATION = 0x10
OFF_LOCATION = 0x11

__all__ = ["PROTOCOL", "PLATFORM_SWITCH", "HEADER_SIZE", "OFF_NAT_FLAGS", "OFF_PLATFORM",
           "OFF_HAS_VARIABLE_ID", "OFF_CONSTANT_ID", "OFF_VARIABLE_ID", "OFF_NAT_LOCATION",
           "OFF_LOCATION", "CONNECTION_REQUEST", "CONNECTION_RESPONSE",
           "ACK", "ACK_SIZE", "build_ack", "ack_id_of",
           "RELAY_CONNECTION_REQUEST", "RESULT_NAMES", "RESPONSE_SIZE", "build_connection_request",
           "build_connection_response", "parse_connection_request", "parse_incoming_request",
           "parse_station_location", "parse_reply", "inet_address", "ldn_constant_id",
           "ldn_service_variable_id", "station_location"]


def build_connection_request(target_constant_id, target_variable_id, location,
                             nat_flags=5, nat_location=1, with_variable_id=True, relay=False,
                             platform=PLATFORM_SWITCH):
    """One version-4 connection request. `location` is `station_protocol.station_location`.

    `nat_flags` goes to [1] and `nat_location` to [0x10] - the pair the console compares against its
    own and the pair a run sweeps. `with_variable_id=False` clears [3], which makes the console skip
    the variable-id comparison entirely; the id is still written, because the parser only stops
    reading it, not the fields after it.
    """
    location = bytes(location)
    if not STATION_LOCATION_MIN <= len(location) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location is 0x20..0x40 bytes, this is {len(location)}")
    out = bytearray(HEADER_SIZE)
    out[0] = RELAY_CONNECTION_REQUEST if relay else CONNECTION_REQUEST
    out[OFF_NAT_FLAGS] = nat_flags & 0xFF
    out[OFF_PLATFORM] = platform & 0xFF
    out[OFF_HAS_VARIABLE_ID] = 1 if with_variable_id else 0
    struct.pack_into(">Q", out, OFF_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_NAT_LOCATION] = nat_location & 0xFF
    return bytes(out) + location


def parse_connection_request(data):
    """-> dict. The inverse of the builder, so a test can read back what a run will send."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a connection request is at least {HEADER_SIZE} bytes")
    return {"type": data[0], "nat_flags": data[OFF_NAT_FLAGS], "platform": data[OFF_PLATFORM],
            "with_variable_id": data[OFF_HAS_VARIABLE_ID],
            "constant_id": struct.unpack_from(">Q", data, OFF_CONSTANT_ID)[0],
            "variable_id": struct.unpack_from(">I", data, OFF_VARIABLE_ID)[0],
            "nat_location": data[OFF_NAT_LOCATION], "location": data[OFF_LOCATION:]}


RESPONSE_SIZE = 0x11              # 17 bytes, the allocation the sender asks for
OFF_RESPONSE_RESULT = 1
OFF_RESPONSE_CONSTANT_ID = 5
OFF_RESPONSE_VARIABLE_ID = 0xD


def build_connection_response(result, constant_id, variable_id):
    """The 17-byte answer, field for field off the sender at 0x017c6c30.

        [0]    2                      the message type
        [1]    the connection result   0 accepted, 1 denied, 2 version too low, 3 too high
        [2]    9                      the platform, written as a literal
        [3]    0
        [4]    0
        [5]    a constant id           u64 big-endian (0x1853b40)
        [0xD]  a variable id           u32 big-endian (0x1853b10)

    MEASURED: a wrong-platform request is answered with result 2 and both ids zero, which is this
    with x3 and w4 both xzr - sw15 read back `0202090000...` byte for byte. WHOSE ids belong in the
    accepted case is a DEDUCTION: the only other caller passes them out of the peer's own station
    location, so they are read here as the station being answered.
    """
    out = bytearray(RESPONSE_SIZE)
    out[0] = CONNECTION_RESPONSE
    out[OFF_RESPONSE_RESULT] = result & 0xFF
    out[2] = PLATFORM_SWITCH
    struct.pack_into(">Q", out, OFF_RESPONSE_CONSTANT_ID, constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_RESPONSE_VARIABLE_ID, variable_id & 0xFFFFFFFF)
    return bytes(out)


def parse_station_location(data):
    """-> dict. The two size-prefixed addresses, then the fixed tail. MEASURED against the console's
    own connection request (sw20), whose location carries a size-2 address and a size-6 one."""
    s1, s2 = data[0], data[1]
    a1, a2 = data[2:2 + s1], data[2 + s1:2 + s1 + s2]
    t = 2 + s1 + s2
    return {"address_sizes": (s1, s2), "address1": a1, "address2": a2,
            "ip": ".".join(str(b) for b in a2[:4]) if len(a2) >= 6 else None,
            "port": int.from_bytes(a2[4:6], "big") if len(a2) >= 6 else None,
            "relay_address": int.from_bytes(data[t:t + 4], "big"),
            "relay_port": int.from_bytes(data[t + 4:t + 6], "big"),
            "constant_id": int.from_bytes(data[t + 6:t + 14], "big"),
            "variable_id": int.from_bytes(data[t + 14:t + 18], "big"),
            "service_variable_id": int.from_bytes(data[t + 18:t + 22], "big"),
            "nat_flags": data[t + 22], "nat_location": data[t + 23],
            "probeinit": data[t + 24], "private_available": data[t + 25],
            "size": t + 26}


def parse_incoming_request(data):
    """A connection request the CONSOLE sent us: the header, its location and the trailing ack id.

    MEASURED, sw20: the console answers an accepted request by sending one of its own, addressed to
    the constant id and the variable id it read out of OUR location. Its own tail is
    `location || u32 ack id` - four bytes our first requests never sent, which is what
    `0x017d5750` reads by taking the message size minus four.
    """
    got = parse_connection_request(data)
    location = got["location"]
    got["station"] = parse_station_location(location)
    got["ack_id"] = int.from_bytes(location[got["station"]["size"]:], "big") or None
    return got


ACK = 5
ACK_SIZE = 8


def build_ack(ack_id):
    """The type-5 acknowledgement: `05 00 00 00` then a u32 big-endian.

    MEASURED, sw21: the console answered our connection response with `05 00 00 00 121a8113`, eight
    bytes, and 5.27-5.45 sends the same eight (`mesh_protocol.ack_for`). WHICH u32 is a DEDUCTION -
    the console put its own variable id there, and every message it sends ends in a counter that
    increments per message (7106cab5, b6, b7), so both readings are worth sweeping.
    """
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def ack_id_of(data):
    """The trailing counter: the last four bytes, big-endian. `0x017d5750` reads exactly this -
    message size minus four - which is how the console finds it in what we send."""
    return int.from_bytes(data[-4:], "big") if len(data) >= 4 else 0


def parse_reply(data):
    """-> (message type, connection result or None). Any 0x14 message from the console is the
    finding; a connection response carries its verdict in the byte after the type."""
    if not data:
        return None, None
    kind = data[0]
    result = data[1] if kind == CONNECTION_RESPONSE and len(data) > 1 else None
    return kind, result
