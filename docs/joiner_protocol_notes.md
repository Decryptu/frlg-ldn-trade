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

### After u05, offline: the decomp path, and the five-frame pattern

No hardware run spent. Two things came out of reading the child side of the Union Room connect end
to end, plus a re-timing of u03/u04/u05 against each other.

FACT (decomp): the Union Room child expects no parent NI at all. `rfu_LMAN_CHILD_checkSendChildName2`
[AgbRfu_LinkManager.c:1203] raises `LMAN_MSG_CHILD_NAME_SEND_COMPLETED` as soon as its own name NI
reaches `SLOT_STATE_SEND_SUCCESS`; `LinkManagerCB_UnionRoom` [link_rfu_2.c:2526] answers by setting
`RFUSTATE_UR_PLAYER_EXCHANGE` and a TYPE_UNI receive buffer, never a TYPE_NI one, and
`Task_UnionRoomListen` [link_rfu_2.c:533] then calls `rfu_UNI_setSendData` and starts
`Task_PlayerExchange` as MODE_CHILD. The trade-centre callback [link_rfu_2.c:2364] is the one that
adds the TYPE_NI buffer for our join status. This is why u03/u04 mirrored our NI_STARTs but no NI
body: `rfu_STC_NI_receive` accepts LCOM_NI_START into control data without a game buffer
[librfu_rfu.c:2202], and only the LCOM_NI body needs one. `skip_parent_ni` is therefore
decomp-backed, not just u05-backed.

DEDUCTION (decomp): candidate 2 (MODE_P_C_SWITCH) is dead as a cause. `rfu_LMAN_CHILD_connectParent`
sets `pcswitch_flag = PCSWITCH_CP` [AgbRfu_LinkManager.c:232], and after that nothing in
`rfu_LMAN_settingPCSWITCH` [:565] touches the flag, the ID_SP_END_REQ branch skips it [:750], and
`rfu_LMAN_forceChangeSP` (called every frame by `LinkRfu_ForceChangeSpParent` because `RfuMain1`
zeroes `gRfu.parentId` each frame [link_rfu_2.c:2111]) has no case for the post-connect LMAN
states. The switch machine is quiescent once the console is our child.

DEDUCTION (decomp): no game-side timer fits a ~100 ms disconnect. The name-accept timer is 360
frames, `NI_failCounter_limit` is 480 [link_rfu_2.c:139], the Union Room connect timeout is 480
[link_rfu_2.c:2970], link recovery is off. The only child-side disconnects are link loss reported
by the adapter (`rfu_LMAN_linkWatcher`), a `RFUCMD_DISCONNECT` from the parent, or a queue overflow,
none of which we cause.

FACT (u03, u04, u05 re-timed): the 'D' follows exactly five parent frames the console left
unanswered, whatever those frames were.
  u03  child NULL 28.361  we send NI ts=8..12, K only   D 28.496   (NI_STARTs ts=6,7 were mirrored)
  u04  child NULL 34.069  we send NI ts=8..12, K only   D 34.199
  u05  child NULL 36.527  we send UNI ts=6..10, K only  D 36.628
Measured from the child's NULL the delay is 135/130/101 ms; measured from the A frame it is
646/646/615 ms. u05 is two frames earlier on both clocks, and two frames is exactly the pair of
NI_START mirrors u05 did not have. Counting unanswered frames fits all three runs with no residual.

HYPOTHESIS: the emulated adapter declares link loss on the child when the child has had nothing to
send for more than `maxMFrame` (4) consecutive parent frames [sRfuReqConfigTemplate,
link_rfu_2.c:128]. h8 never exceeds two silent frames (NULL ts=12, UNI ts=13) before the child's
first UNI IDLE. Under this hypothesis the D is a symptom: the real defect is that the console never
calls `rfu_UNI_setSendData`, i.e. never reaches `RFUSTATE_UR_PLAYER_EXCHANGE`, and we do not know
why, since the wire exchange up to the child's NULL is byte-identical to h8.

UNKNOWN: what the Union Room child is waiting for before `rfu_UNI_setSendData`. One candidate with
a mechanism: our advertisement flips to the started-activity form when the console joins
(`activate_trade_app_data` sets record bit 0x80 at byte 17 and the Pia header byte 0x16). A real
Union Room parent sets `startedActivity` only at `RFUSTATE_UR_FINALIZE` [link_rfu_2.c:554], after
the child's name, and the room's list compares `startedActivity` when deciding whether a player
changed [union_room.c:4157]. The trade-centre child never looks at beacons, so h8 could not have
shown this. It does not explain the five-frame count by itself.

Probe (tag u06): --union-room-keepalive N re-presents the first parent NI_START for N VBlanks
before UNI; the console mirrors it, so if the five-frame rule is real the link survives the
keepalive. A second probe that held the pre-join beacon was dropped after u06 connected without it.

### u06: the keepalive carries the Union Room connect all the way to the prompt

FACT (u06, one run, `--union-room --union-room-keepalive 120`): the console mirrored every
re-presented NI_START for the whole keepalive (ts=6..125, each answered `NI_START ack=1`), then
answered the first UNI SEND_PLAYER_IDS with UNI frames of its own, sent its LinkPlayer block
(identified as the user's trainer), took ours, exchanged trainer cards (block count 9, no standby
after it), and the user's screen showed "PkCamp: oh bonjour <name>, vous désirez quelque chose ?"
with Salut / Combat / Tchat / Retour. Picking Salut sent `SEND_PACKET 0x48` (ACTIVITY_CARD |
IN_UNION_ROOM) once, and the console then waited on us ("voilà ma carte de dresseur") until the
host was stopped, 65 s later, with no disconnect from its side.

