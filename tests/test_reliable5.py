"""Pia 5.29-5.43's reliable sliding window (protocol 0x7c) - where BDSP's game data is.

The two fixtures are the whole reliable side of sp35: the console sent exactly these, to us by
station bitmap, and repeated them 3.1 s later because nothing acknowledged them.
"""

import pytest

from pokeldn.ldn import reliable5 as rl


SP35_FIRST = bytes.fromhex("0f00001400010001000100110800315a005a611fc1cad38132e7ddb840")
SP35_SECOND = bytes.fromhex("07000004000200010012000123")


def test_the_protocol_and_version_are_the_ones_the_console_advertises():
    assert rl.PROTOCOL == 0x7C and rl.VERSION == 3        # the wiki pins v3 to Pia 5.31-5.43


def test_the_header_is_nine_or_thirteen_bytes_not_the_wiki_eight_or_twelve():
    assert rl.header_size(0) == 9
    assert rl.header_size(1) == rl.header_size(31) == 13
    assert rl.MAX_DESTINATION_BITS == 31                  # cmp #0x20 / b.lo, not "not higher than 32"


def test_the_first_captured_message_is_a_whole_application_message():
    out = rl.parse(SP35_FIRST)
    assert out["flags"] == 0x0F
    assert out["flag_names"] == ["APPLICATION_DATA", "START", "END", "INITIALIZED"]
    assert out["stream_id"] == 0
    assert out["payload_size"] == 20 and len(out["payload"]) == 20
    assert out["sequence_id"] == 1 and out["lowest_pending"] == 1
    assert out["destination_bits"] == 0 and out["bitmap"] == []
    assert out["header_size"] == 9 and out["truncated"] is False and out["is_ack"] is False
    assert out["payload"].hex() == "01001108 00315a00 5a611fc1 cad38132 e7ddb840".replace(" ", "")


def test_the_second_captured_message_is_the_next_sequence_id():
    out = rl.parse(SP35_SECOND)
    assert out["flag_names"] == ["APPLICATION_DATA", "START", "END"]   # no INITIALIZED this time
    assert out["sequence_id"] == 2 and out["lowest_pending"] == 1
    assert out["payload"] == bytes.fromhex("12000123")


def test_the_header_round_trips():
    head = rl.build_header(0x0F, sequence_id=1, payload_size=20, lowest_pending=1)
    assert head == SP35_FIRST[:9]
    assert rl.parse(head + SP35_FIRST[9:])["payload"] == SP35_FIRST[9:]
    with_bits = rl.build_header(0x08, 5, 0, destination_bits=3, bitmap=[0b101])
    assert len(with_bits) == 13
    assert rl.parse(with_bits)["bitmap"] == [0b101]


def test_what_the_console_refuses_is_refused_here_too():
    with pytest.raises(ValueError):
        rl.parse(SP35_FIRST[:8])                          # cmp w2, #8 / b.ls
    with pytest.raises(ValueError):
        rl.parse(bytes([0x0F, 0, 0x05, 0xA1, 0, 1, 0, 1, 0]))     # payload size 0x5a1
    with pytest.raises(ValueError):
        rl.parse(bytes([0x0F, 0, 0, 0, 0, 1, 0, 1, 0x20]))        # 32 destination bits
    with pytest.raises(ValueError):
        rl.build_header(0x0F, 1, 0, destination_bits=32)


def test_an_ack_payload_round_trips_at_two_plus_twenty_one_per_entry():
    entries = [{"stream_id": 0, "ack_id": 2, "field_0x50": 3, "mask": bytes(range(16))},
               {"stream_id": 1, "ack_id": 9, "field_0x50": 0, "mask": b""}]
    raw = rl.build_ack_payload(entries)
    assert len(raw) == 2 + rl.ACK_ENTRY_SIZE * 2 == 44     # 0x0159716c: n * 0x14 + n + 2
    out = rl.parse_ack_payload(raw)
    assert out["count"] == 2 and out["unknown0"] == 0
    assert out["entries"][0]["ack_id"] == 2 and out["entries"][0]["field_0x50"] == 3
    assert out["entries"][0]["mask"] == bytes(range(16))
    assert out["entries"][1]["stream_id"] == 1 and out["entries"][1]["mask"] == bytes(16)
    with pytest.raises(ValueError):
        rl.build_ack_payload([entries[0]] * 33)            # cmp #0x21 / b.lo


def test_a_message_without_the_application_flag_is_an_ack():
    body = rl.build_ack_payload([{"stream_id": 0, "ack_id": 2}])
    msg = rl.build_header(rl.FLAG_IS_INITIALIZED, 0, len(body)) + body
    out = rl.parse(msg)
    assert out["is_ack"] is True
    assert rl.parse_ack_payload(out["payload"])["entries"][0]["ack_id"] == 2


# The console's own bulk acknowledgement, sp44: what it sent back after we put two application
# messages (sequence 0 and 1) into its reliable window. This is the only ack anyone has captured.
SP44_ACK = bytes.fromhex(
    "00000017ffff0003000001000002000100000000000000000000000000000000")


def test_the_captured_ack_reads_back_the_way_the_console_built_it():
    out = rl.parse(SP44_ACK)
    assert out["is_ack"] is True and out["flags"] == 0 and out["flag_names"] == []
    assert out["sequence_id"] == rl.ACK_SEQUENCE == 0xFFFF   # a control message has no sequence
    assert out["lowest_pending"] == 3 and out["payload_size"] == 23
    body = rl.parse_ack_payload(out["payload"])
    assert body == {"unknown0": 0, "count": 1,
                    "entries": [{"stream_id": 0, "ack_id": 2, "field_0x50": 1, "mask": bytes(16)}]}


def test_build_ack_message_reproduces_it_byte_for_byte():
    assert rl.build_ack_message(2, lowest_pending=3) == SP44_ACK
    # the halfword before the mask defaults to ack_id - 1, which is what the console sent
    assert rl.parse_ack_payload(rl.parse(rl.build_ack_message(9))["payload"]
                                )["entries"][0]["field_0x50"] == 8
