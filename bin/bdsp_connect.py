#!/usr/bin/env python3
"""Ask a BDSP console to let us into its mesh - and make it answer even when it will not.

Session 46 got the console to accept a packet: answering the Local Protocol's update session made
it stop asking. That is bookkeeping, and the game saw nothing. The layer a station actually JOINS
on is the Mesh Station Protocol (0x14), and this sends its connection request.

THE RUN IS A SWEEP, and the reason is worth stating because it is what makes it cheap. The
console's parser (main.bin 0x0154ebd0, see pokeldn/ldn/station_protocol.py for the field-by-field
reading) checks things in this order:

    the target constant id and variable id must be the console's own   -> else SILENCE
    the protocol count at [0xF] must equal the console's own count     -> else SILENCE
    each protocol's version must match what the console registers      -> else A REPLY

and an id the console does NOT register has an expected version of 0. So a request carrying N
entries of (id 0xFF, version 1) is a guaranteed "version is too high" the moment N is right, and
silence every other time. **Sweeping N therefore measures the console's protocol count**, without
knowing a single one of its protocols, and the first reply this project has ever had from a native
Switch title is the pass signal.

The ack goes first, so the console falls silent and ANY packet afterwards is unambiguously an
answer to us. docs/bdsp_pia.md. Never pass --verbose to a live run; use --capture.
"""
import argparse, json, os, socket, struct, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED):
    sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.bdsp import COMM_ID, PASSPHRASE, PIA_PORT, session_keys
from pokeldn.ldn import local_protocol as lp, station_protocol as stp
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


def wrap(keys, our_mac, src_var, dst_var, nonce8, payload, protocol, port=0,
         destination=lp.BROADCAST, message_flags=lp.MESSAGE_FLAGS):
    """A Pia message in a Pia packet, in the framing session 46 proved the console accepts."""
    body = pad_payload(build_message(payload, protocol=protocol, port=port,
                                     message_flags=message_flags, destination=destination))
    iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, our_mac), src_var, nonce8)
    ct, tag = encrypt_payload(keys.session_key, iv, body)
    return PiaHeader5(dst_var=dst_var, src_var=src_var, packet_id=0, footer_size=0,
                      nonce8=nonce8, tag=tag[:8], encrypted=True).pack() + ct