DEDUCTION: the five-frame rule was real, and it was the only gate left. With the child kept busy
for two seconds it had all the time it needed to reach RFUSTATE_UR_PLAYER_EXCHANGE; the exact
delay it needs is still unmeasured (somewhere between 5 and ~120 frames).

FACT (u06): the hole guard fired every ~8 s during the idle prompt (ack 6 behind, 1-8 held ticks)
and recovered each time; same behaviour as the Mystery Gift host.

Implemented from the decomp, untested past the first reply: the parent's half of the prompt
[UR_STATE_HANDLE_ACTIVITY_REQUEST, union_room.c:3151]. `_child_send_packet` in host_trade.py answers
0x48 (cards) and 0x44 (trading-board trade) with `SEND_PACKET 0x51` (ACCEPT | IN_UNION_ROOM),
0x41/0x45 (battle, chat) with 0x52 (DECLINE), and treats 0x40 (Exit) as the console's close. After
the cards both sides SetLinkStandbyCallback [union_room.c:2995, :3012] and the console returns to
its prompt; the parent then waits for the next packet. The trade path needs our advertisement to
carry tradeSpecies/tradeType/tradeLevel so the console's trading board lists us
[union_room.c:3400]; where tradeType and tradeLevel sit in the 24-byte record is still UNKNOWN
(only tradeSpecies in [22:24] is proven).

### u07: why the keepalive works, and why u07 still died

DEDUCTION (decomp + u06 timing): the console reaches `RFUSTATE_UR_PLAYER_EXCHANGE` promptly and
sits in `Task_UnionRoomListen` retrying `rfu_UNI_setSendData` every frame [link_rfu_2.c:533]. That
call fails with ERR_SUBFRAME_SIZE while our NI_START is pending on its receive slot: the receive
control takes 2 of the child's 16 LL-frame bytes [rfu_STC_NI_initSlot_asRecvControllData,
librfu_rfu.c:2262], and the child's UNI subframe needs all 16 [rfu_STC_setSendData_org,
librfu_rfu.c:1449]. The pending receive is released only by the LMAN's NI fail counter,
`NI_failCounter_limit` 480 frames [link_rfu_2.c:139] after our last NI_START, via
`rfu_NI_stopReceivingData` [AgbRfu_LinkManager.c:1328]. In u06 the console's first UNI frame came
on the very frame after its last NI_START ack (ts 177963 -> 177964), 482 frames after our last
NI_START. While the receive is pending the child has an ack subframe to send every frame, which is
what keeps the five-frame rule from firing.

DEDUCTION: releasing the receive early is not an option. An NI body frame makes the child's
`rfu_STC_NI_initSlot_asRecvDataEntity` fail with ERR_RECV_BUFF_OVER (no game buffer, size 0)
[librfu_rfu.c:2300], which sets `recvErrorFlag`, which turns `rfu_REQ_recvData` into a REQ error,
which `LinkManagerCB_UnionRoom` handles as `LMAN_MSG_REQ_API_ERROR` -> `RfuSetErrorParams` ->
the "erreur de connexion, rapprochez-vous" screen [link_rfu_2.c:2585]. That is also what u03/u04
showed after their NI body frames. So the sequence stays: NI_START keepalive, then ~8 s of the
console's own re-acks, then UNI. The user sees "Communication avec PkCamp" for about ten seconds.

