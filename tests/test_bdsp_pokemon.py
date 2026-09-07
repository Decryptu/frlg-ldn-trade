"""The 328-byte PB8 a NetTradePokeData carries.

sp82's real Zubat is a capture and stays out of the repository (CLAUDE.md rule 6), so everything
here is built from synthetic bodies. What the real one proved, and what these reproduce, is that
the checksum verifies a decryption and that encrypt is exactly the inverse of decrypt.
"""
import struct

import pytest

from pokeldn.bdsp import pokemon, room


def a_body(ec=0xCDBEB642, species=41, nickname="Nosferapti", ot="Gurvan", tid=44466, sid=4080):
    """A plain, unshuffled 328-byte body with the named fields set and the rest patterned.

    The filler is deliberately NOT zero: a block permutation and an off-by-one offset both survive
    a body of zeros, and neither survives this.
    """
    plain = bytearray(bytes(range(256)) * 2)[:pokemon.SIZE_STORED]
    struct.pack_into("<I", plain, 0x00, ec)
    struct.pack_into("<H", plain, 0x04, 0)
    struct.pack_into("<H", plain, pokemon.OFF_SPECIES, species)
    struct.pack_into("<H", plain, pokemon.OFF_TID, tid)
    struct.pack_into("<H", plain, pokemon.OFF_SID, sid)
    for offset, value in ((pokemon.OFF_NICKNAME, nickname), (pokemon.OFF_OT_NAME, ot)):
        plain[offset:offset + pokemon.NAME_LENGTH] = \
            value.encode("utf-16-le").ljust(pokemon.NAME_LENGTH, b"\x00")
    return bytes(plain)


def test_encrypt_is_the_inverse_of_decrypt_and_the_checksum_is_written_from_the_body():
    raw = pokemon.encrypt(a_body())
    assert len(raw) == pokemon.SIZE_STORED == 328
    plain = pokemon.decrypt(raw)
    # the header travels in the clear; the body comes back exactly
    assert plain[8:] == a_body()[8:]
    assert struct.unpack_from("<H", raw, 6)[0] == pokemon.checksum(plain)
    assert pokemon.encrypt(plain) == raw


def test_a_corrupted_body_is_refused_by_its_own_checksum():
    """The checksum sums the DECRYPTED body, so nothing wrong about a decryption can pass it."""
    raw = bytearray(pokemon.encrypt(a_body()))
    raw[100] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        pokemon.decrypt(bytes(raw))


def test_the_block_order_follows_the_encryption_constant():
    """(EC >> 13) & 31 picks one of 24 orderings, so two ECs shuffle the same body differently."""
    body = bytearray(a_body())
    struct.pack_into("<I", body, 0, 0x00000000)
    first = pokemon.encrypt(bytes(body))
    struct.pack_into("<I", body, 0, 0x0000E000)          # (>> 13) & 31 lands on a different order
    second = pokemon.encrypt(bytes(body))
    assert pokemon.BLOCK_ORDER[(0 >> 13) & 31] != pokemon.BLOCK_ORDER[(0xE000 >> 13) & 31]
    assert first[8:] != second[8:]
    # and each still decodes to the body it was built from
    assert pokemon.decrypt(first)[8:] == pokemon.decrypt(second)[8:]


def test_reading_back_what_was_written():
    r = pokemon.read(pokemon.encrypt(a_body()))
    assert r["species"] == 41
    assert r["nickname"] == "Nosferapti"
    assert r["ot_name"] == "Gurvan"
    assert r["trainer_id"] == 44466
    assert r["secret_id"] == 4080


def test_building_from_a_template_changes_only_what_was_asked_for():
    """A Pokemon we send is a real one with named fields moved - every other byte stays a console's."""
    template = pokemon.encrypt(a_body())
    made = pokemon.build_from(template, species=25, nickname="PIKA", ot_name="PkCamp",
                              ivs=(31, 31, 31, 31, 31, 31))
    r = pokemon.read(made)
    assert (r["species"], r["nickname"], r["ot_name"]) == (25, "PIKA", "PkCamp")
    assert r["ivs"] == (31, 31, 31, 31, 31, 31)
    # untouched fields still hold the template's values
    assert r["trainer_id"] == 44466 and r["secret_id"] == 4080
    before, after = pokemon.decrypt(template), pokemon.decrypt(made)
    untouched = [i for i in range(0xA0, 0xF8) if before[i] != after[i]]
    assert untouched == [], f"bytes changed that nothing asked for: {untouched}"
    with pytest.raises(ValueError, match="unknown field"):
        pokemon.build_from(template, sparkly=1)


def test_a_name_too_long_for_its_field_is_refused_rather_than_truncated():
    template = pokemon.encrypt(a_body())
    with pytest.raises(ValueError, match="too long"):
        pokemon.build_from(template, nickname="A" * 13)
    with pytest.raises(ValueError, match="too long"):
        room.build_trade_traner("A" * 8, 1, 2)


def test_the_trade_messages_wrap_the_payloads_the_console_wraps_them_in():
    raw = pokemon.encrypt(a_body())
    msg = room.build_trade_poke(raw)
    assert msg[:3].hex() == "130148"                     # id 0x13, length 0x148 = 328
    assert room.parse(msg)["name"] == "NetTradePokeData"
    assert msg[3:] == raw
    with pytest.raises(ValueError, match="328-byte"):
        room.build_trade_poke(raw[:-1])
    rec = room.build_trade_traner("Gurvan", 44466, 4080)
    assert room.parse_trade_traner(rec[3:])["trainer_id"] == 44466
