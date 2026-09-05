"""Encoder for the host's advertisement application_data = <Pia system header, 0x5C> <custom-base85(24-byte RFU record)>,
the inverse of transport._dump_beacon / _b85_decode. Record (LE): [0:2] trainer id, [2:10] name (FRLG charset,
0xFF-padded), [10:12] RFU session id, [12:20] partnerInfo, [20:24] game data (high u16 tradeSpecies, low u16 the
RfuGameData compatibility word). Only trainer id, name, session id and tradeSpecies are proven by the decoder; the
activity/hasCard bit positions are inferred.
"""

from . import charmap

PIA_HDR = 0x5C
RECORD_SIZE = 24

RFU_SERIAL_GAME = 0x0002
# The cable-club colosseum: Direct Corner -> Colosseum -> Single Battle searches with
# LINK_GROUP_SINGLE_BATTLE, whose accept list is this activity alone
# [sAcceptedActivityIds_SingleBattle, src/data/union_room.h:398].
ACTIVITY_BATTLE_SINGLE = 1
ACTIVITY_TRADE = 4
ACTIVITY_SEARCH = 12
ACTIVITY_WONDER_CARD = 21
ACTIVITY_WONDER_NEWS = 22
# A console standing in the Union Room advertises ACTIVITY_SEARCH and its search accepts only
# ACTIVITY_SEARCH back (sAcceptedActivityIds_Init, LINK_GROUP_UNION_ROOM_INIT; union_room.c sets it
# with SetHostRfuGameData(ACTIVITY_SEARCH, 0, FALSE)). Once players are in the room the resume search
# accepts IN_UNION_ROOM | activity instead (sAcceptedActivityIds_Resume). IN_UNION_ROOM is 1 << 6 and
# so fits inside SEARCH_ACTIVITY_MASK.
IN_UNION_ROOM = 1 << 6
LANGUAGE_ENGLISH = 2
VERSION_FIRE_RED = 4
HASCARD_BIT = 0x20                 # gname[0] |= 0x20 [union_room]

# Packed search-word positions in the record; hardware-proven.
SEARCH_WORD_OFFSET = 16
SEARCH_ACTIVITY_MASK = 0x007F
SEARCH_UNKNOWN_BIT7 = 0x0080
SEARCH_VERSION_MASK = 0x0700
SEARCH_VERSION_SHIFT = 8
SEARCH_LANGUAGE_MASK = 0x3800
SEARCH_LANGUAGE_SHIFT = 11
SEARCH_HAS_CARD = 0x4000
SEARCH_STARTED_ACTIVITY = 1 << 15

# Trading-board registration in the record. Hardware-proven 2026-09-03 by diffing one console's
# advertisement before and after it registered a Chansey lv26 asking for FEU (TYPE_FIRE = 10):
#   byte 22  0x00 -> 0x71   tradeSpecies low byte (113)
#   byte 19  0x01 -> 0x35   gender:1 | tradeLevel:7, the RfuGameData byte [include/link_rfu.h:112]
#   byte 18  0x03 -> 0x2b   tradeType:6 << 2; bits 0-1 unchanged (meaning unknown)
# Byte 23 proven u16b: we registered species 277 (Treecko), whose low byte alone is 21 (Spearow),
# and the console's board listed ARCKO -- so 22:24 is the little-endian tradeSpecies:10
# [include/link_rfu.h:107]. The same entry read "NORMAL" and "26", so all three fields are proven.
TRADE_BOARD_TYPE_OFFSET = 18
TRADE_BOARD_LEVEL_OFFSET = 19
TRADE_BOARD_SPECIES_OFFSET = 22
# include/constants/pokemon.h; 9 is TYPE_MYSTERY, unused for a request.
TYPE_NAMES = {
    "normal": 0, "fighting": 1, "flying": 2, "poison": 3, "ground": 4, "rock": 5, "bug": 6,
    "ghost": 7, "steel": 8, "fire": 10, "water": 11, "grass": 12, "electric": 13, "psychic": 14,
    "ice": 15, "dragon": 16, "dark": 17,
}


