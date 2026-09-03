"""The per-VBlank orchestrator: transport <-> crypto <-> Pia <-> trade engine. No trade traffic until the ConnectionManager
is connected; station var-ids are learned from the wire (header = [dst_var][src_var], footer = dest var).
"""

import json
import os
import time

from . import crypto as cryptomod, reliable, gbaframe, rfu, pia_connect, ni, linkplayer
from .reliable import _E_ACKED as _E_ACKED_IDX

RELIABLE_SEQ_START = 0xFFF0

# The reliable layer runs on a millisecond clock; 59.727 Hz VBlank.
MS_PER_VBLANK = 1000.0 / 59.727

# The reference host batches up to 9 Reliable messages per datagram.
RELIABLE_BATCH_MAX = 9
# The console MAC-acks but drops ~40% of our datagrams inside its own stack when another of ours lands within ~20ms;
# one merged datagram per ~33ms window is dropped <5% of the time.
PACE_MIN_GAP_MS = 34
# A datagram sent within ~2ms after a console frame is dropped ~40% of the time; 20ms+ after, ~6%.
REPLY_HOLDOFF_MS = 6
# Every reliable data frame is repeated in the next CARRY_DEPTH datagrams: the console drops ~40% of our datagrams inside
# its stack regardless of timing, and Pia delivers in order, so one hole stalls the game stream for an RTO.
CARRY_DEPTH = 4

# LIVE cap on new standby frames per count: the reference child sends each ~3-4x then stops; emitting every VBlank
# keeps the host in the same round forever. Offline keeps the unbounded cadence its MockHost depends on.
BARRIER_EMITS = 6

RTX_GAP_LIMIT = 1
RTX_GAP_LIMIT_NI = 2
# RTO_BACKOFF stays 1.0 (off): backoff blew recovery latency up to seconds.
MAX_INFLIGHT = 24         # window/RTO bounds throughput; 24 reaches the console's native 60/s poll rate
RTT_JITTER_K = 1.0
DUP_NACK_THRESHOLD = 1
RTO_CEIL_MS = 120
RTO_BACKOFF = 1.0
RECV_NI_REACK_EVERY = 20
# DO NOT RAISE THESE: child registration must finish inside the parent's establishConnection window of 240/360 frames
# [link_rfu_2.c:340-345, 522-527], and the host's librfu NI receiver is intolerant of extra sub-frames - faster re-sends dropped the link.
HOST_ACK_REPEAT_BEFORE_RESEND = 10
NULL_REEMIT_EVERY = 12
NI_ACK_WAIT_RESEND = 12
NULL_REEMIT_MAX = 30
RTO_BOOTSTRAP_MS = 200    # RTO while sampleless, so the connect J/C retransmit until the host's reliable side engages (~2s in); NOT a floor
# K supersedes rather than queues (only the newest un-acked host ts is pending, one per VBlank) and is NOT window-gated:
# the parent blocks its whole post-finalize sequence on the DRAC ack it carries [link_rfu_2.c:867]. k_seq is the running
# count of host 'T' frames received; under-reporting it wedges the trade-room entry.
K_INFLIGHT_MAX = 4
# The per-VBlank child slot is a liveness obligation (FRLG's MC_TimerCount = 32 ~ 534ms, linkRecovery disabled
# [link_rfu_2.c:129,136]); the window may DELAY it, never silence it.
CHILD_SILENCE_LIMIT = 20   # VBlanks (~335ms)

# Ceiling on the liveness override: once the peer is gone forced slots go unacked forever, so the window resumes as a hard cap.
SILENCE_OVERRIDE_CEIL = 2
# One child slot per host poll is librfu's native cadence [MscCallback_Child]; surplus idle slots delay the K-ack the
# stop-and-wait parent is blocked on.
SLOT_CREDIT_MAX = 2
# MUST STAY 1: the parent keeps exactly one child slot per poll and treats any tag not +1 mod 8 as a receive error, fatal
# on the fifth [link_rfu_2.c:876-892]; a second slot per poll is a guaranteed dropped tag.
WALK_SLOTS_PER_POLL = 1
ACK_PERIOD = 2             # delayed-ack interval in VBlanks (~33ms); the ack piggybacks on data datagrams and goes standalone only when owed
COMPRESS_MIN = 62          # zstd-compress iff the body is >= 62 bytes: the real host's exact threshold (largest raw 61, smallest compressed 62)

