"""Inside the console: its own code and data, every address read off the hardware.

`rom_map` is the ledger of measured addresses; `thumb` and `decomp_source` are how a dump is
read as code; `scrcmd*`, `special_names`, `scrcmd_names`, `symbol_names` and `worker_names`
name the four function tables and their operands; `leafgreen_twins` holds the second
cartridge's copy of each. Native code is `buffer_script` + `buffer_payloads` (generated) and
`native_script` + `field_stubs` (generated); the Mystery Event bytecode is `mystery_event`;
the RNG is `lcg`, `rng_script` and `rng_countdown`.

`docs/inside_the_console.md`, `docs/buffer_script.md`, `docs/rng.md`, `docs/mystery_event.md`.
An address belongs here only once a run has measured it - keep FACT and HYPOTHESIS apart.
"""