def set_trade_board(record, species, level, wanted_type):
    """Register (species, level) on the trading board, asking for wanted_type in return."""
    rec = bytearray(record)
    if not 0 <= species < 1024 or not 0 <= level < 128 or not 0 <= wanted_type < 64:
        raise ValueError("trade board fields out of range")
    rec[TRADE_BOARD_SPECIES_OFFSET:TRADE_BOARD_SPECIES_OFFSET + 2] = species.to_bytes(2, "little")
    rec[TRADE_BOARD_LEVEL_OFFSET] = (rec[TRADE_BOARD_LEVEL_OFFSET] & 0x01) | ((level & 0x7F) << 1)
    rec[TRADE_BOARD_TYPE_OFFSET] = (rec[TRADE_BOARD_TYPE_OFFSET] & 0x03) | ((wanted_type & 0x3F) << 2)
    return bytes(rec)


# Pia 6.16-6.41 system header (NintendoClients wiki LDN-Application-Data-(Pia)), big-endian; values confirmed from a
# real FRLG beacon. A zero-filled header is rejected by the console's Pia layer.
PIA_SYS_COMM_VERSION = 22
PIA_APP_COMM_VERSION = 88
PIA_NAME_UTF8, PIA_NAME_UTF16 = 1, 2


def _encode_pia_name(nickname, encoding):
    if encoding == PIA_NAME_UTF16:
        return (nickname or "").encode("utf-16-be")
    return (nickname or "").encode("utf-8")


def build_pia_header(*, sys_comm_ver=PIA_SYS_COMM_VERSION, app_comm_ver=PIA_APP_COMM_VERSION,
                     user_password=b"", player_limit_enabled=True, num_players=1, nickname="EMU",
                     name_encoding=PIA_NAME_UTF8):
    """92-byte big-endian Pia system header; everything after offset 0x5C is the game's application data."""
    name = _encode_pia_name(nickname, name_encoding)[:64]
    h = bytearray(PIA_HDR)
    h[0x00:0x02] = PIA_HDR.to_bytes(2, "big")                       # system property data size (0x5C)
    h[0x02] = sys_comm_ver & 0xFF                                   # system communication version
    h[0x03:0x05] = (app_comm_ver & 0xFFFF).to_bytes(2, "big")       # application communication version
    h[0x05:0x15] = bytes(user_password)[:16].ljust(16, b"\x00")     # user password (16)
    h[0x15] = 1 if player_limit_enabled else 0                      # is player limit enabled
    h[0x16] = num_players & 0xFF                                    # number of players
    h[0x17:0x1B] = len(name).to_bytes(4, "big")                     # player name size
    h[0x1B] = name_encoding & 0xFF                                  # player name encoding (1 UTF-8 / 2 UTF-16)
    h[0x1C:0x1C + len(name)] = name                                 # player name (64, null-padded)
    return bytes(h)


def decode_pia_header(header):
    h = bytes(header)[:PIA_HDR].ljust(PIA_HDR, b"\x00")
    name_size = int.from_bytes(h[0x17:0x1B], "big")
    enc = h[0x1B]
    raw_name = h[0x1C:0x1C + min(name_size, 64)]
    try:
        name = raw_name.decode("utf-16-be" if enc == PIA_NAME_UTF16 else "utf-8", "replace")
    except Exception:
        name = raw_name.hex()
    return {
        "size": int.from_bytes(h[0x00:0x02], "big"),
        "sys_comm_ver": h[0x02],
        "app_comm_ver": int.from_bytes(h[0x03:0x05], "big"),
        "user_password": h[0x05:0x15].hex(),
        "player_limit_enabled": h[0x15],
        "num_players": h[0x16],
        "name_size": name_size,
        "name_encoding": enc,
        "nickname": name,
    }


def _b85_char(digit):
    """Digit 0..84 -> alphabet byte 0x23.., skipping 0x5C."""
    c = 0x23 + (digit % 85)
    return c + 1 if c >= 0x5C else c


