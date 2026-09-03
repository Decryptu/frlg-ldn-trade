"""Pia host framing and the single-Switch Net/Session/RTT peer controller.

This module ends at encrypted UDP datagrams.  It does not own sockets, LDN
interfaces, beacon threads, Pokémon files, or process cleanup.
"""

from dataclasses import dataclass
import os
import time
import zlib

from . import crypto, pia_connect, reliable


PIA_HOST_VAR = 0x00C6
NET_RETRY_SECONDS = 0.5
SESSION_ACCEPT_RETRY_SECONDS = 0.25
# frlg-ldn-trade session 12 (2026-09-02): the first capture from INSIDE a real Mystery Gift host's
# session (scratchpad/mc1, frlgmg_client.py) showed that a console SHARING a Wonder Card does NOT
# accept the Pia Session join the way a trade host (j84) does: it sends NO type 2 Join Response at
# all, sends the type 5 Update Session only 2.03s after the join request, and originates RTT
# requests every 316ms from 0.25s after the join, BEFORE the session is finalized. Our host answers
# in 2ms with type 2 + type 5 and starts RTT only after finalization. These three switches make the
# host mimic the real Mystery Gift host's timing, for an A/B against the 3-second wall.
#   FRLG_ACCEPT_DELAY_MS=2030   delay the session acceptance this long after the join request
#   FRLG_NO_TYPE2=1             never send the type 2 Join Response (type 5 only, like mc1)
#   FRLG_EARLY_RTT=1            originate RTT probes from join+0.25s, before finalization
EARLY_RTT_FIRST_SECONDS = 0.25


def _env_int(name, default=0):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_flag(name):
    return os.environ.get(name, "") not in ("", "0")


def synth_rtt_request_template(host_var, random4=None):
    """A host-originated RTT request in the layout the real Mystery Gift host uses (mc1):
    type(1) 00 00 01 | 4 constant bytes | 8-byte systime | 00 00 00 | sender var (2, BE)."""
    rnd = bytes(random4 or os.urandom(4))
    return (bytes([0, 0, 0, 1]) + rnd + bytes(8) + bytes(3)
            + (host_var & 0xFFFF).to_bytes(2, "big"))
HOST_RTT_PERIOD_SECONDS = 0.315
# frlg-ldn-trade session 11: FRLG_LIVENESS_SCALE scales the RTT / Net-property keepalive cadence to
# test whether feeding the emulator's svc_51 watchdog FASTER pushes the 3s wall out. 1.0 = the real
# host's rate (default, no change). 0.5 = twice as fast. Applied to the RTT period and the Net
# property/keepalive interval only (NOT the one-shot session-accept retry). Env-gated so default
# behaviour is byte-identical.
def _liveness_scale():
    try:
        v = float(os.environ.get("FRLG_LIVENESS_SCALE", "1") or 1)
    except ValueError:
        v = 1.0
    return v if 0.1 <= v <= 4.0 else 1.0
HOST_VBLANK_SECONDS = 1.0 / 59.727
RELIABLE_BATCH_MAX = 9
PIA_COMPRESS_MIN = 62
PIA_APPLICATION_HEADER_SIZE = 0x5C


@dataclass(frozen=True)
class OutboundDatagram:
    data: bytes
    destination: str


class PiaNonceSequence:
    """Session-wide native counter, with random mode retained for diagnostics."""

    def __init__(self, native=False, initial=None):
        self.native = bool(native)
        if initial is None:
            initial = int.from_bytes(os.urandom(8), "big")
        self._next = int(initial) & 0xFFFFFFFFFFFFFFFF

    def take(self):
        if not self.native:
            return os.urandom(8)
        nonce = self._next.to_bytes(8, "big")
        self._next = (self._next + 1) & 0xFFFFFFFFFFFFFFFF
        return nonce


