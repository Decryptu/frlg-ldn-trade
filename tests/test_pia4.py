"""Pia version 4, against the packets a retail Sword actually sent us.

The two packets below are from sw01 (session 55), captured while we held a seat in a Sword's LDN
session with its Link Trade over local communication open. They are a GOLDEN VECTOR in the strict
sense: the tag is sixteen bytes and unforgeable, so a change that breaks the derivation, the IV or
the framing cannot pass these.
"""

from Crypto.Cipher import AES

from pokeldn.ldn import pia4
from pokeldn.swsh.session import packet_iv, session_keys

# The advertisement the capture's own session carried. A DIFFERENT session from the two scans
# earlier the same evening - the network id at 0 and the seed at 12 both move per session, which is
# what made an earlier sweep of the wrong advertisement's values fail against these packets.
APP_DATA = bytes.fromhex("0330112400000000051800008b718ac6")
CONSOLE_MAC = bytes.fromhex("48f1eb209b22")

STATION_ANNOUNCE = bytes.fromhex(
    "32ab986484000000452d57647fe03a54f4d35e83aa655a5425aef3a2fe5a2ec7154568d7a532cc620981f7a1"
    "8e8dc067c19d1a8fbbed2dd0667589303b2d99524ec3321910372a0a5609df84a25a306c7bb1f99e57e6676b"
    "70dfcf01ef08855304e8fc7717a3c7a913a5462fc2851fcd603c31b4e868d40ad505249fddb43ed35c54436b"
    "2a51e1f7f209a8f7077e3b5b3c355294b4695cb0544244d899e67dc308d183f0d5fb441d48cac6503ede6ddf"
    "8407615b1af22b760fac8d66668ea37a")
SHORT_MESSAGE = bytes.fromhex(
    "32ab986484000000452d57647fe03bcb64917791e8316e48b8ecb61e8ef29509c527ad3a3b557907de32b370"
    "f50fb0ad5ca8dcc63a0f7cdb0caaa4c00037199a94dd0407fd09df3ce124bd26142a4b70")


class _Net:
    application_data = APP_DATA


def _decrypt(packet):
    h = pia4.PiaHeader4.parse(packet)
    keys = session_keys(_Net())
    iv = packet_iv(keys, CONSOLE_MAC, h.nonce8)
    return AES.new(keys.session_key, AES.MODE_GCM, nonce=iv, mac_len=pia4.TAG_SIZE
                   ).decrypt_and_verify(pia4.ciphertext(packet), h.tag)


def test_the_header_reads_the_way_the_deserializer_writes_it():
    h = pia4.PiaHeader4.parse(STATION_ANNOUNCE)
    assert h.version == 4 and h.encrypted
    assert h.station == 0
    assert h.session_id == 0
    assert h.nonce8.hex() == "452d57647fe03a54"
    assert len(h.tag) == 16                        # not truncated, unlike 5.27-5.45
    assert pia4.is_pia4(STATION_ANNOUNCE)


def test_a_header_round_trips():
    h = pia4.PiaHeader4.parse(STATION_ANNOUNCE)
    assert h.pack() == STATION_ANNOUNCE[:pia4.HEADER_SIZE]


def test_bdsps_version_is_not_taken_for_this_one():
    bdsp = bytearray(STATION_ANNOUNCE)
    bdsp[4] = 0x80 | 9
    assert not pia4.is_pia4(bytes(bdsp))


def test_the_console_packets_authenticate():
    """The whole derivation, end to end: advertisement -> session key -> IV -> tag."""
    assert len(_decrypt(STATION_ANNOUNCE)) == 160
    assert len(_decrypt(SHORT_MESSAGE)) == 48


def test_the_station_announcement_lists_both_of_us():
    """169.254.14.1 is the console and .2 is the seat we took, both on the Pia port."""
    plain = _decrypt(STATION_ANNOUNCE)
    assert bytes.fromhex("a9fe0e013039") in plain
    assert bytes.fromhex("a9fe0e023039") in plain


def test_the_framing_accounts_for_the_payload_exactly():
    for packet, size in ((STATION_ANNOUNCE, 121), (SHORT_MESSAGE, 16)):
        plain = _decrypt(packet)
        messages = pia4.parse_messages(plain)
        assert len(messages) == 1
        header, body = messages[0]
        assert len(header) == pia4.MESSAGE_HEADER_SIZE == 24
        assert len(body) == size
        used = 24 + size
        assert set(plain[used + (-used % 4):]) <= {0xFF}


def test_every_message_header_in_the_capture_held_the_same_constants():
    for packet in (STATION_ANNOUNCE, SHORT_MESSAGE):
        header = pia4.parse_messages(_decrypt(packet))[0][0]
        assert header[0] == 0x7F                   # the presence byte
        assert header[1] == 0x09                   # message flags
        assert header[4] == 0x24                   # protocol
        assert header[8:16] == b"\0" * 8           # destination, broadcast


