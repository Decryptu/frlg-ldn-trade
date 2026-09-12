"""The 720-byte Wonder Card record Sword/Shield's importer accepts, and how to build one.

The record is PKHeX's WC8. It carries its own checksum at +0x2CC: CRC-16/CCITT-FALSE (poly 0x1021,
init 0xFFFF, no reflection, no final xor) over all 0x2D0 bytes with that halfword zeroed, verified
at 0x010b5de0. The first eight bytes are the card's date, a calendar bitfield in UTC. Field by
field: docs/swsh_gift.md, "What a record must carry" onwards.
Trap: the nickname array is at 0x030 and the trainer array at 0x12C; a console shows them that way
round, whatever a parser trace suggests."""
import struct
import time

RECORD = 0x2D0
CHECKSUM_AT = 0x2CC
GIFT_KIND_AT = 0x11
GIFT_KIND_POKEMON = 1

_T = []
for _i in range(256):
    _c = _i << 8
    for _ in range(8):
        _c = ((_c << 1) ^ 0x1021) & 0xFFFF if _c & 0x8000 else (_c << 1) & 0xFFFF
    _T.append(_c)


def record_crc(rec):
    """CRC-16/CCITT-FALSE over the record with the checksum halfword zeroed (0x010b5f54)."""
    d = bytearray(rec)
    struct.pack_into("<H", d, CHECKSUM_AT, 0)
    crc = 0xFFFF
    for b in d:
        crc = (_T[(b ^ (crc >> 8)) & 0xFF] ^ ((crc << 8) & 0xFFFF)) & 0xFFFF
    return crc


def seal(rec):
    """-> the record with its checksum written at +0x2CC."""
    d = bytearray(rec)
    struct.pack_into("<H", d, CHECKSUM_AT, record_crc(d))
    return bytes(d)


def sealed(rec):
    return len(rec) == RECORD and struct.unpack_from("<H", rec, CHECKSUM_AT)[0] == record_crc(rec)


def pack_date(t=None):
    """The date at +0x00: a little-endian u64 bitfield 0x016cc5e0 converts to posix time as UTC and
    the album shows in the console's zone. Seconds bits 0-5, minutes 6-11, hours 12-16, day 17-21,
    month 22-25, year 26-39, all absolute (docs/swsh_gift.md, "The card's date")."""
    tm = time.gmtime(time.time() if t is None else t)
    v = (tm.tm_sec | tm.tm_min << 6 | tm.tm_hour << 12 | tm.tm_mday << 17 | tm.tm_mon << 22
         | tm.tm_year << 26)
    return struct.pack("<Q", v)


def unpack_date(rec):
    """-> (year, month, day, hour, minute, second) as the bitfield carries them."""
    v = struct.unpack_from("<Q", rec, 0)[0]
    return ((v >> 26) & 0x3FFF, (v >> 22) & 0xF, (v >> 17) & 0x1F, (v >> 12) & 0x1F,
            (v >> 6) & 0x3F, v & 0x3F)


def build(card_id=0x270F, region_mask=0xFFFF, dedup=0, extra=None, date=None):
    """A sealed record with the card id, the region mask, the duplicate-check byte and the date set,
    and `extra` ({offset: bytes}) written over it before sealing."""
    r = bytearray(RECORD)
    r[0:8] = pack_date(date)
    struct.pack_into("<H", r, 0x08, card_id)
    struct.pack_into("<H", r, 0x0E, region_mask)
    r[0x13] = dedup
    for off, data in (extra or {}).items():
        r[off:off + len(data)] = data
    return seal(r)


