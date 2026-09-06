"""Pia 5.27-5.45 header codec (BDSP). The fixture bytes are a real packet off a French Shining
Pearl in the Union Room, session 43 - see NOTES.local.md sp4/sp8."""
import pytest

from pokeldn.ldn.pia5 import PiaHeader5, is_pia5, HEADER_SIZE, CT_OFF, MAGIC, VERSION

# the first datagram of sp4: 169.254.54.1:12345 -> .255:12345, 176 bytes
REAL = bytes.fromhex(
    "32ab9864890000000011bac90d000000f5a83bd383ce712d"
    "59baa5cbc320cb56a319c5fc3ecfdaca65d89eb747e02e816dc4f21eac462965")


def test_parses_a_real_packet():
    h = PiaHeader5.parse(REAL)
    assert h.encrypted is True
    assert h.version == VERSION == 9
    assert h.dst_var == 0                      # broadcast to the mesh
    assert h.src_var == 0x11BAC90D             # big-endian on the wire
    assert h.packet_id == 0
    assert h.footer_size == 0
    assert h.nonce8 == bytes.fromhex("f5a83bd383ce712d")
    assert h.tag == bytes.fromhex("59baa5cbc320cb56")


def test_round_trips_byte_identically():
    assert PiaHeader5.parse(REAL).pack() == REAL[:HEADER_SIZE]


def test_header_is_32_bytes_not_29():
    # 6.32 (pia_connect.py) uses 0x1D; getting these two confused is the whole point of the module
    assert HEADER_SIZE == 0x20 and CT_OFF == 0x20
    assert len(PiaHeader5().pack()) == 0x20


def test_encryption_flag_round_trips():
    plain = PiaHeader5(encrypted=False).pack()
    assert plain[4] == VERSION                 # 0x09, the 0x80 bit clear
    assert PiaHeader5.parse(plain).encrypted is False
    assert PiaHeader5.parse(PiaHeader5(encrypted=True).pack()).encrypted is True


def test_variable_ids_are_four_bytes():
    h = PiaHeader5(dst_var=0x11223344, src_var=0xAABBCCDD)
    raw = h.pack()
    assert raw[5:9] == bytes.fromhex("11223344")
    assert raw[9:13] == bytes.fromhex("aabbccdd")
    back = PiaHeader5.parse(raw)
    assert (back.dst_var, back.src_var) == (0x11223344, 0xAABBCCDD)


def test_rejects_non_pia_and_short():
    assert not is_pia5(b"\x00" * 32)
    assert is_pia5(REAL)
    with pytest.raises(ValueError):
        PiaHeader5.parse(REAL[:8])
    with pytest.raises(ValueError):
        PiaHeader5.parse(b"\x00" * 32)
