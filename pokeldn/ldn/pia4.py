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
           "ciphertext", "is_pia4", "gcm_iv", "ldn_session_key", "parse_messages5",
           "ALL_FIELDS_PRESENT", "MESSAGE_FLAGS", "build_message", "parse_message_header",
           "MESSAGE_FIELDS", "message_header_size", "parse_packet",
           "pad_payload", "encrypt_payload", "decrypt_payload", "build_packet"]


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


# A MESSAGE HEADER IS NOT A FIXED 24 BYTES. The presence byte at [0] says which fields follow, in
# bit order, and the size is the arithmetic the library inlines at eighteen sites (session 56):
#
#     1 + (bit0: flags, 1) + (bit1: size, 2) + (bit2: protocol|port, 4)
#       + (bit3: destination, 8) + (bit4: source, 8)
#
# so 0x7F gives 24 and bits 0x20/0x40 own nothing. Every packet of sw01, sw02 and sw03 carried ONE
# message with every field present, which is why a fixed 24 held for three sessions.
#
# AND A FIELD THE PRESENCE BYTE OMITS IS INHERITED FROM THE PREVIOUS MESSAGE IN THE SAME PACKET,
# not defaulted and not implied by the remaining length. `0x01853050` is that rule bit by bit: it
# takes the newly parsed header and the previous one and, for each clear bit, copies flags at +9,
# size at +0xA, protocol|port at +0xC, destination at +0x10 and source at +0x18. `0x01852da0` is
# what saves the previous header before parsing the next. sw29 is the first capture with any of it:
# its 0x80 packets carry the same 42-byte body twice, port 0 then port 1, and the second message's
# header is FIVE bytes - `04 80 00 00 01`.
MESSAGE_FIELDS = ((0x01, 1, "flags"), (0x02, 2, "size"), (0x04, 4, "proto_port"),
                  (0x08, 8, "destination"), (0x10, 8, "source"))


def message_header_size(present):
    """-> the byte length of a message header with this presence byte."""
    return 1 + sum(width for bit, width, _ in MESSAGE_FIELDS if present & bit)


def parse_packet(plaintext):
    """Split a decrypted version-4 payload into messages, resolving inherited fields.

    -> [dict], each with the resolved `flags`, `size`, `protocol`, `port`, `destination`, `source`
    and `payload`, plus `present`, `header_size`, `at` and the set of names it `inherited`. A
    message is padded to a multiple of four.

    THE WALK STOPS AT 0xFF AND AT NOTHING ELSE. `0x01852da0` reads the presence byte and compares
    it against 0xFF alone; a presence byte of **0x00 is a legal one-byte header** that inherits
    every field, and stopping on it throws away real messages. sw29's reliable-window packets are
    where that shows: they carry three 0x7C messages, the second and third of them one byte of
    header each, and a walk that stops at 0x00 sees only the first and leaves 32 bytes of the
    plaintext unaccounted for.
    """
    out, off, prev = [], 0, None
    while off < len(plaintext):
        present = plaintext[off]
        if present == 0xFF:
            break
        if present == 0 and prev is None:
            break                             # nothing to inherit; not a shape the console sends
        size = message_header_size(present)
        if off + size > len(plaintext):
            break
        m = {"at": off, "present": present, "header_size": size, "inherited": set()}
        p = off + 1
        for bit, width, name in MESSAGE_FIELDS:
            if present & bit:
                m[name] = int.from_bytes(plaintext[p:p + width], "big")
                p += width
            elif prev is not None:
                m[name] = prev[name]
                m["inherited"].add(name)
            else:
                m[name] = 0                   # nothing to inherit from; the console never does this
                m["inherited"].add(name)
        m["protocol"], m["port"] = m["proto_port"] >> 24, m["proto_port"] & 0xFFFFFF
        end = p + m["size"]
        if end > len(plaintext):
            break
        m["header"] = plaintext[off:p]
        m["payload"] = plaintext[p:end]
        out.append(m)
        prev = m
        off = end + (-end % 4)
    return out


def parse_messages(plaintext):
    """-> [(header_bytes, body)], the raw header of each message and its body.

    Kept because it is what every caller and capture tool already speaks. `header_bytes` is the
    header AS SENT, so it is 24 bytes only when the message states every field; use `parse_packet`
    when the resolved values are what matter.
    """
    return [(m["header"], m["payload"]) for m in parse_packet(plaintext)]


