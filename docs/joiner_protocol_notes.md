# Joining as the child: what the console actually does

Findings for the JOINER direction (`frlgtrade.py --live`), where the Switch hosts and this program
is the RFU child. Everything here was measured on retail hardware or read out of the
[pret/pokefirered](https://github.com/pret/pokefirered) decompilation, and each claim cites its
source. The GBA release on Switch runs the original ROM inside an emulator, so the decomp is
authoritative for the whole game-level protocol (RFU commands, link tasks, union room, trade room,
seating); only the LDN/Pia wireless layer below it is the emulator's own.

## One child slot per parent poll. Never more.

`RfuMain2_Parent` keeps exactly ONE child slot per poll in `gRfu.childRecvBuffer[i]` - the adapter
overwrites it - and compares its rolling `childSendCmdId` tag against the last one it kept
[`link_rfu_2.c:876-892`]. A tag that is not exactly `+1 mod 8` increments `numChildRecvErrors[i]`,
and `> 4` calls `RfuSetErrorParams` and kills the link. The `else` branch resets that counter to 0
on any good tag, so death needs five CONSECUTIVE bad polls.

A second slot inside one poll is therefore not "faster", it is a guaranteed dropped tag. Measured,
survival in the trade room scales inversely with how far past one-per-poll the child goes:

| child emission | console kept polling for |
|---|---|
| free-running (~57/s against its ~55/s) | 0.10 s |
| 2 slots per poll | 0.28 s |
| 1 slot per poll | 5.8 s |

Nothing is exempt, including the seat walk.

## A tile step is exactly 16 link updates

`FacingHandler_DpadMovement` sets `objEvent->directionSequenceIndex = 16`;
`MovementStatusHandler_TryAdvanceScript` decrements it once per link update while the key is ignored
(`MOVEMENT_MODE_FROZEN`) [`overworld.c:3432-3470`]. So one tile is 16 updates start to finish, and a
run of N direction keys leaves `N mod 16` of its last step already spent.

Consequences for a scripted walk: the EMPTY gap after a direction run only needs to cover
`16 - (N mod 16)`, not a full 16. Overshooting a gap is harmless (a direction sent while frozen is
ignored, and the run's remaining keys retry it) but costs a slot per update, and slots are the
scarce resource.

## The player's inputs are not always transmitted

`UpdateHeldKeyCode` rewrites EMPTY, all four DPAD codes, START and A to `LINK_KEY_CODE_NULL`
whenever `GetLinkSendQueueLength() > 1` [`overworld.c:2786-2810`], and `SendKeysToRfu` then sends
nothing at all. A walking player goes silent under queue pressure and looks parked.

`LINK_KEY_CODE_READY` (0x16) is NOT in that list, so a console that reaches its seat always
transmits its READY. Do not build a gate on the ABSENCE of DPAD codes; do build one on 0x16.

## The seat is a mutual barrier, and the standby rounds come after it

`Task_EnterCableClubSeat` shows "Please wait", calls `SetInCableClubSeat()` (which makes the next
held-key emission `LINK_KEY_CODE_READY`), then spins on `GetCableClubPartnersReady()`
[`cable_club.c:827-869`]. That returns `CABLE_SEAT_SUCCESS` only when
`AreAllPlayersInLinkState(PLAYER_LINK_STATE_READY)` [`overworld.c:2988-2999`] - ALL players. Only
then does it hand off to `Task_StartWirelessTrade`, whose `SetLinkStandbyCallback()`
[`cable_club.c:910-943`] is where the post-seat standby rounds come from.

So: drive the post-seat rounds only once both players are READY. Driving them at a console still in
`CABLE_SEAT_WAITING` faults its seat FSM.

## What a real child sends, end to end

Recorded off a retail French FireRed acting as the CHILD against this repo's own host, full trade
(`HostTradeEngine.child_slot_runs()`, printed by `host_app`):

```
IDLE x8
SEND_BLOCK_INIT w1=0x0011 x4   + 17 fragments      (LinkPlayer, 0x11 = 17)
IDLE x31
SEND_BLOCK_INIT w1=0x0009 x4   + 9 fragments       (trainer card)
IDLE x262   READY_EXIT_STANDBY w1=0x0000 x1
IDLE x72    READY_EXIT_STANDBY w1=0x0001 x1
IDLE x45    <room: SEND_HELD_KEYS 0x1b x24, EMPTY, 0x1a once, the walk, READY, then EMPTY x13>
IDLE x22    READY_EXIT_STANDBY w1=0x0002 x1
IDLE x28    READY_EXIT_STANDBY w1=0x0003 x1
IDLE x75    -> the host pulls the party
```

Two properties are easy to get wrong:

* **Each standby round is ONE frame.** Not a burst. Over a link with a reliable transport underneath
  (Pia Reliable here) that single frame is retransmitted until it lands, which the GBA-to-GBA link
  could not do. Repeating the count only shows the host a round it has already completed.
* **The child is fully IDLE between rounds.** All-zero `gSendCmd`, not an EMPTY held-keys keepalive.
  The leader's quiet-frame counter before the party exchange only advances on a slot that is exactly
  idle, so a keepalive there deadlocks it.

The room-load prefix (`SEND_HELD_KEYS 0x1b` = HANDLE_RECV_QUEUE x24, then `0x1a` = IDLE once) is the
child's own queue housekeeping. `LINK_KEY_CODE_IDLE` is what sets `sPlayerLinkStates[player] = IDLE`
on the peer [`overworld.c:2755`], and the tile-script branch of `HandleLinkPlayerKeyInput` only runs
for a player in state IDLE.

## Both sides only advance when they have heard from the peer

`CB1_UpdateLinkState` runs `UpdateAllLinkPlayers` only when `!IsRfuRecvQueueEmpty()`, and that
function does not inspect a queue at all - it returns FALSE if any `gRecvCmds` entry is non-zero
[`link_rfu_2.c:787-800`]. Since `MoveSendCmdToRecv` copies the parent's own `gSendCmd` into
`gRecvCmds[0]` and clears it, the parent can self-sustain; but in practice the loop settles into one
exchange per round trip. Measured on a healthy link: 182 out->in alternations against 182 in->out,
with only 22 in->in and 27 out->out.

A useful diagnostic falls out of this. The host's `SEND_HELD_KEYS` high byte is `heldKeyCount`,
incremented once per prepared command, so the last value it sends is exactly how many link updates
its trade room survived - a clock independent of wall time and of the child's slot rate. Comparing
it against the frames actually received also shows how far its game loop outran the wire; on every
run that made progress the ratio was exactly 1.0x.

## Version and language are not gates

`IsTryingToTradeAcrossVersionTooSoon` [`union_room.c:1499`] fires only when the partner is neither
FireRed nor LeafGreen, and it prints an in-game message rather than dropping the link. Cross-version
FR<->LG trading is confirmed working on hardware. The only language branch on the link path is
`ConvertInternationalString`, which special-cases Japanese and nothing else; a French FireRed accepts
an English Wonder Card.
