"""The BDSP session's own constants, and the derivation that turns an advertisement into keys.

The values pinned here are the ones session 45 measured offline and session 46 confirmed against a
LIVE session with a different SSID, network id and session parameter - 42 of 42 packets
authenticated - which is what says the derivation is general rather than fitted to one capture.
"""

import pytest

from pokeldn.bdsp import CRYPTO_KEY_DATA_SEED, PASSPHRASE, PIA_PORT, session_keys


class _Net:
    def __init__(self, app_data, app_version=199):
        self.application_data = app_data
        self.app_version = app_version


SP4 = bytes.fromhex("b4c85cf8000000000810000059e0de3600")


def test_the_sp4_advertisement_derives_the_measured_keys():
    k = session_keys(_Net(SP4))
    assert k.game_key.hex() == "9900bd0cdcfa65639918bd0fc7fa6577"
    assert k.session_key.hex() == "7b182cb087eeabd228a2efd91a8be147"
    assert k.network_id_le.hex() == "b4c85cf8"
    assert k.session_param == 0x36DEE059          # twelve bytes in, LITTLE-endian


def test_the_passphrase_is_raw_and_unpadded():
    assert PASSPHRASE == b"WirelessStrongCryptoKey2021"
    assert len(PASSPHRASE) == 27
    assert PIA_PORT == 12345


def test_the_seed_is_the_constant_and_the_game_key_is_the_derived_thing():
    """Four bytes apart, which is what reads as a corrupt published key and is not one."""
    k = session_keys(_Net(SP4))
    differ = [i for i in range(16) if k.game_key[i] != CRYPTO_KEY_DATA_SEED[i]]
    assert differ == [1, 3, 7, 12]


def test_a_different_version_moves_exactly_those_four_bytes():
    a = session_keys(_Net(SP4, app_version=199)).game_key
    b = session_keys(_Net(SP4, app_version=200)).game_key
    assert [i for i in range(16) if a[i] != b[i]]
    assert all(a[i] == b[i] for i in range(16) if i not in (1, 3, 7, 12))


def test_short_application_data_is_refused_rather_than_read_off_the_end():
    with pytest.raises(ValueError):
        session_keys(_Net(b"\x01\x02\x03"))
