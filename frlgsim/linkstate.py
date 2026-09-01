"""Held-keys overworld link-state engine - the keepalive + sit-at-RIGHT-seat + exit FSM.

The real FRLG child runs CB1_UpdateLinkState every VBlank [src/overworld.c:2579-2599]: it calls
the active key-intercept callback to produce ONE key code, runs it through UpdateHeldKeyCode
(clamp to [0x11,0x1D] else EMPTY) into gHeldKeyCodeToSend, and SendKeysToRfu emits
RFUCMD_SEND_HELD_KEYS (0xBE00) with gSendCmd[1]=gHeldKeyCodeToSend [link_rfu_2.c:1069-1080,
1315-1316]. This module reproduces that callback chain so the sim, during the overworld/seat
phase, emits a real 0xBE00 keepalive slot every VBlank instead of an all-zero idle.

Why this matters (decomp-verified):
  * The host's seat barrier GetCableClubPartnersReady [overworld.c:2989-3000] clears at
    CABLE_SEAT_SUCCESS only when AreAllPlayersInLinkState(PLAYER_LINK_STATE_READY=0x82) over
    i in [0, gFieldLinkPlayerCount). For a 2P trade BOTH slot 0 (host) and slot 1 (us) must be
    READY. The host drives OUR slot from the key we send: UpdateAllLinkPlayers truncates the key
    to u8 [overworld.c:2776] and HandleLinkPlayerKeyInput's tail switch [overworld.c:2749-2766]
    maps key READY(0x16)->sPlayerLinkStates[1]=READY, EXIT_ROOM(0x17)->EXITING_ROOM,
    IDLE(0x1A)->IDLE, EXIT_SEAT(0x1D)-while-READY->BUSY. So we reach READY by emitting 0x16 once.
  * CheckRfuKeepAliveTimer [overworld.c:2623-2626] does ++sRfuKeepAliveTimer>60 -> FatalError. This
    is a CHILD-LOCAL liveness watchdog, NOT a wire-cadence requirement: sRfuKeepAliveTimer is RESET to
    0 ONLY by SetKeyInterceptCallback, i.e. when the active key-intercept callback CHANGES
    [overworld.c:2614-2616]. The keepalive callbacks (KeyInterCB_Idle [2867-2871],
    KeyInterCB_DoNothingAndKeepAlive [2924-2928], KeyInterCB_Ready while NOT-yet-ready [2946],
    KeyInterCB_WaitForPlayersToExit while not-exiting [2968]) call it every frame, so it would trip a
    state that never transitions for >60 frames - but it is the CHILD's own check, decoupled from what
    is on the wire. Importantly, ONCE SEATED (KeyInterCB_Ready with sPlayerLinkStates[self]==READY) the
    callback returns EMPTY WITHOUT calling CheckRfuKeepAliveTimer [2941, the READY branch] - so the
    timer is NOT even running while we hold the seat. The reason linkstate emits a 0xBE00 EVERY VBlank
    in the seat phase is the HOST's view of our liveness (so it keeps OUR slot alive / sees READY),
    NOT this child-local timer. Outside the seat phase the child is on CB1_UpdateLink (the trade menu),
    which never runs this engine at all - so the per-frame 0xBE00 is strictly a seat-phase behavior.
  * gHeldKeyCodeToSend packing: SendKeysToRfu does `heldKeyCount++` THEN
    `gHeldKeyCodeToSend |= (heldKeyCount<<8)` [link_rfu_2.c:1076-1077]. heldKeyCount is a
    function-static u8, so the FIRST emit carries high byte 1 (NOT 0), then 2,3,... rolling mod
    256. The host stores gLinkPartnersHeldKeys[i]=gRecvCmds[i][1] (full u16) [link_rfu_2.c:1217]
    but reads it as `u8 key` [overworld.c:2776], so the high byte is a pure liveness nonce and
    the low byte is the key code.

RIGHT SEAT - resolved from the decomp, NOT from a chosen chair:
  There are TWO ids. (a) gLocalLinkPlayerId [overworld.c:120] = the wire mpId =
  GetMultiplayerId(); for the wireless child this is gRfu.multiplayerId = 1
  [link.c:965-971; link_rfu_2.c:1633-1638]. This is the index the WHOLE link-state machine uses
  (sPlayerLinkStates[gLocalLinkPlayerId] [overworld.c:2993-2997], CB1 selfId [overworld.c:2583],
  and the trade-menu partner index id^1 [trade.c:984-985,1008-1009]). (b) gLocalLinkPlayer.id
  (LinkPlayer field 0x18 [include/link.h:170]) set by SetLocalLinkPlayerId(gSpecialVar_0x8005)
  [cable_club.c:840; link.c:338-341] = the COSMETIC chair the player walked into. The chairs:
  TradeCenter_EventScript_Chair0 setvar 0 (x=4, LEFT), Chair1 setvar 1 (x=7, RIGHT)
  [data/scripts/cable_club.inc:637-649; data/maps/TradeCenter/map.json coord_events]. This chair
  id does NOT drive held-keys indexing. CONCLUSION: "RIGHT" = mpId 1 = gLocalLinkPlayerId = the
  joiner, whose trade partner is id^1 = 0 (the host, LEFT). The joiner SetReadyToTrade only fires
  when GetMultiplayerId()==1 [trade.c:1816], confirming mpId 1 is the Follower. So the sim is
  already the RIGHT seat by virtue of being the joiner; self_id is asserted == 1.

FSM (mirrors the child KeyInterCB callback chain):
  PRE_SEAT  (KeyInterCB_SelfIdle/_Idle [overworld.c:2856-2870]): emit EMPTY(0x11) every frame.
  -- sit() --> emit READY(0x16) on exactly ONE frame (KeyInterCB_SetReady [overworld.c:2951-2955])
  SEATED    (KeyInterCB_Ready/_DoNothingAndKeepAlive [overworld.c:2924-2948]): emit EMPTY(0x11).
              Slot 1 is now READY; stays here across the trade-menu and between sequential trades.
  -- exit() --> emit EXIT_ROOM(0x17) on exactly ONE frame (KeyInterCB_SendExitRoomKey
                [overworld.c:2977-2981]); print the cancel-to-leave intent to STDOUT.
  EXITING   (KeyInterCB_WaitForPlayersToExit [overworld.c:2962-2975]): emit EMPTY(0x11) until the
              host slot is also EXITING_ROOM; then -> SEND_NOTHING.
  SEND_NOTHING (KeyInterCB_SendNothing [overworld.c:2957]): emit EMPTY(0x11) keepalive.

Suppression / handoff: SendKeysToRfu does not emit when gHeldKeyCodeToSend==NULL or while
transferring data [link_rfu_2.c:1072-1074], and UpdateHeldKeyCode NULL-suppresses movement/idle
keys when GetLinkSendQueueLength()>1 [overworld.c:2793-2810]. In the sim this maps to: held-keys
keepalive replaces an IDLE slot ONLY - never a real SEND_BLOCK/LINKCMD slot. sim.py asks the
trade engine first; only if it returns idle does it emit this keepalive (see sim.py).
"""

