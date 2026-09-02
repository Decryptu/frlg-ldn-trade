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


## Post-seat standby gate and walk-out (measured 2026-09-02, j81/j82)

- After BOTH players sit, the console (leader) broadcasts its own `READY_EXIT_STANDBY` count=2 at
  mpId 0 about 130ms after it reflects ours. Its receive gate accepts a child count only when it
  equals its own (`Rfu_LinkStandby` recv gate, `link_rfu_2.c:1577-1591`), so a count=3 sent on the
  reflection of our count=2 is ignored. The reflection of a child slot proves the parent saw it,
  not that it completed the round. Gate count=3 on the host's OWN mp0 count=2, and keep re-arming
  it, spaced by more than the 75 idle slots the leader needs before `BufferTradeParties`.
- The walk-out: the host emits `LINK_KEY_CODE_EXIT_ROOM` (0x17) and blocks in
  `KeyInterCB_WaitForPlayersToExit` until `AreAllPlayersInLinkState(EXITING_ROOM)`
  [`overworld.c:2962-2981`]. The child must answer with its own 0x17 on the held-keys stream; an
  all-zero child slot is not a key and the host waits forever.
- Transport: the Switch host drops ~40% of the child's Pia datagrams inside its own stack after
  MAC-acking them (passive-monitor measurement), independent of spacing, timing, size or content.
  Pia delivers in order, so each drop stalls the child's whole stream for an RTO. Repeating every
  reliable data frame in the next few datagrams (the host de-duplicates by seq) removes the stalls.

## The emulator can close the link on its own: `svc_51` (REVISION >= 0xA)

**This is not game logic. It is the Switch emulator, and it is polled every frame.**

`HandleLinkConnection` runs this on the Switch build only [decomp:src/link.c:1654]:

    #if REVISION >= 0xA
        bool32 reloadOrReset = FALSE;
        if (svc_51())
        {
            if (!FuncIsActiveTask(Task_WirelessCommunicationScreen)
                && (InUnionRoom() || gReceivedRemoteLinkPlayers != 0 || Rfu_IsMaster() <= MODE_PARENT))
            {
                reloadOrReset = TRUE;
            }
            CloseLink();
        }
    #endif

`svc_51` is a bare `swi 0x51` whose return value comes from the emulator
[decomp:src/sloopsvc.c:120, "Called by HandleLinkConnection"]. When it returns nonzero the ROM
calls `CloseLink()` immediately, and then [decomp:src/link.c:1674]:

    // If active task is mystery gift then soft reset, otherwise reload the save.
    if (FuncIsActiveTask(Task_MysteryGift)) RfuSoftReset();
    else RfuReloadSave();

**So during Mystery Gift, the emulator deciding to drop the link SOFT RESETS the game.** That is
the 2318-0006 the user sees, and it is why our captures show our own side clean at the instant the
console leaves: no game-level condition was violated. Nothing in `gSendCmd`, the reliable window,
the tag sequence or the K-ack stream can explain a drop that the ROM did not decide to make.

The GBA original has none of this - the whole block is `REVISION >= 0xA`. Every timing gate we
tune (`client_ready_idle_frames`, `inter_block_gap_frames`, the standby barrier) is game-level, and
`svc_51` sits underneath all of it.

What makes `svc_51` return nonzero is inside the emulator and is NOT in the decomp. It is almost
certainly LDN/Pia session state - the layer `frlgsim/pia_connect.py` reimplements - which makes the
Pia session (keepalives, RTT liveness, session update sequencing) the place to look for the
semi-random quits, not the RFU command stream.

### The rest of the emulator's RFU surface, for orientation

| SVC | Called from | What it does |
|---|---|---|
| `swi 0x45` | `librfu_rfu.c:667,749` | hands the emulator `gRfuLinkStatus` (it READS our link state) |
| `swi 0x49` | `AgbRfu_LinkManager.c:657` | while nonzero, holds `connect_period` open during SEARCH_CHILD (cap `connect_period_initial < 300`) |
| `swi 0x4a` | `AgbRfu_LinkManager.c:720` | same, during SEARCH_PARENT |
| `swi 0x4b` | `link_rfu_2.c:2114`, `union_room_player_avatar.c:518` | `SVC4B_EXIT_EARLY` bails out of SpawnGroupLeader; `SVC4B_RESEED_RNG` reseeds from the host's trainer id |
| `swi 0x51` | `link.c:1654` | **close the link now** (soft reset under Mystery Gift) |
| `swi 0x53` | `wireless_communication_status_screen.c:328` | emulator-driven exit from the status screen |

`svc_49`/`svc_4a` prove the emulator is an active participant in RFU timing, not a passive host: it
can extend the discovery window past what the ROM would allow. Assume the same kind of authority
everywhere else on this list.

### What this does NOT explain

It does not say WHY the emulator drops us. It relocates the question from the RFU command stream to
the Pia/LDN session, and it means a run that dies with our side clean is evidence about the session
layer, not about the game protocol. Do not tune game-level frame counts against these deaths -
2026-09-02 spent 28 hardware runs doing exactly that and measured nothing (3/13 at
`client_ready_idle_frames=20` vs 2/13 at 120, indistinguishable).

### RESOLVED (2026-09-02, session 10): the culprit was a BROADCAST Pia handshake message

The svc_51 pointer above ("look at the Pia session, not the RFU stream") was correct, and the
specific cause is now found. The **type 5 Update Session** - the message the console must receive
before it answers with the type 6 ACK that finalizes its Pia session - was being sent BROADCAST only
(`host_pia._send_session_acceptance`). The Switch receives only ~1 in 5 of our broadcast data frames
(the same loss that made the Net 0x11 connection request slow until af73f0e unicast it). So on ~2 in
3 attempts the console never cleanly received the type 5 in time, its Pia session never fully
finalized, and the emulator's svc_51 watchdog dropped the link 3.0/3.6s (180/216 frames) after the
join - the "semi-random 3s quit".

Fix: `host_pia` now ALSO sends the type 5 unicast to each joined station (commit on fork/main;
broadcast is still sent, so the change is purely additive). Measured the same session, same consoles:
Mystery Gift on the FireRed went 1/4 -> 4/4, the LeafGreen delivered first try (it had logged 40+
straight deaths on this message the day before), and a full two-round host-direction TRADE completed
clean. That is why session 9's "nothing we control changes the rate" and the 28-run
`client_ready_idle_frames` A/B measured nothing: they compared runs where finalization HAPPENED, but
the failure is the console MISSING the broadcast entirely - those runs have no finalize to compare.

Still true: game-level frame-count tuning against these deaths is pointless (the watchdog is below
it), and the emulator can still drop a link for other Pia-session reasons. But the dominant cause of
the wall is fixed. The remaining known MG failure is the separate ident-25 fragment stall.
