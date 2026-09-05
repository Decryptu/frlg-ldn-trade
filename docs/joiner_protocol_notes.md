---
title: Console protocol notes
parent: The link protocol
nav_order: 1
---

# What the console actually does on the link

Findings for both directions: the joiner (`bin/frlgtrade.py --live`, the Switch hosts and we are the
RFU child) and the host (`bin/frlgtrade_host.py`, `bin/frlgmg_host.py`). Everything here was measured
on retail hardware or read out of the
[pret/pokefirered](https://github.com/pret/pokefirered) decompilation, and each claim cites its
source. The GBA release on Switch runs the original ROM inside an emulator, so the decomp is
authoritative for the whole game-level protocol (RFU commands, link tasks, union room, trade room,
seating); only the LDN/Pia wireless layer below it is the emulator's own.

Run tags: `hNN` trade host, `jNN` trade joiner, `uNN` Union Room, `lgNN`/`frNN` Mystery Gift,
`bsNN` buffer script, `mevNN` Mystery Event.

# The GBA link layer

## One child slot per parent poll. Never more.

`RfuMain2_Parent` keeps exactly one child slot per poll in `gRfu.childRecvBuffer[i]` - the adapter
overwrites it - and compares its rolling `childSendCmdId` tag against the last one it kept
[`link_rfu_2.c:876-892`]. A tag that is not exactly `+1 mod 8` increments `numChildRecvErrors[i]`,
and `> 4` calls `RfuSetErrorParams` and kills the link. The `else` branch resets that counter to 0
on any good tag, so death needs five consecutive bad polls.

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

For a scripted walk, the empty gap after a direction run only needs to cover `16 - (N mod 16)`, not
a full 16. Overshooting is harmless (a direction sent while frozen is ignored, and the run's
remaining keys retry it) but costs a slot per update, and slots are the scarce resource.

## The player's inputs are not always transmitted

`UpdateHeldKeyCode` rewrites EMPTY, all four DPAD codes, START and A to `LINK_KEY_CODE_NULL`
whenever `GetLinkSendQueueLength() > 1` [`overworld.c:2786-2810`], and `SendKeysToRfu` then sends
nothing at all. A walking player goes silent under queue pressure and looks parked.

`LINK_KEY_CODE_READY` (0x16) is not in that list, so a console that reaches its seat always
transmits its READY. Do not build a gate on the absence of DPAD codes; do build one on 0x16.

## The seat is a mutual barrier, and the standby rounds come after it

`Task_EnterCableClubSeat` shows "Please wait", calls `SetInCableClubSeat()` (which makes the next
held-key emission `LINK_KEY_CODE_READY`), then spins on `GetCableClubPartnersReady()`
[`cable_club.c:827-869`]. That returns `CABLE_SEAT_SUCCESS` only when
`AreAllPlayersInLinkState(PLAYER_LINK_STATE_READY)` [`overworld.c:2988-2999`] - all players. Only
then does it hand off to `Task_StartWirelessTrade`, whose `SetLinkStandbyCallback()`
[`cable_club.c:910-943`] is where the post-seat standby rounds come from.

So drive the post-seat rounds only once both players are READY. Driving them at a console still in
`CABLE_SEAT_WAITING` faults its seat FSM.

## What a real child sends, end to end

Recorded off a retail French FireRed acting as the child against this repo's own host, full trade
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

* **Each standby round is one frame.** Not a burst. Over a link with a reliable transport underneath
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
`gRecvCmds[0]` and clears it, the parent can self-sustain; in practice the loop settles into one
exchange per round trip. Measured on a healthy link: 182 out->in alternations against 182 in->out,
with only 22 in->in and 27 out->out.

A diagnostic falls out of this. The host's `SEND_HELD_KEYS` high byte is `heldKeyCount`, incremented
once per prepared command, so the last value it sends is exactly how many link updates its trade
room survived - a clock independent of wall time and of the child's slot rate. Comparing it against
the frames actually received also shows how far its game loop outran the wire; on every run that
made progress the ratio was exactly 1.0x.

## Row one of the parent's table is the console's own command, mirrored back

This is the rule that governs every stall while the console is *sending*, in any activity. The
console's own RFU block sender and `MGL_Send` both wait on seeing their own command come back
through row one of the parent's `gRecvCmds` table - the copy we mirror. Never drop a distinct child
command from that mirror; fold away a repeat that is still queued. `rfu_leader.ChildEcho`.
The derivation, the failure it caused (bs05) and the tool that reads it out of a capture
(`scratchpad/echo_gaps.py`) are on [the native code page](buffer_script.md).

## Version and language are not gates

`IsTryingToTradeAcrossVersionTooSoon` [`union_room.c:1499`] fires only when the partner is neither
FireRed nor LeafGreen, and it prints an in-game message rather than dropping the link. Cross-version
FR<->LG trading is confirmed working on hardware. The only language branch on the link path is
`ConvertInternationalString`, which special-cases Japanese and nothing else; a French FireRed accepts
an English Wonder Card.

## Post-seat standby gate and walk-out

After both players sit, the console (leader) broadcasts its own `READY_EXIT_STANDBY` count=2 at
mpId 0 about 130 ms after it reflects ours. Its receive gate accepts a child count only when it
equals its own (`Rfu_LinkStandby` recv gate, `link_rfu_2.c:1577-1591`), so a count=3 sent on the
reflection of our count=2 is ignored. The reflection of a child slot proves the parent saw it, not
that it completed the round. Gate count=3 on the host's own mp0 count=2, and keep re-arming it,
spaced by more than the 75 idle slots the leader needs before `BufferTradeParties`.

The walk-out: the host emits `LINK_KEY_CODE_EXIT_ROOM` (0x17) and blocks in
`KeyInterCB_WaitForPlayersToExit` until `AreAllPlayersInLinkState(EXITING_ROOM)`
[`overworld.c:2962-2981`]. The child must answer with its own 0x17 on the held-keys stream; an
all-zero child slot is not a key and the host waits for ever.

## One-sided cancel returns both sides to the menu

`PLAYER_CANCEL_TRADE` / `PARTNER_CANCEL_TRADE` go through `CB_HandleTradeCanceled` ->
`CB_MAIN_MENU` [trade.c:2094-2113]; only `BOTH_CANCEL_TRADE` ends the session [1715-1722]. The joiner
re-enters S4_PARTY and selects again after 60 frames. On the host, answering every `REQUEST_CANCEL`
at SELECT with `PARTNER_CANCEL_TRADE` looped the console on "votre ami veut échanger des Pokémon"
(h6). A second consecutive CANCEL now makes the leader cancel too, `BOTH_CANCEL_TRADE`, and the exit
path runs (h7: cancel, A, cancel, both walk out, link closed, console left LDN).

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

# The wireless layer

## The 3-second wall, and the beacon that caused it

The console, as our station, deauthenticated (802.11 reason 3, "STA is leaving") 3.0-3.8 s after its
LDN association on 40-60% of runs, both consoles, trade and Mystery Gift, in whatever handshake phase
the run was in at that instant. The clock runs from the association, not from any Pia milestone (120
host runs: finalized at 2.84 s and left at 2.98 s; finalized at 3.86 s and lived). Two real consoles
never wall. Everything decodable on the wire was identical between a delivered run and a walled one
up to the deauth.

Two causes were found, in order:

1. **The Pia type 5 Update Session was broadcast only.** The console receives ~1 in 5 of our
   broadcast data frames, so it often never finalized its Pia session in time. `host_pia` now also
   unicasts it to each joined station. Mystery Gift on the FireRed went 1/4 to 4/4 in the same
   session, which removed one trigger without closing the wall (~40-50% residual).
2. **The probe and association responses omitted the mandatory OFDM rates.** The bare set was
   1B 2B 5.5B 11B 18 24 36 54. Advertising the Switch host's set, 1B 2B 5.5B 11B 6 9 12 18 with
   extended rates 24 36 48 54, passed the wall 20/20 across both consoles against 3-4/8 for the bare
   set, one variable at a time in one afternoon. The rate set alone is sufficient; the Switch's other
   beacon and association elements (DTIM 2, ERP, capability 0x411, the Nintendo vendor element,
   HT/HE, WMM) are not needed.

**Why the rate set matters was answered later, by the beacon (u30/u31).** A real Switch beacons with
fourteen elements, 208 bytes, its Supported Rates reading `1* 2* 5.5* 11* 6 9 12 18` with extended
`24 36 48 54`. Ours carried three elements, 34 bytes: the kernel's TIM, our extended rates and RSN.
`_create_beacon_head` set no elements at all, so element 1 (Supported Rates), element 0 (SSID) and
element 3 (DS Params) were absent from the beacon - the probe and association responses had all
three.

The omission propagates into the console. The same console associating to a real Switch sends
`Rates: 1 2 5.5 11 6 9 12 18 | Ext: 24 36 48 54`; associating to us in u30 it sent
`Rates: 1 2 5.5 11 18 24 36 54` and no extended-rates element - 6, 9 and 12 missing, exactly the
three whose absence caused the wall. u31 changed one variable (elements 0, 1 and 3 added to the
beacon head) and the association request became byte-identical to what it sends a real Switch.

**So the console builds the rate set it advertises from the beacon, not from our probe response.**
In u30 the probe response already carried the correct set and the association request was still
wrong. That is why the advertised rate set matters: it decides what the console claims to support,
and so what the link may use.

**Do not extend the beacon further without a regression check.** The old `LDN_SWITCH_IES` level 1,
which added a real host's full 208-byte element set, made Mystery Gift worse (0/5 completions against
a ~50% baseline; the heavier management frames stalled our TX). The u31 change is a 41-byte subset.
lg156/lg157 both delivered first try and u31/u32 covered the Union Room and a full battle.

