"""The Gen-8 Pokemon entity - the format BDSP's PB8 and Sword/Shield's PK8 BOTH are.

This is not a guess about two formats resembling each other. In PKHeX both classes are
`PKHeX.Core/PKM/Shared/G8PKM.cs` and neither overrides a single shared offset: `PB8.cs` adds one
field at 0x52 and `PK8.cs` adds one at 0x156, and that is the whole difference in the field map.
So the crypto, the block order and the ninety-odd offsets belong to neither game, and a copy of
them in each game package would be two records of one fact.

    0x00  u32  encryption constant, in the clear. It seeds both the cipher and the block order
    0x04  u16  sanity, 0 for a stored Pokemon
    0x06  u16  checksum, in the clear, over the decrypted body only
    0x08       four 80-byte blocks, encrypted and permuted   -> 0x148 = SIZE_STORED
    0x148      the party stats, encrypted and NOT permuted   -> 0x158 = SIZE_PARTY

An LCG (`seed = seed * 0x41C64E6D + 0x6073`, high half of each step) XORs every 16-bit word, and
the four blocks are then permuted by `(EC >> 13) & 31` into one of the 24 orderings of four things.

**THE PARTY STATS RESTART THE LCG.** `PokeCrypto.Decrypt8` calls `CryptArray` twice, both seeded
from the same encryption constant - the stream does not run on across 0x148. A party read
levels of 110 and 118 out of a tail that had never been decrypted at all.

**THE CHECKSUM DOES NOT CHECK THE BLOCK ORDER, AND THIS PROJECT HAS BEEN CAUGHT BY THAT TWICE.**
It is the 16-bit sum of the decrypted body, so a wrong LCG stream cannot survive it - but
permuting whole 80-byte blocks leaves a sum of 16-bit words untouched, because addition commutes.
An inverted order survives behind agreeing checksums (`bdsp/pokemon.py` tells that
one); `sw84_read.py` reintroduced the same inversion independently and called six
verifying checksums self-proving while reporting an empty slot that held a Dragonite. What catches
a wrong order is reading fields and seeing whether a Pokemon comes out.
"""
import struct

HEADER_SIZE = 8
BLOCK_SIZE = 0x50
BLOCK_COUNT = 4
SIZE_STORED = HEADER_SIZE + BLOCK_COUNT * BLOCK_SIZE       # 0x148, 328
SIZE_PARTY = SIZE_STORED + 0x10                            # 0x158, 344

# The orderings of four blocks, indexed by (EC >> 13) & 31.
#
# The index is 0..31 and there are only 24 orderings, so the table is 32 long with entries 24-31
# repeating 0-7. PKHeX's `PokeCrypto.BlockPosition` is written the same way ("duplicates of 0-7 to
# eliminate modulus (32 => 24)") and its first 24 rows match row for row.
#
# A 24-long table raises IndexError on any record whose encryption constant gives sv >= 24, inside
# the trade answer and mid-trade.
BLOCK_ORDER = (
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2), (0, 2, 3, 1), (0, 3, 2, 1),
    (1, 0, 2, 3), (1, 0, 3, 2), (2, 0, 1, 3), (3, 0, 1, 2), (2, 0, 3, 1), (3, 0, 2, 1),
    (1, 2, 0, 3), (1, 3, 0, 2), (2, 1, 0, 3), (3, 1, 0, 2), (2, 3, 0, 1), (3, 2, 0, 1),
    (1, 2, 3, 0), (1, 3, 2, 0), (2, 1, 3, 0), (3, 1, 2, 0), (2, 3, 1, 0), (3, 2, 1, 0),
    # 24-31: the duplicates
    (0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 1, 3), (0, 3, 1, 2), (0, 2, 3, 1), (0, 3, 2, 1),
    (1, 0, 2, 3), (1, 0, 3, 2),
)
assert len(BLOCK_ORDER) == 32, "the index is 5 bits; the table has to cover all of it"

