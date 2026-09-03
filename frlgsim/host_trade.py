"""Leader-side FRLG trade-room engine: tick() returns one parent gSendCmd (seven u16 words) for UNI
row 0, feed_child_slot() consumes the child's reflected 14-byte row. The leader owns SET_MONS/START/
CONFIRM and every cancel decision, so the follower engine in frlgsim.trade cannot be reused with mpid=0."""

from collections import Counter, deque
from dataclasses import dataclass

from . import (battle_link as bl, block, linkplayer, mon as monmod, rfu, rfu_leader,
               trade, uroom_battle, uroom_chat)


# Only a deadlock guard: the console re-sends a fragment until it sees the echo, so this
# should never fire. It is logged when it does.
ECHO_WAIT_MAX_POLLS = 240
STATUS_REPORT_FRAMES = 30   # 0.5s; the H_LINK_PLAYER stall window is only ~2s
LEAVE_MENU_REPORT_FRAMES = 300
H_LINK_PLAYER = "H_LINK_PLAYER"
H_ENTRY_CARD = "H_ENTRY_CARD"
# Union Room only: cards are exchanged, the console is at its "do something" prompt and every
# choice arrives as a SEND_PACKET [union_room.c:2928, :2955].
H_UROOM_PROMPT = "H_UROOM_PROMPT"
# Union Room only: a trading-board request was accepted; Task_StartUnionRoomTrade exchanges one
# Pokemon block then one mail block, then CB2_LinkTrade with the mons preselected
# [union_room.c:1713].
H_UROOM_TRADE = "H_UROOM_TRADE"
# Union Room only: a chat request was accepted. Both members SendBlock a JOIN, then one 0x28
# block per line typed, until the leader DISBANDs or the child LEAVEs [union_room_chat.c:429].
H_UROOM_CHAT = "H_UROOM_CHAT"
# Union Room only: a battle request was accepted. Both sides send a 0x20 selection block, two link
# standbys pass, then a 31-byte LinkBattlerHeader and the party three blocks at a time
# [CB2_UnionRoomBattle, CB2_HandleStartBattle battle_main.c:934].
H_UROOM_BATTLE = "H_UROOM_BATTLE"
# ...and then the battle proper: the console is master and runs the whole engine, we answer its
# controller commands [InitLinkBtlControllers, battle_controllers.c:141].
H_UROOM_BATTLE_LINK = "H_UROOM_BATTLE_LINK"
H_ENTRY_SEAT = "H_ENTRY_SEAT"
H_PARTY = "H_PARTY"
H_SELECT = "H_SELECT"
H_CONFIRM = "H_CONFIRM"
H_ANIM = "H_ANIM"
H_SAVE = "H_SAVE"
H_LEAVE_MENU = "H_LEAVE_MENU"
H_CANCEL = "H_CANCEL"
H_RETURN_FIELD = "H_RETURN_FIELD"
H_EXIT = "H_EXIT"
H_CLOSE = "H_CLOSE"
H_DONE = "H_DONE"


@dataclass(frozen=True)
class HostTradeTiming:
    # A native completed trade has six consecutive child-initiated standby rounds before BufferTradeParties.
    save_barrier_rounds: int = 6
    # The child repeats the sixth post-save standby after 60 frames until the parent echo completes.
    save_final_standby_quiet_frames: int = 75
    # BufferTradeParties needs a quiescent window after the child's first IDLE reaches the host.
    party_link_settle_frames: int = 30
    startup_standby_echo_frames: int = 4
    # The child parks in Task_PlayerExchange case 2 until a *received* SEND_PLAYER_IDS sets
    # gRfu.playerCount; a single-VBlank emission is missed [decomp:src/link_rfu_2.c:1832].
    player_ids_repeat_frames: int = 8
    # After both LinkPlayer blocks land the console may idle waiting for the leader to move first, and
    # nothing on the wire reports block consumption; counted only after our own block has drained.
    link_player_idle_frames: int = 12
    # Longer than SendReadyExitStandbyUntilAllReady's native re-emission cadence.
    entry_final_standby_quiet_frames: int = 75
    # CB2_CreateTradeMenu needs time to finish installing its menu callback.
    final_menu_ready_frames: int = 5 * 60
    post_cancel_exit_wait_frames: int = 5 * 60
    # Keep Pia traffic alive after READY_CLOSE_LINK while the Switch completes its fade/warp.
    post_client_close_grace_frames: int = 15 * 60
    close_retry_frames: int = 60
    # Task_ReceiveChatMessage latches one block per player and scrolls it in; back-to-back sends
    # would overwrite gBlockRecvBuffer before it reads. A typed line is seconds apart natively.
    chat_message_gap_frames: int = 90
    # ChatEntryRoutine_ExitChat runs SetCloseLinkCallback and then waits on
    # !gReceivedRemoteLinkPlayers [union_room_chat.c:665]. u14: the leaver DOES answer with its own
    # READY_CLOSE_LINK (0.1s) and its 'D' right after, so this bound is only the fallback for a
    # leaver that stays silent; it must stay short, since it is the console's whole wait.
    chat_exit_close_frames: int = 120


DEFAULT_HOST_TRADE_TIMING = HostTradeTiming()

SAVE_BARRIER_ROUNDS = DEFAULT_HOST_TRADE_TIMING.save_barrier_rounds
SAVE_FINAL_STANDBY_QUIET_FRAMES = DEFAULT_HOST_TRADE_TIMING.save_final_standby_quiet_frames
PARTY_LINK_SETTLE_FRAMES = DEFAULT_HOST_TRADE_TIMING.party_link_settle_frames
STARTUP_STANDBY_ECHO_FRAMES = DEFAULT_HOST_TRADE_TIMING.startup_standby_echo_frames
PLAYER_IDS_REPEAT_FRAMES = DEFAULT_HOST_TRADE_TIMING.player_ids_repeat_frames
LINK_PLAYER_IDLE_FRAMES = DEFAULT_HOST_TRADE_TIMING.link_player_idle_frames
ENTRY_FINAL_STANDBY_QUIET_FRAMES = DEFAULT_HOST_TRADE_TIMING.entry_final_standby_quiet_frames
FINAL_MENU_READY_FRAMES = DEFAULT_HOST_TRADE_TIMING.final_menu_ready_frames
POST_CANCEL_EXIT_WAIT_FRAMES = DEFAULT_HOST_TRADE_TIMING.post_cancel_exit_wait_frames
POST_CLIENT_CLOSE_GRACE_FRAMES = DEFAULT_HOST_TRADE_TIMING.post_client_close_grace_frames
CLOSE_RETRY_FRAMES = DEFAULT_HOST_TRADE_TIMING.close_retry_frames
CHAT_MESSAGE_GAP_FRAMES = DEFAULT_HOST_TRADE_TIMING.chat_message_gap_frames
CHAT_EXIT_CLOSE_FRAMES = DEFAULT_HOST_TRADE_TIMING.chat_exit_close_frames
HOST_NAME_PAD = linkplayer.HOST_NAME_PAD

