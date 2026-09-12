"""Pia station protocol version 9 (Pia 5.10-5.18) - protocol 0x14, the layer a station joins on
for Let's Go Pikachu / Eevee.

The connection-request handler at Let's Go Pikachu's `main` 0x5b8800 reads the wiki's 5.10-5.18
layout, station-protocol version number 9:

    [0]     message type            1, or 6 for the relay variant
    [1]     connection id
    [2]     version number          9   (`cmp w8, #9` at 0x5b8848)
    [3]     is inverse connection request; `b.hi` rejects anything above 1
    [4]     target constant id      u64 big-endian, 4..0xB, compared against the console's own
    [0xC]   target variable id      u32 big-endian, checked only when [3] is 1
    [0x10]  inverse connection id   compared against the station's record at +0xA0
    [0x11]  station location        the 5.11-5.45 layout, 0x20..0x40 bytes
    [...]   ack id                  u32 big-endian, read as the message size minus four

This is neither Sword's version-4 request (a platform byte at [2], a shift flag at [3]: `station4`)
nor the repo's 5.29-5.45 `station_protocol` (a protocol list at [1]). The station location is the
5.11-5.45 one `station_protocol.station_location` builds. docs/lgpe_session.md "The station
protocol, for a mesh join".
"""
import struct

from pokeldn.ldn.station_protocol import (ACK, CONNECTION_REQUEST, CONNECTION_RESPONSE,
                                          RELAY_CONNECTION_REQUEST, RESULT_NAMES,
                                          STATION_LOCATION_MAX, STATION_LOCATION_MIN,
                                          inet_address, ldn_constant_id,
                                          ldn_service_variable_id, station_location)

PROTOCOL = 0x14
VERSION = 9

HEADER_SIZE = 0x11
OFF_CONNECTION_ID = 1
OFF_VERSION = 2
OFF_IS_INVERSE = 3
OFF_CONSTANT_ID = 4
OFF_VARIABLE_ID = 0xC
OFF_INVERSE_ID = 0x10
OFF_LOCATION = 0x11

PLATFORM_SWITCH = 4

# The response fields the console's parser at 0x5b9270 reads, confirmed against Let's Go Pikachu:
#   [1]     result byte; 2 (version too low) takes a separate path
#   [5..C]  target constant id, big-endian, compared against the receiver's own (its +0x68)
#   [0xD..10] target variable id, big-endian, compared against the receiver's own (+0x70)
#   [0x37]  one byte, result-0 only, dropped when >= 5 (like Sword's gate)
# Nothing else is required to accept the response; the player-info body is what the HOST sends back.
OFF_RESPONSE_RESULT = 1
OFF_RESPONSE_VERSION = 2
OFF_RESPONSE_PLATFORM = 3
OFF_RESPONSE_FRAGMENT = 4
OFF_RESPONSE_CONSTANT_ID = 5
OFF_RESPONSE_VARIABLE_ID = 0xD
OFF_RESPONSE_GATE = 0x37
ACCEPTED_RESPONSE_SIZE = 0x38

__all__ = ["PROTOCOL", "VERSION", "HEADER_SIZE", "PLATFORM_SWITCH", "CONNECTION_REQUEST",
           "CONNECTION_RESPONSE", "RELAY_CONNECTION_REQUEST", "ACK", "RESULT_NAMES",
           "ACCEPTED_RESPONSE_SIZE", "build_connection_request", "parse_connection_request",
           "build_connection_response", "build_ack", "ack_id_of", "parse_reply",
           "station_location", "inet_address", "ldn_constant_id", "ldn_service_variable_id"]


def build_connection_request(target_constant_id, target_variable_id, location, ack_id=0,
                             connection_id=0, inverse_connection_id=0, is_inverse=False,
                             relay=False):
    """One version-9 connection request, with a trailing u32 ack id.

    `location` is `station_protocol.station_location` (the joiner's own). `is_inverse=False`
    clears [3], which makes the console skip the variable-id comparison; the id is written anyway,
    since the parser only stops reading it, not the fields after.
    """
    location = bytes(location)
    if not STATION_LOCATION_MIN <= len(location) <= STATION_LOCATION_MAX:
        raise ValueError(f"a station location is 0x20..0x40 bytes, this is {len(location)}")
    out = bytearray(HEADER_SIZE)
    out[0] = RELAY_CONNECTION_REQUEST if relay else CONNECTION_REQUEST
    out[OFF_CONNECTION_ID] = connection_id & 0xFF
    out[OFF_VERSION] = VERSION
    out[OFF_IS_INVERSE] = 1 if is_inverse else 0
    struct.pack_into(">Q", out, OFF_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_INVERSE_ID] = inverse_connection_id & 0xFF
    return bytes(out) + location + struct.pack(">I", ack_id & 0xFFFFFFFF)


def parse_connection_request(data):
    """-> dict, the inverse of the builder, so a test can read back what a run will send."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a connection request is at least {HEADER_SIZE} bytes")
    return {"type": data[0], "connection_id": data[OFF_CONNECTION_ID],
            "version": data[OFF_VERSION], "is_inverse": data[OFF_IS_INVERSE],
            "constant_id": struct.unpack_from(">Q", data, OFF_CONSTANT_ID)[0],
            "variable_id": struct.unpack_from(">I", data, OFF_VARIABLE_ID)[0],
            "inverse_connection_id": data[OFF_INVERSE_ID],
            "location": data[OFF_LOCATION:-4], "ack_id": struct.unpack_from(">I", data, len(data) - 4)[0]}


def build_connection_response(target_constant_id, target_variable_id, result=0, ack_id=1,
                              gate=1, platform=PLATFORM_SWITCH):
    """A version-9 connection response, padded to the size that answers the gate from inside the
    message. `target_constant_id` and `target_variable_id` are the RECEIVER's own ids (the host's),
    which its parser compares against itself; `gate` is the byte at 0x37 the result-0 path reads and
    drops when 5 or more. A trailing u32 ack id follows the padded body."""
    out = bytearray(ACCEPTED_RESPONSE_SIZE)
    out[0] = CONNECTION_RESPONSE
    out[OFF_RESPONSE_RESULT] = result & 0xFF
    out[OFF_RESPONSE_VERSION] = VERSION
    out[OFF_RESPONSE_PLATFORM] = platform & 0xFF
    struct.pack_into(">Q", out, OFF_RESPONSE_CONSTANT_ID, target_constant_id & ((1 << 64) - 1))
    struct.pack_into(">I", out, OFF_RESPONSE_VARIABLE_ID, target_variable_id & 0xFFFFFFFF)
    out[OFF_RESPONSE_GATE] = gate & 0xFF
    return bytes(out) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def build_ack(ack_id):
    """The type-5 acknowledgement: `05 00 00 00` then a u32 big-endian. The station-protocol ack is
    one layout across every 5.x version (`station_protocol` and `station4` send the same eight)."""
    return bytes([ACK, 0, 0, 0]) + struct.pack(">I", ack_id & 0xFFFFFFFF)


def ack_id_of(data):
    """The trailing u32, big-endian, which the console reads as the message size minus four."""
    return struct.unpack_from(">I", data, len(data) - 4)[0] if len(data) >= 4 else 0


def parse_reply(data):
    """-> (message type, connection result or None). A connection response carries its verdict in
    the byte after the type."""
    if not data:
        return None, None
    kind = data[0]
    result = data[1] if kind == CONNECTION_RESPONSE and len(data) > 1 else None
    return kind, result
