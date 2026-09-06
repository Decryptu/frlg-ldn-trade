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
import zlib

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


def gcm_iv(station_crc, src_variable_id, nonce8):
    """Pia 5.x's twelve-byte AES-GCM IV, as the stream objects build it.

    Read off `nn::pia::local::LdnOutputStream::vfunc3` (main.bin 0x16b39c4), and the same code is
    `LocalOutputStream` / `LanOutputStream` / `NexOutputStream` for the other three families:

        IV[0..3]  = u32be(crc32(network id || six bytes of the station record))
        IV[3]     = OVERWRITTEN with the low byte of the packet's source variable id
        IV[4..11] = the packet's eight-byte header nonce

    so only three bytes of the CRC reach the IV. Both of the other two inputs are on the wire, which
    is why a capture pins the IV down to those three bytes. docs/bdsp_pia.md "The GCM nonce".
    """
    if len(nonce8) != 8:
        raise ValueError(f"a Pia 5.x header nonce is eight bytes, not {len(nonce8)}")
    return (struct.pack(">I", station_crc & 0xFFFFFFFF)[:3]
            + bytes([src_variable_id & 0xFF])
            + bytes(nonce8))


def ldn_session_key(game_key, seed):
    """Pia 5.x's LDN session key: AES-128-ECB(game_key) over sixteen bytes of SEAD output.

    Read off BDSP's `nn::pia::local::LocalProtocol` at main.bin 0x016b14e8 (sp7): the seed is a u32
    stored at +0x5b0, the game key sixteen bytes at +0x5bc, and the plaintext four consecutive SEAD
    draws packed little-endian. This is the LDN family's derivation and ONLY the LDN family's - the
    HMAC-SHA256 one belongs to `nn::pia::lan::LanProtocol`, and applying it to an LDN capture cannot
    work. docs/bdsp_pia.md "The session key".
    """
    from Crypto.Cipher import AES

    from pokeldn.ldn.sead import Sead

    if len(game_key) != 16:
        raise ValueError(f"a Pia game key is sixteen bytes, not {len(game_key)}")
    return AES.new(bytes(game_key), AES.MODE_ECB).encrypt(Sead(seed=seed).bytes(16))


def ldn_game_key(crypto_key_data_seed, local_communication_version):
    """The Pia game key: the game's constant seed, with four bytes replaced by the version.

    Read off BDSP's own key construction (base_main.bin 0x1e3f404) and matching the NintendoClients
    wiki's "Pokemon Brilliant Diamond" page. The seed is what ships in the game's metadata; the key
    is what Pia is handed. So a PUBLISHED per-game key is a derived value for one game version, and
    the seed is the thing that does not move - which is exactly the distinction that cost session 45
    a day of sweeps, because the published key and the measured seed differ in precisely these four
    bytes and that reads as corruption until you know the rule.
    """
    key = bytearray(crypto_key_data_seed)
    if len(key) != 16:
        raise ValueError(f"a cryptoKeyDataSeed is sixteen bytes, not {len(key)}")
    v = local_communication_version
    key[1] = (v >> 8) & 0xFF
    key[3] = (v >> 4) & 0xFF
    key[7] = (v >> 1) & 0xFF
    key[12] = v & 0xFF
    return bytes(key)


def ldn_nonce_crc(network_id_le, source_mac):
    """The CRC32 whose first three bytes open the GCM IV: network id (LITTLE-endian) then the MAC.

    The source MAC is the field this project never guessed. Every offline sweep failed on it alone,
    with the key, the session key and the IV layout all already correct.
    """
    if len(network_id_le) != 4 or len(source_mac) != 6:
        raise ValueError("network id is four bytes little-endian, MAC is six")
    return zlib.crc32(bytes(network_id_le) + bytes(source_mac)) & 0xFFFFFFFF


class Pia5Message:
    """One message out of a decrypted Pia 5.27-5.45 packet."""

    __slots__ = ("message_flags", "protocol", "port", "destination", "payload")

    def __init__(self, message_flags, protocol, port, destination, payload):
        self.message_flags, self.protocol = message_flags, protocol
        self.port, self.destination, self.payload = port, destination, payload

    def __repr__(self):
        return (f"Pia5Message(proto={self.protocol} port={self.port} "
                f"flags={self.message_flags:#04x} dest={self.destination:#x} "
                f"len={len(self.payload)})")


def parse_messages(plaintext):
    """Split a decrypted payload into messages. Presence-flagged, and fields INHERIT.

    Pia 5.27-6.30: each message opens with a byte saying which header fields are present, and any
    field that is absent keeps the previous message's value - so a packet's second message is often
    a single byte of flags and a payload. Messages are padded to a multiple of four bytes, and the
    packet's tail is 0xFF padding, which is where the walk stops.

    Sizes and ids here are BIG-endian, like the packet header and unlike the wiki's note about the
    advertisement. docs/bdsp_pia.md "What the console is saying".
    """
    out, off = [], 0
    flags = size = protocol = port = 0
    destination = 0
    while off < len(plaintext):
        present = plaintext[off]
        if present == 0xFF or present == 0:
            break                                   # padding, or an empty flags byte
        off += 1
        if present & 1:
            if off >= len(plaintext):
                break
            flags = plaintext[off]; off += 1
        if present & 2:
            if off + 2 > len(plaintext):
                break
            size = struct.unpack_from(">H", plaintext, off)[0]; off += 2
        if present & 4:
            if off + 4 > len(plaintext):
                break
            protocol = plaintext[off]
            port = int.from_bytes(plaintext[off + 1:off + 4], "big"); off += 4
        if present & 8:
            if off + 8 > len(plaintext):
                break
            destination = struct.unpack_from(">Q", plaintext, off)[0]; off += 8
        if size > len(plaintext) - off:
            break
        out.append(Pia5Message(flags, protocol, port, destination, plaintext[off:off + size]))
        off += size
        off += -off % 4
    return out