Measured offline from the air captures of the rate experiment
(`scratchpad/rates3s.py`), for the record:

- The console copies our advertised rates into its association request. With the Switch set in the
  probe response it lists `24 36 48 54`, our extended-rates element alone. That list bounds our own
  unicast TX rates, but level 4 passed the wall with the bare-looking list (lg106), so our TX rate
  mask is not the lever.
- Nothing else on the air differs. Console data at 54M or HT MCS, retries 0-5%, RTS before every data
  frame at 24M, ACKs to us at 24M, the deauth at 3.06-3.63 s reason 3 with the same frame mix before
  it.
- The console accepted every reliable Pia frame we sent before it left: 0 Pia-level retransmits in
  either direction and 0 decode failures inside the first 2.9 s of every walled run. The leave is not
  caused by data loss.

DEDUCTION: the trigger lives inside the console's wlan/LDN layer, takes the advertised rate set as
its only input, and is not visible on the wire. Which of 6, 9, 12 is required is UNKNOWN.

Two things that looked like the wall and were not: WMM (the console switches to QoS data frames once
the AP advertises it, and the vendored decoder rejected subtype 8; fixed), and a probe response that
dropped its RSN element while the capability word advertised privacy (fixed).

## Console as a Pia child: what it needs from a host

Measured with the receive client (`bin/frlgmg_client.py`, run mc1) against a real Mystery Gift host,
and against our host with the type 2 disabled:

- The console child does not finalize on a type 5 Update Session alone. It re-sends its join request
  every 0.5 s, ignores unicast type 5 copies, and leaves 3.05-3.20 s after its join. The type 2 Join
  Response is required.
- A real Mystery Gift host sends a real console child its type 5 within ~50-66 ms of its Net 0x11.
  To our client it sent no type 2 and held the type 5 for 2.03 s, sending only RTT probes every
  316 ms meanwhile; the difference in our join request is not identified.
- A real trade host sends type 5 and type 2 within 34 ms and originates RTT only after finalization.
- Our adapter, as the console's station, stayed associated for the full 31 s; the console never used
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

## 802.11 layer facts

- Console as station: no power save (PM bit 0 on every frame), RTS before every data frame, a clean
  mid-stream deauth with no probe or null frames before it.
- rtw88 (kernel 7.0) sends management frames at the lowest BSS basic rate and beacons at 1M
  unconditionally; injected action frames have no vif and go at 1M. A Switch host beacons at 11M
  and sends data at 48-54M.
- The monitor vif's copy of our own frames carries mac80211's intended rate (software loopback), so
  air captures cannot measure our TX rate. Worse, that loopback is emitted at TX status (the rtw88
  USB URB completion) and lags `sendto` by a median 594 ms, quantised at ~610 ms multiples, while the
  console acknowledges the same frame within 15 ms. **Use our own frames' air timestamps for order
  only.**
- The Switch host drops ~40% of the child's Pia datagrams inside its own stack after MAC-acking them,
  independent of spacing, timing, size or content. Pia delivers in order, so each drop stalls the
  child's stream for an RTO; repeating every reliable data frame in the next few datagrams removes
  the stalls (the host de-duplicates by sequence).
- LDN allows 5 GHz channels 36/40/44/48 and the host can use them, but the FRLG app scans 2.4 GHz
  only.

## Pia header nonce is a counter the console enforces

The console keeps, per channel, the last accepted 8-byte header nonce (big-endian) and drops any
datagram whose nonce is not strictly above it. The joiner used a random nonce, which passes that test
about half the time:

    j86-j88 (random):   ~1.1 duplicate outgoing reliable deliveries per unique frame, ~0.3 inbound
    j89     (counter):  0.34 outgoing, 0.00 inbound; the user called the trade "much smoother"

The inbound duplicates were the console retransmitting because our acks were being dropped too.
`Sim._next_nonce` now counts; the host already did. This is also what the "~40% silent drop inside the
console" behind the carry-forward and the reply holdoff was.

## Carry-forward stays at 4 on both sides

With the counter nonce the remaining joiner duplicates are the carry-forward (each reliable frame
repeated in the next 4 datagrams), acked ~17 ms after the original. It earns its place: air loss is
1-2% and bursty, Pia delivers in order, so a hole holds every later slot back and the console's
8-deep RFU receive queue overflows when it fills.

    h5, host carry 0: parent slot seq 954 lost with its 68ms retransmit; the 137ms one landed; the
        console received ten slots at once and disconnected 300ms later, "erreur de connexion"
    h4, host carry unlimited (a [-0:] slicing bug at depth 0, since guarded): clean.
    j90, joiner carry 0: clean, but zero trade-phase loss, so it proves nothing.

The console's own child-side retransmit rate is ~0.01-0.02 per frame in every host capture: that is
the real air loss, and what a single-copy sender is up against. `scratchpad/host_rtx.py` measures a
host capture, `rtx_analyze.py` / `rtx_where.py` a joiner one.