FACT (u07, one run, same flags as u06): the console connected, the keepalive ran, and at 17.0 s
(5 s into the console's 480-frame wait) both Pia reliable windows stopped advancing at once: we
retransmitted seq 419-422 and the console retransmitted 847-850 for four seconds, then it sent
'D' and left. Its frames kept reaching us and our socket kept sending at a steady rate with no
errors, so our frames stopped reaching it. The dmesg line `failed to get tx report from firmware`
is the teardown symptom (u09 logged it 10 s after its stall), not the cause. Cause UNKNOWN.

### u08-u11: the Union Room greet loop, end to end

FACT (u08, u10, u11; u09 lost to the same one-way loss as u07): with `--union-room
--union-room-keepalive 120` the console connects, waits its 480 frames, exchanges LinkPlayer blocks
and trainer cards, and shows its menu. Salut sends SEND_PACKET 0x48; our ACCEPT (0x51) makes the
console show our trainer card, which reads as expected (type NORMALE, Pokedex 0, time 00:00, 0
battles, 0 trades; the easy-chat quote line shows "??? ???" because we leave it blank), then it
runs a standby barrier and returns to the menu. A second Salut works (u10, after fixing a
dedup that swallowed identical repeated requests in u08). Retour sends SEND_PACKET 0x40, then
READY_CLOSE_LINK; once we answer with our own READY_CLOSE_LINK (u11) the console sends the normal
'D', leaves LDN, and the player is back in the room with no error.

UNKNOWN: the one-way loss in u07/u09 (our frames stop reaching the console 1-3 s after the
keepalive ends, its frames keep reaching us, no send errors, steady packet rate). The dmesg
tx-report line came 10 s after the u09 stall, at teardown, so the adapter-wedge reading of u07 is
retracted. The launcher now records an air capture and station counters for every run; u10/u11
did not reproduce it.

NEXT: trading from the room. The console's trading board lists partners whose advertisement
carries tradeSpecies / tradeType / tradeLevel [union_room.c:3400]; only tradeSpecies [record
22:24] is located in the 24-byte record. Then `Task_StartUnionRoomTrade` [union_room.c:1936] on
the console side, unread.

### u12: a Pokemon traded through the Union Room

FACT (u12, one run, `--union-room --union-room-keepalive 120 --board-type normal`): the console's
trading board listed PkCamp with Chansey lv26 wanting NORMAL. The user picked it, offered their
own Chansey, the console connected (usual ten seconds), sent `SEND_PACKET 0x44 113 26`, took our
ACCEPT, ran the START_ACTIVITY standby, then Task_StartUnionRoomTrade exactly as read: its Pokemon
block (count 9), ours back, its mail block (count 19), ours back, then the animation, its
READY_FINISH, our CONFIRM_FINISH, the save barriers, its READY_CLOSE_LINK, ours, its normal 'D'.
The user saw the trade animation, "saving", and was back in the room with PkCamp still there. We
received their Chansey lv26 (OT Tops, checksum valid) in received.pk3. Timeline: board pick to
back in the room in ~45 s, of which ~10 s is the keepalive wait and ~32 s the animation.

DEDUCTION: the record bytes for the trading board (18: type<<2, 19: gender|level<<1, 22:
species) are correct for a lv26 species-113 registration; the species high byte (23) is still
inferred. The Union Room trade path needs no party exchange, no menu, no room-entry route: it is
the shortest trade the host does.

### Union Room chat, read from the decomp (offline, no run spent)

The room's "Tchat" was declined by the host until now. Read end to end in `src/union_room_chat.c`
and `src/union_room.c`; nothing about it needs a hardware run to specify.

FACT: chat rides the ordinary `SendBlock` path, not `Rfu_SendPacket`. Every member calls
`SendBlock(0, sendMessageBuffer, 0x28)` unsolicited — there is no `BLOCK_REQ` first
[`ChatEntryRoutine_Join`, union_room_chat.c:429; `ChatEntryRoutine_SendMessage`, :823]. A 0x28-byte
block is `count` 4, the same as the trade path's giftRibbons block.

FACT: the block layout, from `PrepareSendBuffer_*` [union_room_chat.c:1256-1281] and
`ProcessReceivedChatMessage` [:1283]:

    [0]      command: 0 NULL, 1 CHAT, 2 JOIN, 3 LEAVE, 4 DROP, 5 DISBAND
    [1..8]   player name, PLAYER_NAME_LENGTH + 1 bytes, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)

`messageEntryBuffer` is `2 * MESSAGE_BUFFER_NCHAR + 1` = 31 bytes [union_room_chat.c:21, :67], so a
full line plus its terminator is exactly the block's tail: a CHAT block is never truncated by the
0x28 limit.

FACT: entry is the same shape as the room trade. The console asks with `SEND_PACKET 0x45`
(`ACTIVITY_CHAT | IN_UNION_ROOM`); on our `ACCEPT` (0x51) it prints the start message, runs
`SetLinkStandbyCallback` [UR_STATE_START_ACTIVITY_LINK, union_room.c:3096], fades, and enters
`Task_StartActivity`'s chat branch [union_room.c:1938]. As the child (multiplayer id 1) it calls
`LinkRfu_StopManagerBeforeEnteringChat` — `rfu_LMAN_stopManager(FALSE)`, which only stops accepting
NEW connections — then `SetHostRfuGameData(ACTIVITY_CHAT | IN_UNION_ROOM, 0, TRUE)` and
`EnterUnionRoomChat`. The existing link is untouched, so the host has nothing to rebuild.

FACT: both members send JOIN on entry, independently and with no wait for a peer
[`ChatEntryRoutine_Join` case 0 falls straight into the send]. Reacting to the console's JOIN with
ours is therefore safe and avoids racing its fade.

FACT: the leader (multiplayer id 0, the parent — us) sends DISBAND when it quits; a child sends
LEAVE, then parks on `!gReceivedRemoteLinkPlayers` waiting for the parent to drop the link before it
saves and walks back into the room [`ChatEntryRoutine_AskQuitChatting` cases 2/4/5,
union_room_chat.c:596-660]. So the host must disconnect when the console's LEAVE arrives.

FACT: on the Switch build the accepting side also gates on
`svc_CommsAllowedByParentalControls()` [union_room.c:3159, :3037, REVISION >= 0xA]. The console is
the requester here, so its own parental-control setting can turn its request into a DECLINE before
we ever see it — a silent refusal at the prompt is that, not a protocol fault.

Shipped: `frlgsim/uroom_chat.py` (block build/parse/validate), `H_UROOM_CHAT` in `host_trade.py`,
`--union-room-chat` and repeatable `--chat-message TEXT` on `frlgtrade_host.py`.

### u13, u14: Union Room chat works both ways

FACT (u13 and u14, `--union-room --union-room-keepalive 120 --union-room-chat`): the console
accepts our ACCEPT for 0x45, runs the START_ACTIVITY standby and opens its chat keyboard; its JOIN
block arrives, our JOIN lists us as a member on its screen, our queued lines appear in order at the
90-frame spacing, and every line it types reaches us decoded. u13 read back `SALUT` and `ÇA VA?`,
u14 `0123456789`: letters, the accented-Latin range, punctuation and digits all round-trip through
`charmap`. A 30-character line (the full field) sent from our side reached the console and decoded,
but see the line limit below: it was drawn off the right edge of the screen, which the run did not
check for. The 2026-09-03 note "displayed correctly" was our own inference, not the user's report.

