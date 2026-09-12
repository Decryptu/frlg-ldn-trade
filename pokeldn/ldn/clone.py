"""Pia Clone Protocol - protocol 0x73, the mesh's synchronized-object layer.

Let's Go Pikachu runs the game's partner sync on it. GetProtocolId at main.bin 0x158aab8 returns
0x73 (typeinfo nn::pia::clone::CloneProtocol at 0x158ab70). The message type byte is 0xAB: the high
nibble is the structure, the low nibble a variant (wiki Clone-Protocol). Measured between two
Let's Go endpoints (docs/lgpe_session.md "The Clone Protocol"):

  every message   [0] version 3, [1] type, [2] u16 the sender's frame counter (60 Hz)
  type 0x11       clock request, 18 bytes: [4] u32 message count, [8] u16 destination bitmap,
                  [0xA] u64 the sender's system tick (19.2 MHz). Both sides send them, ~5/s.
  type 0x21/0x22  clock reply, 22 bytes: the replier's own count and the requester's bitmap,
                  [0xA] u32 the replier's clone clock in ms, [0xE] u64 the request's tick echoed.
                  0x22 once either side has participated.
  type 0x31       participate, 10 bytes: [4] u32 count, [8] u16 bitmap 0x0003 (every station).
                  Sent by each side after ten of its own requests were answered.
  type 0x33       participate ack, same layout, bitmap of the sender of the 0x31.

  type 0x8N..0xfN  clone command messages, 18 bytes plus a payload: [4] u8 clone type (1..4),
                  [5] u8 owning station (0xfd = none), [6] u16 0, [8] u32 clone id, [0xC] u32 the
                  sender's message count, [0x10] u16 destination bitmap. 0x9N adds a u32 clock in
                  ms at [0x12]; 0xaN adds a u8 count at [0x16] (three unread bytes follow); 0xbN
                  adds a u32 participant bitmap at [0x16]; 0xcN both, the bitmap at [0x1a].

The message count is one counter per sender across all of these, starting at 1; the receive
handler (0x51c100) drops a message whose count does not exceed the last one from that station.
A joiner that only answers the host's requests, echoing the request's fields with a zero clock,
is never accepted; `Participant` runs the measured exchange.
"""
import struct

PROTOCOL = 0x73
VERSION = 3

CLOCK_REQUEST = 0x11
CLOCK_REPLY = 0x21
PARTICIPATE = 0x31
EXIT_ACK = 0x41
CLOCK_REPLY_SYNCED = 0x22
PARTICIPATE_ACK = 0x33
COMMAND_ANNOUNCE = 0x81
COMMAND_REQUEST = 0x82
COMMAND_END = 0x83
COMMAND_END_ACK = 0x84
CLOCK_COMMAND = 0x91
CLOCK_AND_COUNT = 0xA1
CLOCK_AND_COUNT_2 = 0xA2
CLOCK_AND_PARTICIPANT = 0xB1
CLOCK_COUNT_PARTICIPANT = 0xC1
TICK_HZ = 19_200_000
FRAME_HZ = 60

# The handlers in Let's Go Pikachu's main, for the reverse engineering that remains:
#   0x51ab20  CloneProtocol::vfunc9, the receive dispatch (splits the 0xAB type byte)
#   0x51b010  the reply/ack state machine, a jump table at 0xf76674 on (type - 0x21)
#   0x51b1d0  the clock-driven element retransmit scheduler (handles the 0x11 request side)
#   0x51f9b0  ClockRequestMessage serialize (18 bytes)
#   0x51fab0  ClockReplyMessage serialize (22 bytes)
#   0x51fbd0  ParticipateMessage serialize (10 bytes)
# The clone protocol is a synchronized-object system: once both sides have participated the
# game's clone elements run (types 0x81..0xf3, docs/lgpe_session.md "Clone elements").

__all__ = ["PROTOCOL", "VERSION", "CLOCK_REQUEST", "CLOCK_REPLY", "CLOCK_REPLY_SYNCED",
           "PARTICIPATE", "PARTICIPATE_ACK", "EXIT_ACK", "parse_clock_request", "parse_clock_reply",
           "build_clock_request", "build_clock_reply", "reply_to", "build_participate",
           "build_command", "parse_command", "Participant"]


