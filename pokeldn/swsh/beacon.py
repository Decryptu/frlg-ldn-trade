"""The LDN advertise data Sword/Shield's BeaconCommunication core sends and reassembles: the frame,
the message split across advertisements, and the reassembly the console performs.

Wire advertise data is 0x180 bytes: a 0x18 Pia header, then a 0x168 body. The body is a u16
CRC-16/ARC at +0 over body[2:0x168] (init 0, no final xor), a 12-bit network id at +2 (0xD70 on
every screen), a zero byte, and the application payload at +5, at most 0x163 bytes. A type-1
payload carries a ten-byte message header and up to 300 bytes of one fragment; the console sizes
its buffer from the header's length, copies 300 bytes per fragment except the last, and checks a
CRC-16/ARC over the reassembled message before handing it to the importer. docs/swsh_gift.md, "The
beacon body frame" through "The message checksum".
Trap: the Pia header is outside the body checksum but a retail console lists nothing without it;
`pia_header()` is what goes there."""
import os
import struct

ADVERTISE_LEN = 0x180
PIA_HEADER_LEN = 0x18
BODY_LEN = 0x168
PAYLOAD_OFF = 5
PAYLOAD_MAX = 0x163
NETWORK_ID = 0xD70
PAYLOAD_TYPE_GIFT = 1

FRAGMENT = 0x12C          # 300, the element size of the context vector at 0x010f7100
MESSAGE_HEADER = 10       # the ten bytes 0x010f7c60 skips
MAX_FRAGMENTS = 256       # the bitmap at context+0x58 is four qwords

_T = []
for _i in range(256):
    _c = _i
    for _ in range(8):
        _c = (_c >> 1) ^ 0xA001 if _c & 1 else _c >> 1
    _T.append(_c)


