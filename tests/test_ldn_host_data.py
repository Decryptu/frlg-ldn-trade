"""Regressions for AP TAP-to-802.11 destination handling."""

import os
import struct
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
VENDORED_LDN = os.path.join(ROOT, "vendor", "LDN")
sys.path.insert(0, VENDORED_LDN)

import ldn
from ldn import wlan
from frlgsim.transport import HostTransport


def test_ldn_import_resolves_to_the_tracked_vendored_package():
    module_path = os.path.abspath(ldn.__file__)
    assert os.path.commonpath((module_path, VENDORED_LDN)) == VENDORED_LDN


class _StopTransmit(Exception):
    pass


DATA_KEY = bytes(range(16))
HOST_MAC = wlan.MACAddress("3c:33:00:60:94:93")
SWITCH_MAC = wlan.MACAddress("3c:a9:ab:f7:3c:06")


def _run_immediate(coroutine):
    """Drive a coroutine whose test doubles never actually suspend."""
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("test coroutine unexpectedly suspended")


def _hybrid_decrypted_frame(payload=b"arp-request"):
    """Build protected-header + CCMP-header + plaintext + retained-MIC bytes."""
    snap = wlan.SNAPHeader(protocol=wlan.ETH_P_ARP, payload=payload).encode()
    encrypted = wlan.DataFrame(
        target=HOST_MAC,
        source=SWITCH_MAC,
        bssid=HOST_MAC,
        tods=True,
        payload=snap,
    )
    encrypted.encrypt(DATA_KEY, 7, 0)
    encoded = encrypted.encode()
    return encoded[:32] + snap + encrypted.payload[-8:], snap


def test_radiotap_decoder_removes_only_an_advertised_fcs():
    body = b"802.11 frame"
    fcs = b"FCS!"

    flagged = wlan.RadiotapFrame(data=body + fcs, flags=0x10).encode()
    decoded = wlan.RadiotapFrame()
    decoded.decode(flagged)
    assert decoded.data == body

    unflagged = wlan.RadiotapFrame(data=body + fcs).encode()
    decoded = wlan.RadiotapFrame()
    decoded.decode(unflagged)
    assert decoded.data == body + fcs

    short = wlan.RadiotapFrame(data=b"123", flags=0x10).encode()
    decoded = wlan.RadiotapFrame()
    try:
        decoded.decode(short)
    except ValueError as exc:
        assert "shorter than its FCS" in str(exc)
    else:
        raise AssertionError("undersized flagged FCS was accepted")


def test_hardware_decrypted_ccmp_frame_is_normalized():
    hybrid, snap = _hybrid_decrypted_frame()
    capture = wlan.RadiotapFrame(
        data=hybrid + b"FCS!", flags=0x10).encode()
    radiotap = wlan.RadiotapFrame()
    radiotap.decode(capture)

    frame = wlan.DataFrame()
    frame.decode(radiotap.data)
    assert frame.protected is True
    assert frame.accept_decrypted_ccmp() is True
    assert frame.protected is False
    assert frame.payload == snap


def test_hardware_decrypted_ccmp_trusts_the_driver_verified_retained_mic():
    hybrid, _snap = _hybrid_decrypted_frame()
    frame = wlan.DataFrame()
    frame.decode(hybrid[:-1] + bytes([hybrid[-1] ^ 1]))

    assert frame.accept_decrypted_ccmp() is True
    assert frame.protected is False


def test_hardware_decrypted_ccmp_rejects_a_short_snap_and_mic_body():
    frame = wlan.DataFrame(
        target=HOST_MAC, source=SWITCH_MAC, bssid=HOST_MAC,
        tods=True, protected=True, nonce=7,
        payload=wlan.RFC1042_SNAP_PREFIX + b"123456789",
    )

    try:
        frame.accept_decrypted_ccmp()
    except ValueError as exc:
        assert "too short" in str(exc)
    else:
        raise AssertionError("undersized decrypted CCMP frame was accepted")


def test_ordinary_ccmp_frame_still_uses_software_decryption():
    snap = wlan.SNAPHeader(protocol=wlan.ETH_P_IP, payload=b"ip packet").encode()
    encrypted = wlan.DataFrame(
        target=HOST_MAC, source=SWITCH_MAC, bssid=HOST_MAC,
        tods=True, payload=snap)
    encrypted.encrypt(DATA_KEY, 9, 0)

    frame = wlan.DataFrame()
    frame.decode(encrypted.encode())
    assert frame.accept_decrypted_ccmp() is False
    frame.decrypt(DATA_KEY)
    assert frame.payload == snap


def test_ap_accept_option_delivers_hybrid_arp_to_the_tap():
    hybrid, _snap = _hybrid_decrypted_frame(b"arp body")
    frame = wlan.DataFrame()
    frame.decode(hybrid)
    writes = []

    class Monitor:
        def address(self):
            return HOST_MAC

    class Tap:
        async def write(self, data):
            writes.append(data)

    network = object.__new__(ldn.APNetwork)
    network._monitor = Monitor()
    network._tap = Tap()
    network._key = DATA_KEY
    network._peers = [SWITCH_MAC]
    network._param = SimpleNamespace(accept_decrypted_ccmp=True)

    _run_immediate(network._process_data_frame(frame))

    assert len(writes) == 1
    ethernet = wlan.EthernetFrame()
    ethernet.decode(writes[0])
    assert ethernet.target == HOST_MAC
    assert ethernet.source == SWITCH_MAC
    assert ethernet.protocol == wlan.ETH_P_ARP
    assert ethernet.payload == b"arp body"


