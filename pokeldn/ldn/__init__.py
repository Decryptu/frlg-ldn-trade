"""The wireless layer, GAME-INDEPENDENT: LDN association, Pia, and the transport crypto.

Layers, bottom-up: UDP :12345 (`transport`) -> zstd + AES-GCM (`crypto`) -> Pia connection
(`pia_connect`, Pia 6.32+; `pia5`, Pia 5.27-5.45) -> Pia message + Reliable (`reliable`).
`sead` is Nintendo's own RNG, which Pia's LDN session key is built on.
`host_pia` is the leader-side peer controller, `beacon`/`host_beacon` the advertisement a
console discovers us by, and `joyspot_discovery`/`joyspot_probe` the discovery-only paths.

Read `docs/ldn.md` and `docs/pia.md` before changing anything here. Do NOT put a game's
addresses or a game's payload shapes in this package - they go in that game's own.
"""
