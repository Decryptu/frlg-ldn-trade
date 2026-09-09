"""The save file's structs, as the game lays them out.

`mon` is the 100-byte party Pokemon (80-byte BoxPokemon plus the derived tail), `stats` and
`basestats` derive that tail, `battle_mon` is the battle-side struct, `mevent_pokemon` the
shape a Mystery Event `givepokemon` payload carries, and `save_inject` the sector format the
console commits to flash. `docs/frlg_rom.md`.
"""
