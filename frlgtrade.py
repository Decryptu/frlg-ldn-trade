#!/usr/bin/env python3
"""frlgtrade - FireRed/LeafGreen trade simulator (JOINER) over the LDN bridge.

Joins a real FRLG console's link session as the wireless CHILD and performs 1..6 sequential trades,
injecting chosen .pk3 mons and saving each received mon as a .pk3.

Supply 1..6 party .pk3/.ek3 files (gPlayerParty slots 0..5). --trades N (1..6, default 1) sets how
many sequential trades to perform; --slots picks which OUR slot is offered each round (default:
ascending distinct slots from --slot, or [0..N-1] for the full-party swap). After the Nth trade the
sim leaves by selecting the trade-menu CANCEL option (REQUEST_CANCEL 0xEEAA), a graceful
cancel-to-leave [trade.c:2049].

LIVE (needs the Switch, root, and the ldn/trio/netlink deps):
    sudo -E python3 frlgtrade.py --live --password PASS dummy.pk3 trademon.pk3 -o received.pk3
    sudo -E python3 frlgtrade.py --live --trades 6 a.pk3 b.pk3 c.pk3 d.pk3 e.pk3 f.pk3

OFFLINE self-check (replays a captured host stream through the full RX stack - no Switch):
    python3 frlgtrade.py --replay capture.jsonl dummy.pk3 trademon.pk3
"""

import argparse
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frlgsim import config as configmod, crypto as cryptomod, trade, sim as simmod  # noqa
from frlgsim import transport as tmod, linkstate as lsmod  # noqa: E402
from frlgsim import barrier as lsmod_barrier, pia_connect  # noqa: E402
from frlgsim import trade_runtime as runtime  # noqa: E402


def make_engine(run_config, lg, *, default_anim_delay=None):
    plan = run_config.plan
    options = run_config.role
    party = runtime.load_party(plan.party_paths, lg)
    lg.info(f"Loaded {len(party)} party Pokémon (offering slot {plan.trade_slot + 1}).")
    lp = run_config.profile.to_link_player()
    elog = runtime.ConsoleLog(lg.verbose, "  [trade]", start=lg.start)
    anim_delay = plan.anim_delay if plan.anim_delay is not None else default_anim_delay
    eng = trade.TradeEngine(
        party, trade_slot=plan.trade_slot, link_player=lp, mpid=options.self_id,
        anim_delay=anim_delay, decline=options.decline, trades=plan.trades,
        offered_slots=plan.offered_slots,
        refuse_partner_deoxys_mew=options.refuse_illegit,
        trust_pia=plan.trust_pia, log=elog)
    lg(f"  seat=RIGHT (Follower / mpId={eng.mpid}); trades={eng.trades}, "
       f"offered_slots={eng.offered_slots}")
    return eng


def _paced_sleep(s, period, slice_s=0.002):
    """Flushes the TX pacer and polls RX every 2ms so PACE_MIN_GAP_MS / REPLY_HOLDOFF_MS hold at that
    resolution rather than once per tick."""
    end = time.monotonic() + period
    while True:
        now = time.monotonic()
        if now >= end:
            return
        time.sleep(min(slice_s, end - now))
        if s.pace_ms:
            s.poll_rx()
            s.flush_paced()


# Going silent before the host leads the walk-out trips its keepalive watchdog (LinkRfu_FatalError); err long.
LEAVE_TAIL_S = 120.0


