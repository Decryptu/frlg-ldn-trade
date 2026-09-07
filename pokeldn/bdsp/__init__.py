"""Brilliant Diamond and Shining Pearl - the first NATIVE Switch title this project speaks to.

What belongs here is what is true of BDSP and of nothing else: the game's own crypto seed, its LDN
passphrase, its local communication id, and the way its advertisement is turned into a session.
Pia and LDN themselves are `pokeldn.ldn` and carry no game's constants; a native title sits
directly on them, with no link layer of its own, so there is nothing between this and `ldn` the way
`gba` sits under `frlg`.
"""

from pokeldn.bdsp.session import (COMM_ID, CRYPTO_KEY_DATA_SEED, PASSPHRASE, PIA_PORT,
                                  SessionKeys, session_keys)
from pokeldn.bdsp.room import JOIN, KEEPALIVE, POS, build_join, build_pos, parse

__all__ = ["COMM_ID", "CRYPTO_KEY_DATA_SEED", "PASSPHRASE", "PIA_PORT", "SessionKeys",
           "session_keys", "JOIN", "POS", "KEEPALIVE", "build_join", "build_pos", "parse"]
