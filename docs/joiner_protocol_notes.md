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

## Post-seat standby gate and walk-out

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

## The emulator can close the link on its own: `svc_51` (REVISION >= 0xA)

This is not game logic. `HandleLinkConnection` runs it on the Switch build only
[decomp:src/link.c:1654]:

    #if REVISION >= 0xA
        if (svc_51())
        {
            ...
            CloseLink();
        }
    #endif

`svc_51` is a bare `swi 0x51` whose return value comes from the emulator
[decomp:src/sloopsvc.c:120]. When it returns nonzero the ROM calls `CloseLink()` and then, if
`Task_MysteryGift` is active, `RfuSoftReset()`, otherwise `RfuReloadSave()` [decomp:src/link.c:1674].
That soft reset is the 2318-0006 the user sees. A run that dies with our side clean at the RFU level
is evidence about the LDN/Pia layer, not the game protocol; game-level frame counts cannot move it.

The rest of the emulator's RFU surface:

| SVC | Called from | What it does |
|---|---|---|
| `swi 0x45` | `librfu_rfu.c:667,749` | hands the emulator `gRfuLinkStatus` |
| `swi 0x49` | `AgbRfu_LinkManager.c:657` | while nonzero, holds `connect_period` open during SEARCH_CHILD |
| `swi 0x4a` | `AgbRfu_LinkManager.c:720` | same, during SEARCH_PARENT |
| `swi 0x4b` | `link_rfu_2.c:2114`, `union_room_player_avatar.c:518` | `SVC4B_EXIT_EARLY` bails out of SpawnGroupLeader; `SVC4B_RESEED_RNG` reseeds from the host's trainer id |
| `swi 0x51` | `link.c:1654` | close the link now (soft reset under Mystery Gift) |
| `swi 0x53` | `wireless_communication_status_screen.c:328` | emulator-driven exit from the status screen |

## The 3-second wall

The console, as our station, deauthenticated (802.11 reason 3, "STA is leaving") 3.0-3.8s after its
LDN association on 40-60% of runs, both consoles, trade and Mystery Gift, in whatever handshake
phase the run was in at that instant. The clock runs from the association, not from any Pia
milestone (120 host runs: finalized at 2.84s and left at 2.98s; finalized at 3.86s and lived). Two
real consoles never wall. Outcomes clustered in streaks. Everything decodable on the wire was
identical between a delivered run and a walled one up to the deauth.

Two causes were found, in order:

1. **The Pia type 5 Update Session was broadcast only.** The console receives ~1 in 5 of our
   broadcast data frames, so it often never finalized its Pia session in time. `host_pia` now also
   unicasts it to each joined station (broadcast still sent). Mystery Gift on the FireRed went 1/4
   to 4/4 in the same session, and it removed one trigger without closing the wall (~40-50% residual).
2. **The probe and association responses omitted the mandatory OFDM rates.** The bare set was
   1B 2B 5.5B 11B 18 24 36 54. Advertising the Switch host's set, 1B 2B 5.5B 11B 6 9 12 18 with
   extended rates 24 36 48 54, passed the wall 20/20 across both consoles against 3-4/8 for the bare
   set, alternating one variable at a time in one afternoon. The rate set alone is sufficient; the
   Switch's other beacon and association elements (DTIM 2, ERP, capability 0x411, the Nintendo vendor
   element, HT/HE, WMM) are not needed. `vendor/LDN/ldn/wlan.py` sends the full set unconditionally.

Why the emulator's watchdog is satisfied by the fuller rate set is not proven. Measured offline on
2026-09-03 from the air captures of the experiment (`scratchpad/rates3s.py`, walled lg96/98/102/105
against passed lg95/117 bare and lg106/112/113/114 with the Switch set, first 2.9-4s after association):

- FACT: the console copies our advertised rates into its association request. Bare set: it lists
  exactly `1 2 5.5 11 18 24 36 54`. Switch set in the probe response: it lists `24 36 48 54`, our
  extended-rates element alone. That list is what `wlan.py` hands nl80211 as the station's rates, so
  it bounds our own unicast TX rates; level 4 passed the wall with the bare-looking list (lg106), so
  our TX rate mask is not the lever.
