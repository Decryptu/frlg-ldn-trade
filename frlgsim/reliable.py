"""Pia message tiling + the Reliable(10) sub-header. A decrypted+decompressed blob = <message>* <2-byte recipient
station-id footer> <0xff padding>; message headers are presence-flagged (fields inherit from the previous message when
the bit is clear).
"""

from dataclasses import dataclass, field

PROTO_NAMES = {1: "Net", 3: "RTT", 4: "Sync", 5: "Unreliable",
               9: "Clock", 10: "Reliable", 13: "Session"}
PROTO_RELIABLE = 10

# The footer is the RECIPIENT var id: a guest->host blob's footer is STATION_HOST.
STATION_HOST = 0x7620
STATION_JOINER = 0xc493

# Reliable flagsA: 1=AppData 2=MsgStart 4=MsgEnd 8=Initialized; the other Pia bits are unused by this title.
FLAGSA_GBA = 0x07
FLAGSA_INIT = 0x0f      # stream-opening frame; the peer ignores DATA until it sees one
FLAGSA_CTRL = 0x00

# All times are milliseconds.
RTO_BASE_MS = 33        # also the delayed-ack interval
RTO_RTT_FACTOR = 1.4    # RTO = RTO_BASE_MS + RTO_RTT_FACTOR * median(RTT); no backoff, no clamp
RTT_WINDOW = 7
FAST_RETX_MIN_MS = 25   # floor between two fast-retransmits of the same hole (or the median RTT if larger)
MAX_INFLIGHT = 128      # the selective-ack mask spans 128 sequence ids

# The emulator's first Reliable payload: a title/version metadata frame on the INIT frame.
METADATA_FRAME = bytes.fromhex("4a002a005801004c656166477265656e5f65" + "00" * 28)


def build_bulk_ack(next_expected, mask=b"\x00" * 16, stream_id=0):
    """`<stream_id> 01 <next_expected:2 BE> <16-byte mask>` (unicast carries a single entry)."""
    return bytes([stream_id & 0xFF, 1]) + (next_expected & 0xFFFF).to_bytes(2, "big") + mask


def parse_bulk_ack(payload):
    """-> (ack_id, mask): ack_id = next-expected (everything below is acked); mask bit i => ack_id+i+1 received. The +1
    origin is measured on hardware: reading `ack_id+i` marks the console's own hole as received.
    """
    if len(payload) < 4:
        return None, b""
    return int.from_bytes(payload[2:4], "big"), payload[4:20].ljust(16, b"\x00")


# Bit i of a bulk-ack mask refers to ack_id + i + MASK_ORIGIN_OFFSET; reading and writing must agree (one codec both ways).
MASK_ORIGIN_OFFSET = 1


def _seq_lt(a, b):
    d = (b - a) & 0xFFFF
    return d != 0 and d < 0x8000


# send entry = [flagsA, inner, last_tx_ms, resends, acked]
_E_FLAGS, _E_INNER, _E_LASTTX, _E_RESENDS, _E_ACKED = range(5)