def b85_encode(data):
    """4-byte LE groups -> 5 base85 chars each, LOW digit first (inverse of transport._b85_decode)."""
    data = bytes(data)
    if len(data) % 4:
        data = data.ljust(len(data) + (4 - len(data) % 4), b"\x00")
    out = bytearray()
    for i in range(0, len(data), 4):
        v = int.from_bytes(data[i:i + 4], "little")
        for _ in range(5):
            out.append(_b85_char(v % 85))
            v //= 85
    return bytes(out)


def encode_name(name, width=8):
    return charmap.encode(name or "", width=width, pad=0xFF)


def game_data_word(*, trade_species=0, activity=ACTIVITY_WONDER_CARD, has_card=True,
                   language=LANGUAGE_ENGLISH, version=VERSION_FIRE_RED):
    """[20:24]: high u16 = tradeSpecies, low u16 = language:4 | version:4 | activity<<8 | hasCard. The low-u16 bit packing
    is inferred, not proven.
    """
    compat = (language & 0xF) | ((version & 0xF) << 4) | ((activity & 0x7F) << 8)
    if has_card:
        compat |= HASCARD_BIT
    return ((trade_species & 0xFFFF) << 16) | (compat & 0xFFFF)


def build_record(*, trainer_id, name, rfu_session_id, partner_info=b"", **game_data_kwargs):
    rec = bytearray(RECORD_SIZE)
    rec[0:2] = (trainer_id & 0xFFFF).to_bytes(2, "little")
    rec[2:10] = encode_name(name, width=8)
    rec[10:12] = (rfu_session_id & 0xFFFF).to_bytes(2, "little")
    rec[12:20] = bytes(partner_info)[:8].ljust(8, b"\x00")
    rec[20:24] = game_data_word(**game_data_kwargs).to_bytes(4, "little")
    return bytes(rec)


def build_beacon(*, trainer_id=0x2288, name="EMU", rfu_session_id=0x0002, pia_header=None,
                 partner_info=b"", nickname="EMU", sys_comm_ver=PIA_SYS_COMM_VERSION,
                 app_comm_ver=PIA_APP_COMM_VERSION, user_password=b"", name_encoding=PIA_NAME_UTF8,
                 **game_data_kwargs):
    """`pia_header` overrides the built header with a captured real one verbatim (the surest option)."""
    if pia_header is not None:
        header = bytes(pia_header)[:PIA_HDR].ljust(PIA_HDR, b"\x00")
    else:
        header = build_pia_header(sys_comm_ver=sys_comm_ver, app_comm_ver=app_comm_ver,
                                  user_password=user_password, nickname=nickname,
                                  name_encoding=name_encoding)
    record = build_record(trainer_id=trainer_id, name=name, rfu_session_id=rfu_session_id,
                          partner_info=partner_info, **game_data_kwargs)
    return header + b85_encode(record)


def mutate_beacon(captured_app_data, *, name=None, trainer_id=None, rfu_session_id=None,
                  **game_data_kwargs):
    """Clone a captured real host application_data, keeping its Pia header verbatim, and re-encode only the overridden
    record fields.
    """
    from .transport import _b85_decode
    captured = bytes(captured_app_data)
    header = captured[:PIA_HDR]
    rec = bytearray(_b85_decode(captured[PIA_HDR:])[:RECORD_SIZE].ljust(RECORD_SIZE, b"\x00"))
    if trainer_id is not None:
        rec[0:2] = (trainer_id & 0xFFFF).to_bytes(2, "little")
    if name is not None:
        rec[2:10] = encode_name(name, width=8)
    if rfu_session_id is not None:
        rec[10:12] = (rfu_session_id & 0xFFFF).to_bytes(2, "little")
    if game_data_kwargs:
        rec[20:24] = game_data_word(**game_data_kwargs).to_bytes(4, "little")
    return header + b85_encode(bytes(rec))