### The chat line is 15 entries, not 30 bytes

FACT (decomp, no run needed): `MESSAGE_BUFFER_NCHAR` is 15 [src/union_room_chat.c:21] and the
keyboard's append loop stops at `bufferCursorPos < MESSAGE_BUFFER_NCHAR` [union_room_chat.c:1112],
so the console itself can never type a 16th entry. Its buffer is `2 * MESSAGE_BUFFER_NCHAR + 1` = 31
bytes only because one entry may be a `CHAR_EXTRA_SYMBOL` (0xF9) pair, which
`StringLength_Multibyte` counts as one [src/string_util.c:560]; our charmap emits no 0xF9, so for us
one entry is one byte and 31 bytes of field is 15 sendable characters.

FACT: nothing on the receive path re-checks that. `ProcessReceivedChatMessage` does a bare
`StringCopy(tempStr, recvMessage)` of whatever we sent [union_room_chat.c:1308], and
`PrintTextOnWin0Colorized` draws it as one unwrapped line into a 168 px row that the name and an
`EXT_CTRL_CODE_CLEAR_TO 42` push to x=42 [union_room_chat_display.c]. There is no clip and no wrap:
entry 16 onward is drawn past the right edge. 15 glyphs of `FONT_NORMAL` are 6 px each
[sFontNormalLatinGlyphWidths, src/text.c:187], 90 px into the ~126 px left, so a console-legal line
always fits and anything longer is exactly what the user saw overflow.

DEDUCTION: `check_text` was bounding the block field (30) instead of the console's line (15). Fixed:
`uroom_chat.MESSAGE_NCHAR` = 15, counted multibyte-aware by `uroom_chat.entry_count`, so an
over-long `--chat-message` or `--chat-file` line is refused at start-up rather than half-drawn on
the console. u14's 30-character line is why the wrong bound looked proven.

FACT (u13): the leader must actively close on a LEAVE. u13 marked the activity done and stopped
there; the console sat on its "quit the chat?" yes/no prompt with the network icon spinning for 70
seconds until the host was killed, because `ChatEntryRoutine_AskQuitChatting` case 5 parks the
leaver on `!gReceivedRemoteLinkPlayers`. The host loop only ends on `done` once the console has
already left LDN, so both sides waited for each other.

FACT (u14, with the fix): our DROP goes out 0.1 s after its LEAVE, we run the close-link handshake,
and the console answers with its own READY_CLOSE_LINK at +0.1 s and its normal 'D' at +0.2 s, then
leaves LDN 4 s later and the user is back in the room with no error.

CORRECTION: the comment shipped with the fix said the leaver never sends a READY_CLOSE_LINK of its
own. u14 shows it does. The bounded chat-exit grace stays, now as the fallback for a silent leaver
rather than as the expected path; what matters is that it is short, since the console is frozen on
its prompt for exactly as long as we wait.

UNKNOWN: on both runs the console's cumulative ack fell 6 frames behind on a strikingly regular
cycle even with the link otherwise idle -- u13 deltas 16.9, 16.9, 16.8, 16.9, 16.9, 16.9, 16.9,
8.7, 8.7, 8.7, 9.3, 16.9, 16.8, 17.0 s. The 8.7s gaps are half of 16.9, so the fundamental is
~8.45 s with holds sometimes skipped. A period that stable on an idle link is a clock, not load.
This is the same UNKNOWN left open by the ident-25 work, on a much cleaner sample.

### u15: a live two-way conversation through the Union Room chat

FACT (u15, `--union-room-chat --chat-message "HELLO FROM LINUX" --chat-file <path>`): lines
appended to the chat file while the host was already running reached the console, so the chat is
genuinely interactive rather than a queue played out at launch.

    28.8s  us      HELLO FROM LINUX        (queued at launch)
    40.0s  GURVAN  HEY CLAUDE
    54.5s  us      HEY GURVAN! I READ YOU  (written to the file mid-run)
    74.3s  GURVAN  WATS 2 PLUS 6
    82.8s  us      2 PLUS 6 IS 8
    92.4s  GURVAN  THX
    99.0s  us      ANYTIME. THIS IS ON LDN
   104.6s  GURVAN  [LEAVE] -> our DROP +0.1s, its READY_CLOSE_LINK +0.2s, its 'D' +0.3s, LDN leave
                   +4.3s, back in the room with no error

DEDUCTION: the chat-exit fix is 2/2 on hardware (u14, u15). Round-trip latency is dominated by the
console's on-screen keyboard, not by the link: our reply lands ~1.7s after the file is written
(one chat_message_gap_frames wait plus the block send).

## Two host-side defects found offline (2026-09-03)

### The host never stopped on its own after a successful close

