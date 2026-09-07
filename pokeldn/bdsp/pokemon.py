"""A BDSP Pokemon on the wire: the 328-byte PB8 a `NetTradePokeData` carries.

The console handed one over in sp82 - a Zubat the player picked out of their own boxes - and the
whole format is the Gen 6+ one, unchanged since XY:

    0x00  u32  encryption constant, in the clear. It seeds both the cipher and the block order
    0x04  u16  sanity, 0 for a stored Pokemon
    0x06  u16  checksum, in the clear
    0x08       four 80-byte blocks, encrypted and permuted

An LCG (`seed = seed * 0x41C64E6D + 0x6073`, high half of each step) XORs every 16-bit word from
0x08 to the end, and the four blocks are then permuted by `(EC >> 13) & 31` into one of the 24
orderings of four things.

THE CHECKSUM IS WHAT MAKES THIS SAFE TO BUILD. It is stored in the clear and is the 16-bit sum of
the DECRYPTED body, so a decryption that is wrong in any way - key, order, offset, length - cannot
produce a match, and a Pokemon we assemble ourselves is verified by decoding it back before it ever
reaches a console. `docs/bdsp.md`.

SIZE_STORED is 328 and that is exactly what the message carried, so a trade sends the stored form
and not the party form (which is longer and holds the battle stats).
"""
import struct

SIZE_STORED = 328
BLOCK_SIZE = 80
HEADER_SIZE = 8

# the 24 orderings of four blocks, indexed by (EC >> 13) & 31
BLOCK_ORDER = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2), (0, 2, 3, 1), (0, 3, 2, 1),
    (1, 0, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2), (2, 3, 0, 1), (3, 2, 0, 1),
    (1, 2, 3, 0), (1, 3, 2, 0), (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
)

# offsets into the DECRYPTED, UNSHUFFLED body. Only what sp82 confirmed against its own two
# messages is named here; the rest of the 328 bytes is left alone rather than guessed at.
OFF_SPECIES = 0x08
OFF_HELD_ITEM = 0x0A
OFF_TID = 0x0C
OFF_SID = 0x0E
OFF_EXPERIENCE = 0x10
OFF_ABILITY = 0x14
OFF_PID = 0x1C
OFF_NATURE = 0x20
OFF_FORM = 0x24
OFF_EVS = 0x26
OFF_NICKNAME = 0x58
OFF_IVS = 0x8C
OFF_OT_NAME = 0xF8
NAME_LENGTH = 26                      # 13 UTF-16LE code units, null terminated


def _crypt(data, seed):
    """XOR every 16-bit word from 0x08 with the LCG stream. Its own inverse."""
    out = bytearray(data)
    for i in range(HEADER_SIZE, len(out), 2):
        seed = (seed * 0x41C64E6D + 0x00006073) & 0xFFFFFFFF
        struct.pack_into("<H", out, i,
                         struct.unpack_from("<H", out, i)[0] ^ ((seed >> 16) & 0xFFFF))
    return bytes(out)


def _permute(data, order):
    out = bytearray(data[:HEADER_SIZE])
    for src in order:
        out += data[HEADER_SIZE + src * BLOCK_SIZE: HEADER_SIZE + (src + 1) * BLOCK_SIZE]
    return bytes(out)


def checksum(plain):
    """The 16-bit sum of the decrypted body - what the header carries in the clear."""
    n = (len(plain) - HEADER_SIZE) // 2
    return sum(struct.unpack_from(f"<{n}H", plain, HEADER_SIZE)) & 0xFFFF


def decrypt(raw):
    """-> the plain, unshuffled 328 bytes. Raises if the checksum does not agree."""
    if len(raw) != SIZE_STORED:
        raise ValueError(f"{len(raw)} bytes, expected {SIZE_STORED}")
    ec = struct.unpack_from("<I", raw, 0)[0]
    order = BLOCK_ORDER[(ec >> 13) & 31]
    # `order` says where each block went, so reading them back inverts it
    inverse = tuple(order.index(block) for block in range(4))
    plain = _permute(_crypt(raw, ec), inverse)
    want = struct.unpack_from("<H", raw, 6)[0]
    got = checksum(plain)
    if got != want:
        raise ValueError(f"checksum {got:#06x}, header says {want:#06x} - not a valid PB8")
    return plain


