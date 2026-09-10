"""Everything a Sword/Shield session is keyed on, as far as the binary has been read.

Read off a Shield 1.3.2 cartridge image, offline, with no hardware run - see `docs/swsh.md` for the
addresses behind each value. Two of these differ from BDSP in a way that matters:

  * the game key is a LITERAL, handed to Pia unchanged. BDSP builds its key by replacing four bytes
    of a `cryptoKeyDataSeed` with the local communication version, so a published key there is a
    derived value for one game version. Here there is nothing to derive: three call sites `ldp` the
    same sixteen ASCII bytes straight out of rodata into Pia's crypto setting.
  * the Pia protocol version byte is 4, which is NEITHER of the two bands `pokeldn.ldn` implements.
    `pia_connect.py` is 6.32+ (byte 15/16) and `pia5.py` is 5.27-5.45 (byte 9). Nothing here can
    speak to a console until a version-4 header exists, so this module deliberately stops at the
    constants and the one derivation that IS shared.

BOTH OF THE OPEN ITEMS ARE CLOSED, on hardware. The local communication id is
0x0100ABF008968000, read off a Sword's own advertisement - SWORD, so the id here is not the Shield
cartridge the binary was read from. And the value that seeds the session key is where BDSP keeps
it, twelve bytes into the application data, little-endian: 484 packets, all authenticated.
"""

import struct
from dataclasses import dataclass

from pokeldn.ldn.pia5 import gcm_iv, ldn_nonce_crc, ldn_session_key

# The LDN passphrase, 64 bytes used RAW. main.bin 0x203ff04, handed to Pia's
# LdnCreateSessionSetting with a literal `mov w2, #0x40` at 0x006c3ec8 - so the length is the
# instruction's, not a strlen, and there is no padding question the way there was for BDSP.
PASSPHRASE = b"W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL"
assert len(PASSPHRASE) == 64

# The Pia game key, sixteen ASCII bytes at main.bin 0x1c3dc87, used unchanged. Every one of its
# three call sites builds the same {u32 enabled = 1; u8 key[16]} and hands it to the session; Pia
# keeps it at LocalProtocol+0x4d4 (the setter is at 0x17ab750) and the session key is derived
# straight from it.
GAME_KEY = b"p1frXqxmeCZWFv0X"
assert len(GAME_KEY) == 16

# The Pia protocol version byte, from the header initializer's one 64-bit store of
# 0x00000004_32AB9864 at 0x17748bc and from three validators that each check (byte & 0x7f) == 4.
PIA_VERSION = 4

# The header the deserializer at 0x1774730 accepts: it refuses anything <= 0x1f bytes, then copies
# magic (4, big-endian), version (1), a station byte, a big-endian halfword, an 8-byte GCM nonce and
# a SIXTEEN-byte GCM tag - where 5.27-5.45 truncates its tag to eight and spends the difference on
# 4-byte station ids.
PIA_HEADER_SIZE = 0x20
PIA_TAG_SIZE = 16

# Every Pia station listens on the same port; this is not game-specific, and BDSP measured it.
PIA_PORT = 12345


def session_key(seed, game_key=GAME_KEY):
    """The LDN session key: AES-128-ECB(game key) over sixteen bytes of SEAD output.

    The SAME derivation BDSP uses, and `pokeldn.ldn.pia5.ldn_session_key` already implements it -
    Sword/Shield's copy is at main.bin 0x17ab010 and it is instruction-for-instruction the shape
    `pia5` describes: seed the xorshift128 with the recurrence around 0x6C078965, take four draws
    into consecutive words, then AES-ECB them under the key at LocalProtocol+0x4d4.

    `seed` is NOT yet known to come from the same place as BDSP's session parameter. What produces
    it is 0x179bff0 -> 0x1774f40, which caches a value computed from LocalProtocol+0x80; until a
    capture says what that is, this function takes the seed rather than an advertisement.
    """
    return ldn_session_key(game_key, seed)


# Sword's local communication id, read off its advertisement. Shield's will differ -
# this is the SWORD title id, and the cartridge the binary was read from is Shield.
COMM_ID = 0x0100ABF008968000

# Where the advertisement keeps what the derivation needs. The SAME offsets as BDSP, which is not
# an assumption: the seed at 12 authenticated all 484 packets of a capture, and the network id at
# 0 is what makes their IVs come out right.
NETWORK_ID_OFF = 0
SESSION_PARAM_OFF = 12


@dataclass
class SessionKeys:
    session_key: bytes
    game_key: bytes
    network_id_le: bytes
    session_param: int

    def __repr__(self):
        return (f"SessionKeys(session={self.session_key.hex()} game={self.game_key.hex()} "
                f"network_id_le={self.network_id_le.hex()} param={self.session_param:#010x})")


def session_keys(net, game_key=GAME_KEY):
    """-> SessionKeys, from a scanned network. `net` needs `application_data`.

    NO VERSION SUBSTITUTION. BDSP builds its game key by replacing four bytes of a
    cryptoKeyDataSeed with the local communication version; Sword/Shield hands Pia the same sixteen
    ASCII bytes at every call site, so the key is the literal and the advertisement contributes the
    seed alone.
    """
    app = bytes(getattr(net, "application_data", b"") or b"")
    if len(app) < SESSION_PARAM_OFF + 4:
        raise ValueError(f"application data is {len(app)} bytes, need at least "
                         f"{SESSION_PARAM_OFF + 4}")
    param = struct.unpack_from("<I", app, SESSION_PARAM_OFF)[0]
    return SessionKeys(ldn_session_key(game_key, param), bytes(game_key),
                       app[NETWORK_ID_OFF:NETWORK_ID_OFF + 4], param)


def packet_iv(keys, source_mac, nonce8, source_id=0):
    """The twelve-byte GCM IV for a version-4 packet - `pia5`'s construction, unchanged.

    Three bytes of crc32(network id || the sender's MAC), then a byte of source id, then the
    packet's own nonce. Measured: every packet a Sword sent us came out with source_id 0.
    """
    return gcm_iv(ldn_nonce_crc(keys.network_id_le, source_mac), source_id, nonce8)