- FACT: nothing else on the air differs. Console data at 54M or HT MCS, retries 0-5%, RTS before
  every data frame at 24M, ACKs to us at 24M, the deauth at 3.06-3.63s reason 3 with the same frame
  mix before it. The sampled `tx bitrate` of our station entry is 18M or 54M in both sets.
- FACT: the console accepted every reliable Pia frame we sent before it left. `first3s.py` shows 0
  Pia-level retransmits in either direction and 0 decode failures inside the first 2.9s of every
  walled run. The leave is not caused by data loss; the Pia session is healthy when the console
  decides to go.

DEDUCTION: the trigger lives inside the console's wlan/LDN layer, takes the advertised rate set as its
only input, and is not visible on the wire. HYPOTHESIS (untested): the console's driver checks link
statistics on a ~3s timer after association, and with a rate table that lacks the mandatory OFDM
rates 6/12 the check fails on whichever runs had a retry that fell back below 18M. Which of 6, 9, 12
is required is UNKNOWN; each candidate needs ~8 hardware runs against the 40-60% baseline.

Two things that looked like the wall and were not:

- Level 1 (Switch elements including WMM) "stalled the handshake": the console switches to QoS data
  frames once the AP advertises WMM and the vendored decoder rejected subtype 8. Fixed; QoS data decodes.
- Levels 3 and 5 "broke association": the probe response dropped its RSN element while the
  capability word advertised privacy. Fixed; RSN is in every response.

## Console as a Pia child: what it needs from a host

Measured with the receive client (`frlgmg_client.py`, run mc1) against a real Mystery Gift host,
and against our host with the type 2 disabled:

- The console child does not finalize on a type 5 Update Session alone. It re-sends its join request
  every 0.5s, ignores unicast type 5 copies, and leaves 3.05-3.20s after its join. The type 2 Join
  Response is required.
- A real Mystery Gift host sends a real console child its type 5 within ~50-66ms of its Net 0x11
  (passive two-console captures). To our client it sent no type 2 and held the type 5 for 2.03s,
  sending only RTT probes every 316ms meanwhile; the difference in our join request is not identified.
- A real trade host sends type 5 and type 2 within 34ms and originates RTT only after finalization.
- Our adapter, as the console's station, stayed associated for the full 31s; the console never used
  svc_51 against us as a child.

Timeline of the real Mystery Gift host (times from its Net 0x11, `scratchpad/pia_msgs.py`):

    0.000  Net 0x11 (once)
    0.006  us: Net 0x12 + Session join
    0.252  RTT request, then every 316ms (6 probes, nothing else)
    2.038  Session type 5, no type 2 ever
    2.040  us: type 6 (finalize); 2.159 reliable open
    2.318  host 'A' frame
    4.63   host's own NI (join status = the user's YES on the console)
    6.82   SEND_PLAYER_IDS, 6.87 BLOCK_REQ (2.2s after the YES: delayTimerAfterOk 120f + WaitRfuState)
    8.15   Net 0x50 property update every ~0.5s, acked 0x51

## Transmission-phase deaths after the card (Mystery Gift host)

Every death after the card showed the host's UDP output peaking at 52-519 datagrams per 0.25s where
every delivery peaked at 23-36. The mechanism: a 250ms-3s adapter TX stall (frames sat in the
rtw88 USB path; the host process never paused), no acks, every unacked frame due and re-sent every
tick, a flood the console never recovers from. Four host fixes, all on by default:

- `HOST_RTX_LIMIT` caps Reliable retransmits per VBlank.
- `FRLG_ECHO_MAX` bounds the FIFO echo of the child's block slots, which lagged the console ~0.5s
  (60.4 vs 58.7 slots/s) and made it re-send fragments of its READY_END block for a second.
- The TX socket is non-blocking and `FRLG_QUIET_GATE_MS` holds retransmits and carry-forward while
  the console is silent: it pauses ~0.5s after accepting the card (its flash save), and a blocking
  send during that pause froze the host 6-11s.
