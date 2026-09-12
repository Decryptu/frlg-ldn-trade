"""Let's Go's session constants, pinned to the binary reading on docs/lgpe_session.md, and the
version-3 header through pia4."""
import struct
import types

import pytest

from pokeldn.ldn import pia4
from pokeldn.lgpe import (GAME_KEY, PASSPHRASE, PIA_VERSION, link_code, packet_iv, session_key,
                          session_keys)
from pokeldn.lgpe.session import APP_HEADER_SIZE
import lgpe_join


def test_constants_are_the_literals_read_off_main():
    assert PASSPHRASE == b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
    assert GAME_KEY == b"p1frXqxmeCZWFv0X"
    assert PIA_VERSION == 3
    assert link_code() == "pikachu pikachu pikachu"


def _net(app):
    return types.SimpleNamespace(application_data=app)


def test_session_keys_read_the_5_9_header():
    app = struct.pack("<IIBBHIQ", 0x11223344, 0xDEADBEEF, 4, APP_HEADER_SIZE, 0, 0x55667788, 0)
    app += b"\xAA" * 8
    k = session_keys(_net(app))
    assert k.network_id_le == bytes.fromhex("44332211")
    assert k.session_param == 0x55667788
    assert k.password_crc == 0xDEADBEEF
    assert k.session_key == session_key(0x55667788)
    hdr = lgpe_join.app_header(app)
    assert hdr["system_comm_version"] == 4 and hdr["header_size"] == APP_HEADER_SIZE
    assert hdr["game_data"] == "aa" * 8
    with pytest.raises(ValueError):
        session_keys(_net(b"\0" * 8))


def test_version_3_packet_round_trips_through_pia4():
    app = struct.pack("<IIBBHIQ", 0x01020304, 0, 4, APP_HEADER_SIZE, 0, 0xCAFEBABE, 0)
    k = session_keys(_net(app))
    mac = bytes.fromhex("48f1eb0a0b0c")
    nonce = (7).to_bytes(8, "big")
    iv = packet_iv(k, mac, nonce, source_id=1)
    body = pia4.pad_payload(b"\x01\x02\x03\x04")
    pkt = bytearray(pia4.build_packet(k.session_key, iv, body, station=1, nonce8=nonce))
    pkt[4] = 0x80 | PIA_VERSION
    hdr = pia4.PiaHeader4.parse(bytes(pkt))
    assert hdr.version == 3 and hdr.encrypted and hdr.station == 1
    pt = pia4.decrypt_payload(k.session_key, iv, pia4.ciphertext(bytes(pkt)), hdr.tag)
    assert pt == body
    h, pt2, m, sid = lgpe_join.try_decrypt(k, bytes(pkt), [bytes(6), mac])
    assert pt2 == body and m == mac and sid == 1


def test_pia3_message_framing_is_22_bytes_and_round_trips():
    from pokeldn.ldn import pia3
    src = 0xEB9B2220F1480000
    m = pia3.build_message(b"\x11\x22\x33", protocol=0x14, source=src, port=2, destination=0x2,
                           message_flags=pia3.MESSAGE_FLAG_BITMAP | pia3.MESSAGE_FLAG_UNBUNDLED)
    assert len(m) == 28 and m[1] == 1 and m[4] == 0x14 and m[5] == 2
    assert m[2:4] == b"\x00\x03" and m[6:14] == (2).to_bytes(8, "big")
    second = pia3.build_message(b"", protocol=0x58, source=src)
    pkt = pia3.pad_payload(m + second)
    msgs = pia3.parse_packet(pkt)
    assert [(x["protocol"], x["port"], x["payload"], x["source"]) for x in msgs] == [
        (0x14, 2, b"\x11\x22\x33", src), (0x58, 0, b"", src)]
    assert msgs[0]["flags"] == 0x09 and msgs[1]["at"] == 28
    app = struct.pack("<IIBBHIQ", 0x01020304, 0, 4, APP_HEADER_SIZE, 0, 0xCAFEBABE, 0)
    k = session_keys(_net(app))
    nonce = (9).to_bytes(8, "big")
    iv = packet_iv(k, bytes(6), nonce, source_id=0)
    data = pia3.build_packet(k.session_key, iv, pkt, nonce8=nonce)
    assert pia3.is_pia3(data) and not pia4.is_pia4(data)
    hdr = pia3.PiaHeader4.parse(data)
    assert pia3.decrypt_payload(k.session_key, iv, pia3.ciphertext(data), hdr.tag) == pkt


def test_station9_connection_request_round_trips():
    from pokeldn.ldn import station9
    loc = station9.station_location("169.254.105.2", 12345, 0x1122334455667788, 0x99AABBCC,
                                    0xDDEEFF00)
    req = station9.build_connection_request(0xEB9B2220F1480000, 0x0, loc, ack_id=7,
                                            connection_id=0x2A)
    assert req[0] == 1 and req[station9.OFF_VERSION] == 9 and req[station9.OFF_IS_INVERSE] == 0
    got = station9.parse_connection_request(req)
    assert got["constant_id"] == 0xEB9B2220F1480000 and got["ack_id"] == 7
    assert got["connection_id"] == 0x2A and got["location"] == loc
    assert station9.build_ack(7) == bytes.fromhex("0500000000000007")
    assert station9.ack_id_of(req) == 7
