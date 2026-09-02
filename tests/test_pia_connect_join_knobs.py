"""Session-12 client-side join experiment knobs on ConnectionManager (all default-off)."""

from frlgsim import pia_connect
from frlgsim.pia_connect import PROTO_NET, PROTO_RTT, PROTO_SESSION


def _net_0x11(host_var=0x7620):
    # version, type, size, then a body whose first 4 bytes are the seqid; parse_net_conn_request
    # needs the host var + mac: build one via the host-side builder for realism.
    body = pia_connect.build_net_conn_request(2, host_var, b"\x02\x00\x00\x00\x00\x01", 1, ["169.254.1.1"])
    return body


def _cm(**kw):
    return pia_connect.ConnectionManager(b"\x58\xd8\x12\x21\x49\xa2", b"\x02\x00\x00\x00\x00\x01",
                                         "169.254.1.2", "169.254.1.1", player_name="PkCamp", **kw)


def test_defaults_send_the_join_once_and_ignore_rtt_before_finalize():
    cm = _cm()
    cm.on_message(PROTO_NET, _net_0x11(), tick=10)
    protos = [e["proto"] for e in cm.drain()]
    assert protos == [PROTO_NET, PROTO_SESSION]
    for t in range(11, 400):
        cm.maybe_repeat_join(t)
    assert cm.drain() == []
    rtt = bytes([0, 0, 0, 3]) + bytes(4) + bytes(8) + bytes(3) + b"\x76\x20"
    cm.on_message(PROTO_RTT, rtt, tick=20)
    assert cm.drain() == []          # native behaviour: no RTT answer before finalize


def test_join_repeat_and_rtt_before_finalize_and_player_id():
    pid = bytes(range(16))
    cm = _cm(join_repeat_ticks=30, rtt_before_finalize=True, player_id=pid)
    cm.on_message(PROTO_NET, _net_0x11(), tick=10)
    first = cm.drain()
    join = pia_connect.parse_session_join(first[1]["payload"])
    assert join["players"][0]["player_id"] == pid
    for t in range(11, 40):
        cm.maybe_repeat_join(t)
    assert cm.drain() == []
    cm.maybe_repeat_join(40)
    again = cm.drain()
    assert [e["proto"] for e in again] == [PROTO_SESSION]
    rtt = bytes([0, 0, 0, 3]) + bytes(4) + bytes(8) + bytes(3) + b"\x76\x20"
    cm.on_message(PROTO_RTT, rtt, tick=41)
    out = cm.drain()
    assert [e["proto"] for e in out] == [PROTO_RTT] and out[0]["payload"][0] == 1
