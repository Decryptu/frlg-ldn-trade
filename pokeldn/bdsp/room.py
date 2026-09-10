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

# The three payloads whose C# struct is not blittable AND whose layout the wire has decided anyway.
# `netdata.OPAQUE` is a fact about the source; this is a fact about the marshalling, measured from
# captures and from `ANetData<T>$$ConvertStructToBytes`, and the other nine ids in OPAQUE have
# never been on the air at all (`scratchpad/bdsp_msgids.py`).
MEASURED = {
    0x02: "12 x PosData, 72 bytes: ushort posX, ushort posZ, short rotY",
    0x13: "one encrypted PB8 at stored size, 328 bytes, no length prefix",
    0x14: "694 bytes: RECORD 120, RANDOM_SEED 132, TvRecodeData 204, 4 x TV_STR_DATA 36, "
          "RECORD_HEAD 48, ten ints, six bytes",
    0x15: "143 bytes: byte count, is3D, template, then 20 x SealParam{short x, y, z; byte id}",
    0x22: "5 x StandbyData, 20 bytes: byte isAddPlayer, hostIndex, myIndex, langId",
    0x24: "26-byte name, u32 tranerId, byte cassetVersion, byte langId",
    0x38: "481 bytes: a 328-byte PB8, 20 x SealParam, u32 attachPokemonId, u32 attachPersonalRnd, "
          "byte index, num, is3DEditMode, isAppliedTemplate, affixSealCount",
    0x18: "616 bytes: short zoneID, posX, posY; byte direction, expansionStatus; int goodCount; "
          "30 x UgStoneStatue{int statueId, pedestalId, posX, posY, dir}; bool isEnable (4)",
    0x42: "26-byte name, byte genderid, byte languageId",
    0x54: "the same 616 bytes as 0x18",
    0x61: "8 bytes of dig-fossil ids, one per station",
}

RECODE = 0x14                     # NetDataRecodeData - the record-mixing payload
BALL_DECO = 0x15                  # NetDataAttachSealNetData - the ball-capsule payload
SEAL_SLOTS = 20
SEAL_SIZE = 7

# The marshalled size of every OPAQUE payload, read from the 1.3.0 executable's
# Il2CppTypeDefinitionSizes table (docs/bdsp_protocol.md "Framing"). Four are also on the wire.
NATIVE_SIZES = {
    0x02: 72, 0x13: 328, 0x14: 694, 0x15: 143, 0x18: 616, 0x22: 20, 0x24: 32, 0x29: 8,
    0x38: 481, 0x42: 28, 0x54: 616, 0x61: 8,
}

STANDBY_LIST = 0x22               # NetDataStandbyWaitListData - answers a request for 0x22
STANDBY_SLOTS = 5                 # UnionRoomManager$$SendStandbyPlayerData allocates the array
STANDBY_SIZE = 4

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
           "truncated": len(body) < length,
           "opaque": data_id in OPAQUE and data_id not in MEASURED}
    fields = parse_fields(data_id, body)
    if fields is not None:
        out["fields"] = fields
    if data_id == JOIN and len(body) >= JOIN_BODY_SIZE:
        out["join"] = parse_join_body(body)
    elif data_id == POS:
        out["points"] = parse_pos_body(body)
    elif data_id == STANDBY_LIST:
        out["standby"] = parse_standby_list(body)
    elif data_id == BALL_DECO and len(body) >= 3 + SEAL_SIZE:
        out["ball_deco"] = parse_ball_deco(body)
    elif data_id == RECODE and len(body) >= NATIVE_SIZES[RECODE]:
        out["recode"] = parse_recode_head(body)
    elif data_id == SELECT_POKEMON and len(body) >= NATIVE_SIZES[SELECT_POKEMON]:
        out["select_pokemon"] = parse_select_pokemon(body)
    elif data_id == TRADE_TRANER and len(body) == TRADE_TRANER_SIZE:
        out["traner"] = parse_trade_traner(body)
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


def parse_standby_list(body):
    """`StanbyListData`: five StandbyData{isAddPlayer, hostIndex, myIndex, langId}, one byte each.

    The sender fills slot i from the i-th entry of its standby list with isAddPlayer = 1 and
    hostIndex left 0 [1.3.0 main 0x01e52fa0]; an empty list is twenty zero bytes.
    """
    return [{"is_add_player": body[i], "host_index": body[i + 1], "my_index": body[i + 2],
             "lang_id": body[i + 3]}
            for i in range(0, min(len(body), STANDBY_SLOTS * STANDBY_SIZE), STANDBY_SIZE)]


