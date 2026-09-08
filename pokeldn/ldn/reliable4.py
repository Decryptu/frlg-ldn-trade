"""Pia version 4's reliable sliding window - protocol 0x7C, and the ack shape that is NOT 5.29's.

`reliable5.py` is the 5.29-5.43 wrapper and its HEADER is version 4's header too: sw29 and sw30
between them put 221887 of a retail Sword's reliable messages through `reliable5.parse` without a
field out of place. Nothing in this module touches the header; it is the ACK PAYLOAD that moved,
and it moved BACKWARDS - version 4 carries the original fixed table that 5.29 replaced with a
counted list.

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
           "parse_broadcast_message",
           "build_ack_message"]


def build_ack_payload(ack_id, stream_id=0, mask=b"", slots=None):
    """The 0x260 bytes. `slots` is which of the 32 to fill; None fills them all.

    A slot that is not filled carries stream id 0xFF, which cannot match a real stream and so is
    ignored if the console reads it - the entry is inert rather than a second, wrong acknowledgement.
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
            out += b"\xff" + b"\0" * (ACK_ENTRY_SIZE - 1)
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


def build_ack_message(ack_id, stream_id=0, mask=b"", slots=None, lowest_pending=1):
    """Header and payload. `ack_id` is one MORE than the highest sequence id received.

    The header is `reliable5`'s unchanged - a control message carries no sequence of its own, so it
    goes out as 0xFFFF. `lowest_pending` is OUR send window and we have never sent application data
    on this protocol, so 1 (the next id we would use, and what the console itself sends while
    waiting on its first) and 0 are both readings of it.
    """
    body = build_ack_payload(ack_id, stream_id=stream_id, mask=mask, slots=slots)
    return reliable5.build_header(0, ACK_SEQUENCE, len(body), lowest_pending=lowest_pending,
                                  stream_id=stream_id) + body


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
    """-> dict. One decompressed protocol-0x80 message: the header, its destinations, its payload.

    THE CONSOLE'S OWN ACK IS IN HERE, and it is the independent confirmation of `build_ack_payload`:
    all 32 slots filled, every one stream 0 with the same ack id and a zero mask, which is exactly
    what `slots=None` builds. It had been on the wire since sw29, unreadable because nothing
    decompressed it.
    """
    if len(data) < BROADCAST_HEADER:
        raise ValueError(f"a broadcast reliable message is at least {BROADCAST_HEADER} bytes")
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
    out["is_ack"] = not (data[0] & reliable5.FLAG_APPLICATION_DATA)
    return out