from collections import deque

from . import rfu

# Key codes [include/overworld.h:7-24]; the OUT subset linkstate emits.
LINK_KEY_CODE_NULL = 0x00        # suppress (SendKeysToRfu skips)
LINK_KEY_CODE_EMPTY = 0x11       # keepalive (no state change)
LINK_KEY_CODE_DPAD_DOWN = 0x12
LINK_KEY_CODE_DPAD_UP = 0x13
LINK_KEY_CODE_DPAD_LEFT = 0x14
LINK_KEY_CODE_DPAD_RIGHT = 0x15
LINK_KEY_CODE_READY = 0x16       # sit -> sPlayerLinkStates[self]=READY(0x82)
LINK_KEY_CODE_EXIT_ROOM = 0x17   # leave -> sPlayerLinkStates[self]=EXITING_ROOM(0x83)
LINK_KEY_CODE_IDLE = 0x1A
LINK_KEY_CODE_EXIT_SEAT = 0x1D

# PLAYER_LINK_STATE_* [src/overworld.c:57-60] - host-side per-peer state (for the host model).
PLAYER_LINK_STATE_IDLE = 0x80
PLAYER_LINK_STATE_BUSY = 0x81
PLAYER_LINK_STATE_READY = 0x82
PLAYER_LINK_STATE_EXITING_ROOM = 0x83

# CABLE_SEAT_* [include/constants/cable_club.h:28-30] - GetCableClubPartnersReady verdict.
CABLE_SEAT_WAITING = 0
CABLE_SEAT_SUCCESS = 1
CABLE_SEAT_FAILED = 2