def _live_connect(run_config, lg):
    """Brings up the LDN transport, the Pia connection manager, the engine and the Sim."""
    plan, ldn, options = run_config.plan, run_config.ldn, run_config.role
    profile = run_config.profile
    lg(f"[live] scanning for FRLG LDN network (nickname={profile.name})...")
    t = tmod.LiveTransport(
        password=ldn.password, nickname=profile.name, keys_path=ldn.keys_path,
        local_comm_id=ldn.local_comm_id, phyname=ldn.phy, log=lg).start()
    pc = cryptomod.PiaCrypto(t.ssid)
    engine = make_engine(run_config, lg)
    # The sim must not emit trade traffic or sit until the host confirms the Pia connection
    # (Net 0x11->0x12, Session join) [frlgsim/pia_connect.py].
    if not t.our_mac or not t.host_mac:
        lg(f"[live] WARNING: MAC(s) not resolved from the participant list "
              f"(us={t.our_mac and t.our_mac.hex()} host={t.host_mac and t.host_mac.hex()}); "
              f"the Session join may be rejected.")
    conn = pia_connect.ConnectionManager(
        our_mac=t.our_mac or b"\x00" * 6, host_mac=t.host_mac or b"\x00" * 6,
        our_ip=t.our_ip, host_ip=t.host_ip, player_name=profile.name,
        random4=os.urandom(4), log=lg)
    lstate = lsmod.LinkState(self_id=options.self_id, log=lg)
    # Any nonzero connect id works; a FRESH id per run avoids the host's ~40s lost-id re-join lockout.
    if options.connect_id:
        connect_id = options.connect_id
    else:
        connect_id = (int.from_bytes(os.urandom(2), "big") or 1).to_bytes(2, "big")
    lg.info(f"emulator connect id {connect_id.hex()} "
            f"({'override' if options.connect_id else 'random nonzero'})")
    lg(f"[live] emulator connect: will send 'C' with connect id {connect_id.hex()} "
          f"({'override' if options.connect_id else 'random nonzero'}); the host's 'A' (0x41) accept "
          f"seats our slot - the value need not match anything on the host.")
    s = simmod.Sim(t, pc, engine, t.our_ip, t.host_ip, conn=conn, compress=options.compress,
                   linkstate=lstate, connect_id=connect_id, capture_path=ldn.capture_path, log=lg,
                   pace_ms=options.pace_ms)
    lg.info(f"TX pacing: one datagram per {options.pace_ms}ms" if options.pace_ms else "TX pacing: off")
    if ldn.capture_path:
        lg(f"[live] capturing every Pia datagram (both dirs) -> {ldn.capture_path} "
              f"(decrypt/analyse offline afterward)")
    lg(f"[live] joined LDN; awaiting the host's Pia connection handshake "
          f"(Net 0x11 -> Session join -> confirm). NOT trading until the host confirms us.")
    lg(f"[live] configured trades={plan.trades} (cancel-to-leave after the final trade)")
    return t, engine, s, conn, lstate