# offsets into the DECRYPTED, UNSHUFFLED record, header included - PKHeX's own numbering, so a
# constant here can be read straight off `G8PKM.cs` and back again.
#
# The first block is confirmed against a console's own two messages. The rest is from
# PKHeX - and it is worth saying WHY that is not a guess: PKHeX names 102 fields and **every one of
# the twelve read independently agrees**, offset for offset. Twelve out of twelve is not a
# coincidence, so the other ninety are as good as the twelve. Three PK8s then read with the
# same map and got the player's own team, levels included.
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

# IV32 at 0x8C carries two flags above the six 5-bit IVs.
IV32_EGG = 1 << 30
IV32_NICKNAMED = 1 << 31

OFF_GENDER = 0x22                     # bits 2-3 of the byte; the rest is FatefulEncounter/Flag2
OFF_MOVES = 0x72                      # 4 x u16
OFF_MOVE_PP = 0x7A                    # 4 x u8
OFF_MOVE_PP_UPS = 0x7E                # 4 x u8
OFF_RELEARN = 0x82                    # 4 x u16
OFF_HT_NAME = 0xA8                    # HandlingTrainerName, 26 bytes like the others. PKHeX's
                                      # `IsUntraded` IS `Data[0xA8] == 0`: an empty handler name is
                                      # what "never been traded" looks like. A console watched
                                      # cross that line.
OFF_HT_LANGUAGE = 0xC3
OFF_CURRENT_HANDLER = 0xC4            # 0 = the original trainer still holds it
OFF_HT_ID = 0xC6                      # PKHeX writes this one `// unused?`, and it is:
                                      # the console filled in name, language, handler and
                                      # friendship on a traded Pokemon AND LEFT THIS ZERO.
OFF_HT_FRIENDSHIP = 0xC8
OFF_VERSION = 0xDE
OFF_LANGUAGE = 0xE2
OFF_OT_FRIENDSHIP = 0x112
OFF_EGG_DATE = 0x119                  # year-2000, month, day
OFF_MET_DATE = 0x11C                  # year-2000, month, day
OFF_EGG_LOCATION = 0x120
OFF_MET_LOCATION = 0x122
OFF_BALL = 0x124
OFF_MET_LEVEL = 0x125                 # low 7 bits; bit 7 is the OT's gender
OFF_HYPER_TRAIN = 0x126               # one bit per stat, bit 0 = HP .. bit 5 = SPE, PKHeX's HT_* order

# The party stats, past SIZE_STORED. Present only in the 0x158 form, outside the four blocks and
# never permuted, so a level reads correctly even when the block order is wrong.
OFF_STAT_LEVEL = 0x148
OFF_STAT_HP_CURRENT_PARTY = 0x149     # PKHeX leaves 0x149 unnamed; the stats start at 0x14A
OFF_STATS = 0x14A                     # HP, ATK, DEF, SPE, SPA, SPD - u16 each, PKHeX's order
OFF_DYNAMAX_TYPE = 0x156              # PK8 only; PB8 has nothing here

STAT_NAMES = ("hp", "attack", "defence", "speed", "special_attack", "special_defence")
IV_SHIFTS = (0, 5, 10, 15, 20, 25)    # HP, ATK, DEF, SPE, SPA, SPD - the EV/stat order, not the
                                      # display order. PKHeX's IV_SPE is bits 15-19.


def crypt(chunk, seed):
    """XOR every 16-bit word of `chunk` with the LCG stream seeded at `seed`. Its own inverse."""
    out = bytearray(chunk)
    for i in range(0, len(out) - 1, 2):
        seed = (seed * 0x41C64E6D + 0x00006073) & 0xFFFFFFFF
        struct.pack_into("<H", out, i,
                         struct.unpack_from("<H", out, i)[0] ^ ((seed >> 16) & 0xFFFF))
    return bytes(out)


def permute(data, order):
    """-> data with its four blocks reordered, `order[i]` naming the block that becomes block i.

    Everything outside the blocks - the eight-byte header and the party stats, if there are any -
    is copied through untouched, because neither is part of the shuffle.
    """
    out = bytearray(data[:HEADER_SIZE])
    for src in order:
        out += data[HEADER_SIZE + src * BLOCK_SIZE:HEADER_SIZE + (src + 1) * BLOCK_SIZE]
    return bytes(out) + data[SIZE_STORED:]