## The console's ack lag is a 512 ms metronome, not congestion

`scratchpad/acklag.py` reconstructs, per datagram, our highest sent seq against the console's
cumulative ack (which lives in the CTRL frame's *payload* via `parse_bulk_ack`, not in the reliable
header's `ack` field - that one is the sender's own lowest pending seq).

**The console stalls for ~50-70 ms at a time.** It is not silent-by-choice and not slow: inbound
stops for one gap of 35-70 ms against a 15 ms baseline, during which it sends only a retransmit of
its own last frames (its RTO firing because our ack did not get processed), and then it advances its
cumulative ack several frames in a single jump:

    26.553 in   D1849 D1850 ACK next=919
    26.587 OUT  D919 D920 ACK next=1851
    26.617 in   D1849* D1850*        (retransmits, no ack: its RTO fired)
    26.653 in   ACK next=924         (catches up five frames at once)

**It is periodic, and every period is an integer number of 512 ms slots.** Across 42 intervals in
five runs - h8 (FireRed, trade), u13/u14 (FireRed, Union Room chat), lg154/lg155 (LeafGreen, Mystery
Gift) - every measured period lands on a 512 ms grid with a maximum error of 16 ms, which is one
60 Hz frame, i.e. our own sampling resolution. Slot counts observed are 16 and 17 (8.192 s and
8.704 s), with one 18 and one 33 where a tick was skipped.

**The grid is phase-locked to the console's LDN join** and does not drift: h8's twelve stalls over
103 s span 18 ms of phase, u13's twelve span 18 ms, lg154's two span 2 ms. It is not us - our
advertisement and beacon updates are state transitions and do not correlate - and it appears on both
consoles, in all three activities, on a link that is otherwise idle.

DEDUCTION: this is the cause the ident-25 hole guard treats the symptom of. The stall is the same
size everywhere; what differs is what it lands on. On an idle chat link outstanding reaches 5 and
nothing happens; under Mystery Gift or trade load the same 50-70 ms lands on a full send window.

UNKNOWN: what the 512 ms grid is. It is console-internal and joins-relative, so it is a timer the
emulator or the Pia/LDN layer starts at session establishment, not a game-side one (the ROM has no
512 ms tick, and the stalls are indifferent to what the game is doing). Not worth a hardware run:
every capture already taken carries the signal, and `acklag.py <host capture>` prints it.

## The ident-25 stall: a hole plus an unbounded backlog

The console sometimes goes idle after our last delivery-script block (ident 25,
`MG_LINKID_RAM_SCRIPT`) and never sends ident 20 (READY_END), then leaves. A parent block is never
reflected by the child, so the lost fragment is invisible in the capture.

lg150 caught the mechanism. Two consecutive frames (seq 927, 928) were lost at 18.78 s. The console's
cumulative ack stayed at 927 for 1.75 s and it sent no bulk ack at all in that time, while its own
data kept flowing at 45-62 datagrams/s. We re-sent 927 and 928 in every datagram (about 100 copies)
and kept emitting new frames behind them, five per datagram with carry-forward. When the console
finally acked at 20.53 s it held 927, 928 and 960-969 only; the mask then filled at 30-80 frames per
50 ms, and at 21.00 s the hole closed and the console released 97 frames to the game in one datagram.
Its RFU receive queue is 8 deep: the ident-25 fragments in that release were dropped, the block never
completed, and the console sat on "Transmission..." for 150 s with no timeout.

FACT: the console accepted nothing from us for 1.75 s although every datagram carried the frame it
was waiting for. DEDUCTION: with the backlog behind the hole the console had no room to take the
retransmit either; the hole is self-sustaining as long as new frames keep arriving. FACT: the normal
ack lag is 0-1 frames at 99% of acks.

**Fix:** `HostSession` holds new frames while the console has not cumulatively acked
`HOST_OUTSTANDING_MAX` (6) frames, keeps retransmitting the gap, and resumes when the ack catches up.
A closed hole then releases at most 6 frames. Load-bearing on hardware (lg150-lg155). Tools:
`scratchpad/ack_trace.py`, and the K-per-datagram count over `host_decode.py` output (97 in lg150
against max 3 in lg149).

Separately, sending the ident-25 block three times (`--ram-script-block-repeat 3`) took a stalling
console to 5/5. Not proven to be air loss rather than the console's post-Pia RFU-to-game handoff
dropping a fragment; the redundancy covers both. `--block-repeat 1` is measurably worse.

## Transmission-phase deaths after the card (Mystery Gift host)

Every death after the card showed the host's UDP output peaking at 52-519 datagrams per 0.25 s where
every delivery peaked at 23-36. The mechanism: a 250 ms-3 s adapter TX stall (frames sat in the rtw88
USB path; the host process never paused), no acks, every unacked frame due and re-sent every tick, a
flood the console never recovers from. Four host fixes, all on by default:

- `HOST_RTX_LIMIT` caps Reliable retransmits per VBlank.
- `FRLG_ECHO_MAX` bounds the FIFO echo of the child's block slots, which lagged the console ~0.5 s
  and made it re-send fragments of its READY_END block for a second.
- The TX socket is non-blocking and `FRLG_QUIET_GATE_MS` holds retransmits and carry-forward while
  the console is silent: it pauses ~0.5 s after accepting the card (its flash save), and a blocking
  send during that pause froze the host 6-11 s.
- A duplicate child message no longer crashes the host receiver.

The adapter stall itself is unexplained. rtw88's USB path queues without back-pressure; VM USB
passthrough is a candidate.

## Open: our datagrams are sometimes held between the socket and the air

FACT (u21, u22, u25, u26): a battle run can end with the console showing "erreur de connexion,
rapprochez-vous", and it begins with our datagrams being held 0.1-1.1 s below the UDP socket. The
console's Pia window froze, it kept retransmitting its own frames and we received every one of them;
the host kept emitting ~90 datagrams/s with monotonic Pia header nonces and no EAGAIN; the air
capture shows our frames absent for the blackout and released as one burst (u22: 71 frames in
200 ms). The console's power-management bit was never set. It is not the party data: u25 failed with
the party that u19, u20, u23 and u24 completed with. By the time frames resumed the game had already
taken the link-loss path [`link_rfu_2.c:2312` -> `CB2_PrintErrorMessage`, link.c:1521]; u22's console
resumed receiving us for 70 ms and disconnected anyway.

**Where to look, and where not to.** The host's UDP socket is `SO_BINDTODEVICE`'d to `ldn-tap`, and
the vendor reads that tap **in Python** and injects the 802.11 frame with AF_PACKET on `ldn-mon`
(`ldn/__init__.py:1795-1858`, `wlan.py:1115-1144`), so our datagrams never enter the AP vif's TX path
at all. Measured with kprobes: `ieee80211_subif_start_xmit` fired 0 times in u29 while `tun_net_xmit`
fired 17549 and `ieee80211_monitor_start_xmit` 24705 in u30. Every station-txq observation (empty
queue, frozen dequeue counters, aqm backlog 0, AQL, block-ack, the qdisc) sits downstream of a
userspace hop. mac80211's power-save buffer is dead on direct evidence:
`ieee80211_tx_h_unicast_ps_buf` returned TX_QUEUED zero times in u29 and u30.

