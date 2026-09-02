#!/usr/bin/env python3
"""frlgmg_client - RECEIVE a Wonder Card from a real FireRed/LeafGreen console (Mystery Gift CLIENT).

The console SHARES: Mystery Gift -> Wonder Cards -> Friend -> send (it must hold a card whose
sendType allows sharing, e.g. one delivered with `--gift beast-cutscene-share`). We join its LDN
session as the wireless CHILD, run the ROM's mystery_gift_client.c state machine against it, and
save whatever it pushes: the client scripts, the 332-byte Wonder Card and the 1024-byte delivery
RAM script. Every message and every parent slot is recorded, so a run is a full-fidelity capture
of a REAL Mystery Gift host - the data no passive two-console capture could give.

    sudo -E ./.venv/bin/python -u frlgmg_client.py --live --version firered --language french \\
        --capture scratchpad/mc1.pcap --out scratchpad/mc1

Outputs (with --out PREFIX): PREFIX_card.bin, PREFIX_ramscript.bin, PREFIX_messages.jsonl (every
MysteryGiftLink message both ways, hex), PREFIX_trace.jsonl (engine events by VBlank).
"""

import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frlgsim import config as configmod, crypto as cryptomod, sim as simmod  # noqa: E402
from frlgsim import transport as tmod, pia_connect, mg_client  # noqa: E402
from frlgsim import trade_runtime as runtime  # noqa: E402

PERIOD = 1.0 / 59.727


def _paced_sleep(s, period, slice_s=0.002):
    deadline = time.monotonic() + period
    while True:
        s.poll_rx()
        left = deadline - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(slice_s, left))


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


def save_outputs(engine, prefix, lg):
    if not prefix:
        return
    written = []
    if engine.saved_card is not None:
        p = f"{prefix}_card.bin"
        with open(p, "wb") as f:
            f.write(engine.saved_card)
        written.append(p)
    if engine.saved_ram_script is not None:
        p = f"{prefix}_ramscript.bin"
        with open(p, "wb") as f:
            f.write(engine.saved_ram_script)
        written.append(p)
    p = f"{prefix}_messages.jsonl"
    with open(p, "w") as f:
        for tick, d, ident, size, payload in engine.messages:
            f.write(json.dumps({"tick": tick, "dir": d, "ident": ident,
                                "name": mg_client.IDENT_NAMES.get(ident), "size": size,
                                "payload_hex": payload.hex()}) + "\n")
    written.append(p)
    p = f"{prefix}_trace.jsonl"
    with open(p, "w") as f:
        for ev in engine.trace:
            f.write(json.dumps({"tick": ev[0], "event": ev[1], "args": [
                (a.hex() if isinstance(a, (bytes, bytearray)) else a) for a in ev[2:]]}) + "\n")
    written.append(p)
    for w in written:
        lg.info(f"wrote {w}")