- A duplicate child message no longer crashes the host receiver.

The adapter stall itself is unexplained. rtw88's USB path queues without back-pressure; VM USB
passthrough is a candidate.

## The ident-25 stall

The console sometimes goes idle after our last delivery-script block (ident 25, `MG_LINKID_RAM_SCRIPT`)
and never sends ident 20 (READY_END), then leaves. A parent block is never reflected by the child, so
the lost fragment is invisible in the capture. Sending the ident-25 block three times
(`--ram-script-block-repeat 3`) took the console that was stalling to 5/5. Not proven to be air
loss rather than the console's post-Pia RFU-to-game handoff dropping a fragment; the redundancy
covers both. `--block-repeat 1` is measurably worse.

## 802.11 layer facts

- Console as station: no power save (PM bit 0 on every frame), RTS before every data frame, a clean
  mid-stream deauth with no probe or null frames before it.
- rtw88 (kernel 7.0) sends management frames at the lowest BSS basic rate and beacons at 1M
  unconditionally; injected action frames have no vif and go at 1M. A Switch host beacons at 11M
  and sends data at 48-54M.
- The monitor vif's copy of our own frames carries mac80211's intended rate (software loopback), so
  air captures cannot measure our TX rate.
- The Switch host drops ~40% of the child's Pia datagrams inside its own stack after MAC-acking them,
  independent of spacing, timing, size or content. Pia delivers in order, so each drop stalls the
  child's stream for an RTO; repeating every reliable data frame in the next few datagrams removes
  the stalls (the host de-duplicates by sequence).
- LDN allows 5 GHz channels 36/40/44/48 and the host can use them, but the FRLG app scans 2.4 GHz only.

## Pia header nonce is a counter the console enforces

The console keeps, per channel, the last accepted 8-byte header nonce (big-endian) and drops any
datagram whose nonce is not strictly above it (upstream tornadus 5a5a138). The joiner used a random
nonce, which passes that test about half the time. Measured with `scratchpad/rtx_analyze.py` and
`decode.py`'s duplicate-delivery line:

    j86-j88 (random):   ~1.1 duplicate outgoing reliable deliveries per unique frame, ~0.3 inbound
    j89     (counter):  0.34 outgoing, 0.00 inbound; the user called the trade "much smoother"

The inbound duplicates were the console retransmitting because our acks were being dropped too.
`Sim._next_nonce` now counts; the host already did (`native_nonce_sequence = true`). This is also
what the "~40% silent drop inside the console" behind the carry-forward and the reply holdoff was.

## Carry-forward stays at 4 on both sides

With the counter nonce the remaining joiner duplicates are the carry-forward (each reliable frame
repeated in the next 4 datagrams), acked ~17ms after the original. It still earns its place: air
loss is 1-2% and bursty, and Pia delivers in order, so a hole holds every later slot back and the
console's 8-deep RFU receive queue overflows when it fills.

    h5, host carry 0: parent slot seq 954 lost with its 68ms retransmit; the 137ms one landed; the
        console received ten slots at once and disconnected 300ms later (type D, LEAVE reason 3),
        "erreur de connexion" on screen, during the mail block.
    h4, host carry unlimited (a [-0:] slicing bug at depth 0, since guarded): clean.
    j90, joiner carry 0: clean, but zero trade-phase loss, so it proves nothing.

The console's own child-side retransmit rate is ~0.01-0.02 per frame in every host capture: that is
the real air loss, and what a single-copy sender is up against. `scratchpad/host_rtx.py` measures a
host capture, `rtx_analyze.py` / `rtx_where.py` a joiner one.

## One-sided cancel returns both sides to the menu

`PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE` go through `CB_HandleTradeCanceled` ->
`CB_MAIN_MENU` [trade.c:2094-2113]; only `BOTH_CANCEL_TRADE` ends the session [1715-1722]. The joiner
now re-enters S4_PARTY and selects again after 60 frames (upstream 3eaf381). On the host, answering
every `REQUEST_CANCEL` at SELECT with `PARTNER_CANCEL_TRADE` looped the console on "votre ami veut
échanger des Pokémon" (h6: two cancels, two identical prompts, then a normal trade still worked). A
second consecutive CANCEL now makes the leader cancel too, `BOTH_CANCEL_TRADE`, and the exit path
runs (h7: cancel, A, cancel, both walk out, link closed, console left LDN).

