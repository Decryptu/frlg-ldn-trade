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


def test_station9_connection_response_is_read_where_the_handler_looks():
    from pokeldn.ldn import station9
    host_const, host_var = 0xEB9B2220F1480000, 0xC30760A9
    resp = station9.build_connection_response(host_const, host_var, ack_id=3)
    assert len(resp) == station9.ACCEPTED_RESPONSE_SIZE + 4
    assert resp[0] == station9.CONNECTION_RESPONSE and resp[1] == 0
    assert resp[station9.OFF_RESPONSE_CONSTANT_ID:station9.OFF_RESPONSE_CONSTANT_ID + 8] == \
        host_const.to_bytes(8, "big")
    assert resp[station9.OFF_RESPONSE_VARIABLE_ID:station9.OFF_RESPONSE_VARIABLE_ID + 4] == \
        host_var.to_bytes(4, "big")
    assert resp[station9.OFF_RESPONSE_GATE] == 1 and resp[-4:] == (3).to_bytes(4, "big")


def test_clone_clock_reply_matches_the_serializer():
    from pokeldn.ldn import clone
    req = bytes.fromhex("0311c2350000000100020000000000003647")
    r = clone.parse_clock_request(req)
    assert r["type"] == clone.CLOCK_REQUEST and r["field_a"] == 0xC235 and r["count"] == 1
    assert r["participant"] == 2 and r["clock"] == 0x3647
    rep = clone.reply_to(req)
    assert len(rep) == 22 and rep[0] == 3 and rep[1] == clone.CLOCK_REPLY
    assert rep[2:4] == b"\xc2\x35" and rep[4:8] == (1).to_bytes(4, "big")
    assert rep[8:10] == (2).to_bytes(2, "big") and rep[0xA:0xE] == b"\x00\x00\x00\x00"
    assert rep[0xE:0x16] == (0x3647).to_bytes(8, "big")
    assert clone.parse_clock_request(b"\x03\x21" + b"\x00" * 16) is None


def test_clone_participate_is_ten_bytes():
    from pokeldn.ldn import clone
    p = clone.build_participate(field_a=0xC235, value=1, participant=2)
    assert len(p) == 10 and p[0] == 3 and p[1] == clone.PARTICIPATE
    assert p[2:4] == b"\xc2\x35" and p[4:8] == (1).to_bytes(4, "big")
    assert p[8:10] == (2).to_bytes(2, "big")


def test_clone_participant_reproduces_the_two_endpoint_exchange():
    """The measured exchange (docs/lgpe_session.md "The Clone Protocol"): a reply carries the
    replier's own count, the requester's bitmap, the replier's ms clock and the request's tick; the
    participate goes out after ten answered requests; the peer's participate is acked with 0x33."""
    from pokeldn.ldn import clone
    p = clone.Participant(100.0, dest=0x0001)
    # the host's first request, as captured
    req = bytes.fromhex("0311161b0000000100020000000000013483")
    rep, = p.receive(req, 100.275)
    r = clone.parse_clock_reply(rep)
    assert rep[1] == clone.CLOCK_REPLY and r["count"] == 1 and r["participant"] == 0x0001
    assert r["ms"] == 275 and r["clock"] == 0x13483
    # our own requests, one per interval, count continuing
    out = p.poll(100.3)
    assert len(out) == 1 and out[0][1] == clone.CLOCK_REQUEST and len(out[0]) == 18
    assert clone.parse_clock_request(out[0])["count"] == 2
    assert p.poll(100.31) == []
    # ten answers bring the participate, count continuing, bitmap 0x0003
    for i in range(10):
        p.poll(101 + i)
        assert p.receive(clone.build_clock_reply(0, 0, 1, 0, kind=clone.CLOCK_REPLY), 101 + i) == []
    out = p.poll(111.0)
    assert out[-1][1] == clone.PARTICIPATE and out[-1][8:10] == b"\x00\x03"
    assert clone.parse_clock_request(out[0])["count"] + 1 == int.from_bytes(out[-1][4:8], "big")
    # after that our replies are 0x22, and the host's participate draws a 0x33 to its bit
    rep, = p.receive(req, 112.0)
    assert rep[1] == clone.CLOCK_REPLY_SYNCED
    ack, = p.receive(bytes.fromhex("033116dd000000240003"), 112.1)
    assert ack[1] == clone.PARTICIPATE_ACK and ack[8:10] == b"\x00\x01" and len(ack) == 10
    # two participants against each other both participate
    a, b = clone.Participant(0.0, dest=0x0002), clone.Participant(0.0, dest=0x0001)
    t = 0.0
    while t < 5 and not (a.participated and b.participated):
        for src, dst in ((a, b), (b, a)):
            for m in src.poll(t):
                for back in dst.receive(m, t):
                    src.receive(back, t)
        t += 0.05
    assert a.participated and b.participated


def test_sync_clock_matches_the_wiki_layout():
    """A request carries the sender's tick and eight zero bytes; the reply copies the tick and
    adds the mesh clock in ms. Bytes from the two-endpoint capture."""
    from pokeldn.ldn import sync_clock
    req = bytes.fromhex("00000000412702000000000000000000")
    rep = bytes.fromhex("00000000412702000000000000001864")
    assert sync_clock.parse_message(req) == (0x41270200, 0)
    assert sync_clock.parse_message(rep) == (0x41270200, 0x1864)
    assert sync_clock.build_request(0x41270200) == req
    s = sync_clock.SyncClock(100.0)
    out, = s.poll(100.0)
    assert len(out) == 16 and out[8:] == b"\0" * 8 and s.poll(100.5) == []
    tick = sync_clock.parse_message(out)[0]
    assert tick == int(100.0 * sync_clock.TICK_HZ)
    assert s.receive(struct.pack(">QQ", tick, 6244), 100.040) == []
    assert s.clock_ms == 6244 + 20            # half the 40 ms round trip
    assert s.now_ms(101.040) == s.clock_ms + 1000
    assert s.poll(102.0) and s.replies == 1