def run_live(args, profile, lg):
    lg.info(f"scanning for the console's Mystery Gift LDN network (nickname={profile.name})...")
    t = tmod.LiveTransport(
        password=_hex_bytes(None, "--password", args.password) if args.password else None,
        nickname=profile.name, keys_path=args.keys,
        local_comm_id=int(args.comm_id, 16) if args.comm_id else None,
        phyname=args.phy, log=lg).start()
    pc = cryptomod.PiaCrypto(t.ssid)
    elog = runtime.ConsoleLog(lg.verbose, "  [mgc]", start=lg.start)
    engine = mg_client.MysteryGiftClientEngine(
        profile.to_link_player(), version=profile.version, language=profile.language,
        holding_flag_id=args.holding_card, accept_replacement=not args.keep_card,
        yes_no_answer=not args.answer_no, software_version=args.software_version,
        trust_pia=args.trust_pia, inter_block_gap=args.inter_block_gap, log=elog)
    if not t.our_mac or not t.host_mac:
        lg.info(f"WARNING: MAC(s) not resolved from the participant list "
                f"(us={t.our_mac and t.our_mac.hex()} host={t.host_mac and t.host_mac.hex()})")
    conn = pia_connect.ConnectionManager(
        our_mac=t.our_mac or b"\x00" * 6, host_mac=t.host_mac or b"\x00" * 6,
        our_ip=t.our_ip, host_ip=t.host_ip, player_name=profile.name,
        random4=os.urandom(4), log=lg,
        player_id=os.urandom(16) if args.random_player_id else None,
        rtt_before_finalize=args.rtt_before_finalize,
        join_repeat_ticks=int(round(args.join_repeat_ms / 16.74)) if args.join_repeat_ms else 0)
    if args.random_player_id or args.rtt_before_finalize or args.join_repeat_ms:
        lg.info(f"[join-experiment] random_player_id={args.random_player_id} "
                f"rtt_before_finalize={args.rtt_before_finalize} join_repeat_ms={args.join_repeat_ms}")
    connect_id = _hex_bytes(None, "--connect-id", args.connect_id, size=2) if args.connect_id \
        else (int.from_bytes(os.urandom(2), "big") or 1).to_bytes(2, "big")
    lg.info(f"emulator connect id {connect_id.hex()}")
    s = simmod.Sim(t, pc, engine, t.our_ip, t.host_ip, conn=conn, compress=args.compress,
                   linkstate=None, connect_id=connect_id, capture_path=args.capture, log=lg,
                   pace_ms=args.pace_ms)
    lg.info("joined LDN; awaiting the console's Pia connection handshake (Net 0x11 -> Session join).")
    lg.info("ON THE CONSOLE: a player named "
            f"{profile.name!r} appears in its list - select it and answer YES to send.")

    interrupts = 0

    def on_interrupt(_s, _f):
        nonlocal interrupts
        interrupts += 1
        raise KeyboardInterrupt

    old = signal.signal(signal.SIGINT, on_interrupt)
    connect_ticks = ni_ticks = gift_ticks = 0
    announced = set()
    done_at = None
    saved = False
    CLOSE_GRACE_S = 3.0
    DONE_TAIL_S = 20.0
    try:
        while True:
            s.tick()
            if getattr(s, "ni_rejected", False):
                lg.info("ABORT: the console rejected our join (NI status != JOIN_GROUP_OK) - it answered NO.")
                break
            if getattr(s, "host_disconnected", False):
                lg.info("Console closed the RFU link ('D' 0x44) - done.")
                break
            if not s.connected:
                connect_ticks += 1
                if connect_ticks % 120 == 0:
                    lg.info(f"awaiting Pia connection: {connect_ticks}f conn={conn.state} "
                            f"rx_ok={s.rx_count} rx_fail={s.rx_fail} protos={dict(sorted(s.rx_protos.items()))} "
                            f"tx={s.tx_count}")
                _paced_sleep(s, PERIOD)
                continue
            if "conn" not in announced:
                announced.add("conn")
                lg.info(f"Pia connection ESTABLISHED after {connect_ticks}f; now the emulator RFU "
                        "connect + NI handshake (the console shows our name and asks YES/NO).")
            if not s._ni_done:
                ni_ticks += 1
                if ni_ticks % 120 == 0:
                    ni_ = getattr(s, "_ni", None)
                    lg.info(f"awaiting RFU handshake: {ni_ticks}f gba_accepted={s._gba_accepted} "
                            f"send_ni={'done' if (ni_ is not None and ni_.done) else 'in progress' if ni_ else 'not built'} "
                            f"host_ni_null={s._host_ni_null_seen} host_uni={s._host_uni_seen} "
                            f"host_t={s.host_t_in} tx={s.tx_count}")
            else:
                gift_ticks += 1
                if gift_ticks % 300 == 0:
                    lg.info(f"[mgc] {gift_ticks}f: {engine.status()} host_t={s.host_t_in} tx={s.tx_count}")
            if engine.established and "est" not in announced:
                announced.add("est")
                lg.info("RFU link ESTABLISHED (both LinkPlayer blocks exchanged).")
            if engine.card_received and not saved:
                saved = True
                save_outputs(engine, args.out, lg)
            if engine.done and done_at is None:
                done_at = time.monotonic()
                lg.info(f"Client finished with result {mg_client.CLI_MSG_NAMES.get(engine.result, engine.result)}; "
                        "closing the link.")
            if done_at is not None:
                if engine.close_confirmed and time.monotonic() - done_at >= CLOSE_GRACE_S:
                    lg.info("Close handshake complete - leaving.")
                    break
                if time.monotonic() - done_at >= DONE_TAIL_S:
                    lg.info("No close acknowledgement from the console within the tail - leaving.")
                    break
            _paced_sleep(s, PERIOD)
    except KeyboardInterrupt:
        lg.info("interrupted")
    finally:
        signal.signal(signal.SIGINT, old)
        s.close()
        t.stop()
        lg.info("Link closed.")
        lg.info(f"final: {engine.status()}")
        save_outputs(engine, args.out, lg)
    return engine


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    configmod.add_identity_arguments(ap)
    ap.add_argument("--live", action="store_true", required=True, help="join the real console")
    ap.add_argument("--holding-card", type=int, default=0, metavar="FLAGID",
                    help="claim to already hold the Wonder Card with this flagId (0 = none). Same "
                         "id as the console's card -> it answers HadCard; a different id -> it asks to "
                         "replace (we answer YES unless --keep-card)")
    ap.add_argument("--keep-card", action="store_true", help="answer NO to the replace-card prompt")
    ap.add_argument("--answer-no", action="store_true", help="answer NO to any yes/no prompt")
    ap.add_argument("--software-version", type=int, default=0, help="RomHeaderSoftwareVersion to report")
    ap.add_argument("--inter-block-gap", type=int, default=mg_client.DEFAULT_INTER_BLOCK_GAP,
                    help="idle VBlanks between two blocks of one outgoing message")
    ap.add_argument("--trust-pia", action=argparse.BooleanOptionalAction, default=False,
                    help="send each block fragment once (default: faithful re-send until reflected)")
    ap.add_argument("--random-player-id", action="store_true",
                    help="send a random 16-byte Pia player id in the Session join (a console sends a real one)")
    ap.add_argument("--rtt-before-finalize", action="store_true",
                    help="answer the host's RTT probes before the Session is finalized")
    ap.add_argument("--join-repeat-ms", type=int, default=0,
                    help="re-send the Session join every N ms until accepted, like a console (0 = once)")
    ap.add_argument("--compress", action="store_true", help="zstd-compress OUT payloads")
    ap.add_argument("--pace-ms", type=int, default=0)
    ap.add_argument("--connect-id", default="", help="override the 2-byte emulator connect id (hex)")
    ap.add_argument("--password", default="", help="LDN passphrase as hex (default: the built-in one)")
    ap.add_argument("--phy", default="phy0")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--comm-id", help="LDN local_communication_id (hex) to join")
    ap.add_argument("--capture", metavar="FILE", help="record every Pia datagram both ways (.jsonl)")
    ap.add_argument("--out", metavar="PREFIX", default="", help="write PREFIX_card.bin etc.")
    ap.add_argument("--verbose", action="store_true", help="NEVER on a live run (floods the link)")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if not cryptomod.HAVE_ZSTD:
        sys.exit("FATAL: zstandard is not installed in this interpreter")
    profile = configmod.profile_from_overrides(ot=args.ot, version=args.version,
                                              language=args.language, trainer_id=args.id)
    lg = runtime.ConsoleLog(args.verbose)
    engine = run_live(args, profile, lg)
    if engine.card_received:
        print(f"\nReceived Wonder Card: {mg_client.describe_wonder_card(engine.saved_card)}")
        return 0
    print(f"\nNo card received (result={engine.result}, state={engine.state}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
