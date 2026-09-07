"""BDSP's OWN protocol, above Pia - the messages the Union Room is made of.

The game runs a typed protocol of its own inside the Pia payloads, and `TeamLumi/opendpr` names
every message in it: `Dpr.NetworkUtils.NetDataParser` registers 65 classes, each an `ANetData<T>`
with a `DataID` byte, and each `T` is a plain struct. Reading that beat guessing by a wide margin -
the six bytes this module first called "a fixed head" are three struct fields and a length.
`pokeldn.bdsp.netdata` is the generated table; this is what encodes and decodes.

THE FRAMING, and it fits every payload ever captured:

    0x0  1  data id
    0x1  2  payload length, BIG-endian
    0x3  .  payload - the struct, little-endian and PACKED

    01 0011 08 00 31 5a00 <x><y><z>     NetJoinData    "a player has joined, here"
    02 0048 <12 x 6 bytes>              NetPosData     where a player has been moving
    12 0001 23                          NetRequestData     "send me your data id 0x23"
    23 0001 00                          NetDataIsMatchWaitData  "I am not waiting for a match"

PACKED IS MEASURED, NOT ASSUMED. `JoinData` is byte, byte, byte, short, Vector3, which is 17 bytes
packed and 20 aligned - and the console's own message is 17, with the short at offset 3. Every
payload in every capture agrees with the packed reading, so the whole table decodes on it.

**NetJoinData (id 1) IS THE TWENTY-BYTE MESSAGE**, not a position update, and sending it repeatedly
is what put a crowd of avatars in a real console's Union Room (sp47, sp48): every one is a fresh
player arriving. A real console sends avatar 8, colour 0, casset 0x31.

**NetPosData (id 2) is how a player MOVES**, and it is much cheaper: `ushort posX, ushort posZ,
short rotY` per point, several points to a message, on the unreliable stream. The game's own
conversion is `pos = (-posX * 0.05, posZ * 0.05)`, so a coordinate is a twentieth of a unit and X is
NEGATED. THE TWELVE POINTS ARE A SPAN, not a burst: they are where the player HAS BEEN since the
last message, so a walk is one message per stride with the strides interpolated across it. sp57 sent
twelve points 0.008 apart and the avatar crept and then jumped, which is what `pos_span` fixes.

**THE TWO MESSAGES THE CONSOLE HAS BEEN REPEATING SINCE THE FIRST JOIN ARE A QUESTION AND ITS OWN
ANSWER.** `12 0001 23` is `NetRequestData{RequestDataID = 0x23}` and 0x23 is itself a data id -
`OpcManager._RequestNetDataCallback` is an `Action<byte>`, so a request names the message it wants -
and `23 0001 00` is the console answering its own: `NetDataIsMatchWaitData{isMatchWait = 0}`, "I am
not waiting to be matched". Nothing this project has sent has ever answered a request.

`docs/bdsp.md` "What the room says".
"""

import struct

from pokeldn.bdsp.netdata import FIELDS, NAMES, OPAQUE

HEADER_SIZE = 3

JOIN = 0x01                       # NetJoinData
POS = 0x02                        # NetPosData
EMOTION = 0x03                    # NetEmotionData
STATE = 0x04                      # NetCharacterStateData
TRAINER_CARD = 0x05               # NetDataTranerCardData
REQUEST = 0x12                    # NetRequestData - "send me your <data id>"
MATCH_WAIT = 0x23                 # NetDataIsMatchWaitData
PLAYER_NAME = 0x42                # NetPlayerNameData - a string, so the layout is NOT known

JOIN_BODY_SIZE = 17
POS_POINT_SIZE = 6
POS_POINTS = 12                   # what a console puts in one message; 12 * 6 is the 0x48 captured
POS_SCALE = 0.05                  # PosData.pos: -posX * 0.05, posZ * 0.05
POS_UNIT = 20.0                   # and the setter MULTIPLIES by 20 rather than dividing by 0.05 -
                                  # 10.35 / 0.05 truncates to 206 where 10.35 * 20 gives 207
KEEPALIVE = bytes.fromhex("0400020000")   # the unreliable stream every 2 s when nothing happens

# The name this project used before opendpr named them, kept so an old log still reads.
DATA_ID_NAMES = {ident: name for ident, (name, _) in NAMES.items()}


def name(data_id):
    """-> the game's own class name for a data id, or a bare description of the number."""
    known = NAMES.get(data_id)
    return known[0] if known else f"data id {data_id:#04x}"


def layout(data_id):
    """-> the struct format for a payload, or None when its struct is not blittable.

    A `None` is a real answer: `NetPlayerNameData` carries a C# string and `NetPosData` an array,
    and neither has a layout the source decides. They are named in `netdata.OPAQUE`.
    """
    fields = FIELDS.get(data_id)
    return "<" + "".join(fmt for _, _, fmt in fields) if fields else None