FACT: of 356 host logs on disk, not one reached `_completion_message` ("Room-exit grace period
complete"). 124 stopped by themselves, every one of them through the branch taken when the console
leaves LDN *without* having confirmed a room exit -- early deaths and failed joins. Every clean
close in the project's history ended in a SIGTERM, which is why the notes carried "the host does
not exit on its own" as a fact about the host rather than as the bug it is.

DEDUCTION: the runtime waited for the activity's `done`, and `done` cannot arrive once the console
is gone. `done` is set from the session's disconnect path, which is gated on
`disconnect_requested`; that flag is set by `_tick_close_link`, which only runs inside
`activity.tick()`; and `HostSession.tick` returns before calling `activity.tick()` while the hole
guard holds. A departed console stops acking, so the guard latches within a few frames and the
clock that would release it never advances. The guard's own comment says the close path must never
be gated -- it is the close *decision* that was.

Fixed at the runtime: once the console has left LDN after a confirmed exit, the host settles
briefly and stops. The 15-second post-exit grace was for keeping Pia traffic alive while the Switch
fades and warps, and the console leaving LDN is that finishing.

UNKNOWN, not fixed: a console that is still in LDN but has stopped acking will also stall the close
timer behind the guard. No run has shown it -- u14 and u15 both had the console send its own 'D'
and leave -- so the transport hot path is left alone.

### The trainer card's profile quote read "??? ???"

FACT: an all-zero `easyChatProfile` is word 0, which is group EC_GROUP_POKEMON_2 index 0
(SPECIES_NONE). `IsECWordInvalid` rejects it and `CopyEasyChatWord` substitutes
gText_ThreeQuestionMarks [easy_chat.c:166-171], which is what the console displayed for our card in
u08-u11. A word is `(group & 0x7F) << 9 | (index & 0x1FF)` [EC_WORD, easy_chat.h:1089] and the card
holds four [trainer_card.h:28]. The card now carries a real phrase; a short one pads with
EC_WORD_UNDEFINED (0xFFFF), which prints nothing rather than "???".

### u16b: the trading board's species is 10 bits, the card quote reads, the host stops itself

One run, three closures, no trade started.

FACT: the trading board takes a full 10-bit species. We registered species 277 (Treecko) from our
own party file -- its low byte alone is 21, which is Spearow -- and the console's board listed
"PkCamp / NORMAL / ARCKO / 26". So record bytes 22:24 are the little-endian tradeSpecies:10 of
RfuGameData [include/link_rfu.h:107], and byte 23 stops being inferred. The same line proves the
type and level fields beside it.

FACT: the trainer card's profile quote renders. With a real easyChatProfile the console showed
"SALUT AMIS ECHANGER POKEMON" -- our HELLO / FRIEND / TRADE / POKEMON word ids, drawn from the
console's own French easy-chat table -- in place of the "??? ???" of u08-u11.

FACT: the host now stops on its own after a clean close, which no run had ever done:

    117.9s  console's 'D', the normal close
    120.1s  console left LDN; settling
    122.1s  Room-exit grace period complete; host peer traffic stopped cleanly

That is the 357th host log and the first to reach the completion message.

## The console's ack lag is a 512 ms metronome, not congestion (2026-09-03)

The ident-25 work left an UNKNOWN: what makes the console's cumulative ack fall behind in the first
place. It was never load. `scratchpad/acklag.py` reconstructs, per datagram, our highest sent seq
against the console's cumulative ack (which lives in the CTRL frame's *payload* via
`parse_bulk_ack`, not in the reliable header's `ack` field -- that one is the sender's own lowest
pending seq).

FACT: the console stalls for ~50-70 ms at a time. It is not silent-by-choice and not slow: inbound
stops for one gap of 35-70 ms against a 15 ms baseline, during which it sends only a retransmit of
its own last frames -- its RTO firing because our ack did not get processed -- and then it advances
its cumulative ack several frames in a single jump. Worked example, u14 at 26.6 s:

    26.553 in   D1849 D1850 ACK next=919
    26.587 OUT  D919 D920 ACK next=1851
    26.617 in   D1849* D1850*        (retransmits, no ack: its RTO fired)
    26.653 in   ACK next=924         (catches up five frames at once)

FACT: it is periodic, and every period is an integer number of 512 ms slots. Across 42 intervals in
five runs -- h8 (FireRed, trade), u13 and u14 (FireRed, Union Room chat), lg154 and lg155
(LeafGreen, Mystery Gift) -- every measured period lands on a 512 ms grid with a maximum error of
16 ms, which is one 60 Hz frame, i.e. our own sampling resolution. The slot counts observed are 16
and 17 (8.192 s and 8.704 s), with one 18 and one 33 where a tick was skipped. Mean spacing ~16.5
slots, so the underlying event is not itself a multiple of 512 ms and lands on alternating slots.

FACT: the grid is phase-locked to the console's LDN join. Within a run the stalls sit at a constant
fraction of a slot after the join, and it does not drift: h8's twelve stalls over 103 s span 18 ms
of phase, u13's twelve span 18 ms, lg154's two span 2 ms.

FACT: it is not us. Our advertisement and beacon app-data updates are state transitions (u14: 0,
9.7, 21.1, 52.4 s) and do not correlate with the stalls (17.9, 26.6, 34.8, 43.5 s). It appears on
both consoles, in all three activities, and on a link that is otherwise idle.

DEDUCTION: this is the cause the ident-25 hole guard treats the symptom of. The stall is the same
size everywhere; what differs is what it lands on. On an idle chat link outstanding reaches 5 and
nothing happens. Under Mystery Gift or trade load the same 50-70 ms lands on a full send window:
h8's peaks reach 47 and lg150's reach 126, and lg150's catastrophic release at join+17.22 s is
itself on the metronome (join+8.52 s, then +8.70 s). The guard's job is to survive these, and
lg151-lg155 show it does.