The console-side re-send mechanics seen in u25 are the decomp's, not a fault: the child re-enqueues
every fragment missing from its own echo bitmask (`HandleSendFailure`, link_rfu_2.c:1015) and the
receiver ORs fragments into a bitmask, so duplicated or reordered echoes are harmless. What is not
harmless is the 0.1 s hole that started it.

UNKNOWN: which of the three stages holds the frame. The hold has not reproduced since (u27-u32 are
six clean runs), so the next run is a trap set rather than a search: `scratchpad/txpath_trace.bt`
partitions the path into g_tap (the tap ring), g_py (inside Python) and g_mon (mac80211/rtw88), and
`scratchpad/txpath.py` names the growing gauge at a hold.

# The Union Room

Every activity the room offers now works: greetings, a trading-board trade, chat both ways, and full
link battles. What follows is the mechanism, in the order a session hits it.

## Getting listed at all: the advertised activity byte

A console searching for a partner keeps a candidate only if its advertised activity appears in the
accept list of the link group it is searching in [`IsPartnerActivityAcceptable`, union_room.c:1590;
`sAcceptedActivityIds`, src/data/union_room.h:398-456]. Most of those lists hold exactly one id.

A console standing in the Union Room advertises `ACTIVITY_SEARCH` (12) and searches with
`LINK_GROUP_UNION_ROOM_INIT`, whose list is `{ACTIVITY_SEARCH, 0xFF}` [src/data/union_room.h:419].
Our trade host advertises `ACTIVITY_TRADE` (4) and our Mystery Gift host `ACTIVITY_WONDER_CARD` (21),
so both were rejected before the group list was even drawn. That is why the middle NPC on Pokemon
Center 2F could never see us, and it is a filter on the advertised activity alone - not a different
transport, discovery service or Pia-level difference.

Once players are inside the room the search switches to `LINK_GROUP_UNION_ROOM_RESUME`
[union_room.c:2664], whose list is `IN_UNION_ROOM | activity` with `IN_UNION_ROOM` = `1 << 6`
[include/constants/union_room.h:49].

**And the activity byte alone decides which menu lists us.** wn01 changed that one byte in the record
at offset 16 from 21 to 22 and moved the host from the console's Wonder Cards screen to its Wonder
News screen. Nothing else in the advertisement changed - same Pia header, same record, same trainer
id, same name - and the console listed us, joined, and completed a gift session. That is the direct
confirmation that the search word's activity field is what those accept lists are read against,
rather than the packed `RfuGameData.activity` position inferred from the struct.

## The connect: IN_UNION_ROOM, exactly and alone

`IsPartnerActivityIncompatible` [src/link_rfu_2.c:2925] tests

    else if (partner->activity != IN_UNION_ROOM)   // [link_rfu_2.c:2933]
        return TRUE;

as an **exact equality**, so any activity bits beside IN_UNION_ROOM fail it. Advertising
`IN_UNION_ROOM | ACTIVITY_TRADE` (0x44) spawns the PkCamp avatar and talking to it prints
"Communication avec PkCamp" then "le DRESSEUR est occupé" with not one packet from the console on the
air (u01, u02): the connect is refused inside `Task_TryConnectToUnionRoomParent` [link_rfu_2.c:2963]
before the RFU layer transmits. The trade intent is carried in `sPlayerCurrActivity` and negotiated
after the link is up, never advertised.

Advertising the bare `IN_UNION_ROOM` (0x40) connects (u03, u04). The avatar tracks our beacon live -
it walked out and back in when the host was restarted mid-session - so the room's player list is not
a snapshot taken at entry.

## No parent NI, and the five-frame rule

The Union Room child expects no parent join-status NI at all, which is what killed u03-u05.

`rfu_LMAN_CHILD_checkSendChildName2` [AgbRfu_LinkManager.c:1203] raises
`LMAN_MSG_CHILD_NAME_SEND_COMPLETED` as soon as its own name NI reaches `SLOT_STATE_SEND_SUCCESS`;
`LinkManagerCB_UnionRoom` [link_rfu_2.c:2526] answers by setting `RFUSTATE_UR_PLAYER_EXCHANGE` and a
TYPE_UNI receive buffer, never a TYPE_NI one; `Task_UnionRoomListen` [link_rfu_2.c:533] then calls
`rfu_UNI_setSendData` and starts `Task_PlayerExchange` as MODE_CHILD. The trade-centre callback
[link_rfu_2.c:2364] is the one that adds the TYPE_NI buffer for our join status.

That is why u03/u04 mirrored our NI_STARTs but never one NI body frame: `rfu_STC_NI_receive` accepts
LCOM_NI_START into control data without a game buffer [librfu_rfu.c:2202], and only the LCOM_NI body
needs one. **Sending an NI body is actively harmful** - the child's
`rfu_STC_NI_initSlot_asRecvDataEntity` fails with ERR_RECV_BUFF_OVER [librfu_rfu.c:2300], which sets
`recvErrorFlag`, which turns `rfu_REQ_recvData` into a REQ error, which `LinkManagerCB_UnionRoom`
handles as `LMAN_MSG_REQ_API_ERROR` -> `RfuSetErrorParams` -> "erreur de connexion, rapprochez-vous"
[link_rfu_2.c:2585]. `RFULeader(skip_parent_ni=True)`, enabled by `--union-room`, is the fix; the 'G'
link-state 1 frame is still sent.

Skipping the NI reached UNI (u05) and the console still disconnected ~0.1 s later without sending one
UNI frame. Re-timing u03, u04 and u05 against each other found the rule:

    u03  child NULL 28.361  we send NI ts=8..12, K only   D 28.496   (NI_STARTs ts=6,7 were mirrored)
    u04  child NULL 34.069  we send NI ts=8..12, K only   D 34.199
    u05  child NULL 36.527  we send UNI ts=6..10, K only  D 36.628

**The 'D' follows exactly five parent frames the console left unanswered, whatever those frames
were.** Measured from the child's NULL the delay is 135/130/101 ms; u05 is two frames earlier on both
clocks, and two frames is exactly the pair of NI_START mirrors u05 did not have. Counting unanswered
frames fits all three runs with no residual, and it matches `maxMFrame` = 4 in
`sRfuReqConfigTemplate` [link_rfu_2.c:128]. A healthy trade-centre run never exceeds two silent
frames.

**The keepalive is what carries the connect through.** `--union-room-keepalive N` re-presents the
first parent NI_START for N VBlanks before UNI. The console mirrors each one, so it always has an ack
subframe to send and the five-frame rule never fires. u06 ran with 120 and the console mirrored every
re-presented NI_START (ts=6..125), then answered the first UNI `SEND_PLAYER_IDS` with UNI frames of
its own, sent its LinkPlayer block, took ours, exchanged trainer cards, and showed its prompt.

**Why the console then waits about eight seconds** (the user sees "Communication avec PkCamp" for
that long, and it is not a defect): the console reaches `RFUSTATE_UR_PLAYER_EXCHANGE` promptly and
sits in `Task_UnionRoomListen` retrying `rfu_UNI_setSendData` every frame. That call fails with
ERR_SUBFRAME_SIZE while our NI_START is pending on its receive slot - the receive control takes 2 of
the child's 16 LL-frame bytes [librfu_rfu.c:2262] and the child's UNI subframe needs all 16
[librfu_rfu.c:1449]. The pending receive is released only by the LMAN's `NI_failCounter_limit`, 480
frames after our last NI_START [link_rfu_2.c:139, AgbRfu_LinkManager.c:1328]. In u06 the console's
first UNI frame came on the very frame after its last NI_START ack, 482 frames after our last. There
is no way to release it early: an NI body is the error path above.

