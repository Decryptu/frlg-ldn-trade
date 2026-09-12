"""Let's Go Pikachu and Let's Go Eevee - native Switch titles on Pia, with a link code.

What belongs here is what is true of Let's Go and of nothing else: its Pia header version, its
link code and how the code reaches the advertisement. The LDN passphrase and the Pia game key are
the literals Sword and Shield carry, read out of Let's Go's own binary; they live here as this
title's values, since nothing in `pokeldn.swsh` may be imported by a sibling game package.

Pia and LDN themselves are `pokeldn.ldn`. The header is `pokeldn.ldn.pia4` with version 3. The
addresses behind every value are on `docs/lgpe_session.md`.
"""

from pokeldn.lgpe.session import (APPLICATION_VERSION, CODE_POKEMON, COMM_ID_PIKACHU, GAME_KEY,
                                  MAX_PARTICIPANTS, PASSPHRASE, PIA_HEADER_SIZE, PIA_PORT,
                                  PIA_TAG_SIZE, PIA_VERSION, SCENE_ID, SSID, build_advertise_data,
                                  link_code, packet_iv, parse_advertise_data, session_key,
                                  session_keys)

__all__ = ["APPLICATION_VERSION", "CODE_POKEMON", "COMM_ID_PIKACHU", "GAME_KEY",
           "MAX_PARTICIPANTS", "PASSPHRASE", "PIA_HEADER_SIZE", "PIA_PORT", "PIA_TAG_SIZE",
           "PIA_VERSION", "SCENE_ID", "SSID", "build_advertise_data", "link_code", "packet_iv",
           "parse_advertise_data", "session_key", "session_keys"]
