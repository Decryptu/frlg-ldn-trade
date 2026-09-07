"""Pia's RTT Protocol - protocol 0x58, the round-trip timer the mesh runs under everything.

The console starts sending these the moment a station joins the mesh, and there is no wiki page for
it: every field below is read off BDSP's own ARM64 and then checked against the thirteen messages
sp35 captured.

A message is thirteen bytes and always thirteen (`nn::pia::transport::RttProtocol::Data`, size
main.bin 0x015adab4 -> 0xd, serialise 0x015ada24, parse 0x015ad54c - the parse refuses anything
0x0c or shorter):

    u8   kind          0 = request, 1 = response; anything else is dropped (0x015ad020)
    u64  timestamp     big-endian, the sender's own clock. A response ECHOES it unchanged
    u32  target        big-endian, whose reply this is. ZERO IS ACCEPTED BY EVERYONE

The host broadcasts a REQUEST every ~410 ms with target 0 (13 of 13 in sp35, message flags 0x01,
destination bitmap 0xffffffff - the local protocol's 0x11 is the local protocol's alone). A station
answers with kind 1, the same timestamp, and the requester's own id in `target`; the receiver's
first test is `if target == 0: accept` (0x015ad000), so answering with 0 needs no id at all.

What the host does with the answer (0x015ad058): `(now - echoed) / ticks per ms` goes into a nine
sample ring per station at `[protocol + 0x120] + index * 0x34`, and the median becomes that
station's RTT once the ring is full. **NOTHING IN THIS PROTOCOL DROPS A STATION FOR STAYING
SILENT** - a station that never answers simply never gets a sample. Read the code before believing
the opposite; sp35 sat through 78 s of it.

`docs/bdsp_pia.md` "The RTT protocol".
"""

import struct

PROTOCOL = 0x58
VERSION = 3                       # 0x015ada18 returns 3, 0x015ada10 returns 0x58
PORT = 0
SIZE = 13                         # 0x015adab4: `mov w0, #0xd`
MESSAGE_FLAGS = 0x01              # what the console itself sends on this protocol

REQUEST = 0
RESPONSE = 1
KIND_NAMES = {REQUEST: "REQUEST", RESPONSE: "RESPONSE"}

ANY_TARGET = 0                    # 0x015ad000 accepts a target of 0 without comparing anything


def build(kind, timestamp, target=ANY_TARGET):
    """The thirteen bytes, in the order 0x015ada24 writes them."""
    return (bytes([kind & 0xFF]) + struct.pack(">Q", timestamp & ((1 << 64) - 1))
            + struct.pack(">I", target & 0xFFFFFFFF))


def parse(data):
    """-> dict. The console's own parser refuses anything shorter than thirteen bytes."""
    if len(data) < SIZE:
        raise ValueError(f"an RTT message is {SIZE} bytes, got {len(data)}: {data.hex()}")
    kind = data[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#04x}"),
            "timestamp": struct.unpack_from(">Q", data, 1)[0],
            "target": struct.unpack_from(">I", data, 9)[0]}


def response_for(data, target=ANY_TARGET):
    """-> the answer to an RTT request, or None if this is not one.

    The console builds its own at 0x015ad024: kind 1, the request's timestamp copied across
    unchanged, and the requester's id in `target`. We send 0 there because the receiver takes any
    message whose target is 0 and we have no id to put in it that the console has told us.
    """
    if len(data) < SIZE or data[0] != REQUEST:
        return None
    return build(RESPONSE, struct.unpack_from(">Q", data, 1)[0], target)
