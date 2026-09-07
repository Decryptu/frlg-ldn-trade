"""BDSP's own protocol, above Pia - the messages the Union Room is made of.

Every fixture is real, off a console. The names come from `TeamLumi/opendpr`'s decompiled C#
(`Dpr.NetworkUtils.NetDataParser`), which names every message the game speaks.
"""

import pytest

from pokeldn.bdsp import room


JOIN_SP43 = bytes.fromhex("0100110800315a00487615c1000000003a0be640")
JOIN_SP36 = bytes.fromhex("0100110800310000c3f5e0c00000000000002841")
POS_SP36 = bytes.fromhex("0200488c00cf00b4008c00cd00b4008e00c800ca009000c400ce009400bb00cc00"
                         "96")
SMALL_A = bytes.fromhex("12000123")
SMALL_B = bytes.fromhex("23000100")


def test_the_framing_is_an_id_and_a_big_endian_length():
    for raw, data_id, length in ((JOIN_SP43, room.JOIN, 17), (JOIN_SP36, room.JOIN, 17),
                                 (SMALL_A, 0x12, 1), (SMALL_B, 0x23, 1)):
        out = room.parse(raw)
        assert out["data_id"] == data_id
        assert out["length"] == length == len(out["body"])
        assert out["truncated"] is False


def test_the_twenty_byte_message_is_a_JOIN_and_not_a_position():
    out = room.parse(JOIN_SP43)
    assert out["data_id"] == room.JOIN == 1 and out["name"] == "NetJoinData"
    j = out["join"]
    assert (j["avatar_id"], j["color_id"], j["casset_version"]) == (8, 0, 0x31)
    assert j["rot_y"] == 90
    assert round(j["x"], 3) == -9.341 and j["y"] == 0.0 and round(j["z"], 3) == 7.189


def test_a_join_round_trips():
    j = room.parse(JOIN_SP43)["join"]
    assert room.build_join(j["x"], j["y"], j["z"], rot_y=j["rot_y"]) == JOIN_SP43
    assert room.build_join(-7.03, 0.0, 10.5, rot_y=0) == JOIN_SP36


def test_pos_data_is_halfwords_at_a_twentieth_of_a_unit_with_x_negated():
    out = room.parse(POS_SP36)
    assert out["data_id"] == room.POS == 2 and out["name"] == "NetPosData"
    assert out["length"] == 72 and out["truncated"] is True     # the fixture is a short capture
    first = out["points"][0]
    assert first["raw"] == (140, 207)
    assert round(first["x"], 2) == -7.00 and round(first["z"], 2) == 10.35
    # and that is the same place the JOIN message named, which is what says they are one player
    assert abs(first["x"] - room.parse(JOIN_SP36)["join"]["x"]) < 0.1
    assert abs(first["z"] - room.parse(JOIN_SP36)["join"]["z"]) < 0.2


def test_pos_round_trips_through_the_games_own_scaling():
    raw = room.build_pos([(-7.00, 10.35, 180)])
    pts = room.parse(raw)["points"]
    assert pts[0]["raw"] == (140, 207) and pts[0]["rot_y"] == 180
    assert room.parse(room.build_pos([(-1.0, 2.0, 0)]))["points"][0]["raw"] == (20, 40)


def test_several_points_go_in_one_message():
    raw = room.build_pos([(-1.0, 2.0, 0), (-1.5, 2.5, 90), (-2.0, 3.0, 180)])
    out = room.parse(raw)
    assert out["length"] == 3 * room.POS_POINT_SIZE == 18
    assert len(out["points"]) == 3
    assert out["points"][2]["rot_y"] == 180


def test_a_short_message_is_refused():
    with pytest.raises(ValueError):
        room.parse(b"\x01\x00")
    with pytest.raises(ValueError):
        room.parse_join_body(b"\x00" * 16)


def test_the_keepalive_is_five_bytes():
    assert room.KEEPALIVE == bytes.fromhex("0400020000")
