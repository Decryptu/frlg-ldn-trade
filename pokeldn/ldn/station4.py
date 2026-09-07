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
           "RELAY_CONNECTION_REQUEST", "RESULT_NAMES", "build_connection_request",
           "parse_connection_request", "parse_reply", "inet_address", "ldn_constant_id",
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


def parse_reply(data):
    """-> (message type, connection result or None). Any 0x14 message from the console is the
    finding; a connection response carries its verdict in the byte after the type."""
    if not data:
        return None, None
    kind = data[0]
    result = data[1] if kind == CONNECTION_RESPONSE and len(data) > 1 else None
    return kind, result
