"""Pia 5.29-5.43's reliable sliding window - protocol 0x7c, and where BDSP's game data is.

It parses version 4 with no change: a retail Sword's own reliable
messages read field for field through `parse()` - flags 0x0F on the first and 0x07 after it, stream
0, payload size 6, sequence 1..20, lowest-pending stuck at 1, zero destination bits, a 9-byte
header and a six-byte game payload `61 00 00 00 0a 00`. It sent 1637 messages of 20 distinct
sequence ids in 90 seconds, the earlier ids more often than the later ones, which is one
retransmit train per unacknowledged sequence: nothing of ours has ever acked this protocol.

`reliable.py` is the SAME idea for Pia 6.32 (the GBA app) and its header is a different shape; do
not reach for one while reading the other. This module is the 5.29-5.43 wrapper, which the wiki
"Reliable Sliding Window" describes and BDSP's own code corrects in two places.

THE MESSAGE HEADER (parse main.bin 0x0159756c, build 0x01597364, size 0x015977f0):

    0x0  1  flags                      the FLAG_* bits below
    0x1  1  stream id                  AND, on a RESET, a COUNTER - see below
    0x2  2  payload size, big-endian   refused at 0x5a1 or more
    0x4  2  sequence id, big-endian
    0x6  2  lowest sequence id pending ack, big-endian
    0x8  1  number of destination bits (N)   refused at 0x20 or more
    0x9  4 * ceil(N / 32)  destination bitmap words, big-endian
            payload

**The header is 9 or 13 bytes, not the 8 or 12 the wiki says** - the wiki's own field list runs
through offset 0x8, and `GetSize` is `9 + (((N + 0x1f) >> 3) & 0x3c)`. And N must be **strictly
less than 32**, where the wiki says "not higher than 32": both the parser and the builder branch on
`cmp #0x20 / b.lo`. Against a published reference, the binary wins.

THE ACK PAYLOAD, sent when FLAG_APPLICATION_DATA is clear (parse 0x01596fa4, build 0x0159718c,
size 0x0159716c = `2 + 21 * n`):

    0x0  1  UNKNOWN - the byte at AckMessage + 8. Neither the constructor nor the one-entry
            builder writes it, and no capture holds an ack, so it is not read yet
    0x1  1  entry count n, refused at 0x21 or more
    0x2  21 * n  entries, each:
            0x0  1   stream id
            0x1  2   acknowledgement id, big-endian
            0x3  2   the window's own field 0x50, big-endian - it is filed per station at
                     protocol + 0x7b8 and is HYPOTHESIS: the sender's lowest pending id
            0x5  16  acknowledgement mask, sent as stored

The wiki's "Ack Data" is the 5.18 shape (19-byte entries, always 32 of them). 5.29-5.43 carries an
explicit count and one more halfword per entry.

**THE BYTE AT 0x1 IS NOT ONLY A STREAM ID.** On a message carrying FLAG_RESET the handler
(main.bin 0x0159f9b4) reads it as a reset COUNTER and requires it to be exactly one more than the
value it holds for that station: `stream_id == record[0x1e]` is rejected outright at 0x0159fa24 and
`stream_id != record[0x1e] + 1` at 0x0159fa4c. A reset numbered 0 against a stored 0 is therefore
thrown away in silence, which is what five swept framings each did while the framing was
never the thing being measured. Before any of that the handler needs `record[0x1f]` non-zero, an
active-station flag we do not set.

**THE ACK, MEASURED OFF THE CONSOLE.** Sending the console application data made it answer,
and its answer is the shape no amount of reading the builder had settled:

    00 00 0017 ffff 0003 00   00 01   00 0002 0001  00 * 16

a header with **no flags at all**, stream 0, **sequence id 0xFFFF** - a control message carries no
sequence of its own - and the lowest id it is still waiting on; then the payload, whose first byte
is **0** and whose entry acknowledges `ack_id = highest received + 1` with the halfword before the
mask holding `ack_id - 1`. That is the reply to two application messages of ours, sequence 0 and 1.

`docs/bdsp_session.md` "The reliable protocol".
"""

import struct

PROTOCOL = 0x7C
VERSION = 3                       # the wiki pins version 3 to Pia 5.31-5.43
PORT = 0
MESSAGE_FLAGS = 0x01              # what the console itself sends on this protocol

HEADER_SIZE = 9                   # plus 4 bytes per bitmap word
MAX_PAYLOAD = 0x5A0               # 0x0159756c refuses 0x5a1 and above
MAX_DESTINATION_BITS = 31         # `cmp #0x20 / b.lo`, so 31 and not the wiki's 32
MAX_ACK_ENTRIES = 32              # `cmp #0x21 / b.lo`
ACK_ENTRY_SIZE = 21               # 0x0159716c: n * 0x14 + n + 2

FLAG_APPLICATION_DATA = 0x01
FLAG_MESSAGE_START = 0x02
FLAG_MESSAGE_END = 0x04
FLAG_IS_INITIALIZED = 0x08
FLAG_ZLIB = 0x10
FLAG_RESET = 0x20
FLAG_RESET_ACK = 0x40
FLAG_NAMES = [(FLAG_APPLICATION_DATA, "APPLICATION_DATA"), (FLAG_MESSAGE_START, "START"),
              (FLAG_MESSAGE_END, "END"), (FLAG_IS_INITIALIZED, "INITIALIZED"),
              (FLAG_ZLIB, "ZLIB"), (FLAG_RESET, "RESET"), (FLAG_RESET_ACK, "RESET_ACK")]


def flag_names(flags):
    """-> the set bits, named, so a log line says what a message is rather than a number."""
    out = [name for bit, name in FLAG_NAMES if flags & bit]
    rest = flags & ~sum(bit for bit, _ in FLAG_NAMES)
    if rest:
        out.append(f"unknown {rest:#04x}")
    return out


