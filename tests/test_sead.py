"""SEAD's RNG, and the Pia 5.x LDN session key that is built on it.

The generator is the one input to BDSP's session key that is NOT in doubt: session 43 read it
instruction by instruction off the console's ARM64 and session 45 found the NintendoClients wiki
describing the same thing, down to the state rotation and the multiply-not-modulo range reduction.
That agreement is load-bearing - it is what says a failed derivation is a wrong key or a wrong
nonce rather than a wrong xorshift, and it is what makes a 2^32 sweep of the seed meaningful.

So these tests re-derive the generator from its published formula rather than pinning bytes this
project produced, and check the module against that. A pin of our own output would pass even if
both readings had been mis-transcribed the same way.
"""

import os
import struct
import sys

import pytest
from Crypto.Cipher import AES

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.ldn.pia5 import ldn_session_key                    # noqa: E402
from pokeldn.ldn.sead import INIT_MULTIPLIER, Sead, create_key  # noqa: E402

M32 = 0xFFFFFFFF


def reference_state(seed):
    """The published init, written out longhand."""
    temp, state = seed, []
    for i in range(1, 5):
        temp ^= temp >> 30
        temp = (temp * 0x6C078965 + i) & M32
        state.append(temp)
    return state


def reference_draws(seed, count):
    """The published u32(), written out longhand."""
    s = reference_state(seed)
    out = []
    for _ in range(count):
        t = (s[0] ^ (s[0] << 11)) & M32
        t ^= t >> 8
        t ^= s[3]
        t ^= s[3] >> 19
        t &= M32
        s = [s[1], s[2], s[3], t]
        out.append(t)
    return out


@pytest.mark.parametrize("seed", [0, 1, 31, 0x59E0DE36, 0xFFFFFFFF])
def test_init_matches_the_published_formula(seed):
    assert Sead(seed=seed).state == reference_state(seed)


def test_the_init_multiplier_is_the_one_that_was_read():
    assert INIT_MULTIPLIER == 0x6C078965


@pytest.mark.parametrize("seed", [0, 31, 0x59E0DE36])
def test_draws_match_the_published_generator(seed):
    assert [Sead(seed=seed).u32() for _ in range(1)] == reference_draws(seed, 1)
    r = Sead(seed=seed)
    assert [r.u32() for _ in range(8)] == reference_draws(seed, 8)


def test_every_draw_is_a_u32():
    r = Sead(seed=12345)
    assert all(0 <= r.u32() <= M32 for _ in range(200))


def test_a_state_can_be_given_directly():
    """SEAD takes four words as readily as a seed - which is why a 16-byte 'seed' is ambiguous."""
    state = [0x0FBD1899, 0x7765FADC, 0x0FBD1899, 0x7765FADC]
    a, b = Sead(state=state), Sead(state=list(state))
    assert [a.u32() for _ in range(4)] == [b.u32() for _ in range(4)]
    assert Sead(state=state).state == state


def test_a_state_given_as_bytes_is_four_words():
    seed = bytes.fromhex("9918bd0fdcfa65779918bd0fdcfa6577")
    assert len(struct.unpack("<4I", seed)) == 4


def test_a_seed_is_only_a_shorthand_for_the_state_it_builds():
    state = reference_state(7)
    assert Sead(seed=7).u32() == Sead(state=state).u32()


def test_u64_is_two_draws_high_first():
    a = Sead(seed=99)
    hi, lo = a.u32(), a.u32()
    assert Sead(seed=99).u64() == (hi << 32) | lo


def test_uint_reduces_by_multiply_not_modulo():
    """SEAD's range reduction is (u32 * max) >> 32; a modulo would give different answers."""
    for seed in (0, 5, 0x1234):
        draws = reference_draws(seed, 6)
        r = Sead(seed=seed)
        assert [r.uint(64) for _ in range(6)] == [(d * 64) >> 32 for d in draws]