## What the console does once connected

[src/union_room.c:2858-2879]

    if (gReceivedRemoteLinkPlayers) {
        CreateTrainerCardInBuffer(gBlockSendBuffer, TRUE);
        CreateTask(Task_ExchangeCards, 5);
        uroom->state = UR_STATE_COMMUNICATING_WAIT_FOR_DATA;
    }
    ... then, if sPlayerCurrActivity == (ACTIVITY_TRADE | IN_UNION_ROOM),
        UR_STATE_SEND_TRADE_REQUST

So the Union Room is not a separate transport: it is the ordinary link plus a trainer card block
exchange in front of an activity request.

The prompt reads "PkCamp: oh bonjour <name>, vous désirez quelque chose ?" with Salut / Combat /
Tchat / Retour. Each choice sends one `SEND_PACKET` and waits on our answer
[UR_STATE_HANDLE_ACTIVITY_REQUEST, union_room.c:3151]:

| the console sends | activity | we answer |
|---|---|---|
| 0x48 | CARD (Salut) | 0x51 ACCEPT |
| 0x44 | TRADE (trading board) | 0x51 ACCEPT |
| 0x41 | BATTLE (Combat) | 0x51 ACCEPT |
| 0x45 | CHAT (Tchat) | 0x51 ACCEPT |
| 0x40 | EXIT (Retour) | treat as the console's close |

After each activity both sides `SetLinkStandbyCallback` [union_room.c:2995, :3012] and the console
returns to its prompt, so a session can run several in a row.

On the Switch build the accepting side also gates on `svc_CommsAllowedByParentalControls()`
[union_room.c:3159, :3037, REVISION >= 0xA]. The console is the requester, so its own parental-control
setting can turn its request into a DECLINE before we ever see it - a silent refusal at the prompt is
that, not a protocol fault.

Runs u08, u10, u11: Salut shows our trainer card, a second Salut works, and Retour sends 0x40 then
READY_CLOSE_LINK; once we answer with our own READY_CLOSE_LINK the console sends its normal 'D',
leaves LDN, and the player is back in the room with no error.

## The trading board

The console's board lists partners whose advertisement carries tradeSpecies, tradeType and tradeLevel
[union_room.c:3400]. Record bytes 18 (`type << 2`), 19 (`gender | level << 1`) and 22:24
(little-endian `tradeSpecies:10` of RfuGameData [include/link_rfu.h:107]) are all proven: u16b
registered species 277 (Treecko), whose low byte alone is 21 (Spearow), and the board listed
"PkCamp / NORMAL / ARCKO / 26" - so byte 23 is not inferred any more.

u12 traded through it: the user picked our entry, offered their own Chansey, the console connected,
sent `SEND_PACKET 0x44 113 26`, took our ACCEPT, ran the START_ACTIVITY standby, then
`Task_StartUnionRoomTrade` exactly as read - its Pokemon block (count 9), ours back, its mail block
(count 19), ours back, the animation, its READY_FINISH, our CONFIRM_FINISH, the save barriers, its
READY_CLOSE_LINK, ours, its normal 'D'. Board pick to back in the room in ~45 s, of which ~10 s is the
keepalive wait and ~32 s the animation.

**The Union Room trade needs no party exchange, no menu and no room-entry route: it is the shortest
trade the host does.**

## Chat

Chat rides the ordinary `SendBlock` path, not `Rfu_SendPacket`. Every member calls
`SendBlock(0, sendMessageBuffer, 0x28)` unsolicited - there is no `BLOCK_REQ` first
[`ChatEntryRoutine_Join`, union_room_chat.c:429; `ChatEntryRoutine_SendMessage`, :823]. A 0x28-byte
block is `count` 4, the same as the trade path's giftRibbons block.

The block layout [`PrepareSendBuffer_*`, union_room_chat.c:1256-1281; `ProcessReceivedChatMessage`,
:1283]:

    [0]      command: 0 NULL, 1 CHAT, 2 JOIN, 3 LEAVE, 4 DROP, 5 DISBAND
    [1..8]   player name, PLAYER_NAME_LENGTH + 1 bytes, EOS-terminated
    [9]      multiplayer id            (JOIN / LEAVE / DROP / DISBAND)
    [9..39]  message text, EOS-terminated (CHAT)

Entry is the same shape as the room trade: the console asks with 0x45, and on our ACCEPT it prints
the start message, runs `SetLinkStandbyCallback`, fades, and enters `Task_StartActivity`'s chat
branch [union_room.c:1938]. As the child it calls `LinkRfu_StopManagerBeforeEnteringChat`
(`rfu_LMAN_stopManager(FALSE)`, which only stops accepting *new* connections), then
`SetHostRfuGameData(ACTIVITY_CHAT | IN_UNION_ROOM, 0, TRUE)` and `EnterUnionRoomChat`. The existing
link is untouched, so the host has nothing to rebuild.

Both members send JOIN on entry, independently and with no wait for a peer, so reacting to the
console's JOIN with ours is safe and avoids racing its fade.

**A line is 15 entries, not 30 bytes.** `MESSAGE_BUFFER_NCHAR` is 15 [union_room_chat.c:21] and the
keyboard's append loop stops there [:1112], so the console itself can never type a 16th entry. Its
buffer is `2 * MESSAGE_BUFFER_NCHAR + 1` = 31 bytes only because one entry may be a
`CHAR_EXTRA_SYMBOL` (0xF9) pair, which `StringLength_Multibyte` counts as one [string_util.c:560];
our charmap emits no 0xF9, so 31 bytes of field is 15 sendable characters.

Nothing on the receive path re-checks that. `ProcessReceivedChatMessage` does a bare `StringCopy` of
whatever we sent [:1308] and `PrintTextOnWin0Colorized` draws it as one unwrapped line into a 168 px
row that the name and an `EXT_CTRL_CODE_CLEAR_TO 42` push to x=42. There is no clip and no wrap:
entry 16 onward is drawn past the right edge, which is what the user saw when we sent 30 characters.
`uroom_chat.MESSAGE_NCHAR` is 15 now, counted multibyte-aware by `uroom_chat.entry_count`, so an
over-long `--chat-message` or `--chat-file` line is refused at start-up.

**The leader must actively close on a LEAVE.** The leaver parks on `!gReceivedRemoteLinkPlayers`
waiting for the parent to drop the link before it saves and walks back into the room
[`ChatEntryRoutine_AskQuitChatting` cases 2/4/5, union_room_chat.c:596-660]. u13 marked the activity
done and stopped there, and the console sat on its "quit the chat?" prompt with the network icon
spinning for 70 s until the host was killed. With the fix (u14, u15) our DROP goes out 0.1 s after its
LEAVE, we run the close-link handshake, the console answers with its own READY_CLOSE_LINK and its
normal 'D', and the user is back in the room. The bounded chat-exit grace stays as the fallback for a
silent leaver rather than the expected path.

u15 was a live two-way conversation: lines appended to `--chat-file` while the host was already
running reached the console, so the chat is genuinely interactive rather than a queue played out at
launch. Round-trip latency is dominated by the console's on-screen keyboard, not by the link - our
reply lands ~1.7 s after the file is written.