def invert(order):
    return tuple(order.index(block) for block in range(BLOCK_COUNT))


def checksum(plain):
    """The 16-bit sum of the decrypted body - what the header carries in the clear.

    BOUNDED AT SIZE_STORED, and that bound is load-bearing for a party record: PKHeX sums
    `data[8..SIZE_8STORED]` and the party stats past it are not in the sum.
    """
    n = (SIZE_STORED - HEADER_SIZE) // 2
    return sum(struct.unpack_from(f"<{n}H", plain, HEADER_SIZE)) & 0xFFFF


def decrypt(raw):
    """-> the plain, unshuffled record, stored or party sized. Raises if the checksum disagrees."""
    if len(raw) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(raw)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    ec = struct.unpack_from("<I", raw, 0)[0]
    out = bytearray(raw)
    out[HEADER_SIZE:SIZE_STORED] = crypt(raw[HEADER_SIZE:SIZE_STORED], ec)
    # The stream restarts here, seeded from the same constant. PokeCrypto.Decrypt8, two calls.
    out[SIZE_STORED:] = crypt(raw[SIZE_STORED:], ec)
    # BLOCK_ORDER[sv] is the read order for decryption, applied directly. Inverting it here is
    # wrong for any sv whose permutation is not its own inverse, which is 24 of the 32. PKHeX's
    # decrypt path uses BlockPosition[sv] as it stands and
    # only its ENCRYPT path goes through BlockPositionInvert. Both of this project's block-order
    # bugs were that inversion, in two different modules, three sessions apart.
    plain = permute(bytes(out), BLOCK_ORDER[(ec >> 13) & 31])
    want = struct.unpack_from("<H", raw, 6)[0]
    got = checksum(plain)
    if got != want:
        raise ValueError(f"checksum {got:#06x}, header says {want:#06x} - not a valid Gen-8 record")
    return plain


def is_plain(raw):
    """-> whether a record on disk is already decrypted: PKHeX's plain export keeps the
    checksum in the header, so the sum over the raw body matches it only when nothing is
    encrypted. An encrypted body matching by chance is a 1-in-65536 event."""
    if len(raw) not in (SIZE_STORED, SIZE_PARTY):
        return False
    return checksum(raw) == struct.unpack_from("<H", raw, 6)[0]


def load(raw):
    """-> a plain PARTY record from a file in any of the four shapes a .pk8 comes in: stored or
    party, encrypted or PKHeX's decrypted export. A stored record gets a zero party tail; the
    receiving game rebuilds the tail from the body (docs/swsh_trade.md)."""
    plain = bytes(raw) if is_plain(raw) else decrypt(raw)
    if len(plain) == SIZE_STORED:
        plain += bytes(SIZE_PARTY - SIZE_STORED)
    return plain


def encrypt(plain):
    """-> the bytes to put on the wire, with the checksum written from the body itself."""
    if len(plain) not in (SIZE_STORED, SIZE_PARTY):
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED} or {SIZE_PARTY}")
    body = bytearray(plain)
    struct.pack_into("<H", body, 6, checksum(body))
    ec = struct.unpack_from("<I", body, 0)[0]
    shuffled = bytearray(permute(bytes(body), invert(BLOCK_ORDER[(ec >> 13) & 31])))
    out = bytearray(shuffled)
    out[HEADER_SIZE:SIZE_STORED] = crypt(shuffled[HEADER_SIZE:SIZE_STORED], ec)
    out[SIZE_STORED:] = crypt(shuffled[SIZE_STORED:], ec)
    return bytes(out)


def text(plain, offset):
    return plain[offset:offset + NAME_LENGTH].decode("utf-16-le", "replace").split("\x00")[0]


