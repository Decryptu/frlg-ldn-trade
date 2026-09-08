"""Pia version 4's reliable sliding window - protocol 0x7C, and the ack shape that is NOT 5.29's.

`reliable5.py` is the 5.29-5.43 wrapper, and sw29 and sw30 between them put 221887 of a retail
Sword's reliable messages through `reliable5.parse` without a field out of place - because every
one of them carried NO destination, which is the only count at which the two headers agree.
Version 4's own header is built and read here (`build_header`, `parse_message`, read off
`MessageHeader` at 0x0184e230/0x0184e390/0x0184e480): its byte at 0x8 is a COUNT of eight-byte
station ids, not 5.29's bitmap width. The ACK PAYLOAD moved BACKWARDS too - version 4 carries the
original fixed table that 5.29 replaced with a counted list.

    5.29-5.43   1 unknown byte, 1 count byte, then `count` x 21 bytes
                    u8 stream id, u16be ack id, u16be the window's field 0x50, 16-byte mask
    version 4   32 entries of 19 bytes, ALWAYS, and nothing before them
                    u8 stream id, u16be ack id, 16-byte mask

so a version-4 ack payload is **exactly 0x260 bytes**, 32 * 19, and that is not a deduction: the
handler at `0x01859a84` opens with `ldrh w8, [x2, #0xa]; cmp w8, #0x260; b.ne` and answers error
0x2c03 without reading a byte of the body. sw30 sent 96 acks in 5.29's 23-byte shape and every one
of them died there - the console's own `lowest_pending` never moved off 1 across two runs and 221887
messages. The serialiser `0x0185bfb0` is the layout: a bound of 0x260 on the buffer, a loop of 0x20,
and per entry a stream id, an ack id written big-endian into [1] and [2], and sixteen mask bytes
written as two big-endian u64 halves.

**THE 32 SLOTS ARE INDEXED BY STATION, and the console's own ack says so.** Its broadcast ack
(protocol 0x80, decompressed - see `parse_broadcast_message`) fills slots **0..7** with the real ack
id and leaves 8..31 at zero, and 8 is `max_total` from the join response: one entry per station the
mesh can hold. Ours fills all 32, which is a superset of that and is what slid the window at sw52.

**WHICH slot the console READS is still not settled.** The handler indexes
the table with its fourth argument (`0x01859c1c`: `add x9, x23, w22; ldrb w5, [x9, #8]`) and requires
that slot's stream id to equal the window's own at `[x21+0x2e]` before it applies the ack id and mask
at the matching offsets. A 32-slot table addressed by station index is one ack message answering up
to 32 stations at once - so the slot is either the RECEIVER's index (0, the console) or the SENDER's
(1, us), and the binary does not say which from this site alone. `build_ack_payload` therefore fills
EVERY slot with the same entry by default: only one is read, so a table that answers both readings
is correct under either, and costs no association to find out.
"""

import struct

from pokeldn.ldn import reliable5

PROTOCOL = reliable5.PROTOCOL             # 0x7C, the same number
MESSAGE_FLAGS = reliable5.MESSAGE_FLAGS
ACK_SEQUENCE = reliable5.ACK_SEQUENCE     # 0xFFFF; BDSP's, not measured at version 4

ACK_ENTRIES = 32                          # 0x0185bfb0: `cmp x8, #0x20` closes the loop
ACK_ENTRY_SIZE = 19                       # u8 stream id, u16be ack id, 16 mask bytes
ACK_PAYLOAD_SIZE = ACK_ENTRIES * ACK_ENTRY_SIZE            # 0x260, checked at 0x01859a84
MASK_SIZE = 16

__all__ = ["PROTOCOL", "MESSAGE_FLAGS", "ACK_SEQUENCE", "ACK_ENTRIES", "ACK_ENTRY_SIZE",
           "ACK_PAYLOAD_SIZE", "MASK_SIZE", "build_ack_payload", "parse_ack_payload",
           "BROADCAST_PROTOCOL", "BROADCAST_HEADER", "BROADCAST_ID_SIZE",
           "parse_broadcast_message", "parse_message", "build_header", "header_size",
           "build_message", "build_data_message", "MAX_PAYLOAD", "MAX_DESTINATIONS",
           "FLAG_APPLICATION_DATA", "FLAG_MESSAGE_START", "FLAG_MESSAGE_END",
           "FLAG_IS_INITIALIZED", "FIRST_DATA_FLAGS", "DATA_FLAGS", "FIRST_SEQUENCE",
           "max_payload_for", "build_ack_message"]