# linkstate FSM states (for logging/tests).
PRE_SEAT = "PRE_SEAT"
SEATED = "SEATED"
EXITING = "EXITING"
SEND_NOTHING = "SEND_NOTHING"

# 60-frame watchdog (CheckRfuKeepAliveTimer >60 -> LinkRfu_FatalError [overworld.c:2623-2626]).
KEEPALIVE_WATCHDOG = 60

# The child's walk from the trade-room entrance to the RIGHT chair, as (LINK_KEY_CODE, frames).
# The seat walk is REAL PLAYER INPUT relayed over the link, not a script: each side animates the
# peer's avatar from the key codes it receives, so a child that only ever sends EMPTY stands in the
# doorway forever and the host waits for a READY that never comes. host_trade.ENTRY_LEFT_CHAIR_ROUTE
# is the mirror of this for the LEADER (UP -> LEFT -> UP -> READY, to the left chair).
#
# Measured, not guessed: recorded off a real French FireRed acting as the CHILD against this repo's
# own host (HostTradeEngine.child_route_runs), walking a clean path to its chair:
#     (EMPTY,1) (0x1b,21) (EMPTY,5) (0x1a,1) (EMPTY,87)
#     (UP,43) (EMPTY,23) (RIGHT,9) (EMPTY,30) (UP,7) (EMPTY,59) (READY,1) (EMPTY,13)
# The 0x1b/0x1a prefix (HANDLE_RECV_QUEUE / IDLE) is the console's own queue housekeeping around the
# room load, not movement, so it is not reproduced here; the movement and its gaps are verbatim. The
# EMPTY runs between direction changes are load-bearing - tile movement has to finish before the next
# direction is accepted - so do not compress them without a fresh capture to justify it.
# The two long EMPTY runs in the recording - 87 before the first step and 59 before READY - are the
# player waiting for the room to render and pausing at the chair, not protocol. They are trimmed:
# the peer advances our avatar ONE key per slot it receives, so every frame here costs a slot, and
# measured on hardware (j38) the console goes quiet the moment it is in the room, dropping us to the
# 3/s liveness floor - at which 87 lead-in frames alone is 29 seconds of standing still. The gaps
# BETWEEN direction changes are kept verbatim: tile movement has to finish before the next direction
# is accepted, and those are load-bearing.
# The gaps are trimmed to TILE_STEP_FRAMES, the length of one walking step - the peer has to finish
# the step in progress before it will accept a new direction, and that is the whole job of the gap;
# the recorded 23/30/59 were the player pausing on top of it. Measured (j50): the console polled for
# ~6s after entering the room, ~85 slots at 13-16/s, and we emit ONE route frame per poll - so a
# 145-frame route ran out of runway mid-way (UP and RIGHT done, final UP and READY not; the player
# saw us walk partway and stop). 112 frames fits that budget with margin.
TILE_STEP_FRAMES = 16


def _step_gap(run_frames):
    # Updates still owed to FINISH the step a run of `run_frames` direction keys left in progress,
    # plus one of margin. FacingHandler_DpadMovement sets directionSequenceIndex = 16 and
    # MovementStatusHandler_TryAdvanceScript decrements it once per link update while the key is
    # ignored (MOVEMENT_MODE_FROZEN) [overworld.c:3432-3470] - so a step is exactly 16 updates start
    # to finish, and a run of N keys leaves (N mod 16) of its last step already spent. The gap only
    # has to cover the remainder, not a whole TILE_STEP_FRAMES. Overshooting is not harmful (a fresh
    # direction sent while frozen is ignored, and the next run's remaining keys retry it) - it just
    # burns slots, and the route costs one slot per host poll.
    return (TILE_STEP_FRAMES - (run_frames % TILE_STEP_FRAMES)) % TILE_STEP_FRAMES + 1


