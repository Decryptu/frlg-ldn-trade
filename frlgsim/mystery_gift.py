"""Pure Mystery Gift protocol constants [decomp:src/mystery_gift_link.c, include/mystery_gift.h].
We are the server (RFU parent, link player 0); the console runs MysteryGiftClient as link player 1."""

# MysteryGiftLink message idents [include/mystery_gift_link.h:8-22].
MG_LINKID_CLIENT_SCRIPT = 16    # server -> client: client-script instruction array
MG_LINKID_GAME_DATA = 17        # client -> server: struct MysteryGiftLinkGameData
MG_LINKID_GAME_STAT = 18
MG_LINKID_RESPONSE = 19         # client -> server: a u32 yes/no/toss answer
MG_LINKID_READY_END = 20        # size=0 request expands to a 1024-byte wire payload
MG_LINKID_DYNAMIC_MSG = 21      # server -> client: a 64-byte live message
MG_LINKID_CARD = 22             # server -> client: struct WonderCard (332 B)
MG_LINKID_NEWS = 23             # server -> client: struct WonderNews (444 B)
MG_LINKID_STAMP = 24
MG_LINKID_RAM_SCRIPT = 25       # server -> client: raw event-script bytecode (the delivery script)
MG_LINKID_EREADER_TRAINER = 26

MG_LINK_BUFFER_SIZE = 0x400     # AllocZeroed size of the client's send/recv/script buffers
MG_LINK_HEADER_SIZE = 6         # {u16 ident; u16 crc; u16 size}
MG_LINK_MAX_CHUNK = 252         # each SendBlock chunk, asserted <= 252 [link_rfu_2.c:1336]

# MysteryGiftLinkGameData validation magic [src/mystery_gift.c].
GAME_DATA_VALID_VAR = 0x101     # data->unk_00
VERSION_CODE_FIRERED = 1
VERSION_CODE_LEAFGREEN = 2

# Wonder Card enums checked by ValidateWonderCard [mystery_gift.c:191].
CARD_TYPE_GIFT = 0
CARD_TYPE_STAMP = 1
CARD_TYPE_LINK_STAT = 2
CARD_TYPE_COUNT = 3

SEND_TYPE_DISALLOWED = 0        # cannot be shared onward
SEND_TYPE_ALLOWED = 1           # can be shared once (auto-flips to DISALLOWED)
SEND_TYPE_ALLOWED_ALWAYS = 2

NUM_WONDER_BGS = 8              # bgType must be < this
MAX_STAMP_CARD_STAMPS = 7      # maxStamps must be <= this

WONDER_CARD_FLAG_OFFSET = 1000  # flagId = WONDER_CARD_FLAG_OFFSET + index into sReceivedGiftFlags
NUM_WONDER_CARD_FLAGS = 20      # 1 + FLAG_WONDER_CARD_UNUSED_17 - FLAG_RECEIVED_AURORA_TICKET

# Receipt event flags gated by the card flagId (sReceivedGiftFlags, mystery_gift.c:30).
FLAG_RECEIVED_AURORA_TICKET = 0x2A7
FLAG_RECEIVED_MYSTIC_TICKET = 0x2A8
FLAG_RECEIVED_OLD_SEA_MAP = 0x2A9
FLAG_WONDER_CARD_UNUSED_1 = 0x2AA   # first free slot


def crc16(data):
    """CalcCRC16WithTable [decomp:src/util.c:250]: reflected CRC16, init 0x1121, poly 0x8408, final
    one's-complement; used for every MysteryGiftLink message header."""
    crc = 0x1121
    for b in bytes(data):
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
    return (~crc) & 0xFFFF


def _crc16_table():
    """gCrc16Table [decomp:src/util.c:77]."""
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if (c & 1) else (c >> 1)
        table.append(c & 0xFFFF)
    return table


def _crc16_tabledriven(data):
    """Exact port of CalcCRC16WithTable [decomp:src/util.c:250]; the self-test checks crc16() against it."""
    table = _crc16_table()
    crc = 0x1121
    for b in bytes(data):
        hi = crc >> 8
        crc ^= b
        crc = (hi ^ table[crc & 0xFF]) & 0xFFFF
    return (~crc) & 0xFFFF


def _selftest():
    for sample in (b"", b"\x00", b"GameFreak inc.", bytes(range(256)), b"\xff" * 333):
        assert crc16(sample) == _crc16_tabledriven(sample), sample
    assert MG_LINK_MAX_CHUNK == 252 and MG_LINK_HEADER_SIZE == 6
    print("mystery_gift self-test OK (crc16 bitwise == table-driven)")


if __name__ == "__main__":
    _selftest()