def build_ack_payload(ack_id, stream_id=0, mask=b"", slots=None, filler=0xFF):
    """The 0x260 bytes. `slots` is which of the 32 to fill; None fills them all.

    A slot that is not filled carries stream id 0xFF, which cannot match a real stream and so is
    ignored if the console reads it - the entry is inert rather than a second, wrong acknowledgement.
    The console's own acks leave theirs at 0 instead (`filler=0`), which is safe for it because the
    slots it skips are past `max_total` and no station is ever indexed there.
    """
    mask = bytes(mask).ljust(MASK_SIZE, b"\0")[:MASK_SIZE]
    if len(mask) != MASK_SIZE:
        raise ValueError(f"a mask is {MASK_SIZE} bytes")
    if not 0 <= ack_id <= 0xFFFF:
        raise ValueError(f"an ack id is a halfword, got {ack_id}")
    want = set(range(ACK_ENTRIES) if slots is None else slots)
    if not want <= set(range(ACK_ENTRIES)):
        raise ValueError(f"a slot is 0..{ACK_ENTRIES - 1}, got {sorted(want)}")
    out = bytearray()
    for i in range(ACK_ENTRIES):
        if i in want:
            out += bytes([stream_id & 0xFF]) + struct.pack(">H", ack_id) + mask
        else:
            out += bytes([filler & 0xFF]) + b"\0" * (ACK_ENTRY_SIZE - 1)
    assert len(out) == ACK_PAYLOAD_SIZE
    return bytes(out)


def parse_ack_payload(data):
    """-> [dict] of all 32 entries, in slot order. There is no count byte to believe or doubt."""
    if len(data) != ACK_PAYLOAD_SIZE:
        raise ValueError(f"a version-4 ack payload is {ACK_PAYLOAD_SIZE:#x} bytes, "
                         f"got {len(data):#x} - which is what the console refuses at 0x01859a84")
    return [{"slot": i, "stream_id": data[o], "ack_id": struct.unpack_from(">H", data, o + 1)[0],
             "mask": data[o + 3:o + ACK_ENTRY_SIZE]}
            for i, o in enumerate(range(0, ACK_PAYLOAD_SIZE, ACK_ENTRY_SIZE))]


def build_ack_message(ack_id, stream_id=0, mask=b"", slots=None, lowest_pending=1,
                     destinations=(), filler=0xFF):
    """Header and payload. `ack_id` is one MORE than the highest sequence id received.

    A control message carries no sequence of its own, so it goes out as 0xFFFF. `lowest_pending` is
    OUR send window and we have never sent application data on this protocol, so 1 (the next id we
    would use, and what the console itself sends while waiting on its first) and 0 are both
    readings of it. `destinations` defaults to none - which is what sw52 sent and what slid the
    window, and what the receiver never filters; the console directs ITS acks at one id.
    """
    body = build_ack_payload(ack_id, stream_id=stream_id, mask=mask, slots=slots, filler=filler)
    return build_header(0, ACK_SEQUENCE, len(body), lowest_pending=lowest_pending,
                        stream_id=stream_id, destinations=destinations) + body


# --- The BROADCAST reliable window, protocol 0x80 --------------------------------------------
#
# `nn::pia::transport::BroadcastReliableProtocol` (vfunc4 at 0x0184d880 returns 0x80; the similarly
# named `ReliableBroadcastProtocol` is 0x84 and is NOT this). Every one of its messages in sw29 and
# sw52 is zlib compressed - see `pia4.MESSAGE_FLAG_ZLIB` - and read raw its 42 bytes look like a
# well-formed message claiming a payload of 0x6260.
#
# Decompressed, it is 625 bytes: a SEVENTEEN-byte header and then the same 0x260 ack payload this
# module builds. The header is `reliable5`'s nine bytes with the destination BITMAP replaced by a
# COUNT and that many eight-byte station constant ids:
#
#     00 00 0260 ffff 0001 01 1249a221d8580000   flags 0, stream 0, size 0x260, seq 0xFFFF,
#                                                lowest pending 1, one destination, and it is US
#
# The length is what settles the shape rather than a reading of the disassembly: 5.29's rule would
# make the header 13 bytes for one destination bit and the message 621, and the message is 625.
BROADCAST_PROTOCOL = 0x80
BROADCAST_HEADER = 9                      # before the destination ids
BROADCAST_ID_SIZE = 8


def parse_broadcast_message(data):
    """-> dict, one decompressed protocol-0x80 message. `parse_message` under its first name.

    Kept because the 0x80 path is where the shape was found and where every caller reaches for it;
    the header is not the broadcast protocol's own, it is version 4's, shared with 0x7C.
    """
    return parse_message(data)