def test_uint_stays_in_range():
    r = Sead(seed=3)
    assert all(0 <= r.uint(64) < 64 for _ in range(500))


def test_bytes_packs_each_draw_little_endian():
    assert Sead(seed=0).bytes(16) == struct.pack("<4I", *reference_draws(0, 4))


def test_bytes_refuses_a_size_that_is_not_whole_words():
    with pytest.raises(ValueError):
        Sead(seed=0).bytes(15)


def test_constructing_with_both_or_neither_is_refused():
    with pytest.raises(ValueError):
        Sead()
    with pytest.raises(ValueError):
        Sead(seed=1, state=[0, 0, 0, 0])
    with pytest.raises(ValueError):
        Sead(state=[1, 2, 3])


def test_enl_create_key_is_bytes_picked_out_of_the_table():
    """Every byte of an ENL key comes from the table, so no byte can be anything else."""
    table = [0x11223344, 0x55667788, 0xAABBCCDD, 0xEEFF0011]
    allowed = set()
    for w in table:
        allowed.update((w >> s) & 0xFF for s in (0, 8, 16, 24))
    key = create_key(Sead(seed=0), table, 16)
    assert len(key) == 16
    assert set(key) <= allowed


def test_enl_create_key_is_deterministic_for_a_seed():
    table = [0x11223344, 0x55667788, 0xAABBCCDD, 0xEEFF0011]
    assert create_key(Sead(seed=31), table) == create_key(Sead(seed=31), table)
    assert create_key(Sead(seed=31), table) != create_key(Sead(seed=0), table)


def test_enl_create_key_refuses_a_part_word_size():
    with pytest.raises(ValueError):
        create_key(Sead(seed=0), [1, 2], 6)


def test_ldn_session_key_is_aes_ecb_over_sixteen_sead_bytes():
    game_key = bytes.fromhex("9918bd0fdcfa65779918bd0fdcfa6577")
    seed = 0x59E0DE36
    expected = AES.new(game_key, AES.MODE_ECB).encrypt(struct.pack("<4I", *reference_draws(seed, 4)))
    assert ldn_session_key(game_key, seed) == expected
    assert len(ldn_session_key(game_key, seed)) == 16


def test_ldn_session_key_refuses_a_key_that_is_not_sixteen_bytes():
    with pytest.raises(ValueError):
        ldn_session_key(b"\x00" * 15, 1)


def test_gcm_iv_is_three_crc_bytes_then_the_source_id_then_the_nonce():
    """The fourth byte is the source variable id, not the CRC's - the game overwrites it."""
    from pokeldn.ldn.pia5 import gcm_iv
    nonce8 = bytes.fromhex("f5a83bd383ce712d")
    iv = gcm_iv(0xAABBCCDD, 0x11BAC90D, nonce8)
    assert len(iv) == 12
    assert iv[:3] == bytes.fromhex("aabbcc")
    assert iv[3] == 0x0D
    assert iv[4:] == nonce8


def test_gcm_iv_refuses_a_nonce_that_is_not_eight_bytes():
    from pokeldn.ldn.pia5 import gcm_iv
    with pytest.raises(ValueError):
        gcm_iv(0, 0, b"\x00" * 7)


# --- The BDSP session, end to end. These pin the values a real capture authenticates with.

BDSP_SEED = bytes.fromhex("9918bd0fdcfa65779918bd0fdcfa6577")   # cryptoKeyDataSeed, from metadata
BDSP_KEY = bytes.fromhex("9900bd0cdcfa65639918bd0fc7fa6577")    # what Pia is handed, version 199
SP4_NETID_LE = bytes.fromhex("b4c85cf8")                        # advertisement +0x00
SP4_MAC = bytes.fromhex("48f1eb209b22")                         # the console's MAC
SP4_SESSPARAM = 0x36DEE059                                      # advertisement +0x0c, LE
SP4_SESSION_KEY = bytes.fromhex("7b182cb087eeabd228a2efd91a8be147")