def parse(data):
    """-> dict, one game message. The length is big-endian; everything inside it is not."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a game message is at least {HEADER_SIZE} bytes, got {len(data)}")
    data_id = data[0]
    length = struct.unpack_from(">H", data, 1)[0]
    body = data[HEADER_SIZE:HEADER_SIZE + length]
    out = {"data_id": data_id, "name": name(data_id), "length": length, "body": body,
           "truncated": len(body) < length, "opaque": data_id in OPAQUE}
    fields = parse_fields(data_id, body)
    if fields is not None:
        out["fields"] = fields
    if data_id == JOIN and len(body) >= JOIN_BODY_SIZE:
        out["join"] = parse_join_body(body)
    elif data_id == POS:
        out["points"] = parse_pos_body(body)
    return out


def parse_fields(data_id, body):
    """-> {name: value} for any payload the generated table gives a layout, else None."""
    fmt = layout(data_id)
    if fmt is None or len(body) < struct.calcsize(fmt):
        return None
    values, out = struct.unpack_from(fmt, body), {}
    i = 0
    for field, _, sub in FIELDS[data_id]:
        count = len(struct.unpack("<" + sub, bytes(struct.calcsize("<" + sub))))
        out[field] = values[i] if count == 1 else values[i:i + count]
        i += count
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


def build_fields(data_id, *values):
    """Pack a payload from the generated layout. Raises on an id whose struct is not blittable."""
    fmt = layout(data_id)
    if fmt is None:
        raise ValueError(f"{name(data_id)} has no layout this table can decide "
                         f"({OPAQUE.get(data_id, 'unknown')} is not blittable)")
    return build(data_id, struct.pack(fmt, *values))


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


def pos_span(start, end, rot_y, points=POS_POINTS):
    """-> the points for ONE NetPosData covering a whole stride, endpoint included.

    THE TWELVE POINTS SPAN THE MOVEMENT SINCE THE LAST MESSAGE. sp57 sent twelve points 0.008 apart
    and then jumped 0.1 to the next message's first point, so the avatar crept and stuttered across
    the room; the fix is not to send more messages but to make each one describe the stride it
    covers. `start` and `end` are (x, z).
    """
    if points < 1:
        raise ValueError("a NetPosData carries at least one point")
    (x0, z0), (x1, z1) = start, end
    last = max(points - 1, 1)
    return [(x0 + (x1 - x0) * i / last, z0 + (z1 - z0) * i / last, rot_y) for i in range(points)]


def build_request(requested_id):
    """"Send me your <data id>." `RequestData.RequestDataID` is itself one of these ids."""
    return build_fields(REQUEST, requested_id & 0xFF)


def build_match_wait(is_waiting=False):
    """The console's own repeated answer is 0 - "I am not waiting to be matched"."""
    return build_fields(MATCH_WAIT, 1 if is_waiting else 0)


# `StateData.state` is an `OpcState.OnlineState` [opendpr:Assets/Scripts/OpcState.cs] - a short
# enum, copied rather than generated because nothing in the message table references it by type.
# NONE is what a character standing still is; the RECRUITMENT_* values are what a player advertising
# itself for a battle or a trade sends, and `OpcState.IsCanTalkState()` reads this field, so it is
# what decides whether the game lets the player talk to an avatar at all.
STATE_NONE = 0
STATE_RECRUITMENT_BATTLE = 3
STATE_RECRUITMENT_TRADE = 4
STATE_RECRUITMENT_RECORD = 5
STATE_RECRUITMENT_GREETINGS = 6
STATE_RECRUITMENT_BALL_DECORATION = 7
STATE_COMMUNICATE = 8
STATE_NAMES = {0: "NONE", 1: "DIG_FOSILL", 2: "SECRETBASE_ACTION", 3: "RECRUITMENT_BATTLE",
               4: "RECRUITMENT_TRADE", 5: "RECRUITMENT_RECORD", 6: "RECRUITMENT_GREETINGS",
               7: "RECRUITMENT_BALL_DECORATION", 8: "COMMUNICATE", 9: "LIKES", 10: "CROSS",
               11: "EXCLAMATION", 12: "TOGETHER", 13: "GET", 14: "NOW_DIG_FOSILE", 15: "NOW_MENU",
               16: "NOW_BATTLE", 17: "NOW_BATTLE_UNION", 18: "NOW_TRADE", 19: "NOW_RECORD",
               20: "NOW_GREETINGS", 21: "NOW_BALL_DECORATION", 22: "_NULL"}


def build_state(state=STATE_NONE, is_recruitment=0):
    """`StateData`: what the character is doing, and whether it is recruiting.

    THE DEFAULT IS THE NEUTRAL ANSWER - a character standing in the room doing nothing. It is what
    a request for 0x04 is answered with until there is a reason to say anything else.
    """
    return build_fields(STATE, state & 0xFF, is_recruitment & 0xFF)


def build_emotion(emotion_id):
    return build_fields(EMOTION, emotion_id & 0xFF)


def answer(message):
    """-> the reply a NetRequestData asks for, when this module can build one, else None.

    The console has been asking for 0x23 since the first join and has never been answered. An
    answer is buildable whenever the requested id has a layout; a request for an OPAQUE one is
    named in the return so a caller can say what it could not answer.
    """
    if message.get("data_id") != REQUEST or not message.get("fields"):
        return None
    wanted = message["fields"]["RequestDataID"]
    if wanted == MATCH_WAIT:
        return build_match_wait(False)
    if wanted == STATE:
        return build_state()
    if layout(wanted) is None:
        return None
    return build(wanted, bytes(struct.calcsize(layout(wanted))))