def crc16(data):
    """The core's checksum, 0x0065dcb0: CRC-16/ARC, init 0, no final xor."""
    crc = 0
    for b in data:
        crc = _T[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc


def body_crc(body):
    """What the game stores at body+0: crc16 over body[2:0x168]."""
    return crc16(body[2:BODY_LEN])


def pia_header():
    """The Pia header that opens the advertise data (docs/swsh_session.md): a random network id, a
    zero password CRC, system communication version 5, header size 0x18, a random session parameter
    and eight zero bytes. A console keeps one for a boot; a distributor keeps one for a run."""
    return (os.urandom(4) + bytes(4) + bytes((5, PIA_HEADER_LEN)) + bytes(2)
            + os.urandom(4) + bytes(8))


def split(blob):
    if len(blob) != ADVERTISE_LEN:
        raise ValueError(f"expected {ADVERTISE_LEN:#x} bytes, got {len(blob):#x}")
    return blob[:PIA_HEADER_LEN], blob[PIA_HEADER_LEN:]


def decode(blob):
    head, body = split(blob)
    stored = struct.unpack_from("<H", body, 0)[0]
    nid = body[2] | ((body[3] & 0xF) << 8)
    payload = body[PAYLOAD_OFF:]
    return {
        "header": head, "body": body, "stored_crc": stored, "computed_crc": body_crc(body),
        "network_id": nid, "spare_nibble": body[3] >> 4, "byte4": body[4], "payload": payload,
        "payload_used": len(payload.rstrip(b"\0")),
    }


def build(payload, header=None, network_id=NETWORK_ID, byte4=0):
    """One 0x180 advertise-data blob carrying `payload`. `header` is the 0x18 Pia header, or a
    whole 0x180 template whose header is reused; None builds a fresh one."""
    if len(payload) > PAYLOAD_MAX:
        raise ValueError(f"payload {len(payload)} > {PAYLOAD_MAX} (the memcpy bound at 0x6c2174)")
    if header is None:
        head = pia_header()
    elif len(header) == ADVERTISE_LEN:
        head = split(header)[0]
    else:
        head = bytes(header)
    if len(head) != PIA_HEADER_LEN:
        raise ValueError(f"header is {len(head)} bytes, want {PIA_HEADER_LEN}")
    body = bytearray(BODY_LEN)
    body[2] = network_id & 0xFF
    body[3] = (network_id >> 8) & 0xF
    body[4] = byte4
    body[PAYLOAD_OFF:PAYLOAD_OFF + len(payload)] = payload
    struct.pack_into("<H", body, 0, body_crc(body))
    return bytes(head) + bytes(body)


def fragments(data):
    """-> the 300-byte pieces the console stores by index; the last is zero-padded."""
    if len(data) % FRAGMENT:
        data = data + b"\0" * (FRAGMENT - len(data) % FRAGMENT)
    return [data[o:o + FRAGMENT] for o in range(0, len(data), FRAGMENT)]


def payload(index, count, piece, length, checksum):
    if not 0 <= index < count:
        raise ValueError(f"index {index} outside a count of {count}")
    p = bytearray(1 + MESSAGE_HEADER + FRAGMENT)
    p[0] = PAYLOAD_TYPE_GIFT               # the gift job's poll
    struct.pack_into("<I", p, 1, 0)           # header +0, zero or the poll returns at once
    struct.pack_into("<H", p, 5, length)      # header +4, total message length, sizes the buffer
    p[7] = count                              # header +6, total fragment count, sizes the bitmap
    p[8] = index                              # header +7, this fragment's index
    struct.pack_into("<H", p, 9, checksum)    # header +8, crc16 over the reassembled buffer
    p[11:11 + FRAGMENT] = piece
    assert len(p) <= PAYLOAD_MAX
    return bytes(p)


def build_message(data, header=None, checksum=None, count=None):
    """The advertise-data blobs that carry `data` (a whole number of records), one per fragment,
    sharing one Pia header. count defaults to ceil(len/300); a smaller count declares the full
    length but sends only the first pieces, and the console completes on the bitmap, not on the
    buffer being filled (0x010f7610)."""
    if not 1 <= len(data) <= 0xFFFF:
        raise ValueError(f"{len(data)} bytes does not fit the halfword length at header +4")
    pieces = fragments(data)
    if count is None:
        count = len(pieces)
    if not 1 <= count <= min(len(pieces), MAX_FRAGMENTS):
        raise ValueError(f"count {count} outside 1..{min(len(pieces), MAX_FRAGMENTS)}")
    if checksum is None:
        checksum = crc16(data)                 # 0x010f7680 refuses the message without this
    if header is None:
        header = pia_header()
    return [build(payload(i, count, pieces[i], len(data), checksum), header) for i in range(count)]


def reassemble(blobs):
    """What the console does: match the context, copy each fragment at index*300, the last clamped,
    then check the message checksum. Raises ValueError where the console would drop the message."""
    buf, count, length, key = None, None, None, None
    seen = set()
    for b in blobs:
        pl = decode(b)["payload"]
        if pl[0] != PAYLOAD_TYPE_GIFT:
            raise ValueError("payload type is not 1")
        status, ln = struct.unpack_from("<IH", pl, 1)
        n, idx = pl[7], pl[8]
        k = struct.unpack_from("<H", pl, 9)[0]
        if status:
            raise ValueError(f"status {status} is non-zero; the poll would return")
        if buf is None:
            key, count, length = (ln, n, k), n, ln
            buf = bytearray(length)
        elif (ln, n, k) != key:
            raise ValueError("fragment key does not match the context, a new one would be built")
        if idx >= count:
            raise ValueError(f"index {idx} not below the count {count}")
        if idx in seen:
            continue                                   # the bitmap drops a repeat
        take = FRAGMENT if idx + 1 != count else length - idx * FRAGMENT
        buf[idx * FRAGMENT:idx * FRAGMENT + take] = pl[11:11 + take]
        seen.add(idx)
    missing = [i for i in range(count) if i not in seen]
    if missing:
        raise ValueError(f"incomplete: missing fragments {missing}")
    got = crc16(buf)
    if got != key[2]:
        raise ValueError(f"checksum {got:#06x} does not match header +8 {key[2]:#06x}; "
                         "0x010f7680 would return null, the sink would be skipped "
                         "and the context erased")
    return bytes(buf)
