"""Pia's RTT Protocol - protocol 0x58, the round-trip timer the mesh runs under everything.

The console starts sending these the moment a station joins the mesh, and there is no wiki page for
it: every field below is read off BDSP's own ARM64 and then checked against the thirteen messages
captured off a real host.

A message is thirteen bytes and always thirteen (`nn::pia::transport::RttProtocol::Data`, size
main.bin 0x015adab4 -> 0xd, serialise 0x015ada24, parse 0x015ad54c - the parse refuses anything
0x0c or shorter):

    u8   kind          0 = request, 1 = response; anything else is dropped (0x015ad020)
    u64  timestamp     big-endian, the sender's own clock. A response ECHOES it unchanged
    u32  target        big-endian, whose reply this is. ZERO IS ACCEPTED BY EVERYONE

The host broadcasts a REQUEST every ~410 ms with target 0 (13 of 13, message flags 0x01,
destination bitmap 0xffffffff - the local protocol's 0x11 is the local protocol's alone). A station
answers with kind 1, the same timestamp, and the requester's own id in `target`; the receiver's
first test is `if target == 0: accept` (0x015ad000), so answering with 0 needs no id at all.

What the host does with the answer (0x015ad058): `(now - echoed) / ticks per ms` goes into a nine
sample ring per station at `[protocol + 0x120] + index * 0x34`, and the median becomes that
station's RTT once the ring is full. **NOTHING IN THIS PROTOCOL DROPS A STATION FOR STAYING
SILENT** - a station that never answers simply never gets a sample. Read the code before believing
the opposite; one capture sat through 78 s of it.

`docs/bdsp_session.md` "The RTT protocol".
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


# --- Version 4 (Sword/Shield), off the binary and off a capture ----------------------------------
#
# THE MESSAGE IS SIXTEEN BYTES, NOT THIRTEEN. `nn::pia::transport::RttProtocol` is at vtable
# 0x25db4f8 in the Sword image, its GetProtocolId (vfunc4, 0x0185d590) returns 0x58 as BDSP's does,
# and its parser (0x0185d2a0) reads a FLAT 0x10 bytes into the object at +0x48 - `mov w3, #0x10` at
# 0x0185d320. So BDSP's thirteen-byte builder would be short by three at a Sword, which is why
# `build`/`parse` above are not simply reused.
#
# What a capture shows, 26 of 26 messages, all from the console and all requests:
#
#     0000000000000000 | 00000e783eaa067c
#     0000000000000000 | 00000e783f68f4d2
#
# the first EIGHT bytes zero and the last eight a big-endian counter that only ever rises, by a
# steady ~12.51 million per message. Message flags 0x01, and the destination is **2** - the bitmap
# bit for station index 1, us - where BDSP broadcasts to 0xffffffff.
#
# FACT: the size, and that bytes 8..15 are a monotonic big-endian u64.
# DEDUCTION: [0] is BDSP's kind byte and the u64 is BDSP's timestamp moved to an aligned offset.
# UNKNOWN: what bytes 1..7 are. They are zero in every message seen, so a capture of a request with
# a target in it is what would name them - and no station but us has ever been in this mesh.
SIZE_V4 = 0x10                    # 0x0185d320: `mov w3, #0x10`
TIMESTAMP_OFF_V4 = 8              # the only field the wire distinguishes


def parse_v4(data):
    """-> dict. Only what sixteen bytes of a version-4 RTT message actually distinguish."""
    if len(data) != SIZE_V4:
        raise ValueError(f"a version-4 RTT message is {SIZE_V4} bytes, got {len(data)}: "
                         f"{data.hex()}")
    kind = data[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#04x}"),
            "timestamp": struct.unpack_from(">Q", data, TIMESTAMP_OFF_V4)[0],
            "unread": data[1:TIMESTAMP_OFF_V4]}


def response_for_v4(data):
    """-> the sixteen bytes that answer a version-4 request: ITS OWN, with the kind set to 1.

    Echoing every byte we did not read is the point. BDSP's response is "kind 1, the timestamp
    unchanged, the requester in `target`", and a target of 0 is accepted without comparison
    (0x015ad000); here bytes 1..7 are unread and zero on every request seen, so mirroring them
    cannot be wrong in a way that inventing a layout for them could.
    """
    if len(data) != SIZE_V4:
        raise ValueError(f"a version-4 RTT message is {SIZE_V4} bytes, got {len(data)}")
    if data[0] != REQUEST:
        raise ValueError(f"only a request is answered, this is kind {data[0]:#04x}")
    return bytes([RESPONSE]) + data[1:]


def response_for(data, target=ANY_TARGET):
    """-> the answer to an RTT request, or None if this is not one.

    The console builds its own at 0x015ad024: kind 1, the request's timestamp copied across
    unchanged, and the requester's id in `target`. We send 0 there because the receiver takes any
    message whose target is 0 and we have no id to put in it that the console has told us.
    """
    if len(data) < SIZE or data[0] != REQUEST:
        return None
    return build(RESPONSE, struct.unpack_from(">Q", data, 1)[0], target)


# --- Version 3 (Let's Go Pikachu / Eevee, Pia 5.11) ----------------------------------------------
#
# Sixteen bytes as version 4, but the kind is a big-endian u32 at [0], not a byte: a response to
# `00000000 00000000 0000000049845557` is `00000001 00000000 0000000049845557`, measured in both
# directions between two Let's Go endpoints. The timestamp is the sender's own system tick at
# 19.2 MHz, and a response copies it unchanged. Each station sends its own requests about once a
# second and answers the other's.
SIZE_V3 = 0x10
TIMESTAMP_OFF_V3 = 8
TICK_HZ_V3 = 19_200_000


def build_v3(kind, timestamp):
    """The sixteen bytes: the kind as a big-endian u32, four zero bytes, the timestamp u64."""
    return struct.pack(">IIQ", kind & 0xFFFFFFFF, 0, timestamp & ((1 << 64) - 1))


def parse_v3(data):
    """-> dict of a version-3 RTT message's fields."""
    if len(data) < SIZE_V3:
        raise ValueError(f"a version-3 RTT message is {SIZE_V3} bytes, got {len(data)}: "
                         f"{data.hex()}")
    kind = struct.unpack_from(">I", data, 0)[0]
    return {"kind": kind, "name": KIND_NAMES.get(kind, f"unknown {kind:#x}"),
            "timestamp": struct.unpack_from(">Q", data, TIMESTAMP_OFF_V3)[0]}


def response_for_v3(data):
    """-> the answer to a version-3 request, or None if this is not one: its own bytes with the
    kind set to 1."""
    if len(data) < SIZE_V3 or struct.unpack_from(">I", data, 0)[0] != REQUEST:
        return None
    return struct.pack(">I", RESPONSE) + bytes(data[4:SIZE_V3])
