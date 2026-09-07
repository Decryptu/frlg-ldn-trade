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

**THE STREAM DECIDES THE STREAM.** All 4333 requests for 0x23 arrived on the RELIABLE protocol and
all 55 requests for 0x04 on the UNRELIABLE one, with no crossover in nineteen runs - so a request is
answered on the protocol it came in on, which is also where the console puts its own answer.

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
TALK = 0x06                       # NetDataTalkData{talkOpcSexId, talkState} - and talkState
                                  # CHECK (0) is a NULL DEREFERENCE in the receiver unless a
                                  # message window is already open. sp80/sp81 crashed on it.
TALK_RESERVE = 0x63               # NetDataTalkReserveData - "I want to talk to your character"
TALK_RESERVE_RESULT = 0x64        # NetDataTalkReserveResultData - and the answer that unblocks it
PLAYER_NAME = 0x42                # NetPlayerNameData - a string, so the layout is NOT known

JOIN_BODY_SIZE = 17
POS_POINT_SIZE = 6
POS_POINTS = 12                   # what a console puts in one message; 12 * 6 is the 0x48 captured

# HOW A REAL PLAYER WALKS, measured over 80 of the console's own NetPosData messages. Our first
# walks moved 0.15 units every 0.6 s - a ninth of this - which is the whole of sp57's and sp59's
# "stutter": twelve points crossing a sixth of a step and then a pause. Match the console.
POS_PERIOD = 0.41                 # seconds between messages; median gap, min 0.20 max 1.59
POS_STRIDE = 0.93                 # units one message spans; median, max 2.60
POS_SCALE = 0.05                  # PosData.pos: -posX * 0.05, posZ * 0.05
POS_UNIT = 20.0                   # and the setter MULTIPLIES by 20 rather than dividing by 0.05 -
                                  # 10.35 / 0.05 truncates to 206 where 10.35 * 20 gives 207
# WHAT THIS PROJECT CALLED A KEEPALIVE IS A MESSAGE. `04 00 02 00 00` is data id 4, big-endian
# length 2, body `00 00` - `NetCharacterStateData{state: NONE, isRecruiment: 0}`, the console
# broadcasting its own character's state every two seconds. It was named before the table existed.
# Every one of the 968 unreliable payloads in the archive is a whole game message and 853 are this.
STATE_NONE_MESSAGE = bytes.fromhex("0400020000")
KEEPALIVE = STATE_NONE_MESSAGE            # the old name, kept so an old log still reads

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


def build_trainer_card(fashion_id=0, body_type=0, gender_id=0, lang_id=2, trainer_rank=1,
                       trainer_id=0, money=0, zukan_count=0, play_time_hour=1, play_time_minute=0):
    """`NetDataTranerCardData`: 75 blittable bytes of appearance and trainer card.

    NO CONSOLE HAS EVER SENT ONE in this project's 42 captures - the only game messages any capture
    holds are 0x01, 0x04, 0x12 and 0x23 - so there is no template and every byte here comes from
    opendpr's field list rather than from the wire. The first four fields are the ones the screen
    can answer: fashionId, bodyType, genderid and langId are what an avatar LOOKS like.
    `docs/bdsp.md`.
    """
    return build_fields(TRAINER_CARD,
                        fashion_id & 0xFF, body_type & 0xFF, gender_id & 0xFF, lang_id & 0xFF,
                        trainer_rank & 0xFF,
                        0,                                  # cardData.startTime, a long
                        trainer_id & 0xFFFFFFFF, money & 0xFFFFFFFF, zukan_count & 0xFFFFFFFF,
                        0, 0, 0, 0, 0,                      # style/beatiful/cute/clever/strong rank
                        0, 0, 0, 0,                         # the four renshou streaks
                        0,                                  # clearTime
                        0,                                  # digFossilPlayCount, a short
                        play_time_hour & 0xFFFF, play_time_minute & 0xFFFF,
                        0, 0, 0, 0)                         # tagIndex, isZukanGet, cooking, statues


def build_request(requested_id):
    """"Send me your <data id>." `RequestData.RequestDataID` is itself one of these ids."""
    return build_fields(REQUEST, requested_id & 0xFF)


TRADE_TRANER = 0x24               # NetDataTradeTranerData - who the player trading with us IS
TRADE_POKE = 0x13                 # NetTradePokeData - and a whole Pokemon, 328 bytes


