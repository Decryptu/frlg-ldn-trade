import json
import os
import tempfile
from types import SimpleNamespace

from frlgsim import ldntrace, transport


_IW_NO_AP = """Wiphy phy0
Supported interface modes:
 * managed
 * monitor
software interface modes (can always be added):
 * monitor
"""

_IW_WITH_AP = """Wiphy phy1
Supported interface modes:
 * managed
 * AP
 * monitor
software interface modes (can always be added):
 * monitor
"""


def test_preflight_rejects_phy_without_ap_mode():
    modes, soft = transport._parse_iw_modes(_IW_NO_AP)
    assert modes == ["managed", "monitor"] and soft == ["monitor"]
    try:
        transport.preflight_host("phy0", log=lambda *parts: None, _iw_output=_IW_NO_AP)
    except RuntimeError as exc:
        assert "no AP mode" in str(exc) and "AP-capable adapter" in str(exc)
    else:
        raise AssertionError("preflight accepted a phy without AP mode")


def test_preflight_accepts_ap_capable_phy():
    assert transport.preflight_host(
        "phy1", log=lambda *parts: None, _iw_output=_IW_WITH_AP) is True


def test_known_host_adapter_profiles_report_required_flags():
    alfa = transport.wifi_profile_messages("mt76x0u", True, False)
    assert alfa == [
        "Wi-Fi adapter profile: ALFA AWUS036ACHM (mt76x0u); expected "
        "--skip-encryption --no-accept-decrypted-ccmp."
    ]

    tplink = transport.wifi_profile_messages("rtw88_8822bu", True, True)
    assert tplink == [
        "Wi-Fi adapter profile: TP-Link Archer T3U (USB 2357:012d) "
        "(rtw88_8822bu); expected --skip-encryption --accept-decrypted-ccmp."
    ]

    mismatch = transport.wifi_profile_messages("rtw88_8822bu", True, False)
    assert len(mismatch) == 2
    assert mismatch[1].startswith("WARNING:")
    assert transport.wifi_profile_messages("unknown", False, False) == []


def test_tracer_writes_records_and_summary():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "trace.jsonl")
        tracer = ldntrace.Tracer(path, log=lambda *parts: None)
        tracer.write("udp_out", dst="169.254.1.255", hex="5c00")
        tracer.write("advert", nonce="00000001", hex="7f0022aa")
        tracer.close()
        with open(path, encoding="utf-8") as stream:
            records = [json.loads(line) for line in stream]
    assert [record["kind"] for record in records] == ["udp_out", "advert", "summary"]
    assert all(record["rec"] == "trace" and "ts" in record for record in records)
    assert records[2]["counts"]["advert"] == 1


def test_attached_trace_records_rx_option_and_rejection_reason():
    class Network:
        def __init__(self):
            self._param = SimpleNamespace(
                skip_encryption=True, accept_decrypted_ccmp=True)
            self._send_advertisement = self._unused
            self._process_authentication_event = self._unused
            self._register_participant = self._unused
            self._process_disassociation = self._unused
            self._send_data_frame = self._unused
            self._process_data_frame = self._reject

        async def _unused(self, *args, **kwargs):
            raise AssertionError("unused test hook was called")

        async def _reject(self, frame):
            raise ValueError("retained MIC did not verify")

    frame = SimpleNamespace(
        source="switch", target="host", protected=True,
        nonce=7, keyid=0, tods=True, fromds=False,
        payload=b"\xAA\xAA\x03\x00\x00\x00payload-and-mic",
    )

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "trace.jsonl")
        tracer = ldntrace.Tracer(path, log=lambda *parts: None)
        network = Network()
        ldntrace.attach(network, tracer, log=lambda *parts: None)
        coroutine = network._process_data_frame(frame)
        try:
            coroutine.send(None)
        except ValueError as exc:
            assert "retained MIC" in str(exc)
        else:
            raise AssertionError("data-frame rejection was swallowed")
        tracer.close()
        with open(path, encoding="utf-8") as stream:
            records = [json.loads(line) for line in stream]

    assert records[0] == {
        "rec": "trace", "kind": "network_config", "ts": records[0]["ts"],
        "skip_encryption": True, "accept_decrypted_ccmp": True,
    }
    rejected = next(record for record in records
                    if record["kind"] == "dataframe_rejected")
    assert rejected["candidate"] is True
    assert rejected["error"] == "ValueError: retained MIC did not verify"
