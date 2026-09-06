"""Pia's Mesh Protocol (0x18) - the membership layer above the station handshake.

BDSP advertises mesh protocol version 3 in its connection response, which the wiki pins to Pia
5.30-5.45, so the structures here are the 5.31-5.45 ones. Synthetic throughout.
"""

import struct

import pytest

from pokeldn.ldn import mesh_protocol as mp, station_protocol as stp


def test_a_join_request_is_six_bytes_and_calls_itself_253():
    req = mp.build_join_request(7)
    assert req == bytes([mp.JOIN_REQUEST, 253]) + struct.pack(">I", 7)
    assert len(req) == 6
    assert mp.STATION_INDEX_INVALID == 253       # "has not joined a mesh yet"
    assert mp.parse_message(req) == (mp.JOIN_REQUEST, "JOIN_REQUEST")


def test_a_refusal_is_told_from_a_success_by_its_two_ff_bytes():
    out = mp.parse_join_response(bytes([mp.JOIN_RESPONSE, 0, 0xFF, 0xFF, 9]))
    assert out == {"refused": True, "reason": 9}


def _success(entries=2, our_index=1, fragments=1):
    head = bytes([mp.JOIN_RESPONSE, entries, 0, our_index, fragments, 0, entries, 0,
                  8, 0, 8, 0]) + struct.pack(">I", 42)
    body = b""
    for i in range(entries):
        loc = stp.station_location(f"169.254.14.{i + 1}", 12345, 0x1122334455667788 + i,
                                   0xAABB0000 + i, 0xCCDD0000 + i)
        body += loc.ljust(mp.LOCATION_FIELD, b"\0") + bytes([i]) + b"\0" * 3
    return head + body + struct.pack(">I", 0x17CAD56C)


def test_a_success_reads_the_whole_mesh_back():
    out = mp.parse_join_response(_success())
    assert out["refused"] is False
    assert out["stations"] == 2 and out["host_index"] == 0 and out["our_index"] == 1
    assert out["fragments"] == 1 and out["entries"] == 2
    assert out["update_counter"] == 42
    assert out["ack_id"] == 0x17CAD56C
    assert [e["station_index"] for e in out["station_info"]] == [0, 1]
    assert out["station_info"][0]["location"]["private"] == ("169.254.14.1", 12345)
    assert out["station_info"][1]["location"]["variable_id"] == 0xAABB0001


def test_a_station_info_entry_is_sixty_eight_bytes():
    assert mp.STATION_INFO_SIZE == 68 and mp.LOCATION_FIELD == 64
    out = mp.parse_join_response(_success(entries=3))
    assert len(out["station_info"]) == 3


def test_a_truncated_entry_stops_the_walk_rather_than_reading_past_the_end():
    raw = _success(entries=2)
    out = mp.parse_join_response(raw[:-40])
    assert len(out["station_info"]) < 2


def test_the_wrong_message_type_is_refused():
    with pytest.raises(ValueError):
        mp.parse_join_response(bytes([mp.UPDATE_MESH, 0, 0, 0, 0]))
    with pytest.raises(ValueError):
        mp.parse_message(b"")


def test_the_type_table_names_what_a_capture_will_hold():
    assert mp.parse_message(bytes([mp.UPDATE_MESH]))[1] == "UPDATE_MESH"
    assert mp.parse_message(bytes([mp.KICKOUT_NOTICE]))[1] == "KICKOUT_NOTICE"
    assert mp.parse_message(bytes([0x7E]))[1].startswith("unknown")