def test_ap_ignores_looped_back_host_plaintext_before_rx_normalization():
    snap = wlan.SNAPHeader(protocol=wlan.ETH_P_IP, payload=b"host packet").encode()
    frame = wlan.DataFrame(
        target=SWITCH_MAC, source=HOST_MAC, bssid=HOST_MAC,
        fromds=True, protected=True, nonce=11, payload=snap)
    writes = []

    class Monitor:
        def address(self):
            return HOST_MAC

    class Tap:
        async def write(self, data):
            writes.append(data)

    network = object.__new__(ldn.APNetwork)
    network._monitor = Monitor()
    network._tap = Tap()
    network._key = DATA_KEY
    network._peers = [SWITCH_MAC]
    network._param = SimpleNamespace(accept_decrypted_ccmp=True)

    _run_immediate(network._process_data_frame(frame))

    assert writes == []
    assert frame.protected is True
    assert frame.payload == snap


def test_tap_destination_is_forwarded_to_data_sender():
    target = wlan.MACAddress("3c:a9:ab:f7:3c:06")
    ethernet = wlan.EthernetFrame(
        target=target,
        source=wlan.MACAddress("3c:33:00:60:94:93"),
        protocol=wlan.ETH_P_IP,
        payload=b"ip packet",
    )

    class Tap:
        async def read(self):
            return ethernet.encode()

    seen = []
    network = object.__new__(ldn.APNetwork)
    network._tap = Tap()

    async def send_data_frame(data, destination):
        seen.append((data, destination))
        raise _StopTransmit

    network._send_data_frame = send_data_frame

    async def run():
        try:
            await network._transmit_data_frames()
        except _StopTransmit:
            pass

    _run_immediate(run())

    assert len(seen) == 1
    snap = wlan.SNAPHeader()
    snap.decode(seen[0][0])
    assert snap.protocol == wlan.ETH_P_IP
    assert snap.payload == b"ip packet"
    assert seen[0][1] == target


def test_kernel_encrypted_unicast_keeps_pairwise_destination():
    target = wlan.MACAddress("3c:a9:ab:f7:3c:06")
    sent = []

    class Monitor:
        def address(self):
            return wlan.MACAddress("3c:33:00:60:94:93")

        async def send_frame(self, frame, *, encrypt=False):
            sent.append((frame, encrypt))

    network = object.__new__(ldn.APNetwork)
    network._monitor = Monitor()
    network._key = b"key-present"
    network._param = SimpleNamespace(skip_encryption=True)
    network._data_nonce = 0

    _run_immediate(network._send_data_frame(b"snap packet", target))

    assert len(sent) == 1
    frame, encrypt = sent[0]
    assert frame.target == target
    assert frame.payload == b"snap packet"
    assert encrypt is True


def test_ap_authorizes_station_after_custom_ldn_authentication():
    requests = []

    class Netlink:
        async def request(self, command, attrs):
            requests.append((command, attrs))

    access_point = object.__new__(wlan.AccessPoint)
    access_point._wlan = Netlink()
    access_point._index = 12

    _run_immediate(access_point.set_authorized(SWITCH_MAC))

    assert len(requests) == 1
    command, attrs = requests[0]
    assert command == wlan.nl80211.NL80211_CMD_SET_STATION
    assert attrs[wlan.nl80211.NL80211_ATTR_IFINDEX] == 12
    assert attrs[wlan.nl80211.NL80211_ATTR_MAC] == SWITCH_MAC.encode()
    mask, enabled = struct.unpack(
        "II", attrs[wlan.nl80211.NL80211_ATTR_STA_FLAGS2])
    expected = 1 << wlan.nl80211.NL80211_STA_FLAG_AUTHORIZED
    assert mask == expected
    assert enabled == expected


def test_host_transport_removes_participant_on_leave_event():
    logs = []
    host = HostTransport(log=logs.append)
    participant = SimpleNamespace(
        ip_address="169.254.31.2",
        mac_address=bytes.fromhex("3ca9abf73c06"),
        name=b"Chase",
    )
    join = type("JoinEvent", (), {"index": 1, "participant": participant})()
    leave = type("LeaveEvent", (), {"index": 1})()

    host._on_event(join, None)
    assert host.participants == [
        (1, "169.254.31.2", bytes.fromhex("3ca9abf73c06"), b"Chase")
    ]
    host._on_event(leave, None)
    assert host.participants == []
    assert logs[-1] == "[host] console left: idx=1"


def test_host_transport_logs_wireless_leave_reason():
    logs = []
    host = HostTransport(log=logs.append)
    host.participants = [(1, "169.254.31.2", bytes(SWITCH_MAC), b"Chase")]
    leave = type("LeaveEvent", (), {
        "index": 1, "reason": 8, "management_type": "deauthentication"
    })()

    host._on_event(leave, None)

    assert logs[-1] == (
        "[host] console left: idx=1 via deauthentication reason=8")


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("LDN host data tests: OK")
