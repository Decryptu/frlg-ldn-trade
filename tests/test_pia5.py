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


def test_the_message_header_is_byte_exact_against_the_console():
    """The 16 bytes in front of the console's own update session, off the sp4 capture.

    The presence byte is 0x7F and not 0x0F - the four defined bits are all this header carries, but
    the console sets three more that name nothing. Emitting 0x0F was the one byte our send path had
    wrong; everything after it already matched.
    """
    from pokeldn.ldn.pia5 import build_message
    real = bytes.fromhex("7f110079240000000000000000000000")
    built = build_message(b"\0" * 121, protocol=36, port=0, message_flags=0x11, destination=0)
    assert built[:16] == real
    assert len(built) == 16 + 121 + 3            # padded up to a multiple of four


def test_an_inherited_message_still_opens_with_its_own_presence_byte():
    from pokeldn.ldn.pia5 import build_message, parse_messages
    first = build_message(b"\x01\x02\x03\x04", protocol=36, message_flags=0x11, destination=0)
    second = build_message(b"\x05\x06\x07\x08", protocol=0, inherit=True)
    got = parse_messages(first + second)
    assert [m.protocol for m in got] == [36, 36]         # the second inherits the first's
    assert [m.message_flags for m in got] == [0x11, 0x11]