def header_size(destination_bits):
    """9, or 13 once there is a bitmap. The console's own arithmetic, kept as its own."""
    return HEADER_SIZE + (((destination_bits + 0x1F) >> 3) & 0x3C)


def build_header(flags, sequence_id, payload_size, lowest_pending=0, stream_id=0,
                 destination_bits=0, bitmap=()):
    if destination_bits > MAX_DESTINATION_BITS:
        raise ValueError(f"{destination_bits} destination bits; the console refuses 0x20 and above")
    if payload_size > MAX_PAYLOAD:
        raise ValueError(f"payload {payload_size}; the console refuses 0x5a1 and above")
    out = (bytes([flags & 0xFF, stream_id & 0xFF]) + struct.pack(">H", payload_size)
           + struct.pack(">H", sequence_id & 0xFFFF) + struct.pack(">H", lowest_pending & 0xFFFF)
           + bytes([destination_bits & 0xFF]))
    words = (header_size(destination_bits) - HEADER_SIZE) // 4
    bitmap = list(bitmap) + [0] * (words - len(bitmap))
    return out + b"".join(struct.pack(">I", w & 0xFFFFFFFF) for w in bitmap[:words])


def parse(data):
    """-> dict, one reliable message off the wire, header and payload split."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"a reliable message is at least {HEADER_SIZE} bytes, got {len(data)}")
    size = struct.unpack_from(">H", data, 2)[0]
    if size > MAX_PAYLOAD:
        raise ValueError(f"payload size {size:#x} is 0x5a1 or more, which the console refuses")
    bits = data[8]
    if bits > MAX_DESTINATION_BITS:
        raise ValueError(f"{bits} destination bits is 0x20 or more, which the console refuses")
    head = header_size(bits)
    out = {
        "flags": data[0],
        "flag_names": flag_names(data[0]),
        "stream_id": data[1],
        "payload_size": size,
        "sequence_id": struct.unpack_from(">H", data, 4)[0],
        "lowest_pending": struct.unpack_from(">H", data, 6)[0],
        "destination_bits": bits,
        "bitmap": [struct.unpack_from(">I", data, HEADER_SIZE + 4 * i)[0]
                   for i in range((head - HEADER_SIZE) // 4)],
        "header_size": head,
    }
    out["payload"] = data[head:head + size]
    out["truncated"] = len(out["payload"]) < size
    out["is_ack"] = not (data[0] & FLAG_APPLICATION_DATA)
    return out


def parse_ack_payload(data):
    """-> dict, the bulk acknowledgement a message with no APPLICATION_DATA flag carries."""
    if len(data) < 2:
        raise ValueError(f"an ack payload is at least two bytes, got {len(data)}")
    count = data[1]
    if count > MAX_ACK_ENTRIES:
        raise ValueError(f"{count} ack entries is 0x21 or more, which the console refuses")
    entries, off = [], 2
    for _ in range(count):
        if off + ACK_ENTRY_SIZE > len(data):
            break
        entries.append({"stream_id": data[off],
                        "ack_id": struct.unpack_from(">H", data, off + 1)[0],
                        "field_0x50": struct.unpack_from(">H", data, off + 3)[0],
                        "mask": data[off + 5:off + 21]})
        off += ACK_ENTRY_SIZE
    return {"unknown0": data[0], "count": count, "entries": entries}


ACK_SEQUENCE = 0xFFFF             # a control message has no sequence of its own


def contiguous_through(sequence_ids, start=0):
    """-> the highest sequence id such that every id from `start` + 1 up to it has been received.

    A bulk ack names ONE id and a mask; the id is one past the end of the contiguous run, so a gap
    stops the run rather than being skipped over. Keeping this separate from the receive loop is
    what lets a capture replay it: 1637 captured messages go through it offline.
    """
    have = set(sequence_ids)
    through = start
    while through + 1 in have:
        through += 1
    return through


def build_ack_message(ack_id, stream_id=0, field_0x50=None, mask=b"", lowest_pending=None,
                      unknown0=0):
    """A whole bulk-acknowledgement message, header and payload, as the console sends it.

    `ack_id` is one MORE than the highest sequence id received - the console answered our sequence 0
    and 1 with an ack id of 2. The halfword before the mask carried `ack_id - 1` in that same
    message, so it defaults here to exactly that.
    """
    if field_0x50 is None:
        field_0x50 = max(0, ack_id - 1)
    body = build_ack_payload([{"stream_id": stream_id, "ack_id": ack_id,
                               "field_0x50": field_0x50, "mask": mask}], unknown0=unknown0)
    return build_header(0, ACK_SEQUENCE, len(body),
                        lowest_pending=ack_id if lowest_pending is None else lowest_pending,
                        stream_id=stream_id) + body


def build_ack_payload(entries, unknown0=0):
    """The bulk acknowledgement, 2 + 21 per entry. `unknown0` is the byte nothing has read yet.

    NOT YET SENT TO A CONSOLE. The shape is the serialiser's, byte for byte; what the first byte
    should hold is not known, which is exactly the kind of one-byte unknown a sweep settles.
    """
    if len(entries) > MAX_ACK_ENTRIES:
        raise ValueError(f"{len(entries)} ack entries; the console refuses 0x21 and above")
    out = bytes([unknown0 & 0xFF, len(entries)])
    for e in entries:
        mask = bytes(e.get("mask", b"")).ljust(16, b"\0")[:16]
        out += (bytes([e.get("stream_id", 0) & 0xFF])
                + struct.pack(">H", e["ack_id"] & 0xFFFF)
                + struct.pack(">H", e.get("field_0x50", 0) & 0xFFFF) + mask)
    return out