def parse_trade_traner(body):
    """-> the player's own trade record. 32 bytes, READ OFF THE WIRE - opendpr gives it no layout.

    `netdata.OPAQUE` lists this id because its C# struct holds a string, so the generated table
    cannot decide a layout for it. The console sent one in sp82 and it reads cleanly, and the
    reading CHECKS ITSELF: the trainer id and secret id sit in the clear at 0x1a and 0x1c and are
    the same pair carried inside the encrypted PB8 of the same trade (44466 / 4080), which is two
    independent messages agreeing.

        0x00  name, 8 UTF-16LE code units, null padded
        0x10  u32   107544        unidentified, and adjacent - they differ by 4
        0x14  u32   107540
        0x18  u16   0
        0x1a  u16   trainer id
        0x1c  u16   secret id
        0x1e  u16   817
    """
    if len(body) != TRADE_TRANER_SIZE:
        raise ValueError(f"{len(body)} bytes, expected {TRADE_TRANER_SIZE}")
    a, b, c, tid, sid, tail = struct.unpack_from("<IIHHHH", body, 16)
    return {"name": body[0:16].decode("utf-16-le").split("\x00")[0],
            "unknown_10": a, "unknown_14": b, "unknown_18": c,
            "trainer_id": tid, "secret_id": sid, "unknown_1e": tail}


TRADE_TRANER_SIZE = 32


def build_talk_reserve(body_byte=0):
    """"I want to talk to your character" - the message the player who WALKS UP sends.

    Every run to sp78 had our character advertising and the console's player approaching it, which
    makes us the responder. The roles are the other way round when the CONSOLE puts an emote up:
    picking one locks the player in place waiting to be interacted with, so the approach has to
    come from us. This is that approach.

    The console's own is `63 00 01 00` in sp70-sp76 - one body byte, zero - and `NetDataTalkReserveData`
    is not in the generated FIELDS table (opendpr declares no layout for it), so this builds the
    console's own bytes rather than packing a struct.
    """
    return build(TALK_RESERVE, bytes([body_byte & 0xFF]))


def build_match_wait(is_waiting=False):
    """The console's own repeated answer is 0 - "I am not waiting to be matched".

    AND 1 IS THE ONLY VALUE THAT STARTS A TRADE. `UnionRoomManager$$SetNetData`'s branch for this
    id ends in one comparison [main.bin 0x01fd56e4]:

        ldrb w23, [x19, #0x10]      isMatchWait, off the received message
        cmp  w23, #1
        b.ne 0x1fd5704              anything but 1 skips the rest
        bl   UnionFrontDeskTradeController$$StartMatch

    The console has requested this id since the first join of session 46 and every run has answered
    0 - a station saying it does not want to be matched. That is the `StateData{NONE, 0}` mistake
    again: the right question, answered with a no-op. `docs/bdsp.md`.
    """
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


def build_talk_reserve_result(can_talk=1, is_recruitment=1, emoticon_state=STATE_NONE):
    """`NetDataTalkReserveResultData`: the answer to a console asking to talk to our character.

    sp70 IS WHERE THIS CAME FROM. A character reporting `StateData{RECRUITMENT_TRADE, 1}` showed a
    speech bubble, the player pressed A on him, and the console sent `63 00 01 00` - a
    `NetDataTalkReserveData`, a message no capture in this project had ever held. Nothing answered
    it and THE PLAYER'S OWN CHARACTER FROZE until the game was rebooted: the talk is a
    request/response and the console waits on ours.

    `IsCanTalk` is the field that decides it. `emoticonStateType` is an `OpcState.OnlineState`,
    the same enum `build_state` takes.
    """
    return build_fields(TALK_RESERVE_RESULT, can_talk & 0xFF, is_recruitment & 0xFF,
                        emoticon_state & 0xFF)


def build_emotion(emotion_id):
    return build_fields(EMOTION, emotion_id & 0xFF)


def answer(message, state=STATE_NONE, is_recruitment=0, match_wait=False):
    """-> the reply a NetRequestData asks for, when this module can build one, else None.

    The console has been asking for 0x23 since the first join and has never been answered. An
    answer is buildable whenever the requested id has a layout; a request for an OPAQUE one is
    named in the return so a caller can say what it could not answer.

    THE STATE IS THE PART THAT MEANS SOMETHING. sp63 and sp64 answered the console's request for
    0x04 and NOTHING CHANGED on screen, which was written down as "answering does nothing" - but
    both answered `StateData{NONE, 0}`, which is the character saying it is doing nothing. `state`
    is `OpcState.OnlineState`, and the RECRUITMENT_* values are what a Union Room player showing a
    speech bubble is in: `OpcController.ShowEmoticon(OnlineState)` and `GetEmoticonType(state)`
    both read it. A negative result measured with a no-op payload is not a negative result.
    """
    if message.get("data_id") != REQUEST or not message.get("fields"):
        return None
    wanted = message["fields"]["RequestDataID"]
    if wanted == MATCH_WAIT:
        return build_match_wait(match_wait)
    if wanted == STATE:
        return build_state(state, is_recruitment)
    if layout(wanted) is None:
        return None
    return build(wanted, bytes(struct.calcsize(layout(wanted))))