## The ident-25 stall: a hole plus an unbounded backlog (lg150, 2026-09-03)

Mystery Gift host, LeafGreen. Two consecutive frames (seq 927, 928) were lost at 18.78s. The console's
cumulative ack stayed at 927 for 1.75s and it sent no bulk ack at all in that time, while its own data
kept flowing at 45-62 datagrams/s. We re-sent 927 and 928 in every datagram (about 100 copies) and kept
emitting new frames behind them, five per datagram with carry-forward. When the console finally acked
at 20.53s it held 927, 928 and 960-969 only; the mask then filled at 30-80 frames per 50ms, and at
21.00s the hole closed and the console released 97 frames to the game in one datagram (97 K acks,
acked_ts 973-1069). Its RFU receive queue is 8 deep (h5): the ident-25 fragments in that release were
dropped, the block never completed, and the console sat on "Transmission..." for 150s with no timeout.

FACT: the console accepted nothing from us for 1.75s although every datagram carried the frame it
was waiting for. DEDUCTION: with the backlog behind the hole the console had no room to take the
retransmit either; the hole is self-sustaining as long as new frames keep arriving. FACT: the normal
ack lag is 0-1 frames at 99% of acks (lg149: 1180 acks, one at 7; lg150 before the hole: one at 10).

Fix: `HostSession` holds new frames while the console has not cumulatively acked
`HOST_OUTSTANDING_MAX` (6) frames, keeps retransmitting the gap, and resumes when the ack catches up.
A closed hole then releases at most 6 frames. Measured tools: `scratchpad/ack_trace.py` (bulk acks and
masks), the K-per-datagram count over `host_decode.py` output (97 vs max 3 in lg149).

## Why the Union Room NPC cannot see our host (decomp, 2026-09-03)

The middle NPC on Pokemon Center 2F is the Union Room; the third NPC is the wireless club trade
centre. Every run so far has used the third NPC, and CLAUDE.md recorded the middle NPC's blindness as
a bare observation. The decomp gives the mechanism, with no hardware run spent.

FACT: a console standing in the Union Room advertises `ACTIVITY_SEARCH` (12) and searches with
`LINK_GROUP_UNION_ROOM_INIT`:

    SetHostRfuGameData(ACTIVITY_SEARCH, 0, FALSE);   [src/union_room.c:3549]
    CreateTask_SearchForChildOrParent(..., LINK_GROUP_UNION_ROOM_INIT);   [src/union_room.c:3565]

FACT: that group's accept list holds exactly one activity, and `IsPartnerActivityAcceptable`
[src/union_room.c:1590] walks it and returns FALSE for anything absent:

    sAcceptedActivityIds_Init[] = {ACTIVITY_SEARCH, 0xFF};   [src/data/union_room.h:419]

DEDUCTION: our trade host advertises `ACTIVITY_TRADE` (4) and our Mystery Gift host
`ACTIVITY_WONDER_CARD` (21). Both are rejected by that filter before the group list is drawn, so the
console never had a chance to list us. This is a filter on the advertised activity alone, not a
different transport, a different discovery service or a Pia-level difference.

FACT: once players are inside the room the search switches to `LINK_GROUP_UNION_ROOM_RESUME`
[src/union_room.c:2664], whose list is `IN_UNION_ROOM | activity`
[src/data/union_room.h:407-418], with `IN_UNION_ROOM` = `1 << 6`
[include/constants/union_room.h:49]. That bit fits inside our hardware-proven
`SEARCH_ACTIVITY_MASK` (0x7F), so both forms are expressible in the record we already build.

