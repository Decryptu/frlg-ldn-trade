"""FireRed and LeafGreen: everything true of these two cartridges and nothing else.

    .link  the trade room, the Union Room, link battles and the cable club
    .gift  Mystery Gift end to end - the link protocol, the Wonder Card, the composer
    .rom   the console's own code and data: measured addresses, field scripts, native code
    .save  the save file's structs
    .text  the charmap and the Easy Chat vocabularies

The two cartridges share most of their ROM at a per-segment offset; `frlg.rom.leafgreen_twins`
and `frlg.rom.rom_map.LEAFGREEN_DELTA_BOUNDARIES` hold what has been measured. `docs/leafgreen.md`.
"""