# Per-new-frame 'T' counter, reused on a Pia retransmit; the host gates on monotonicity, so seed nonzero.
TS_SEED = 0x0000362E


class Sim:
    def __init__(self, transport, pia_crypto, engine, our_ip, host_ip, *, conn=None,
                 our_var=0xc493, compress=False, header_flags=0x50, capture_path=None,
                 linkstate=None, connect_id=None, log=lambda *a: None,
                 pace_ms=0, pace_clock=None):
        self.t = transport
        self.pace_ms = pace_ms
        self._pace_clock = pace_clock or (lambda: time.monotonic() * 1000.0)
        self._pace_pending = []
        self._pace_last_ms = None
        self._last_rx_ms = None
        self.reply_holdoff_ms = REPLY_HOLDOFF_MS if pace_ms else 0
        self.paced_merges = 0
        self._carry = []
        self.carried = 0
        self.crypto = pia_crypto
        self.engine = engine
        # Held keys (0xBE00) go out on an idle VBlank ONLY while engine.in_seat_phase, mirroring SendKeysToRfu, which runs only
        # while gRfu.callback == SendKeysToRfu [link_rfu_2.c:1069-1089] - cleared on the warp out of the cable seat
        # [cable_club.c:918]. Held keys never override a real slot.
        self.linkstate = linkstate
        self.conn = conn
        if conn is not None and hasattr(engine, "barrier"):
            engine.barrier.max_emits = BARRIER_EMITS
        # LIVE: gate READY_TO_TRADE on the full BufferTradeParties (the offline MockHost has no mail/ribbons).
        if conn is not None and hasattr(engine, "_live"):
            engine._live = True
        self.our_ip = our_ip
        self.host_ip = host_ip
        self.broadcast = host_ip.rsplit(".", 1)[0] + ".255"
        self.compress = compress
        self.header_flags = header_flags
        self.log = log
        self.info = getattr(log, "info", log)

        self.slot = rfu.SlotBuilder()
        self.ts = TS_SEED
        self._k_seq = 0
        self._acked_ts = set()
        self._pending_k_ts = None
        self._k_seqs = set()
        self.host_t_in = 0
        self._last_t_tick = 0
        self.silence_forced = 0
        self.max_silence = 0
        self.t_out = 0
        self.k_out = 0
        self._ni = None
        self._ni_done = False
        self._ni_built = False
        # librfu's NI transfer is stop-and-wait: one sub-frame in flight, advance on the host's ack; sending them faster puts
        # out-of-sequence sub-frames into the host's receiver and it disconnects.
        self._ni_awaiting = None
        self._ni_wait_ticks = 0
        self._ni_recv = ni.NIReceiver()
        # One current recv-NI ack, re-emitted per DISTINCT host sub-frame; a per-frame queue spammed hundreds of duplicates under loss.
        self._cur_ni_ack = None
        # At most one reliable recv-NI ack in flight; queuing one per poll backlogs stale acks and deadlocks the handshake.
        self._ni_ack_seq = None
        self._ni_ack_bytes = None
        self._emitted_ni_ack = None
        self._host_uni_seen = False
        # Stop acking at the host's NI NULL: re-emitting the stale NI_END ack through the ~2.4s join-textbox gap causes the
        # in-game Communication error.
        self._host_ni_null_seen = False
        self._host_ni_ack_state = None
        self._host_ni_repeat = 0
        self._host_ni_ack_key = None
        self._host_ni_ack_repeat = 0
        self._host_ni_resend = None
        self._null_reemits = 0
        self._null_ticks = 0
        self._ni_status_logged = False
        self.ni_rejected = False
        self.host_disconnected = False
        self.out_seq = RELIABLE_SEQ_START
        # Pia packet ids are per-channel counters keyed by header dst var (dst=0 establishing, 0x0001 session/RTT, host-var
        # reliable); a single global counter skips reliable pktids.
        self._pktid_by_dst = {}
        self.last_in_seq = 0
        self._recv_hi = None
        self.rel = reliable.ReliableLink(start=RELIABLE_SEQ_START, max_inflight=MAX_INFLIGHT,
                                         rtt_jitter_k=RTT_JITTER_K, dup_nack_threshold=DUP_NACK_THRESHOLD,
                                         rto_ceil_ms=RTO_CEIL_MS, rto_backoff=RTO_BACKOFF,
                                         rto_bootstrap_ms=RTO_BOOTSTRAP_MS)
        self._rel_opened = False
        self._ack_owed = False
        self._last_ack_tick = -100
        self._tick = 0
        self._connect_id = bytes(connect_id) if connect_id else None
        self._gba_conn_sent = False
        self._gba_accepted = False
        self._slot_credit = 0
        self._last_seat_emit = -100
        self._seen_in = set()
        self.rx_count = self.tx_count = 0
        self.rx_fail = 0
        self.rx_protos = {}
        self._dbg = None

        # our var id is self-chosen; the host's is learned from incoming headers (its first packet has dst=0).
        self.our_var = our_var.to_bytes(2, "big")
        self.host_var = reliable.STATION_HOST.to_bytes(2, "big")
        self._learned = False
        if conn is not None:
            conn.our_var = int.from_bytes(self.our_var, "big")

        self._cap = open(capture_path, "w", buffering=1) if capture_path else None
        if self._cap:
            self._cap.write(json.dumps({"rec": "meta", "event": "session", "kind": "sim",
                                        "ip": our_ip, "host": host_ip,
                                        "ssid_hex": pia_crypto.ssid.hex(),
                                        "broadcast": self.broadcast}) + "\n")
        self._t0 = None

    @property
    def connected(self):
        return self.conn is None or self.conn.connected

    @property
    def _now_ms(self):
        return self._tick * MS_PER_VBLANK

    def _capture(self, direction, datagram, src, dst):
        if not self._cap:
            return
        if self._t0 is None:
            self._t0 = time.monotonic()
        self._cap.write(json.dumps({
            "rec": "pkt", "seq": self.rx_count + self.tx_count, "t": time.monotonic() - self._t0,
            "dir": direction, "proto": 17, "src": src, "dst": dst,
            "len": len(datagram), "hex": datagram.hex(),
        }) + "\n")

    def process_datagram(self, datagram, src_ip):
        if not cryptomod.is_pia(datagram):
            return False
        self._capture("in", datagram, f"{src_ip}:12345", f"{self.our_ip}:12345")
        hdr = cryptomod.PiaHeader.unpack(datagram)
        if not self._learned and hdr.src != 0:
            self.host_var = hdr.src.to_bytes(2, "big")
            self._learned = True
            if self.conn:
                self.conn.learn_ids(self.our_var, self.host_var)
        pt = self.crypto.decrypt(datagram, src_ip)
        if pt is None:
            self.rx_fail += 1
            if self.rx_fail <= 5:
                self.log(f"[sim] RX decrypt FAILED from {src_ip} hdr.src=0x{hdr.src:04x} "
                         f"(SSID/key mismatch?) - host msg never reaches the handshake")
            return False
        app, _ = cryptomod.decompress(pt)
        msgs, _, _ = reliable.parse_app(app)
        for m in msgs:
            self.rx_protos[m.proto] = self.rx_protos.get(m.proto, 0) + 1
        if self.rx_count < 8:
            self.log(f"[sim] RX ok from {src_ip}: protos={[m.proto for m in msgs]} "
                     f"(1=Net 3=RTT 10=Reliable 13=Session)")
        for m in msgs:
            if m.proto == reliable.PROTO_RELIABLE:
                rl = reliable.parse_reliable(m.payload)
                if rl is None:
                    continue
                if self.conn is None:
                    self._note_in_seq(rl.seq)
                    if rl.flagsA & 0x01 and rl.payload[:1] == b"\x57":
                        self._on_gba_in(rl.payload)
                elif rl.flagsA & 0x01:                # live: deliver each unique frame as it lands (the emulator is order-tolerant), never stall the RFU exchange on a gap
                    self._ack_owed = True
                    if rl.seq not in self._seen_in:
                        self._note_in_seq(rl.seq)
                        if rl.payload[:1] == b"\x57":
                            self._on_gba_in(rl.payload)
                    self.rel.note_received(rl.seq)
                else:
                    ackid, mask = reliable.parse_bulk_ack(rl.payload)
                    self.rel.on_ack(ackid, mask, now_ms=self._now_ms)
            elif self.conn:
                self.conn.on_message(m.proto, m.payload, tick=self._tick)
        self.rx_count += 1
        return True

    def _on_gba_in(self, payload):
        rec = gbaframe.parse_in(payload)
        if rec is None:
            return
        typ = rec.get("type")
        if typ == "A" and not self._gba_accepted:
            self._gba_accepted = True
            self.log(f"[sim] host ACCEPTED emulator connect ('A' 0x41): {payload[:10].hex()} "
                     f"-> our slot is seated; RFU link up, starting the NI handshake")
            self.info("Host accepted the link.")
            return
        if typ == gbaframe.TYPE_D and not self.host_disconnected:
            self.host_disconnected = True
            self.log("[sim] host emulator DISCONNECT ('D' 0x44) - RFU link closing")
            return
        if typ != "T":
            return
        ts = rec.get("ts")
        self.host_t_in += 1
        if ts is not None and ts not in self._acked_ts:
            self._acked_ts.add(ts)
            self._k_seq += 1
            self._pending_k_ts = ts
            if len(self._acked_ts) > 8192:
                self._acked_ts = set(list(self._acked_ts)[-2048:])
        ni_rec = rec.get("ni")
        if ni_rec is not None:
            ack_slot = self._ni_recv.on_host_ni(ni_rec)
            if ack_slot is not None:
                if ack_slot == self._cur_ni_ack:
                    # The host repeating a sub-frame means it has not seen our ack; re-ack on a slow cadence (every poll spams duplicates).
                    self._host_ni_repeat += 1
                    if self._host_ni_repeat % RECV_NI_REACK_EVERY == 0:
                        self._ni_ack_bytes = None
                        if self._host_ni_repeat == RECV_NI_REACK_EVERY:
                            self.info("Host is repeating its NI sub-frame; re-acking it.")
                else:
                    self._host_ni_repeat = 0
                self._cur_ni_ack = ack_slot
            if ni_rec.get("ack") == 1:
                # A repeated host ack of OUR send-NI names the sub-frame it is waiting for: the next one we emitted was lost.
                key = (ni_rec.get("state"), ni_rec.get("n"), ni_rec.get("phase"))
                self._host_ni_ack_state = ni_rec.get("state")
                if key == self._host_ni_ack_key:
                    self._host_ni_ack_repeat += 1
                    if (self._host_ni_ack_repeat >= HOST_ACK_REPEAT_BEFORE_RESEND
                            and self._ni is not None and self._host_ni_resend is None):
                        self._host_ni_resend = self._ni.resend_after(*key)
                else:
                    self._host_ni_ack_key = key
                    self._host_ni_ack_repeat = 0
                    self._host_ni_resend = None
                    self._null_reemits = 0
                    self._null_ticks = 0
            if ni_rec.get("state") == rfu.LCOM_NULL and ni_rec.get("ack") == 0:
                self._host_ni_null_seen = True
            st = self._ni_recv.status
            if st is not None and not self._ni_status_logged:
                self._ni_status_logged = True
                if st == ni.RFU_STATUS_JOIN_GROUP_OK:
                    self.log(f"[sim] host NI join status = JOIN_GROUP_OK ({st})")
                else:
                    self.ni_rejected = True
                    self.log(f"[sim] WARNING: host NI join status = {st} (NOT JOIN_GROUP_OK=5) -> host "
                             f"REJECTED our join; the trade cannot proceed")
        # The host's first UNI slot ends its NI; sending a UNI slot before the host itself is in UNI faults its link manager.
        if rec.get("llsf_state") == 4:
            self._host_uni_seen = True
        _walk = self.linkstate is not None and self.linkstate.walking
        _per_poll = WALK_SLOTS_PER_POLL if _walk else 1
        self._slot_credit = min(self._slot_credit + _per_poll,
                                SLOT_CREDIT_MAX * _per_poll)
        self.engine.feed_in_frame(rec)

    def _note_in_seq(self, seq):
        if seq in self._seen_in:
            return
        self._seen_in.add(seq)
        if len(self._seen_in) > 4096:
            self._seen_in = set(list(self._seen_in)[-1024:])
        if ((seq - self.last_in_seq) & 0xFFFF) < 0x8000:
            self.last_in_seq = seq

    def _next_pktid(self, dv):
        pktid = self._pktid_by_dst.get(dv, 1)
        self._pktid_by_dst[dv] = pktid + 1 if pktid < 0xFFFF else 1
        return pktid

    def flush_paced(self):
        """Called between ticks too, so PACE_MIN_GAP_MS and the reply hold-off are honoured at sub-VBlank resolution."""
        if not self._pace_pending:
            return None
        now = self._pace_clock()
        if self._pace_last_ms is not None and now - self._pace_last_ms < self.pace_ms:
            return None
        if self._last_rx_ms is not None and now - self._last_rx_ms < self.reply_holdoff_ms:
            return None
        key, kw, msgs = self._pace_pending.pop(0)
        self._pace_last_ms = now
        return self._send_messages(msgs, _paced=True, **kw)

    def _send_messages(self, messages, *, dst_var=None, src_var=None, compress=False,
                       footer=True, establishing=False, unicast=True, pktid=None, footer_var=None,
                       _paced=False):
        """Frame N messages into ONE datagram: [messages, optionally zstd as a whole][2-byte recipient var-id footer,
        uncompressed][0xFF pad to a multiple of 16]; header byte5 = (pad << 4) | (1 if zstd) | (2 if establishing). One pktid
        per datagram, not per message.
        """
        if not messages:
            return None
        if self.pace_ms and not _paced:
            key = (dst_var, src_var, compress, footer, establishing, unicast, pktid, footer_var)
            for k, kw, msgs in self._pace_pending:
                if k == key and len(msgs) + len(messages) <= RELIABLE_BATCH_MAX:
                    msgs.extend(messages); self.paced_merges += len(messages)
                    break
            else:
                self._pace_pending.append((key, dict(dst_var=dst_var, src_var=src_var, compress=compress,
                                                     footer=footer, establishing=establishing, unicast=unicast,
                                                     pktid=pktid, footer_var=footer_var), list(messages)))
            self.flush_paced()
            return None
        dv = dst_var if dst_var is not None else int.from_bytes(self.host_var, "big")
        sv = src_var if src_var is not None else int.from_bytes(self.our_var, "big")
        body = b"".join(reliable.build_message(m[0], m[1], m[2] if len(m) > 2 else None)
                        for m in messages)
        do_zstd = compress or (len(body) >= COMPRESS_MIN and cryptomod.HAVE_ZSTD)
        if do_zstd:
            body = cryptomod.compress(body)
        fsize = 0
        if footer:
            fv = footer_var if footer_var is not None else dv
            body += fv.to_bytes(2, "big")
            fsize = 2
        pad = (-len(body)) % 16
        body += b"\xff" * pad
        flags = (1 if do_zstd else 0) | (2 if establishing else 0)
        if pktid is None:
            pktid = self._next_pktid(dv)
        hdr = cryptomod.PiaHeader(dst=dv, src=sv, pktid=pktid, nonce8=os.urandom(8),
                                  flags=(pad << 4) | flags, footer=fsize)
        dg = self.crypto.encrypt(body, self.our_ip, hdr)
        dst = self.host_ip if unicast else self.broadcast
        self.t.send(dg, dst)
        self._capture("out", dg, f"{self.our_ip}:12345", f"{dst}:12345")
        self.tx_count += 1
        return dg

    def _send(self, proto, payload, *, dst_var=None, src_var=None, compress=False,
              footer=True, establishing=False, unicast=True, pktid=None, footer_var=None):
        return self._send_messages([(proto, payload)], dst_var=dst_var, src_var=src_var,
                                   compress=compress, footer=footer, establishing=establishing,
                                   unicast=unicast, pktid=pktid, footer_var=footer_var)

    def _tx_reliable(self, seq, flagsA, inner):
        """Pure-ack frames carry no seq of their own and ride the window base (the reference reuses 0xFFF0)."""
        s = RELIABLE_SEQ_START if seq is None else seq
        rel = reliable.build_reliable(s, self.rel.send_low(), inner, flagsA=flagsA)
        self._send(reliable.PROTO_RELIABLE, rel,
                   dst_var=int.from_bytes(self.host_var, "big"),
                   src_var=int.from_bytes(self.our_var, "big"),
                   compress=False, footer=True, establishing=False)

    def _tx_reliable_batch(self, batch):
        if not batch:
            return
        # carry-forward: prepend the still-unacked data frames of the previous datagrams, newest first; ctrl-acks are never carried
        if CARRY_DEPTH:
            have = {s for s, _, _ in batch if s is not None}
            carried = []
            for prev in reversed(self._carry):
                for seq, flagsA, inner in prev:
                    e = self.rel.unacked.get(seq)
                    if seq in have or e is None or e[_E_ACKED_IDX]:
                        continue
                    carried.append((seq, flagsA, inner)); have.add(seq)
            room = RELIABLE_BATCH_MAX - len(batch)
            carried = carried[:max(0, room)]
            self.carried += len(carried)
            self._carry.append([(s, f, i) for s, f, i in batch if s is not None and f != reliable.FLAGSA_CTRL])
            batch = sorted(carried, key=lambda x: x[0]) + batch
            self._carry = self._carry[-CARRY_DEPTH:]
        msgs = []
        for seq, flagsA, inner in batch:
            s = RELIABLE_SEQ_START if seq is None else seq
            rel = reliable.build_reliable(s, self.rel.send_low(), inner, flagsA=flagsA)
            # Pia message flag 0x40 on every pure ack: both native parties set it, and without it the host never fast-retransmitted
            # a hole. The ctrl-ack is LAST so its 0x40 never leaks into a later message via msgflags inheritance.
            mf = 0x40 if flagsA == reliable.FLAGSA_CTRL else None
            msgs.append((reliable.PROTO_RELIABLE, rel, mf))
        dv = int.from_bytes(self.host_var, "big")
        sv = int.from_bytes(self.our_var, "big")
        for i in range(0, len(msgs), RELIABLE_BATCH_MAX):
            self._send_messages(msgs[i:i + RELIABLE_BATCH_MAX], dst_var=dv, src_var=sv,
                                compress=False, footer=True, establishing=False)

    def _drive_reliable(self):
        tick = self._tick
        now_ms = self._now_ms
        if not self._rel_opened:
            seq = self.rel.queue(reliable.METADATA_FRAME, reliable.FLAGSA_INIT, now_ms)
            self._tx_reliable(seq, reliable.FLAGSA_INIT, reliable.METADATA_FRAME)
            self._rel_opened = True
            return
        if self._connect_id is not None and not self._gba_conn_sent:
            frame = gbaframe.build_connect(self._connect_id)
            seq = self.rel.queue(frame, reliable.FLAGSA_GBA, now_ms)
            self._tx_reliable(seq, reliable.FLAGSA_GBA, frame)
            self._gba_conn_sent = True
            return
        # One datagram per VBlank; wire order (the reference's KT/KTA): retransmits, K, T, ctrl-ack last.
        batch = []
        # Block/trade phase: gap-targeted retransmit (the host buffers out-of-order); NI/seat phase: a longer tail so the few
        # critical frames get through.
        in_block_phase = self._gba_accepted and not getattr(self.engine, "in_seat_phase", True)
        rtx_limit = RTX_GAP_LIMIT if in_block_phase else RTX_GAP_LIMIT_NI
        for seq, flagsA, inner in self.rel.due_retransmits(now_ms, limit=rtx_limit)[:RELIABLE_BATCH_MAX]:
            batch.append((seq, flagsA, inner))
        self._k_seqs.intersection_update(self.rel.unacked)
        queued = 0
        k_frames = []
        if (self._pending_k_ts is not None
                and len(self._k_seqs) < K_INFLIGHT_MAX):
            kf = gbaframe.build_k(self._k_seq, 1, self._pending_k_ts)
            seq = self.rel.queue(kf, reliable.FLAGSA_GBA, now_ms)
            self._k_seqs.add(seq)
            k_frames.append((seq, reliable.FLAGSA_GBA, kf))
            self._pending_k_ts = None
            self.k_out += 1
            queued = 1
        t_frames = []
        if self._gba_accepted:
            # Gate on outstanding(), not inflight(); the window yields to the liveness bound after CHILD_SILENCE_LIMIT quiet VBlanks.
            _out = self.rel.outstanding()
            _quiet = self._tick - self._last_t_tick >= CHILD_SILENCE_LIMIT
            _starved = _quiet and _out < self.rel.max_inflight * SILENCE_OVERRIDE_CEIL
            # NOTHING is exempt from the credit pacer, the seat walk included: the parent samples one child slot per poll and
            # hard-errors after >4 lost tag increments [link_rfu_2.c:884-888].
            _gated = ((_out >= self.rel.max_inflight and not _starved)
                      or (self._slot_credit <= 0 and not _quiet))
            if _starved and _out >= self.rel.max_inflight:
                self.silence_forced += 1
            inner = None
            if not _gated:
                inner = self._gba_frame()
                if inner is not None:
                    if self._slot_credit > 0:
                        self._slot_credit -= 1
                    self._last_seat_emit = tick
                    seq = self.rel.queue(inner, reliable.FLAGSA_GBA, now_ms)
                    t_frames.append((seq, reliable.FLAGSA_GBA, inner))
                    self.t_out += 1
                    self.max_silence = max(self.max_silence, self._tick - self._last_t_tick)
                    self._last_t_tick = self._tick
                    if self._emitted_ni_ack is not None:
                        self._ni_ack_seq = seq
                        self._ni_ack_bytes = self._emitted_ni_ack
            else:
                # window-gated: an in-flight block send must still advance on the host's reflection
                self.engine.poll_send_done()
        batch.extend(k_frames)
        batch.extend(t_frames)
        if self._gba_accepted and self._dbg is not None:
            _snd = getattr(self.engine, "sender", None)
            self._dbg.append({"tick": tick, "credits": 0, "kacks": queued,
                              "gba_emitted": len(t_frames), "inflight": self.rel.inflight(),
                              "sender": (_snd.state, _snd.index, _snd.count) if _snd else None})
        # Bulk-ack LAST, rate-limited to ACK_PERIOD and only when owed: a standalone pure-ack every VBlank flooded the half-duplex link.
        due = (tick - self._last_ack_tick) >= ACK_PERIOD
        if due and (self._ack_owed or self.rel.recv_ooo):
            batch.append((None, reliable.FLAGSA_CTRL, self.rel.ack_payload()))
            self._ack_owed = False
            self._last_ack_tick = tick
        self._tx_reliable_batch(batch)

    def _ensure_ni(self):
        if self._ni_built:
            return
        self._ni_built = True
        lp = getattr(self.engine, "lp", None) or linkplayer.LinkPlayer()
        # ACTIVITY_TRADE for the trade joiner, ACTIVITY_WONDER_CARD for the Mystery Gift client [SetHostRfuGameData, union_room.c:2255].
        src = ni.build_game_data(version_low=lp.version & 0xFF,
                                 trainer_id=lp.trainer_id & 0xFFFF, ot_name=lp.name,
                                 activity=getattr(self.engine, "ni_activity", ni.ACTIVITY_TRADE),
                                 started=getattr(self.engine, "ni_started", True))
        self._ni = ni.NISender(src)

    def _gba_frame(self):
        """One slot per call: the NI handshake (after 'A', before UNI), then UNI slots. Held keys + sit() fire only while
        engine.established AND in_seat_phase; earlier idle VBlanks are bare all-zero slots so a tagged 0xBE00 never races
        the NI/block handshake.
        """
        self._emitted_ni_ack = None
        # Do not go UNI until our send-NI is finished AND the host has entered UNI.
        if self.conn is not None and self._gba_accepted and not self._ni_done:
            self._ensure_ni()
            if not self._ni.done:
                if self._ni_awaiting is None or self._host_ni_ack_key == self._ni_awaiting:
                    slot = self._ni.next_slot()
                    if slot is not None:
                        self._ni_awaiting = self._ni.emitted[-1][:3]
                        self._ni_wait_ticks = 0
                        return self._wrap_t(slot)
                else:
                    self._ni_wait_ticks += 1
                    if self._ni_wait_ticks % NI_ACK_WAIT_RESEND == 0:
                        return self._wrap_t(self._ni.emitted[-1][3])
            # The host is blocked on its current sub-frame's ack; this outranks our own re-sends (a branch below returns early).
            if self._cur_ni_ack is not None and self._ni_ack_bytes != self._cur_ni_ack:
                self._emitted_ni_ack = self._cur_ni_ack
                return self._wrap_t(self._cur_ni_ack)
            # The host re-acking one of our sub-frames means the next never reached it; re-send it, paced (see the constants).
            if (self._ni.done and not self._host_uni_seen
                    and self._host_ni_resend is not None
                    and self._null_reemits < NULL_REEMIT_MAX):
                self._null_ticks += 1
                if self._null_ticks % NULL_REEMIT_EVERY == 0:
                    self._null_reemits += 1
                    if self._null_reemits == 1:
                        self.info("Host is still awaiting one of our NI sub-frames; re-sending it.")
                    return self._wrap_t(self._host_ni_resend)
            if not self._host_uni_seen:
                # Re-emit the current recv-NI ack rather than go silent past MC_Timer (a Pia retransmit keeps its seq and never
                # reaches librfu), but not after the host's NULL.
                if (self._cur_ni_ack is not None and not self._host_ni_null_seen
                        and self._tick - self._last_t_tick >= CHILD_SILENCE_LIMIT):
                    self.silence_forced += 1
                    self._emitted_ni_ack = self._cur_ni_ack
                    return self._wrap_t(self._cur_ni_ack)
                return None
            self._ni_done = True
            self.log("[sim] host entered UNI -> NI handshake complete, switching to UNI trade slots")
            self.info("Join handshake complete.")

        # engine.tick() returns None on a barrier frame with nothing to emit; treat it as idle.
        words = self.engine.tick() or [0] * 7
        if (self.linkstate is not None and (words[0] & 0xFFFF) == 0
                and getattr(self.engine, "established", False)
                and getattr(self.engine, "host_in_seat", False)
                and getattr(self.engine, "held_keys_active",
                            getattr(self.engine, "in_seat_phase", True))):
            words = self.linkstate.tick()
        cmd14 = self.slot.build(words)
        return self._wrap_t(rfu.uni_slot(cmd14))

    def _wrap_t(self, slot):
        frame = gbaframe.wrap_t(slot, self.ts)
        self.ts = (self.ts + 1) & 0xFFFFFFFF
        return frame

    def _reliable_trade_payload(self):
        """Offline (conn=None): the bare UNI/idle 'T' the offline tests expect; the K-ack/NI layers are live-only."""
        frame = self._gba_frame()
        rel = reliable.build_reliable(self.out_seq, self.last_in_seq, frame)
        self.out_seq = (self.out_seq + 1) & 0xFFFF
        return rel

    def poll_rx(self):
        for datagram, src_ip in self.t.recv():
            if self.pace_ms:
                self._last_rx_ms = self._pace_clock()
            self.process_datagram(datagram, src_ip)

    def tick(self):
        self._tick += 1
        for datagram, src_ip in self.t.recv():
            if self.pace_ms:
                self._last_rx_ms = self._pace_clock()
            self.process_datagram(datagram, src_ip)
        if self.conn is not None and getattr(self.conn, "rtt_samples", None):
            for rtt_vblanks in self.conn.rtt_samples:
                self.rel.add_rtt_sample(rtt_vblanks * MS_PER_VBLANK)
            self.conn.rtt_samples = []
        if self.conn:
            if hasattr(self.conn, "maybe_originate_rtt"):
                self.conn.maybe_originate_rtt(self._tick)
            if hasattr(self.conn, "maybe_repeat_join"):
                self.conn.maybe_repeat_join(self._tick)
            for e in self.conn.drain():
                self._send(e["proto"], e["payload"], dst_var=e["dst"], src_var=e["src"],
                           compress=e["compress"], footer=e["footer"],
                           establishing=e["establishing"], unicast=e.get("unicast", True),
                           pktid=e.get("pktid"), footer_var=e.get("footer_var"))
        if self.connected:
            if self.conn is not None:
                self._drive_reliable()
            else:
                self._send(reliable.PROTO_RELIABLE, self._reliable_trade_payload(),
                           dst_var=int.from_bytes(self.host_var, "big"),
                           src_var=int.from_bytes(self.our_var, "big"),
                           compress=False, footer=True, establishing=False)
        self.flush_paced()

    def close(self):
        if self._cap:
            self._cap.close()
