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
