"""Pia version 4 packet header and message framing - the wire format Sword/Shield speaks.

Read off the game's own deserializer at `main` 0x1774730 (session 54) and then MEASURED against 484
packets a retail Sword broadcast at us while we held a seat in its LDN session (session 55, sw01).
Every one of them authenticated.

    off  size  field                            parser evidence
    0x00  4    magic 0x32AB9864, big-endian     the same magic as 5.27-6.32
    0x04  1    0x80 (encrypted) | version (4)   three validators check (byte & 0x7f) == 4
    0x05  1    a station index
    0x06  2    big-endian halfword              a session or protocol id
    0x08  8    AES-GCM nonce, a counter
    0x10  16   AES-GCM tag, NOT truncated
    0x20  ...  ciphertext

WHAT VERSION 4 SHARES WITH 5.27-5.45, and it is nearly everything that matters: the session key is
`pia5.ldn_session_key` over the advertisement's session parameter, and the IV is `pia5.gcm_iv` -
three bytes of the station CRC, one byte of source id, then the header's own eight-byte nonce. The
version byte and the header layout are the whole difference, which is why this module is fifty
lines and not a second protocol stack.

THE MESSAGE FRAMING IS 5.27's, PLUS ONE FIELD. A message header is presence-flagged the same way,
and version 4 carries an extra eight-byte source id after the destination, so the header is 24
bytes rather than 16. FACT: 24 + size, padded to a multiple of four, accounts for all 484 payloads
exactly, with nothing but 0xFF after it. DEDUCTION: which presence bit owns that field - every
packet in the capture carries the same presence byte (0x7f), so the capture cannot separate them.
"""
import struct

from pokeldn.ldn.pia5 import gcm_iv, ldn_session_key, parse_messages as parse_messages5

MAGIC = 0x32AB9864
VERSION = 4
HEADER_SIZE = 0x20
NONCE_OFF, TAG_OFF, CT_OFF = 0x08, 0x10, 0x20
TAG_SIZE = 16                      # 5.27-5.45 truncates to eight; version 4 does not
FLAG_ENCRYPTED = 0x80
MESSAGE_HEADER_SIZE = 24

__all__ = ["MAGIC", "VERSION", "HEADER_SIZE", "TAG_SIZE", "MESSAGE_HEADER_SIZE", "PiaHeader4",
           "ciphertext", "is_pia4", "gcm_iv", "ldn_session_key", "parse_messages5"]


class PiaHeader4:
    __slots__ = ("station", "session_id", "nonce8", "tag", "encrypted", "version")

    def __init__(self, station=0, session_id=0, nonce8=b"\0" * 8, tag=b"\0" * TAG_SIZE,
                 encrypted=True, version=VERSION):
        self.station, self.session_id = station, session_id
        self.nonce8, self.tag = bytes(nonce8), bytes(tag)
        self.encrypted, self.version = encrypted, version

    @classmethod
    def parse(cls, data):
        if len(data) < HEADER_SIZE:
            raise ValueError(f"short packet: {len(data)} bytes")
        magic, vb, station, session_id = struct.unpack_from(">IBBH", data, 0)
        if magic != MAGIC:
            raise ValueError(f"not Pia: magic {magic:#010x}")
        return cls(station, session_id, data[NONCE_OFF:TAG_OFF], data[TAG_OFF:CT_OFF],
                   bool(vb & FLAG_ENCRYPTED), vb & 0x7F)

    def pack(self):
        vb = (FLAG_ENCRYPTED if self.encrypted else 0) | (self.version & 0x7F)
        return (struct.pack(">IBBH", MAGIC, vb, self.station & 0xFF, self.session_id & 0xFFFF)
                + self.nonce8.ljust(8, b"\0")[:8] + self.tag.ljust(TAG_SIZE, b"\0")[:TAG_SIZE])

    def __repr__(self):
        return (f"PiaHeader4(v{self.version}{'E' if self.encrypted else ''} "
                f"station={self.station} session={self.session_id:#06x} "
                f"nonce={self.nonce8.hex()})")


def is_pia4(data):
    """-> True for a version-4 packet. The version byte is what separates it from BDSP's 9."""
    return (len(data) >= HEADER_SIZE and struct.unpack_from(">I", data, 0)[0] == MAGIC
            and (data[4] & 0x7F) == VERSION)


def ciphertext(data):
    """The encrypted body. Version 4 has no footer-size field, so this is simply the tail."""
    return data[CT_OFF:]


def parse_messages(plaintext):
    """Split a decrypted version-4 payload into messages.

    -> [(header_bytes, body)]. The header is 24 bytes and the body `size` bytes, big-endian at
    offset 2, with the message padded to a multiple of four - the arithmetic that accounts for all
    484 packets of sw01 exactly. The walk stops at 0xFF padding, the way 5.27's does.
    """
    out, off = [], 0
    while off + MESSAGE_HEADER_SIZE <= len(plaintext):
        if plaintext[off] in (0x00, 0xFF):
            break
        size = struct.unpack_from(">H", plaintext, off + 2)[0]
        end = off + MESSAGE_HEADER_SIZE + size
        if end > len(plaintext):
            break
        out.append((plaintext[off:off + MESSAGE_HEADER_SIZE],
                    plaintext[off + MESSAGE_HEADER_SIZE:end]))
        off = end + (-end % 4)
    return out