# --- The version-4 header, and it is ONE class for BOTH protocols -----------------------------
#
# `nn::pia::transport::ReliableSlidingWindow::MessageHeader` serialises every reliable message
# version 4 sends, on 0x7C and on 0x80 alike. Session 58 read all three of its methods:
#
#     GetSize      0x0184e480    `ldrb w8, [x0,#0x10]; lsl w8, w8, #3; add w0, w8, #9`
#     Deserialize  0x0184e390
#     Serialize    0x0184e230
#
#     0x0  1  flags
#     0x1  1  stream id
#     0x2  2  payload size, big-endian     REFUSED at 0x589 and above (0x0184e3cc)
#     0x4  2  sequence id, big-endian
#     0x6  2  lowest sequence id pending ack, big-endian
#     0x8  1  destination COUNT            REFUSED at 0x20 and above (0x0184e404)
#     0x9  8 * count  station constant ids, big-endian
#
# **THE BYTE AT 0x8 IS A COUNT OF EIGHT-BYTE IDS, NOT 5.29's BITMAP WIDTH.** `GetSize` is
# `9 + 8 * count` where 5.29's is `9 + (((n + 0x1f) >> 3) & 0x3c)`, and the deserialiser reads
# `count` big-endian u64s at [9] one after another (`ldr x11, [x9], #8; rev x11, x11`). The two
# rules agree only at count 0, which is every 0x7C message either side has ever sent, and that is
# why `reliable5.parse` read 221887 of them without a field out of place.
#
# THE RECEIVE PATH IS `0x01859338`, and it refuses four things before the payload is looked at:
#
#     0x0185952c   payload size <= 0x57F - 8 * count      (a tighter bound than the deserialiser's)
#     0x0185954c   the Pia message length must EQUAL 9 + 8 * count + size, exactly
#     0x0185956c   the stream id must equal the window's own for this station, [w + 0x18*st + 0x46]
#     0x01859578   a count > 0 means the receiver must find ITS OWN id in the list, or the message
#                  is dropped in silence. A count of 0 is addressed to everyone and is never filtered
#
# and then dispatches on the flags at `0x01859734`: bit 5 RESET, bit 6 RESET_ACK, bit 0
# APPLICATION_DATA -> `0x01859ca0`, and everything else falls through to the ack handler
# `0x01859a70` - which is why a message with no flags at all is an ack.
MAX_PAYLOAD = 0x588                       # 0x0184e3cc refuses 0x589 and above
MAX_DESTINATIONS = 31                     # 0x0184e404: `cmp x8, #0x20; b.lo`
RECEIVE_BUDGET = 0x57F                    # 0x0185952c: size <= 0x57F - 8 * count

FLAG_APPLICATION_DATA = reliable5.FLAG_APPLICATION_DATA     # 0x01
FLAG_MESSAGE_START = reliable5.FLAG_MESSAGE_START           # 0x02
FLAG_MESSAGE_END = reliable5.FLAG_MESSAGE_END               # 0x04
FLAG_IS_INITIALIZED = reliable5.FLAG_IS_INITIALIZED         # 0x08

# **THE FIRST MESSAGE ON A STREAM MUST CARRY FLAG_IS_INITIALIZED OR IT IS DROPPED IN SILENCE.**
# `0x01859ca0` opens on the per-station byte at `[window + 0x18*station + 0x47]`: while it is zero
# the stream does not exist yet, and the handler reads the flags and does `tbz w9, #3, exit` - no
# error, no reply, nothing on the wire to say why. Only then does it adopt the message's stream id
# into `+0x46` and ITS SEQUENCE ID into `+0x40` as the window's start. So the first data message
# both opens the stream and chooses where it begins, and every one after it is `DATA_FLAGS`.
#
# The console's own 0x7C traffic is the worked example: its first message carried 0x0F and all 1636
# after it carried 0x07.
FIRST_DATA_FLAGS = (FLAG_APPLICATION_DATA | FLAG_MESSAGE_START | FLAG_MESSAGE_END
                    | FLAG_IS_INITIALIZED)                 # 0x0F
DATA_FLAGS = FLAG_APPLICATION_DATA | FLAG_MESSAGE_START | FLAG_MESSAGE_END   # 0x07

# The console's broadcast ack asks us for sequence 1 in sw29 and sw52 alike - 256 messages, ack id
# 1 in every filled slot, never moving. That is a window that has received nothing, so 1 is where
# ours starts. It is not a constant in the binary: `0x01859d20` takes the start from whatever the
# first message says.
FIRST_SEQUENCE = 1


