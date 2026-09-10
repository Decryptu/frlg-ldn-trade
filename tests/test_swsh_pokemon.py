"""The 0x158-byte PK8 a Sword sends on protocol 0x84, and the party of six it arrives in.

Two runs are captures and stay out of the repository (CLAUDE.md rule 6), so everything here is
built from synthetic records. What the real ones proved - and what these reproduce - is that the
party stats RESTART the LCG, that they are outside both the shuffle and the checksum, and that the
block order is applied and not inverted.
"""
import struct

import pytest

from pokeldn import gen8
from pokeldn.swsh import pokemon


def a_record(ec=0x39C5F2CC, species=94, nickname="Ectoplasma", ot="Gurvan", level=100,
             size=gen8.SIZE_PARTY):
    """A plain, unshuffled record with the named fields set and the rest patterned.

    The filler is deliberately NOT zero: a block permutation and an off-by-one offset both survive
    a body of zeros, and neither survives this.
    """
    plain = bytearray(bytes(range(256)) * 2)[:size]
    struct.pack_into("<I", plain, 0x00, ec)
    struct.pack_into("<H", plain, 0x04, 0)
    struct.pack_into("<H", plain, gen8.OFF_SPECIES, species)
    struct.pack_into("<I", plain, gen8.OFF_EXPERIENCE, 1059860)
    for offset, value in ((gen8.OFF_NICKNAME, nickname), (gen8.OFF_OT_NAME, ot)):
        plain[offset:offset + gen8.NAME_LENGTH] = \
            value.encode("utf-16-le").ljust(gen8.NAME_LENGTH, b"\x00")
    if size == gen8.SIZE_PARTY:
        plain[gen8.OFF_STAT_LEVEL] = level
        struct.pack_into("<6H", plain, gen8.OFF_STATS, 261, 149, 156, 350, 359, 187)
    return bytes(plain)


def test_a_party_record_round_trips_with_its_stats():
    raw = pokemon.encrypt(a_record())
    assert len(raw) == gen8.SIZE_PARTY == 0x158
    assert pokemon.decrypt(raw)[8:] == a_record()[8:]
    r = pokemon.read(raw)
    assert (r["species"], r["nickname"], r["ot_name"]) == (94, "Ectoplasma", "Gurvan")
    assert r["level"] == 100
    assert r["stats"]["hp"] == 261 and r["stats"]["special_attack"] == 359


def test_the_stored_form_has_no_party_stats_at_all():
    """A PK8 can be either size, and only the longer one carries a level."""
    r = pokemon.read(pokemon.encrypt(a_record(size=gen8.SIZE_STORED)))
    assert "level" not in r and "stats" not in r
    with pytest.raises(ValueError, match="party-record field"):
        gen8.write(a_record(size=gen8.SIZE_STORED), level=50)


def test_the_party_stats_restart_the_lcg_rather_than_continuing_the_body_stream():
    """`PokeCrypto.Decrypt8` calls CryptArray TWICE, both seeded from the encryption constant.

    A round trip cannot catch this - the cipher is its own inverse either way - so the test asserts
    the keystream directly: the first word of the tail is masked with the SAME step as the first
    word of the body. Levels of 110 and 118 were read out of a tail nothing had decrypted.
    """
    ec = 0x39C5F2CC
    plain = a_record(ec=ec)
    raw = pokemon.encrypt(plain)
    first_step = ((ec * 0x41C64E6D + 0x6073) & 0xFFFFFFFF) >> 16 & 0xFFFF

    tail_plain = struct.unpack_from("<H", plain, gen8.SIZE_STORED)[0]
    tail_cipher = struct.unpack_from("<H", raw, gen8.SIZE_STORED)[0]
    assert tail_cipher == tail_plain ^ first_step

    # and the body's first word uses that same first step, which is what "restart" means
    body_plain = struct.unpack_from("<H", plain, gen8.HEADER_SIZE)[0]
    shuffled = gen8.permute(plain, gen8.invert(gen8.BLOCK_ORDER[(ec >> 13) & 31]))
    if gen8.BLOCK_ORDER[(ec >> 13) & 31][0] == 0:                 # block 0 stayed in place
        body_cipher = struct.unpack_from("<H", raw, gen8.HEADER_SIZE)[0]
        assert body_cipher == body_plain ^ first_step
    assert len(shuffled) == gen8.SIZE_PARTY, "the shuffle must carry the tail through untouched"