def encrypt(plain):
    """-> the 328 bytes to put on the wire, with the checksum written from the body itself."""
    if len(plain) != SIZE_STORED:
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED}")
    body = bytearray(plain)
    struct.pack_into("<H", body, 6, checksum(body))
    ec = struct.unpack_from("<I", body, 0)[0]
    return _crypt(_permute(bytes(body), BLOCK_ORDER[(ec >> 13) & 31]), ec)


def _text(plain, offset):
    return plain[offset:offset + NAME_LENGTH].decode("utf-16-le", "replace").split("\x00")[0]


def read(raw):
    """-> what a received Pokemon says about itself. Only the fields sp82 confirmed."""
    plain = decrypt(raw)
    u16 = lambda o: struct.unpack_from("<H", plain, o)[0]
    ivs = struct.unpack_from("<I", plain, OFF_IVS)[0]
    return {
        "species": u16(OFF_SPECIES),
        "held_item": u16(OFF_HELD_ITEM),
        "trainer_id": u16(OFF_TID),
        "secret_id": u16(OFF_SID),
        "experience": struct.unpack_from("<I", plain, OFF_EXPERIENCE)[0],
        "ability": u16(OFF_ABILITY),
        "pid": struct.unpack_from("<I", plain, OFF_PID)[0],
        "nature": plain[OFF_NATURE],
        "form": u16(OFF_FORM),
        "evs": tuple(plain[OFF_EVS:OFF_EVS + 6]),
        "ivs": tuple((ivs >> s) & 31 for s in (0, 5, 10, 15, 20, 25)),
        "nickname": _text(plain, OFF_NICKNAME),
        "ot_name": _text(plain, OFF_OT_NAME),
    }


def build_from(template_raw, **fields):
    """-> an encrypted PB8 made by editing a REAL one.

    328 bytes hold far more than the dozen fields sp82 identified, and the rest is not zero on a
    console's own Pokemon - move counts, met data, ribbons, the language byte, handler records.
    Assembling one from nothing would mean inventing every byte this project has not read, so a
    Pokemon we send is a Pokemon the console sent us with named fields changed. Every unknown byte
    is then a real one, from a real save, in a slot the game itself put it in.

    The checksum is rewritten from the edited body by `encrypt`, so a template edit cannot leave an
    inconsistent Pokemon behind - and `read` on the result is the check that it did what was asked.

        species, held_item, trainer_id, secret_id, experience, ability, pid,
        nature, form, evs (6), ivs (6), nickname, ot_name, encryption_constant
    """
    plain = bytearray(decrypt(template_raw))
    u16 = lambda o, v: struct.pack_into("<H", plain, o, v & 0xFFFF)
    u32 = lambda o, v: struct.pack_into("<I", plain, o, v & 0xFFFFFFFF)

    def text(offset, value):
        encoded = value.encode("utf-16-le")
        if len(encoded) + 2 > NAME_LENGTH:
            raise ValueError(f"{value!r} is too long for a {NAME_LENGTH}-byte name field")
        plain[offset:offset + NAME_LENGTH] = encoded.ljust(NAME_LENGTH, b"\x00")

    for key, value in fields.items():
        if key == "species":
            u16(OFF_SPECIES, value)
        elif key == "held_item":
            u16(OFF_HELD_ITEM, value)
        elif key == "trainer_id":
            u16(OFF_TID, value)
        elif key == "secret_id":
            u16(OFF_SID, value)
        elif key == "experience":
            u32(OFF_EXPERIENCE, value)
        elif key == "ability":
            u16(OFF_ABILITY, value)
        elif key == "pid":
            u32(OFF_PID, value)
        elif key == "encryption_constant":
            u32(0x00, value)
        elif key == "nature":
            plain[OFF_NATURE] = value & 0xFF
        elif key == "form":
            u16(OFF_FORM, value)
        elif key == "evs":
            plain[OFF_EVS:OFF_EVS + 6] = bytes(value)
        elif key == "ivs":
            packed = 0
            for shift, iv in zip((0, 5, 10, 15, 20, 25), value):
                packed |= (iv & 31) << shift
            # the top bits of this word are not IVs and are left exactly as the template had them
            old = struct.unpack_from("<I", plain, OFF_IVS)[0]
            u32(OFF_IVS, (old & ~0x3FFFFFFF) | packed)
        elif key == "nickname":
            text(OFF_NICKNAME, value)
        elif key == "ot_name":
            text(OFF_OT_NAME, value)
        else:
            raise ValueError(f"unknown field {key!r}")
    return encrypt(bytes(plain))
