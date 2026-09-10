"""Sword and Shield's constants, pinned to what the binary says rather than to a published table.

Every value here was read off a Shield 1.3.2 cartridge image offline; none of it has been on the
air. The point of pinning them is that the next person to touch this cannot quietly "fix" the
passphrase to the wiki's Scarlet/Violet row or the version byte to BDSP's 9 - the differences are
the findings.
"""

import pytest

from pokeldn.ldn.pia5 import ldn_session_key
from pokeldn.swsh import (COMM_ID, GAME_KEY, PASSPHRASE, PIA_HEADER_SIZE, PIA_PORT, PIA_TAG_SIZE,
                          PIA_VERSION, session_key, session_keys)


def test_the_passphrase_is_sixty_four_bytes_used_raw():
    # The length is the instruction's - `mov w2, #0x40` at main.bin 0x006c3ec8 - so there is no
    # padding question here the way there was for BDSP's 27-byte row.
    assert len(PASSPHRASE) == 64
    assert PASSPHRASE.decode().isprintable()
    assert b"\0" not in PASSPHRASE


def test_the_passphrase_is_not_the_arceus_one():
    # The wiki has no Sword/Shield row at all. Its Scarlet/Violet row is this string exactly; its
    # Legends: Arceus row differs in ONE character, and reading one as the other's typo is the
    # mistake this test exists to prevent.
    arceus = b"W3GoSMEn7RIIUQ89rzqBHGHGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
    assert PASSPHRASE != arceus
    assert sum(a != b for a, b in zip(PASSPHRASE, arceus)) == 1


def test_the_game_key_is_a_literal_not_a_derivation():
    # BDSP builds its key by replacing four bytes of a cryptoKeyDataSeed with the local
    # communication version. Sword/Shield does not: all three call sites `ldp` these sixteen ASCII
    # bytes and hand them over unchanged.
    assert GAME_KEY == b"p1frXqxmeCZWFv0X"
    assert len(GAME_KEY) == 16


def test_the_pia_version_is_a_third_band():
    # 6.32+ is 15/16 and 5.27-5.45 is 9. Four is neither - but the crypto underneath turned out to
    # be 5.27's exactly, so the band costs a header (`pokeldn.ldn.pia4`) and not a stack.
    assert PIA_VERSION == 4
    assert PIA_VERSION not in (9, 15, 16)


def test_the_header_is_a_full_tag_in_the_same_twenty_bytes():
    # 5.27-5.45 also totals 0x20 but truncates its tag to eight; version 4 carries all sixteen and
    # spends less on station ids.
    assert PIA_HEADER_SIZE == 0x20
    assert PIA_TAG_SIZE == 16
    assert PIA_PORT == 12345


def test_the_session_key_is_the_same_derivation_bdsp_uses():
    # main.bin 0x17ab010 is instruction-for-instruction pia5's shape, so it must not drift into a
    # copy of its own.
    for seed in (0, 1, 0x36DEE059, 0xFFFFFFFF):
        assert session_key(seed) == ldn_session_key(GAME_KEY, seed)


def test_a_game_key_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError):
        session_key(1, game_key=b"short")


def test_the_advertisement_carries_the_seed_twelve_bytes_in():
    """A run's own advertisement, and the key that authenticated all 484 of its packets."""
    class _Net:
        application_data = bytes.fromhex("0330112400000000051800008b718ac6")

    k = session_keys(_Net())
    assert k.session_param == 0xC68A718B
    assert k.network_id_le.hex() == "03301124"
    assert k.session_key.hex() == "e421f24ecd7166e3e13dc7ea8c379dd9"
    assert k.game_key == GAME_KEY          # a literal: the advertisement contributes the seed only


def test_a_short_advertisement_is_refused_rather_than_read_past():
    class _Net:
        application_data = b"\x01\x02\x03"

    with pytest.raises(ValueError):
        session_keys(_Net())


def test_the_local_communication_id_is_swords_not_shields():
    # Read off the advertisement. The binary this project reads is a SHIELD image, so
    # nothing about this id can be assumed to hold for the other cartridge.
    assert COMM_ID == 0x0100ABF008968000