def read(plain):
    """-> what a DECRYPTED record says about itself. Party stats only if it is the party form."""
    u16 = lambda o: struct.unpack_from("<H", plain, o)[0]
    ivs = struct.unpack_from("<I", plain, OFF_IVS)[0]
    fields = {
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
        "ivs": tuple((ivs >> s) & 31 for s in IV_SHIFTS),
        "nickname": text(plain, OFF_NICKNAME),
        "ot_name": text(plain, OFF_OT_NAME),
        # The name is only shown when this is set. A Gen-8 record always carries a name string
        # (the species name if the player never renamed it), so `nickname` alone does not say what
        # the console displays.
        "is_nicknamed": bool(ivs & IV32_NICKNAMED),
        "is_egg": bool(ivs & IV32_EGG),
        "gender": (plain[OFF_GENDER] >> 2) & 3,
        "moves": struct.unpack_from("<4H", plain, OFF_MOVES),
        "move_pp": tuple(plain[OFF_MOVE_PP:OFF_MOVE_PP + 4]),
        "relearn": struct.unpack_from("<4H", plain, OFF_RELEARN),
        "current_handler": plain[OFF_CURRENT_HANDLER],
        "ht_name": text(plain, OFF_HT_NAME),
        "ht_language": plain[OFF_HT_LANGUAGE],
        "ht_id": u16(OFF_HT_ID),
        "ht_friendship": plain[OFF_HT_FRIENDSHIP],
        # what PKHeX calls IsUntraded, and it is a real question about a real Pokemon
        "is_untraded": plain[OFF_HT_NAME] == 0 and plain[OFF_HT_NAME + 1] == 0,
        "version": plain[OFF_VERSION],
        "language": plain[OFF_LANGUAGE],
        "ot_friendship": plain[OFF_OT_FRIENDSHIP],
        "met_date": tuple(plain[OFF_MET_DATE:OFF_MET_DATE + 3]),
        "egg_location": u16(OFF_EGG_LOCATION),
        "met_location": u16(OFF_MET_LOCATION),
        "ball": plain[OFF_BALL],
        "met_level": plain[OFF_MET_LEVEL] & 0x7F,
        "ot_gender": plain[OFF_MET_LEVEL] >> 7,
        # a hyper-trained stat is computed as IV 31 whatever the IV word says
        "hyper_trained": tuple(bool(plain[OFF_HYPER_TRAIN] >> b & 1) for b in (0, 1, 2, 5, 3, 4)),
    }
    if len(plain) == SIZE_PARTY:
        fields["level"] = plain[OFF_STAT_LEVEL]
        fields["stats"] = dict(zip(STAT_NAMES, struct.unpack_from("<6H", plain, OFF_STATS)))
    return fields


