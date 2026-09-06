"""FireRed and LeafGreen's own link protocol, above the RFU layer in `pokeldn.gba`.

The trade room (`trade` joiner, `host_trade` leader), the Union Room (`uroom_chat`,
`uroom_battle`), link battles (`battle_link`), the cable-club colosseum (`cable_club`), the
player record exchanged at entry (`linkplayer`), the overworld link state (`linkstate`), and
the runtimes that own one whole session (`host_app`, `host_session`, `sim`).

`docs/protocol.md` and `docs/joiner_protocol_notes.md`.
"""