def decode_datagram(datagram, src_ip, pia_crypto):
    if not crypto.is_pia(datagram):
        return None, "not Pia"
    header = crypto.PiaHeader.unpack(datagram)
    plaintext = pia_crypto.decrypt(datagram, src_ip)
    if plaintext is None:
        return None, "AES-GCM authentication failed"
    pad = header.flags >> 4
    if pad:
        if len(plaintext) < pad or plaintext[-pad:] != b"\xff" * pad:
            return None, f"invalid {pad}-byte padding"
        plaintext = plaintext[:-pad]
    if header.footer:
        if len(plaintext) < header.footer:
            return None, "footer exceeds plaintext"
        plaintext = plaintext[:-header.footer]
    if header.flags & 1:
        plaintext, compressed = crypto.decompress(plaintext)
        if not compressed:
            return None, "Zstd flag set but payload did not decompress"
    messages, consumed = reliable.parse_messages(plaintext)
    if not messages or consumed != len(plaintext):
        return None, f"message tiling stopped at {consumed}/{len(plaintext)} bytes"
    return (header, messages), None


def build_messages(network, pia_crypto, messages, *, dst_var, src_var,
                   pktid=1, compress=False, auto_compress=False,
                   establishing=False, footer_var=None, nonce_source=None):
    body = b"".join(reliable.build_message(
        item[0], item[1], item[2] if len(item) > 2 else None)
        for item in messages)
    do_compress = compress or (
        auto_compress and len(body) >= PIA_COMPRESS_MIN and crypto.HAVE_ZSTD)
    if do_compress:
        body = crypto.compress(body)
    footer_size = 0
    if footer_var is not None:
        body += (footer_var & 0xFFFF).to_bytes(2, "big")
        footer_size = 2
    pad = (-len(body)) % 16
    body += b"\xff" * pad
    header = crypto.PiaHeader(
        dst=dst_var, src=src_var, pktid=pktid,
        nonce8=(nonce_source.take() if nonce_source else os.urandom(8)),
        flags=(pad << 4) | (1 if do_compress else 0) | (2 if establishing else 0),
        footer=footer_size)
    return pia_crypto.encrypt(body, network.our_ip, header)


def build_message(network, pia_crypto, proto, payload, **kwargs):
    return build_messages(network, pia_crypto, [(proto, payload)], **kwargs)


def build_net_probe(network, sequence_id=2, nonce_source=None, pia_crypto=None):
    """Build the leader's establishing Net 0x11 broadcast datagram."""
    station_ips = [network.our_ip] + [p[1] for p in network.participants]
    network_id = zlib.crc32(bytes(network.ssid)[1:16]) & 0xFFFFFFFF
    net = pia_connect.build_net_conn_request(
        sequence_id, PIA_HOST_VAR, network.our_mac, network_id, station_ips,
        max_stations=network.max_participants)
    body = crypto.compress(reliable.build_message(pia_connect.PROTO_NET, net))
    pad = (-len(body)) % 16
    plaintext = body + b"\xff" * pad
    header = crypto.PiaHeader(
        dst=0, src=PIA_HOST_VAR, pktid=0,
        nonce8=(nonce_source.take() if nonce_source else os.urandom(8)),
        flags=(pad << 4) | 0x03, footer=0)
    pia_crypto = pia_crypto or crypto.PiaCrypto(network.ssid)
    return pia_crypto.encrypt(plaintext, network.our_ip, header)


def build_net_property_update(network, app_data, sequence_id=1):
    """Build the native leader's Net 0x50 application-property payload."""
    app_data = bytes(app_data)
    network_id = zlib.crc32(bytes(network.ssid)[1:16]) & 0xFFFFFFFF
    system_len = min(PIA_APPLICATION_HEADER_SIZE, len(app_data))
    game_len = len(app_data) - system_len
    body = bytearray()
    body += (sequence_id & 0xFFFFFFFF).to_bytes(4, "big")
    body += network_id.to_bytes(8, "big")
    body += (1 + len(network.participants)).to_bytes(2, "big")
    body += network.max_participants.to_bytes(2, "big")
    body += b"\x00" * 6
    body += (network.SCENE_ID & 0xFFFF).to_bytes(2, "big")
    body += b"\x01\x01"
    body += system_len.to_bytes(4, "big") + game_len.to_bytes(4, "big")
    body += app_data
    return (bytes([0x01, pia_connect.NET_UPDATE_PROPERTY])
            + len(app_data).to_bytes(2, "big") + bytes(body))


