"""BDSP's OWN protocol, above Pia - the messages the Union Room is made of.

The game runs a typed protocol of its own inside the Pia payloads, and `TeamLumi/opendpr` names
every message in it: `Dpr.NetworkUtils.NetDataParser` lists the classes, each an `ANetData<T>` with
a `DataID` byte, and each `T` is a plain struct. Reading that beat guessing by a wide margin - the
six bytes this module first called "a fixed head" are three struct fields and a length.

THE FRAMING, and it fits every payload ever captured:

    0x0  1  data id
    0x1  2  payload length, BIG-endian
    0x3  .  payload - the struct, little-endian, as C# lays it out

    01 0011 08 00 31 5a00 <x><y><z>     NetJoinData    "a player has joined, here"
    02 0048 <12 x 6 bytes>              NetPosData     where a player has been moving
    12 0001 23                          data id 18, one byte
    23 0001 00                          data id 35, one byte

**NetJoinData (id 1) IS THE TWENTY-BYTE MESSAGE**, not a position update, and sending it repeatedly
is what put a crowd of avatars in a real console's Union Room (sp47, sp48): every one is a fresh
player arriving. `JoinData` is `byte avatarId, byte colorId, byte cassetVersion, short InitRotY,
Vector3 InitPos`, and a real console sends avatar 8, colour 0, casset 0x31.

**NetPosData (id 2) is how a player MOVES**, and it is much cheaper: `ushort posX, ushort posZ,
short rotY` per point, several points to a message, on the unreliable stream. The game's own
conversion is `pos = (-posX * 0.05, posZ * 0.05)`, so a coordinate is a twentieth of a unit and X is
NEGATED. A trail decodes to the same place the join message named, which is what says the two
representations are the same player.

`docs/bdsp.md` "What the room says".
"""

import struct

HEADER_SIZE = 3

JOIN = 1                          # NetJoinData
POS = 2                           # NetPosData
DATA_ID_NAMES = {JOIN: "NetJoinData", POS: "NetPosData"}

JOIN_BODY_SIZE = 17
POS_POINT_SIZE = 6
POS_SCALE = 0.05                  # PosData.pos: -posX * 0.05, posZ * 0.05
POS_UNIT = 20.0                   # and the setter MULTIPLIES by 20 rather than dividing by 0.05 -
                                  # 10.35 / 0.05 truncates to 206 where 10.35 * 20 gives 207
KEEPALIVE = bytes.fromhex("0400020000")   # the unreliable stream every 2 s when nothing happens


def parse(data):
    """-> dict, one game message. The length is big-endian; everything inside it is not."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a game message is at least {HEADER_SIZE} bytes, got {len(data)}")
    data_id = data[0]
    length = struct.unpack_from(">H", data, 1)[0]
    body = data[HEADER_SIZE:HEADER_SIZE + length]
    out = {"data_id": data_id, "name": DATA_ID_NAMES.get(data_id, f"data id {data_id}"),
           "length": length, "body": body, "truncated": len(body) < length}
    if data_id == JOIN and len(body) >= JOIN_BODY_SIZE:
        out["join"] = parse_join_body(body)
    elif data_id == POS:
        out["points"] = parse_pos_body(body)
    return out


def parse_join_body(body):
    """`JoinData`: avatarId, colorId, cassetVersion, InitRotY, InitPos - C#'s own field order."""
    if len(body) < JOIN_BODY_SIZE:
        raise ValueError(f"a JoinData is {JOIN_BODY_SIZE} bytes, got {len(body)}")
    x, y, z = struct.unpack_from("<fff", body, 5)
    return {"avatar_id": body[0], "color_id": body[1], "casset_version": body[2],
            "rot_y": struct.unpack_from("<h", body, 3)[0], "x": x, "y": y, "z": z}


def parse_pos_body(body):
    """-> a list of {x, z, rot_y}, already through the game's own scaling."""
    out = []
    for i in range(len(body) // POS_POINT_SIZE):
        px, pz, rot = struct.unpack_from("<HHh", body, i * POS_POINT_SIZE)
        out.append({"x": -px * POS_SCALE, "z": pz * POS_SCALE, "rot_y": rot,
                    "raw": (px, pz)})
    return out


def build(data_id, body):
    return bytes([data_id & 0xFF]) + struct.pack(">H", len(body)) + bytes(body)


def build_join(x, y, z, rot_y=0, avatar_id=8, color_id=0, casset_version=0x31):
    """"A player has joined, here." The defaults are what a real console sends."""
    body = (bytes([avatar_id & 0xFF, color_id & 0xFF, casset_version & 0xFF])
            + struct.pack("<h", int(rot_y)) + struct.pack("<fff", float(x), float(y), float(z)))
    return build(JOIN, body)


def build_pos(points):
    """`points` is [(x, z, rot_y), ...]. X is negated and both scaled by 20, the way `PosData.pos`'s setter does it."""
    body = b"".join(struct.pack("<HHh", int(abs(x * POS_UNIT)), int(abs(z * POS_UNIT)), int(rot))
                    for x, z, rot in points)
    return build(POS, body)