UNKNOWN: what the 512 ms grid is. It is console-internal and joins-relative, so it is a timer the
emulator or the Pia/LDN layer starts at session establishment, not a game-side one (the ROM has no
512 ms tick, and the stalls are indifferent to what the game is doing). Whether the ~16.5-slot
spacing is one process with a period near 8.45 s quantised onto the grid, or two interleaved
processes, is not decided by this data.

Not worth a hardware run on its own: every capture already taken carries the signal, and
`acklag.py <host capture>` prints it.

## The Union Room battle (UR_BATTLE 0x41), read from the decomp

No hardware run was spent on any of this. Every claim below is a decomp citation; what is a
deduction from those citations is labelled, and the two hypotheses are called out as such.

### The entry gate is on the console's party, not on us

FACT: `HasAtLeastTwoMonsOfLevel30OrLower` [union_room.c:4565] counts party mons with
`MON_DATA_LEVEL <= UNION_ROOM_MAX_LEVEL` (30) [constants/union_room.h:15] that are not eggs, and
requires two. It gates the activity twice: when the console *offers* a battle [union_room.c:2923,
message `gText_UR_NeedTwoMonsOfLevel30OrLower1`] and when it *accepts* ours [union_room.c:3176,
which sends `ACTIVITY_DECLINE | IN_UNION_ROOM` and message ...2 instead]. Both tests read
`gPlayerParty`, i.e. each side tests only itself. So the console needs two non-egg mons at level
30 or lower in its own party or the battle cannot start, and the refusal is a message on its
screen, not a protocol fault on ours.

### The pre-battle block exchange

FACT [union_room_battle.c, `CB2_UnionRoomBattle`]: after both sides pick two mons, each sends one
0x20-byte block whose first byte is `ACTIVITY_ACCEPT | 0x40` = 0x51, or `ACTIVITY_DECLINE | 0x40`
= 0x52 if the selection was cancelled (`gSelectedOrderFromParty[0] == -gSelectedOrderFromParty[1]`).
The rest of the block is zero. Both blocks must read 0x51 (`GetBlockReceivedStatus() == 3`) or the
console closes the link and prints "refused". Then, on the Switch path only:

    #if REVISION >= 0xA   case 50: fade; case 51: IsLinkTaskFinished -> SetLinkStandbyCallback;
                          case 52: IsLinkTaskFinished -> SetUpPartiesAndStartBattle

so there are TWO link-task waits with a standby between them, where the GBA release had one. This
is the same REVISION >= 0xA reordering already seen elsewhere; read the 0xA branch.

FACT [`SetUpPartiesAndStartBattle`]: each side keeps only its two chosen mons, zeroes the other
four, and calls `StartUnionRoomBattle(BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER)` [union_room.c:1811],
which sets `gLinkPlayers[0].linkType = LINKTYPE_BATTLE` (0x2211) [link.h:92] and
`gTrainerBattleOpponent_A = TRAINER_UNION_ROOM`. `TryReceiveLinkBattleData` tests that 0x2211
exactly [battle_controllers.c:520], so the link type is load-bearing, not cosmetic.

FACT [`CB2_HandleStartBattle`, battle_main.c:934]:

    state 1  SendBlock struct LinkBattlerHeader {versionSignatureLo=1, versionSignatureHi=2,
             vsScreenHealthFlagsLo, vsScreenHealthFlagsHi, struct BattleEnigmaBerry}
    state 2  both received -> LinkBattleComputeBattleTypeFlags, vs-screen task
    state 3  SendBlock gPlayerParty[0..1]   200 bytes
    state 4  recv -> gEnemyParty[0..1]
    state 7  SendBlock gPlayerParty[2..3]   200 bytes
    state 8  recv
    state 11 SendBlock gPlayerParty[4..5]   200 bytes
    state 12 recv
    state 15 InitBattleControllers

DEDUCTION: the party exchange is byte-for-byte the 3 x 200-byte block transfer we already do for
trades (`mon.party_blocks`, `PARTY_BLOCK_SIZE` 200), proven on hardware many times. Nothing new is
needed for it. `Rfu_InitBlockSend` asserts size <= 252 [link_rfu_2.c:1336], so 200 is legal.

### Master election, and why it is the whole ballgame

FACT [`InitLinkBtlControllers`, battle_controllers.c:141]: in a link single battle only the side
with `BATTLE_TYPE_IS_MASTER` sets `gBattleMainFunc = BeginBattleIntro`. The other side's
`gBattleMainFunc` stays `BeginBattleIntroDummy` [SetUpBattleVars, battle_controllers.c:45].

DEDUCTION, and the central finding of this read: **the non-master runs no battle logic at all.**
It has no turn resolution, no damage calculation, no RNG. It receives BUFFER_A controller commands
over the link, runs them for display, and answers. Implementing our side as the non-master is
therefore writing a battle *controller*, not a battle *engine* -- a bounded command handler over a
transport we already have, instead of a reimplementation of Gen-3 battle mechanics.

FACT [`LinkBattleComputeBattleTypeFlags`, battle_main.c:886], for two players, from the console's
seat at multiplayer id 1 (we are the parent, id 0):
  - if `gBlockRecvBuffer[0][0] == 0x100`, player 0 is master -- the console is not;
  - else if both signatures are equal, player 0 is master -- the console is not;
  - else "lowest index player with the highest game version": the console breaks out of the loop,
    and so fails to be master, only if our signature is 0x201 (equal, index 0 < 1) or > 0x201.