def parse_ball_deco(body):
    """`BallDecoData`: count, is3DEditMode, isAppliedTemplate, then twenty SealParam."""
    seals = [dict(zip(("x", "y", "z", "seal_id"), struct.unpack_from("<hhhB", body, 3 + i * SEAL_SIZE)))
             for i in range(min(SEAL_SLOTS, (len(body) - 3) // SEAL_SIZE))]
    return {"count": body[0], "is_3d_edit": body[1], "is_template": body[2], "seals": seals}


def parse_recode_head(body):
    """The named fields of a `NetRecodeData` a reader wants first: the thirty RECORD counters,
    the names, the trainer id, the version. The full layout is on docs/bdsp_protocol.md."""
    counters = struct.unpack_from("<30I", body, 0)
    group = body[0x78:0x98].decode("utf-16-le", "replace").split("\0")[0]
    name = body[0x98:0xd8].decode("utf-16-le", "replace").split("\0")[0]
    sex, region, seed, random, stamp, user_id = struct.unpack_from("<iiQQqI", body, 0xd8)
    return {"counters": counters, "group_name": group, "name": name, "sex": sex,
            "region_code": region, "seed": seed, "random": random, "time_stamp": stamp,
            "user_id": user_id, "language": struct.unpack_from("<i", body, 0x274)[0],
            "unique_id": struct.unpack_from("<I", body, 0x280)[0], "version": body[0x2b0]}


SELECT_POKEMON = 0x38             # NetDataBattleMatchingSelectPokemon - one per team member


def parse_select_pokemon(body):
    """`BattleMatchingPokeData`: the encrypted PB8, then the seals, then the ids and the slot."""
    attach_id, attach_rnd, index, num, is_3d, template, count = struct.unpack_from("<IIBBBBB", body, 0x1d4)
    return {"pb8": body[:328], "seals": parse_ball_deco(b"\0\0\0" + body[0x148:0x1d4])["seals"],
            "attach_pokemon_id": attach_id, "attach_personal_rnd": attach_rnd, "index": index,
            "num": num, "is_3d_edit": is_3d, "is_template": template, "seal_count": count}


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


UG_JOIN = 0x16                    # NetUgJoinData - the Grand Underground's join record
ZONE = 0x17                       # NetZoneData - a station's zone and position, sent on arrival


def build_ug_join(x, y, z, zone_id, rot_y=0, avatar_id=0, color_id=0):
    """`UgJoinData`: avatarId, colorId, short zoneID, short InitRotY, Vector3 InitPos - 18 bytes,
    the fields `UgNetworkManager$$MakeJoinData` [1.3.0 main 0x01f79580] fills."""
    body = (bytes([avatar_id & 0xFF, color_id & 0xFF]) + struct.pack("<hh", int(zone_id), int(rot_y))
            + struct.pack("<fff", float(x), float(y), float(z)))
    return build(UG_JOIN, body)


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


TRADE_POKE_CHECK_OK = 0x46        # NetDataTradePokeCheckOkData - "I have looked at yours and
                                  # it is fine". sp85 got `46 00 01 01` after sending a Pokemon:
                                  # the first message in this project's history that no capture had
                                  # ever held AND that says the console ACCEPTED something we made.
TRADE_READY_OK = 0x21             # NetDataTradeReadyOkData - the step after, and the one that
                                  # leads to the exchange itself. IT IS THE LINE: past it the
                                  # console writes its save. `build_trade_ready_ok` below.
TRADE_TRANER = 0x24               # NetDataTradeTranerData - who the player trading with us IS
TRADE_POKE = 0x13                 # NetTradePokeData - and a whole Pokemon, 328 bytes
RETURN_SELECT = 0x45              # NetDataReturnSelectData - THE MESSAGE ON THE FAR SIDE OF A
                                  # COMPLETED TRADE. sp92 and sp93 both ended with the console
                                  # sending `45 00 01 00` once a second (78 and 50 times) until our
                                  # station left. `build_fields(RETURN_SELECT, 1)` answers it.
                                  #
                                  # NOTHING IN dump_base EXPLAINS IT. The base game has no such
                                  # type, no such method and not even the string - it is one of the
                                  # 41 messages 1.3.0 added, and the console runs 1.3.0. The only
                                  # reading available is opendpr's signature,
                                  # `TradeSelectPokeModel$$SendReturnSelectPoke(bool received)`,
                                  # which makes the byte "received" and 1 the answer. HYPOTHESIS,
                                  # from a parameter name; there is no code to check it against.


def parse_trade_traner(body):
    """-> the player's own trade record. 32 bytes, and every one of them is accounted for.

    `TradeTranerData` is `string tranerName; uint tranerId; byte cassetVersion; byte langId`, and
    `ANetData<T>$$ConvertStructToBytes` [main.bin 0x27bb0e0] puts it on the wire through
    `Marshal.SizeOf`, `Marshal.AllocHGlobal` and `Marshal.StructureToPtr`, so the payload IS the
    marshalled struct, in declaration order, packed:

        0x00  26  tranerName, UTF-16LE, NUL-terminated
        0x1a   4  tranerId, the full 32-bit id - secret id in its high half
        0x1e   1  cassetVersion
        0x1f   1  langId

    Four fields, 26 + 4 + 1 + 1 = 32, and nothing left over. THE READING CHECKS ITSELF against the
    encrypted PB8 of the same trade: 0x1a..0x1d is 0x0FF0ADB2, which is that Pokemon's trainer id
    44466 and secret id 4080; 0x1e is 49, its `version`; 0x1f is 3, its `language`. Two independent
    messages agreeing on four fields.

    THE TEN BYTES PAST THE STRING'S TERMINATOR CARRY NOTHING. `AllocHGlobal` does not clear its
    block and marshalling a string into a fixed field writes the characters and one terminator, so
    what follows is whatever was in the heap - which is why 0x14 was 107540 in nine runs, 44 in
    sp88 and 60 in sp94 while every declared field held still. `slack` is those bytes as hex, and
    a record we build sends the console's own so that ours differs from a real one only where we
    meant it to.
    """
    if len(body) != TRADE_TRANER_SIZE:
        raise ValueError(f"{len(body)} bytes, expected {TRADE_TRANER_SIZE}")
    trainer_id32, casset, lang = struct.unpack_from("<IBB", body, 26)
    return {"name": body[0:TRADE_TRANER_NAME_SIZE].decode("utf-16-le").split("\x00")[0],
            "trainer_id32": trainer_id32,
            "trainer_id": trainer_id32 & 0xFFFF, "secret_id": trainer_id32 >> 16,
            "casset_version": casset, "lang_id": lang,
            "slack": bytes(body[16:26]).hex()}


TRADE_TRANER_SIZE = 32
TRADE_TRANER_NAME_SIZE = 26       # by subtraction: the other three fields are 6 bytes

# the console's own heap residue at 0x10, which a record we send carries so that it differs from
# a real one only in the fields that mean something
CONSOLE_SLACK = bytes.fromhex("18a4010014a4010000 00".replace(" ", ""))


def build_trade_poke(pb8):
    """"here is my Pokemon" - a NetTradePokeData carrying an encrypted 328-byte PB8.

    `UnionTradeManager$$RecivePokeData` [main.bin 0x1dd2800] takes it only when the manager's own
    state field is 1, stores it at `[this+0x28]+0x68` and raises a flag at +0x70, so the message is
    accepted in one phase and ignored in every other. `pokeldn.bdsp.pokemon` builds the payload.
    """
    if len(pb8) != 328:
        raise ValueError(f"{len(pb8)} bytes, expected a 328-byte PB8")
    return build(TRADE_POKE, pb8)


def build_trade_traner(name, trainer_id, secret_id, casset_version=0x31, lang_id=3,
                       slack=CONSOLE_SLACK):
    """"and here is who I am" - the marshalled 32-byte record.

    The defaults are a French BDSP console's own: `cassetVersion` 0x31 and `langId` 3 are the
    `version` and `language` the console's Pokemon carry, and `slack` is the heap residue a real
    record happened to have behind its name.
    """
    encoded = name.encode("utf-16-le")
    if len(encoded) + 2 > TRADE_TRANER_NAME_SIZE:
        raise ValueError(f"{name!r} is too long for the {TRADE_TRANER_NAME_SIZE}-byte name field")
    if len(slack) != 10:
        raise ValueError(f"{len(slack)} bytes of slack, expected 10")
    trainer_id32 = (trainer_id & 0xFFFF) | ((secret_id & 0xFFFF) << 16)
    return build(TRADE_TRANER,
                 encoded.ljust(16, b"\x00") + bytes(slack)
                 + struct.pack("<IBB", trainer_id32, casset_version & 0xFF, lang_id & 0xFF))


# `TradeStateModel.TradeState` [dump.cs:258737]. The union-room flow only ever uses WAIT, which is
# what a "ready" means here - the state machine that uses the rest of the enum is the one created
# AFTER the handshake, on the other side of the save.
TRADE_STATE_NONE = 0
TRADE_STATE_INIT = 1
TRADE_STATE_WAIT = 2
TRADE_STATE_SEND_POKE = 3
TRADE_STATE_WAIT_POKE = 4
TRADE_STATE_SEND_READYOK = 5
TRADE_STATE_WAIT_READYOK = 6
TRADE_STATE_START_WRITE_SAVE = 7
TRADE_STATE_WRITEING_SAVE = 8


TRADE_STATE_NAMES = {
    TRADE_STATE_NONE: "NONE", TRADE_STATE_INIT: "INIT", TRADE_STATE_WAIT: "WAIT",
    TRADE_STATE_SEND_POKE: "SEND_POKE", TRADE_STATE_WAIT_POKE: "WAIT_POKE",
    TRADE_STATE_SEND_READYOK: "SEND_READYOK", TRADE_STATE_WAIT_READYOK: "WAIT_READYOK",
    TRADE_STATE_START_WRITE_SAVE: "START_WRITE_SAVE", TRADE_STATE_WRITEING_SAVE: "WRITEING_SAVE",
    9: "END_SAVE", 10: "END", 11: "ERROR",
}


def mirror_trade_state(their_state):
    """-> the state to claim back, so that THEIR machine advances.

    `TradeParentStateModel$$StateProc` [main.bin 0x1cd1790] switches on `currentState - 2` through
    a ten-entry table at 0x3b8d50b, and every case advances on something WE control:

        2 WAIT          targetState == WAIT          -> 3 SEND_POKE
        3 SEND_POKE     sends its own Pokemon        -> 4 WAIT_POKE
        4 WAIT_POKE     targetPokeData is non-null   -> 5 SEND_READYOK   (our NetTradePokeData)
        5 SEND_READYOK  tradeParent == PARENT        -> 6 WAIT_READYOK
        6 WAIT_READYOK  waitRndTime runs out AND targetIsTradeReadyOk   -> 7 START_WRITE_SAVE
        7 START_WRITE_SAVE  WriteSaveData -> ReplacePoke                -> 8 WRITEING_SAVE
        8 WRITEING_SAVE     CheckReplacePokeData                        -> 10 END
       10 END          PlayerSave, close the window, currentState = 0

    So INIT is answered with WAIT rather than echoed: `ReciveState`'s INIT case sets their state to
    WAIT and records ours as `targetState` in the same call, so a WAIT here saves the round trip
    that an echo would cost. From SEND_READYOK on, the value stops mattering and only the ARRIVAL
    does - state 6 sets `targetIsTradeReadyOk` for any message that reaches it - so it is held at
    SEND_READYOK rather than chasing states we cannot be in.
    """
    if their_state <= TRADE_STATE_INIT:
        return TRADE_STATE_WAIT
    if their_state >= TRADE_STATE_SEND_READYOK:
        return TRADE_STATE_SEND_READYOK
    return their_state


def build_trade_ready_ok(trade_state=TRADE_STATE_WAIT, is_trade_ok=0):
    """"I am ready" - AND IT IS THE MESSAGE THAT LETS THE CONSOLE WRITE ITS SAVE.

    ONE BYTE OF IT IS READ. `TradeSelectPokeModel$$ReciveReadyOk` [main.bin 0x1cd4860] is three
    instructions - `ldrb w8, [x1, #0x11]; str w8, [x0, #0x78]; ret` - so the SECOND field,
    `tradeState`, becomes `targetTradeState` and `isTradeOk` is never looked at. The console's own,
    in sp87, was `{isTradeOk 0, tradeState 2}`, and 0 is kept as the default for the field the game
    ignores so that ours is byte-identical to it: sp87's message is `21 00 02 00 02` in
    `scratchpad/sp87_pia.jsonl` and `build_trade_ready_ok()` produces those five bytes.

    WHAT IT DOES. `UnionTradeManager.<WaitBoxWindowComplete>d__24$$MoveNext` [0x1dd3780] waits for
    `myTradeState == WAIT` (the player's own `MyReadyOk` sets that) AND `targetTradeState == WAIT`,
    which has no other writer in the image. Both at WAIT and it sets
    `UnionTradeManager.currentState = SECURIY_TRADE`, clears the select model and sends its own
    0x21 back carrying zero. From there `TradeSecurityController` -> `CreateTradeStateModel` ->
    `TradeStateModel$$InitState`, whose first instruction after the prologue is `PlayerSave`.

    So the console cannot leave SELECT_WINDOW without this message, and it writes a save shortly
    after it. `bin/bdsp_connect.py` gates it behind `--complete-trade`, off by default.
    docs/bdsp.md "Where it stops, and why".
    """
    return build_fields(TRADE_READY_OK, is_trade_ok & 0xFF, trade_state & 0xFF)


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