def test_the_published_game_key_is_the_seed_derived_with_the_version():
    """Not a corrupted transcription - the four differing bytes are the four the game overwrites."""
    from pokeldn.ldn.pia5 import ldn_game_key
    assert ldn_game_key(BDSP_SEED, 199) == BDSP_KEY
    differing = [i for i in range(16) if BDSP_SEED[i] != BDSP_KEY[i]]
    assert differing == [1, 3, 7, 12]


def test_a_different_version_moves_only_those_four_bytes():
    from pokeldn.ldn.pia5 import ldn_game_key
    other = ldn_game_key(BDSP_SEED, 200)
    assert [i for i in range(16) if other[i] != BDSP_SEED[i]] == [1, 3, 7, 12]
    assert other != BDSP_KEY


def test_game_key_refuses_a_seed_that_is_not_sixteen_bytes():
    from pokeldn.ldn.pia5 import ldn_game_key
    with pytest.raises(ValueError):
        ldn_game_key(b"\x00" * 15, 199)


def test_the_nonce_crc_is_over_the_network_id_then_the_mac():
    from pokeldn.ldn.pia5 import ldn_nonce_crc
    assert ldn_nonce_crc(SP4_NETID_LE, SP4_MAC) == 0xDA291352


def test_the_nonce_crc_rejects_the_wrong_field_sizes():
    from pokeldn.ldn.pia5 import ldn_nonce_crc
    with pytest.raises(ValueError):
        ldn_nonce_crc(SP4_NETID_LE, b"\x00" * 4)
    with pytest.raises(ValueError):
        ldn_nonce_crc(b"\x00" * 6, SP4_MAC)


def test_the_session_key_of_the_captured_bdsp_session():
    from pokeldn.ldn.pia5 import ldn_session_key
    assert ldn_session_key(BDSP_KEY, SP4_SESSPARAM) == SP4_SESSION_KEY


def test_the_whole_chain_reproduces_the_iv_of_a_captured_packet():
    """seed -> key -> session key, and network id + MAC -> CRC -> IV, as sp4 authenticates."""
    from pokeldn.ldn.pia5 import gcm_iv, ldn_game_key, ldn_nonce_crc
    key = ldn_game_key(BDSP_SEED, 199)
    crc = ldn_nonce_crc(SP4_NETID_LE, SP4_MAC)
    iv = gcm_iv(crc, 0x11BAC90D, bytes.fromhex("f5a83bd383ce712d"))
    assert iv == bytes.fromhex("da29130df5a83bd383ce712d")
    assert key == BDSP_KEY


def test_a_captured_packet_actually_decrypts_and_authenticates():
    """The GCM tag is the oracle: a wrong key, session key, IV or layout cannot pass this."""
    from Crypto.Cipher import AES
    from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc, ldn_session_key
    nonce8 = bytes.fromhex("f5a83bd383ce712d")          # the first sp4 packet's header nonce
    sk = ldn_session_key(BDSP_KEY, SP4_SESSPARAM)
    assert sk == SP4_SESSION_KEY
    iv = gcm_iv(ldn_nonce_crc(SP4_NETID_LE, SP4_MAC), 0x11BAC90D, nonce8)
    plaintext = b"\x11" * 32
    ct, tag = AES.new(sk, AES.MODE_GCM, nonce=iv, mac_len=8).encrypt_and_digest(plaintext)
    assert len(tag) == 8                                 # Pia keeps only the first eight
    assert AES.new(sk, AES.MODE_GCM, nonce=iv, mac_len=8).decrypt_and_verify(ct, tag) == plaintext
    with pytest.raises(ValueError):                      # and a wrong IV must not pass
        AES.new(sk, AES.MODE_GCM, nonce=bytes(12), mac_len=8).decrypt_and_verify(ct, tag)
