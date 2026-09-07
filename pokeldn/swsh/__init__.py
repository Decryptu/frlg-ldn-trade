"""Sword and Shield - a NATIVE Switch title whose Mystery Gift has a local-wireless branch.

What belongs here is what is true of Sword/Shield and of nothing else: its LDN passphrase, its Pia
game key, its Pia protocol version and the shape of its header. Pia and LDN themselves are
`pokeldn.ldn` and carry no game's constants. Like `bdsp`, this sits directly on `ldn` with no link
layer of its own - there is no `gba` beneath it.

Nothing here has been on the air yet. `docs/swsh.md` says what is FACT, what is deduced and what is
still open.
"""

from pokeldn.swsh.session import (GAME_KEY, PASSPHRASE, PIA_HEADER_SIZE, PIA_PORT, PIA_TAG_SIZE,
                                  PIA_VERSION, session_key)

__all__ = ["GAME_KEY", "PASSPHRASE", "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE", "PIA_VERSION",
           "session_key"]
