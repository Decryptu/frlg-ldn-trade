"""Pia's RTT Protocol (0x58) - the thirteen bytes the mesh times a station with.

There is no wiki page for this one, so every field is read off BDSP's own ARM64 and then checked
against the thirteen messages sp35 captured. `docs/bdsp_pia.md` "The RTT protocol".
"""

import struct

import pytest

from pokeldn.ldn import rtt_protocol as rtt


# The first RTT request off the console, sp35, byte for byte out of scratchpad/sp35_pia.jsonl.
SP35_REQUEST = bytes.fromhex("0000000b0df9d3437b00000000")


def test_the_protocol_and_its_version_are_the_ones_the_console_advertises():
    assert rtt.PROTOCOL == 0x58 and rtt.VERSION == 3       # 0x015ada10 / 0x015ada18
    assert rtt.SIZE == 13                                  # 0x015adab4: mov w0, #0xd


def test_the_captured_request_reads_back_as_a_broadcast_request():
    out = rtt.parse(SP35_REQUEST)
    assert out["kind"] == rtt.REQUEST and out["name"] == "REQUEST"
    assert out["timestamp"] == 0x00000B0DF9D3437B
    assert out["target"] == 0                              # what the console broadcasts


def test_a_response_echoes_the_timestamp_unchanged():
    reply = rtt.response_for(SP35_REQUEST)
    assert len(reply) == rtt.SIZE
    assert reply[0] == rtt.RESPONSE
    assert reply[1:9] == SP35_REQUEST[1:9]                 # 0x015ad02c-0x015ad04c copies the u64
    assert struct.unpack_from(">I", reply, 9)[0] == rtt.ANY_TARGET == 0
    assert rtt.parse(reply)["timestamp"] == rtt.parse(SP35_REQUEST)["timestamp"]


def test_a_target_can_be_named_when_one_is_known():
    reply = rtt.response_for(SP35_REQUEST, target=0x002A1F29)
    assert rtt.parse(reply)["target"] == 0x002A1F29


def test_only_a_request_produces_a_response():
    assert rtt.response_for(rtt.build(rtt.RESPONSE, 1)) is None
    assert rtt.response_for(rtt.build(7, 1)) is None        # 0x015ad020 drops anything but 0 and 1
    assert rtt.response_for(b"") is None


def test_a_short_message_is_refused_the_way_the_console_refuses_it():
    with pytest.raises(ValueError):
        rtt.parse(SP35_REQUEST[:12])                        # cmp w2, #0xc / b.hi
    assert rtt.parse(SP35_REQUEST + b"\xff")["kind"] == 0    # longer is read, not refused


def test_build_round_trips_through_parse():
    raw = rtt.build(rtt.REQUEST, 0x0123456789ABCDEF, 0xDEADBEEF)
    assert raw.hex() == "00" + "0123456789abcdef" + "deadbeef"
    assert rtt.parse(raw) == {"kind": 0, "name": "REQUEST",
                              "timestamp": 0x0123456789ABCDEF, "target": 0xDEADBEEF}