class _LiveJoiner:
    """The live joiner loop's shared state: the wired-up objects plus the once-only announce flags."""

    def __init__(self, run_config, lg, t, engine, s, conn, lstate):
        self.run_config, self.lg = run_config, lg
        self.t, self.engine, self.s, self.conn, self.lstate = t, engine, s, conn, lstate
        # sit() is gated on engine.established: SendKeysToRfu only emits once gReceivedRemoteLinkPlayers is set
        # [link_rfu_2.c:1069], and a READY before that faults the host's childSendCmdId check.
        self.sat = self.walking = self.exited = False
        self.connect_announced = self.responded_exit = False
        self.announced_cancel = self.announced_close = False
        self.announced_entry = self.announced_menu = False
        self.announced_established = False
        self.saved_commits = 0  # received mons already written to disk (save AT COMMIT, not just run-end)
        self.connect_ticks = 0
        self.ni_wait_ticks = 0
        self.entry_ticks = 0
        self.leave_ticks = 0
        self.leave_until = None
        self.close_until = None
        self.graceful_interrupt = False
        self.interrupt_count = 0
        self.last_rates = [0.0, 0, 0, 0]      # [t_at_sample, host_t_in, t_out, k_out]

    def rates(self):
        s = self.s
        now = time.monotonic()
        dt = max(1e-3, now - self.last_rates[0])
        r = (f"host_t={(s.host_t_in - self.last_rates[1]) / dt:.0f}/s "
             f"our_t={(s.t_out - self.last_rates[2]) / dt:.0f}/s "
             f"k={(s.k_out - self.last_rates[3]) / dt:.0f}/s "
             f"out={s.rel.outstanding()}/{s.rel.max_inflight} "
             f"rto={s.rel.rto() and round(s.rel.rto())}ms "
             f"max_quiet={s.max_silence}f forced={s.silence_forced}")
        self.last_rates[:] = [now, s.host_t_in, s.t_out, s.k_out]
        return r

    def on_interrupt(self, _signum, _frame):
        self.interrupt_count += 1
        if self.interrupt_count == 1:
            self.graceful_interrupt = True
        else:
            raise KeyboardInterrupt

    def handle_interrupt(self):
        engine, lg = self.engine, self.lg
        if self.graceful_interrupt:
            self.graceful_interrupt = False
            if engine.host_in_seat and engine.in_seat_phase and self.lstate is not None:
                self.lstate.exit()
                lg("[live] Ctrl+C: sent EXIT_ROOM; waiting for the host to terminate the link. "
                   "Press Ctrl+C again to stop immediately.")
            else:
                raise KeyboardInterrupt

    def save_at_commit(self):
        # Save at commit: the post-trade tail can stall or be interrupted and the mon is already valid.
        engine, lg = self.engine, self.lg
        if engine.commits > self.saved_commits:
            self.saved_commits = engine.commits
            try:
                n = save_received(engine, self.run_config, lg)
                lg(f"[live] trade committed -> saved {n} received mon(s) to disk now "
                      f"(robust to an abrupt exit)")
            except Exception as e:                       # never let a save error kill the link tail
                lg(f"[live] WARNING: could not save received mon at commit: {e}")

    def check_abort(self):
        """True when the host refused or dropped us and the loop must stop."""
        s, lg = self.s, self.lg
        if getattr(s, "ni_rejected", False):
            lg("[live] ABORT: host rejected our join (NI status != JOIN_GROUP_OK) - leaving.")
            lg.info("Host rejected our join; leaving.")
            return True
        if getattr(s, "host_disconnected", False):
            lg("[live] host closed the RFU link ('D' 0x44) - disconnecting.")
            return True
        return False

    def connect_gate(self):
        """True while the Pia connection is not up yet (the caller must idle a tick and retry)."""
        s, lg = self.s, self.lg
        if not s.connected:
            self.connect_ticks += 1
            if self.connect_ticks % 120 == 0:
                # No proto 13 means the console never sent its Session join (a wedged host session: close
                # and reopen the game); proto 13 with conn not OK is a handshake we mishandle.
                lg.info(f"awaiting host connection: {self.connect_ticks}f, conn={self.conn.state}, "
                        f"host_var={'learned' if s._learned else 'unseen'}, "
                        f"rx_ok={s.rx_count} rx_decryptfail={s.rx_fail} "
                        f"protos={dict(sorted(s.rx_protos.items()))} tx={s.tx_count}")
            return True
        if not self.connect_announced:
            lg(f"[live] Pia connection ESTABLISHED - host confirmed us "
                  f"(conn={self.conn.state} after {self.connect_ticks}f). Awaiting the emulator RFU "
                  f"connect/'A' + NI handshake + LinkPlayer exchange before sitting.")
            self.connect_announced = True
        return False

    def log_ni_progress(self):
        s, lg = self.s, self.lg
        if not s._ni_done:
            self.ni_wait_ticks += 1
            if self.ni_wait_ticks % 120 == 0:
                ni = getattr(s, "_ni", None)
                lg.info(f"awaiting RFU handshake: {self.ni_wait_ticks}f, "
                   f"gba_accepted={s._gba_accepted}, "
                   f"send_ni={'done' if (ni is not None and ni.done) else 'in progress' if ni else 'not built'}, "
                   f"host_ni_ack={'pending' if s._cur_ni_ack else 'none'}, "
                   f"host_ni_null={s._host_ni_null_seen}, host_uni={s._host_uni_seen}, "
                   f"rx_ok={s.rx_count} protos={dict(sorted(s.rx_protos.items()))} tx={s.tx_count} "
                   f"{self.rates()}")

    def log_entry_progress(self):
        s, engine, lg = self.s, self.engine, self.lg
        if s._ni_done and not engine.commits:
            self.entry_ticks += 1
            if self.entry_ticks % 120 == 0:
                ent = getattr(engine, "entry", None)
                lg.info(f"entry state: {self.entry_ticks}f, "
                        f"established={engine.established}, "
                        f"host_in_seat={getattr(engine, 'host_in_seat', None)}, "
                        f"host_ready={getattr(engine, 'host_ready', None)}, "
                        f"we_sat={self.sat}, in_seat_phase={getattr(engine, 'in_seat_phase', None)}, "
                        f"card_pulled={getattr(ent, 'card_pulled', None)}, "
                        f"rx_ok={s.rx_count} tx={s.tx_count} {self.rates()}")

    def log_leave_progress(self):
        s, engine, lg = self.s, self.engine, self.lg
        if engine.commits and getattr(engine, "leaving", False) and not engine.cancelled:
            self.leave_ticks += 1
            if self.leave_ticks % 120 == 0:
                lg.info(f"leave state: {self.leave_ticks}f since the trade committed, "
                        f"menu_live={engine._trade_menu_live()}, "
                        f"state={engine.state}, selected={engine._selected}, "
                        f"host_party_blocks={engine._host_party_blocks}/3, "
                        f"party_sent={engine._party_sent}, "
                        f"requested_cancel={engine.requested_cancel}, "
                        f"rx_ok={s.rx_count} tx={s.tx_count} {self.rates()}")

    def handle_seating(self):
        """Announcements plus the walk/seat gating, in the order the entry sequence reaches them."""
        engine, lg = self.engine, self.lg
        if not self.announced_established and engine.established:
            self.announced_established = True
            lg("[live] RFU link ESTABLISHED (gReceivedRemoteLinkPlayers: both LinkPlayer "
                  "blocks exchanged) - held keys + sit are now armed.")
        # Walk as soon as the host is in the room: the console leader sends only EMPTY held keys in the
        # trade room and waits for the CHILD's READY, so waiting for host_ready deadlocks. READY fires
        # only at the chair; from the doorway it faults the host's cable-seat FSM.
        if not self.walking and engine.host_in_seat:
            lg("[live] host is in the trade room - walking to the RIGHT seat.")
            self.lstate.walk_to_seat()
            self.walking = True
        if not self.sat and self.lstate.seated:
            lg("[live] our READY (0x16) went out at the RIGHT seat.")
            engine.note_self_seated()
            self.sat = True
        if not self.announced_entry and engine.entry.card_pulled:
            lg("[live] entry: host pulled our 100B trainer card (BLOCK_REQ_SIZE_100) - "
                  "supplied; this is the pre-trade card exchange (Task_ExchangeCards).")
            self.announced_entry = True
        if not self.announced_menu and engine.entry.complete:
            lg("[live] entry: complete (P0..P5) - trade menu is live; entering the trade FSM.")
            lg.info("Trade menu open; received the host's party.")
            self.announced_menu = True

    def handle_barrier(self):
        """True when the host's CLOSE has been answered long enough to disconnect."""
        engine, lg = self.engine, self.lg
        # READY_CLOSE_LINK (0x5F00): answer briefly, then disconnect [link_rfu_2.c:1460-1520].
        if engine.barrier.mode == lsmod_barrier.CLOSE:
            if not self.announced_close:
                self.announced_close = True
                self.close_until = time.monotonic() + 1.5
                lg("[live] host issued READY_CLOSE_LINK (0x5F00) - answering, then disconnecting.")
                lg.info("Closing the link...")
            if self.close_until is not None and time.monotonic() >= self.close_until:
                return True
        elif (self.exited and engine.barrier.mode == lsmod_barrier.STANDBY
              and not self.announced_cancel):
            lg("[live] answering the host's cancel-side standby (0x6600) so its "
                  "cancel-to-leave completes.")
            self.announced_cancel = True
        return False

    def handle_exit(self):
        """True when the walk-out is over (host CLOSE answered, or the leave tail elapsed)."""
        engine, lg = self.engine, self.lg
        # Let the HOST lead the exit: a proactive EXIT_ROOM hits it mid-CB2_ReturnToFieldFromMultiplayer
        # -> LinkRfu_FatalError. Its walk-out is mutual: it blocks at KeyInterCB_WaitForPlayersToExit
        # until we answer with OUR EXIT_ROOM, so keep the link alive and answer reactively below.
        if engine.done and not self.exited:
            lg("[live] trade(s) complete - returning to the overworld; keeping the link ALIVE "
                  "(held-keys keepalive + barrier) and letting the HOST lead the walk-out. Will answer "
                  "the host's EXIT_ROOM with ours, then mirror its READY_CLOSE_LINK / 'D'.")
            self.exited = True
            self.leave_until = time.monotonic() + LEAVE_TAIL_S
        if engine.host_exiting and not self.responded_exit and self.lstate is not None:
            lg("[live] host is walking out (EXIT_ROOM 0x17, 'escorted out... please wait') - "
                  "responding with OUR EXIT_ROOM so both are EXITING_ROOM -> host closes the link.")
            self.lstate.exit()
            self.responded_exit = True
        if self.handle_barrier():
            return True
        if self.leave_until is not None and time.monotonic() >= self.leave_until:
            lg("[live] overworld leave tail elapsed without a host CLOSE - disconnecting.")
            return True
        return False


