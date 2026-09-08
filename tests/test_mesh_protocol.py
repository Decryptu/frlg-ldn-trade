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


# The sp35 join response, off the console, byte for byte out of scratchpad/sp35_pia.jsonl. Eleven
# identical copies arrived 500 ms apart because nothing acknowledged it.
SP35_JOIN_RESPONSE = bytes.fromhex(
    "0202000101000200080008000000000002060000a9fe0e013039000000000000eb9b2220f148"
    "0000002a1f29597bc2a30000000100000000000000000000000000000000000000000000000000"
    "000000000000000606a9fe0e023039a9fe0e0230390000000000001249a221d85800002b7f4c11"
    "32669aea050100010000000000000000000000000000000000000000000000000100010017cad56f")


def test_the_ack_id_is_the_last_four_bytes_big_endian():
    assert mp.read_ack_id(SP35_JOIN_RESPONSE) == 0x17CAD56F
    assert mp.read_ack_id(mp.build_join_request(7)) == 7      # the last four of six
    assert mp.read_ack_id(b"\x02\x00\x00") == 0          # 0x01542db8's borrow check answers 0


def test_a_mesh_message_is_acked_on_the_station_protocol_not_the_mesh_one():
    proto, payload = mp.ack_for(SP35_JOIN_RESPONSE)
    assert proto == stp.PROTOCOL == 0x14                 # NOT mp.PROTOCOL
    assert payload == bytes.fromhex("050000_0017cad56f".replace("_", ""))
    assert payload == stp.build_ack(0x17CAD56F)
    assert len(payload) == 8                             # main.bin 0x01550324 sends w3 = 8


def test_only_the_two_acked_types_produce_an_ack():
    assert mp.ack_for(mp.build_join_request(3))[0] == stp.PROTOCOL
    assert mp.ack_for(bytes([mp.UPDATE_MESH, 0, 0, 0, 0])) is None
    assert mp.ack_for(bytes([mp.DUMMY_ACK, 0, 0, 0])) is None
    assert mp.ack_for(b"") is None


def test_the_real_join_response_reads_back_as_the_mesh_the_console_named():
    out = mp.parse_join_response(SP35_JOIN_RESPONSE)
    assert out["stations"] == 2 and out["host_index"] == 0 and out["our_index"] == 1
    assert out["fragments"] == 1 and out["entries"] == 2 and out["update_counter"] == 0
    assert (out["max_active"], out["max_buffer"], out["max_total"]) == (8, 0, 8)
    assert out["ack_id"] == 0x17CAD56F
    host, us = out["station_info"]
    assert host["station_index"] == 0 and host["join_order"] == 0
    assert us["station_index"] == 1 and us["join_order"] == 1
    assert host["location"]["private"] == ("169.254.14.1", 12345)
    assert host["location"]["constant_id"] == 0xEB9B2220F1480000
    assert us["location"]["private"] == ("169.254.14.2", 12345)
    assert us["location"]["variable_id"] == 0x2B7F4C11


# One real UPDATE_MESH off the console, sp45. It sent 110 of these, every one identical, about once
# a second, and always at the full 556 bytes with the six empty seats left zero.
SP45_UPDATE_MESH = bytes.fromhex(
    "20020000000000050100020002060000a9fe07013039000000000000eb9b2220f1480000406a4ae6597bc2a30000000100000000000000000000000000000000000000000000000000000000000000000606a9fe07023039a9fe070230390000000000001249a221d85800002b7f4c1a32669aea0501000100000000000000000000000000000000000000000000000001000300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000")


def test_the_update_mesh_is_always_the_full_eight_seats():
    assert len(SP45_UPDATE_MESH) == mp.UPDATE_MESH_SIZE == 556
    assert mp.UPDATE_MESH_SIZE == 12 + 8 * mp.STATION_INFO_SIZE
    out = mp.parse_update_mesh(SP45_UPDATE_MESH)
    assert out["stations"] == 2 and out["host_index"] == 0
    assert out["update_counter"] == 5
    assert out["fragments"] == 1 and out["fragment_index"] == 0
    assert out["entries"] == 2 and out["base_index"] == 0
    assert len(out["station_info"]) == 2          # entries, not the length, says how many
    host, us = out["station_info"]
    assert host["station_index"] == 0 and host["join_order"] == 0
    # join order 3, not 1: it counts JOINS, and sp43/sp44/sp45 each took a seat in the same room
    # session. That is the field naming itself.
    assert us["station_index"] == 1 and us["join_order"] == 3
    assert host["location"]["private"][1] == 12345
    assert us["location"]["variable_id"] == 0x2B7F4C1A     # the --src-var sp45 ran with


def test_a_wrong_type_is_refused():
    with pytest.raises(ValueError):
        mp.parse_update_mesh(bytes([mp.JOIN_RESPONSE]) + bytes(20))


# --------------------------------------------------------------------------- version 4
# Sword/Shield. Read off the retail binary in session 57 (scratchpad/swsh/main.bin); the addresses
# are in mesh_protocol's own comments. Synthetic, like everything above.

def _success_v4(stations=2, our_index=1, fragments=1, fragment_entries=None, base=0):
    """A version-4 join response: the same 16-byte header, 64-byte entries, index at 0x3E."""
    count = stations if fragments == 1 else fragment_entries
    head = bytes([mp.JOIN_RESPONSE, stations, 0, our_index, fragments, 0,
                  fragment_entries or 0, base, 8, 0, 8, 0]) + struct.pack(">I", 42)
    body = b""
    for i in range(count):
        loc = stp.station_location(f"169.254.14.{i + 1}", 12345, 0x1122334455667788 + i,
                                   0xAABB0000 + i, 0xCCDD0000 + i)
        entry = bytearray(mp.STATION_INFO_SIZE_V4)
        entry[:len(loc)] = loc
        entry[mp.INDEX_FIELD_V4] = base + i
        body += bytes(entry)
    return head + body + struct.pack(">I", 0x17CAD56C)