def build_session_acceptance(network, pia_crypto, join, host_name,
                             nonce_source=None, update_pktid=1):
    """Build the native type-5 update/type-2 response acceptance pair."""
    host_constant = pia_connect.ldn_constant_id(network.our_mac)
    host_var, guest_var = join["destination_var"], join["source_var"]
    update = pia_connect.build_session_update(
        join, host_constant, host_var, network.our_ip, host_name,
        host_player_id=pia_connect.DEFAULT_PLAYER_ID)
    response = pia_connect.build_session_join_response(
        join, host_constant, host_var, os.urandom(4))
    # Native allocates the response nonce first but transmits the update first.
    response_data = build_message(
        network, pia_crypto, pia_connect.PROTO_SESSION, response,
        dst_var=guest_var, src_var=host_var, pktid=1,
        compress=False, footer_var=guest_var, nonce_source=nonce_source)
    update_data = build_message(
        network, pia_crypto, pia_connect.PROTO_SESSION, update,
        dst_var=pia_connect.SESSION_VAR, src_var=host_var, pktid=update_pktid,
        compress=True, footer_var=guest_var, nonce_source=nonce_source)
    return update_data, response_data


def build_host_rtt(network, pia_crypto, payload, guest_var, packet_id,
                   nonce_source=None):
    """Frame one host RTT message on Pia's reserved Session channel."""
    return build_message(
        network, pia_crypto, pia_connect.PROTO_RTT, payload,
        dst_var=pia_connect.SESSION_VAR, src_var=PIA_HOST_VAR,
        pktid=packet_id, compress=False, footer_var=guest_var,
        nonce_source=nonce_source)


def reliable_output_batches(outputs, limit=RELIABLE_BATCH_MAX):
    """Keep ACK/retransmit-marked messages last so flags cannot inherit."""
    if type(limit) is not int or limit < 1:
        raise ValueError("Reliable batch limit must be a positive integer")
    batches, batch = [], []
    for emission in outputs:
        if len(batch) >= limit:
            batches.append(batch)
            batch = []
        batch.append(emission)
        if emission.message_flags is not None:
            batches.append(batch)
            batch = []
    if batch:
        batches.append(batch)
    return batches