def run_live(run_config, lg):
    t, engine, s, conn, lstate = _live_connect(run_config, lg)
    period = 1.0 / 59.727
    st = _LiveJoiner(run_config, lg, t, engine, s, conn, lstate)
    old_sigint = signal.signal(signal.SIGINT, st.on_interrupt)
    try:
        while True:
            s.tick()
            st.handle_interrupt()
            st.save_at_commit()
            if st.check_abort():
                break
            if st.connect_gate():
                _paced_sleep(s, period)
                continue
            st.log_ni_progress()
            st.log_entry_progress()
            st.log_leave_progress()
            st.handle_seating()
            if st.handle_exit():
                break
            _paced_sleep(s, period)
    finally:
        signal.signal(signal.SIGINT, old_sigint)
        s.close()          # flush the --capture .jsonl
        t.stop()
        lg.info("Link closed.")
    return engine


def run_replay(run_config, lg):
    replay_path = run_config.role.replay_path
    print(f"[replay] feeding host IN stream from {replay_path} through the RX stack...")
    t = tmod.ReplayTransport.from_capture(replay_path)
    if not t.ssid:
        sys.exit("capture has no SSID (predates SSID logging) - cannot decrypt")
    pc = cryptomod.PiaCrypto(t.ssid)
    # A finite capture would not outlast the 1935-frame anim; the early-arrival guard keeps READY_FINISH
    # before commit for any value.
    engine = make_engine(run_config, lg, default_anim_delay=5)
    s = simmod.Sim(t, pc, engine, t.our_ip, t.host_ip, log=lg)
    while not t.drained and not engine.done:
        s.tick()
    print(f"[replay] processed {s.rx_count} IN / emitted {s.tx_count} OUT datagrams")
    if engine.host_link_player:
        lg(f"[replay] host LinkPlayer reconstructed: {engine.host_link_player.name} "
           f"v0x{engine.host_link_player.version:04x}")
    print(f"[replay] host party blocks collected: {engine._host_party_blocks}/3")
    return engine


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("party", nargs="+", metavar="MON",
                    help="1..6 party mons, each a .pk3 or .ek3 file (gPlayerParty slots 0..5). The "
                         "documented default supplies 2: a kept mon (slot 0) and the trade mon "
                         "(slot 1).")
    ap.add_argument("-o", "--out", default="received.pk3",
                    help="save the received mon here (trades=1); for trades>1 this is a BASE/prefix "
                         "and each received mon is saved as <stem>_trade<k>_<species>.pk3")
    ap.add_argument("--out-size", type=int, choices=(80, 100), default=100,
                    help="received file size (100=party, 80=box)")
    ap.add_argument("--out-format", choices=("pk3", "ek3"), default="pk3",
                    help="received mon format: pk3=decrypted (opens in PKHeX), ek3=encrypted/raw")
    ap.add_argument("--slot", type=int, default=1,
                    help="party slot to offer on the FIRST round (default 1); the per-round default "
                         "list grows ascending from here (or [0..N-1] for a full-party swap)")
    ap.add_argument("--slots", default="",
                    help="explicit comma list of 0-based party slots to offer, one per trade "
                         "(len must == --trades, distinct, each < party size), e.g. --slots 0,2,4")
    ap.add_argument("--trades", type=int, default=1, choices=range(1, 7), metavar="N",
                    help="number of sequential trades to perform, 1..6 (default 1; 6 = swap both "
                         "entire parties). After the Nth trade the sim cancels-to-leave.")
    ap.add_argument("--self-id", type=int, default=1, choices=(1,),
                    help="wire mpId / gLocalLinkPlayerId (joiner = 1 = RIGHT seat; the only valid "
                         "value - mpId 0 is the host/parent) [trade.c:1816; link_rfu_2.c:1633-1638]")
    configmod.add_identity_arguments(ap)
    ap.add_argument("--anim-delay", type=int, default=None,
                    help="frames to wait after START_TRADE before READY_FINISH "
                         f"(default {trade.DEFAULT_ANIM_FRAMES}, the wire-measured wireless "
                         "DoTradeAnim duration)")
    ap.add_argument("--decline", action="store_true",
                    help="decline at the confirm prompt (confirm-NO -> immediate READY_CANCEL, "
                         "graceful cancel-to-leave) [trade.c:2019-2023]")
    ap.add_argument("--refuse-illegit", action="store_true",
                    help="treat an offered Deoxys/Mew as PARTNER_MON_INVALID and cancel-to-leave "
                         "(the host's illegitimate-legend gate; legitimacy is not offline-decodable)"
                         " [trade.c:1965-1968]")
    ap.add_argument("--trust-pia", action=argparse.BooleanOptionalAction, default=False,
                    help="send each block fragment ONCE (fire-and-forget) instead of the console's "
                         "re-send-until-confirmed loop. Default OFF (faithful re-send): against the real "
                         "client, a block streams in 1-2s WITH aggressive re-sends (~1.5x) and completes; "
                         "trust_pia's send-once crawled (~0.1 frag/s) and never completed. trust_pia was a "
                         "workaround for the 'flood', but that was the RTT deadlock (now fixed). "
                         "--trust-pia re-enables send-once")
    ap.add_argument("--compress", action="store_true", help="zstd-compress OUT payloads")
    ap.add_argument("--pace-ms", type=int, default=0,
                    help="live: minimum ms between two datagrams to the console, merging what is due "
                         "into one (0 = off). See sim.PACE_MIN_GAP_MS for the measurement.")
    ap.add_argument("--connect-id", "--parent-pid", dest="connect_id", default="",
                    help="(live) override the RFU connection id (hex, e.g. 7036) sent in the emulator "
                         "connect ('C') frame. Default: a random nonzero id - any nonzero value works. "
                         "--parent-pid is a deprecated alias.")
    ap.add_argument("--verbose", action="store_true")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="join the real Switch")
    mode.add_argument("--replay", metavar="CAPTURE", help="offline: replay a capture's host stream")
    ap.add_argument("--password", default="", help="LDN passphrase as hex (live); default = "
                    "the built-in 64-byte emulator passphrase (shared by FRLG/RSE)")
    ap.add_argument("--phy", default="phy0", help="wifi phy for the LDN join (live)")
    ap.add_argument("--keys", default="~/.switch/prod.keys", help="Switch prod.keys (live)")
    ap.add_argument("--comm-id", help="LDN local_communication_id (hex) to join (live); "
                    "if omitted, joins the only available network (scan logs candidates)")
    ap.add_argument("--capture", metavar="FILE", help="(live) record EVERY Pia datagram both "
                    "directions to a .jsonl (incl. the SSID), so a live attempt can be "
                    "decrypted/analysed offline")
    return ap