Implemented offline: `beacon.ACTIVITY_SEARCH` / `beacon.IN_UNION_ROOM`,
`host_beacon.build_union_room_app_data(profile, session_id, activity=None)`, the `union_room`
`HostOptions` field and `frlgtrade_host.py --union-room`. `tests/test_union_room_advertisement.py`
(7 tests) pins the constants against the decomp, checks the advertisement carries `ACTIVITY_SEARCH`
with `startedActivity` and the wonder flags clear (matching the console's own
`SetHostRfuGameData(ACTIVITY_SEARCH, 0, FALSE)`), checks the resume form round-trips, checks every
other captured byte is identical to the trade advertisement, and drives the real
`HostApplication._build_components` to confirm the flag changes what reaches the transport.

HYPOTHESIS, untested: with `--union-room` the middle NPC lists us. UNKNOWN: what the console expects
after it joins. The Union Room is a persistent room with avatars, chat and `ACTIVITY_PLYRTALK`
negotiation, not the trade centre's straight-to-trade flow, so being listed is very unlikely to be
enough to reach a trade. Being listed at all is the single thing the next run should test.

### The Union Room connect, on hardware (u01-u04, 2026-09-03)

FACT (u01, u02): advertising `IN_UNION_ROOM | ACTIVITY_TRADE` (0x44) spawns the PkCamp avatar in the
room, and talking to it prints "Communication avec PkCamp" then "le DRESSEUR est occupe" with **not one
packet from the console on the air**. The whole capture is our own beacons; `pia_msgs.py` finds no Pia
message at all.

DEDUCTION, then confirmed: `IsPartnerActivityIncompatible` [src/link_rfu_2.c:2925] tests

    else if (partner->activity != IN_UNION_ROOM)   // [link_rfu_2.c:2933]
        return TRUE;

as an **exact equality**, so any activity bits beside IN_UNION_ROOM fail it. The connect is refused
inside `Task_TryConnectToUnionRoomParent` [link_rfu_2.c:2963] before the RFU layer transmits, which is
why the air is silent. The trade intent is carried in `sPlayerCurrActivity` and negotiated after the
link is up (UR_STATE_SEND_TRADE_REQUST), never advertised.

FACT (u03, u04, two runs, identical): advertising the bare `IN_UNION_ROOM` (0x40) connects. The console
joins LDN, completes the Pia Session join, answers RTT liveness, sends its RFU identity, and we reach
H_LINK_PLAYER. It then sends the RFU disconnect 'D' 0.1-0.2s after our join-status NI and leaves.
Pia is healthy to the last frame (RTT req/rsp still flowing, no loss), so the 'D' is a game-layer
rejection, not a transport failure. u03 and u04 die at the same point with the same frame shape.

FACT: the game-layer traffic in u03 is 32 gba frames against 13413 in the good trade-centre run h8.
In u03 we send NI_S, NI, NI_E, then `0x47`, then a **second** NI_S and a burst of repeated NI frames
(seq 65530-65533) before the console answers 'D'.

UNKNOWN: why the console rejects that NI stream. The two candidate readings are (a) the second NI
transfer is wrong here and the union room expects a single one, (b) the union room's post-connect
protocol differs from the trade centre's and our H_LINK_PLAYER state machine is simply the wrong
conversation. Do not conclude between them without evidence.

What the console expects after the connect [src/union_room.c:2858-2879]:

    if (gReceivedRemoteLinkPlayers) {
        CreateTrainerCardInBuffer(gBlockSendBuffer, TRUE);
        CreateTask(Task_ExchangeCards, 5);
        uroom->state = UR_STATE_COMMUNICATING_WAIT_FOR_DATA;
    }
    ... then, if sPlayerCurrActivity == (ACTIVITY_TRADE | IN_UNION_ROOM),
        UR_STATE_SEND_TRADE_REQUST

DEDUCTION: the Union Room is not a separate transport. It is the ordinary link plus a **trainer card
block exchange** (`Task_ExchangeCards`) in front of the trade request. Step 1, the LinkPlayer exchange
that sets `gReceivedRemoteLinkPlayers`, is code the trade host already has and is where u03/u04 die.
Step 2 (trainer card) and step 3 (trade request) are unwritten.

