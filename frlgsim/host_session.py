"""Composition of the FRLG leader Reliable, RFU, and trade layers."""

from dataclasses import replace

from . import reliable, rfu, trade
from .host_trade import DEFAULT_HOST_TRADE_TIMING, HostTradeEngine
from .rfu_leader import RFULeader, UNI


# After a ~250ms adapter TX hiccup every unacked frame comes due at once and the console never
# recovers from that flood, so retransmits per VBlank are capped.
HOST_RTX_LIMIT = 2

# The console releases in-order Reliable frames to the game in one burst when a hole closes, and its
# RFU receive queue is 8 deep (h5). If we keep emitting new frames while the console's cumulative ack
# is stuck behind a lost frame, the backlog grows without bound and the release burst overflows the
# queue, silently dropping block fragments (the ident-25 stall, lg150, session 16). Cap the frames the
# console has not yet cumulatively acked: below its queue depth, so any single release fits.
HOST_OUTSTANDING_MAX = 6

class HostSession:
    def __init__(self, party=None, *, engine=None, plan=None, profile=None, trade_slot=0,
                 offered_slots=None, trades=1, link_player=None,
                 anim_delay=None, trust_pia=True, log=lambda *a: None,
                 reliable_kwargs=None, rfu_kwargs=None,
                 player_ids_repeat_frames=None, link_player_idle_frames=None,
                 union_room=False, union_room_chat=False, chat_messages=None,
                 union_room_battle=False, battle_forfeit=True, battle_move_slot=0):
        if plan is not None:
            trade_slot = plan.trade_slot
            offered_slots = plan.offered_slots
            trades = plan.trades
            anim_delay = plan.anim_delay
            trust_pia = plan.trust_pia
            if player_ids_repeat_frames is None:
                player_ids_repeat_frames = plan.player_ids_repeat_frames
            if link_player_idle_frames is None:
                link_player_idle_frames = plan.link_player_idle_frames
        self.reliable = reliable.HostReliableSession(retransmit_limit=HOST_RTX_LIMIT, **(reliable_kwargs or {}))
        self.rfu = RFULeader(**(rfu_kwargs or {}))
        if engine is not None:
            if party is not None or plan is not None:
                raise ValueError("supply an activity engine or trade configuration, not both")
            self.activity = engine
        elif party is not None:
            overrides = {}
            if player_ids_repeat_frames is not None:
                overrides["player_ids_repeat_frames"] = player_ids_repeat_frames
            if link_player_idle_frames is not None:
                overrides["link_player_idle_frames"] = link_player_idle_frames
            timing = replace(DEFAULT_HOST_TRADE_TIMING, **overrides) if overrides else None
            self.activity = HostTradeEngine(
                party, trade_slot=trade_slot, offered_slots=offered_slots, trades=trades,
                link_player=link_player, profile=profile,
                anim_delay=(trade.DEFAULT_ANIM_FRAMES if anim_delay is None else anim_delay),
                trust_pia=trust_pia, timing=timing, union_room=union_room,
                union_room_chat=union_room_chat, chat_messages=chat_messages,
                union_room_battle=union_room_battle, battle_forfeit=battle_forfeit,
                battle_move_slot=battle_move_slot,
                log=log)
        else:
            raise ValueError("HostSession needs either a party or an activity engine")
        self.log = log
        self.peer_open_ack_sent = False
        self.connect_seq = None
        self.connect_ack_sent = False
        self.close_poll_sent = False
        self.disconnect_sent = False
        self.stopped = False
        self.send_window_full = False
        self.window_full_ticks = 0
        self.console_backlogged = False
        self.backlog_ticks = 0

    @property
    def trade(self):
        """Compatibility alias for trade-host callers; the activity may be a Mystery Gift engine."""
        return self.activity

    @property
    def inflight(self):
        return self.reliable.inflight

    def receive_reliable(self, payload, now_ms):
        if self.stopped:
            return []
        events = []
        for delivery in self.reliable.receive(payload, now_ms):
            event = self.rfu.receive(delivery.payload)
            if event is not None:
                events.append(event)
            if event == "connect" and self.connect_seq is None:
                self.connect_seq = delivery.seq
            if event == "uni":
                self.activity.echo_backlog = getattr(self.rfu, "echo_backlog", 0)
                self.activity.echo_progress = getattr(self.rfu, "echo_progress", 0)
                self.activity.feed_child_slot(self.rfu.child_cmd)
        return events

    def note_rtt(self, rtt_ms):
        self.reliable.note_rtt(rtt_ms)

    def tick(self, now_ms):
        """At most one RFU slot per call."""
        if self.stopped:
            return []
        self.activity.echo_backlog = getattr(self.rfu, "echo_backlog", 0)
        self.activity.echo_progress = getattr(self.rfu, "echo_progress", 0)
        out = list(self.reliable.poll(now_ms))
        for emission in out:
            if emission.flagsA != reliable.FLAGSA_CTRL:
                continue
            self.peer_open_ack_sent = True
            ack_id, _ = reliable.parse_bulk_ack(emission.payload)
            if self.connect_seq is not None and ack_id is not None:
                target = (self.connect_seq + 1) & 0xFFFF
                # Native opens A only after the cumulative ACK (wrapping 16-bit) covers C itself.
                if ((ack_id - target) & 0xFFFF) < 0x8000:
                    self.connect_ack_sent = True

        if self.reliable.inflight >= self.reliable.link.max_inflight:
            if not self.send_window_full:
                self.send_window_full = True
                getattr(self.log, "info", self.log)(
                    f"Reliable send window is full ({self.reliable.inflight} frames "
                    "unacknowledged); pausing the activity until it drains.")
            self.window_full_ticks += 1
            return out
        if self.send_window_full:
            self.send_window_full = False
            getattr(self.log, "info", self.log)(
                f"Reliable send window drained after {self.window_full_ticks} ticks; "
                "resuming the activity.")
            self.window_full_ticks = 0

        # Hole guard: while the console's cumulative ack lags our send by more than its RFU receive
        # queue can release at once, stop emitting NEW frames and let poll()'s retransmits refill the
        # hole. A closed hole then releases at most HOST_OUTSTANDING_MAX frames, which the 8-deep queue
        # accepts without dropping block fragments (lg150, session 16). Never gate the close/disconnect
        # path: those must still go out even if an ack is outstanding.
        if (not (self.close_poll_sent and self.activity.disconnect_requested)
                and self.reliable.link.outstanding() >= HOST_OUTSTANDING_MAX):
            if not self.console_backlogged:
                self.console_backlogged = True
                getattr(self.log, "info", self.log)(
                    f"Console ack is behind by {self.reliable.link.outstanding()} frames; holding "
                    "new frames and retransmitting the gap until it catches up.")
            self.backlog_ticks += 1
            return out
        if self.console_backlogged:
            self.console_backlogged = False
            getattr(self.log, "info", self.log)(
                f"Console ack caught up after {self.backlog_ticks} held ticks; resuming.")
            self.backlog_ticks = 0

        # Queue D one VBlank after the final parent close-link UNI poll.
        if (self.close_poll_sent and self.activity.disconnect_requested
                and not self.disconnect_sent):
            inner = self.rfu.disconnect_frame()
            if inner is not None:
                out.append(self.reliable.send(inner, now_ms))
            self.disconnect_sent = True
            self.activity.mark_disconnect_sent()
            return out

        parent_words = self.activity.tick() if self.rfu.state == UNI else None
        # Native leader ordering: cumulatively ACK C (not merely the preceding INIT) before opening A.
        if not self.reliable.local_opened and not self.connect_ack_sent:
            return out
        inner = self.rfu.tick(parent_words)
        if inner is None:
            return out
        if self.reliable.local_opened:
            out.append(self.reliable.send(inner, now_ms))
        else:
            out.append(self.reliable.open(inner, now_ms))

        if parent_words is not None and (parent_words[0] & rfu.RFUCMD_MASK) == rfu.READY_CLOSE_LINK:
            self.close_poll_sent = True
        return out

    def on_ldn_leave(self):
        self.stopped = True
        self.rfu.on_ldn_leave()