## The link battle (UR_BATTLE 0x41)

The whole design was read out of the decomp before a run was spent, and both of its hypotheses held
on hardware.

**The entry gate is on the console's party, not on us.** `HasAtLeastTwoMonsOfLevel30OrLower`
[union_room.c:4565] counts party mons with `MON_DATA_LEVEL <= 30` that are not eggs and requires two.
It gates the activity twice - when the console offers a battle [union_room.c:2923] and when it accepts
ours [union_room.c:3176, which sends DECLINE instead] - and both tests read `gPlayerParty`, so each
side tests only itself. The refusal is a message on the console's screen, not a protocol fault on
ours.

**The pre-battle exchange** [union_room_battle.c, `CB2_UnionRoomBattle`]: after both sides pick two
mons, each sends one 0x20-byte block whose first byte is `ACTIVITY_ACCEPT | 0x40` = 0x51, or 0x52 if
the selection was cancelled. The rest is zero. Both blocks must read 0x51 or the console closes the
link and prints "refused". Then, on the Switch path only, there are **two** link-task waits with a
standby between them where the GBA release had one (`#if REVISION >= 0xA` cases 50/51/52) - the same
reordering seen elsewhere.

`SetUpPartiesAndStartBattle` keeps only the two chosen mons, zeroes the other four, and calls
`StartUnionRoomBattle(BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER)` [union_room.c:1811], which sets
`gLinkPlayers[0].linkType = LINKTYPE_BATTLE` (0x2211) [link.h:92]. `TryReceiveLinkBattleData` tests
that value exactly [battle_controllers.c:520], so the link type is load-bearing, not cosmetic.

Then [`CB2_HandleStartBattle`, battle_main.c:934]:

    state 1  SendBlock struct LinkBattlerHeader {versionSignatureLo, versionSignatureHi,
             vsScreenHealthFlagsLo, vsScreenHealthFlagsHi, struct BattleEnigmaBerry}
    state 3  SendBlock gPlayerParty[0..1]   200 bytes      state 4  recv -> gEnemyParty
    state 7  SendBlock gPlayerParty[2..3]   200 bytes      state 8  recv
    state 11 SendBlock gPlayerParty[4..5]   200 bytes      state 12 recv
    state 15 InitBattleControllers

The party exchange is byte for byte the 3 x 200-byte transfer trades already use
(`mon.party_blocks`); `Rfu_InitBlockSend` asserts size <= 252, so 200 is legal.

### Master election is the whole ballgame

In a link single battle only the side with `BATTLE_TYPE_IS_MASTER` sets
`gBattleMainFunc = BeginBattleIntro`; the other side's stays `BeginBattleIntroDummy`
[`InitLinkBtlControllers`, battle_controllers.c:141; `SetUpBattleVars`, :45].

**The non-master runs no battle logic at all.** No turn resolution, no damage calculation, no RNG. It
receives BUFFER_A controller commands over the link, runs them for display, and answers. Implementing
our side as the non-master is writing a battle *controller*, not a battle *engine*.

`LinkBattleComputeBattleTypeFlags` [battle_main.c:886], from the console's seat at multiplayer id 1
(we are the parent, id 0): if `gBlockRecvBuffer[0][0] == 0x100`, player 0 is master; else if both
signatures are equal, player 0 is master; else "lowest index player with the highest game version".
So **sending a version signature below 0x201 and not equal to 0x100 makes the console elect itself
master.** We send 0x200. Confirmed u17/u19: it ran the entire engine and we never computed a single
battle mechanic.

### The link buffer protocol

Every controller command travels as one SendBlock with an 8-byte header
[battle_controllers.c:401-435]: `LINK_BUFF_BUFFER_ID, ACTIVE_BATTLER, ATTACKER, TARGET, SIZE_LO,
SIZE_HI, ABSENT_BATTLER_FLAGS, EFFECT_BATTLER`, then the payload, whose stored size is rounded up as
`alignedSize = size - size % 4 + 4` (always at least +1 word, so a 4-byte payload is stored as 8).
`bufferId` is 0 = BUFFER_A (a command), 1 = BUFFER_B (a reply), 2 = an exec-flag clear whose one
payload byte is the sender's multiplayer id [Task_HandleCopyReceivedLinkBuffersData:566-594].

Battler numbering agrees on both sides - battler 0 is the master's mon, battler 1 the non-master's -
because the master maps 0=Player/1=LinkOpponent and the non-master maps 1=Player/0=LinkOpponent. Our
mon is battler 1.

**The sync rule** [battle_util.c:185-201]: `MarkBattlerForControllerExec` sets bit `28+battler`; when
the command's own block arrives back, `MarkBattlerReceivedLinkData` sets `gBitTable[battler] << (i*4)`
for every linked player i and clears bit 28+battler; each player clears its own nibble by sending
bufferId 2 with its multiplayer id. The master advances only on `gBattleControllerExecFlags == 0`.

So **we must acknowledge every command the console emits, for both battlers**, or the master stalls
for ever. That single rule is most of the work.

Of the 56 player-buffer commands [battle_controller_player.c:110] all but these are display-only and
need nothing but the ack:

    CONTROLLER_GETMONDATA    -> EmitDataTransfer(BUFFER_B, size, data)   [player.c:1515]
    CONTROLLER_CHOOSEACTION  -> EmitTwoReturnValues(1, B_ACTION_*, 0)    [player.c:232-241]
    CONTROLLER_CHOOSEMOVE    -> EmitTwoReturnValues(1, 10, move | target << 8) [player.c:342]
    CONTROLLER_CHOOSEPOKEMON -> EmitChosenMonReturnValue(1, partyId, order)    [player.c:1316]
    CONTROLLER_OPENBAG       -> EmitOneReturnValue(1, itemId)            [player.c:1340]
    CONTROLLER_EXPUPDATE     -> EmitTwoReturnValues(1, RET_VALUE_LEVELED_UP, exp) [player.c:1051]
    CONTROLLER_ENDLINKBATTLE -> gBattleOutcome = payload[1], then ack     [player.c:2876]

`B_ACTION_USE_MOVE` 0, `USE_ITEM` 1, `SWITCH` 2, `RUN` 3 [battle.h:34].

The first command of every battle is `GETMONDATA` with `REQUEST_ALL_BATTLE`, emitted to each battler
in turn [battle_main.c:2519]. The reply is a whole `struct BattlePokemon` [pokemon.h:170, 0x58 bytes]
built field by field in `CopyPlayerMonData` [player.c:1519]. Every field it fills - species, the five
stats, moves, PP, the six IVs, level, hp/maxHP, item, nickname, otName, experience, personality,
status1, friendship, ppBonuses, abilityNum, otId - we already compute or carry (`frlgsim/stats.py`,
`frlgsim/mon.py`). Note what it does *not* fill: `statStages`, `ability`, `type1`, `type2`, `status2`,
`unknown`. They go out as stack garbage and the receiver recomputes them, so we may send zeros.

**We may skip the BUFFER_B replies for battler 0**, the console's own mon: it answers its own
GETMONDATA locally from `gEnemyParty` through its LinkOpponent controller [link_opponent.c:444] and
its reply loops back to it, so ours would be a duplicate. Confirmed u18/u19.

