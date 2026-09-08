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


# --------------------------------------------------------------------------- version 4
# Sword/Shield. The header is this module's, unchanged; the ACK PAYLOAD is the fixed table 5.29
# replaced. Read off the retail binary in session 57 after sw30's 96 acks were refused by size.

def test_the_version_four_ack_payload_is_the_size_the_handler_demands():
    from pokeldn.ldn import reliable4 as r4
    assert r4.ACK_PAYLOAD_SIZE == 0x260 == r4.ACK_ENTRIES * r4.ACK_ENTRY_SIZE == 32 * 19
    assert len(r4.build_ack_payload(21)) == r4.ACK_PAYLOAD_SIZE
    # and it is NOT the 5.29 size. This is the payload sw30 sent 96 times, refused unread.
    five = rl.build_ack_payload([{"stream_id": 0, "ack_id": 21, "field_0x50": 20, "mask": b""}])
    assert len(five) == 2 + rl.ACK_ENTRY_SIZE == 23 != r4.ACK_PAYLOAD_SIZE


def test_a_version_four_entry_is_a_stream_an_ack_id_and_a_mask_and_nothing_else():
    from pokeldn.ldn import reliable4 as r4
    body = r4.build_ack_payload(0x1234, stream_id=7, mask=bytes(range(16)), slots=[3])
    entries = r4.parse_ack_payload(body)
    assert len(entries) == r4.ACK_ENTRIES == 32
    assert entries[3] == {"slot": 3, "stream_id": 7, "ack_id": 0x1234, "mask": bytes(range(16))}
    assert body[3 * 19:3 * 19 + 3] == bytes([7, 0x12, 0x34])       # ack id is big-endian at [1]
    # every other slot is inert: 0xFF cannot match a real stream id
    assert all(e["stream_id"] == 0xFF for e in entries if e["slot"] != 3)


def test_filling_every_slot_answers_both_readings_of_which_one_is_read():
    from pokeldn.ldn import reliable4 as r4
    entries = r4.parse_ack_payload(r4.build_ack_payload(21))
    assert {e["ack_id"] for e in entries} == {21}
    assert {e["stream_id"] for e in entries} == {0}


def test_the_version_four_ack_message_is_this_modules_header_over_that_payload():
    from pokeldn.ldn import reliable4 as r4
    msg = r4.build_ack_message(21, lowest_pending=1)
    got = rl.parse(msg)
    assert got["is_ack"] and got["flags"] == 0
    assert got["sequence_id"] == rl.ACK_SEQUENCE == 0xFFFF
    assert got["payload_size"] == r4.ACK_PAYLOAD_SIZE and got["header_size"] == 9
    assert len(msg) == 9 + 0x260 == 617
    assert msg[:9].hex() == "00000260ffff000100"
    assert r4.parse_ack_payload(got["payload"])[0]["ack_id"] == 21


def test_a_wrongly_sized_ack_payload_is_refused_here_the_way_the_console_refuses_it():
    from pokeldn.ldn import reliable4 as r4
    with pytest.raises(ValueError, match="0x260"):
        r4.parse_ack_payload(b"\0" * 23)          # exactly what sw30 sent, 96 times
