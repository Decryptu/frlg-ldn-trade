"""A BDSP Pokemon on the wire: the 328-byte PB8 a `NetTradePokeData` carries.

The console handed one over in sp82 - a Zubat the player picked out of their own boxes - and the
whole format is the Gen 6+ one, unchanged since XY. The format ITSELF is `pokeldn.gen8`, because
Sword/Shield's PK8 is the same class in PKHeX with one extra field; what belongs HERE is what is
true of BDSP and of nothing else.

SIZE_STORED is 328 and that is exactly what the message carried, so **a BDSP trade sends the
STORED form** and not the party form (which is 0x10 longer and holds the battle stats). Sword sends
the party form on protocol 0x84, which is the one difference in how the two games use one format.

THE CHECKSUM IS WHAT MAKES THIS SAFE TO BUILD - BUT IT DOES NOT CHECK EVERYTHING. It is stored in
the clear and is the 16-bit sum of the DECRYPTED body, so a wrong LCG stream cannot produce a match.
It says NOTHING about the block order: permuting whole 80-byte blocks leaves a sum of 16-bit words
untouched, because addition commutes. Session 54 shipped a block-order bug for nine runs behind a
checksum that agreed every time. What catches a wrong order is reading the fields and seeing whether
a Pokemon comes out. `docs/bdsp.md`.
"""
from pokeldn import gen8
from pokeldn.gen8 import (                                             # noqa: F401 - the PB8 view
    BLOCK_ORDER, BLOCK_SIZE, HEADER_SIZE, IV32_EGG, IV32_NICKNAMED, NAME_LENGTH, OFF_ABILITY,
    OFF_BALL, OFF_CURRENT_HANDLER, OFF_EGG_DATE, OFF_EGG_LOCATION, OFF_EVS, OFF_EXPERIENCE,
    OFF_FORM, OFF_GENDER, OFF_HELD_ITEM, OFF_HT_FRIENDSHIP, OFF_HT_ID, OFF_HT_LANGUAGE,
    OFF_HT_NAME, OFF_IVS, OFF_LANGUAGE, OFF_MET_DATE, OFF_MET_LEVEL, OFF_MET_LOCATION,
    OFF_MOVES, OFF_MOVE_PP, OFF_MOVE_PP_UPS, OFF_NATURE, OFF_NICKNAME, OFF_OT_FRIENDSHIP,
    OFF_OT_NAME, OFF_PID, OFF_RELEARN, OFF_SID, OFF_SPECIES, OFF_TID, OFF_VERSION,
    checksum, invert, permute,
)

SIZE_STORED = gen8.SIZE_STORED                # 328 = 0x148, the stored form and what BDSP trades


def decrypt(raw):
    """-> the plain, unshuffled 328 bytes. Raises if the checksum does not agree.

    BLOCK_ORDER[sv] IS THE READ ORDER FOR DECRYPTION, APPLIED DIRECTLY (`gen8.decrypt`). It is not
    "where each block went", and inverting it - which this function did until session 54 - is wrong
    for any sv whose permutation is not its own inverse.

    THAT BUG SURVIVED NINE RUNS BECAUSE OF ONE POKEMON. Every PB8 this project had decoded came
    from sp82's Zubat, EC giving sv=21 and the ordering (3, 1, 2, 0), which IS self-inverse - so
    the extra inversion was a no-op and the checksum agreed. sp97's Keunotor is sv=28,
    (0, 2, 3, 1), which is not, and it decoded to a Bidoof with no moves, no ball and its species
    name in the trainer field.

    AND THE CHECKSUM CANNOT CATCH THIS. It is a sum of 16-bit words over the whole body, and
    permuting whole 80-byte blocks does not change a sum - addition commutes. It verifies the LCG
    stream and nothing about the block order.
    """
    if len(raw) != SIZE_STORED:
        raise ValueError(f"{len(raw)} bytes, expected {SIZE_STORED}")
    return gen8.decrypt(raw)


def encrypt(plain):
    """-> the 328 bytes to put on the wire, with the checksum written from the body itself."""
    if len(plain) != SIZE_STORED:
        raise ValueError(f"{len(plain)} bytes, expected {SIZE_STORED}")
    return gen8.encrypt(plain)


def read(raw):
    """-> what a received Pokemon says about itself. sp82's twelve fields and PKHeX's rest."""
    return gen8.read(decrypt(raw))


def build_from(template_raw, **fields):
    """-> an encrypted PB8 made by editing a REAL one.

    328 bytes hold far more than the dozen fields sp82 identified, and the rest is not zero on a
    console's own Pokemon - move counts, met data, ribbons, the language byte, handler records.
    Assembling one from nothing would mean inventing every byte this project has not read, so a
    Pokemon we send is a Pokemon the console sent us with named fields changed. Every unknown byte
    is then a real one, from a real save, in a slot the game itself put it in.

    The checksum is rewritten from the edited body by `encrypt`, so a template edit cannot leave an
    inconsistent Pokemon behind - and `read` on the result is the check that it did what was asked.
    `gen8.write` lists the fields; `level` and `stats` are not among them for a PB8, which is the
    stored form and has no party stats to set.
    """
    return encrypt(gen8.write(decrypt(template_raw), **fields))