def parse_clock_request(payload):
    """-> dict of the clock request's fields, or None if it is not a type-0x11 clone message."""
    if len(payload) < 0x12 or payload[0] != VERSION or payload[1] != CLOCK_REQUEST:
        return None
    field_a, count, participant = struct.unpack_from(">HIH", payload, 2)
    clock = struct.unpack_from(">Q", payload, 0xA)[0]
    return {"version": payload[0], "type": payload[1], "field_a": field_a, "count": count,
            "participant": participant, "clock": clock}


def parse_clock_reply(payload):
    """-> dict of a clock reply's fields (type 0x21 or 0x22), or None."""
    if len(payload) < 0x16 or payload[0] != VERSION or payload[1] not in (CLOCK_REPLY,
                                                                          CLOCK_REPLY_SYNCED):
        return None
    field_a, count, participant, ms = struct.unpack_from(">HIHI", payload, 2)
    clock = struct.unpack_from(">Q", payload, 0xE)[0]
    return {"type": payload[1], "field_a": field_a, "count": count, "participant": participant,
            "ms": ms, "clock": clock}


def build_clock_request(field_a, count, participant, clock):
    """The 18-byte clock request (type 0x11), fields in the order 0x51f9b0 writes them."""
    return (bytes([VERSION, CLOCK_REQUEST]) + struct.pack(">HIH", field_a & 0xFFFF,
            count & 0xFFFFFFFF, participant & 0xFFFF) + struct.pack(">Q", clock & ((1 << 64) - 1)))


def build_clock_reply(field_a, count, participant, clock, extra=0, kind=CLOCK_REPLY):
    """The 22-byte clock reply (type 0x21, or 0x22 once participating), fields in the order
    0x51fab0 writes them: `extra` is the replier's clone clock in ms, `clock` the request's tick."""
    return (bytes([VERSION, kind]) + struct.pack(">HIH", field_a & 0xFFFF,
            count & 0xFFFFFFFF, participant & 0xFFFF) + struct.pack(">I", extra & 0xFFFFFFFF)
            + struct.pack(">Q", clock & ((1 << 64) - 1)))


def reply_to(request_payload, extra=0):
    """-> the clock reply bytes for a clock request, echoing its fields. None if not a request."""
    r = parse_clock_request(request_payload)
    if r is None:
        return None
    return build_clock_reply(r["field_a"], r["count"], r["participant"], r["clock"], extra)


def build_participate(field_a=0, value=0, participant=0, kind=PARTICIPATE):
    """The 10-byte participate message (type 0x31) or its ack (0x33), fields in the order 0x51fbd0
    writes them: version 3, type, the frame counter, the message count, the destination bitmap."""
    return (bytes([VERSION, kind]) + struct.pack(">HIH", field_a & 0xFFFF,
            value & 0xFFFFFFFF, participant & 0xFFFF))


def build_command(kind, ctype, station, clone_id, count, dest, payload=b""):
    """A clone command message (types 0x81 and up), header per CloneCommandMessage::Serialize
    (0x51f820) with `payload` after the 18-byte header."""
    return (bytes([VERSION, kind]) + struct.pack(">HBBHIIH", 0, ctype & 0xFF, station & 0xFF, 0,
            clone_id & 0xFFFFFFFF, count & 0xFFFFFFFF, dest & 0xFFFF) + payload)


def parse_command(payload):
    """-> dict of a clone command message's header and payload, or None."""
    if len(payload) < 0x12 or payload[0] != VERSION or payload[1] < 0x80:
        return None
    frame, ctype, station, _, clone_id, count, dest = struct.unpack_from(">HBBHIIH", payload, 2)
    return {"type": payload[1], "frame": frame, "ctype": ctype, "station": station,
            "clone_id": clone_id, "count": count, "dest": dest, "payload": payload[0x12:]}


