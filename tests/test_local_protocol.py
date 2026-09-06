"""Pia's Local Protocol - protocol 36, the session bookkeeping behind a Union Room.

Once BDSP's payloads decrypt, this is what the console is actually saying: an *update session*
message listing the room's eight seats, rebroadcast every 100 ms until every station acknowledges
it. The captured Shining Pearl session carries 674 of them and every one has sequence id 4, which
is the host repeating itself because nothing ever answered - so the 0x21 ack is a hardware test
with a pass/fail that needs nothing on the console's screen.

THE TRAP THESE GUARD IS BYTE ORDER, and it is genuinely mixed three ways: the Pia message header
around these is big-endian, the Local Protocol's own fields are little-endian, and a local address
inside them is big-endian again. Getting any one of them wrong still parses and gives nonsense.

Synthetic throughout - captures do not belong in the tree, and the real message carries the
console's MAC address in its constant id.
"""

import struct

import pytest

from pokeldn.ldn import local_protocol as lp


def _address(ip, port):
    """A local address the way the wire holds it: IPv4 then port, BIG-endian, then 2 bytes."""
    return bytes(int(p) for p in ip.split(".")) + struct.pack(">H", port) + b"\0\0"


def _update_session(seq=4, network_id=0x223B4A8B, host_var=0x11BAC90D, host_svc=0x597BC2A3,
                    constant_id=b"\x00\x00\xAA\xBB\xCC\xDD\xEE\xFF", allow=True, seats=()):
    nodes = b""
    for i in range(lp.NODE_COUNT):
        if i < len(seats):
            ip, port, rank = seats[i]
            nodes += _address(ip, port) + bytes([rank])
        else:
            nodes += b"\0" * 8 + bytes([lp.RANKING_EMPTY])
    payload = nodes + b"\x00"                       # + host migration state
    head = struct.pack("<BBH", 1, lp.UPDATE_SESSION, len(payload)) + b"\0" * 6 + b"\0" * 2
    body = (struct.pack("<4I", seq, network_id, host_var, host_svc) + b"\0" * 4
            + constant_id + bytes([1 if allow else 0]) + b"\0" * 7)
    return head + body + payload


SEATS = (("169.254.54.1", 12345, 0), ("169.254.54.2", 12345, 1))


def test_an_update_session_parses_to_the_room_it_describes():
    u = lp.parse_update_session(_update_session(seats=SEATS))
    assert u.sequence_id == 4
    assert u.network_id == 0x223B4A8B
    assert u.host_variable_id == 0x11BAC90D
    assert u.allow_participating is True
    assert u.host_migration_state == 0


def test_the_seats_read_back_with_their_addresses_and_ranking():
    u = lp.parse_update_session(_update_session(seats=SEATS))
    assert len(u.nodes) == 8
    assert (u.nodes[0].ip, u.nodes[0].port, u.nodes[0].ranking) == ("169.254.54.1", 12345, 0)
    assert (u.nodes[1].ip, u.nodes[1].port, u.nodes[1].ranking) == ("169.254.54.2", 12345, 1)
    assert [n.ip for n in u.nodes[2:]] == ["0.0.0.0"] * 6


def test_an_empty_seat_is_ranking_255_and_is_not_counted_as_occupied():
    u = lp.parse_update_session(_update_session(seats=SEATS))
    assert all(n.ranking == lp.RANKING_EMPTY for n in u.nodes[2:])
    assert all(not n.occupied for n in u.nodes[2:])
    assert len(u.occupied) == 2


def test_the_port_is_big_endian_inside_a_little_endian_message():
    """12345 is 0x3039: byte-swapped it would read 14640, and everything else still parses."""
    u = lp.parse_update_session(_update_session(seats=SEATS))
    assert u.nodes[0].port == 12345
    raw = _update_session(seats=SEATS)
    assert raw[lp.UPDATE_SESSION_FIXED + 4:lp.UPDATE_SESSION_FIXED + 6] == b"\x30\x39"


def test_the_sequence_id_is_little_endian():
    raw = _update_session(seq=0x01020304, seats=SEATS)
    assert raw[0x0C:0x10] == bytes.fromhex("04030201")
    assert lp.parse_update_session(raw).sequence_id == 0x01020304


def test_a_bad_version_byte_is_refused():
    raw = bytearray(_update_session(seats=SEATS))
    raw[0] = 2
    with pytest.raises(ValueError, match="version"):
        lp.parse_update_session(bytes(raw))


def test_the_wrong_message_type_is_refused_rather_than_misread():
    raw = bytearray(_update_session(seats=SEATS))
    raw[1] = lp.DESTROY_NETWORK
    with pytest.raises(ValueError, match="message type"):
        lp.parse_update_session(bytes(raw))


def test_a_truncated_message_is_refused():
    raw = _update_session(seats=SEATS)
    with pytest.raises(ValueError, match="truncated"):
        lp.parse_update_session(raw[:-20])
    with pytest.raises(ValueError, match="header"):
        lp.parse_update_session(raw[:8])


def test_the_ack_is_twenty_bytes_and_names_its_sequence():
    ack = lp.build_ack(4)
    assert len(ack) == 0x14
    assert ack[0] == 1 and ack[1] == lp.UPDATE_SESSION_ACK
    assert lp.parse_ack(ack) == 4
    assert lp.parse_ack(lp.build_ack(0xDEADBEEF)) == 0xDEADBEEF


def test_the_ack_refuses_to_parse_an_update_session():
    with pytest.raises(ValueError, match="message type"):
        lp.parse_ack(_update_session(seats=SEATS))


def test_an_ack_travels_as_a_protocol_36_message():
    """What actually goes on the wire: the ack inside a Pia message, inside a padded payload."""
    from pokeldn.ldn.pia5 import build_message, pad_payload, parse_messages
    body = pad_payload(build_message(lp.build_ack(4), protocol=lp.PROTOCOL, destination=1))
    assert len(body) % 16 == 0
    m = parse_messages(body)
    assert len(m) == 1 and m[0].protocol == lp.PROTOCOL
    assert lp.parse_ack(m[0].payload) == 4
