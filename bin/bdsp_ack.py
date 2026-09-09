#!/usr/bin/env python3
"""Answer the console. Take the LDN seat in a BDSP session and send Pia's update-session ack.

The whole sp4 capture is one Shining Pearl host rebroadcasting a Local Protocol *update session*
every 100 ms - 674 of them, sequence id 4 in every one, with us already listed at seat 1. A host
repeats that until every station acknowledges it, so it is one console asking the same question
674 times and never being answered. This sends the answer.

THE PASS SIGNAL NEEDS NOTHING ON SCREEN, which is the point: the console shows nothing when we
join, so "the rebroadcast stopped" is the only readable outcome this run can have. A gap longer
than `--quiet-for` in a stream that has been arriving every 100 ms means the console accepted a
packet from us.

What the ack is made of is read off the console's own code and its own packets, not guessed:

  the 20 bytes      main.bin 0x016bc0f4 serialises {1, 0x21, size=0, six zeros, pad, seq, zero},
                    and the constructor at 0x016bc0c8 leaves the size field at 0 for an ack
  message flags     0x11. LocalProtocol has exactly ONE send path (0x016af22c) and all four of its
                    message types reach it with the same options, so an ack is framed like the
                    update session it answers - which reads 0x11 on the wire
  destination       a bitmap of `1 << station_index` (0x0159a15c builds it), and 0 for broadcast,
                    which is what the console's own update session carries
  presence byte     0x7F, off the capture. Only bits 1/2/4/8 name a field; the console sets three
                    more that name nothing
  who the ack is    the sender's ADDRESS. 0x016aec94 walks the nine node slots comparing a 16-byte
  attributed to     address and a port - not the variable id, not the constant id. So our own
                    source variable id, which the console has never been told, cannot be what
                    decides whether this lands

STILL NOT READ OFF THE CONSOLE, and why this sends in phases: whether a client's LocalProtocol
broadcasts its ack the way the host broadcasts the question, or unicasts it to the host with the
host's variable id in the packet header. Each phase is timestamped and the rebroadcast either
stops during one of them or it does not, so a single run separates them.

docs/bdsp_session.md, NOTES.local.md sp24. Never pass --verbose to a live run; use --capture.
"""
import argparse, json, os, socket, struct, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED):
    sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.bdsp import COMM_ID, PASSPHRASE, PIA_PORT, session_keys
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn.pia5 import (PiaHeader5, is_pia5, ciphertext, gcm_iv, ldn_nonce_crc,
                              build_message, pad_payload, parse_messages, encrypt_payload,
                              decrypt_payload)
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.host_support import resolve_keys

