"""Application runtime for hosting one complete FRLG trade session; owns OS resources and
scheduling only (protocol bytes live in host_pia, RFU/trade state in host_session)."""

import os
import time

from . import config as configmod, host_session, host_trade, ldntrace, trade_runtime, transport
from .linkplayer import HOST_NAME_PAD
from .host_beacon import (
    BeaconInjector, build_colosseum_app_data, build_trade_app_data, build_union_room_app_data,
)
from .host_pia import HostPeerProtocol
from .host_support import resolve_keys


HOST_CONTROL_POLL_SECONDS = 0.05
# Settle time after the console has left LDN following a confirmed room exit. It is not the
# 15-second post-exit grace: that grace keeps Pia traffic alive while the Switch fades and
# warps, and the console leaving LDN is that finishing.
HOST_CLOSE_SETTLE_SECONDS = 2.0
CHAT_FILE_POLL_SECONDS = 0.25


class ChatFileWatcher:
    """Tails a file so lines appended to it while the host runs are sent into a live Union Room
    chat. Only whole lines are taken, so a half-written line is never sent."""

    def __init__(self, path, log=print):
        self.path = path
        self.log = log
        self.info = getattr(log, "info", log)
        self.offset = 0
        self._partial = ""
        self._next_poll = 0.0

    def due(self, now):
        return now >= self._next_poll

    def lines(self, now):
        self._next_poll = now + CHAT_FILE_POLL_SECONDS
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return []
        if size < self.offset:            # truncated or replaced: start over
            self.offset, self._partial = 0, ""
        if size == self.offset:
            return []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
                self.offset = fh.tell()
        except OSError as exc:
            self.info(f"Union Room chat: cannot read {self.path}: {exc}")
            return []
        text = self._partial + chunk
        parts = text.split("\n")
        self._partial = parts.pop()
        return [line.strip() for line in parts if line.strip()]


