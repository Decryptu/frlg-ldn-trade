"""The GBA wireless adapter's own protocol, the link layer a GBA title runs ON TOP of Pia.

A Switch-release GBA game is the original ROM inside an emulator, so its wireless traffic is
AgbRfu/librfu carried inside Pia's Reliable protocol 10 - a second link layer that a native
Switch title does not have. Bottom-up: the 14-byte RFU command slot (`rfu`), the emulator's
0x57 frame (`gbaframe`), the leader side of the RFU protocol (`rfu_leader`), NI acknowledged
transfers (`ni`), block transfer (`block`) and the exit/close barrier (`barrier`).

Cited against pokefirered's `link_rfu_2.c` and `librfu_rfu.c`, but the protocol is the
adapter's, so it is shared by any Gen-3 wireless game. `docs/frlg_link_notes.md`.
"""