def max_payload_for(destinations=()):
    """-> the largest payload this many destinations leaves room for, at the RECEIVER's bound."""
    return min(MAX_PAYLOAD, RECEIVE_BUDGET - BROADCAST_ID_SIZE * len(tuple(destinations)))


def header_size(destinations=()):
    """9, plus eight per destination id. `GetSize` at 0x0184e480, kept as its own arithmetic."""
    return BROADCAST_HEADER + BROADCAST_ID_SIZE * len(tuple(destinations))


def build_header(flags, sequence_id, payload_size, lowest_pending=0, stream_id=0,
                 destinations=()):
    """The version-4 reliable header. `destinations` are station constant ids, or () for everyone.

    A count of zero is what both sides' 0x7C traffic carries and what the receiver never filters
    on; a count above zero is a list the receiver must find itself in.
    """
    destinations = tuple(destinations)
    if len(destinations) > MAX_DESTINATIONS:
        raise ValueError(f"{len(destinations)} destinations; the console refuses 0x20 and above")
    if payload_size > max_payload_for(destinations):
        raise ValueError(f"payload {payload_size} with {len(destinations)} destinations; "
                         f"0x0185952c refuses anything over {max_payload_for(destinations)}")
    out = (bytes([flags & 0xFF, stream_id & 0xFF]) + struct.pack(">H", payload_size)
           + struct.pack(">H", sequence_id & 0xFFFF) + struct.pack(">H", lowest_pending & 0xFFFF)
           + bytes([len(destinations)]))
    return out + b"".join(struct.pack(">Q", d & 0xFFFFFFFFFFFFFFFF) for d in destinations)


def parse_message(data):
    """-> dict. One version-4 reliable message, either protocol, header and payload split.

    THE CONSOLE'S OWN ACK IS WHAT PROVES THE SHAPE: its 0x80 message decompresses to 625 bytes and
    5.29's bitmap rule accounts for only 621 of them. `parse_ack_payload` then reads all 32 slots
    of what is left, which is the independent confirmation of `build_ack_payload` - all filled,
    stream 0, one ack id, a zero mask, exactly what `slots=None` builds.
    """
    if len(data) < BROADCAST_HEADER:
        raise ValueError(f"a version-4 reliable message is at least {BROADCAST_HEADER} bytes")
    count = data[8]
    head = BROADCAST_HEADER + count * BROADCAST_ID_SIZE
    if len(data) < head:
        raise ValueError(f"{count} destination ids need {head} bytes of header, got {len(data)}")
    size = struct.unpack_from(">H", data, 2)[0]
    out = {
        "flags": data[0], "flag_names": reliable5.flag_names(data[0]), "stream_id": data[1],
        "payload_size": size,
        "sequence_id": struct.unpack_from(">H", data, 4)[0],
        "lowest_pending": struct.unpack_from(">H", data, 6)[0],
        "destination_count": count,
        "destinations": [struct.unpack_from(">Q", data, BROADCAST_HEADER + i * BROADCAST_ID_SIZE)[0]
                         for i in range(count)],
        "header_size": head,
    }
    out["payload"] = data[head:head + size]
    out["truncated"] = len(out["payload"]) < size
    out["is_ack"] = not (data[0] & FLAG_APPLICATION_DATA)
    return out


def build_message(payload, flags, sequence_id, lowest_pending=0, stream_id=0, destinations=()):
    """Header and payload, nothing else - the caller chooses the protocol it goes out on."""
    payload = bytes(payload)
    return build_header(flags, sequence_id, len(payload), lowest_pending=lowest_pending,
                        stream_id=stream_id, destinations=destinations) + payload


def build_data_message(payload, sequence_id=FIRST_SEQUENCE, destinations=(), stream_id=0,
                       lowest_pending=None, first=None):
    """One application-data message. `first` opens the stream and defaults to `sequence_id == 1`.

    `lowest_pending` is OUR window's oldest unacknowledged id and defaults to `sequence_id`, which
    is what the console sends on every message of its own: it has nothing older outstanding
    because we ack each one before it sends the next.
    """
    if first is None:
        first = sequence_id == FIRST_SEQUENCE
    return build_message(payload, FIRST_DATA_FLAGS if first else DATA_FLAGS, sequence_id,
                         lowest_pending=sequence_id if lowest_pending is None else lowest_pending,
                         stream_id=stream_id, destinations=destinations)