class Participant:
    """One side of the measured clock exchange. `now` is a monotonic clock in seconds; the
    frame counter, tick and ms clock all start at construction. `dest` is the peer's station
    bitmap (0x0001 for a host at index 0). Feed every 0x73 payload to `receive`; call `poll` a
    few times a second; send what both return."""

    def __init__(self, now, dest=0x0001, request_interval=0.2, requests_before_participate=10):
        self.t0 = now
        self.dest = dest
        self.count = 0
        self.next_request = now + 0.06
        self.request_interval = request_interval
        self.answered = 0
        self.participate_after = requests_before_participate
        self.participated = False
        self.peer_participated = False
        self.announced = False
        self.mesh_ms = None
        self.log = []

    def frame(self, now):
        return int((now - self.t0) * FRAME_HZ) & 0xFFFF

    def tick(self, now):
        return int(now * TICK_HZ)

    def ms(self, now):
        """The clock a clone message carries: the mesh clock from the Sync Clock Protocol once
        the host has answered one, our own elapsed milliseconds before that."""
        if self.mesh_ms is not None:
            return self.mesh_ms
        return int((now - self.t0) * 1000)

    def _next_count(self):
        self.count += 1
        return self.count

    def poll(self, now):
        """-> [payload] to send now: a clock request on its interval, the participate once due."""
        out = []
        if now >= self.next_request:
            self.next_request = now + self.request_interval
            out.append(build_clock_request(self.frame(now), self._next_count(), self.dest,
                                           self.tick(now)))
        if not self.participated and self.answered >= self.participate_after:
            self.participated = True
            out.append(build_participate(self.frame(now), self._next_count(), 0x0003))
        if self.participated and self.peer_participated_ack and not self.announced:
            # what a joiner sends 6 ms after the host's 0x33: a ClockAndCount (0xa1) for the
            # type-3 clone id 0, count 1
            self.announced = True
            out.append(self._command(CLOCK_AND_COUNT, 3, 0xFD, 0, now,
                                     struct.pack(">IB", self.ms(now), 1) + b"\0\0\0"))
        return out

    peer_participated_ack = False

    def _command(self, kind, ctype, station, clone_id, now, payload=b""):
        m = build_command(kind, ctype, station, clone_id, self._next_count(), self.dest, payload)
        return m[:2] + struct.pack(">H", self.frame(now)) + m[4:]

    def receive(self, payload, now):
        """-> [payload] to send in answer to one received 0x73 payload."""
        if len(payload) < 2 or payload[0] != VERSION:
            return []
        kind = payload[1]
        self.log.append((round(now - self.t0, 3), kind, len(payload)))
        if kind == CLOCK_REQUEST:
            r = parse_clock_request(payload)
            reply_kind = CLOCK_REPLY_SYNCED if (self.participated or self.peer_participated) \
                else CLOCK_REPLY
            return [build_clock_reply(self.frame(now), self._next_count(), self.dest,
                                      r["clock"], extra=self.ms(now), kind=reply_kind)]
        if kind in (CLOCK_REPLY, CLOCK_REPLY_SYNCED):
            self.answered += 1
            return []
        if kind == PARTICIPATE:
            self.peer_participated = True
            return [build_participate(self.frame(now), self._next_count(), self.dest,
                                      kind=PARTICIPATE_ACK)]
        if kind == PARTICIPATE_ACK:
            self.peer_participated_ack = True
            return []
        c = parse_command(payload)
        if c is None:
            return []
        key = (c["ctype"], c["station"], c["clone_id"])
        if key == (3, 0xFD, 0):
            # the measured joiner answers of the type-3 clone: a2 echoes a1's clock with count 1,
            # c1 echoes b1's clock with count 1 and its participant bitmap, 0x84 answers 0x83
            if kind == CLOCK_AND_COUNT and len(c["payload"]) >= 4:
                clk = c["payload"][:4]
                return [self._command(CLOCK_AND_COUNT_2, 3, 0xFD, 0, now,
                                      clk + b"\x01\0\0\0")]
            if kind == CLOCK_AND_PARTICIPANT and len(c["payload"]) >= 8:
                clk, part = c["payload"][:4], c["payload"][4:8]
                return [self._command(CLOCK_COUNT_PARTICIPANT, 3, 0xFD, 0, now,
                                      clk + b"\x01\0\0\x02" + part)]
            if kind == COMMAND_END:
                return [self._command(COMMAND_END_ACK, 3, 0xFD, 0, now)]
        return []
