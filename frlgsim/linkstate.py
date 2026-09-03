"""Held-keys overworld link-state engine: the child's CB1_UpdateLinkState / SendKeysToRfu chain
[overworld.c:2579-2599; link_rfu_2.c:1069-1080]. The joiner is mpId 1 = gLocalLinkPlayerId = the RIGHT seat; the
chair id is cosmetic. Held keys replace an IDLE slot only, never a SEND_BLOCK/LINKCMD slot."""

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

PRE_SEAT = "PRE_SEAT"
SEATED = "SEATED"
EXITING = "EXITING"
SEND_NOTHING = "SEND_NOTHING"

# 60-frame watchdog (CheckRfuKeepAliveTimer >60 -> LinkRfu_FatalError [overworld.c:2623-2626]).
KEEPALIVE_WATCHDOG = 60

# The seat walk is real player input relayed over the link: a child that only sends EMPTY stands in the
# doorway and the host waits for a READY that never comes. The EMPTY gaps between direction changes are
# load-bearing (a step must finish before a new direction is accepted); the route costs one slot per host poll.
TILE_STEP_FRAMES = 16


def _step_gap(run_frames):
    # A step is exactly 16 link updates (directionSequenceIndex=16, decremented once per update while frozen
    # [overworld.c:3432-3470]); a run of N keys leaves N mod 16 of its last step spent, so cover the rest, +1.
    return (TILE_STEP_FRAMES - (run_frames % TILE_STEP_FRAMES)) % TILE_STEP_FRAMES + 1


# Each route frame costs one host link update and the console's trade room can be short-lived; keep it short.
ENTRY_RIGHT_CHAIR_ROUTE = (
    (LINK_KEY_CODE_EMPTY, 4),
    (LINK_KEY_CODE_DPAD_UP, 43),
    (LINK_KEY_CODE_EMPTY, _step_gap(43)),
    (LINK_KEY_CODE_DPAD_RIGHT, 9),
    (LINK_KEY_CODE_EMPTY, _step_gap(9)),
    (LINK_KEY_CODE_DPAD_UP, 7),
    (LINK_KEY_CODE_EMPTY, _step_gap(7)),
    (LINK_KEY_CODE_READY, 1),
)


class LinkState:
    def __init__(self, self_id=1, log=lambda *a: None, out=print):
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
        # host-side mirror of our slot's link state, advanced from the key we send [overworld.c:2749-2766]
        self.our_link_state = PLAYER_LINK_STATE_IDLE

    @property
    def seated(self):
        return self._seated

    @property
    def walking(self):
        return bool(self._route)

    def walk_to_seat(self):
        """Prefer this to sit(): a READY fired from the doorway is rejected by the host's cable-seat FSM and
        both sides then wait forever."""
        if self._walking or self._seated:
            return
        self._walking = True
        for keycode, frames in ENTRY_RIGHT_CHAIR_ROUTE:
            self._route.extend([keycode] * max(0, int(frames)))
        self.info("Walking to the right seat.")
        self.log(f"linkstate: walk_to_seat() -> {len(self._route)} route frames to the RIGHT chair")

    def sit(self):
        """Emits READY(0x16) exactly once on the next tick [cable_club.c:839; overworld.c:2951-2955]."""
        if self._seated:
            return
        self._seated = True
        self._pending_once = LINK_KEY_CODE_READY
        self.info("Setting sit flag.")
        self.log("linkstate: sit() -> READY(0x16) at RIGHT seat (mpId 1)")

    def exit(self):
        """Emits EXIT_ROOM(0x17) exactly once on the next tick [overworld.c:2977-2981]; the overworld-layer exit
        that follows the trade engine's REQUEST_CANCEL."""
        if self._exiting:
            return
        self._exiting = True
        self._pending_once = LINK_KEY_CODE_EXIT_ROOM
        self.state = EXITING
        self.info("Leaving the room.")
        self.log("linkstate: exit() -> EXIT_ROOM(0x17); keepalive until the host also exits the room")

    def host_exiting(self):
        if self.state == EXITING:
            self.state = SEND_NOTHING
            self.log("linkstate: host EXITING_ROOM -> SEND_NOTHING")

    def _emit(self, keycode):
        """heldKeyCount++ then w1 = (count<<8) | key [link_rfu_2.c:1076-1077]: the first emit carries high byte 1."""
        self._held_key_count = (self._held_key_count + 1) & 0xFF
        w1 = ((self._held_key_count & 0xFF) << 8) | (keycode & 0xFF)
        if keycode == LINK_KEY_CODE_READY:
            self.our_link_state = PLAYER_LINK_STATE_READY
        elif keycode == LINK_KEY_CODE_EXIT_ROOM:
            self.our_link_state = PLAYER_LINK_STATE_EXITING_ROOM
        elif keycode == LINK_KEY_CODE_IDLE:
            self.our_link_state = PLAYER_LINK_STATE_IDLE
        return [rfu.SEND_HELD_KEYS, w1, 0, 0, 0, 0, 0]

    def tick(self):
        """Never returns an all-zero idle: the host's view of our slot needs a 0xBE00 every VBlank in the seat phase."""
        # EXIT_ROOM preempts the route (the host can walk out mid-route); nothing else does.
        if self._route and self._pending_once is None:
            key = self._route.popleft()
            if key == LINK_KEY_CODE_READY:
                self._seated = True
                self.state = SEATED
                self.info("Sat down at the right seat.")
            return self._emit(key)
        if self._pending_once is not None:
            key = self._pending_once
            self._pending_once = None
            if key == LINK_KEY_CODE_READY:
                self.state = SEATED
            return self._emit(key)
        return self._emit(LINK_KEY_CODE_EMPTY)

    @staticmethod
    def key_of(words):
        return words[1] & 0xFF

    @staticmethod
    def nonce_of(words):
        return (words[1] >> 8) & 0xFF