# Native leader route from the cable-club entrance to the LEFT trade chair as (LINK_KEY_CODE low byte,
# held frames); the high byte is a rolling heldKeyCount. READY is emitted exactly once, at count 161.
LINK_KEY_EMPTY = 0x11
LINK_KEY_UP = 0x13
LINK_KEY_LEFT = 0x14
LINK_KEY_READY = 0x16
LINK_KEY_EXIT_ROOM = 0x17
ENTRY_LEFT_CHAIR_ROUTE = (
    (LINK_KEY_EMPTY, 43),
    (LINK_KEY_UP, 9),
    (LINK_KEY_EMPTY, 4),
    (LINK_KEY_UP, 14),
    (LINK_KEY_EMPTY, 31),
    (LINK_KEY_LEFT, 5),
    (LINK_KEY_EMPTY, 12),
    (LINK_KEY_UP, 17),
    (LINK_KEY_EMPTY, 25),
    (LINK_KEY_READY, 1),
    (LINK_KEY_EMPTY, 7),
)


class HostTradeEngine:
    ECHO_WAIT_MAX_POLLS = ECHO_WAIT_MAX_POLLS
    """Call feed_child_slot(cmd14) for each *new* child UNI command and tick() once per VBlank; after
    disconnect_requested, queue 'D' only after Reliable has delivered the final close-link poll."""

    @property
    def close_confirmed(self):
        return self._close_confirmed

    def __init__(self, party, trade_slot=0, *, offered_slots=None, trades=1,
                 link_player=None, profile=None, anim_delay=1935, trust_pia=True, timing=None,
                 union_room=False, union_room_chat=False, chat_messages=None,
                 union_room_battle=False, battle_forfeit=True, battle_move_slot=0,
                 log=lambda *a: None):
        self.party = list(party)
        if not 1 <= len(self.party) <= 6:
            raise ValueError("party must contain 1..6 Pokémon")
        if not 1 <= trades <= 6:
            raise ValueError("trades must be 1..6")
        self.trades = trades
        self.offered_slots = trade.resolve_offered_slots(
            offered_slots, trade_slot, trades, party_size=len(self.party))
        if any(i >= len(self.party) for i in self.offered_slots):
            raise ValueError("offered slot exceeds party size")
        if link_player is not None and profile is not None:
            raise ValueError("supply link_player or profile, not both")
        self.lp = (profile.to_link_player() if profile is not None else link_player) \
            or linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED)
        self.trainer_card = linkplayer.build_trainer_card(
            self.lp, mon_species=[m.species for m in self.party],
            name_pad=HOST_NAME_PAD)
        self.anim_delay = anim_delay
        self.trust_pia = trust_pia
        self.union_room = bool(union_room)
        self.union_room_chat = bool(union_room_chat)
        self.union_room_battle = bool(union_room_battle)
        if self.union_room_battle and len(self.party) < 2:
            # SetUpPartiesAndStartBattle keeps exactly two mons a side [union_room_battle.c:47];
            # with one, the console's gEnemyParty[1] stays zero and the battle has nothing to send
            # out second. Fail at start-up, not three blocks into a hardware run.
            raise ValueError("a Union Room battle needs two party Pokemon; pass a second with "
                             "PARTY2= or --party")
        self.battle_forfeit = bool(battle_forfeit)
        self.battle_move_slot = int(battle_move_slot)
        self.battle = None                 # the BattleController, once the battle starts
        self.echo_backlog = 0              # set by HostSession each poll; see _echo_owed
        self.echo_progress = 0             # monotonic count of echoes that have left the queue
        self.last_echo_cmd = None          # the child slot the leader most recently mirrored back
        self._child_slot = None            # the slot currently being fed to us
        self._echo_wait_slot = None        # the slot that must be mirrored before we answer
        self._echo_wait_polls = 0
        self._battle_party_block = 0
        self.uroom_requests = []
        self.uroom_trade_request = None
        self.chat_received = []            # parsed blocks from the console, in arrival order
        self._chat_outbox = deque(uroom_chat.check_text(t) for t in (chat_messages or ()))
        self._chat_joined = False
        self._chat_send_wait = None
        self._chat_exiting = False
        self._last_uroom_packet = None
        self._last_uroom_frame = 0
        self.timing = timing if timing is not None else DEFAULT_HOST_TRADE_TIMING
        self.log = log
        self.info = getattr(log, "info", log)

        self.state = H_LINK_PLAYER
        self.state_history = [self.state]
        self.round = 0
        self.commits = 0
        self.received_mons = []
        self.child_link_player = None
        self.child_card = None
        self.child_party = bytearray(600)
        self.child_cursor = None
        self.done = False
        self.disconnect_requested = False

        self._rx = block.RecvBlock()
        self._words = deque()
        self._blocks = deque()
        self._sender = None
        self._expected = None
        self._party_pair = 0
        self._link_waiting_idle = False
        self._link_idle_frames = 0
        self._link_completed = None
        self._link_player_idle = 0
        self._child_finish = False
        self._anim_wait = None
        self._save_rounds = 0
        self._save_last_count = None
        self._save_final_standby_seen = False
        self._save_standby_quiet = 0
        self._last_child_standby = None
        self._entry_final_standby_seen = False
        self._entry_standby_quiet = 0
        self._exit_count = 0
        self._cancel_standby_count = None
        self._return_standby_count = None
        self._return_standby_quiet = 0
        self._room_exit_wait = None
        self._child_exit_seen = False
        self._leave_menu_wait = None
        self._host_cancel_ready = False
        self._child_cancel_requested = False
        self._select_cancels = 0        # consecutive console CANCELs at the select screen
        # Every entry into H_CLOSE resets this; a real value rather than None keeps the type stable
        # for _tick_close_link, which is the only reader.
        self._close_retry_wait = self.timing.close_retry_frames
        self._close_confirmed = False
        self._close_grace_wait = None
        # Room entry is a real held-key movement route, not a static READY flag; omitting it strands
        # the child on the black room-transition screen.
        self._child_slot_runs = []
        self._child_key_runs = []
        self._held_count = 0
        self._held_plan = deque()
        self._held_steady = None
        self._held_label = None
        self._child_frames = 0
        self._child_idles = 0
        self._child_op_counts = Counter()
        self._child_ops = set()
        self._parent_polls = 0
        self._status_countdown = STATUS_REPORT_FRAMES
        self._leave_menu_run_mark = 0
        self._leave_menu_frame_mark = 0
        self._leave_menu_idle_mark = 0
        self._leave_menu_report = None
        self.trace = []

        # SEND_PLAYER_IDS is idempotent in RfuHandleReceiveCommand, so repeating it is safe.
        for _ in range(self.timing.player_ids_repeat_frames):
            self._queue_words(rfu.send_player_ids_words(), "SEND_PLAYER_IDS")
        self._link_player_block = linkplayer.build_block(
            self.lp, name_pad=HOST_NAME_PAD).ljust(200, b"\x00")
        # Native case 3 emits only the block request and parks until the child's block lands
        # [decomp:src/link_rfu_2.c:1852]; our block goes out from _after_child_block on a valid child block.
        self._expected = "link_player"
        self._queue_words(rfu.send_block_req_words(trade.BLOCK_REQ_SIZE_NONE),
                          "BLOCK_REQ:link_player")

    def _report_leave_menu(self):
        frames = self._child_frames - self._leave_menu_frame_mark
        idles = self._child_idles - self._leave_menu_idle_mark
        runs = self._child_slot_runs[self._leave_menu_run_mark:]
        if not runs:
            # A run that started before the mark grows in place, so empty means "no new run", not "no frames".
            tail = ("no frames at all - the console is off the air"
                    if frames == 0 else
                    f"one unbroken run continuing from before the refresh ({frames} frames)")
        else:
            tail = ", ".join(
                f"{'IDLE' if op is None else rfu.RFUCMD_NAMES.get(op, hex(op))}"
                f"{'' if op is None else f'/{w1:#06x}'}x{n}"
                for (op, w1), n in runs[-8:])
        self.info(
            f"Waiting in H_LEAVE_MENU for the Switch CANCEL; host cancel ready="
            f"{self._host_cancel_ready}, child cancel seen={self._child_cancel_requested}. "
            f"Console has sent since the party refresh: {frames} frames "
            f"({idles} idle): {tail}")

    def _report_status(self):
        ops = ", ".join(
            f"{rfu.RFUCMD_NAMES.get(op, hex(op))}x{count}"
            for op, count in sorted(self._child_op_counts.items(),
                                    key=lambda kv: -kv[1])) or "none"
        self.info(
            f"Waiting in {self.state}: expecting {self._expected!r}, "
            f"console LinkPlayer {'received' if self.child_link_player else 'NOT received'}, "
            f"child frames {self._child_frames} ({self._child_idles} idle) "
            f"vs parent polls {self._parent_polls}, "
            f"queued words {len(self._words)} blocks {len(self._blocks)}, "
            f"opcodes seen: {ops}")

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_history.append(state)
            self.trace.append(("state", state))
            self.log(f"host trade: -> {state}")

    def _queue_words(self, words, label):
        self._words.append(list(words))
        self.trace.append(("queue", label))

    def _queue_block(self, data, label):
        self._blocks.append((bytes(data), label))
        self.trace.append(("queue_block", label, len(data)))

    def child_route_runs(self):
        return tuple((k, n) for k, n in self._child_key_runs)

    def child_slot_runs(self):
        return tuple((tuple(k), n) for k, n in self._child_slot_runs)

    def format_child_slots(self):
        out = []
        for (op, w1), n in self.child_slot_runs():
            name = "IDLE" if op is None else rfu.RFUCMD_NAMES.get(op, f"0x{op:04x}")
            detail = "" if op is None else f" w1=0x{w1:04x}"
            out.append(f"    {name}{detail} x{n}")
        return "\n".join(out)

    def _set_held_plan(self, runs, label, steady=None):
        self._held_plan.clear()
        for keycode, count in runs:
            self._held_plan.extend([keycode & 0xFF] * max(0, int(count)))
        self._held_steady = None if steady is None else steady & 0xFF
        self._held_label = label
        self.trace.append(("held_plan", label, len(self._held_plan), self._held_steady))

    def _hold_key(self, keycode, label):
        self._set_held_plan(((keycode, 1),), label, steady=LINK_KEY_EMPTY)

    def _start_entry_route(self):
        self._set_held_plan(ENTRY_LEFT_CHAIR_ROUTE, "ENTRY_LEFT_CHAIR")

    def _release_key(self, label):
        if self._held_plan or self._held_steady is not None:
            self.trace.append(("release", label))
        self._held_plan.clear()
        self._held_steady = None
        self._held_label = None

    def _next_held_words(self):
        if self._held_plan:
            keycode = self._held_plan.popleft()
        elif self._held_steady is not None:
            keycode = self._held_steady
        else:
            return None
        self._held_count = (self._held_count + 1) & 0xFF
        value = (self._held_count << 8) | keycode
        self.trace.append(("emit_held", self._held_label, value))
        words = rfu.held_keys_words(value)
        # Even if the Switch exited first, our EXIT_ROOM must be exposed for one full parent poll before READY_CLOSE_LINK.
        if (keycode == LINK_KEY_EXIT_ROOM and self.state == H_EXIT
                and self._child_exit_seen):
            self._complete_room_exit()
        return words

    def _request_and_send(self, reqtype, data, expected):
        self._expected = expected
        self._queue_words(rfu.send_block_req_words(reqtype), f"BLOCK_REQ:{reqtype}:{expected}")
        self._queue_block(data, f"host:{expected}")

    def _send_linkcmd(self, cmd, cursor=0):
        self._queue_block(trade.linkcmd_block(cmd, cursor), trade.LINKCMD_NAMES[cmd])

    def _enter_cancel_to_leave(self):
        if not (self._host_cancel_ready and self._child_cancel_requested):
            raise RuntimeError("BOTH_CANCEL requires both leader and follower cancel decisions")
        self._set_state(H_CANCEL)
        self._cancel_standby_count = None
        self._return_standby_count = None
        self._return_standby_quiet = 0
        self._room_exit_wait = None
        self._child_exit_seen = False
        self._send_linkcmd(trade.BOTH_CANCEL_TRADE)
        self.info("Switch CANCEL received; both players cancelled. Leaving the trade menu.")

    def _leader_cancel_is_ready(self):
        self._host_cancel_ready = True
        self.trace.append(("leader_cancel_ready",))
        if self._child_cancel_requested:
            self._enter_cancel_to_leave()
        else:
            self.info(
                "Linux host is ready to leave. On the Switch, select CANCEL and confirm YES.")

    def _finish_party_exchange(self):
        self._expected = None
        if self.round >= self.trades:
            self._set_state(H_LEAVE_MENU)
            self._leave_menu_wait = self.timing.final_menu_ready_frames
            self._host_cancel_ready = False
            self._child_cancel_requested = False
            self._leave_menu_run_mark = len(self._child_slot_runs)
            self._leave_menu_frame_mark = self._child_frames
            self._leave_menu_idle_mark = self._child_idles
            self._leave_menu_report = LEAVE_MENU_REPORT_FRAMES
            self.info("Final party refresh complete; waiting 5 seconds for the trade menu.")
        else:
            self._select_cancels = 0
            self._set_state(H_SELECT)

    def _begin_room_exit(self, *, child_already_exited=False):
        self._set_state(H_EXIT)
        self._room_exit_wait = None
        self._child_exit_seen = bool(child_already_exited)
        self._hold_key(LINK_KEY_EXIT_ROOM, "EXIT_ROOM_KEY")
        if child_already_exited:
            self.info("Switch exited the room first; sending the Linux EXIT_ROOM response.")
        else:
            self.info("Five-second room delay complete; Linux is exiting the trade room.")

    def _complete_room_exit(self):
        if self.state != H_EXIT:
            return
        self._release_key("EXIT_ROOM_KEY")
        self.trace.append(("child_key", "EXIT_ROOM"))
        self._set_state(H_CLOSE)
        self._close_confirmed = False
        self._close_grace_wait = None
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
        self._close_retry_wait = self.timing.close_retry_frames
        self.info("Both players left the room; closing the RFU link.")

    def _begin_card_exchange(self):
        self._set_state(H_ENTRY_CARD)
        self._request_and_send(trade.BLOCK_REQ_SIZE_100, self.trainer_card, "card")

    def _begin_party_exchange(self):
        self._set_state(H_PARTY)
        self.child_party = bytearray(600)
        self._party_pair = 0
        self._request_party_pair()

    def _request_party_pair(self):
        host_party = monmod.party_blocks(monmod.build_player_party(self.party))
        self._request_and_send(trade.BLOCK_REQ_SIZE_200,
                               host_party[self._party_pair], f"party:{self._party_pair}")

    def _after_child_block(self, count, data):
        expected = self._expected
        self.trace.append(("child_block", expected, count))
        expected_count = {
            "link_player": trade.COUNT_PARTY,
            "card": trade.COUNT_TRAINER_CARD,
            "mail": trade.COUNT_MAIL,
            "ribbons": trade.COUNT_RIBBON,
            "uroom_mon": trade.COUNT_TRAINER_CARD,     # one 100-byte Pokemon
            "uroom_mail": trade.COUNT_MAIL,
            "uroom_chat": trade.COUNT_RIBBON,          # the 0x28-byte chat block
            "battle_accept": uroom_battle.COUNT_ACCEPT,
            "battle_header": uroom_battle.COUNT_HEADER,
        }.get(expected, trade.COUNT_PARTY
              if expected and (expected.startswith("party:") or expected.startswith("battle_party:"))
              else None)
        if expected == "battle_link":
            # Link buffer records are sized by their payload, from 12 bytes to over 100, so there is
            # no fixed count to check here [PrepareBufferDataTransferLink, battle_controllers.c:412].
            self._on_battle_block(data)
            return
        if expected_count is None:
            self.trace.append(("unexpected_child_block", count))
            return
        if count != expected_count:
            raise ValueError(f"child block count {count}, expected {expected_count} for {expected}")
        if expected == "link_player":
            lp, ok = linkplayer.parse_block(data)
            if not ok:
                # A block that predates Task_PlayerExchange case 0 carries stale buffer bytes: a too-early request, not fatal.
                self._rejected_link_players = getattr(self, "_rejected_link_players", 0) + 1
                self.trace.append(("link_player_rejected", self._rejected_link_players))
                self.info("Console LinkPlayer block had an invalid GameFreak magic "
                          f"(#{self._rejected_link_players}); still waiting for a valid one.")
                return
            self.child_link_player = lp
            self._expected = "warp0"
            self._queue_block(self._link_player_block, "host:link_player")
            self.info(f"Console identified as {lp.name!r}; sending the host LinkPlayer block now.")
            return
        if expected == "uroom_chat":
            self._on_chat_block(data)
            return
        if expected == "battle_accept":
            self._on_battle_accept(data)
            return
        if expected == "battle_header":
            self._on_battle_header(data)
            return
        if expected and expected.startswith("battle_party:"):
            self._on_battle_party(int(expected.split(":", 1)[1]), data)
            return
        if expected == "uroom_mon":
            # Task_StartUnionRoomTrade case 0/1: both sides SendBlock their registered mon, no
            # request first [union_room.c:1721]. Ours goes out once theirs is in, like LinkPlayer.
            self.child_party = bytearray(600)
            self.child_party[0:monmod.PARTY_MON_SIZE] = data[:monmod.PARTY_MON_SIZE]
            self.child_cursor = 0
            slot = self.offered_slots[self.round]
            host_party = monmod.build_player_party(self.party)
            self._queue_block(host_party[slot * monmod.PARTY_MON_SIZE:
                                         (slot + 1) * monmod.PARTY_MON_SIZE], "host:uroom_mon")
            self._expected = "uroom_mail"
            self.info("Union Room trade: console Pokemon block received; sending ours, "
                      "mail blocks next.")
            return
        if expected == "uroom_mail":
            # case 2/3: mail both ways, then CB2_LinkTrade with the mons preselected. From here the
            # trade-centre animation path applies: READY_FINISH from the console, our CONFIRM.
            self._queue_block(trade.empty_mail_block(), "host:uroom_mail")
            self._expected = None
            self._child_finish = False
            self._set_state(H_ANIM)
            self._anim_wait = self.anim_delay
            self.info("Union Room trade: mail exchanged; the trade animation runs now.")
            return
        if expected == "card":
            self.child_card = bytes(data[:100])
            if self.union_room:
                # No standby follows Task_ExchangeCards in the room [union_room.c:1753]; the console
                # goes to its prompt and talks in SEND_PACKETs from here on.
                self._expected = None
                self._set_state(H_UROOM_PROMPT)
                self.info("Union Room: trainer cards exchanged; waiting at the console's "
                          "'do something' prompt for a SEND_PACKET.")
                return
            self._expected = "warp1"
            return
        if expected and expected.startswith("party:"):
            i = int(expected.split(":", 1)[1])
            self.child_party[i * 200:(i + 1) * 200] = data[:200]
            # BufferTradeParties gates the next request on IsLinkTaskFinished(), not a standby barrier.
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = f"party:{i}"
            self.trace.append(("party_wait_idle", i))
            self.info(f"Party block {i + 1}/3 exchanged; waiting for the Switch link task to finish.")
            return
        if expected == "mail":
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = "mail"
            self.trace.append(("mail_wait_idle",))
            self.info("Mail block exchanged; waiting for the Switch link task to finish.")
            return
        if expected == "ribbons":
            self._link_waiting_idle = True
            self._link_idle_frames = 0
            self._link_completed = "ribbons"
            self.trace.append(("ribbons_wait_idle",))
            self.info("Ribbon block exchanged; waiting for the Switch link task to finish.")

    def feed_child_slot(self, slot):
        """Consume one child gSendCmd row (14 bytes, rolling tag permitted)."""
        self._child_slot = rfu_leader._normalize_child_cmd(slot)
        self._child_frames += 1
        is_idle = bytes(slot) == rfu.idle_slot()
        self._record_child_slot_run(slot, is_idle)
        if is_idle:
            self._child_idles += 1
        else:
            self._count_child_op(slot)
        if is_idle:
            self._feed_idle_slot()
            return
        if self.state == H_PARTY and self._link_waiting_idle:
            self._link_idle_frames = 0
        self._link_player_idle = 0
        rec = rfu.parse_slot(slot)
        if rec is None:
            return
        handler = _CHILD_OP_HANDLERS.get(rec["op"])
        if handler is not None:
            handler(self, rec)

    def _record_child_slot_run(self, slot, is_idle):
        _r = None if is_idle else rfu.parse_slot(slot)
        _key = (None, 0) if _r is None else (_r["op"], int.from_bytes(slot[2:4], "little"))
        if self._child_slot_runs and self._child_slot_runs[-1][0] == _key:
            self._child_slot_runs[-1][1] += 1
        else:
            self._child_slot_runs.append([_key, 1])

    def _count_child_op(self, slot):
        _rec = rfu.parse_slot(slot)
        if _rec is not None:
            self._child_op_counts[_rec["op"]] += 1
            if _rec["op"] not in self._child_ops:
                self._child_ops.add(_rec["op"])
                self.info("First console "
                          f"{rfu.RFUCMD_NAMES.get(_rec['op'], hex(_rec['op']))} "
                          f"while host is in {self.state}.")

    def _feed_idle_slot(self):
        if self.state == H_SAVE and self._save_final_standby_seen:
            self._idle_save_final_standby()
            return
        if self.state == H_ENTRY_SEAT and self._entry_final_standby_seen:
            self._idle_entry_final_standby()
            return
        if self.state == H_LINK_PLAYER and self._expected == "warp0":
            self._idle_link_player_wait()
            return
        if self.state == H_PARTY and self._link_waiting_idle:
            self._idle_party_link_settle()

    def _idle_save_final_standby(self):
        self._save_standby_quiet += 1
        if (self._save_standby_quiet
                >= self.timing.save_final_standby_quiet_frames):
            self.trace.append(("save_final_standby_complete",
                               self._save_last_count))
            if self.union_room:
                # CB2_SaveAndEndTrade case 8: the room's savedCallback is CB2_ReturnToField, so the
                # console calls SetCloseLinkCallback instead of another standby [trade_scene.c:2722].
                self.done = True
                self.info("Union Room trade: save barriers complete; the console closes the link "
                          "and returns to the room.")
                return
            self._begin_party_exchange()

    def _idle_entry_final_standby(self):
        self._entry_standby_quiet += 1
        if (self._entry_standby_quiet
                >= self.timing.entry_final_standby_quiet_frames):
            self.trace.append(("entry_final_standby_complete",
                               self._entry_standby_quiet))
            self._expected = None
            self._begin_party_exchange()

    def _idle_link_player_wait(self):
        # tick() drains _words before an in-flight BlockSender, so a BLOCK_REQ queued while our
        # block is still going out preempts it mid-transfer.
        if self._sender is not None or self._blocks:
            return
        self._link_player_idle += 1
        if self._link_player_idle >= self.timing.link_player_idle_frames:
            self.trace.append(("link_player_idle_complete", self._link_player_idle))
            self.info("Console is idle after the LinkPlayer exchange; "
                      "starting the trainer-card exchange.")
            self._begin_card_exchange()

    def _idle_party_link_settle(self):
        self._link_idle_frames += 1
        if self._link_idle_frames >= self.timing.party_link_settle_frames:
            completed = self._link_completed
            self._link_waiting_idle = False
            self._link_completed = None
            if completed and completed.startswith("party:"):
                i = int(completed.split(":", 1)[1])
            else:
                i = None
            if i is not None and i < 2:
                self._party_pair = i + 1
                self.trace.append(("party_link_finished", i))
                self._request_party_pair()
            elif i == 2:
                self.info("Party blocks 3/3 exchanged; exchanging mail and ribbon data.")
                self._request_and_send(
                    trade.BLOCK_REQ_SIZE_220, b"\x00" * 220, "mail")
            elif completed == "mail":
                self._request_and_send(
                    trade.BLOCK_REQ_SIZE_40, b"\x00" * 40, "ribbons")
            elif completed == "ribbons":
                self._finish_party_exchange()

    def _child_send_block_init(self, rec):
        self._rx.on_init(rec["count"], rec.get("owner_raw"))

    def _child_send_block(self, rec):
        was_done = self._rx.done
        self._rx.on_block(rec["index"], rec["frag"])
        if self._rx.done and not was_done:
            data, count = self._rx.data(), self._rx.count
            self._rx.consume()
            self._on_child_block(count, data)

    def _child_send_held_keys(self, rec):
        key = rec.get("keycode", 0) & 0xFF
        if self._child_key_runs and self._child_key_runs[-1][0] == key:
            self._child_key_runs[-1][1] += 1
        else:
            self._child_key_runs.append([key, 1])
        if key == LINK_KEY_READY and self.state == H_ENTRY_SEAT:
            self.trace.append(("child_key", "READY"))
            self._maybe_finish_entry()
        elif key == LINK_KEY_EXIT_ROOM and self.state == H_RETURN_FIELD:
            self.trace.append(("child_exit_first",))
            self._begin_room_exit(child_already_exited=True)
        elif key == LINK_KEY_EXIT_ROOM and self.state == H_EXIT:
            self._child_exit_seen = True
            self._complete_room_exit()

    def _child_ready_exit_standby(self, rec):
        self._on_child_standby(rec.get("count", 0))

    # Union Room activity words [include/constants/union_room.h]
    UR_IN_ROOM = 0x40
    UR_CARD = 0x48        # ACTIVITY_CARD, "Salut": show each other's trainer card
    UR_BATTLE = 0x41      # ACTIVITY_BATTLE_SINGLE | IN_UNION_ROOM
    UR_TRADE = 0x44       # ACTIVITY_TRADE | IN_UNION_ROOM, from the trading board
    UR_CHAT = 0x45        # ACTIVITY_CHAT | IN_UNION_ROOM
    UR_ACCEPT = 0x51      # ACTIVITY_ACCEPT | IN_UNION_ROOM
    UR_DECLINE = 0x52     # ACTIVITY_DECLINE | IN_UNION_ROOM
    UR_PACKET_REPEAT = 3  # PollPartnerYesNoResponse reads gRecvCmds every frame; a few repeats are safe

    def _child_send_packet(self, rec):
        """The parent's half of UR_STATE_HANDLE_ACTIVITY_REQUEST [union_room.c:3151]: answer the
        console's activity request with ACCEPT or DECLINE in a SEND_PACKET of our own."""
        packet = rec.get("packet") or [0] * 6
        request = packet[0]
        if not self.union_room or request == 0:
            return
        if self.state not in (H_ENTRY_CARD, H_UROOM_PROMPT):
            self.trace.append(("uroom_packet_ignored", self.state, request))
            return
        key = tuple(packet)
        # Reliable already drops retransmits; this only guards a packet echoed in consecutive frames.
        # The same choice made again later (a second Salut, u08) is a new request and must be answered.
        if key == self._last_uroom_packet and self._child_frames - self._last_uroom_frame <= 4:
            return
        self._last_uroom_packet = key
        self._last_uroom_frame = self._child_frames
        self.uroom_requests.append(key)
        self._set_state(H_UROOM_PROMPT)
        if request == self.UR_CARD:
            reply, what = self.UR_ACCEPT, "greetings (trainer cards); accepting, a standby barrier follows"
        elif request == self.UR_TRADE:
            reply = self.UR_ACCEPT
            what = (f"a trade from the trading board (it offers species {packet[1]} level "
                    f"{packet[2]}); accepting. It sends its Pokemon block after a standby barrier")
            self.uroom_trade_request = (packet[1], packet[2])
            self._set_state(H_UROOM_TRADE)
            self._expected = "uroom_mon"
        elif request == self.UR_CHAT and self.union_room_chat:
            reply = self.UR_ACCEPT
            what = ("a chat; accepting. A standby barrier follows, then both members SendBlock a "
                    "JOIN and the console opens its chat keyboard")
            self._set_state(H_UROOM_CHAT)
            self._expected = "uroom_chat"
        elif request == self.UR_BATTLE and self.union_room_battle:
            reply = self.UR_ACCEPT
            what = ("a battle; accepting. It picks two mons, then both sides send a 0x20 selection "
                    "block and the link battle starts")
            self._set_state(H_UROOM_BATTLE)
            self._expected = "battle_accept"
        elif request in (self.UR_BATTLE, self.UR_CHAT):
            reply, what = self.UR_DECLINE, "a battle or chat; declining, the console closes the link"
        elif request == self.UR_IN_ROOM:
            self.trace.append(("uroom_exit", key))
            self.info("Union Room: the console chose Exit; it closes the link now.")
            return
        else:
            reply, what = self.UR_DECLINE, f"an unknown activity 0x{request:02x}; declining"
        self.trace.append(("uroom_reply", request, reply))
        for _ in range(self.UR_PACKET_REPEAT):
            self._queue_words(rfu.send_packet_words([reply]), f"UROOM_PACKET:{reply:#04x}")
        self.info(f"Union Room: the console asked for {what}.")

    def _child_ready_close_link(self, rec):
        if self.union_room and self.state not in (H_CLOSE, H_DONE):
            # Exit at the prompt, or a declined request: the console runs SetCloseLinkCallback and
            # waits for every player's READY_CLOSE_LINK [WaitAllReadyToCloseLink, link_rfu_2.c:1471]
            # before it disconnects itself. u10: without our half it sat on the prompt text.
            self._set_state(H_CLOSE)
            self._close_confirmed = False
            self._close_grace_wait = None
            for _ in range(self.timing.startup_standby_echo_frames):
                self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
            self._close_retry_wait = self.timing.close_retry_frames
            self.info("Union Room: the console is closing the link; sending our READY_CLOSE_LINK.")
        if self.state != H_CLOSE:
            return
        self.trace.append(("child_close_ready", rec.get("count", 0)))
        if not self._close_confirmed:
            self._close_confirmed = True
            if not self._chat_exiting:
                # The chat exit runs its own short grace: the leaver is parked on
                # !gReceivedRemoteLinkPlayers and 15s of it is 15s of a frozen prompt (u13).
                self._close_grace_wait = self.timing.post_client_close_grace_frames
            self.trace.append(("child_close_confirmed",
                               rec.get("count", 0),
                               self.timing.post_client_close_grace_frames))
            self.info(
                "Switch confirmed it left the chat; closing now."
                if self._chat_exiting else
                "Switch confirmed it left the trade room; keeping peer traffic active "
                "for 15 seconds before disconnecting.")

    def _on_child_block(self, count, data):
        # u17: a battle link buffer record with a 4-byte payload is 16 bytes, which is exactly
        # COUNT_LINKCMD, so every ack and every short command was being read as a trade LINKCMD and
        # silently dropped. There are no trade LINKCMDs inside a battle: let the state decide, not
        # the size. It cost the first battle run at the very first GETMONDATA.
        if count == trade.COUNT_LINKCMD and self.state != H_UROOM_BATTLE_LINK:
            self._on_child_linkcmd(int.from_bytes(data[:2], "little"),
                                   int.from_bytes(data[2:4], "little"))
        else:
            self._after_child_block(count, data)

    def _on_child_standby(self, count):
        if self.state == H_PARTY:
            # Late room-entry standby traffic can overlap BufferTradeParties but is not its gate.
            self._link_idle_frames = 0
            return
        # A one-VBlank barrier echo can be missed, leaving the child repeating its count forever;
        # save/cancel barriers are already multi-round handshakes and keep a single echo.
        repeats = (self.timing.startup_standby_echo_frames
                   if self.state in (H_LINK_PLAYER, H_ENTRY_CARD, H_ENTRY_SEAT,
                                     H_UROOM_PROMPT, H_UROOM_TRADE, H_UROOM_CHAT,
                                     H_UROOM_BATTLE, H_UROOM_BATTLE_LINK,
                                     H_CANCEL, H_RETURN_FIELD)
                   else 1)
        for _ in range(repeats):
            self._queue_words(rfu.exit_standby_words(count), f"STANDBY:{count}")
        self._last_child_standby = count
        self._exit_count = max(self._exit_count, count + 1)
        if self.state == H_LINK_PLAYER and self._expected == "warp0":
            self._begin_card_exchange()
        elif self.state == H_ENTRY_CARD and self._expected == "warp1":
            self._set_state(H_ENTRY_SEAT)
            self._expected = "warp2"
            self._start_entry_route()
        elif self.state == H_ENTRY_SEAT:
            if count >= 3:
                self._entry_standby_quiet = 0
            self._maybe_finish_entry()
        elif self.state == H_SAVE:
            if self._save_last_count is None:
                self._save_last_count = count
                self._save_rounds = 1
            elif count == self._save_last_count:
                pass
            elif count == ((self._save_last_count + 1) & 0xFFFF):
                self._save_last_count = count
                self._save_rounds += 1
            else:
                self.trace.append(("save_standby_out_of_sequence",
                                   self._save_last_count, count))
            if self._save_rounds >= self.timing.save_barrier_rounds:
                self._save_standby_quiet = 0
                if not self._save_final_standby_seen:
                    self._save_final_standby_seen = True
                    self.trace.append(("save_final_standby_seen", count))
                    self.info(
                        "Save barriers complete; waiting for the Switch menu handoff to finish.")
        elif self.state == H_CANCEL:
            if self._cancel_standby_count is None:
                self._cancel_standby_count = count
            elif count == ((self._cancel_standby_count + 1) & 0xFFFF):
                # The next child-initiated count is wire proof that the cancel barrier passed.
                self._set_state(H_RETURN_FIELD)
                self._return_standby_count = count
                self._room_exit_wait = self.timing.post_cancel_exit_wait_frames
                self.trace.append(("cancel_standby_complete",
                                   self._cancel_standby_count, count))
                self.info("Trade menu closed; waiting 5 seconds before Linux exits the room.")
        elif self.state == H_RETURN_FIELD:
            self._return_standby_count = count

    def _maybe_finish_entry(self):
        if (self.state == H_ENTRY_SEAT and self._last_child_standby is not None
                and self._last_child_standby >= 3):
            self._release_key("ENTRY_LEFT_CHAIR")
            self._entry_final_standby_seen = True
            self._entry_standby_quiet = 0
            self.trace.append(("entry_final_standby_seen", self._last_child_standby))

    def _on_child_linkcmd(self, cmd, cursor):
        self.trace.append(("child_linkcmd", trade.LINKCMD_NAMES.get(cmd, hex(cmd)), cursor))
        if cmd == trade.READY_TO_TRADE and self.state == H_SELECT:
            self._select_cancels = 0
            self.child_cursor = cursor % 6
            self._set_state(H_CONFIRM)
            self._send_linkcmd(trade.SET_MONS_TO_TRADE, self.offered_slots[self.round])
        elif cmd == trade.INIT_BLOCK and self.state == H_CONFIRM:
            self._set_state(H_ANIM)
            self._anim_wait = self.anim_delay
            self._send_linkcmd(trade.START_TRADE)
        elif cmd == trade.READY_FINISH_TRADE and self.state == H_ANIM:
            self._child_finish = True
        elif cmd == trade.REQUEST_CANCEL and self.state == H_SELECT:
            # Leader_ReadLinkBuffer takes partner CANCEL with no state guard [decomp:src/trade.c:1622]. The
            # leader with a mon selected answers PARTNER_CANCEL_TRADE [trade.c:1694-1701]: the console shows
            # "your friend wants to trade" and both return to the menu. Answering that way every time loops
            # forever (h6: two cancels, two identical prompts), so a second consecutive CANCEL means the
            # console wants out and the leader cancels too: BOTH_CANCEL_TRADE [trade.c:1715-1722].
            self._select_cancels += 1
            if self._select_cancels >= 2:
                self._host_cancel_ready = True
                self._child_cancel_requested = True
                self.trace.append(("both_cancel_at_select",))
                self._enter_cancel_to_leave()
            else:
                self._send_linkcmd(trade.PARTNER_CANCEL_TRADE)
                self.trace.append(("partner_cancel_at_select",))
                self.info(
                    "Switch backed out of the trade menu; Linux acknowledged the cancel. "
                    "The menu is live again - select a Pokemon, or CANCEL again to leave.")
        elif cmd == trade.REQUEST_CANCEL and self.state == H_LEAVE_MENU:
            # BOTH_CANCEL requires both select statuses CANCEL; the follower's REQUEST_CANCEL is a prerequisite.
            self._child_cancel_requested = True
            self.trace.append(("child_cancel_requested",))
            if self._host_cancel_ready:
                self._enter_cancel_to_leave()
            else:
                self.info("Switch requested CANCEL; honoring it after the 5-second menu wait.")
        elif cmd in (trade.READY_TO_TRADE, trade.READY_CANCEL_TRADE) \
                and self.state == H_LEAVE_MENU:
            # Native sends PLAYER_CANCEL when the leader chose CANCEL but the follower picked a mon.
            self._send_linkcmd(trade.PLAYER_CANCEL_TRADE)
            self.trace.append(("reject_extra_trade", trade.LINKCMD_NAMES.get(cmd, hex(cmd))))
            self.info(
                "Switch selected another trade; Linux declined it. Dismiss the message, then "
                "select CANCEL and confirm YES to leave.")

    def _commit(self):
        host_slot = self.offered_slots[self.round]
        child_slot = self.child_cursor
        if child_slot is None:
            raise RuntimeError("cannot commit without child selection")
        off = child_slot * monmod.PARTY_MON_SIZE
        received = monmod.Mon(bytes(self.child_party[off:off + monmod.PARTY_MON_SIZE]))
        self.received_mons.append(received)
        self.party[host_slot] = received
        self.round += 1
        self.commits += 1
        self.trace.append(("commit", self.commits, host_slot, child_slot))
        self._send_linkcmd(trade.CONFIRM_FINISH_TRADE)
        self._set_state(H_SAVE)
        self._save_rounds = 0
        self._save_last_count = None
        self._save_final_standby_seen = False
        self._save_standby_quiet = 0
        self._child_finish = False
        self._anim_wait = None

    def tick(self):
        """One VBlank; returns the parent's seven-word gSendCmd row."""
        self._parent_polls += 1
        if self.state == H_LINK_PLAYER:
            self._tick_status_report()
        if self.state == H_LEAVE_MENU:
            self._tick_leave_menu()
        if self.state == H_RETURN_FIELD and self._room_exit_wait is not None:
            self._tick_room_exit_wait()
        if self.state == H_CLOSE and not self.disconnect_requested:
            self._tick_close_link()
        if self.state == H_ANIM and self._anim_wait is not None:
            self._tick_anim()
        if self.state == H_UROOM_CHAT:
            self._tick_chat_exit() if self._chat_exiting else self._tick_chat_outbox()
        return self._next_parent_words()

    # --- the Union Room battle ------------------------------------------------------------------

    def _on_battle_accept(self, data):
        """CB2_UnionRoomBattle case 3/4 [union_room_battle.c:139]: each side sends a 0x20 block
        whose first byte is 0x51, and the console closes the link unless BOTH read 0x51. It sends
        after its own party menu, so we answer rather than lead."""
        if not uroom_battle.read_accept_block(data):
            self.info("Union Room battle: the console backed out of its party selection; it closes "
                      "the link now.")
            self._expected = None
            self._set_state(H_UROOM_PROMPT)
            return
        self._queue_block(uroom_battle.accept_block(), "host:battle_accept")
        self._expected = "battle_header"
        self.info("Union Room battle: the console picked its two Pokemon; sending our accept. "
                  "Two link standbys, then the battler header.")

    def _on_battle_header(self, data):
        """CB2_HandleStartBattle state 1/2 [battle_main.c:962]. We answer with version signature
        0x200 on purpose: LinkBattleComputeBattleTypeFlags [:886] then makes the CONSOLE master, so
        it runs the whole battle engine and we only have to answer its controller commands."""
        version = data[0] | (data[1] << 8)
        self._queue_block(uroom_battle.battler_header(), "host:battle_header")
        self._battle_party_block = 0
        self._expected = "battle_party:0"
        self.info(f"Union Room battle: console version signature 0x{version:03x}; sending ours as "
                  f"0x{uroom_battle.VERSION_NON_MASTER:03x} so it takes the master role. "
                  "Three party blocks next.")

    def _on_battle_party(self, i, data):
        """States 3/7/11: the six party slots two at a time, the same 200-byte transfer the trade
        already does. Only the first block carries the two mons that fight; the console zeroed the
        rest in SetUpPartiesAndStartBattle [union_room_battle.c:51]."""
        self.child_party[i * 200:(i + 1) * 200] = data[:200]
        blocks = uroom_battle.party_blocks(self.party[:2])
        self._queue_block(blocks[i], f"host:battle_party:{i}")
        if i + 1 < uroom_battle.PARTY_BLOCK_COUNT:
            self._expected = f"battle_party:{i + 1}"
            self.info(f"Union Room battle: party block {i + 1}/3 exchanged.")
            return
        self._expected = "battle_link"
        self._set_state(H_UROOM_BATTLE_LINK)
        self.battle = uroom_battle.BattleController(
            self.party[:2], multiplayer_id=0, forfeit=self.battle_forfeit,
            move_slot=self.battle_move_slot, log=self.info)
        self.info("Union Room battle: parties exchanged; the console is master and drives the "
                  "battle from here. " + ("We forfeit at the first action prompt."
                                          if self.battle_forfeit else "We fight."))

    def _on_battle_block(self, data):
        """One link buffer record. Every BUFFER_A command must be acked, for BOTH battlers, or the
        master waits on gBattleControllerExecFlags forever [battle_util.c:185]."""
        rec = bl.parse(data)
        # The slot that completed this block is the one the console must see returned before it will
        # set the exec-flag bit our answer clears. Wait for that exact slot. See _echo_owed.
        self._echo_wait_slot = self._child_slot
        self._echo_wait_polls = 0
        self.trace.append(("battle_recv", rec["buffer_id"], rec["active_battler"], rec["cmd"]))
        self.info(f"Union Room battle: <- {bl.describe(rec)}")
        for out in self.battle.feed(data):
            self._queue_block(out, f"host:battle:{bl.describe(bl.parse(out))}")
        if self.battle.done:
            self._expected = None
            self.info("Union Room battle: over; waiting for the console to close the link.")

    def _on_chat_block(self, data):
        """One inbound 0x28 chat block. `_expected` stays "uroom_chat": members send blocks for as
        long as the chat lives, with no request from us [union_room_chat.c:1451]."""
        msg = uroom_chat.parse(data)
        self.chat_received.append(msg)
        self.trace.append(("uroom_chat_recv", msg["cmd"], msg["name"]))
        self.info(f"Union Room chat: {uroom_chat.describe(msg)}")
        if msg["cmd"] == uroom_chat.JOIN and not self._chat_joined:
            self._chat_joined = True
            self._queue_block(uroom_chat.build(uroom_chat.JOIN, self.lp.name, multiplayer_id=0),
                              "host:chat_join")
            self._chat_send_wait = self.timing.chat_message_gap_frames
            self.info("Union Room chat: sending our JOIN; the console lists us as a member.")
        elif msg["cmd"] in (uroom_chat.LEAVE, uroom_chat.DROP, uroom_chat.DISBAND):
            self._begin_chat_exit()

    def _begin_chat_exit(self):
        """Task_ReceiveChatMessage case 4 [union_room_chat.c:1524]: with only the two of us left,
        the leader stops its partner search, sends a DROP block of its own, then runs
        SetCloseLinkCallback and drops the link [ChatEntryRoutine_ExitChat, :665]. The leaver is
        parked on !gReceivedRemoteLinkPlayers and does nothing until we do (u13: without this the
        console sat on its yes/no prompt while we sat on `done`)."""
        if self._chat_exiting:
            return
        self._chat_exiting = True
        self._chat_send_wait = None
        self._chat_outbox.clear()
        self._queue_block(uroom_chat.build(uroom_chat.DROP, self.lp.name, multiplayer_id=0),
                          "host:chat_drop")
        self.info("Union Room chat: the console left the chat; sending our DROP, then closing "
                  "the link it is waiting on.")

    def queue_chat_message(self, text):
        """Add a line while the chat is live, so the operator can answer instead of queueing every
        line at launch. Returns False once the chat is over or has not opened."""
        if self.state != H_UROOM_CHAT or self._chat_exiting or not self._chat_joined:
            return False
        self._chat_outbox.append(uroom_chat.check_text(text))
        if self._chat_send_wait is None:
            self._chat_send_wait = 0          # the outbox had drained; send on the next tick
        return True

    def _tick_chat_exit(self):
        """Hold in the chat until our DROP has drained, then take the room's close-link path with
        a short grace of our own: the leaver is already parked waiting for the link to go, so the
        room's 15-second post-exit buffer must not apply here."""
        if self._sender is not None or self._blocks or self._words:
            return
        self._set_state(H_CLOSE)
        self._close_confirmed = False
        self._close_grace_wait = self.timing.chat_exit_close_frames
        for _ in range(self.timing.startup_standby_echo_frames):
            self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
        self._close_retry_wait = self.timing.close_retry_frames
        self.trace.append(("chat_exit_close", self._exit_count))
        self.info("Union Room chat: our DROP is out; closing the RFU link, which is what the "
                  "console is waiting for.")

    def _tick_chat_outbox(self):
        """One queued line at a time, spaced: the console latches a single block per player and
        scrolls it in before it reads the next. None means the outbox is drained or the chat has
        not opened yet."""
        if self._chat_send_wait is None or self._sender is not None or self._blocks:
            return
        if self._chat_send_wait > 0:
            self._chat_send_wait -= 1
            return
        if not self._chat_outbox:
            self._chat_send_wait = None
            self.info("Union Room chat: every queued line has been sent; the chat stays open "
                      "until the console leaves it.")
            return
        text = self._chat_outbox.popleft()
        self._queue_block(uroom_chat.build(uroom_chat.CHAT, self.lp.name, text=text),
                          "host:chat_msg")
        self._chat_send_wait = self.timing.chat_message_gap_frames
        self.trace.append(("uroom_chat_send", text))
        self.info(f"Union Room chat: sending {text!r}.")

    def _tick_status_report(self):
        self._status_countdown -= 1
        if self._status_countdown <= 0:
            self._status_countdown = STATUS_REPORT_FRAMES
            self._report_status()

    def _tick_leave_menu(self):
        if self._leave_menu_report is not None:
            self._leave_menu_report -= 1
            if self._leave_menu_report <= 0:
                self._leave_menu_report = LEAVE_MENU_REPORT_FRAMES
                self._report_leave_menu()
        if self.state == H_LEAVE_MENU and self._leave_menu_wait is not None:
            self._leave_menu_wait -= 1
            if self._leave_menu_wait <= 0:
                self._leave_menu_wait = None
                self._leader_cancel_is_ready()

    def _tick_room_exit_wait(self):
        self._room_exit_wait -= 1
        # Counted in child polls, not wall-clock: it stretches when the console's poll rate drops.
        if self._room_exit_wait % 60 == 0 and self._room_exit_wait > 0:
            done = self.timing.post_cancel_exit_wait_frames - self._room_exit_wait
            self.info(
                f"Room-exit buffer {done}/{self.timing.post_cancel_exit_wait_frames} frames; "
                f"still waiting before Linux walks out.")
        if self._room_exit_wait <= 0:
            self._begin_room_exit()

    def _tick_close_link(self):
        if self._close_grace_wait is not None:
            self._close_grace_wait -= 1
            if self._close_grace_wait <= 0:
                self._close_grace_wait = None
                self.disconnect_requested = True
                self.trace.append(("close_grace_complete",))
                self.info(
                    "Fifteen-second room-exit buffer complete; closing the RFU session.")
        self._close_retry_wait -= 1
        if self._close_retry_wait <= 0:
            for _ in range(self.timing.startup_standby_echo_frames):
                self._queue_words(rfu.close_link_words(self._exit_count), "READY_CLOSE_LINK")
            self._close_retry_wait = self.timing.close_retry_frames

    def _tick_anim(self):
        if self._anim_wait > 0:
            self._anim_wait -= 1
        elif self._child_finish:
            self._commit()

    def _echo_owed(self):
        """u18: never answer a command before we have echoed it back.

        Our echo of the console's own block is what makes MarkBattlerReceivedLinkData run over there
        [battle_util.c:193] and SET the exec-flag bit our ack then clears. Our parent command and the
        echo share a frame, one echo per poll, so a short ack can overtake the echo of a long block:
        the console clears a bit that is not set yet, then sets it, and waits forever for an ack that
        already came. That stalled u18.

        u20: waiting for the echo queue to be EMPTY was correct but cost 5-8 s per command, because
        the console sends one every poll and the queue almost never empties.

        u23: waiting for a COUNT of entries to leave the queue was fast but wrong again, and stalled
        the same way. ECHO_MAX drops fragments when the queue overflows and the console re-sends
        them, so a counter reports "echoed" for a fragment that has not gone out; the ack overtook
        the re-sent last fragment of a PLAYSE and the console stopped mid-animation. The user saw our
        attack freeze half-played with the music still going.

        So wait for the block's own last fragment to come back out of the echo, by content. The
        safety valve is not a tuned delay: it exists only so a fragment the console somehow never
        re-sends cannot deadlock us for ever, and it says so in the log when it fires.

        Scoped to the battle. The trade, Mystery Gift and chat paths are proven on hardware with the
        old timing and nothing in them acks a block the console has to see returned first."""
        if self.state != H_UROOM_BATTLE_LINK or self._echo_wait_slot is None:
            return False
        if self.last_echo_cmd == self._echo_wait_slot:
            self._echo_wait_slot = None
            return False
        self._echo_wait_polls += 1
        if self._echo_wait_polls > self.ECHO_WAIT_MAX_POLLS:
            self.info("Union Room battle: the console never took back its own last fragment after "
                      f"{self._echo_wait_polls} polls; answering anyway. If it stalls here, that "
                      "wait is the thing to look at.")
            self._echo_wait_slot = None
            return False
        return True

    def _next_parent_words(self):
        if self._words:
            return self._words.popleft()
        held_words = self._next_held_words()
        if held_words is not None:
            return held_words
        if self._sender is None and self._blocks and not self._echo_owed():
            data, label = self._blocks.popleft()
            self._sender = block.BlockSender(data, owner=0, trust_pia=self.trust_pia)
            self.trace.append(("send_block", label, len(data)))
        if self._sender is not None:
            words = self._sender.tick(None)
            if self._sender.done:
                self._sender = None
            return words
        return [0] * 7

    @property
    def established(self):
        return self.child_link_player is not None

    def mark_disconnect_sent(self):
        """Explicit acknowledgement so the engine cannot declare success before the close-link poll and 'D' enter Reliable's window."""
        if not self.disconnect_requested:
            raise RuntimeError("disconnect sent before close-link handshake")
        self.done = True
        self._set_state(H_DONE)


_CHILD_OP_HANDLERS = {
    rfu.SEND_BLOCK_INIT: HostTradeEngine._child_send_block_init,
    rfu.SEND_BLOCK: HostTradeEngine._child_send_block,
    rfu.SEND_HELD_KEYS: HostTradeEngine._child_send_held_keys,
    rfu.READY_EXIT_STANDBY: HostTradeEngine._child_ready_exit_standby,
    rfu.READY_CLOSE_LINK: HostTradeEngine._child_ready_close_link,
    rfu.SEND_PACKET: HostTradeEngine._child_send_packet,
}