# The Pokemon block, read by the kind-1 path 0x010b58f0; offsets into the record and struct formats.
# Every entry is confirmed on a console where docs/swsh_gift.md says so; the rest is PKHeX's map.
POKEMON = {
    "tid": (0x20, "H"), "sid": (0x22, "H"),          # 0/0 gives the player's own ids
    "ec": (0x28, "I"), "pid": (0x2C, "I"),            # 0 rolls one
    "egg_location": (0x228, "H"), "met_location": (0x22A, "H"),
    "ball": (0x22C, "H"), "held_item": (0x22E, "H"),
    "move1": (0x230, "H"), "move2": (0x232, "H"), "move3": (0x234, "H"), "move4": (0x236, "H"),
    "relearn1": (0x238, "H"), "relearn2": (0x23A, "H"),
    "relearn3": (0x23C, "H"), "relearn4": (0x23E, "H"),
    "species": (0x240, "H"),
    "form": (0x242, "B"),
    "gender": (0x243, "B"),            # 0 male, 1 female, 2 random
    "level": (0x244, "B"),             # zero makes the game roll one
    "egg": (0x245, "B"),
    "nature": (0x246, "B"),
    "ability_type": (0x247, "B"),      # 0/1/2 slot 1/2/hidden, 3 random of two, 4 random of three
    "shiny_type": (0x248, "B"),        # 0 never, 1 random, 2 star, 3 square, 4 the PID as given
    "met_level": (0x249, "B"),
    "dynamax_level": (0x24A, "B"), "gigantamax": (0x24B, "B"),
    "iv_hp": (0x26C, "B"), "iv_atk": (0x26D, "B"), "iv_def": (0x26E, "B"),
    "iv_spe": (0x26F, "B"), "iv_spa": (0x270, "B"), "iv_spd": (0x271, "B"),
    "ot_gender": (0x272, "B"),
    "ev_hp": (0x273, "B"), "ev_atk": (0x274, "B"), "ev_def": (0x275, "B"),
    "ev_spe": (0x276, "B"), "ev_spa": (0x277, "B"), "ev_spd": (0x278, "B"),
}
RIBBONS_AT, RIBBONS_LEN = 0x24C, 0x20     # ribbon indices; 0xFF ends the list
NICKNAMES = 0x030       # 9 entries of 0x1C: 0x1A bytes of UTF-16, then a language byte at +0x1A
OT_NAMES = 0x12C        # 9 entries of 0x1C: 0x1A bytes of UTF-16
LANG_STRIDE = 0x1C
LANG_COUNT = 9
NAME_BYTES = 0x1A


def utf16(text, size=NAME_BYTES):
    b = text.encode("utf-16-le")
    if len(b) > size - 2:
        raise ValueError(f"{text!r} does not fit {size // 2 - 1} characters")
    return b.ljust(size, b"\0")


def pokemon_card(species, level=5, moves=(0, 0, 0, 0), form=0, nickname=None, ot=None,
                 card_id=0x270F, region_mask=0xFFFF, dedup=0, met_level=None, ribbons=(),
                 date=None, **fields):
    """A kind-1 record carrying one Pokemon. Fields not given stay zero, except the ribbon list,
    which is empty rather than thirty-two ribbons of index 0. `fields` are POKEMON keys.

    level 0 makes the game roll one and report the Pokemon as met at level 0; met_level defaults to
    the level so a card looks like a real distribution rather than a measuring instrument."""
    extra = {GIFT_KIND_AT: bytes([GIFT_KIND_POKEMON])}
    if met_level is None:
        met_level = level
    values = dict(species=species, level=level, form=form, met_level=met_level,
                  move1=moves[0], move2=moves[1], move3=moves[2], move4=moves[3])
    values.update(fields)
    for name, value in values.items():
        off, fmt = POKEMON[name]
        extra[off] = struct.pack("<" + fmt, value)
    extra[RIBBONS_AT] = bytes(ribbons) + b"\xff" * (RIBBONS_LEN - len(ribbons))
    for i in range(LANG_COUNT):
        if nickname:
            extra[NICKNAMES + i * LANG_STRIDE] = utf16(nickname)
        if ot:
            extra[OT_NAMES + i * LANG_STRIDE] = utf16(ot)
    return build(card_id=card_id, region_mask=region_mask, dedup=dedup, extra=extra, date=date)


def read(rec):
    """The fields of a record as a dict, for a log line or a test."""
    out = {name: struct.unpack_from("<" + fmt, rec, off)[0] for name, (off, fmt) in POKEMON.items()}
    out["card_id"] = struct.unpack_from("<H", rec, 0x08)[0]
    out["region_mask"] = struct.unpack_from("<H", rec, 0x0E)[0]
    out["kind"] = rec[GIFT_KIND_AT]
    out["dedup"] = rec[0x13]
    out["date"] = unpack_date(rec)
    out["nickname"] = rec[NICKNAMES:NICKNAMES + NAME_BYTES].decode("utf-16-le").rstrip("\0")
    out["ot"] = rec[OT_NAMES:OT_NAMES + NAME_BYTES].decode("utf-16-le").rstrip("\0")
    out["ribbons"] = tuple(b for b in rec[RIBBONS_AT:RIBBONS_AT + RIBBONS_LEN] if b != 0xFF)
    out["sealed"] = sealed(rec)
    return out
