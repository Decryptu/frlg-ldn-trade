"""Pia Clone Protocol - protocol 0x73, the mesh's synchronized-object layer.

Let's Go Pikachu runs the game's partner sync on it. GetProtocolId at main.bin 0x158aab8 returns
0x73 (typeinfo nn::pia::clone::CloneProtocol at 0x158ab70). The message type byte is 0xAB: the high
nibble is the structure, the low nibble a variant (wiki Clone-Protocol). The clock sync seen on the
wire:

  type 0x11  clock request  (the host sends these ~5/s, addressed to the joiner's station bitmap)
  type 0x21  clock reply    (the joiner must answer, or the clone clock never syncs and the game
                             drops the partner with "connexion interrompue")

Read off the console's own serializers. ClockRequestMessage serialize (0x51f9b0), 18 bytes:

    [0]   1  version = 3
    [1]   1  type = 0x11
    [2]   2  field A, big-endian        (obj+0xA; increments ~0xD per request)
    [4]   4  count, big-endian          (obj+0xC; +1 per request)
    [8]   2  participant bitmap, big-endian (obj+0x10; the joiner station's bit)
    [0xA] 8  clock, big-endian          (obj+0x18; a rising tick value)

ClockReplyMessage serialize (0x51fab0), 22 bytes, the same fields plus an extra u32:

    [0]   1  version = 3
    [1]   1  type = 0x21
    [2]   2  field A, big-endian        (obj+0xA)
    [4]   4  count, big-endian          (obj+0xC)
    [8]   2  participant bitmap, big-endian (obj+0x10)
    [0xA] 4  extra u32, big-endian      (obj+0x14; absent from the request)
    [0xE] 8  clock, big-endian          (obj+0x18)

What the extra u32 and the exact clock semantics are is unconfirmed; a reply that echoes the
request's field A, count, participant and clock and sends the extra u32 as zero is the first try.
docs/lgpe_session.md "Joining the mesh".
"""
import struct

PROTOCOL = 0x73
VERSION = 3

CLOCK_REQUEST = 0x11
CLOCK_REPLY = 0x21
PARTICIPATE = 0x31
EXIT_ACK = 0x41

__all__ = ["PROTOCOL", "VERSION", "CLOCK_REQUEST", "CLOCK_REPLY", "parse_clock_request",
           "build_clock_reply"]


def parse_clock_request(payload):
    """-> dict of the clock request's fields, or None if it is not a type-0x11 clone message."""
    if len(payload) < 0x12 or payload[0] != VERSION or payload[1] != CLOCK_REQUEST:
        return None
    field_a, count, participant = struct.unpack_from(">HIH", payload, 2)
    clock = struct.unpack_from(">Q", payload, 0xA)[0]
    return {"version": payload[0], "type": payload[1], "field_a": field_a, "count": count,
            "participant": participant, "clock": clock}


def build_clock_reply(field_a, count, participant, clock, extra=0):
    """The 22-byte clock reply (type 0x21), fields in the order 0x51fab0 writes them."""
    return (bytes([VERSION, CLOCK_REPLY]) + struct.pack(">HIH", field_a & 0xFFFF,
            count & 0xFFFFFFFF, participant & 0xFFFF) + struct.pack(">I", extra & 0xFFFFFFFF)
            + struct.pack(">Q", clock & ((1 << 64) - 1)))


def reply_to(request_payload, extra=0):
    """-> the clock reply bytes for a clock request, echoing its fields. None if not a request."""
    r = parse_clock_request(request_payload)
    if r is None:
        return None
    return build_clock_reply(r["field_a"], r["count"], r["participant"], r["clock"], extra)