def test_the_checksum_covers_the_body_and_stops_at_the_party_stats():
    """PKHeX sums `data[8..SIZE_8STORED]`. A stat is outside it, and a body byte is not."""
    plain = bytearray(a_record())
    before = gen8.checksum(plain)
    plain[gen8.OFF_STAT_LEVEL] = 42
    assert gen8.checksum(plain) == before
    plain[gen8.OFF_SPECIES] ^= 0xFF
    assert gen8.checksum(plain) != before
    # a party record still verifies on decrypt, so the shorter sum is the right one
    assert pokemon.read(pokemon.encrypt(bytes(plain)))["level"] == 42


def test_a_corrupted_record_is_refused_by_its_own_checksum():
    raw = bytearray(pokemon.encrypt(a_record()))
    raw[100] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        pokemon.decrypt(bytes(raw))


def test_every_block_order_puts_the_fields_back_where_they_belong():
    """The session-58 bug, in the shape that catches it.

    `sw84_read.py` inverted the block order, and for sv=1 - whose ordering is its own inverse -
    that is a no-op, so the one slot that happened to have it read perfectly while the two either
    side did not. Sweeping all 32 sv values is what makes the difference visible.
    """
    self_inverse = [sv for sv in range(32)
                    if gen8.BLOCK_ORDER[sv] == gen8.invert(gen8.BLOCK_ORDER[sv])]
    assert self_inverse, "the bug needs at least one of these to have hidden behind"
    assert len(self_inverse) < 32, "and at least one that it cannot hide behind"

    for ec in range(0, 1 << 20, 0x2000):                          # every one of the 32 sv values
        r = pokemon.read(pokemon.encrypt(a_record(ec=ec)))
        sv = (ec >> 13) & 31
        assert r["species"] == 94, f"sv={sv} put the species in the wrong block"
        assert r["nickname"] == "Ectoplasma", f"sv={sv} put the nickname in the wrong block"
        assert r["ot_name"] == "Gurvan", f"sv={sv} put the trainer name in the wrong block"
        assert r["level"] == 100, f"sv={sv} disturbed the party stats, which are not shuffled"


def test_a_party_reads_six_slots_and_an_empty_one_is_an_encryption_constant_of_zero():
    """Slots 4-6 arrive zero-filled from a player carrying three, and a real party is exactly that."""
    filled = [pokemon.encrypt(a_record(ec=0x39C5F2CC, species=94, nickname="Ectoplasma", level=100)),
              pokemon.encrypt(a_record(ec=0xC89430E0, species=254, nickname="Jungko", level=75)),
              pokemon.encrypt(a_record(ec=0xF5213B38, species=149, nickname="Dracolosse", level=73))]
    blob = b"".join(filled) + bytes(3 * gen8.SIZE_PARTY)
    assert len(blob) == pokemon.PARTY_BLOCK == 0x810

    got = pokemon.party(blob)
    assert [p and p["slot"] for p in got] == [1, 2, 3, None, None, None]
    assert [p["species"] for p in got[:3]] == [94, 254, 149]
    assert [p["level"] for p in got[:3]] == [100, 75, 73]
    assert [p["nickname"] for p in got[:3]] == ["Ectoplasma", "Jungko", "Dracolosse"]


def test_a_short_payload_is_refused_rather_than_read_as_a_short_party():
    with pytest.raises(ValueError, match="need"):
        pokemon.party(bytes(pokemon.PARTY_BLOCK - 1))


def test_building_a_party_record_from_a_template_keeps_every_byte_nothing_asked_for():
    """Nothing of ours has been on 0x84 yet, and when it goes it goes as an edit of a real record."""
    template = pokemon.encrypt(a_record())
    made = pokemon.build_from(template, species=25, nickname="PIKA", level=50,
                              stats=(120, 80, 70, 90, 85, 75))
    r = pokemon.read(made)
    assert (r["species"], r["nickname"], r["level"]) == (25, "PIKA", 50)
    assert r["stats"]["hp"] == 120 and r["stats"]["special_defence"] == 75
    assert r["is_nicknamed"] is True, "a name the flag does not enable is one the console never draws"
    before, after = pokemon.decrypt(template), pokemon.decrypt(made)
    untouched = [i for i in range(0xA0, 0xF8) if before[i] != after[i]]
    assert untouched == [], f"bytes changed that nothing asked for: {untouched}"
