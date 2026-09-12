"""The Wonder Card record and the beacon transport that carries it, pinned to what a retail Sword
showed (docs/swsh_gift.md)."""
import struct

import pytest

from pokeldn.swsh import beacon, wc8


def test_record_checksum_is_ccitt_false_over_the_zeroed_field():
    rec = wc8.build(card_id=0x270F)
    assert len(rec) == 0x2D0 and wc8.sealed(rec)
    bad = bytearray(rec)
    bad[0x2CC] ^= 1
    assert not wc8.sealed(bad)
    # CRC-16/CCITT-FALSE of "123456789" is 0x29B1; the routine zeroes +0x2CC first
    probe = bytearray(0x2D0)
    probe[:9] = b"123456789"
    assert wc8.record_crc(probe) != 0x29B1     # the 0x2C7 trailing zeros are part of the sum
    assert wc8.record_crc(b"123456789" + bytes(0x2D0 - 9)) == wc8.record_crc(probe)


def test_names_go_where_the_console_read_them():
    rec = wc8.pokemon_card(25, level=30, nickname="PKCAMP", ot="POKELDN")
    fields = wc8.read(rec)
    assert (fields["nickname"], fields["ot"]) == ("PKCAMP", "POKELDN")
    assert rec[0x030:0x03C] == "PKCAMP".encode("utf-16-le")
    assert rec[0x12C:0x13A] == "POKELDN".encode("utf-16-le")
    for i in range(9):                                     # every language slot carries the same name
        assert rec[0x030 + i * 0x1C:0x030 + i * 0x1C + 12] == "PKCAMP".encode("utf-16-le")


def test_date_bitfield_matches_the_three_album_readings():
    # 18 October 2018 16:26 UTC showed 18/10/2018 18:26; the field is absolute, UTC, month 1-based
    rec = wc8.build(date=1539879960)
    assert wc8.unpack_date(rec) == (2018, 10, 18, 16, 26, 0)
    v = struct.unpack_from("<Q", rec, 0)[0]
    assert (v >> 26) & 0x3FFF == 2018 and (v >> 22) & 0xF == 10 and (v >> 17) & 0x1F == 18
    # the probe 01 02 .. 08 packs month 0 of year 321 and showed December of the year before
    v = struct.unpack("<Q", bytes(range(1, 9)))[0]
    assert ((v >> 26) & 0x3FFF, (v >> 22) & 0xF, (v >> 17) & 0x1F) == (321, 0, 1)


def test_pokemon_fields_as_the_retail_console_showed_them():
    rec = wc8.pokemon_card(25, level=45, moves=(84, 45, 86, 98), nickname="PKCAMP", ot="POKELDN",
                           tid=12345, sid=54321, ball=1, held_item=236, gender=1, nature=10,
                           ability_type=2, shiny_type=3, dynamax_level=10, gigantamax=1,
                           iv_hp=31, iv_atk=31, iv_def=31, iv_spe=31, iv_spa=31, iv_spd=31)
    f = wc8.read(rec)
    assert f["kind"] == 1 and f["species"] == 25 and f["level"] == 45 and f["met_level"] == 45
    assert (f["move1"], f["move2"], f["move3"], f["move4"]) == (84, 45, 86, 98)
    assert (f["tid"], f["sid"]) == (12345, 54321) and (54321 << 16 | 12345) % 1000000 == 993401
    assert (f["ball"], f["held_item"], f["gender"], f["nature"]) == (1, 236, 1, 10)
    assert (f["ability_type"], f["shiny_type"], f["dynamax_level"], f["gigantamax"]) == (2, 3, 10, 1)
    assert f["ribbons"] == () and rec[0x24C:0x26C] == b"\xff" * 0x20
    assert rec[0x26C:0x272] == bytes([31] * 6)
    assert f["region_mask"] == 0xFFFF and f["dedup"] == 0 and f["sealed"]


def test_unknown_field_is_refused():
    with pytest.raises(KeyError):
        wc8.pokemon_card(25, colour=1)


def test_a_card_is_three_fragments_sharing_one_pia_header():
    rec = wc8.pokemon_card(25, level=25, nickname="PKCAMP", ot="POKELDN")
    blobs = beacon.build_message(rec)
    assert len(blobs) == 3 and all(len(b) == 0x180 for b in blobs)
    heads = {b[:0x18] for b in blobs}
    assert len(heads) == 1
    head = heads.pop()
    assert head[4:8] == bytes(4) and head[8:10] == bytes((5, 0x18)) and head[0x10:] == bytes(8)
    assert head[:4] != bytes(4) and head[0xC:0x10] != bytes(4)
    for i, b in enumerate(blobs):
        d = beacon.decode(b)
        assert d["stored_crc"] == d["computed_crc"] and d["network_id"] == 0xD70
        pl = d["payload"]
        assert pl[0] == 1 and struct.unpack_from("<IH", pl, 1) == (0, 0x2D0)
        assert (pl[7], pl[8]) == (3, i)
        assert struct.unpack_from("<H", pl, 9)[0] == beacon.crc16(rec)
    assert beacon.reassemble(blobs) == rec
    assert beacon.reassemble(blobs[::-1] + blobs[:1]) == rec        # order and repeats do not matter


def test_reassembly_refuses_what_the_console_refuses():
    rec = wc8.build()
    blobs = beacon.build_message(rec)
    with pytest.raises(ValueError, match="missing"):
        beacon.reassemble(blobs[:2])
    with pytest.raises(ValueError, match="checksum"):
        beacon.reassemble(beacon.build_message(rec, checksum=0))
    with pytest.raises(ValueError, match="fit"):
        beacon.build_message(b"")


def test_two_records_are_five_fragments():
    blobs = beacon.build_message(wc8.build() + wc8.build(card_id=2))
    assert len(blobs) == 5
    assert len(beacon.reassemble(blobs)) == 2 * 0x2D0