# --- What we send back. Session 56. ------------------------------------------------------------
#
# There is no capture of a version-4 packet LEAVING this machine, so the only offline checks
# available are these two: our builder reproduces the console's own bytes when handed the console's
# own values, and a packet we build decrypts under the derivation the console would use on it.

from pokeldn.ldn import local_protocol as lp, station_protocol as stp

CONSOLE_CONSTANT = stp.ldn_constant_id(CONSOLE_MAC)
OUR_MAC = bytes.fromhex("7e5f4c3b2a19")


def test_the_console_constant_id_is_what_its_message_header_carries():
    """Two independent fields agree: the update session's host_constant_id and the message
    header's eight-byte source, both `ldn_constant_id` over the scanned MAC - and they disagree
    about byte order, the header big-endian and the Local Protocol's body little-endian."""
    plain = _decrypt(STATION_ANNOUNCE)
    header, body = pia4.parse_messages(plain)[0]
    assert pia4.parse_message_header(header)["source"] == CONSOLE_CONSTANT \
        == 0xEB9B2220F1480000
    assert int.from_bytes(lp.parse_update_session(body).host_constant_id, "little") \
        == CONSOLE_CONSTANT


def test_our_builder_reproduces_the_consoles_own_message_header():
    console = pia4.parse_messages(_decrypt(STATION_ANNOUNCE))[0]
    built = pia4.build_message(console[1], protocol=0x24, source=CONSOLE_CONSTANT)
    assert built[:pia4.MESSAGE_HEADER_SIZE] == console[0]


def test_the_announcement_is_the_local_protocols_update_session():
    """Protocol 0x24 is Pia's Local Protocol here too - BDSP's parser reads Sword's field for
    field, which is what says the ack is the right thing to answer with."""
    body = pia4.parse_messages(_decrypt(STATION_ANNOUNCE))[0][1]
    us = lp.parse_update_session(body)
    assert us.sequence_id == 2 and us.allow_participating
    assert [(n.ip, n.port, n.ranking) for n in us.occupied] == [
        ("169.254.14.1", 12345, 0), ("169.254.14.2", 12345, 1)]


def test_a_packet_we_build_decrypts_the_way_the_console_would_read_it():
    """End to end, with the run's own derivation on both sides: ack -> message -> packet ->
    the receiver's IV -> the ack's sequence id back out."""
    keys = session_keys(_Net())
    our_constant = stp.ldn_constant_id(OUR_MAC)
    for station in (0, 1):
        nonce8 = bytes([station]) * 8
        body = pia4.build_message(lp.build_ack(2), protocol=lp.PROTOCOL, source=our_constant)
        packet = pia4.build_packet(keys.session_key,
                                   packet_iv(keys, OUR_MAC, nonce8, source_id=station),
                                   body, station=station, nonce8=nonce8)

        h = pia4.PiaHeader4.parse(packet)              # now read it as the console would
        assert h.station == station and h.version == 4 and h.encrypted
        plain = pia4.decrypt_payload(keys.session_key,
                                     packet_iv(keys, OUR_MAC, h.nonce8, source_id=h.station),
                                     pia4.ciphertext(packet), h.tag)
        assert plain is not None and len(plain) % 16 == 0
        header, payload = pia4.parse_messages(plain)[0]
        fields = pia4.parse_message_header(header)
        assert fields["protocol"] == lp.PROTOCOL == 0x24
        assert fields["flags"] == 0x09 and fields["present"] == 0x7F
        assert fields["destination"] == 0 and fields["source"] == our_constant
        assert lp.parse_ack(payload) == 2


def test_the_tag_refuses_a_packet_built_under_the_wrong_station_byte():
    """The IV's source id follows the header byte, so a receiver reading 0 cannot verify a packet
    built with 1 - which is what makes the sweep readable rather than ambiguous."""
    keys = session_keys(_Net())
    nonce8 = b"\x11" * 8
    body = pia4.build_message(lp.build_ack(2), protocol=lp.PROTOCOL, source=0)
    packet = pia4.build_packet(keys.session_key, packet_iv(keys, OUR_MAC, nonce8, source_id=1),
                               body, station=1, nonce8=nonce8)
    assert pia4.decrypt_payload(keys.session_key, packet_iv(keys, OUR_MAC, nonce8, source_id=0),
                                pia4.ciphertext(packet), pia4.PiaHeader4.parse(packet).tag) is None


# --------------------------------------------------------------------------- more than one message
# sw29, the first capture in which a Sword ever put two messages in one packet. Both vectors are
# the decrypted plaintext of a real packet, taken from the capture rather than typed.