class HostPeerProtocol:
    """Own all Pia state for the one supported Switch peer."""

    def __init__(self, network, profile, host_session, active_app_data, *,
                 native_nonce_sequence=False, session_response_first=False,
                 tracer=None, log=lambda *a: None):
        self.network = network
        self.profile = profile
        self.session = host_session
        self.active_app_data = bytes(active_app_data)
        self.response_first = bool(session_response_first)
        self._liveness_scale = _liveness_scale()
        self.log = log
        self.info = getattr(log, "info", log)
        # Session-layer trace. The per-datagram detail below is on self.log, which is
        # --verbose-gated and banned on live runs, so a decoded session timeline was
        # unavailable exactly when it mattered. The emulator can close the link with no
        # game-level cause (swi 0x51, docs/joiner_protocol_notes.md), which makes THIS
        # layer the one worth recording. Writing to the capture costs no frame time.
        self.tracer = tracer
        self.nonces = PiaNonceSequence(native=native_nonce_sequence)

        self.joined = False
        self.net_acked = False
        self.net_sequence = 2
        self.next_net_send = None
        self.property_started = False
        self.next_property_send = None
        self.property_acks = 0
        self.pia_crypto = None
        self.session_join_seen = False
        self.session_join = None
        self.session_accepts = 0
        self.next_session_accept_send = None
        self.session_finalized = False
        self.guest_var = None
        self.guest_ip = None
        self.session_packet_id = 2
        self.rtt_template = None
        self.rtt_systime = 0x10000
        self.next_rtt_send = None
        self.rtt_pending = {}
        self.rtt_requests_in = 0
        self.rtt_responses_in = 0
        self.rtt_requests_out = 0
        self.rtt_responses_out = 0
        self.reliable_packet_id = 2
        self.next_protocol_tick = None
        self.reliable_messages_in = 0
        self.reliable_messages_out = 0
        self._out = []
        # frlg-ldn-trade session 11: proactive carry-forward for the HOST reliable stream, mirroring the
        # JOINER's CARRY_DEPTH (sim.py). The console silently drops ~40% of our datagrams inside its own
        # stack; the joiner survives that by repeating each reliable data frame in the next few
        # datagrams (one of the three fixes that made the joiner work), but the host only ever sent each
        # once and relied on reactive Reliable retransmit. HOST_CARRY_DEPTH>0 prepends the still-unacked
        # data frames of the last N datagrams to each new one (console dedups by seq). Default 0 = off.
        try:
            self._host_carry_depth = max(0, min(6, int(os.environ.get("HOST_CARRY_DEPTH", "0") or 0)))
        except ValueError:
            self._host_carry_depth = 0
        self._reliable_carry = []
        # session-12 real-MG-host timing switches (see the constants above)
        self.accept_delay = _env_int("FRLG_ACCEPT_DELAY_MS", 0) / 1000.0
        self.no_type2 = _env_flag("FRLG_NO_TYPE2")
        self.early_rtt = _env_flag("FRLG_EARLY_RTT")
        if self.accept_delay or self.no_type2 or self.early_rtt:
            self.info(f"[mg-host-timing] accept_delay={self.accept_delay:.3f}s "
                      f"no_type2={self.no_type2} early_rtt={self.early_rtt}")

    def drain(self):
        result, self._out = self._out, []
        return result

    def _send(self, data, destination):
        self._out.append(OutboundDatagram(bytes(data), destination))

    def on_participant_joined(self):
        if self.joined:
            return
        self.joined = True
        self.pia_crypto = crypto.PiaCrypto(self.network.ssid)
        self.next_net_send = 0.0

    def _build_net_probe(self):
        return build_net_probe(
            self.network, self.net_sequence, self.nonces, self.pia_crypto)

    def _build_property_update(self):
        return build_net_property_update(self.network, self.active_app_data)

    def _session_pair(self):
        # The type 5 rides the shared Session channel (dst 0x0001) with the RTT probes. lg86: with
        # early RTT the probes had used pktids 2..7 before the type 5 went out as pktid 1, and the
        # console ignored all four copies and left at 3.0s - it drops a session-channel packet id
        # that runs backwards. A real host numbers its type 5 after its probes (mc1: pktid 8).
        pktid = 1
        if self.early_rtt:
            pktid = self.session_packet_id
            self.session_packet_id = ((self.session_packet_id + 1) & 0xFFFF) or 1
        return build_session_acceptance(
            self.network, self.pia_crypto, self.session_join,
            self.profile.session_name, self.nonces, update_pktid=pktid)

    def _send_session_acceptance(self):
        update, response = self._session_pair()
        if self.no_type2:
            self._send(update, self.network.broadcast)
            self._unicast_session_update(update)
            return "type 5 Update Session only (broadcast + unicast; FRLG_NO_TYPE2)"
        if self.response_first:
            self._send(response, self.session_join["ip"])
            self._send(update, self.network.broadcast)
            self._unicast_session_update(update)
            return "type 2 Join Response (unicast), then type 5 Update Session (broadcast + unicast)"
        self._send(update, self.network.broadcast)
        self._unicast_session_update(update)
        self._send(response, self.session_join["ip"])
        return "type 5 Update Session (broadcast + unicast), then type 2 Join Response (unicast)"

    def _unicast_session_update(self, update):
        # The console receives only ~1 in 5 of our BROADCAST data frames, and the type 5 Update
        # Session is the one Pia handshake message still sent broadcast-only. It is what the console
        # must receive before it answers with the type 6 ACK that finalizes its Pia session; a run
        # that never finalizes (lg59) never even reaches the RFU layer. So repeat it UNICAST to each
        # joined station, exactly as the Net 0x11 probe already does (the Pia nonce depends on the
        # source, not the destination, and the console de-duplicates by packet id). Unproven against
        # the semi-random 3s quit - dead and delivered runs finalize identically - but it makes
        # finalization reliable and follows the one fix pattern that has worked on this console.
        seen = set()
        targets = [p[1] for p in self.network.participants]
        if self.session_join is not None:
            targets.append(self.session_join["ip"])
        for ip in targets:
            if ip is None or ip in seen or ip == self.network.broadcast:
                continue
            seen.add(ip)
            self._send(update, ip)

    def _apply_carry_forward(self, outputs):
        """Prepend the still-unacked data frames of the last HOST_CARRY_DEPTH datagrams (newest first),
        so a datagram the console dropped is re-offered immediately instead of only on the Reliable RTO.
        The console dedups by seq, so re-sent frames are harmless. Ctrl (pure-ack) frames are never
        carried. No-op when HOST_CARRY_DEPTH is 0."""
        depth = self._host_carry_depth
        if depth <= 0:
            return outputs
        _rel = getattr(self.session, "reliable", None)
        _link = getattr(_rel, "link", _rel)
        unacked = getattr(_link, "unacked", {}) or {}
        have = {getattr(it, "seq", None) for it in outputs}
        carried = []
        for prev in reversed(self._reliable_carry):
            for it in prev:
                seq = getattr(it, "seq", None)
                entry = unacked.get(seq)
                if seq in have or entry is None or entry[reliable._E_ACKED]:
                    continue
                have.add(seq); carried.append(it)
        # record THIS datagram's data frames for future carry (exclude pure-ack ctrl frames)
        self._reliable_carry.append([it for it in outputs
                                     if getattr(it, "seq", None) is not None
                                     and it.flagsA != reliable.FLAGSA_CTRL])
        self._reliable_carry = self._reliable_carry[-depth:]
        if not carried:
            return outputs
        # oldest-seq first, then the fresh outputs (matches sim ordering)
        carried.sort(key=lambda it: (it.seq - (min(have) if have else 0)) & 0xFFFF)
        self.carried_frames = getattr(self, "carried_frames", 0) + len(carried)
        return carried + outputs

    def _console_quiet(self, now):
        """True while the console has sent nothing for FRLG_QUIET_GATE_MS (default 250ms; 0 = off).
        2026-09-03: the console goes silent ~0.5s after accepting the card (its save); retransmits
        and carry-forward pushed into that silence pile up in the adapter as hardware-retried frames
        and either freeze the host (blocking sendto) or flood the console when it returns."""
        gate = _env_int("FRLG_QUIET_GATE_MS", 250) / 1000.0
        last = getattr(self, "_last_rx", None)
        return bool(gate) and last is not None and (now - last) > gate

    def _send_reliable(self, outputs):
        if not outputs or self.pia_crypto is None or self.guest_var is None or self.guest_ip is None:
            return
        if self._console_quiet(time.monotonic()):
            # keep only fresh (non-retransmitted) frames; no carry-forward
            outputs = [o for o in outputs if not getattr(o, "retransmitted", False)]
            if not outputs:
                return
        else:
            outputs = self._apply_carry_forward(list(outputs))
        for chunk in reliable_output_batches(outputs):
            messages = [(pia_connect.PROTO_RELIABLE, item.serialize(), item.message_flags)
                        for item in chunk]
            data = build_messages(
                self.network, self.pia_crypto, messages,
                dst_var=self.guest_var, src_var=PIA_HOST_VAR,
                pktid=self.reliable_packet_id, auto_compress=True,
                footer_var=self.guest_var, nonce_source=self.nonces)
            self._send(data, self.guest_ip)
            self.reliable_messages_out += len(chunk)
            self.log(f"[host] Reliable OUT pktid={self.reliable_packet_id} "
                     f"messages={len(chunk)} seqs={[e.seq for e in chunk]} "
                     f"flags={[e.flagsA for e in chunk]}")
            self.reliable_packet_id = self.reliable_packet_id + 1 \
                if self.reliable_packet_id < 0xFFFF else 1

    def receive(self, datagram, src_ip, now=None):
        now = time.monotonic() if now is None else now
        self._last_rx = now
        if self.pia_crypto is None:
            self.log("[host] UDP arrived before the Pia probe was initialized; ignoring it")
            return []
        decoded, error = decode_datagram(datagram, src_ip, self.pia_crypto)
        if error:
            self.log(f"[host] Pia decode failed: {error}")
            return []
        header, messages = decoded
        self.log(f"[host] Pia reply: dst=0x{header.dst:04x} src=0x{header.src:04x} "
                 f"pktid={header.pktid} protos={[m.proto for m in messages]}")
        if self.tracer is not None:
            self.tracer.write("pia_in", pktid=header.pktid, dst=header.dst, src=header.src,
                              protos=[m.proto for m in messages],
                              sizes=[len(m.payload) for m in messages])
        events = []
        for message in messages:
            if message.proto == pia_connect.PROTO_NET:
                parsed = pia_connect.parse_net(message.payload)
                if parsed and parsed[1] == pia_connect.NET_CONN_RESPONSE:
                    self.net_acked = True
                    seq = int.from_bytes(parsed[2][:4], "big") if len(parsed[2]) >= 4 else None
                    self.info(f"Switch acknowledged the leader Net 0x11 with Net 0x12 "
                              f"(sequence {seq}).")
                elif parsed and parsed[1] == pia_connect.NET_UPDATE_PROPERTY_ACK:
                    self.property_acks += 1
                    self.log(f"[host] Switch acknowledged Net 0x50 with 0x51 "
                             f"(count {self.property_acks})")
            elif message.proto == pia_connect.PROTO_SESSION:
                self._receive_session(header, message.payload, src_ip, now)
            elif message.proto == pia_connect.PROTO_RTT:
                self._receive_rtt(message.payload, src_ip, now)
            elif message.proto == pia_connect.PROTO_RELIABLE:
                if not self.session_finalized:
                    self.log("[host] Reliable arrived before Session finalization; ignoring it")
                    continue
                self.reliable_messages_in += 1
                events.extend(self.session.receive_reliable(message.payload, now * 1000.0))
        return events

    def _receive_session(self, header, payload, src_ip, now):
        parsed = pia_connect.parse_session(payload)
        if not parsed:
            return
        if parsed["type"] == pia_connect.SESSION_JOIN_REQUEST:
            join = pia_connect.parse_session_join(payload)
            if join is None:
                self.log("[host] malformed or unsupported Session join request; ignoring it")
                return
            expected = pia_connect.ldn_constant_id(self.network.our_mac)
            if (join["destination_constant_id"] != expected
                    or join["destination_var"] != PIA_HOST_VAR
                    or join["source_var"] != header.src or join["ip"] != src_ip):
                self.log("[host] Session join identity mismatch; ignoring it")
                return
            if not self.session_join_seen:
                self.session_join_seen = True
                self.info(f"Switch sent its Session join request ({len(payload)} bytes): "
                          f"var=0x{join['source_var']:04x}, "
                          f"player={join['players'][0]['name']!r}.")
            self.session_join = join
            self.guest_var, self.guest_ip = join["source_var"], src_ip
            if self.early_rtt and self.rtt_template is None:
                self.rtt_template = synth_rtt_request_template(PIA_HOST_VAR)
                self.next_rtt_send = now + EARLY_RTT_FIRST_SECONDS
                self.info(f"[mg-host-timing] originating RTT probes from join+{EARLY_RTT_FIRST_SECONDS}s")
            if not self.session_finalized and self.accept_delay > 0 and self.session_accepts == 0 \
                    and self.next_session_accept_send is None:
                self.next_session_accept_send = now + self.accept_delay
                self.info(f"[mg-host-timing] holding the Session acceptance for {self.accept_delay:.2f}s "
                          "(a real Mystery Gift host waits 2.03s, mc1)")
                return
            if not self.session_finalized and self.accept_delay > 0 \
                    and self.next_session_accept_send is not None and now < self.next_session_accept_send:
                return                          # still inside the deliberate hold
            if not self.session_finalized:
                order = self._send_session_acceptance()
                self.session_accepts += 1
                self.next_session_accept_send = now + SESSION_ACCEPT_RETRY_SECONDS
                self.info(f"Accepted the Switch Session join: sent {order} "
                          f"(attempt {self.session_accepts}).")
        elif parsed["type"] == pia_connect.SESSION_UPDATE_ACK and not self.session_finalized:
            self.session_finalized = True
            self.next_session_accept_send = None
            self.next_protocol_tick = now
            self.info("Switch finalized the Pia Session with type 6 Update Session ACK. "
                      "Session join checkpoint complete; starting RTT liveness.")

    def _receive_rtt(self, payload, src_ip, now):
        parsed = pia_connect.parse_rtt(payload)
        if parsed is None or not self.session_finalized or self.guest_var is None:
            return
        if parsed["type"] == 0:
            self.rtt_requests_in += 1
            self.rtt_template = bytes(payload[:21])
            response = pia_connect.build_rtt_response(payload)
            data = build_message(
                self.network, self.pia_crypto, pia_connect.PROTO_RTT, response,
                dst_var=pia_connect.SESSION_VAR, src_var=PIA_HOST_VAR,
                pktid=self.session_packet_id, compress=False,
                footer_var=self.guest_var, nonce_source=self.nonces)
            self.session_packet_id = ((self.session_packet_id + 1) & 0xFFFF) or 1
            self._send(data, src_ip)
            self.rtt_responses_out += 1
            if self.rtt_responses_out == 1:
                self.info("Stage 2.3 RTT liveness active: answered the Switch's first "
                          "type 0 request with type 1.")
            if self.next_rtt_send is None:
                self.next_rtt_send = 0.0
        elif parsed["type"] == 1:
            self.rtt_responses_in += 1
            systime = int.from_bytes(parsed["systime"], "little")
            sent_at = self.rtt_pending.pop(systime, None)
            if sent_at is not None:
                self.session.note_rtt(max(0.0, (now - sent_at) * 1000.0))

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if self.joined and not self.net_acked and now >= self.next_net_send:
            probe = self._build_net_probe()
            self._send(probe, self.network.broadcast)
            # The console receives only ~1 in 5 of our BROADCAST data frames (2026-09-02, lg42-lg49:
            # it answered the 2nd, 4th, 5th, 5th and 6th 0x11), which delays its Pia session join by
            # up to 2.7s, while every UNICAST frame to it is acked. So repeat the same datagram
            # unicast to each joined station; the Pia nonce depends on the source, not the
            # destination, and the console de-duplicates by packet id.
            for participant in self.network.participants:
                self._send(probe, participant[1])
            self.next_net_send = now + NET_RETRY_SECONDS * self._liveness_scale
        if (self.session_join is not None and not self.session_finalized
                and self.next_session_accept_send is not None
                and now >= self.next_session_accept_send):
            order = self._send_session_acceptance()
            self.session_accepts += 1
            self.next_session_accept_send = now + SESSION_ACCEPT_RETRY_SECONDS
            self.log(f"[host] Session acceptance retry #{self.session_accepts}: {order}")
        if ((self.session_finalized or self.early_rtt) and self.rtt_template is not None
                and self.guest_var is not None and self.next_rtt_send is not None
                and now >= self.next_rtt_send):
            self.rtt_systime = (self.rtt_systime + 1) & 0xFFFFFFFFFFFFFFFF
            request = pia_connect.build_rtt_request(self.rtt_template, self.rtt_systime)
            data = build_message(
                self.network, self.pia_crypto, pia_connect.PROTO_RTT, request,
                dst_var=pia_connect.SESSION_VAR, src_var=PIA_HOST_VAR,
                pktid=self.session_packet_id, compress=False,
                footer_var=self.guest_var, nonce_source=self.nonces)
            self.session_packet_id = ((self.session_packet_id + 1) & 0xFFFF) or 1
            self._send(data, self.guest_ip)
            self.rtt_pending[self.rtt_systime] = now
            self.rtt_requests_out += 1
            if self.rtt_requests_out == 1:
                self.info("Stage 2.3 RTT liveness active: originated the first host type 0 probe.")
            self.next_rtt_send = now + HOST_RTT_PERIOD_SECONDS * self._liveness_scale
        if (self.session_finalized and self.next_protocol_tick is not None
                and now >= self.next_protocol_tick):
            self._send_reliable(self.session.tick(now * 1000.0))
            self.next_protocol_tick = now + HOST_VBLANK_SECONDS
        if self.session.trade.established and not self.property_started:
            self.property_started = True
            self.next_property_send = 0.0
            self.network.set_application_data(self.active_app_data)
            self.info("Player info established; advertising active trade-room status.")
        if (self.property_started and self.next_property_send is not None
                and now >= self.next_property_send):
            payload = self._build_property_update()
            data = build_message(
                self.network, self.pia_crypto, pia_connect.PROTO_NET, payload,
                dst_var=0, src_var=PIA_HOST_VAR, pktid=0, compress=True,
                establishing=True, nonce_source=self.nonces)
            self._send(data, self.guest_ip)
            self.next_property_send = now + NET_RETRY_SECONDS * self._liveness_scale
        return self.drain()

    def next_deadline(self, now, default):
        deadlines = []
        if self.joined and not self.net_acked and self.next_net_send is not None:
            deadlines.append(self.next_net_send)
        if self.session_join is not None and not self.session_finalized \
                and self.next_session_accept_send is not None:
            deadlines.append(self.next_session_accept_send)
        if (self.session_finalized or self.early_rtt) and self.next_rtt_send is not None:
            deadlines.append(self.next_rtt_send)
        if self.session_finalized and self.next_protocol_tick is not None:
            deadlines.append(self.next_protocol_tick)
        if self.property_started and self.next_property_send is not None:
            deadlines.append(self.next_property_send)
        return min([default] + [max(0.0, deadline - now) for deadline in deadlines])