DEDUCTION: sending a version signature **below 0x201 and not equal to 0x100** -- 0x200 is the
obvious choice -- makes the console elect *itself* master. Running the same algorithm from our
seat would also elect us master, i.e. the game's own rule is not symmetric here; that does not
matter, because we are not the game. The console decides its own role from the bytes we send, and
we simply behave as the non-master regardless. This is the lever that turns the largest remaining
item in the project into a tractable one.

### The link buffer protocol

FACT [battle_controllers.c:401-435]: every controller command travels as one SendBlock with an
8-byte header, `LINK_BUFF_BUFFER_ID, ACTIVE_BATTLER, ATTACKER, TARGET, SIZE_LO, SIZE_HI,
ABSENT_BATTLER_FLAGS, EFFECT_BATTLER`, then the payload. The stored size is the payload rounded up:
`alignedSize = size - size % 4 + 4` (note: always at least +1 word, so a 4-byte payload is stored
as 8). `bufferId` is 0 = BUFFER_A (a command), 1 = BUFFER_B (a reply), 2 = an exec-flag clear whose
one payload byte is the sender's multiplayer id [Task_HandleCopyReceivedLinkBuffersData:566-594].

FACT: battler numbering agrees on both sides -- battler 0 is the master's mon, battler 1 the
non-master's -- because the master maps 0=Player/1=LinkOpponent and the non-master maps
1=Player/0=LinkOpponent [InitLinkBtlControllers]. Our mon is battler 1.

FACT, the sync rule [battle_util.c:185-201]: `MarkBattlerForControllerExec` sets bit `28+battler`;
when the command's own block arrives back, `MarkBattlerReceivedLinkData` sets
`gBitTable[battler] << (i*4)` for **every** linked player i and clears bit 28+battler; each player
clears its own nibble by sending bufferId 2 with its multiplayer id. The master advances only on
`gBattleControllerExecFlags == 0`.

DEDUCTION: we must acknowledge **every** command the console emits, for **both** battlers, or the
master stalls forever. That single rule is most of the work; the rest is the handful of commands
that also want a BUFFER_B reply.

### What we actually have to answer

FACT [sPlayerBufferCommands, battle_controller_player.c:110]: 56 commands, of which all but these
are display-only and need nothing but the ack:

    CONTROLLER_GETMONDATA    -> EmitDataTransfer(BUFFER_B, size, data)   [player.c:1515]
    CONTROLLER_CHOOSEACTION  -> EmitTwoReturnValues(1, B_ACTION_*, 0)    [player.c:232-241]
    CONTROLLER_CHOOSEMOVE    -> EmitTwoReturnValues(1, 10, move | target << 8) [player.c:342]
    CONTROLLER_CHOOSEPOKEMON -> EmitChosenMonReturnValue(1, partyId, order)    [player.c:1316]
    CONTROLLER_OPENBAG       -> EmitOneReturnValue(1, itemId)            [player.c:1340]
    CONTROLLER_EXPUPDATE     -> EmitTwoReturnValues(1, RET_VALUE_LEVELED_UP, exp) [player.c:1051]
    CONTROLLER_ENDLINKBATTLE -> gBattleOutcome = payload[1], then ack     [player.c:2876]

`B_ACTION_USE_MOVE` 0, `USE_ITEM` 1, `SWITCH` 2, `RUN` 3 [battle.h:34].

FACT: the first command of every battle is `GETMONDATA` with `REQUEST_ALL_BATTLE`, emitted to each
battler in turn [`BattleIntroGetMonsData`, battle_main.c:2519]. The reply is a whole
`struct BattlePokemon` [pokemon.h:170, 0x58 bytes] built field by field in `CopyPlayerMonData`
[player.c:1519]. Every field it fills -- species, the five stats, moves, PP, the six IVs, level,
hp/maxHP, item, nickname, otName, experience, personality, status1, friendship, ppBonuses,
abilityNum, otId -- we already compute or carry: `frlgsim/stats.py` has the exp tables, natures and
the stat formula, and `frlgsim/mon.py` parses every substructure. Note what `CopyPlayerMonData`
does NOT fill: `statStages`, `ability`, `type1`, `type2`, `status2`, `unknown`. They go out as
stack garbage and the receiver recomputes them, so we may send zeros there.

### Forfeiting is a complete first milestone

FACT: the "you can't run from a trainer" branch explicitly excludes link battles
[battle_main.c:3239: `BATTLE_TYPE_TRAINER && !(BATTLE_TYPE_LINK) && ... B_ACTION_RUN`], and a
link battler choosing RUN is given top turn order [battle_main.c:3548-3560].

DEDUCTION: answering the very first `CHOOSEACTION` with `B_ACTION_RUN` forfeits. That exercises the
entire path -- 0x51 handshake, the two standby waits, the version header, three party blocks, the
whole intro command stream with its acks, and one action selection -- and then ends the battle and
returns both sides to the Union Room, without our ever needing to choose a move, take damage, or
model a single turn. It is the right first hardware run, and it is one run.

### Two hypotheses to settle on hardware, not by argument

HYPOTHESIS 1: we can send version signature 0x200 and the console will make itself master. The
algorithm says so; nothing else in the decomp reads the signature. Falsified if the console stalls
at the vs-screen or both sides start emitting commands.

