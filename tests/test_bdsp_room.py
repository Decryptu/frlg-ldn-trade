"""What BDSP's Union Room says - the first payloads this project has read that the GAME wrote.

Every fixture is real, off a console, and the four position messages are four different places on
the Union Room floor.
"""

import pytest

from pokeldn.bdsp import room


# sp35, sp36, sp39, sp43 - one 20-byte reliable payload from each run.
POSITIONS = {
    "sp35": bytes.fromhex("0100110800315a005a611fc1cad38132e7ddb840"),
    "sp36": bytes.fromhex("0100110800310000c3f5e0c00000000000002841"),
    "sp39": bytes.fromhex("010011080031e1007a1908c100000000ba1fda40"),
    "sp43": bytes.fromhex("0100110800315a00487615c1000000003a0be640"),
}
SP36_TRAIL = bytes.fromhex("0200488c00cf00b4008c00cd00b4008e00c800ca009000c400ce00")


def test_every_captured_position_has_the_same_head_and_a_floor_of_zero():
    for tag, raw in POSITIONS.items():
        out = room.parse_position(raw)
        assert out["head"] == room.POSITION_HEAD, tag
        # the floor: exactly 0.0 in three of the four and 1.5e-08 in sp35, so it is a height on a
        # flat room and not a constant field
        assert abs(out["y"]) < 1e-6, tag
        assert room.is_position(raw)


def test_the_angle_is_degrees_and_lands_on_an_eighth_of_a_turn():
    angles = {tag: room.parse_position(raw)["angle"] for tag, raw in POSITIONS.items()}
    assert set(angles.values()) <= {0, 45, 90, 135, 180, 225, 270, 315}
    assert angles["sp36"] == 0 and angles["sp35"] == 90 and angles["sp43"] == 90


def test_the_coordinates_are_the_places_the_console_actually_stood():
    a = room.parse_position(POSITIONS["sp36"])
    assert round(a["x"], 2) == -7.03 and round(a["z"], 2) == 10.5
    b = room.parse_position(POSITIONS["sp43"])
    assert round(b["x"], 2) == -9.34 and round(b["z"], 2) == 7.19
    assert a["x"] != b["x"]                          # four runs, four different spots


def test_a_position_round_trips():
    raw = room.build_position(-7.03, 0.0, 10.5, angle=0)
    assert raw == POSITIONS["sp36"]
    assert room.parse_position(raw)["angle"] == 0


def test_what_is_not_a_position_is_refused():
    with pytest.raises(ValueError):
        room.parse_position(POSITIONS["sp36"][:19])
    with pytest.raises(ValueError):
        room.parse_position(b"\x00" * 20)
    assert not room.is_position(room.KEEPALIVE)


def test_the_trail_is_a_head_and_halfword_triples():
    out = room.parse_trail(SP36_TRAIL)
    assert out["head"] == bytes.fromhex("020048")
    assert out["points"][0] == (140, 207, 180)
    assert out["points"][1] == (140, 205, 180)       # it moves smoothly, point to point
    assert len(out["points"]) == (len(SP36_TRAIL) - 3) // 6
    assert out["trailing"] == b""


def test_the_keepalive_is_five_bytes():
    assert room.KEEPALIVE == bytes.fromhex("0400020000")
