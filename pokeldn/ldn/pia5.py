"""Pia 5.27-5.45 packet header - the wire format BDSP speaks.

This is NOT the format `pia_connect.py` speaks. That module targets Pia 6.32+ (header 0x1D, 2-byte
variable ids); BDSP advertises protocol version 9, which the NintendoClients wiki places in the
5.27-5.45 band, and every field below was read off the console's own parser at main.bin 0x01681ee4
(session 43, sp8/sp9) rather than taken from the wiki:

    off  size  field                         parser evidence
    0x00  4    magic 0x32AB9864, big-endian  ldr w8,[x1]; rev w8; str w8,[x0,#8]
    0x04  1    0x80 (encrypted) | version    ldrb -> obj+0xc, and (b & 0x7f) == 9 is checked
    0x05  4    destination variable id, BE   ldur w8,[x1,#5]; rev; -> obj+0x10
    0x09  4    source variable id, BE        ldur w8,[x1,#9]; rev; -> obj+0x14
    0x0d  2    packet id, BE                 ldurh w8,[x1,#0xd]; rev; lsr #16 -> obj+0x18
    0x0f  1    footer size                   ldrb -> obj+0x1a
    0x10  8    AES-GCM nonce                 copied byte by byte to obj+0x1b
    0x18  8    AES-GCM tag (truncated)       copied byte by byte to obj+0x23
    0x20  ...  ciphertext (0xFF-padded to a multiple of 16 before encryption)

The 4-byte variable ids are the visible difference from 6.32, which uses 2. `rev` on three fields is
why the header is big-endian on the wire while the struct is not.
"""
import struct

MAGIC = 0x32AB9864
VERSION = 9
HEADER_SIZE = 0x20
NONCE_OFF, TAG_OFF, CT_OFF = 0x10, 0x18, 0x20
FLAG_ENCRYPTED = 0x80


class PiaHeader5:
    __slots__ = ("dst_var", "src_var", "packet_id", "footer_size", "nonce8", "tag",
                 "encrypted", "version")

    def __init__(self, dst_var=0, src_var=0, packet_id=0, footer_size=0,
                 nonce8=b"\0" * 8, tag=b"\0" * 8, encrypted=True, version=VERSION):
        self.dst_var, self.src_var = dst_var, src_var
        self.packet_id, self.footer_size = packet_id, footer_size
        self.nonce8, self.tag = bytes(nonce8), bytes(tag)
        self.encrypted, self.version = encrypted, version

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_SIZE:
            raise ValueError(f"short packet: {len(data)} bytes")
        magic, vb = struct.unpack_from(">IB", data, 0)
        if magic != MAGIC:
            raise ValueError(f"not Pia: magic {magic:#010x}")
        dst, src = struct.unpack_from(">I", data, 5)[0], struct.unpack_from(">I", data, 9)[0]
        pid = struct.unpack_from(">H", data, 0x0d)[0]
        return cls(dst, src, pid, data[0x0f], data[NONCE_OFF:TAG_OFF], data[TAG_OFF:CT_OFF],
                   bool(vb & FLAG_ENCRYPTED), vb & 0x7F)

    def pack(self):
        vb = (FLAG_ENCRYPTED if self.encrypted else 0) | (self.version & 0x7F)
        return (struct.pack(">IB", MAGIC, vb)
                + struct.pack(">I", self.dst_var) + struct.pack(">I", self.src_var)
                + struct.pack(">H", self.packet_id) + bytes([self.footer_size])
                + self.nonce8.ljust(8, b"\0")[:8] + self.tag.ljust(8, b"\0")[:8])

    def __repr__(self):
        return (f"PiaHeader5(v{self.version}{'E' if self.encrypted else ''} "
                f"dst={self.dst_var:#010x} src={self.src_var:#010x} "
                f"pid={self.packet_id} footer={self.footer_size} "
                f"nonce={self.nonce8.hex()})")


def ciphertext(data):
    return data[CT_OFF:]


def is_pia5(data):
    return len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