HYPOTHESIS 2: we may skip the BUFFER_B replies for battler 0 (the console's own mon) and send only
the ack. The console answers its own GETMONDATA locally from `gEnemyParty` through its own
LinkOpponent controller [link_opponent.c:444], and its reply loops back to it, so ours would be a
duplicate write of identical bytes into `gBattleBufferB[0]`. Skipping is strictly less traffic;
sending is the reference-faithful choice but needs us to model the console's party as well.
Falsified if the intro stalls at the first GETMONDATA.

### u17-u19: the Union Room battle, proven on hardware

FACT (u19): a complete Union Room link battle. `SEND_PACKET` 0x41 accepted, both 0x20 selection
blocks, our LinkBattlerHeader at signature 0x200 against the console's 0x201, three 200-byte party
blocks, the whole intro, `CHOOSEACTION` for both battlers answered with `B_ACTION_RUN`, the
`STRINGID_BATTLEEND` print carrying `gBattleOutcome` 3 (`B_OUTCOME_DREW`, both sides ran), then
`CONTROLLER_ENDLINKBATTLE`, and on the console the score screen, the save and the walk back into
the room. Every activity the Union Room offers now works.

Both hypotheses from the decomp read held:

  1. CONFIRMED (u17 reached the vs screen, u19 ran the battle): advertising version signature 0x200
     makes the console elect ITSELF master. It ran the entire engine -- turn order, the outcome, the
     battle scripts -- and we never computed a single battle mechanic.
  2. CONFIRMED (u18, u19): we may skip the BUFFER_B replies for the console's own battler. It
     answers its own GETMONDATA locally from `gEnemyParty` and its reply loops back to it; ours
     would be a duplicate. u19's log shows its `bufferB battler 0 DATATRANSFER` arriving with no
     reply of ours, and the battle proceeding.

Two bugs, both ours, both invisible from the decomp and found only by replaying the captures.

FACT (u17): `_on_child_block` routed any block of `trade.COUNT_LINKCMD` (2 fragments) into the trade
LINKCMD path. A link buffer record with a 4-byte payload is exactly 16 bytes -- every ack and every
short command, including the first `GETMONDATA` -- so they were parsed as trade link commands and
dropped. The only record that reached the controller was the 104-byte `DATATRANSFER`, which is
exactly the one line the log showed. Inside a battle the state decides which path a block takes, not
its size.

FACT (u18), and the subtler one: **an ack must never overtake the echo of the block it acks.** The
parent's own command and the child-slot echo share a frame, one echo per poll
[`rfu_leader.tick`], so a 2-fragment ack can pass a 7-fragment echo. On the console the exec-flag
bit is only SET when its own block returns (`MarkBattlerReceivedLinkData` [battle_util.c:193]) and
our ack CLEARS it [battle_controllers.c:585]. In u18 the echo led our ack for all sixteen commands
and trailed it on the seventeenth:

    104.268 console bufferA battler 0 PRINTSTRING (72 B)
    104.366 US      ack battler 0                     <-- ours first
    104.383 echo    bufferA battler 0 PRINTSTRING

so the ack cleared a bit that was not set yet, the echo then set it, and the console waited forever
for an ack it had already received. It froze on the battle-end message with its network icon still
animating -- the game loop and the link both alive, the battle script blocked on
`gBattleControllerExecFlags == 0`, which gates `Cmd_waitmessage` [battle_script_commands.c:2041] and
every script command after it [HandleEndTurn_FinishBattle:3855]. `HostTradeEngine._echo_owed` now
holds a new block while any child command is still waiting to be mirrored back.

DEDUCTION: the user's report that the network logo was still animated is what made this tractable.
It separated "the console crashed" from "the console is alive and waiting on us", and only the
second is worth replaying a capture for.

Tool: `scratchpad/battle_blocks.py <host capture> [lo] [hi]` reassembles three streams -- the
console's blocks, ours, and our echo of the console's own commands -- and prints each as a link
buffer record with which side still owes an ack. It found both bugs. Run it on every battle capture.

UNKNOWN, and the next piece of work: a real turn. `--battle-fight` answers `CHOOSEACTION` with
`B_ACTION_USE_MOVE` and then `CHOOSEMOVE` with slot 0 at the opposing battler. Everything up to the
action prompt is proven; the turn itself -- `MOVEANIMATION`, `HEALTHBARUPDATE`, damage, fainting,
`CHOOSEPOKEMON` on a faint, `EXPUPDATE` -- has never run. The console computes all of it; we still
only answer, so this should be runs rather than redesign.

### Open: an intermittent disconnect during the battle's party exchange

FACT (u21, u22, u25 against u19, u20, u23, u24): about half of battle runs end with the console
showing "erreur de connexion, rapprochez-vous" at the vs screen, during the three 200-byte party
blocks of CB2_HandleStartBattle states 3/7/11. It is not the party data: u25 failed with the same
party that u19, u20, u23 and u24 completed with.

FACT (u25 wire at the disconnect): we were 11 fragments into sending our own 17-fragment party block
3, the console had gone quiet apart from K frames, we had just echoed its own last fragment
(mp1 SEND_BLOCK index 16), and it sent 'D' 0.4 s later.

NOT THE CAUSE, checked: the console's K-frame `mid` field climbing 1,2,3,4 before the disconnect
looks like a retry counter giving up. u19 completed a whole battle with it reaching 5.

UNKNOWN. The next step is offline and costs no runs: diff a failing capture against a succeeding one
across the whole party exchange with `scratchpad/battle_blocks.py` and `scratchpad/host_decode.py`.
