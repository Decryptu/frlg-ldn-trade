"""Pia's Mesh Station Protocol (0x14) - the handshake that joins a mesh, not just its bookkeeping.

Every offset asserted here is one the console's own parser reads, main.bin 0x0154ebd0. The tests
are written against THAT order, because the order is what makes the sweep in bin/bdsp_connect.py
work: the target ids and the protocol count are checked before anything is sent back, and the
protocol VERSIONS are the first thing that draws a reply.

Synthetic except for the one real value - the captured Shining Pearl host's constant id, which is
its MAC put through the wiki's LDN rule.
"""

import struct

import pytest

from pokeldn.ldn import station_protocol as stp

# off scratchpad/bdsp_net_facts.json and the sp4 update session
CONSOLE_MAC = bytes.fromhex("48f1eb209b22")
CONSOLE_CONSTANT_FIELD = bytes.fromhex("000048f120229beb")     # as the message carries it
HOST_VAR = 0x11BAC90D


def test_the_constant_id_rule_reproduces_the_captured_host():
    """The one place three independent things agree: the wiki's rule, the field's byte order, the
    scan's MAC. If any of the three were wrong this would not close."""
    value = stp.ldn_constant_id(CONSOLE_MAC)
    assert value == int.from_bytes(CONSOLE_CONSTANT_FIELD, "little")
    assert value == 0xEB9B2220F1480000


def test_a_constant_id_needs_six_bytes():
    with pytest.raises(ValueError):
        stp.ldn_constant_id(b"\x01\x02\x03")
    with pytest.raises(ValueError):
        stp.ldn_service_variable_id(b"")


def test_the_service_variable_id_is_the_crc_of_the_mac():
    import zlib
    assert stp.ldn_service_variable_id(CONSOLE_MAC) == zlib.crc32(CONSOLE_MAC) & 0xFFFFFFFF


def test_a_station_location_is_forty_bytes_and_inside_the_accepted_range():
    loc = stp.station_location("169.254.49.2", 12345, 0x1122334455667788, 0xAABBCCDD, 0x12345678)
    assert len(loc) == 40
    assert stp.STATION_LOCATION_MIN <= len(loc) <= stp.STATION_LOCATION_MAX
    assert loc[0] == 4 and loc[1] == 4                       # both addresses are IPv4
    assert loc[2:8] == bytes([169, 254, 49, 2]) + struct.pack(">H", 12345)
    assert loc[14:20] == b"\0" * 6                           # no relay on a local network
    assert struct.unpack_from(">Q", loc, 20)[0] == 0x1122334455667788
    assert struct.unpack_from(">I", loc, 28)[0] == 0xAABBCCDD
    assert struct.unpack_from(">I", loc, 32)[0] == 0x12345678


def test_a_player_info_is_195_bytes_with_the_5_27_field_order():
    info = stp.player_info("PkCamp", language=2, principal_id=7)
    assert len(info) == 0xC3
    assert info[0] == 1 and info[1:7] == b"PkCamp"            # encoding BEFORE the string
    assert info[0x51] == 1
    assert info[0x7A] == 2
    assert struct.unpack_from("<Q", info, 0xBB)[0] == 7


def _request(n=8, **kw):
    loc = stp.station_location("169.254.49.2", 12345, 0x1122334455667788, 0xAABBCCDD, 0x12345678)
    return stp.build_connection_request(
        stp.ldn_constant_id(CONSOLE_MAC), HOST_VAR, [(0xFF, 1)] * n, loc,
        player_infos=[stp.player_info("PkCamp")], **kw)


def test_the_request_lands_every_field_where_the_console_reads_it():
    req = _request(n=8)
    assert req[0] == stp.CONNECTION_REQUEST
    assert req[1] == stp.RESULT_ACCEPTED
    assert req[2] == stp.PLATFORM_SWITCH
    # the parser does `ldur x8,[x26,#3]` then `rev` - big-endian, and compared against its own
    assert struct.unpack_from(">Q", req, 3)[0] == stp.ldn_constant_id(CONSOLE_MAC)
    assert struct.unpack_from(">I", req, 0x0B)[0] == HOST_VAR
    assert req[0x0F] == 8                                     # the count it compares with its own
    assert req[0x10:0x20] == bytes([0xFF, 1]) * 8
    size_off = 0x10 + 2 * 8
    assert struct.unpack_from(">H", req, size_off)[0] == 40   # station location size, big-endian


def test_the_protocol_count_byte_follows_the_list_length():
    for n in (0, 1, 12, 31):
        req = _request(n=n)
        assert req[0x0F] == n
        assert req[0x10:0x10 + 2 * n] == bytes([0xFF, 1]) * n


def test_the_request_stays_inside_the_size_window_the_parser_enforces():
    for n in (0, 31):
        assert stp.MIN_SIZE <= len(_request(n=n)) <= stp.MAX_SIZE


