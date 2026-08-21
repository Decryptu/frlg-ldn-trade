"""MysteryGiftLink message framing [src/mystery_gift_link.c].

One logical Mystery Gift message is carried as a *sequence of link.c SendBlock
transfers*, not as a single block:

    block 0     6-byte ``struct SendRecvHeader {u16 ident; u16 crc; u16 size}``
    block 1..n  the payload in <=252-byte chunks (``MG_LINK_MAX_CHUNK``)

``MGL_Send`` and ``MGL_Receive`` step one block per call, resetting the
block-received flag between each, so the two sides stay in lockstep without any
explicit acknowledgement in the payload.

Two size rules from ``MysteryGiftLink_InitSend`` [mystery_gift_link.c:49] are
easy to get wrong and are modelled exactly here:

* ``size == 0`` means "the whole 1024-byte buffer", not "empty".  Both
  ``MG_LINKID_RAM_SCRIPT`` (the server never sets ``ramScriptSize``) and
  ``MG_LINKID_READY_END`` (``CLI_SEND_READY_END`` passes 0) therefore travel as
  1024-byte messages whose tail is buffer padding.
* the CRC covers the *declared size*, padding included - not just the
  meaningful prefix.

The receiver mirrors ``MGL_Receive``: a size above ``MG_LINK_BUFFER_SIZE``, an
unexpected ident, or a final CRC mismatch is what makes the console call
``LinkRfu_FatalError``, so each maps to :class:`MysteryGiftLinkError` here
rather than being silently tolerated.
"""

from .mystery_gift import (
    MG_LINK_BUFFER_SIZE, MG_LINK_HEADER_SIZE, MG_LINK_MAX_CHUNK, crc16,
)


class MysteryGiftLinkError(Exception):
    """A condition that makes the console call ``LinkRfu_FatalError``."""


def build_header(ident, crc, size):
    """Pack ``struct SendRecvHeader`` (little-endian, as the GBA stores it)."""
    return (ident.to_bytes(2, "little")
            + crc.to_bytes(2, "little")
            + size.to_bytes(2, "little"))


def parse_header(block):
    """Return ``(ident, crc, size)`` from the first six bytes of a header block."""
    if len(block) < MG_LINK_HEADER_SIZE:
        raise MysteryGiftLinkError(
            f"header block is {len(block)} bytes, need {MG_LINK_HEADER_SIZE}")
    return (int.from_bytes(block[0:2], "little"),
            int.from_bytes(block[2:4], "little"),
            int.from_bytes(block[4:6], "little"))


def chunk_payload(buf):
    """Split a declared-size payload the way ``MGL_Send`` walks it.

    ``MGL_Send`` sends 252 bytes while more than 252 remain and the remainder
    otherwise, so an exact multiple of 252 ends on a full final chunk and never
    emits a trailing empty block.
    """
    return [buf[i:i + MG_LINK_MAX_CHUNK]
            for i in range(0, len(buf), MG_LINK_MAX_CHUNK)]


def build_message(ident, payload=b"", size=None):
    """Return the ordered blocks for one message: ``[header, chunk, ...]``.

    ``size`` is the value handed to ``MysteryGiftLink_InitSend``. ``None`` means
    "exactly this payload"; ``0`` reproduces the native full-buffer messages
    (RAM script, READY_END). The payload is zero-padded up to the declared size,
    and the CRC is taken over the padded buffer.
    """
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
    """Reassemble one message at a time, exactly as ``MGL_Receive`` does.

    ``expect(ident)`` mirrors ``MysteryGiftLink_InitRecv``.  Feed each completed
    SendBlock to :meth:`feed_block`; it returns the payload once the final chunk
    passes the CRC, and ``None`` while more blocks are needed.

    Blocks arrive from the RFU layer padded out to a multiple of the 12-byte
    fragment size, so every read here is sliced to the length the header
    declared rather than to ``len(block)``.
    """

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
        # MGL_Receive checks size before ident; keep the same order so an
        # oversized message reports the size fault it would fault on natively.
        if size > MG_LINK_BUFFER_SIZE:
            raise MysteryGiftLinkError(
                f"declared size {size} exceeds MG_LINK_BUFFER_SIZE")
        if self.expected_ident is not None and ident != self.expected_ident:
            raise MysteryGiftLinkError(
                f"expected ident {self.expected_ident}, received {ident}")
        if size == 0:
            # Stricter than MGL_Receive, which would accept this and CRC zero
            # bytes. Unreachable in practice because InitSend maps 0 -> 1024, so
            # a zero here means the header is not a header at all.
            raise MysteryGiftLinkError("received header declares a zero size")
        self.ident = ident
        self.crc = crc
        self.size = size
        self._in_header = False