SW29_RELIABLE = bytes.fromhex(          # RTT, then three reliable-window messages
    "7f010010580000000000000000000002eb9b2220f14800000000000000000000"
    "00000e7840e6df8706000f7c0000000f0000060001000100610000000a000000"
    "00070000060002000100610000000a0000070000060003000100610000000a00")

SW29_TWO_PORTS = bytes.fromhex(         # the same 42-byte body on port 0 and then port 1
    "7f11002a800000000000000000000002eb9b2220f1480000484b6260604af8ff"
    "9f819151c87391e28d0806206064c000834268140c0700000000ffff03005fb2"
    "04b900000480000001484b6260604af8ff9f819151c87391e28d0806206064c0"
    "00834268140c0700000000ffff03005fb204b900ffffffffffffffffffffffff")


def test_a_header_is_as_long_as_its_presence_byte_says():
    assert pia4.message_header_size(0x7F) == pia4.MESSAGE_HEADER_SIZE == 24
    assert pia4.message_header_size(0x06) == 1 + 2 + 4      # size and protocol|port only
    assert pia4.message_header_size(0x04) == 1 + 4          # protocol|port only
    assert pia4.message_header_size(0x00) == 1              # everything inherited
    # bits 0x20 and 0x40 own no field, which is why 0x7F and 0x1F are the same length
    assert pia4.message_header_size(0x1F) == pia4.message_header_size(0x7F)


def test_a_presence_byte_of_zero_is_a_message_and_not_the_end_of_the_packet():
    """The console's own walk stops at 0xFF alone (0x01852da0). Stopping at 0x00 as well threw
    away two of the three reliable messages in this packet. Over sw29 the old walk found
    247 messages where there are 1740, and left a non-padding tail on 159 of 238 packets."""
    msgs = pia4.parse_packet(SW29_RELIABLE)
    assert [m["present"] for m in msgs] == [0x7F, 0x06, 0x00, 0x00]
    assert [m["protocol"] for m in msgs] == [0x58, 0x7C, 0x7C, 0x7C]
    assert [m["header_size"] for m in msgs] == [24, 7, 1, 1]
    last = msgs[-1]
    used = last["at"] + last["header_size"] + last["size"]
    assert used == len(SW29_RELIABLE)                       # every byte accounted for


def test_an_omitted_field_comes_from_the_previous_message_in_the_packet():
    """0x01853050, bit by bit: flags, size, protocol|port, destination and source in turn."""
    first, second = pia4.parse_packet(SW29_TWO_PORTS)
    assert first["present"] == 0x7F and second["present"] == 0x04
    assert second["inherited"] == {"flags", "size", "destination", "source"}
    assert second["size"] == first["size"] == 42            # inherited, not "the rest of the packet"
    assert second["payload"] == first["payload"]
    assert (first["protocol"], first["port"]) == (0x80, 0)  # the one field it does state
    assert (second["protocol"], second["port"]) == (0x80, 1)
    assert second["source"] == first["source"] == CONSOLE_CONSTANT


def test_the_walk_consumes_each_packet_up_to_its_ff_padding():
    for plain in (SW29_RELIABLE, SW29_TWO_PORTS):
        last = pia4.parse_packet(plain)[-1]
        used = last["at"] + last["header_size"] + last["size"]
        assert set(plain[used + (-used % 4):]) <= {0xFF}


def test_parse_messages_still_hands_back_the_header_as_sent():
    # every caller and capture tool speaks this; a short header stays short
    assert [len(h) for h, _ in pia4.parse_messages(SW29_RELIABLE)] == [24, 7, 1, 1]
    assert pia4.parse_message_header(pia4.parse_messages(SW29_TWO_PORTS)[1][0]) == {
        "present": 0x04, "proto_port": 0x80000001, "protocol": 0x80, "port": 1}


def test_swords_rtt_and_reliable_messages_read_through_the_modules_we_have():
    """sw29's own bodies. RTT needed a version-4 size; the reliable window needed nothing."""
    from pokeldn.ldn import reliable5 as r5, rtt_protocol as rtt

    req = bytes.fromhex("000000000000000000000e7840e6df87")
    assert len(req) == rtt.SIZE_V4 == 16 != rtt.SIZE          # BDSP's is 13
    assert rtt.parse_v4(req) == {"kind": rtt.REQUEST, "name": "REQUEST",
                                 "timestamp": 0x00000E7840E6DF87, "unread": b"\0" * 7}
    assert rtt.response_for_v4(req) == b"\x01" + req[1:]      # echo everything we did not read

    got = r5.parse(bytes.fromhex("0f0000060001000100610000000a00"))
    assert got["flag_names"] == ["APPLICATION_DATA", "START", "END", "INITIALIZED"]
    assert (got["sequence_id"], got["lowest_pending"], got["stream_id"]) == (1, 1, 0)
    assert got["header_size"] == 9 and got["payload"] == bytes.fromhex("610000000a00")
    assert not got["truncated"] and not got["is_ack"]