async def main_async(args):
    keys_file = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    nets = await ldn.scan(keys_file, phyname=phy,
                          channels=[int(c) for c in args.channels.split(",")], dwell_time=0.8)
    want = int(args.comm_id, 16) if args.comm_id else COMM_ID
    net = next((n for n in nets if n.local_communication_id == want), None)
    if net is None:
        print("[cx] target network not seen - is the console sitting in the room right now?")
        return 3
    keys = session_keys(net)
    print(f"[cx] target ssid={net.ssid.hex()} ch={net.channel} app_version={net.app_version}")
    print(f"[cx] {keys}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys_file, net, PASSPHRASE
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
        bcast = our_ip.rsplit(".", 1)[0] + ".255"
        print(f"[cx] seat taken: us={our_ip} ({our_mac.hex()}) host={host_ip} ({host_mac.hex()})")
        if len(our_mac) != 6 or len(host_mac) != 6:
            print("[cx] a MAC is missing - the IV and the constant ids cannot be built")
            return 6

        our_constant = stp.ldn_constant_id(our_mac)
        our_service = stp.ldn_service_variable_id(our_mac)
        host_constant = stp.ldn_constant_id(host_mac)
        print(f"[cx] our constant id  {our_constant:#018x}  service {our_service:#010x}")
        print(f"[cx] host constant id {host_constant:#018x}  (from its MAC)")
        record(rec="seat", us=our_ip, our_mac=our_mac.hex(), host=host_ip,
               host_mac=host_mac.hex(), our_constant=our_constant, host_constant=host_constant,
               session_key=keys.session_key.hex())

        sock = make_socket(args.ifname)
        t0 = time.monotonic()
        st = {"seq": None, "host_var": None, "host_constant_seen": None, "last_update": None,
              "updates": 0, "phase": "listen", "replies": [], "quiet_since": None}

        def decode(data, addr, now):
            h = PiaHeader5.parse(data)
            iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, host_mac), h.src_var, h.nonce8)
            pt = decrypt_payload(keys.session_key, iv, ciphertext(data), h.tag)
            if pt is None:
                record(rec="rx_undecrypted", t=now, src=addr[0], raw=data[:48].hex())
                print(f"[rx] t={now:6.2f} a packet from {addr[0]} that did NOT decrypt "
                      f"(dst_var={h.dst_var:#010x} src_var={h.src_var:#010x})")
                return None, []
            return h, parse_messages(pt)

        async def receiver():
            while True:
                await trio.lowlevel.wait_readable(sock)
                try:
                    data, addr = sock.recvfrom(4096)
                except BlockingIOError:
                    continue
                now = time.monotonic() - t0
                if addr[0] == our_ip:
                    continue                  # our own broadcast, looped back on the tap
                if not is_pia5(data):
                    record(rec="rx_nonpia", t=now, src=addr[0], data=data[:64].hex())
                    continue
                h, msgs = decode(data, addr, now)
                if h is None:
                    continue
                record(rec="rx", t=now, src=addr[0], dst_var=h.dst_var, src_var=h.src_var,
                       msgs=[{"proto": m.protocol, "port": m.port, "flags": m.message_flags,
                              "dest": m.destination, "payload": m.payload.hex()} for m in msgs])
                for m in msgs:
                    if m.protocol == lp.PROTOCOL and m.payload and m.payload[1] == lp.UPDATE_SESSION:
                        us = lp.parse_update_session(m.payload)
                        st["last_update"] = now
                        st["updates"] += 1
                        st["host_var"] = us.host_variable_id
                        st["host_constant_seen"] = int.from_bytes(us.host_constant_id, "little")
                        if st["seq"] != us.sequence_id:
                            st["seq"] = us.sequence_id
                            print(f"[rx] t={now:6.2f} update session seq={us.sequence_id} "
                                  f"host_var={us.host_variable_id:#010x} "
                                  f"host_constant={st['host_constant_seen']:#018x}")
                    elif m.protocol == stp.PROTOCOL:
                        kind, rest = stp.parse_message(m.payload)
                        st["replies"].append((now, st["phase"], m.payload.hex()))
                        print(f"\n[rx] t={now:6.2f} *** STATION PROTOCOL, type {kind} "
                              f"({len(m.payload)} B), phase {st['phase']} ***")
                        if kind == stp.CONNECTION_RESPONSE:
                            print(f"[rx]     {stp.parse_connection_response(m.payload)}")
                        print(f"[rx]     {m.payload.hex()}\n")
                        record(rec="station_protocol", t=now, phase=st["phase"], kind=kind,
                               payload=m.payload.hex())
                    else:
                        print(f"[rx] t={now:6.2f} protocol {m.protocol} port {m.port} "
                              f"({len(m.payload)} B) - something new")

        async def sender():
            nonce = int.from_bytes(os.urandom(8), "big")

            def next_nonce():
                nonlocal nonce
                nonce = (nonce + 1) & ((1 << 64) - 1)
                return nonce.to_bytes(8, "big")

            await trio.sleep(args.listen_first)
            if st["seq"] is None:
                print("[cx] no update session seen - the console is not hosting a Pia network")
                return
            if st["host_constant_seen"] != host_constant:
                print(f"[cx] NOTE: the update session says {st['host_constant_seen']:#018x} and "
                      f"the MAC rule says {host_constant:#018x} - using the message's")
            target_constant = st["host_constant_seen"] or host_constant
            target_var = st["host_var"]

            st["phase"] = "ack"
            print(f"\n[tx] acking seq={st['seq']} until the rebroadcast stops")
            deadline = time.monotonic() + args.ack_seconds
            while time.monotonic() < deadline:
                pkt = wrap(keys, our_mac, args.src_var, 0, next_nonce(),
                           lp.build_ack(st["seq"]), lp.PROTOCOL)
                sock.sendto(pkt, (bcast, PIA_PORT))
                record(rec="tx_ack", t=time.monotonic() - t0, seq=st["seq"])
                await trio.sleep(0.1)
                quiet = time.monotonic() - t0 - (st["last_update"] or 0)
                if st["updates"] > 3 and quiet > args.quiet_for:
                    print(f"[tx] the rebroadcast stopped ({quiet:.2f}s quiet) - sweeping now")
                    break
            else:
                print("[tx] the rebroadcast did NOT stop; sweeping anyway")

            location = stp.station_location(our_ip, PIA_PORT, our_constant, args.src_var,
                                            our_service)
            infos = [stp.player_info(args.name)]
            # The ack proved BROADCAST framing, so that pass goes first. A silent sweep there is
            # not yet an answer: the station protocol may want the host's own address, and that is
            # one more variable, so it gets its own pass rather than being mixed into the first.
            modes = ["broadcast", "unicast"]
            if args.unicast:
                modes = ["unicast"]
            elif args.broadcast_only:
                modes = ["broadcast"]
            for mode in modes:
                dst_ip = bcast if mode == "broadcast" else host_ip
                dst_var = 0 if mode == "broadcast" else target_var
                print(f"\n[tx] --- sweep pass: {mode} -> {dst_ip} dst_var={dst_var:#010x}")
                for n in range(args.min_protocols, args.max_protocols + 1):
                    st["phase"] = f"{mode}/protocols={n}"
                    req = stp.build_connection_request(
                        target_constant, target_var, [(args.probe_id, args.probe_version)] * n,
                        location, network_id=0, player_infos=infos, ack_id=n + 1)
                    pkt = wrap(keys, our_mac, args.src_var, dst_var, next_nonce(), req,
                               stp.PROTOCOL, port=stp.PORT_UNRELIABLE)
                    sock.sendto(pkt, (dst_ip, PIA_PORT))
                    record(rec="tx_request", t=time.monotonic() - t0, n=n, mode=mode, dst=dst_ip,
                           size=len(req), request=req.hex())
                    print(f"[tx] {mode:9s} protocols={n:2d}  request {len(req)} B"
                          f"{'   REPLY SEEN' if st['replies'] else ''}")
                    await trio.sleep(args.gap)
                    if st["replies"] and args.stop_on_reply:
                        break
                if st["replies"] and args.stop_on_reply:
                    break
            st["phase"] = "after"
            print("[tx] sweep done")

        with trio.move_on_after(args.hold):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver)
                nursery.start_soon(sender)

        print(f"\n[cx] {st['updates']} update session(s), {len(st['replies'])} station-protocol "
              f"reply/replies")
        for t, phase, payload in st["replies"]:
            print(f"[cx]   t={t:.2f} phase {phase}: {payload}")
        if st["replies"]:
            print("[cx] PASS: the console answered on the mesh station protocol")
        else:
            print("[cx] silence across the whole sweep")
        record(rec="end", updates=st["updates"], replies=len(st["replies"]))
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
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--hold", type=float, default=300.0)
    ap.add_argument("--listen-first", type=float, default=5.0)
    ap.add_argument("--ack-seconds", type=float, default=6.0)
    ap.add_argument("--quiet-for", type=float, default=1.0)
    ap.add_argument("--min-protocols", type=int, default=0)
    ap.add_argument("--max-protocols", type=int, default=40)
    ap.add_argument("--gap", type=float, default=1.2, help="seconds to wait for a reply per N")
    ap.add_argument("--probe-id", type=lambda s: int(s, 0), default=0xFF,
                    help="a protocol id the console does not register, so its version is 0")
    ap.add_argument("--probe-version", type=int, default=1,
                    help="1 against an expected 0 is a guaranteed 'version is too high'")
    ap.add_argument("--src-var", type=lambda s: int(s, 0), default=0x2B7F4C11)
    ap.add_argument("--unicast", action="store_true",
                    help="only the unicast pass, skipping the broadcast one")
    ap.add_argument("--broadcast-only", action="store_true",
                    help="only the broadcast pass, the framing the ack proved")
    ap.add_argument("--stop-on-reply", action="store_true", default=True)
    ap.add_argument("--no-stop-on-reply", dest="stop_on_reply", action="store_false")
    ap.add_argument("--capture", default=None)
    args = ap.parse_args()
    if os.geteuid() != 0:
        ap.error("must run as root")
    return trio.run(main_async, args)


if __name__ == "__main__":
    sys.exit(main())
