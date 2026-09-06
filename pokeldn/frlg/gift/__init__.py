"""Mystery Gift end to end: the link, the cards, and the gifts we compose for it.

The link protocol (`mg_link`, `mg_server`, `mg_client`, `mg_script`, `mystery_gift`) and the
hosts that drive it (`host_mystery_gift`, `host_mg_app`); the payloads (`wonder_card`,
`wonder_news`, `ereader_trainer`, `stamp_rally`); and the composer that turns a gift
definition into bytes (`gift_composer`, `gift_registry`, `wonder_card_events`,
`gift_artifact`, `gift_to_bin`). `game_data_log` keeps what each session's console told us
about itself.

`docs/mystery_gift.md`. The Mystery Event VM a card can carry is `pokeldn.frlg.rom.mystery_event`.
"""