def _hex_bytes(ap, option, value, *, size=None):
    if not value:
        return None
    try:
        result = bytes.fromhex(value)
    except ValueError:
        ap.error(f"{option} must contain hexadecimal bytes")
    if size is not None and len(result) != size:
        ap.error(f"{option} must contain exactly {size} bytes")
    return result


def _build_run_config(ap, args):
    try:
        offered_slots = runtime.parse_slots(args.slots, args.trades, len(args.party))
        profile = configmod.profile_from_overrides(
            ot=args.ot, version=args.version, language=args.language,
            trainer_id=args.id)
        plan = configmod.TradePlan(
            party_paths=tuple(args.party), output_path=args.out,
            output_size=args.out_size, output_format=args.out_format,
            trade_slot=args.slot,
            offered_slots=None if offered_slots is None else tuple(offered_slots),
            trades=args.trades, anim_delay=args.anim_delay,
            trust_pia=args.trust_pia)
        ldn = configmod.LdnConfig(
            password=_hex_bytes(ap, "--password", args.password),
            phy=args.phy, keys_path=args.keys,
            local_comm_id=int(args.comm_id, 16) if args.comm_id else None,
            capture_path=args.capture)
        role = configmod.JoinerOptions(
            live=args.live, replay_path=args.replay,
            self_id=args.self_id, decline=args.decline,
            refuse_illegit=args.refuse_illegit, compress=args.compress, pace_ms=args.pace_ms,
            connect_id=_hex_bytes(ap, "--connect-id", args.connect_id, size=2))
        return configmod.TradeRunConfig(profile, plan, ldn, role)
    except ValueError as exc:
        ap.error(str(exc))


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    run_config = _build_run_config(ap, args)
    if not cryptomod.HAVE_ZSTD:
        sys.exit(f"FATAL: 'zstandard' is not installed in this Python ({sys.executable}).\n"
                 f"The host's handshake is zstd-compressed - without it the sim can't read a single\n"
                 f"message and will never reply. Install it into THIS interpreter:\n"
                 f"    {sys.executable} -m pip install zstandard")

    lg = runtime.ConsoleLog(args.verbose)
    engine = run_live(run_config, lg) if args.live else run_replay(run_config, lg)

    saved = save_received(engine, run_config, lg)
    if not saved and args.live:
        print("\nTrade did not complete (no mon received).")
    return 0 if (saved or args.replay) else 1


def save_received(engine, run_config, lg):
    mons = engine.received_mons or ([engine.received_mon] if engine.received_mon else [])
    plan = run_config.plan
    return runtime.save_received_mons(
        mons, output_path=plan.output_path, output_size=plan.output_size,
        output_format=plan.output_format, trades=plan.trades, log=lg)


if __name__ == "__main__":
    sys.exit(main())