def test_the_version_four_entry_is_sixty_four_bytes_with_the_index_at_0x3e():
    assert mp.STATION_INFO_SIZE_V4 == 0x40 and mp.INDEX_FIELD_V4 == 0x3E
    out = mp.parse_join_response(_success_v4(stations=3), version4=True)
    assert [e["station_index"] for e in out["station_info"]] == [0, 1, 2]
    assert out["station_info"][0]["location"]["private"] == ("169.254.14.1", 12345)
    assert out["station_info"][2]["location"]["variable_id"] == 0xAABB0002
    assert "join_order" not in out["station_info"][0]      # the byte at 0x3F is never read


def test_the_version_four_length_bound_is_the_thirty_two_station_table():
    # The parser refuses anything over 0x810, and 0x810 IS the full table - which is what says the
    # stride is 0x40 rather than 68 without trusting the disassembly of the loop alone.
    assert mp.JOIN_RESPONSE_MAX_V4 == 0x10 + mp.MAX_STATIONS_V4 * mp.STATION_INFO_SIZE_V4
    assert len(_success_v4(stations=mp.MAX_STATIONS_V4)) - 4 == mp.JOIN_RESPONSE_MAX_V4


def test_an_unfragmented_version_four_response_counts_by_stations_not_by_field_six():
    # 0x017b48f4 walks `stations` from base 0 and never reads [6] or [7]. A host that leaves them
    # zero would make the 5.31-5.45 reading return nothing at all.
    raw = bytearray(_success_v4(stations=2))
    raw[6] = raw[7] = 0
    out = mp.parse_join_response(bytes(raw), version4=True)
    assert out["entry_count"] == 2 and out["entry_base"] == 0
    assert len(out["station_info"]) == 2
    assert len(mp.parse_join_response(bytes(raw))["station_info"]) == 0    # 5.31-5.45 reads [6]


def test_a_fragmented_version_four_response_counts_by_field_six_into_slot_seven():
    out = mp.parse_join_response(_success_v4(stations=5, fragments=2, fragment_entries=2, base=3),
                                 version4=True)
    assert out["entry_count"] == 2 and out["entry_base"] == 3
    assert [e["station_index"] for e in out["station_info"]] == [3, 4]


def test_the_version_four_message_table_is_the_same_one_without_the_two_dummies():
    assert len(mp.MESH_TYPES_V4) == 19                     # the jump table's live entries
    assert mp.DUMMY_MESSAGE not in mp.MESH_TYPES_V4
    assert mp.DUMMY_ACK not in mp.MESH_TYPES_V4
    named = {v for v, k in mp.TYPE_NAMES.items() if not k.startswith(("PROTOCOL", "PORT_"))}
    assert mp.MESH_TYPES_V4 == named - {mp.DUMMY_MESSAGE, mp.DUMMY_ACK}


def test_the_version_four_join_request_is_the_one_we_already_build():
    # 0x017c1700 compares byte [1] against 0xFD and reads the ack id as the last four bytes.
    req = mp.build_join_request(0x11223344)
    assert req[1] == 0xFD
    assert mp.read_ack_id(req) == 0x11223344
    assert mp.ack_for(req) == (stp.PROTOCOL, stp.build_ack(0x11223344))


def test_the_lengths_sw29_measured_only_fit_the_sixty_four_byte_entry():
    """The wire confirms the stride twice, by length alone - no disassembly in either number."""
    assert mp.JOIN_RESPONSE_TWO_STATIONS_V4 == 148            # sw29's join response
    assert 0x10 + 2 * mp.STATION_INFO_SIZE + 4 == 156         # what 68-byte entries would give
    assert mp.UPDATE_MESH_SIZE_V4 == 524                      # sw29's update mesh
    assert mp.UPDATE_MESH_SIZE == 556                         # BDSP's, unchanged


def test_the_real_version_four_join_response_reads_back_as_the_mesh_the_console_named():
    """sw29, byte for byte off the console. Two stations, us at index 1."""
    raw = bytes.fromhex(
        "0202000101000200020008000000000002060000a9fe5f013039000000000000"
        "eb9b2220f148000069a75e26597bc2a300000001000000000000000000000000"
        "000000000000000000000000000000000606a9fe5f023039a9fe5f0230390000"
        "000000001249a221d858000050af6c5a32669aea050100010000000000000000"
        "000000000000000000000000000001003e3b1c08")
    assert len(raw) == mp.JOIN_RESPONSE_TWO_STATIONS_V4
    out = mp.parse_join_response(raw, version4=True)
    assert out["refused"] is False
    assert (out["stations"], out["host_index"], out["our_index"]) == (2, 0, 1)
    assert out["fragments"] == 1 and out["update_counter"] == 0
    assert out["ack_id"] == 0x3E3B1C08
    assert [e["station_index"] for e in out["station_info"]] == [0, 1]
    assert out["station_info"][0]["location"]["private"] == ("169.254.95.1", 12345)
    assert out["station_info"][1]["location"]["private"] == ("169.254.95.2", 12345)
    assert out["station_info"][0]["location"]["constant_id"] == 0xEB9B2220F1480000
    assert mp.ack_for(raw) == (stp.PROTOCOL, bytes.fromhex("050000003e3b1c08"))