Also FACT, free observations: the avatar tracks our beacon live (it walked out and back in when the
host was restarted mid-session) and it animates/walks. The room's player list is not a snapshot taken
at entry.

### Why the Union Room console rejects our NI (u03/u04 analysis, offline)

Ruled out first, so they are not re-investigated: the NI framing is NOT anomalous. The
`NI_S/NI/NI_E -> 0x47 -> second NI_START` shape and the `n=1 sz=5` + `n=2 sz=2` pair are identical in
h8, the proven trade-centre run. The rising `mid` in the K frames before the 'D' is also normal
(h8 uses mid 1-8 throughout). Both looked like leads and are not.

FACT, from `host_decode.py` on u03 against h8 at the same point: the handover is correct (child's
terminal NULL -> 'G' link-state 1 -> parent NI). The console mirrors both our NI_STARTs
(`T NI_START ack=1 n=1`, then `n=2`). It then **never mirrors a single NI body frame**: we re-present
`T NI n=1 ph=0 sz=1` at ts=8,9,10,11,12 and the console answers only with K frames, then sends 'D'.
In h8 the console mirrors each NI body frame with `T NI ack=1 n=1 sz=0` within ~17ms.

DEDUCTION: the union-room child is not listening for a parent join-status NI at all.
`Task_UnionRoomListen` [src/link_rfu_2.c:505] reaches `RFUSTATE_UR_PLAYER_EXCHANGE` [:533], which does

    rfu_UNI_setSendData(1 << gRfu.childSlot, gRfu.childSendBuffer, sizeof(gRfu.childSendBuffer))
    gRfu.parentChild = MODE_CHILD;
    CreateTask(Task_PlayerExchange, 5);

i.e. it switches straight to UNI and starts the player exchange. The join-status NI belongs to the
group-join flow the trade centre uses, not to this one. The mirrored NI_STARTs are the RFU library
answering below the game; the game never consumes the transfer, and the console gives up.

HYPOTHESIS, untested on hardware: with the parent NI skipped and UNI entered directly after the
child's NI completes, the union-room console proceeds to the player exchange. Implemented as
`RFULeader(skip_parent_ni=True)`, enabled by `--union-room`. The 'G' link-state 1 frame is still sent;
only the NI is skipped. Next run tag u05.

### u05: the NI was not the last gate

FACT (u05, one run): with `skip_parent_ni` the host reaches UNI, which u03/u04 never did. The log
line changes from the NI stall to "RFU NI handshake complete; parent UNI and trade-room startup are
active", and the decode shows the child's NI completing, our 'G' link-state 1, then
`T UNI ts=6..10 mp0:SEND_PLAYER_IDS`. So the parent join-status NI really was rejected, and skipping
it advances the connection by one layer.

FACT: the console still disconnects ~0.1s later, and it never sends one UNI frame. It answers our
SEND_PLAYER_IDS with K frames only (kseq 8, 9; mid 2, 3) and then `type44` 'D'. On the user's screen
this is unchanged: "Communication avec PkCamp" then "erreur de connexion".

UNKNOWN: why the child never enters its own UNI send. Candidates, none tested:
  1. It has not reached RFUSTATE_UR_PLAYER_EXCHANGE. That transition is driven by the LMAN
     connection callback, which on the Switch is emulator-internal, so it may want something from us
     that the trade-centre join provides implicitly.
  2. `rfu_LMAN_establishConnection(MODE_P_C_SWITCH, ...)` [link_rfu_2.c:523] is parent/child
     SWITCHABLE, unlike the trade centre's fixed MODE_CHILD. `LinkRfu_ForceChangeSpParent` and
     `rfu_LMAN_forceChangeSP(TRUE)` are called on both sides of this flow. The role may still be
     under negotiation when we start driving SEND_PLAYER_IDS as a fixed parent.
  3. Our SEND_PLAYER_IDS content or slot assignment is wrong for this flow.

Candidate 2 is the one to read next: nothing in the trade-centre path exercises MODE_P_C_SWITCH, and
it is the clearest structural difference between the two flows.
