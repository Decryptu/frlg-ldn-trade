"""Mystery Gift protocol foundations (FRLG, src/mystery_gift_link.c + mystery_gift.h).

This module holds the parts of the Mystery Gift protocol that are pure and hardware-independent:
the MysteryGiftLink message idents, buffer sizes, the CalcCRC16WithTable checksum, and the
Wonder Card enum values the console validates. The reliable transport (6-byte header + <=252B
SendBlock chunks) and the server-side script driver are layered on top of this in Milestone 2.

We act as the Mystery Gift SERVER (RFU parent / link player 0); the console runs
MysteryGiftClient as link player 1 and executes whatever client scripts we send it.
"""

# --- MysteryGiftLink message idents [include/mystery_gift_link.h:8-22] ------------------------
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

# --- MysteryGiftLinkGameData validation magic [src/mystery_gift.c] ----------------------------
GAME_DATA_VALID_VAR = 0x101     # data->unk_00
VERSION_CODE_FIRERED = 1
VERSION_CODE_LEAFGREEN = 2

# --- Wonder Card enums the console validates in ValidateWonderCard [mystery_gift.c:191] --------
CARD_TYPE_GIFT = 0              # normal Wonder Card
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
FLAG_RECEIVED_OLD_SEA_MAP = 0x2A9   # unused in FRLG
FLAG_WONDER_CARD_UNUSED_1 = 0x2AA   # first free slot -> a clean one-shot for a custom gift


def crc16(data):
    """CalcCRC16WithTable [src/util.c:250]: reflected CRC16, init 0x1121, poly 0x8408 (reflected
    0x1021), final one's-complement. Used for every MysteryGiftLink message header. This is the
    bitwise form of CalcCRC16 [util.c:231], which is mathematically identical to the table-driven
    CalcCRC16WithTable the game actually uses for the link headers (verified in _selftest)."""
    crc = 0x1121
    for b in bytes(data):
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
    return (~crc) & 0xFFFF


def _crc16_table():
    """Build gCrc16Table [util.c:77] from the reflected poly 0x8408 (index -> 8-shift residue)."""
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if (c & 1) else (c >> 1)
        table.append(c & 0xFFFF)
    return table


def _crc16_tabledriven(data):
    """Exact port of CalcCRC16WithTable [util.c:250] (crc = (crc>>8) ^ table[(crc ^ byte) & 0xFF]).
    Kept only to prove the bitwise crc16() above matches the game's table routine byte-for-byte."""
    table = _crc16_table()
    crc = 0x1121
    for b in bytes(data):
        hi = crc >> 8
        crc ^= b
        crc = (hi ^ table[crc & 0xFF]) & 0xFFFF
    return (~crc) & 0xFFFF


def _selftest():
    # The bitwise and table-driven CRC must agree for arbitrary data (the two game routines are
    # documented as interchangeable for the link headers).
    for sample in (b"", b"\x00", b"GameFreak inc.", bytes(range(256)), b"\xff" * 333):
        assert crc16(sample) == _crc16_tabledriven(sample), sample
    # Ident/size sanity.
    assert MG_LINK_MAX_CHUNK == 252 and MG_LINK_HEADER_SIZE == 6
    print("mystery_gift self-test OK (crc16 bitwise == table-driven)")


if __name__ == "__main__":
    _selftest()
