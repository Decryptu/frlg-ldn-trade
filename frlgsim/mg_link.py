"""MysteryGiftLink framing [decomp:src/mystery_gift_link.c]: one message is a sequence of SendBlock
transfers - block 0 is {u16 ident; u16 crc; u16 size}, then <=252-byte chunks. size 0 means the whole
1024-byte buffer (RAM script, READY_END) and the CRC covers the declared size, padding included."""

from .mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINK_HEADER_SIZE, MG_LINK_MAX_CHUNK, crc16,
)


class MysteryGiftLinkError(Exception):
    """A condition that makes the console call ``LinkRfu_FatalError``."""


def build_header(ident, crc, size):
    return (ident.to_bytes(2, "little")
            + crc.to_bytes(2, "little")
            + size.to_bytes(2, "little"))


def parse_header(block):
    if len(block) < MG_LINK_HEADER_SIZE:
        raise MysteryGiftLinkError(
            f"header block is {len(block)} bytes, need {MG_LINK_HEADER_SIZE}")
    return (int.from_bytes(block[0:2], "little"),
            int.from_bytes(block[2:4], "little"),
            int.from_bytes(block[4:6], "little"))


def chunk_payload(buf):
    """As MGL_Send walks it: an exact multiple of 252 ends on a full chunk, never a trailing empty block."""
    return [buf[i:i + MG_LINK_MAX_CHUNK]
            for i in range(0, len(buf), MG_LINK_MAX_CHUNK)]


def build_message(ident, payload=b"", size=None):
    """size None = exactly this payload; 0 = the native full-buffer message (zero-padded to 1024, CRC over padding)."""
    payload = bytes(payload)
    if size is None:
        size = len(payload)
    if size == 0:
        size = MG_LINK_BUFFER_SIZE
    if not 0 < size <= MG_LINK_BUFFER_SIZE:
        raise MysteryGiftLinkError(
            f"message size {size} is outside 1..{MG_LINK_BUFFER_SIZE}")
    if len(payload) > size:
        raise MysteryGiftLinkError(
            f"payload of {len(payload)} bytes exceeds the declared size {size}")
    buf = payload.ljust(size, b"\x00")
    return [build_header(ident, crc16(buf), size)] + chunk_payload(buf)


class MysteryGiftLinkReceiver:
    """Blocks arrive padded to 12-byte RFU fragments, so every read is sliced to the declared size, never len(block)."""

    def __init__(self):
        self.expected_ident = None
        self.ident = None
        self.size = 0
        self.crc = 0
        self.buf = bytearray()
        self.blocks = 0
        self._in_header = True

    @property
    def active(self):
        return self.expected_ident is not None

    def expect(self, ident):
        self.expected_ident = ident
        self.ident = None
        self.size = 0
        self.crc = 0
        self.buf = bytearray()
        self.blocks = 0
        self._in_header = True

    def feed_block(self, block):
        block = bytes(block)
        self.blocks += 1
        if self._in_header:
            self._read_header(block)
            return None
        remaining = self.size - len(self.buf)
        take = min(remaining, MG_LINK_MAX_CHUNK)
        if len(block) < take:
            raise MysteryGiftLinkError(
                f"payload block is {len(block)} bytes, need {take}")
        self.buf += block[:take]
        if len(self.buf) < self.size:
            return None
        payload = bytes(self.buf)
        if crc16(payload) != self.crc:
            raise MysteryGiftLinkError(
                f"ident {self.ident} CRC mismatch: "
                f"header 0x{self.crc:04x}, computed 0x{crc16(payload):04x}")
        self.expected_ident = None
        return payload

    def _read_header(self, block):
        ident, crc, size = parse_header(block)
        # MGL_Receive checks size before ident; keep that order.
        if size > MG_LINK_BUFFER_SIZE:
            raise MysteryGiftLinkError(
                f"declared size {size} exceeds MG_LINK_BUFFER_SIZE")
        if self.expected_ident is not None and ident != self.expected_ident:
            raise MysteryGiftLinkError(
                f"expected ident {self.expected_ident}, received {ident}")
        if size == 0:
            # Stricter than MGL_Receive: InitSend maps 0 -> 1024, so a zero here is not a header at all.
            raise MysteryGiftLinkError("received header declares a zero size")
        self.ident = ident
        self.crc = crc
        self.size = size
        self._in_header = False