**Forfeiting is a complete first milestone**, and was the right first run. The "you can't run from a
trainer" branch explicitly excludes link battles [battle_main.c:3239] and a link battler choosing RUN
is given top turn order [:3548-3560], so answering the first `CHOOSEACTION` with `B_ACTION_RUN`
exercises the whole path - 0x51 handshake, the two standby waits, the version header, three party
blocks, the intro command stream with its acks, one action selection - and ends the battle.

### Two bugs the decomp could not have shown

**A block's size does not decide its path.** `_on_child_block` routed any 2-fragment block into the
trade LINKCMD path. A link buffer record with a 4-byte payload is exactly 16 bytes - every ack and
every short command, including the first `GETMONDATA` - so they were parsed as trade link commands and
dropped (u17). Inside a battle the state decides which path a block takes, not its size.

**An ack must never overtake the echo of the block it acks.** The parent's own command and the
child-slot echo share a frame, one echo per poll, so a 2-fragment ack can pass a 7-fragment echo. On
the console the exec-flag bit is only *set* when its own block returns
[`MarkBattlerReceivedLinkData`, battle_util.c:193] and our ack *clears* it
[battle_controllers.c:585]. In u18 the echo led our ack for sixteen commands and trailed it on the
seventeenth:

    104.268 console bufferA battler 0 PRINTSTRING (72 B)
    104.366 US      ack battler 0                     <-- ours first
    104.383 echo    bufferA battler 0 PRINTSTRING

so the ack cleared a bit that was not set yet, the echo then set it, and the console waited for ever
for an ack it had already received. It froze on the battle-end message with its network icon still
animating - the game loop and the link both alive, the battle script blocked on
`gBattleControllerExecFlags == 0`, which gates `Cmd_waitmessage` [battle_script_commands.c:2041].
`HostTradeEngine._echo_owed` now holds a new block while any child command is still waiting to be
mirrored back.

The user's report that the network logo was still animated is what made this tractable: it separated
"the console crashed" from "the console is alive and waiting on us".

**Tool:** `scratchpad/battle_blocks.py <host capture> [lo] [hi]` reassembles three streams - the
console's blocks, ours, and our echo of the console's own commands - and prints each as a link buffer
record with which side still owes an ack. It found both bugs. Run it on every battle capture.

### On hardware

u19 ran a complete forfeit battle. u27 and u28 ran real ones in both directions: our Machamp KOs the
console's two mons (`MOVEANIMATION`, `HEALTHBARUPDATE`, `FAINTINGCRY`, `FAINTANIMATION`,
`CHOOSEPOKEMON`, `DRAWPARTYSTATUSSUMMARY`, `SWITCHINANIM`, then `ENDLINKBATTLE` outcome 2), and two
level-5 mons of ours knocked out by the console's Chansey with `CHOOSEPOKEMON` answered from the
other party slot and `ENDLINKBATTLE` outcome 1. u29, u30 and u32 repeated it. Every controller command
a two-mon link battle can emit has now run on hardware in both directions.

### The pace is the RFU VBlank budget, not our latency

The user sees roughly a second between each step of a link battle, in both directions. It is not a
defect and there is nothing to tune.

Our datagram turnaround is not the cost: over the u30 battle window `udp_in -> next udp_out` was
median 5.8 ms, p99 16.6 ms, max 17.9 ms across 8204 replies, and the console's own turnaround was
median 8.1 ms. The per-command cadence is identical across runs and unaffected by the beacon fix -
median 800 ms between consecutive `bufferA` commands in u29, u30 and u32 alike. A console block is
echoed in median 19 ms, but our corresponding block appears a median 355 ms later.

That 355 ms is the RFU frame budget. `HostSession.tick` emits at most one RFU slot per call and is
driven at `HOST_VBLANK_SECONDS = 1/59.727` = 16.74 ms; measured in u32, our outgoing inter-send gap is
17 ms for 5035 samples and 16 ms for 413. We are exactly at the GBA's VBlank cadence. A controller
command's block spans roughly twenty RFU frames, and twenty frames at one per VBlank is ~340 ms; a
full step is that plus the return leg, giving the observed ~800 ms.

**Do not look for a latency bug here, and do not "optimise" the tick.** Going faster means emitting
more than one RFU slot per VBlank, which is not what the hardware link does.

# The cable-club colosseum

BUILT, NOT YET RUN. `frlgtrade_host.py --colosseum` hosts Pokemon Center 2F -> third NPC (club sans
fil) -> Colosseum -> Single Battle -> JOIN. Everything here is read off the decomp; no hardware run
has advertised `ACTIVITY_BATTLE_SINGLE` yet.

**Why it exists.** Only `CB2_ReturnFromCableClubBattle` increments the Wonder Card's `battlesWon`
[src/cable_club.c:792]. The in-room Union Room battle returns through `CB2_ReturnToField` and
increments nothing, so the Battle Count Card's prize was unreachable from every activity we hosted.
See [What Mystery Gift can do](mystery_gift_untried.md).

**It is the trade centre's entry with a battle at the end.** `Task_StartActivity` treats
`ACTIVITY_BATTLE_SINGLE` and `ACTIVITY_TRADE` almost identically [union_room.c:1903]: both call
`CreateTrainerCardInBuffer(gBlockSendBuffer, TRUE)`, both `WarpForCableClubActivity` and both enter
`CB2_TransitionToCableClub`. Only the destination map differs - `MAP_BATTLE_COLOSSEUM_2P` at (6, 8)
instead of `MAP_TRADE_CENTER` at (5, 8) - plus a `HealPlayerParty()` the trade does not do. So the
100-byte trainer-card exchange, and with it `MysteryGift_TryEnableStatsByFlagId`, runs exactly as it
does for a trade: `--card-flag-id` arms the console's counters on this path too.

Four things change, and that is the whole build:

1. **The advertised activity byte.** The console searches with `LINK_GROUP_SINGLE_BATTLE`, whose
   accept list is `{ACTIVITY_BATTLE_SINGLE, 0xFF}` [src/data/union_room.h:398], so the trade beacon
   is invisible on that screen and vice versa. `build_colosseum_app_data` changes that byte and
   nothing else - the same one-byte edit wn01 proved for Wonder News.
2. **The spot, not the chair.** `BattleColosseum_2P_EventScript_PlayerSpot0/1` has no party check at
   all [data/scripts/cable_club.inc:576] - the 4P colosseum's `ChooseHalfPartyForBattle` is the one
   with a selection step. The seat handshake itself is unchanged: `SetInCableClubSeat` sets the
   `KeyInterCB_SetReady` intercept and `GetCableClubPartnersReady` waits for
   `PLAYER_LINK_STATE_READY` from everyone [overworld.c:2989], which is the READY key our host
   already exchanges at the trade centre.
3. **One more player record.** `Task_StartWirelessCableClubBattle` case 2 sends
   `SendBlock(0, &gLocalLinkPlayer, sizeof(gLocalLinkPlayer))` [cable_club.c:701] - the bare 28-byte
   `struct LinkPlayer`, **not** the 60-byte LinkPlayerBlock of the entry, so its two GameFreak magics
   must not be added. There is no block request: both sides send unprompted and the console parks in
   case 3 until every player's record has landed. Then 20 frames, an `IsLinkTaskFinished` wait, a
   `SetLinkStandbyCallback` and another wait (cases 4-6, the `REVISION >= 0xA` shape), and
   `CB2_InitBattle`.