class HostApplication:
    def __init__(self, config, *, log=print,
                 transport_factory=transport.HostTransport,
                 injector_factory=BeaconInjector):
        if not isinstance(config.role, configmod.HostOptions):
            raise ValueError("HostApplication requires HostOptions")
        self.config = config
        self.profile = config.profile
        self.plan = getattr(config, "plan", None)
        self.ldn = config.ldn
        self.options = config.role
        self.log = log
        self.info = getattr(log, "info", log)
        self.transport_factory = transport_factory
        self.injector_factory = injector_factory
        self.network = None
        self.injector = None
        self.tracer = None
        self.session = None
        self.peer = None
        chat_file = getattr(self.options, "chat_file", None)
        self.chat_watcher = ChatFileWatcher(chat_file, log=log) if chat_file else None
        self._saved_commits = 0
        self._last_trade_state = None
        self._absence_logged = False
        self._absence_since = None
        self.interrupted = False
        self.idle_timed_out = False

    def _load_party(self):
        party = trade_runtime.load_party(self.plan.party_paths, self.log)
        self.info(f"Loaded {len(party)} party Pokémon "
                  f"(planned offered slots: {self.plan.offered_slots}).")
        return party

    def _resolve_phy_and_keys(self):
        phy = self.ldn.phy
        if phy == "auto":
            if self.ldn.adapter:
                try:
                    phy = transport.find_adapter_phy(self.ldn.adapter, log=self.log)
                except RuntimeError as exc:
                    raise SystemExit(str(exc)) from exc
            else:
                phy = transport.find_ap_phy(log=self.log)
                if phy is None:
                    raise SystemExit("no AP-capable phy found; present phys: "
                                     f"{', '.join(transport.list_phys()) or 'none'}")
        keys = resolve_keys(self.ldn.keys_path)
        if not os.path.exists(keys):
            raise SystemExit(f"prod.keys not found at {keys!r}; pass --keys with an absolute path")
        return phy, keys

    def _build_components(self):
        party = self._load_party()
        phy, keys = self._resolve_phy_and_keys()
        link_player = self.profile.to_link_player()
        union_room = bool(getattr(self.options, "union_room", False))
        rfu_kwargs = None
        if union_room:
            rfu_kwargs = {"skip_parent_ni": True,
                          "keepalive_frames": int(getattr(self.options, "union_room_keepalive", 0))}
        self.session = host_session.HostSession(
            party, plan=self.plan, profile=self.profile, log=self.log,
            rfu_kwargs=rfu_kwargs, union_room=union_room,
            union_room_chat=bool(getattr(self.options, "union_room_chat", False)),
            chat_messages=tuple(getattr(self.options, "chat_messages", ()) or ()),
            union_room_battle=bool(getattr(self.options, "union_room_battle", False)),
            battle_forfeit=bool(getattr(self.options, "battle_forfeit", True)),
            battle_move_slot=int(getattr(self.options, "battle_move_slot", 0) or 0),
            colosseum=bool(getattr(self.options, "colosseum", False)))
        if union_room:
            trade_board = None
            board_type = getattr(self.options, "union_room_board_type", None)
            if board_type is not None:
                offered = party[self.plan.offered_slots[0]]
                level = getattr(self.options, "union_room_board_level", None)
                if level is None:
                    level = offered.decode()["level"]
                trade_board = (offered.species, int(level), int(board_type))
                self.info(f"Union Room trading board: offering {offered.species_name} lv{level}, "
                          f"asking for type {board_type}.")
            inactive, active = build_union_room_app_data(
                self.profile, self.session.rfu.host_session_id,
                activity=getattr(self.options, "union_room_activity", None),
                trade_board=trade_board)
        elif getattr(self.options, "colosseum", False):
            # Direct Corner -> Colosseum -> Single Battle. Only the advertised activity differs from
            # the trade beacon [sAcceptedActivityIds_SingleBattle, src/data/union_room.h:398].
            inactive, active = build_colosseum_app_data(
                self.profile, self.session.rfu.host_session_id)
        else:
            inactive, active = build_trade_app_data(
                self.profile, self.session.rfu.host_session_id)
        self.tracer = (ldntrace.Tracer(self.ldn.capture_path, log=self.log)
                       if self.ldn.capture_path else None)
        self.network = self.transport_factory(
            app_data=inactive, password=self.ldn.password,
            nickname=self.profile.discovery_name, keys_path=keys,
            local_comm_id=self.ldn.local_comm_id,
            scene_id=self.options.scene_id,
            max_participants=self.options.max_participants,
            phyname=phy, channel=self.options.channel,
            skip_encryption=self.options.skip_encryption,
            accept_decrypted_ccmp=self.options.accept_decrypted_ccmp,
            tracer=self.tracer, log=self.log)
        self.peer = HostPeerProtocol(
            self.network, self.profile, self.session, active,
            native_nonce_sequence=self.options.native_nonce_sequence,
            session_response_first=self.options.session_response_first,
            tracer=self.tracer, log=self.log)
        self._last_trade_state = self.session.trade.state
        return link_player

    def _log_identity(self, link_player):
        wire = link_player.pack(name_pad=HOST_NAME_PAD)
        self.info(f"Host identity: OT={self.profile.name!r}, "
                  f"TID=0x{self.profile.tid:04x}, SID=0x{self.profile.sid:04x}")
        self.info("Host LinkPlayer display identity: "
                  f"name_bytes={wire[8:16].hex()} "
                  f"language={int.from_bytes(wire[26:28], 'little')}")
        self.info(f"RFU parent identity: raw={self.session.rfu.host_session_id.hex()} "
                  f"u16=0x{int.from_bytes(self.session.rfu.host_session_id, 'little'):04x} "
                  "(shared by discovery beacon and A response)")
        self.info("RFU block delivery: " + (
            "Pia-backed send-once mode (recommended for this LDN bridge)."
            if self.plan.trust_pia else
            "raw-RFU retransmit mode (diagnostic; may flood the Pia bridge)."))
        self.info("Pia nonce mode: " + (
            "native session-wide counter" if self.options.native_nonce_sequence
            else "independent random values"))

    def _send_pending(self, datagrams):
        for outbound in datagrams:
            self.network.send(outbound.data, outbound.destination)

    def _log_protocol_events(self, events):
        if "connect" in events:
            self.info("Switch requested the RFU link; preparing the leader A response.")
        if "child_ni_complete" in events:
            self.info("Received the Switch RFU identity; sending join-status NI.")
        if "disconnect" in events:
            activity = self._activity()
            state = getattr(activity, "state", None)
            battle = getattr(activity, "battle", None)
            if getattr(activity, "close_confirmed", False):
                self.info(f"Switch sent the RFU disconnect frame (D) in {state}: the normal close.")
            elif battle is not None and battle.done:
                # u19: a finished link battle ends this way. CB2_ReturnFromCableClubBattle takes the
                # console back to the room through its score screen and save, and it drops LDN on
                # the way; nothing the host sent caused it.
                self.info("Switch sent the RFU disconnect frame (D) after the battle ended "
                          f"(outcome {battle.outcome}): the normal close for a link battle. It "
                          "returns to the room on its own; relaunch the host to appear there again.")
            else:
                recent = getattr(activity, "recent_sends", lambda: [])()
                self.info(f"Switch sent the RFU disconnect frame (D) while the host is in {state}; "
                          "it leaves LDN next. What the host sent just before this is the cause.")
                if recent:
                    self.info("  our last blocks, oldest first: " + " | ".join(recent))
                sender = getattr(activity, "_sender", None)
                if sender is not None:
                    self.info(f"  a block send was IN FLIGHT when it left: {sender.state} "
                              f"frag {getattr(sender, 'index', '?')}")

    def _activity(self):
        activity = getattr(self.session, "activity", None)
        return activity if activity is not None else self.session.trade

    def _hosting_instructions(self):
        return "Hosting Direct Corner. On the Switch choose Join Group."

    def _rfu_ready_message(self):
        return "RFU NI handshake complete; parent UNI and trade-room startup are active."

    def _close_grace_message(self):
        return ("The console left LDN after confirming room exit; "
                "settling for a moment before the host stops.")

    def _absence_stop_reason(self, now):
        """The console is gone from LDN. Returns the message to stop on, or None to keep going.

        Waiting here for the activity's own `done` deadlocks. `done` is set from the session's
        disconnect path, whose timer only advances inside `activity.tick()`, and the hole guard
        stops calling that as soon as the departed console's acks stop arriving -- so the clock
        that would release the guard is itself behind the guard. Zero of 356 host logs ever
        reached this completion; every clean close so far ended in a SIGTERM.
        """
        activity = self._activity()
        if not activity.close_confirmed or activity.done:
            return "The console left the LDN network; stopping host peer traffic."
        if not self._absence_logged:
            self._absence_logged = True
            self._absence_since = now
            self.info(self._close_grace_message())
            return None
        if now - self._absence_since >= HOST_CLOSE_SETTLE_SECONDS:
            return self._completion_message()
        return None

    def _completion_message(self):
        return "Room-exit grace period complete; host peer traffic stopped cleanly."

    def _idle_timeout_seconds(self):
        return getattr(self.config, "idle_timeout_seconds", None)

    def _end_on_success(self):
        return bool(getattr(self.config, "end_on_success", False))

    def _activity_succeeded(self):
        return bool(getattr(self._activity(), "gift_sent", False))

    def _poll_chat_file(self, now):
        """Send whatever has been appended to --chat-file into a live chat."""
        if self.chat_watcher is None or not self.chat_watcher.due(now):
            return
        activity = self._activity()
        if not hasattr(activity, "queue_chat_message"):
            return
        for line in self.chat_watcher.lines(now):
            try:
                sent = activity.queue_chat_message(line)
            except ValueError as exc:
                self.info(f"Union Room chat: skipping {line!r}: {exc}")
                continue
            if sent:
                self.info(f"Union Room chat: queued {line!r} from {self.chat_watcher.path}.")
            else:
                self.info(f"Union Room chat: dropped {line!r}; the chat is not open.")

    def _log_activity_progress(self):
        activity = self._activity()
        state = activity.state
        if state != self._last_trade_state:
            self._last_trade_state = state
            message = {
                host_trade.H_ENTRY_CARD: "LinkPlayer exchange complete; exchanging trainer cards.",
                host_trade.H_ENTRY_SEAT: "Trainer cards exchanged; walking the Linux leader into the left chair.",
                host_trade.H_PARTY: "Trade-room entry complete; exchanging party data.",
                host_trade.H_SELECT: "Party exchange complete; trade selection is active.",
            }.get(state)
            if message:
                self.info(message)
            if state == host_trade.H_PARTY:
                runs = activity.child_route_runs()
                if runs:
                    names = {0x11: "EMPTY", 0x12: "DOWN", 0x13: "UP", 0x14: "LEFT", 0x15: "RIGHT",
                             0x16: "READY", 0x17: "EXIT_ROOM", 0x19: "A", 0x1D: "EXIT_SEAT"}
                    self.info("child seat route: " + ", ".join(
                        f"({names.get(k, hex(k))}, {n})" for k, n in runs))
                slots = activity.format_child_slots()
                if slots:
                    self.info("child slot stream (op x run-length):\n" + slots)
        if activity.commits > self._saved_commits:
            self._saved_commits = activity.commits
            self._save_received()

    def _save_received(self):
        mons = self.session.trade.received_mons
        trade_runtime.save_received_mons(
            mons, output_path=self.plan.output_path,
            output_size=self.plan.output_size,
            output_format=self.plan.output_format,
            trades=self.plan.trades, log=self.log)

    def run(self):
        joined_once = False
        rfu_ni_logged = False
        last_peer_activity = time.monotonic()
        try:
            link_player = self._build_components()
            self._log_identity(link_player)
            self.network.start(preflight=not self.options.skip_preflight)
            self.injector = self.injector_factory(
                channel=self.options.channel, log=self.log)
            self.injector.start()
            self.info(self._hosting_instructions())
            while True:
                if self.injector.error is not None:
                    raise RuntimeError(f"802.11 beacon injector stopped: {self.injector.error}")
                if self.network.participants and not joined_once:
                    joined_once = True
                    last_peer_activity = time.monotonic()
                    self.peer.on_participant_joined()
                    self.info("Switch joined the Linux LDN host successfully.")
                if joined_once and not self.network.participants:
                    reason = self._absence_stop_reason(time.monotonic())
                    if reason is not None:
                        self.session.on_ldn_leave()
                        self.info(reason)
                        break

                received = self.network.recv()
                if received:
                    last_peer_activity = time.monotonic()
                for datagram, src_ip in received:
                    events = self.peer.receive(datagram, src_ip)
                    self._log_protocol_events(events)
                    self._send_pending(self.peer.drain())

                now = time.monotonic()
                idle_timeout = self._idle_timeout_seconds()
                if idle_timeout is not None and now - last_peer_activity >= idle_timeout:
                    self.idle_timed_out = True
                    self.info(f"No meaningful Switch traffic for {idle_timeout}s; stopping host.")
                    break
                self._send_pending(self.peer.tick(now))
                self._log_activity_progress()
                self._poll_chat_file(now)
                if self.session.rfu.ni_complete and not rfu_ni_logged:
                    rfu_ni_logged = True
                    self.info(self._rfu_ready_message())
                if (self._activity().done and (
                        not self.network.participants
                        or (self._end_on_success() and self._activity_succeeded()))):
                    self.info(self._completion_message())
                    break
                timeout = self.peer.next_deadline(now, HOST_CONTROL_POLL_SECONDS)
                self.network.wait_readable(timeout)
        except KeyboardInterrupt:
            self.interrupted = True
            self.log("[host] interrupted; shutting down")
        finally:
            if self.injector is not None:
                self.injector.stop()
            if self.network is not None:
                self.network.stop()
            if self.tracer is not None:
                self.tracer.close()
                self.log(f"[host] trace written: {self.ldn.capture_path} "
                         f"(counts: {self.tracer.counts})")
        return joined_once