def write(plain, **fields):
    """-> a plain record with the named fields replaced. The caller re-encrypts.

    A record holds far more than the fields any run has identified, and the rest is not zero on a
    console's own Pokemon - move counts, met data, ribbons, the language byte, handler records. So
    an entity we send is one the console sent us with named fields changed, and every byte we have
    never read is still a real one, from a real save, in the slot the game put it in.

        species, held_item, trainer_id, secret_id, experience, ability, pid,
        nature, form, evs (6), ivs (6), nickname, ot_name, encryption_constant,
        is_nicknamed, is_egg, gender, moves (4), move_pp (4), move_pp_ups (4), relearn (4),
        current_handler, version, language, ot_friendship, met_date (3), egg_location,
        met_location, ball, met_level, ot_gender, ht_name, ht_language, ht_id, ht_friendship,
        level, stats (6)                              - the last two only on a party record

    Passing `nickname` sets is_nicknamed as a side effect, because a name the flag does not enable
    is a name the console never draws.
    """
    plain = bytearray(plain)
    u16 = lambda o, v: struct.pack_into("<H", plain, o, v & 0xFFFF)
    u32 = lambda o, v: struct.pack_into("<I", plain, o, v & 0xFFFFFFFF)

    def name(offset, value):
        encoded = value.encode("utf-16-le")
        if len(encoded) + 2 > NAME_LENGTH:
            raise ValueError(f"{value!r} is too long for a {NAME_LENGTH}-byte name field")
        plain[offset:offset + NAME_LENGTH] = encoded.ljust(NAME_LENGTH, b"\x00")

    def party_field(key):
        if len(plain) != SIZE_PARTY:
            raise ValueError(f"{key} is a party-record field and this is {len(plain)} bytes")

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
            for shift, iv in zip(IV_SHIFTS, value):
                packed |= (iv & 31) << shift
            # the top bits of this word are not IVs and are left exactly as the template had them
            old = struct.unpack_from("<I", plain, OFF_IVS)[0]
            u32(OFF_IVS, (old & ~0x3FFFFFFF) | packed)
        elif key == "nickname":
            name(OFF_NICKNAME, value)
            # Set the flag too, or the console shows the species name and the edit is invisible.
            # An explicit is_nicknamed= after this still wins; dict order is insertion order.
            u32(OFF_IVS, struct.unpack_from("<I", plain, OFF_IVS)[0] | IV32_NICKNAMED)
        elif key == "ot_name":
            name(OFF_OT_NAME, value)
        elif key == "is_nicknamed":
            old_iv = struct.unpack_from("<I", plain, OFF_IVS)[0]
            u32(OFF_IVS, (old_iv | IV32_NICKNAMED) if value else (old_iv & ~IV32_NICKNAMED))
        elif key == "is_egg":
            old_iv = struct.unpack_from("<I", plain, OFF_IVS)[0]
            u32(OFF_IVS, (old_iv | IV32_EGG) if value else (old_iv & ~IV32_EGG))
        elif key == "gender":
            plain[OFF_GENDER] = (plain[OFF_GENDER] & ~0x0C) | ((value & 3) << 2)
        elif key == "moves":
            struct.pack_into("<4H", plain, OFF_MOVES, *value)
        elif key == "move_pp":
            plain[OFF_MOVE_PP:OFF_MOVE_PP + 4] = bytes(value)
        elif key == "move_pp_ups":
            plain[OFF_MOVE_PP_UPS:OFF_MOVE_PP_UPS + 4] = bytes(value)
        elif key == "relearn":
            struct.pack_into("<4H", plain, OFF_RELEARN, *value)
        elif key == "current_handler":
            plain[OFF_CURRENT_HANDLER] = value & 0xFF
        elif key == "ht_name":
            name(OFF_HT_NAME, value)
        elif key == "ht_language":
            plain[OFF_HT_LANGUAGE] = value & 0xFF
        elif key == "ht_id":
            u16(OFF_HT_ID, value)
        elif key == "ht_friendship":
            plain[OFF_HT_FRIENDSHIP] = value & 0xFF
        elif key == "version":
            plain[OFF_VERSION] = value & 0xFF
        elif key == "language":
            plain[OFF_LANGUAGE] = value & 0xFF
        elif key == "ot_friendship":
            plain[OFF_OT_FRIENDSHIP] = value & 0xFF
        elif key == "met_date":
            plain[OFF_MET_DATE:OFF_MET_DATE + 3] = bytes(value)
        elif key == "egg_location":
            u16(OFF_EGG_LOCATION, value)
        elif key == "met_location":
            u16(OFF_MET_LOCATION, value)
        elif key == "ball":
            plain[OFF_BALL] = value & 0xFF
        elif key == "met_level":
            plain[OFF_MET_LEVEL] = (plain[OFF_MET_LEVEL] & 0x80) | (value & 0x7F)
        elif key == "ot_gender":
            plain[OFF_MET_LEVEL] = (plain[OFF_MET_LEVEL] & 0x7F) | ((value & 1) << 7)
        elif key == "level":
            party_field(key)
            plain[OFF_STAT_LEVEL] = value & 0xFF
        elif key == "stats":
            party_field(key)
            values = [value[k] for k in STAT_NAMES] if isinstance(value, dict) else list(value)
            struct.pack_into("<6H", plain, OFF_STATS, *values)
        else:
            raise ValueError(f"unknown field {key!r}")
    return bytes(plain)
