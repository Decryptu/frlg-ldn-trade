"""Speaking Nintendo Switch local wireless (LDN) to Pokemon games.

The package is layered by what a module is TRUE OF, which is the same rule `docs/` uses
(CLAUDE.md, "Where a new finding goes"). Bottom-up:

    pokeldn.ldn      the wireless layer: LDN association, Pia, the transport crypto. GAME-
                     INDEPENDENT - every title on a Switch speaks this. Nothing here may
                     import a game package or carry a game's addresses.
    pokeldn.gba      the GBA wireless adapter's own protocol (AgbRfu/librfu), which a GBA
                     title inside the Switch emulator speaks ON TOP of Pia. Shared by any
                     Gen-3 wireless game.
    pokeldn.frlg     FireRed and LeafGreen, split by what the code is about:
                     .link  the trade room, the Union Room, battles, the cable club
                     .gift  Mystery Gift end to end: the link, the cards, the composer
                     .rom   the console's own code and data: addresses, scripts, native code
                     .save  the save file's structs
                     .text  the charmap and the Easy Chat vocabularies

    config, host_cli, host_support   are game- and layer-neutral: the config file, the
                     shared argument parser, and the launcher helpers.

A NATIVE Switch title (Brilliant Diamond / Shining Pearl and whatever follows) sits directly
on `pokeldn.ldn` with no `pokeldn.gba` beneath it; its game code gets its own package next to
`frlg`. See `docs/bdsp.md`. Entry points are in `bin/`, named for the game they drive.

Imports are ABSOLUTE throughout, so an import line names the layer it reaches into and a
layering mistake is visible in the diff.
"""