# The console's trade room does not always live long. Measured in ITS OWN link updates
# (scratchpad/room_life.py): 152, 151, 123, 109 on the good runs, and 67, 64, 33, 29, 27, 9 on the
# bad ones. The route spends one slot per update, so trimming it fits the walk inside more of those
# rooms: 112 -> 88 frames, same geometry, same five tiles, one update of margin on every gap.
ENTRY_RIGHT_CHAIR_ROUTE = (
    (LINK_KEY_CODE_EMPTY, 4),
    (LINK_KEY_CODE_DPAD_UP, 43),
    (LINK_KEY_CODE_EMPTY, _step_gap(43)),      # 43 = 2 whole steps + 11 -> 5 owed, +1
    (LINK_KEY_CODE_DPAD_RIGHT, 9),
    (LINK_KEY_CODE_EMPTY, _step_gap(9)),       # 7 owed, +1
    (LINK_KEY_CODE_DPAD_UP, 7),
    (LINK_KEY_CODE_EMPTY, _step_gap(7)),       # 9 owed, +1
    (LINK_KEY_CODE_READY, 1),
)


class LinkState:
    """Held-keys overworld link-state engine for the JOINER (mpId 1 = RIGHT seat).

    One instance per link. tick() returns a 7-word pre-tag gSendCmd run for the SEND_HELD_KEYS
    (0xBE00) command, ready for rfu.SlotBuilder.build(). It is trade-count-agnostic: it keepalives
    around/between the configured trades and fires READY once (sit) / EXIT_ROOM once (exit) on the
    explicit sit()/exit() signals from the orchestrator.
    """

    def __init__(self, self_id=1, log=lambda *a: None, out=print):
        # Assert RIGHT seat. self_id is the wire mpId (gLocalLinkPlayerId), which
        # for the wireless child is 1 [link_rfu_2.c:1633-1638]; partner = id^1 = 0 = host (LEFT)
        # [trade.c:984-985]. A joiner is ALWAYS mpId 1; mpId 0 would be the host/parent, never us.
        assert self_id == 1, (
            f"frlgsim is the JOINER: wire mpId (gLocalLinkPlayerId) must be 1 (RIGHT seat), "
            f"got {self_id}. mpId 0 is the host/parent [link.c:965-971; trade.c:1816].")
        self.self_id = self_id
        self.partner_id = self_id ^ 1        # = 0, the host (LEFT) [trade.c:984-985]
        self.log = log
        self.info = getattr(log, "info", log)   # clean milestone sink (default-mode narration)
        self._out = out                      # STDOUT sink (for the cancel-to-leave message)

        self.state = PRE_SEAT
        self._held_key_count = 0             # static u8 heldKeyCount [link_rfu_2.c:1071]; ++ before OR
        self._pending_once = None            # a one-shot key (READY/EXIT_ROOM) to emit next tick
        self._route = deque()                # queued seat-walk key codes (ENTRY_RIGHT_CHAIR_ROUTE)
        self._walking = False
        self._seated = False
        self._exiting = False
        # host-side mirror of OUR own slot's link state, advanced by the key WE send (the host
        # does this in HandleLinkPlayerKeyInput [overworld.c:2749-2766]); exposed for tests/asserts.
        self.our_link_state = PLAYER_LINK_STATE_IDLE

    # ---- orchestrator signals ----------------------------------------------
    @property
    def seated(self):
        """True once our READY (0x16) has actually gone out."""
        return self._seated

    @property
    def walking(self):
        """True while seat-walk route frames are still queued."""
        return bool(self._route)

    def walk_to_seat(self):
        """Walk the RIGHT-chair route and sit at the end of it (ENTRY_RIGHT_CHAIR_ROUTE).

        Call this once the host is in the trade room. Prefer it to sit(): firing READY without
        walking puts our avatar in the doorway with a READY the host's cable-seat FSM rejects as
        out of sequence, and standing still forever deadlocks - the host is waiting for our READY
        while we wait for its own."""
        if self._walking or self._seated:
            return
        self._walking = True
        for keycode, frames in ENTRY_RIGHT_CHAIR_ROUTE:
            self._route.extend([keycode] * max(0, int(frames)))
        self.info("Walking to the right seat.")
        self.log(f"linkstate: walk_to_seat() -> {len(self._route)} route frames to the RIGHT chair")

    def sit(self):
        """Take the RIGHT seat: emit LINK_KEY_CODE_READY(0x16) on exactly the NEXT tick, then
        keepalive in SEATED. Mirrors Task_EnterCableClubSeat -> SetInCableClubSeat ->
        KeyInterCB_SetReady [cable_club.c:839; overworld.c:2951-2955]."""
        if self._seated:
            return
        self._seated = True
        self._pending_once = LINK_KEY_CODE_READY
        self.info("Setting sit flag.")
        self.log("linkstate: sit() -> READY(0x16) at RIGHT seat (mpId 1)")

    def exit(self):
        """Cancel-to-leave: emit LINK_KEY_CODE_EXIT_ROOM(0x17) on exactly the
        NEXT tick, then keepalive while waiting for the host to also exit. Mirrors
        QueueExitLinkRoomKey -> KeyInterCB_SendExitRoomKey [overworld.c:2977-2981]. The trade
        engine separately emits LINKCMD REQUEST_CANCEL(0xEEAA) [trade.c:2049]; this is the
        overworld-layer exit that follows it. Prints the intent to STDOUT."""
        if self._exiting:
            return
        self._exiting = True
        self._pending_once = LINK_KEY_CODE_EXIT_ROOM
        self.state = EXITING
        self.info("Leaving the room.")
        self.log("linkstate: exit() -> EXIT_ROOM(0x17); keepalive until the host also exits the room")

    def host_exiting(self):
        """Signal that the host slot has reached EXITING_ROOM (host emitted its own EXIT_ROOM /
        AreAllPlayersInLinkState(EXITING_ROOM) is now true). Mirrors KeyInterCB_WaitForPlayersToExit
        clearing to KeyInterCB_SendNothing [overworld.c:2969-2973]."""
        if self.state == EXITING:
            self.state = SEND_NOTHING
            self.log("linkstate: host EXITING_ROOM -> SEND_NOTHING")

    # ---- per-VBlank emit ----------------------------------------------------
    def _emit(self, keycode):
        """Pack ONE held-keys slot exactly as SendKeysToRfu + RfuPrepareSendBuffer do:
        heldKeyCount++ then w1 = (heldKeyCount<<8) | keycode, w0 = 0xBE00 [link_rfu_2.c:1076-1077,
        1315-1316]. Returns a 7-word pre-tag gSendCmd run (rfu.SlotBuilder adds the rolling tag)."""
        self._held_key_count = (self._held_key_count + 1) & 0xFF
        w1 = ((self._held_key_count & 0xFF) << 8) | (keycode & 0xFF)
        # advance our own host-mirrored link state from the key, like HandleLinkPlayerKeyInput.
        if keycode == LINK_KEY_CODE_READY:
            self.our_link_state = PLAYER_LINK_STATE_READY
        elif keycode == LINK_KEY_CODE_EXIT_ROOM:
            self.our_link_state = PLAYER_LINK_STATE_EXITING_ROOM
        elif keycode == LINK_KEY_CODE_IDLE:
            self.our_link_state = PLAYER_LINK_STATE_IDLE
        return [rfu.SEND_HELD_KEYS, w1, 0, 0, 0, 0, 0]

    def tick(self):
        """Return the 7-word held-keys gSendCmd run for this VBlank. NEVER returns all-zero idle in
        the overworld/seat phase - it always emits a 0xBE00 slot so the HOST's view of OUR slot stays
        live (it keeps seeing us / our READY). This is NOT the child-local CheckRfuKeepAliveTimer (that
        is the child's own >60-frame watchdog, reset by a key-intercept callback CHANGE and not even
        running once seated [overworld.c:2613-2626, 2941]); it is the wire keepalive the host needs."""
        # the seat walk, one key per VBlank, ahead of the steady keepalive. EXIT_ROOM still preempts
        # it (the host can walk out mid-route), but nothing else does.
        if self._route and self._pending_once is None:
            key = self._route.popleft()
            if key == LINK_KEY_CODE_READY:
                self._seated = True
                self.state = SEATED
                self.info("Sat down at the right seat.")
            return self._emit(key)
        # one-shot READY/EXIT_ROOM takes precedence, exactly once.
        if self._pending_once is not None:
            key = self._pending_once
            self._pending_once = None
            if key == LINK_KEY_CODE_READY:
                self.state = SEATED
            return self._emit(key)
        # steady keepalive in every state (EMPTY does not change link state but IS a live command).
        return self._emit(LINK_KEY_CODE_EMPTY)

    # ---- convenience for the sim host-model (offline tests) ------------------
    @staticmethod
    def key_of(words):
        """Extract the low-byte key code from a held-keys gSendCmd run (or a parsed slot's w1)."""
        return words[1] & 0xFF

    @staticmethod
    def nonce_of(words):
        """Extract the high-byte liveness nonce (heldKeyCount) from a held-keys gSendCmd run."""
        return (words[1] >> 8) & 0xFF
