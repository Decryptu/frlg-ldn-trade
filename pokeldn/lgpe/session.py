"""Everything a Let's Go session is keyed on, as far as the binary has been read.

Read off Let's Go Pikachu 1.0.2's `main`, offline. `docs/lgpe_session.md` has the address behind
each value. Three things are settled by the binary and one is not:

  * the LDN passphrase is the 64-byte literal at 0xf73a50, handed to both session settings with a
    literal length of 0x40. It is Sword's string, byte for byte.
  * the Pia game key is the sixteen ASCII bytes at 0xefd659, loaded with one `ldp` and stored into
    the crypto setting unchanged. Sword's key.
  * the Pia header version byte is 3: the initializer at 0xd122d4 stores 0x00000003_32AB9864 and the
    validator at 0xd12400 checks (byte & 0x7f) == 3. The layout is the 5.11-5.21 one that
    `pokeldn.ldn.pia4` implements for Sword's version 4; the version byte is the only difference.
  * the session-key derivation at 0x5cd560 is BDSP's and Sword's (SEAD from one 32-bit seed, four
    draws, AES-128-ECB under the game key). Which advertised value is the seed is not yet measured
    on this title; the wiki's 5.9-5.18 application-data header puts the session param at +0x0C,
    where Sword's measured seed sits.
"""

import struct
from dataclasses import dataclass

from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc, ldn_session_key

# The LDN passphrase, 64 bytes used raw. main.bin 0xf73a50; `mov w2, #0x40` at 0x4db6c4 (create)
# and 0x4dbbb0 (join) is the length. docs/lgpe_session.md "The LDN passphrase".
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# The Pia game key, sixteen ASCII bytes at main.bin 0xefd659, used unchanged at 0x11a374.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# The Pia header version byte; the header shape is pia4's. docs/lgpe_session.md "The Pia header".
PIA_VERSION = 3
PIA_HEADER_SIZE = 0x20
PIA_TAG_SIZE = 16
PIA_PORT = 12345

# Let's Go Pikachu's title id. The comm id is read off the advertisement at runtime; this is what
# the scan is expected to report, by analogy with BDSP and Sword whose comm ids are their title ids.
COMM_ID_PIKACHU = 0x010003F003A34000

# The link code is three Pokemon chosen in order. The in-game picker's order, and how the choice
# becomes the password hashed into the advertisement, are open on docs/lgpe.md. The sessions this
# project runs use Pikachu three times.
CODE_POKEMON = ("pikachu", "pikachu", "pikachu")


def link_code(names=CODE_POKEMON):
    """The three chosen names, lower-cased and joined with spaces. A placeholder for the password
    string until the binary or a capture says how the game encodes the choice."""
    return " ".join(n.lower() for n in names)


def session_key(seed, game_key=GAME_KEY):
    """The LDN session key: AES-128-ECB(game key) over sixteen bytes of SEAD output, seeded from
    `seed`. main.bin 0x5cd560; the same derivation `pokeldn.ldn.pia5.ldn_session_key` implements."""
    return ldn_session_key(game_key, seed)


# The 5.9-5.18 application-data header: network id at 0, password CRC32 at 4, session param at 12.
NETWORK_ID_OFF = 0
PASSWORD_CRC_OFF = 4
SESSION_PARAM_OFF = 12
APP_HEADER_SIZE = 0x18


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    network_id_le: bytes
    session_param: int
    password_crc: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"network_id_le={self.network_id_le.hex()} param={self.session_param:#010x} "
                f"password_crc={self.password_crc:#010x})")


def session_keys(net, game_key=GAME_KEY):
    """-> SessionKeys, from a scanned network. `net` needs `application_data`."""
    app = bytes(getattr(net, "application_data", b"") or b"")
    if len(app) < SESSION_PARAM_OFF + 4:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{SESSION_PARAM_OFF + 4}")
    param = struct.unpack_from("<I", app, SESSION_PARAM_OFF)[0]
    crc = struct.unpack_from("<I", app, PASSWORD_CRC_OFF)[0]
    return SessionKeys(ldn_session_key(game_key, param), bytes(game_key),
                       app[NETWORK_ID_OFF:NETWORK_ID_OFF + 4], param, crc)


def packet_iv(keys, source_mac, nonce8, source_id=0):
    """The twelve-byte GCM IV: three bytes of crc32(network id || sender MAC), one byte of source
    id, the packet's own nonce. `pia5`'s construction, measured on Sword's version 4."""
    return gcm_iv(ldn_nonce_crc(keys.network_id_le, source_mac), source_id, nonce8)
