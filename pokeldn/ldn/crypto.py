"""Pia AES-GCM transport crypto (NintendoClients wiki "Pia Protocol" / "Pia Game Keys", LDN 6.16-6.42):
    session_key = AES_ECB(game_key, ssid); net_id = CRC32(ssid[1:16])
    GCM nonce = (net_id XOR src_ip_be)(4) || header_nonce(8); AAD empty; tag = first 8 bytes of the GCM tag
29-byte header: [0:4] magic 32AB9864 [4] enc [5] flags [6:8] dst var-id BE [8:10] src var-id BE [10:12] pktid BE
[12] footer size (the 2-byte RECIPIENT station-id footer inside the payload) [13:21] header nonce [21:29] tag [29:] ct.
The decrypted payload may be a zstd frame (stock, no dict); decompress() peels it.
"""

import zlib
from dataclasses import dataclass
from Crypto.Cipher import AES

try:
    import zstandard as _zstd
except ImportError:                      # pragma: no cover
    _zstd = None

# The host's Pia messages are zstd-compressed; without this module decompress() no-ops and nothing parses.
HAVE_ZSTD = _zstd is not None

FRLG_GAME_KEY = bytes.fromhex("83ca7fab734c34633b10183526c1e85b")
PIA_MAGIC = bytes.fromhex("32ab9864")
ZSTD_MAGIC = bytes.fromhex("28b52ffd")
HDR = 29
NONCE_OFF, TAG_OFF, CT_OFF = 13, 21, 29

STATION_HOST = 0x7620
STATION_JOINER = 0xc493


@dataclass
class PiaHeader:
    dst: int = STATION_HOST
    src: int = STATION_JOINER
    pktid: int = 0
    nonce8: bytes = b"\x00" * 8
    enc: int = 0x90
    flags: int = 0x50
    footer: int = 2

    def pack(self):
        return (PIA_MAGIC
                + bytes([self.enc, self.flags])
                + self.dst.to_bytes(2, "big")
                + self.src.to_bytes(2, "big")
                + self.pktid.to_bytes(2, "big")
                + bytes([self.footer])
                + self.nonce8)

    @classmethod
    def unpack(cls, datagram):
        return cls(
            enc=datagram[4], flags=datagram[5],
            dst=int.from_bytes(datagram[6:8], "big"),
            src=int.from_bytes(datagram[8:10], "big"),
            pktid=int.from_bytes(datagram[10:12], "big"),
            footer=datagram[12], nonce8=datagram[NONCE_OFF:TAG_OFF],
        )


def ip_bytes(ip):
    if isinstance(ip, (bytes, bytearray)):
        return bytes(ip)
    return bytes(int(x) for x in ip.split("."))


def is_pia(datagram):
    return len(datagram) >= CT_OFF and datagram[:4] == PIA_MAGIC


def decompress(plaintext):
    """-> (app_bytes, was_compressed); the streaming decompressor stops at the frame end, so trailing 0xff padding is ignored."""
    if plaintext[:4] != ZSTD_MAGIC or _zstd is None:
        return plaintext, False
    try:
        return _zstd.ZstdDecompressor().decompressobj().decompress(plaintext), True
    except Exception:
        return plaintext, False


def _to_window_frame(frame, wd=0x18):
    """Rewrite the zstd frame header to the window-descriptor form the Switch emits (28b52ffd 00 18); only ever widens
    the declared window, so the frame decodes to the same bytes.
    """
    if frame[:4] != ZSTD_MAGIC:
        return frame
    fhd = frame[4]
    if (fhd & 0x03) or (fhd & 0x04):
        return frame
    fcs_flag = fhd >> 6
    if fhd & 0x20:
        blocks = frame[5 + ((1, 2, 4, 8)[fcs_flag]):]
    else:
        if frame[5] > wd:
            return frame
        blocks = frame[6 + ((0, 2, 4, 8)[fcs_flag]):]
    return ZSTD_MAGIC + bytes([0x00, wd]) + blocks


ZSTD_LEVEL = 4               # byte-identical to the console's frames; no other level is


def compress(app_bytes):
    """zstd frame matching the console byte-for-byte; the caller 0xFF-pads to a multiple of 16 before encrypting."""
    if _zstd is None:
        raise RuntimeError("zstandard module not available")
    return _to_window_frame(
        _zstd.ZstdCompressor(level=ZSTD_LEVEL, write_content_size=False).compress(app_bytes))


class PiaCrypto:
    def __init__(self, ssid, game_key=FRLG_GAME_KEY):
        self.ssid = bytes(ssid)
        self.session_key = AES.new(game_key, AES.MODE_ECB).encrypt(self.ssid)
        self.net_id = zlib.crc32(self.ssid[1:16]) & 0xFFFFFFFF

    def nonce(self, src_ip, header_nonce8):
        four = (self.net_id ^ int.from_bytes(ip_bytes(src_ip), "big")) & 0xFFFFFFFF
        return four.to_bytes(4, "big") + bytes(header_nonce8)

    def decrypt(self, datagram, src_ip):
        """-> raw plaintext (still zstd-wrapped if compressed) or None on auth failure; src_ip = the SENDER's LDN ip."""
        if not is_pia(datagram):
            return None
        nonce = self.nonce(src_ip, datagram[NONCE_OFF:TAG_OFF])
        tag = datagram[TAG_OFF:CT_OFF]
        ct = datagram[CT_OFF:]
        c = AES.new(self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=len(tag))
        try:
            return c.decrypt_and_verify(ct, tag)
        except ValueError:
            return None

    def encrypt(self, plaintext, src_ip, header):
        """header.nonce8 is the GCM header nonce: randomise it per packet for live, copy a captured one to replay."""
        nonce = self.nonce(src_ip, header.nonce8)
        c = AES.new(self.session_key, AES.MODE_GCM, nonce=nonce, mac_len=8)
        ct, tag = c.encrypt_and_digest(plaintext)
        return header.pack() + tag + ct
