"""The launcher's own send path, offline - the exact function a hardware run will call.

`tests/test_pia4.py` proves the framing against the console's own packets; this proves that
`swsh_connect.wrap` puts a Local Protocol ack inside it correctly, so the run spends its association
on a question rather than on a typo. There is no capture of one of our version-4 packets yet, so
this is a self-consistency check with the receiver's derivation on the other side of it.
"""

import swsh_connect

from pokeldn.ldn import local_protocol as lp, pia4, station_protocol as stp
from pokeldn.swsh.session import packet_iv, session_keys

APP_DATA = bytes.fromhex("0330112400000000051800008b718ac6")     # sw01's own advertisement
OUR_MAC = bytes.fromhex("7e5f4c3b2a19")


class _Net:
    application_data = APP_DATA


def _read_back(packet, mac=OUR_MAC):
    """Everything the console does with a packet of ours, in its order."""
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, mac, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    assert plain is not None, "the tag did not verify"
    header, body = pia4.parse_messages(plain)[0]
    return h, pia4.parse_message_header(header), body


def _ack(station=0, nonce8=b"\x01" * 8, seq=7):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8,
                             lp.build_ack(seq), lp.PROTOCOL, station)


def test_the_ack_the_run_sends_reads_back_as_an_ack():
    h, fields, body = _read_back(_ack())
    assert h.version == 4 and h.encrypted and len(h.tag) == pia4.TAG_SIZE
    assert fields["protocol"] == lp.PROTOCOL and fields["flags"] == pia4.MESSAGE_FLAGS
    assert fields["source"] == stp.ldn_constant_id(OUR_MAC)
    assert lp.parse_ack(body) == 7


def test_the_station_byte_reaches_the_header_and_the_iv_together():
    """The sweep only reads if the two move as one; a header saying 1 and an IV built on 0 would
    fail the tag and look exactly like the console ignoring us."""
    for station in (0, 1, 2):
        h, _, body = _read_back(_ack(station=station))
        assert h.station == station
        assert lp.parse_ack(body) == 7


def test_the_packet_is_padded_the_way_the_console_pads_its_own():
    """0xFF to a multiple of sixteen, which is what sw01's 160-byte ciphertext measures."""
    packet = _ack()
    assert (len(packet) - pia4.HEADER_SIZE) % 16 == 0
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, OUR_MAC, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    used = pia4.MESSAGE_HEADER_SIZE + 0x14                       # the ack is twenty bytes
    assert set(plain[used:]) <= {0xFF}