def test_a_request_long_enough_to_be_refused_is_refused_here_first():
    loc = stp.station_location("169.254.49.2", 12345, 1, 2, 3)
    with pytest.raises(ValueError):
        stp.build_connection_request(1, 2, [(0xFF, 1)] * 8, loc,
                                     player_infos=[stp.player_info("x")] * 5)


def test_a_station_location_outside_the_accepted_range_is_refused():
    with pytest.raises(ValueError):
        stp.build_connection_request(1, 2, [], b"\0" * 8)
    with pytest.raises(ValueError):
        stp.build_connection_request(1, 2, [], b"\0" * 0x41)


def test_a_denial_reads_back_with_the_console_s_own_ids():
    """The fifteen bytes the console builds at 0x01550190 when it refuses."""
    denial = (bytes([stp.CONNECTION_RESPONSE, stp.RESULT_VERSION_TOO_HIGH, 0])
              + struct.pack(">Q", stp.ldn_constant_id(CONSOLE_MAC))
              + struct.pack(">I", HOST_VAR))
    assert len(denial) == 15
    got = stp.parse_connection_response(denial)
    assert got["result"] == 3 and got["result_name"] == "version too high"
    assert got["constant_id"] == stp.ldn_constant_id(CONSOLE_MAC)
    assert got["variable_id"] == HOST_VAR


def test_a_response_that_is_not_one_is_refused_rather_than_misread():
    with pytest.raises(ValueError):
        stp.parse_connection_response(bytes([stp.CONNECTION_REQUEST, 0]))
    with pytest.raises(ValueError):
        stp.parse_connection_response(b"")


def test_the_message_type_comes_off_the_front():
    assert stp.parse_message(bytes([stp.ACK, 0, 0, 0, 1, 2, 3, 4]))[0] == stp.ACK
    with pytest.raises(ValueError):
        stp.parse_message(b"")


def test_a_version_probe_puts_the_candidate_first_and_pads_with_filler():
    """The console's loop reports the FIRST disagreement, so the candidate has to lead."""
    probe = stp.version_probe(0x14, 3, 9)
    assert len(probe) == 9
    assert probe[0] == (0x14, 3)
    assert probe[1:] == [stp.FILLER] * 8
    assert stp.FILLER == (0xFF, 0)


def test_a_probe_needs_at_least_one_entry():
    with pytest.raises(ValueError):
        stp.version_probe(0x14, 1, 0)


def test_a_probe_result_reads_as_a_direction():
    assert stp.read_version(stp.RESULT_VERSION_TOO_LOW) == "higher"
    assert stp.read_version(stp.RESULT_VERSION_TOO_HIGH) == "lower"
    # the equality signal is a REPLY: the request got past the version loop and something later
    # refused it, which on hardware is result 7 (sp28)
    assert stp.read_version(stp.RESULT_VERSIONS_MATCHED) == "equal"
    assert stp.read_version(stp.RESULT_ACCEPTED) == "equal"
    assert stp.read_version(stp.RESULT_DENIED) == "equal"


def test_silence_is_no_longer_read_as_a_match():
    """The mistake sp28 corrected. Silence means a lost packet, and inventing a version from it is
    exactly the class of error rule 4 is about."""
    with pytest.raises(ValueError):
        stp.read_version(None)


def test_the_known_ids_are_the_5_29_list_and_hold_the_ones_already_measured():
    assert 0x14 in stp.KNOWN_PROTOCOL_IDS      # the station protocol carrying the probe itself
    assert 0x24 in stp.KNOWN_PROTOCOL_IDS      # the local protocol, whose ack the console accepted
    assert 0xFF not in stp.KNOWN_PROTOCOL_IDS  # the filler must not collide with a candidate
    assert len(set(stp.KNOWN_PROTOCOL_IDS)) == len(stp.KNOWN_PROTOCOL_IDS)


def _search_against(actual, **kw):
    """Drive a VersionSearch against a console that really registers `actual`."""
    s = stp.VersionSearch(**kw)
    while not s.done:
        v = s.next_version()
        s.feed("equal" if v == actual else ("higher" if actual > v else "lower"))
    return s


def test_the_version_search_finds_every_version_it_could_be_asked_for():
    for actual in range(0, 256):
        s = _search_against(actual)
        assert s.found == actual, f"{actual} came back as {s.found}"
        assert s.probes <= 9


def test_the_common_case_costs_one_probe():
    assert _search_against(1).probes == 1          # it opens at 1, where Pia versions live


def test_a_bounded_search_still_closes():
    for actual in range(2, 20):
        assert _search_against(actual, lo=2, first=2).found == actual


def test_contradictory_answers_end_the_search_without_inventing_a_version():
    s = stp.VersionSearch(lo=5, hi=5, first=5)
    s.feed("higher")                                # 5 is both the only candidate and too low
    assert s.done and s.found is None


def test_a_finished_search_refuses_to_be_fed_again():
    s = _search_against(3)
    with pytest.raises(ValueError):
        s.feed("equal")
    assert s.next_version() is None


def test_a_non_direction_is_refused_rather_than_treated_as_a_miss():
    s = stp.VersionSearch()
    with pytest.raises(ValueError):
        s.feed("denied")
