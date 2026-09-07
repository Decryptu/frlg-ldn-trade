"""The version-4 connection request, against Sword's own serializer.

Every offset here was read off `main` 0x017c7aa0 (the serializer) and checked against 0x017c62a0
(the parser that reads the same bytes back). There is no capture of one, so what these tests can
prove is that the bytes land where those two functions put them and that a version-4 request is
NOT a 5.27 request - which is the mistake that would cost a run and read as ordinary silence.
"""

import pytest

from pokeldn.ldn import station4 as s4, station_protocol as stp

OUR_MAC = bytes.fromhex("58d8122149a2")
HOST_MAC = bytes.fromhex("48f1eb209b22")
HOST_VAR = 0x15D71A64


def _location(variable_id=0x11223344):
    return stp.station_location("169.254.10.2", 12345, stp.ldn_constant_id(OUR_MAC),
                                variable_id, stp.ldn_service_variable_id(OUR_MAC))


def _request(**kw):
    return s4.build_connection_request(stp.ldn_constant_id(HOST_MAC), HOST_VAR, _location(), **kw)


def test_every_field_lands_where_the_serializer_puts_it():
    r = _request(nat_flags=5, nat_location=1)
    assert r[0] == s4.CONNECTION_REQUEST == 1
    assert r[1] == 5                                  # the target's nat flags
    assert r[2] == s4.PLATFORM_SWITCH == 9            # 5.27-5.45 writes 4 here
    assert r[3] == 1                                  # a target variable id follows
    assert int.from_bytes(r[4:12], "big") == stp.ldn_constant_id(HOST_MAC)
    assert int.from_bytes(r[12:16], "big") == HOST_VAR
    assert r[16] == 1                                 # the target's nat location
    assert r[17:] == _location()
    assert len(r) == 0x11 + 40 == 57


def test_it_is_not_a_5_27_request():
    """The flag byte at [3] shifts everything after it, so the two layouts disagree from there on -
    and a version-4 console drops a mismatched constant id in silence."""
    v4 = _request()
    v5 = stp.build_connection_request(stp.ldn_constant_id(HOST_MAC), HOST_VAR,
                                      [stp.FILLER], _location(), player_infos=[], ack_id=1)
    assert int.from_bytes(v4[4:12], "big") == int.from_bytes(v5[3:11], "big")
    assert v4[3] != v5[3]                             # v5 has the constant id's first byte here
    assert v4[2] == 9 and v5[2] == stp.PLATFORM_SWITCH == 4


def test_the_request_round_trips():
    for flags, loc, with_id in ((5, 1, True), (0, 0, False), (255, 254, True)):
        r = _request(nat_flags=flags, nat_location=loc, with_variable_id=with_id)
        got = s4.parse_connection_request(r)
        assert got["nat_flags"] == flags and got["nat_location"] == loc
        assert got["with_variable_id"] == (1 if with_id else 0)
        assert got["constant_id"] == stp.ldn_constant_id(HOST_MAC)
        assert got["variable_id"] == HOST_VAR       # written even when [3] says not to read it
        assert got["platform"] == 9


def test_the_relay_variant_is_the_same_message_with_type_6():
    """One serializer builds both - `csinc` on the caller's flag picks 1 or 6."""
    a, b = _request(), _request(relay=True)
    assert a[0] == 1 and b[0] == s4.RELAY_CONNECTION_REQUEST == 6
    assert a[1:] == b[1:]


def test_a_location_of_the_wrong_size_is_refused_here_rather_than_on_the_air():
    """0x20..0x40, the same bounds 5.27 has. A malformed location's error is thrown away by the
    connection-request parser, so it reads as a working request the console refuses."""
    with pytest.raises(ValueError):
        s4.build_connection_request(1, 2, b"\0" * 8)


def test_the_address_size_byte_counts_the_port():
    """(1 << size) & 0x40044 - only 2, 6 and 18 pass, in version 4 exactly as in 5.27."""
    location = _location()
    assert location[0] == location[1] == 6
    for size in (2, 6, 18):
        assert (1 << size) & 0x40044
    for size in (4, 8, 16):
        assert not (1 << size) & 0x40044