def cleanup():
    import subprocess
    for v in ("ldn", "ldn-mon", "ldn-tap", "ldnclient"):
        subprocess.run(["iw", "dev", v, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_socket(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, ifname.encode())
    except PermissionError:
        pass
    s.bind(("", PIA_PORT))
    s.setblocking(False)
    return s


def ack_packet(session_key, network_id_le, our_mac, src_var, dst_var, nonce8, sequence_id,
               destination):
    """The whole datagram: Local ack -> Pia message -> padded -> AES-GCM -> Pia 5.x header."""
    body = pad_payload(build_message(lp.build_ack(sequence_id), protocol=lp.PROTOCOL,
                                     message_flags=lp.MESSAGE_FLAGS, destination=destination))
    iv = gcm_iv(ldn_nonce_crc(network_id_le, our_mac), src_var, nonce8)
    ct, tag = encrypt_payload(session_key, iv, body)
    header = PiaHeader5(dst_var=dst_var, src_var=src_var, packet_id=0, footer_size=0,
                        nonce8=nonce8, tag=tag[:8], encrypted=True)
    return header.pack() + ct


async def main_async(args):
    keys = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    nets = await ldn.scan(keys, phyname=phy, channels=[int(c) for c in args.channels.split(",")],
                          dwell_time=0.8)
    want = int(args.comm_id, 16) if args.comm_id else COMM_ID
    net = next((n for n in nets if n.local_communication_id == want), None)
    if net is None:
        print("[ack] target network not seen - is the console sitting in the room right now?")
        return 3
    k = session_keys(net)
    session_key, network_id_le = k.session_key, k.network_id_le
    session_param, game_key = k.session_param, k.game_key
    print(f"[ack] target ssid={net.ssid.hex()} ch={net.channel} app_version={net.app_version}")
    print(f"[ack] network id (LE) {network_id_le.hex()}  session param {session_param:#010x}")
    print(f"[ack] game key {game_key.hex()}")
    print(f"[ack] session key {session_key.hex()}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys, net, PASSPHRASE
    param.name, param.app_version = args.name.encode(), net.app_version
    param.phyname, param.ifname = phy, args.ifname

    cap = open(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n")
            cap.flush()

    async with ldn.connect(param) as network:
        info = network.info()
        parts = list(getattr(info, "participants", []) or [])
        host = parts[0] if parts else None
        host_ip = getattr(host, "ip_address", None) or "169.254.54.1"
        host_mac = bytes(getattr(host, "mac_address", b"") or b"")
        ours = next((p for p in parts[1:] if getattr(p, "connected", False)), None)
        our_ip = getattr(ours, "ip_address", None) or host_ip.rsplit(".", 1)[0] + ".2"
        our_mac = bytes(getattr(ours, "mac_address", b"") or b"")
        if args.our_mac:
            our_mac = bytes.fromhex(args.our_mac.replace(":", ""))
        bcast = our_ip.rsplit(".", 1)[0] + ".255"
        print(f"[ack] seat taken: us={our_ip} ({our_mac.hex()}) "
              f"host={host_ip} ({host_mac.hex()}) bcast={bcast}")
        if len(our_mac) != 6:
            print("[ack] our MAC is unknown - pass --our-mac; the IV cannot be built without it")
            return 6
        record(rec="seat", us=our_ip, our_mac=our_mac.hex(), host=host_ip,
               host_mac=host_mac.hex(), session_key=session_key.hex(),
               network_id_le=network_id_le.hex())

        sock = make_socket(args.ifname)
        t0 = time.monotonic()
        state = {"seq": None, "last_update": None, "updates": 0, "undecrypted": 0,
                 "host_var": None, "stopped_at": None, "phase": "listen"}

        async def receiver():
            while True:
                await trio.lowlevel.wait_readable(sock)
                try:
                    data, addr = sock.recvfrom(4096)
                except BlockingIOError:
                    continue
                now = time.monotonic() - t0
                if addr[0] == our_ip:
                    continue                      # our own broadcast, looped back on the tap
                if not is_pia5(data):
                    record(rec="rx_nonpia", t=now, src=addr[0], data=data[:64].hex())
                    continue
                h = PiaHeader5.parse(data)
                # the IV is keyed to the SENDER's MAC, and everything not ours is the host's
                iv = gcm_iv(ldn_nonce_crc(network_id_le, host_mac), h.src_var, h.nonce8)
                pt = decrypt_payload(session_key, iv, ciphertext(data), h.tag)
                if pt is None:                    # the tag is the oracle; a miss is not an error
                    state["undecrypted"] += 1
                    record(rec="rx_undecrypted", t=now, src=addr[0], dst_var=h.dst_var,
                           src_var=h.src_var, nonce=h.nonce8.hex())
                    continue
                msgs = parse_messages(pt)
                record(rec="rx", t=now, src=addr[0], dst_var=h.dst_var, src_var=h.src_var,
                       nonce=h.nonce8.hex(),
                       msgs=[{"proto": m.protocol, "flags": m.message_flags,
                              "dest": m.destination, "payload": m.payload.hex()} for m in msgs])
                for m in msgs:
                    if m.protocol != lp.PROTOCOL or not m.payload:
                        continue
                    kind = m.payload[1]
                    if kind == lp.UPDATE_SESSION:
                        us = lp.parse_update_session(m.payload)
                        gap = None if state["last_update"] is None else now - state["last_update"]
                        state["last_update"] = now
                        state["updates"] += 1
                        state["host_var"] = us.host_variable_id
                        if state["seq"] != us.sequence_id:
                            state["seq"] = us.sequence_id
                            seats = ", ".join(f"{n.ip}:{n.port}/r{n.ranking}" for n in us.occupied)
                            print(f"[rx] t={now:6.2f} update session seq={us.sequence_id} "
                                  f"host_var={us.host_variable_id:#010x} seats: {seats}")
                        if gap is not None and gap >= args.quiet_for and state["updates"] > 3:
                            print(f"[rx] t={now:6.2f} *** {gap:.2f}s GAP in the rebroadcast, "
                                  f"phase {state['phase']} ***")
                    else:
                        print(f"[rx] t={now:6.2f} local message type {kind:#04x} "
                              f"({len(m.payload)} B) - NOT an update session")

        async def watchdog():
            """The pass signal: the 100 ms rebroadcast simply stopping."""
            while True:
                await trio.sleep(0.2)
                now = time.monotonic() - t0
                last = state["last_update"]
                if last is None or state["updates"] < 4 or state["phase"] == "listen":
                    continue
                if now - last >= args.quiet_for and state["stopped_at"] is None:
                    state["stopped_at"] = now
                    print(f"\n[ack] *** THE REBROADCAST STOPPED at t={now:.2f}s, "
                          f"{now - last:.2f}s after the last one, during phase "
                          f"{state['phase']} - the console accepted a packet from us ***\n")
                    record(rec="stopped", t=now, phase=state["phase"], quiet=now - last)

        async def sender():
            await trio.sleep(args.listen_first)
            if state["seq"] is None:
                print("[ack] no update session seen while listening - nothing to acknowledge")
                return
            nonce = int.from_bytes(os.urandom(8), "big")
            host_var = state["host_var"] or 0
            phases = [
                ("broadcast/dst0", bcast, 0, lp.BROADCAST),
                ("unicast/dst=host_var/bitmap1", host_ip, host_var, 1),
                ("unicast/dst=host_var/bitmap0", host_ip, host_var, lp.BROADCAST),
                ("unicast/dst0/bitmap0", host_ip, 0, lp.BROADCAST),
            ]
            for label, dst_ip, dst_var, destination in phases:
                if state["stopped_at"] is not None:
                    break
                state["phase"] = label
                seq = state["seq"]
                print(f"\n[tx] phase {label}: acking seq={seq} -> {dst_ip} "
                      f"dst_var={dst_var:#010x} destination={destination:#x} "
                      f"for {args.phase_seconds:.0f}s")
                deadline = time.monotonic() + args.phase_seconds
                n = 0
                while time.monotonic() < deadline and state["stopped_at"] is None:
                    nonce = (nonce + 1) & ((1 << 64) - 1)
                    n8 = nonce.to_bytes(8, "big")
                    pkt = ack_packet(session_key, network_id_le, our_mac, args.src_var,
                                     dst_var, n8, state["seq"], destination)
                    try:
                        sock.sendto(pkt, (dst_ip, PIA_PORT))
                    except OSError as e:
                        print(f"[tx] send failed: {e}")
                        break
                    n += 1
                    record(rec="tx", t=time.monotonic() - t0, phase=label, dst=dst_ip,
                           dst_var=dst_var, destination=destination, seq=state["seq"],
                           nonce=n8.hex(), data=pkt.hex())
                    await trio.sleep(args.period)
                print(f"[tx] phase {label}: {n} ack(s) sent, "
                      f"{'STOPPED' if state['stopped_at'] else 'still rebroadcasting'}")
            state["phase"] = "after"

        with trio.move_on_after(args.hold):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver)
                nursery.start_soon(watchdog)
                nursery.start_soon(sender)

        print(f"\n[ack] {state['updates']} update session(s) seen, "
              f"{state['undecrypted']} packet(s) that did not decrypt")
        if state["stopped_at"] is not None:
            print(f"[ack] PASS: the rebroadcast stopped during phase {state['phase']}")
        else:
            print("[ack] the console kept asking - the ack was not accepted as sent")
        record(rec="end", updates=state["updates"], stopped_at=state["stopped_at"])
    if cap:
        cap.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None)
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="6")
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--listen-first", type=float, default=6.0,
                    help="watch the rebroadcast before answering, so its period is measured")
    ap.add_argument("--phase-seconds", type=float, default=6.0)
    ap.add_argument("--period", type=float, default=0.1,
                    help="the console's own update-session period")
    ap.add_argument("--quiet-for", type=float, default=1.5,
                    help="a gap this long in a 100 ms stream is the pass signal")
    ap.add_argument("--src-var", type=lambda s: int(s, 0), default=0x2B7F4C11,
                    help="our own Pia variable id; the console has never been told one")
    ap.add_argument("--our-mac", default=None,
                    help="override the MAC the IV is built from, hex or colon-separated")
    ap.add_argument("--capture", default=None, help="jsonl of every packet, both directions")
    args = ap.parse_args()
    if os.geteuid() != 0:
        ap.error("must run as root")
    return trio.run(main_async, args)


if __name__ == "__main__":
    sys.exit(main())