# --- Building one. Session 56: the first version-4 packet OUT. ---------------------------------
#
# Every field below is MIRRORED from what a retail Sword broadcast at us, not chosen. sw01's 484
# packets all carry the same message header constants (`tests/test_pia4.py` asserts them), and
# `build_message` reproduces the console's own 24 bytes exactly when handed the console's own
# values - which is the only offline check available for a header we have never sent.
#
# The extra eight-byte field is the sender's STATION CONSTANT ID: the console's message header
# reads eb9b2220f1480000, which is `station_protocol.ldn_constant_id` over the MAC the scan
# recorded for it, and the same value the Local Protocol's own update session carries as
# `host_constant_id`. Two independent fields agreeing is what makes this a FACT rather than a guess
# about a field full of MAC-shaped bytes.
#
# AND THE TWO FIELDS DISAGREE ABOUT BYTE ORDER, which is `local_protocol`'s own trap seen from the
# other side: the Pia message header is BIG-endian, so the id is `>Q` here, while the Local
# Protocol's body is LITTLE-endian and its copy of the same id reads 000048f120229beb.

ALL_FIELDS_PRESENT = 0x7F         # what the console emits; bits above 0x08 add no field we can see
MESSAGE_FLAGS = 0x09              # the console's own, on every message in sw01
SOURCE_OFF = 16                   # inside the message header, after the eight-byte destination


def build_message(payload, protocol, source, port=0, message_flags=MESSAGE_FLAGS, destination=0):
    """One version-4 message, padded to four bytes - the shape sw01 measured.

    `source` is this station's constant id as an integer - `station_protocol.ldn_constant_id` over
    its MAC - big-endian like every other field of this header.
    """
    payload = bytes(payload)
    out = (bytes([ALL_FIELDS_PRESENT, message_flags & 0xFF]) + struct.pack(">H", len(payload))
           + bytes([protocol & 0xFF]) + (port & 0xFFFFFF).to_bytes(3, "big")
           + struct.pack(">Q", destination) + struct.pack(">Q", source))
    out += payload
    return out + b"\x00" * (-len(out) % 4)


def parse_message_header(header):
    """-> dict of the fields this header STATES, so a capture can be read field by field.

    A header that omits fields carries no values for them - what they resolve to depends on the
    message before it in the packet, which a lone header cannot know. `parse_packet` is what
    resolves them; anything absent here is simply missing from the dict.
    """
    present = header[0]
    if len(header) != message_header_size(present):
        raise ValueError(f"a header with presence {present:#04x} is "
                         f"{message_header_size(present)} bytes, this is {len(header)}")
    out, off = {"present": present}, 1
    for bit, width, name in MESSAGE_FIELDS:
        if present & bit:
            out[name] = int.from_bytes(header[off:off + width], "big")
            off += width
    if "proto_port" in out:
        out["protocol"], out["port"] = out["proto_port"] >> 24, out["proto_port"] & 0xFFFFFF
    return out


def pad_payload(plaintext):
    """0xFF-pad to a multiple of sixteen, exactly as 5.27 does - and as sw01 measures.

    The station announcement is 24 + 121 = 145 bytes, padded to 148 as a message and then to 160 as
    a packet, and 160 is what the ciphertext length is. So version 4 pads the same way even though
    GCM needs no block alignment.
    """
    return bytes(plaintext) + b"\xff" * (-len(plaintext) % 16)


def encrypt_payload(session_key, iv, plaintext):
    """-> (ciphertext, 16-byte tag). Version 4 keeps the WHOLE tag; 5.27-5.45 truncates to eight."""
    from Crypto.Cipher import AES

    return AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                   mac_len=TAG_SIZE).encrypt_and_digest(bytes(plaintext))


def decrypt_payload(session_key, iv, ct, tag):
    """-> plaintext, or None if the tag does not verify. Sixteen bytes of tag is the oracle."""
    from Crypto.Cipher import AES

    try:
        return AES.new(bytes(session_key), AES.MODE_GCM, nonce=bytes(iv),
                       mac_len=TAG_SIZE).decrypt_and_verify(bytes(ct), bytes(tag))
    except ValueError:
        return None


def build_packet(session_key, iv, plaintext, station=0, session_id=0, nonce8=b"\0" * 8):
    """A whole version-4 packet: header, ciphertext, sixteen-byte tag in the header.

    UNKNOWN, and the thing to sweep if the console ignores us: the byte at 0x05 and the halfword at
    0x06. The console sends 0 in both on every packet of sw01, so 0 is what we send first - but a
    field we have only ever seen one value of cannot be said to mean anything yet.
    """
    ct, tag = encrypt_payload(session_key, iv, pad_payload(plaintext))
    return PiaHeader4(station=station, session_id=session_id, nonce8=nonce8, tag=tag,
                      encrypted=True).pack() + ct
