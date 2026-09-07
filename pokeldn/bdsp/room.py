"""What BDSP's Union Room actually says, once Pia is out of the way.

Everything here is BDSP's own payload shapes - the bytes INSIDE a Pia message, above the reliable
and unreliable transports. Nothing in `pokeldn.ldn` may know about any of it.

Two streams carry the room:

    reliable   0x7c   the player's position, resent until acknowledged
    unreliable 0x68   a keepalive every 2 s, and a trail of recent positions while an avatar moves

THE POSITION MESSAGE, twenty bytes, and it is the first thing this project has read that the GAME
wrote rather than the middleware:

    0x00  6   a fixed head, `01 00 11 08 00 31` in every capture
    0x06  2   facing angle in DEGREES, little-endian
    0x08  4   x, little-endian float
    0x0c  4   y, little-endian float - the Union Room's floor: exactly 0.0 in three captures and
              1.5e-08 in the fourth, so it is a height and the room is flat, not a constant
    0x10  4   z, little-endian float

Four captures, four different places on that floor, and the angle was 0, 90, 90 and 225 - multiples
of 45, which is what an eight-direction facing is. sp35/sp36/sp39/sp43.

THE TRAIL, on the unreliable stream while the avatar is walking: a three-byte head and then triples
of little-endian halfwords, twelve of them in the 75-byte form sp36 caught, moving smoothly from one
to the next. Their units are NOT the position message's - this is a compact form, and calling it
anything more than a trail would be a guess.

`docs/bdsp.md` "What the room says".
"""

import struct

POSITION_SIZE = 20
POSITION_HEAD = bytes.fromhex("010011080031")
KEEPALIVE = bytes.fromhex("0400020000")      # the unreliable stream every 2 s when nothing happens
TRAIL_HEAD_SIZE = 3
TRAIL_POINT_SIZE = 6


def is_position(data):
    return len(data) == POSITION_SIZE and data[:6] == POSITION_HEAD


def parse_position(data):
    """-> dict. Raises on anything that is not the twenty-byte position message."""
    if len(data) != POSITION_SIZE:
        raise ValueError(f"a position message is {POSITION_SIZE} bytes, got {len(data)}")
    if data[:6] != POSITION_HEAD:
        raise ValueError(f"unexpected head {data[:6].hex()}, not {POSITION_HEAD.hex()}")
    x, y, z = struct.unpack_from("<fff", data, 8)
    return {"head": data[:6], "angle": struct.unpack_from("<H", data, 6)[0],
            "x": x, "y": y, "z": z}


def build_position(x, y, z, angle=0):
    """The same twenty bytes, ours. Nothing has been sent to a console with this yet."""
    return (POSITION_HEAD + struct.pack("<H", angle & 0xFFFF)
            + struct.pack("<fff", float(x), float(y), float(z)))


def parse_trail(data):
    """-> dict with the head and the halfword triples. The units are not known; do not invent them."""
    if len(data) < TRAIL_HEAD_SIZE:
        raise ValueError(f"a trail is at least {TRAIL_HEAD_SIZE} bytes, got {len(data)}")
    body = data[TRAIL_HEAD_SIZE:]
    n = len(body) // TRAIL_POINT_SIZE
    return {"head": data[:TRAIL_HEAD_SIZE],
            "points": [struct.unpack_from("<HHH", body, i * TRAIL_POINT_SIZE) for i in range(n)],
            "trailing": body[n * TRAIL_POINT_SIZE:]}
