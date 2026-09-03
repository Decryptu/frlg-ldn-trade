"""JSONL tracer for the LDN hosting path: attach() rebinds hooks on a live ldn.APNetwork INSTANCE (its nursery loops
resolve self._send_advertisement etc. per call). Every wrapper degrades to a log line; a tracer bug must never break hosting.
"""

import json
import time

DATAFRAME_HEX_LIMIT = 20


class Tracer:
    def __init__(self, path, log=print):
        self.path = path
        self.log = log
        self._f = open(path, "a", buffering=1)
        self.counts = {}

    def write(self, kind, **fields):
        rec = {"rec": "trace", "kind": kind, "ts": round(time.time(), 6)}
        rec.update(fields)
        try:
            self._f.write(json.dumps(rec) + "\n")
        except (OSError, TypeError, ValueError) as e:       # pragma: no cover
            self.log(f"[trace] write failed ({kind}): {e}")
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def close(self):
        try:
            if self.counts:
                self.write("summary", counts=dict(self.counts))
            self._f.close()
        except OSError:                                     # pragma: no cover
            pass


def _hex(b):
    return bytes(b).hex()


def attach(network, tracer, log=print):
    param = getattr(network, "_param", None)
    tracer.write(
        "network_config",
        skip_encryption=bool(getattr(param, "skip_encryption", False)),
        accept_decrypted_ccmp=bool(
            getattr(param, "accept_decrypted_ccmp", False)),
    )

    orig_send_advert = network._send_advertisement
    state = {"last_nonce": None}

    async def send_advertisement():
        try:
            nonce = bytes(network._network.nonce)
            if nonce != state["last_nonce"]:
                state["last_nonce"] = nonce
                frame = network._network.build_advertisement(network._key_derivation)
                tracer.write("advert", nonce=_hex(nonce), hex=_hex(frame.encode()))
                tracer.write("beacon_appdata", hex=_hex(network._network.application_data or b""))
                log(f"[trace] advertisement updated (nonce {nonce.hex()}, "
                    f"{len(network._network.application_data or b'')}B app_data)")
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] advert hook error: {e}")
        return await orig_send_advert()

    network._send_advertisement = send_advertisement

    orig_auth = network._process_authentication_event

    async def process_authentication_event(event):
        try:
            tracer.write("auth_req", mac=str(event.address), hex=_hex(event.data))
            log(f"[trace] AUTH REQUEST from {event.address} ({len(event.data)}B)")
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] auth-req hook error: {e}")
        response = await orig_auth(event)
        try:
            tracer.write("auth_resp", status=response.status_code, hex=_hex(response.encode()))
            log(f"[trace] AUTH RESPONSE status={response.status_code}")
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] auth-resp hook error: {e}")
        return response

    network._process_authentication_event = process_authentication_event

    orig_register = network._register_participant

    async def register_participant(address, name, app_version, platform):
        try:
            tracer.write("join", mac=str(address), name=bytes(name).hex(),
                         app_version=app_version, platform=platform)
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] join hook error: {e}")
        return await orig_register(address, name, app_version, platform)

    network._register_participant = register_participant

    orig_disassociate = network._process_disassociation

    async def process_disassociation(address, reason=None, management_type=None):
        try:
            tracer.write("leave", mac=str(address), reason=reason,
                         management_type=management_type)
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] leave hook error: {e}")
        return await orig_disassociate(address, reason, management_type)

    network._process_disassociation = process_disassociation

    orig_data_in = network._process_data_frame
    orig_data_out = network._send_data_frame

    async def process_data_frame(frame):
        candidate = bool(
            frame.protected and
            frame.payload.startswith(b"\xAA\xAA\x03\x00\x00\x00")
        )
        try:
            n = tracer.counts.get("dataframe_in", 0)
            if n < DATAFRAME_HEX_LIMIT:
                tracer.write("dataframe_in", src=str(frame.source), dst=str(frame.target),
                             protected=bool(frame.protected), nonce=frame.nonce,
                             keyid=frame.keyid, tods=bool(frame.tods),
                             fromds=bool(frame.fromds), hex=_hex(frame.payload))
            else:
                tracer.counts["dataframe_in"] = n + 1
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] dataframe-in hook error: {e}")
        try:
            result = await orig_data_in(frame)
        except Exception as e:
            try:
                tracer.write(
                    "dataframe_rejected", src=str(frame.source),
                    protected=bool(frame.protected), candidate=candidate,
                    error=f"{type(e).__name__}: {e}",
                )
            except Exception as trace_error:                # noqa: BLE001
                log(f"[trace] dataframe-rejection hook error: {trace_error}")
            raise
        if candidate and not frame.protected:
            try:
                tracer.write("dataframe_normalized", src=str(frame.source))
            except Exception as e:                          # noqa: BLE001
                log(f"[trace] dataframe-normalized hook error: {e}")
        return result

    async def send_data_frame(data, target=None):
        try:
            n = tracer.counts.get("dataframe_out", 0)
            if n < DATAFRAME_HEX_LIMIT:
                fields = {"hex": _hex(data)}
                if target is not None:
                    fields["dst"] = str(target)
                tracer.write("dataframe_out", **fields)
            else:
                tracer.counts["dataframe_out"] = n + 1
        except Exception as e:                              # noqa: BLE001
            log(f"[trace] dataframe-out hook error: {e}")
        return await orig_data_out(data, target)

    network._process_data_frame = process_data_frame
    network._send_data_frame = send_data_frame

    tap = getattr(network, "_tap", None)
    if tap is not None:
        orig_tap_write = tap.write

        async def tap_write(data):
            try:
                tracer.write("tap_in", hex=_hex(data))
            except Exception as e:                          # noqa: BLE001
                log(f"[trace] TAP-in hook error: {e}")
            return await orig_tap_write(data)

        tap.write = tap_write

    log(f"[trace] attached to APNetwork -> {tracer.path}")
    return network