class ReliableLink:
    """Selective-repeat sliding window, one per peer; all times in ms. `window_lo` is the header's lowest-pending-ack field."""

    def __init__(self, start=0xFFF0, max_inflight=MAX_INFLIGHT, rtt_jitter_k=0.0,
                 dup_nack_threshold=1, rto_ceil_ms=None, rto_backoff=1.0, rto_bootstrap_ms=None):
        """Defaults are the console's algorithm. rtt_jitter_k adds K*MAD(RTT) to the RTO; dup_nack_threshold NACKs before a
        fast-retransmit; rto_ceil_ms clamps; rto_backoff multiplies per resend; rto_bootstrap_ms is the RTO used only before
        the first RTT sample (not a floor).
        """
        self.out_seq = start
        self.window_lo = start
        self.unacked = {}
        self.recv_next = start
        self.recv_buf = {}
        self.recv_ooo = set()
        self.max_inflight = max_inflight
        self._rtt = []
        self._rtt_jitter_k = rtt_jitter_k
        self._dup_nack_threshold = max(1, dup_nack_threshold)
        self._rto_ceil_ms = rto_ceil_ms
        self._rto_backoff = rto_backoff
        self._rto_bootstrap_ms = rto_bootstrap_ms
        self._peer_gap = None
        self._gap_nacks = 0

    def inflight(self):
        return len(self.unacked)

    def outstanding(self):
        """Frames the peer has not acked. inflight() also counts acked frames held behind a hole; gating sends on that
        throttles for nothing.
        """
        return sum(1 for e in self.unacked.values() if not e[_E_ACKED])

    def send_low(self):
        return self.window_lo if self.unacked else self.out_seq

    def queue(self, inner, flagsA, now_ms):
        seq = self.out_seq
        self.out_seq = (self.out_seq + 1) & 0xFFFF
        self.unacked[seq] = [flagsA, inner, now_ms, 0, False]
        return seq

    def add_rtt_sample(self, rtt_ms):
        if rtt_ms is None or rtt_ms < 0:
            return
        self._rtt.append(float(rtt_ms))
        if len(self._rtt) > RTT_WINDOW:
            self._rtt = self._rtt[-RTT_WINDOW:]

    def rto(self):
        """RTO_BASE_MS + RTO_RTT_FACTOR*median(RTT) [+ rtt_jitter_k*MAD], clamped by rto_ceil_ms; None before the first sample
        unless rto_bootstrap_ms is set. Not a floor: once samples exist the pure formula applies (a floor measured ~2x slower).
        """
        if self._rtt:
            s = sorted(self._rtt)
            median = s[len(s) // 2]
            rto = RTO_BASE_MS + RTO_RTT_FACTOR * median
            if self._rtt_jitter_k:
                mad = sum(abs(x - median) for x in self._rtt) / len(self._rtt)
                rto += self._rtt_jitter_k * mad
        elif self._rto_bootstrap_ms is not None:
            rto = self._rto_bootstrap_ms
        else:
            return None
        if self._rto_ceil_ms is not None:
            rto = min(rto, self._rto_ceil_ms)
        return rto

    def on_ack(self, ack_id, mask=None, now_ms=None):
        """A frame is acked by the cumulative run below ack_id or by the mask; the window base advances only over the contiguous
        acked run. An un-retransmitted frame's first ack yields an RTT sample (from the mask too, to avoid head-of-line bias).
        """
        if ack_id is None:
            return
        maskint = int.from_bytes(mask, "little") if mask else 0
        for seq, entry in self.unacked.items():
            arrived = _seq_lt(seq, ack_id)
            if not arrived and maskint:
                # A wrong mask origin marks the peer's real hole as acked, so it is never retransmitted and its window never advances.
                i = (seq - ack_id - MASK_ORIGIN_OFFSET) & 0xFFFF
                arrived = i < 128 and bool((maskint >> i) & 1)
            if arrived and not entry[_E_ACKED]:
                if now_ms is not None and entry[_E_RESENDS] == 0:
                    self.add_rtt_sample(now_ms - entry[_E_LASTTX])
                entry[_E_ACKED] = True
        while self.window_lo in self.unacked and self.unacked[self.window_lo][_E_ACKED]:
            del self.unacked[self.window_lo]
            self.window_lo = (self.window_lo + 1) & 0xFFFF
        if maskint and ack_id in self.unacked and not self.unacked[ack_id][_E_ACKED]:
            if ack_id == self._peer_gap:
                self._gap_nacks += 1
            else:
                self._peer_gap = ack_id
                self._gap_nacks = 1
        else:
            self._peer_gap = None
            self._gap_nacks = 0

    def _fast_retx_gap(self):
        if self._rtt:
            s = sorted(self._rtt)
            return max(FAST_RETX_MIN_MS, s[len(s) // 2])
        return FAST_RETX_MIN_MS

    def due_retransmits(self, now_ms, limit=None):
        """Oldest-first unacked frames due for resend, stamped. The peer's hole is fast-retransmitted re-armably (first response
        immediate, later ones one round trip apart, each consuming the NACK count); timer resend at rto()*backoff**resends.
        limit=N stops at the first not-yet-due frame.
        """
        base_rto = self.rto()
        out = []
        for seq in sorted(self.unacked, key=lambda s: (s - self.window_lo) & 0xFFFF):
            entry = self.unacked[seq]
            if entry[_E_ACKED]:
                continue
            if (seq == self._peer_gap and self._gap_nacks >= self._dup_nack_threshold
                    and (entry[_E_RESENDS] == 0
                         or (now_ms - entry[_E_LASTTX]) >= self._fast_retx_gap())):
                due = True
                self._gap_nacks = 0
            elif base_rto is None:
                due = False
            else:
                eff_rto = base_rto * (self._rto_backoff ** entry[_E_RESENDS])
                if self._rto_ceil_ms is not None:
                    eff_rto = min(eff_rto, self._rto_ceil_ms)
                due = (now_ms - entry[_E_LASTTX]) >= eff_rto
            if due:
                entry[_E_LASTTX] = now_ms
                entry[_E_RESENDS] += 1
                out.append((seq, entry[_E_FLAGS], entry[_E_INNER]))
                if limit is not None and len(out) >= limit:
                    break
            elif limit is not None:
                break
        return out

    def on_data(self, seq, payload):
        """Offline path: deliver in order, buffering across a gap (its ack carries a zero mask)."""
        if seq == self.recv_next:
            out = [payload]
            self.recv_next = (self.recv_next + 1) & 0xFFFF
            while self.recv_next in self.recv_buf:
                out.append(self.recv_buf.pop(self.recv_next))
                self.recv_next = (self.recv_next + 1) & 0xFFFF
            return out
        if _seq_lt(self.recv_next, seq):
            self.recv_buf[seq] = payload
        return []

    def note_received(self, seq):
        """Live path: record a received seq without delivery; advances recv_next and keeps out-of-order seqs for the ack mask."""
        if seq == self.recv_next:
            self.recv_next = (self.recv_next + 1) & 0xFFFF
            while self.recv_next in self.recv_ooo:
                self.recv_ooo.discard(self.recv_next)
                self.recv_next = (self.recv_next + 1) & 0xFFFF
        elif _seq_lt(self.recv_next, seq):
            self.recv_ooo.add(seq)

    def ack_payload(self):
        """Cumulative recv_next + selective mask of recv_ooo (bit i => recv_next+i+1), the origin the console's codec uses."""
        mask = bytearray(16)
        for s in self.recv_ooo:
            i = (s - self.recv_next - MASK_ORIGIN_OFFSET) & 0xFFFF
            if i < 128:
                mask[i >> 3] |= (1 << (i & 7))
        return build_bulk_ack(self.recv_next, bytes(mask))


@dataclass(frozen=True)
class ReliableEmission:
    seq: int
    flagsA: int
    ack: int
    payload: bytes
    retransmitted: bool = False

    @property
    def message_flags(self):
        # Both native peers set Pia message flag 0x40 on pure bulk ACKs and 0x20 on retransmitted DATA.
        if self.flagsA == FLAGSA_CTRL:
            return 0x40
        return 0x20 if self.retransmitted else None

    def serialize(self):
        return build_reliable(self.seq, self.ack, self.payload, self.flagsA)


@dataclass(frozen=True)
class ReliableDelivery:
    seq: int
    flagsA: int
    payload: bytes


class HostReliableSession:
    """Transport-independent Pia Reliable leader. Both streams start at FFF0; the native leader opens with its RFU 'A'
    accept as an Initialized DATA frame (the joiner opens with the title metadata).
    """

    def __init__(self, start=0xFFF0, *, ack_period_ms=RTO_BASE_MS,
                 max_inflight=MAX_INFLIGHT, rto_bootstrap_ms=200,
                 dup_nack_threshold=1, retransmit_limit=None):
        self.start_seq = start & 0xFFFF
        self.link = ReliableLink(
            start=self.start_seq,
            max_inflight=max_inflight,
            rto_bootstrap_ms=rto_bootstrap_ms,
            dup_nack_threshold=dup_nack_threshold,
        )
        self.ack_period_ms = float(ack_period_ms)
        self.retransmit_limit = retransmit_limit
        self.local_opened = False
        self.peer_opened = False
        self._ack_owed = False
        self._next_ack_ms = None

        # Delivery ordering is separate from the receive ACK accounting, which advances immediately with a selective mask.
        self._deliver_next = self.start_seq
        self._deliver_buf = {}

    @property
    def inflight(self):
        return self.link.inflight()

    @property
    def recv_next(self):
        return self.link.recv_next

    def _emission(self, seq, flagsA, payload, *, retransmitted=False):
        # ACK/window base is sampled at emission time, including retransmissions.
        return ReliableEmission(seq & 0xFFFF, flagsA, self.link.send_low(), bytes(payload),
                                retransmitted=retransmitted)

    def open(self, payload, now_ms, flagsA=FLAGSA_GBA):
        """Idempotent: a duplicate child 'C' must not allocate a second opening sequence id."""
        if self.local_opened:
            return None
        flagsA = (int(flagsA) | FLAGSA_INIT) & 0xFF
        payload = bytes(payload)
        seq = self.link.queue(payload, flagsA, now_ms)
        self.local_opened = True
        return self._emission(seq, flagsA, payload)

    def send(self, payload, now_ms, flagsA=FLAGSA_GBA):
        """Raises on a full window rather than dropping, so backpressure is explicit."""
        if not self.local_opened:
            raise RuntimeError("Reliable stream has not been opened")
        if self.link.inflight() >= self.link.max_inflight:
            raise BufferError("Reliable send window is full")
        flagsA = int(flagsA) & 0xFF
        if not (flagsA & 0x01):
            raise ValueError("send() is for Reliable DATA frames, not control ACKs")
        seq = self.link.queue(bytes(payload), flagsA, now_ms)
        return self._emission(seq, flagsA, payload)

    def note_rtt(self, rtt_ms):
        self.link.add_rtt_sample(rtt_ms)

    def _deliver(self, frame):
        seq = frame.seq
        if seq == self._deliver_next:
            ready = [ReliableDelivery(seq, frame.flagsA, bytes(frame.payload))]
            self._deliver_next = (self._deliver_next + 1) & 0xFFFF
            while self._deliver_next in self._deliver_buf:
                buffered = self._deliver_buf.pop(self._deliver_next)
                ready.append(ReliableDelivery(
                    buffered.seq, buffered.flagsA, bytes(buffered.payload)))
                self._deliver_next = (self._deliver_next + 1) & 0xFFFF
            return ready
        if _seq_lt(self._deliver_next, seq):
            self._deliver_buf.setdefault(seq, frame)
        return []

    def receive(self, wire, now_ms):
        """Returns newly in-order DATA; control frames update the window/RTT and are never acked themselves."""
        frame = parse_reliable(bytes(wire))
        if frame is None or frame.raw_len > len(wire) - 8:
            return []
        if not (frame.flagsA & 0x01):
            ack_id, mask = parse_bulk_ack(frame.payload)
            self.link.on_ack(ack_id, mask, now_ms=now_ms)
            return []

        # The fff0 opening DATA must carry Initialized; a plain frame must not consume that slot or a later INIT looks like a duplicate.
        if (not self.peer_opened and frame.seq == self.start_seq
                and not (frame.flagsA & 0x08)):
            return []
        if frame.flagsA & 0x08:
            self.peer_opened = True
        self.link.note_received(frame.seq)
        self._ack_owed = True
        if self._next_ack_ms is None:
            self._next_ack_ms = float(now_ms) + self.ack_period_ms
        return self._deliver(frame)

    def poll(self, now_ms):
        """Due retransmissions followed by at most one bulk ACK."""
        emissions = [
            self._emission(seq, flagsA, payload, retransmitted=True)
            for seq, flagsA, payload in self.link.due_retransmits(
                now_ms, limit=self.retransmit_limit)
        ]
        ack_due = (self._next_ack_ms is not None
                   and float(now_ms) >= self._next_ack_ms)
        if ack_due and (self._ack_owed or self.link.recv_ooo):
            emissions.append(ReliableEmission(
                self.start_seq, FLAGSA_CTRL, self.link.send_low(),
                self.link.ack_payload()))
            self._ack_owed = False
            # keep NACKing a persistent gap at the delayed-ack cadence
            self._next_ack_ms = (float(now_ms) + self.ack_period_ms
                                 if self.link.recv_ooo else None)
        return emissions


@dataclass
class Message:
    flags: int
    proto: int
    size: int
    payload: bytes
    msgflags: int = 0
    hdr_bytes: bytes = b""

    def serialize(self):
        return self.hdr_bytes + self.payload


def parse_messages(data):
    msgs = []
    i, n = 0, len(data)
    mf, size, proto = 0, None, None
    while i < n:
        fl = data[i]
        if fl == 0xff or (fl & 0xF0):
            break
        if fl == 0 and size is None:
            break
        hdr_start = i
        j = i + 1
        if fl & 1:
            if j >= n:
                break
            mf = data[j]
            j += 1
        if fl & 2:
            if j + 2 > n:
                break
            size = int.from_bytes(data[j:j + 2], "big")
            j += 2
        if fl & 4:
            if j >= n:
                break
            proto = data[j]
            j += 1
        if fl & 8:
            # 6.32-6.40 format: bit 0x8 is a 1-byte port (the older format had an 8-byte u64 here and mis-tiles the stream).
            if j + 1 > n:
                break
            j += 1
        if size is None or j + size > n:
            break
        msgs.append(Message(flags=fl, msgflags=mf, proto=proto, size=size,
                            payload=data[j:j + size], hdr_bytes=data[hdr_start:j]))
        i = j + size
    return msgs, i


def build_message(proto, payload, msgflags=None):
    """Header flags bit0=msgflags bit1=size bit2=proto; size+proto are always set so the message parses standalone."""
    flags = 0x02 | 0x04
    hdr = bytearray()
    if msgflags is not None:
        flags |= 0x01
    hdr.append(flags)
    if msgflags is not None:
        hdr.append(msgflags & 0xFF)
    hdr += len(payload).to_bytes(2, "big")
    hdr.append(proto & 0xFF)
    return bytes(hdr) + payload


@dataclass
class Reliable:
    """Reliable(10) sub-header BE: flags(1) size(2) seq(2) window_base(2) N(1) then payload; N = multicast recipient
    count, 0 for unicast.
    """
    flagsA: int
    seq: int
    ack: int
    payload: bytes
    raw_len: int = 0

    def serialize(self):
        return (bytes([self.flagsA]) + len(self.payload).to_bytes(2, "big")
                + self.seq.to_bytes(2, "big") + self.ack.to_bytes(2, "big")
                + bytes([0x00]) + self.payload)


def parse_reliable(payload):
    if len(payload) < 8:
        return None
    ln = int.from_bytes(payload[1:3], "big")
    return Reliable(flagsA=payload[0],
                    seq=int.from_bytes(payload[3:5], "big"),
                    ack=int.from_bytes(payload[5:7], "big"),
                    payload=payload[8:8 + ln], raw_len=ln)


def build_reliable(seq, ack, inner, flagsA=FLAGSA_GBA):
    return Reliable(flagsA=flagsA, seq=seq, ack=ack, payload=inner).serialize()


def parse_app(data):
    """-> (messages, station_id_or_None, tail_len); the tail is a 2-byte station footer then 0xff padding."""
    msgs, consumed = parse_messages(data)
    tail = data[consumed:]
    stripped = tail.rstrip(b"\xff")
    station = int.from_bytes(stripped, "big") if len(stripped) == 2 else None
    return msgs, station, len(tail)


def build_app(messages, station_id=STATION_HOST, pad=0):
    blob = b"".join(messages) + station_id.to_bytes(2, "big")
    return blob + b"\xff" * pad