4. **The whole party fights.** There is no two-mon selection, so `party_blocks` is called with the
   party as it stands rather than `SetUpPartiesAndStartBattle`'s two [union_room_battle.c:47].

From `CB2_InitBattle` on it is byte for byte the Union Room battle documented above: the 31-byte
`LinkBattlerHeader`, the three 200-byte party blocks, the controller loop, and the same version
signature 0x200 that hands the console the master role. The one piece that does **not** appear is the
0x20-byte 0x51 selection block, which belongs to `CB2_UnionRoomBattle` alone.

## Two things that decide whether a run counts

**A forfeit is still a win for the console.** `HandleAction_Run` in a link battle sets
`B_OUTCOME_WON` on the side that did not run and ORs in `B_OUTCOME_LINK_BATTLE_RAN` (1 << 7)
[battle_main.c:4300]. That extra bit would miss `CB2_ReturnFromCableClubBattle`'s
`switch (gBattleOutcome) case B_OUTCOME_WON:` entirely - except `HandleEndTurn_BattleWon` clears it
first [battle_main.c:3734]. So the proven forfeit path moves `battlesWon`, and we do not have to lose
a real battle to test the counter.

**Three wins need three `--id` values.** The id recorded is
`gLinkPlayers[GetMultiplayerId() ^ 1].trainerId` [cable_club.c:794], which comes from the 28-byte
record of point 3 above, and `IncrementCardStatForNewTrainer` counts each trainer id exactly once,
remembering five per stat [mystery_gift.c:630].

# Two host-side defects worth remembering

**The host never stopped on its own after a successful close.** Of 356 host logs on disk, not one
reached `_completion_message`. 124 stopped by themselves, every one through the branch taken when the
console leaves LDN *without* having confirmed a room exit. Every clean close in the project's history
ended in a SIGTERM, which is why the notes carried "the host does not exit on its own" as a fact about
the host rather than as the bug it was.

The runtime waited for the activity's `done`, and `done` cannot arrive once the console is gone:
`done` is set from the session's disconnect path, gated on `disconnect_requested`, set by
`_tick_close_link`, which only runs inside `activity.tick()` - and `HostSession.tick` returns before
calling `activity.tick()` while the hole guard holds. A departed console stops acking, so the guard
latches within a few frames and the clock that would release it never advances. The guard's own
comment says the close path must never be gated; it was the close *decision* that was. Fixed at the
runtime: once the console has left LDN after a confirmed exit, the host settles briefly and stops.

UNKNOWN, not fixed: a console still in LDN but no longer acking will also stall the close timer behind
the guard. No run has shown it, so the transport hot path is left alone.

**The trainer card's profile quote read "??? ???".** An all-zero `easyChatProfile` is word 0, which is
group EC_GROUP_POKEMON_2 index 0 (SPECIES_NONE); `IsECWordInvalid` rejects it and `CopyEasyChatWord`
substitutes `gText_ThreeQuestionMarks` [easy_chat.c:166-171]. A word is
`(group & 0x7F) << 9 | (index & 0x1FF)` [easy_chat.h:1089] and the card holds four
[trainer_card.h:28]. The card now carries a real phrase; a short one pads with `EC_WORD_UNDEFINED`
(0xFFFF), which prints nothing. u16b showed the console rendering "SALUT AMIS ECHANGER POKEMON" from
its own French table.

# The visiting trainer: an e-Reader trainer over Mystery Gift

A second payload the Mystery Gift session can carry. Written from the decomp, proven offline against
`ConsoleClientModel`, and confirmed on hardware first try (vt01, FireRed): ident 26 went out in two
blocks 24.3 s into the session, the console returned READY_END and saved, the old woman on Seven
Island offered the battle, and the full 3v3 against RED ran to a player win.

`CLI_RECV_EREADER_TRAINER` (client instruction 18, link ident `MG_LINKID_EREADER_TRAINER` = 26)
memcpys the received buffer into `gSaveBlock2Ptr->battleTower.ereaderTrainer` and calls
`ValidateEReaderTrainer` [mystery_gift_client.c:233]. The struct is 188 bytes
[struct BattleTowerEReaderTrainer, global.h:286]:

    0x00 u8  unk0                  0x10 u16 greeting[6]            0x34 BattleTowerPokemon party[3]
    0x01 u8  trainerClass          0x1C u16 farewellPlayerLost[6]  0xB8 u32 checksum
    0x02 u16 winStreak             0x28 u16 farewellPlayerWon[6]
    0x04 u8  name[8]
    0x0C u8  trainerId[4]

**Validation is only that the first 46 words are not all zero and that the trailing u32 is their
sum** [battle_tower.c:1354, :1384]. A struct that fails is silently cleared. Nothing about the
trainer, the party or the levels is checked.

`SevenIsland_House_Room1` gates only on that validation. `ValidateEReaderTrainer` returning 0 sets
`TRAINER_VISITING`, opens the door in the map layout and moves the old woman; she offers a 3v3, warps
to Room2, and `StartSpecialBattle` case 2 builds the enemy party with `CreateBattleTowerMon` straight
from the struct [battle_tower.c:928]. The party is healed afterwards and the scene var resets, so the
battle is repeatable. The Battle Tower's level rule and banlist live on `ShouldBattleEReaderTrainer`
[:232], which this path never calls - **the levels we send are the levels that appear.**

`CreateBattleTowerMon` applies species, held item, four moves (PP filled from the move table), level,
ppBonuses, all six EVs, all six IVs, abilityNum, otId, personality, nickname and friendship.
Personality and otId therefore fix nature, gender and shininess. The three phrases are Easy Chat
words, six per line; `farewellPlayerWon` is what the trainer says when the *player* won. The name
field is eight bytes but FRLG displays five [`CopyEReaderTrainerName5`, battle_tower.c:1343].

`CLI_MSG_TRAINER_RECEIVED` (12) is "A new TRAINER has arrived." [strings.c:1296] and
`GetClientResultMessage` marks it a success, so the console saves on its own afterwards. No Wonder
Card is required for that.

What we send (`--gift visiting-trainer`, flagId 1008): the card and its RAM script exactly as any
other gift, then the trainer as ident 26 in the same session. Three server branches, all covered by
tests: no card -> card + script + trainer; the same card already held -> the trainer alone with no
toss prompt (a free rematch); a different card -> the usual toss prompt, then all three.

# Wonder News: the one place the console answers back

`MG_LINKID_RESPONSE` (ident 19) travels client -> server in a gift session that has no player prompt
in it. Every other gift this host sends is one-way. `CLI_SAVE_NEWS` loads that response with the
console's own verdict - FALSE when it saved the news, TRUE when `IsWonderNewsSameAsSaved` matched what
it already held [mystery_gift_client.c:210, mystery_gift.c:140] - and `sServerScript_SendNews`
branches on it [mystery_gift_scripts.c:126]. In wn01 the console sent it 4.0 s after the 444-byte
ident 23 completed, in the same shape as any other client message.

The compatibility `hasNews` bit is not needed on the Friend path: `HasWonderCardOrNewsByLinkGroup`
[union_room.c:3777] is reached only from `Task_ListenForWonderDistributor`, the Wireless path, and
wn01 completed without any news bit being set anywhere - the same way the Wonder Card host has never
needed `hasCard`.
