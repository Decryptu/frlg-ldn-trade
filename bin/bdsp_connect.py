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
from pokeldn.ldn import local_protocol as lp, mesh_protocol as mp, station_protocol as stp
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
              "updates": 0, "phase": "listen", "replies": [], "waiter": None, "reply": None,
              "reply_payload": None, "result": None}

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
                    elif m.protocol == mp.PROTOCOL:
                        kind, name = mp.parse_message(m.payload)
                        st["replies"].append((now, st["phase"], m.payload.hex()))
                        st["reply"] = ("mesh", kind)
                        st["reply_payload"] = m.payload
                        if st["waiter"] is not None:
                            st["waiter"].set()
                        print(f"\n[rx] t={now:6.2f} *** MESH PROTOCOL {name} "
                              f"({len(m.payload)} B), phase {st['phase']} ***")
                        if kind == mp.JOIN_RESPONSE:
                            print(f"[rx]     {mp.parse_join_response(m.payload)}")
                        print(f"[rx]     {m.payload.hex()}\n")
                        record(rec="mesh_protocol", t=now, phase=st["phase"], kind=kind,
                               payload=m.payload.hex())
                    elif m.protocol == stp.PROTOCOL:
                        kind, rest = stp.parse_message(m.payload)
                        st["replies"].append((now, st["phase"], m.payload.hex()))
                        # only a connection response carries a result; an ack's byte 1 is padding
                        result = (m.payload[1] if kind == stp.CONNECTION_RESPONSE
                                  and len(m.payload) > 1 else None)
                        st["reply"] = (kind, result)
                        st["reply_payload"] = m.payload
                        if st["waiter"] is not None:
                            st["waiter"].set()
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

            async def ask(payload, protocol, label, timeout=None, src_var=None):
                """Send one station-protocol message and wait for a reply. -> the result code, or
                None for silence. Silence is a real answer here, so it costs the full timeout."""
                st["phase"] = label
                st["reply"] = None
                st["waiter"] = trio.Event()
                pkt = wrap(keys, our_mac, src_var if src_var is not None else args.src_var,
                           dst_var, next_nonce(), payload, protocol, port=stp.PORT_UNRELIABLE)
                sock.sendto(pkt, (dst_ip, PIA_PORT))
                record(rec="tx_request", t=time.monotonic() - t0, label=label, dst=dst_ip,
                       size=len(payload), request=payload.hex())
                with trio.move_on_after(timeout or args.gap):
                    await st["waiter"].wait()
                st["waiter"] = None
                got = st["reply"]
                if got is None:
                    return None                    # silence, which is itself an answer
                kind, result = got
                if kind != stp.CONNECTION_RESPONSE:
                    return ("other", kind)         # something we did not ask for; never a version
                return result

            def request(protocols, ack_id=1):
                return stp.build_connection_request(
                    target_constant, target_var, protocols, location, network_id=0,
                    player_infos=infos, ack_id=ack_id)

            await trio.sleep(args.listen_first)
            if st["seq"] is None:
                print("[cx] no update session seen - the console is not hosting a Pia network")
                return
            target_constant = st["host_constant_seen"] or host_constant
            target_var = st["host_var"]

            st["phase"] = "ack"
            print(f"\n[tx] acking seq={st['seq']} until the rebroadcast stops")
            deadline = time.monotonic() + args.ack_seconds
            while time.monotonic() < deadline:
                sock.sendto(wrap(keys, our_mac, args.src_var, 0, next_nonce(),
                                 lp.build_ack(st["seq"]), lp.PROTOCOL), (bcast, PIA_PORT))
                record(rec="tx_ack", t=time.monotonic() - t0, seq=st["seq"])
                await trio.sleep(0.1)
                quiet = time.monotonic() - t0 - (st["last_update"] or 0)
                if st["updates"] > 3 and quiet > args.quiet_for:
                    print(f"[tx] the rebroadcast stopped ({quiet:.2f}s quiet)")
                    break
            else:
                print("[tx] the rebroadcast did NOT stop; carrying on anyway")

            dst_ip = bcast if not args.unicast else host_ip
            dst_var = 0 if not args.unicast else target_var
            location = stp.station_location(our_ip, PIA_PORT, our_constant, args.src_var,
                                            our_service)
            infos = [stp.player_info(args.name)]

            count = args.count
            if count is None:
                print(f"\n[tx] --- sweeping for the console's protocol count, {dst_ip}")
                for n in range(args.min_protocols, args.max_protocols + 1):
                    got = await ask(request([(args.probe_id, args.probe_version)] * n, n + 1),
                                    stp.PROTOCOL, f"count={n}")
                    print(f"[tx] count={n:2d}  "
                          f"{'REPLY ' + str(got) if got is not None else 'silence'}")
                    if got is not None:
                        count = n
                        break
                if count is None:
                    print("[cx] the whole count sweep was silent - the target ids are wrong, "
                          "not the count (see the harness)")
                    return
            print(f"\n[cx] the console registers {count} protocols")
            record(rec="protocol_count", count=count)
            if args.connect:
                # THE MINIMAL VALID REQUEST, and it needs no knowledge of the console's protocols:
                # an id it does not register expects version 0, so `count` entries of (0xFF, 0)
                # pass the whole version loop. sp29 proved the pass; what refuses it afterwards is
                # the second stage, 0x0154fcfc.
                print(f"\n[tx] --- one well-formed connection request, {count} x (0xff, 0)")
                for attempt in range(args.connect):
                    payload = stp.build_connection_request(
                        target_constant, target_var, [stp.FILLER] * count, location,
                        network_id=0, player_infos=infos, ack_id=attempt + 1)
                    got = await ask(payload, stp.PROTOCOL, f"connect#{attempt}", timeout=2.0)
                    name = ("silence" if got is None
                            else stp.RESULT_NAMES.get(got, f"result {got}"))
                    print(f"[tx]   attempt {attempt}: {name}")
                    record(rec="connect", attempt=attempt, result=got)
                    if got == stp.RESULT_ACCEPTED:
                        print("\n[cx] *** ACCEPTED INTO THE MESH ***")
                        d = stp.parse_connection_response(st["reply_payload"])
                        record(rec="accepted", response=st["reply_payload"].hex())
                        print(f"[cx] the host's {len(d['protocols'])} protocols: "
                              + ", ".join(f"{p:#04x}v{v}" for p, v in d["protocols"]))
                        print(f"[cx] host location {d['location']['private']} "
                              f"constant={d['location']['constant_id']:#018x} "
                              f"variable={d['location']['variable_id']:#010x}")
                        print(f"[cx] network id {d['network_id']:#010x}  "
                              f"players {d['players']}  {d['player_names']}")
                        # a connection response is repeated every 500 ms until it is acknowledged,
                        # so this is what turns an acceptance into a finished handshake
                        print(f"[cx] acking the acceptance, ack id {d['ack_id']:#010x}")
                        for _ in range(args.ack_repeats):
                            sock.sendto(wrap(keys, our_mac, args.src_var, dst_var, next_nonce(),
                                             stp.build_ack(d["ack_id"]), stp.PROTOCOL,
                                             port=stp.PORT_UNRELIABLE), (dst_ip, PIA_PORT))
                            record(rec="tx_station_ack", t=time.monotonic() - t0,
                                   ack_id=d["ack_id"])
                            await trio.sleep(0.25)
                        st["phase"] = "station-connected"
                        print("[cx] station handshake closed")
                        if not args.join:
                            print("[cx] listening for what the mesh says next")
                            break
                        # THE MESH JOIN. Six bytes, station index 253 - "not in a mesh yet" -
                        # retransmitted every 500 ms; Pia gives up after ten seconds.
                        print(f"\n[tx] --- mesh join request (protocol {mp.PROTOCOL:#04x} v3)")
                        for attempt in range(args.join):
                            st["phase"] = f"join#{attempt}"
                            st["reply"] = None
                            st["reply_payload"] = None
                            st["waiter"] = trio.Event()
                            req = mp.build_join_request(attempt + 1)
                            sock.sendto(wrap(keys, our_mac, args.src_var, dst_var, next_nonce(),
                                             req, mp.PROTOCOL, port=mp.PORT_UNRELIABLE),
                                        (dst_ip, PIA_PORT))
                            record(rec="tx_join", t=time.monotonic() - t0, attempt=attempt,
                                   request=req.hex())
                            with trio.move_on_after(2.0):
                                await st["waiter"].wait()
                            st["waiter"] = None
                            if st["reply_payload"] is None:
                                print(f"[tx]   join {attempt}: silence")
                                continue
                            print(f"[tx]   join {attempt}: answered")
                            break
                        st["phase"] = "joined"
                        break
                    await trio.sleep(args.connect_gap)
                st["phase"] = "after"
                return

            if not args.identify:
                return

            async def probe(pid, version, var_id=None, src_var=None, tries=3):
                """One version probe. A reply is guaranteed now, so silence is a lost packet and
                gets retried rather than read as a match (sp28)."""
                loc = location
                if var_id is not None:
                    loc = stp.station_location(our_ip, PIA_PORT, our_constant, var_id, our_service)
                for _ in range(tries):
                    st["phase"] = f"id={pid:#04x} v={version}"
                    payload = stp.build_connection_request(
                        target_constant, target_var, stp.version_probe(pid, version, count), loc,
                        network_id=0, player_infos=infos, ack_id=1)
                    got = await ask(payload, stp.PROTOCOL, st["phase"], src_var=src_var)
                    if got is None:
                        continue                       # a lost packet, not an answer
                    if isinstance(got, tuple):
                        record(rec="odd_reply", pid=pid, version=version, reply=repr(got))
                        return None, got
                    return stp.read_version(got), got
                return None, None

            ids = ([int(x, 0) for x in args.ids.split(",")] if args.ids
                   else list(range(256)) if args.sweep_ids else list(stp.KNOWN_PROTOCOL_IDS))
            print(f"\n[tx] --- probing {len(ids)} protocol id(s) at version 1")
            registered, unregistered, unknown = {}, [], []
            for pid in ids:
                d, raw = await probe(pid, 1)
                if d is None:
                    unknown.append(pid)
                    print(f"[tx]   {pid:#04x}  NO ANSWER after retries")
                    continue
                if d == "lower":                       # expected < 1, so it is 0: not registered
                    unregistered.append(pid)
                    continue
                if d == "equal":
                    registered[pid] = 1
                    print(f"[tx]   {pid:#04x}  version 1")
                    continue
                search = stp.VersionSearch(lo=2, first=2)   # expected > 1, bisect the rest
                while not search.done:
                    dd, _ = await probe(pid, search.next_version())
                    if dd is None:
                        break
                    search.feed(dd)
                registered[pid] = search.found
                print(f"[tx]   {pid:#04x}  version {search.found} ({search.probes} probes)")
            st["result"] = {"count": count, "registered": registered,
                            "unregistered": len(unregistered), "unknown": unknown}
            record(rec="protocols", count=count, registered=registered,
                   unregistered=unregistered, unknown=unknown)
            print(f"[cx] {len(registered)} registered, {len(unregistered)} not, "
                  f"{len(unknown)} unanswered - the console said {count}")

            print("\n[cx] --- confirming each version against both neighbours")
            for pid, v in sorted(registered.items()):
                if v is None:
                    continue
                below, _ = await probe(pid, max(0, v - 1))
                above, _ = await probe(pid, min(255, v + 1))
                ok = below == "higher" and above == "lower"
                print(f"[cx]   {pid:#04x} v{v}: v-1 {below}, v+1 {above}"
                      f"  {'CONFIRMED' if ok else 'NOT CONFIRMED'}")
                record(rec="confirm", pid=pid, version=v, below=below, above=above, ok=ok)

            if args.vary_var and registered:
                # result 7 is the SECOND stage refusing (0x0154fcfc -> 0x11c0f), and what it tests
                # is whether our variable id is already in an array at session+0x3b8. So vary it.
                pid, v = sorted((k, x) for k, x in registered.items() if x)[0]
                print(f"\n[cx] --- what the second stage refuses: {pid:#04x} v{v}, "
                      f"varying the variable id")
                for label, var_id, src in (("as sent", args.src_var, None),
                                           ("location id + 1", args.src_var + 1, None),
                                           ("location id = 2", 2, None),
                                           ("location id = host's", target_var, None),
                                           ("location id = 0x7fffffff", 0x7FFFFFFF, None),
                                           ("packet src_var differs", args.src_var, 0x5150A001)):
                    _, raw = await probe(pid, v, var_id=var_id, src_var=src)
                    name = stp.RESULT_NAMES.get(raw, raw)
                    print(f"[cx]   {label:26s} var={var_id:#010x} -> {name}")
                    record(rec="vary_var", label=label, var_id=var_id, src_var=src, result=raw)

            st["phase"] = "after"

        with trio.move_on_after(args.hold):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver)
                nursery.start_soon(sender)

        print(f"\n[cx] {st['updates']} update session(s), {len(st['replies'])} station-protocol "
              f"reply/replies")
        if st["result"]:
            reg = st["result"]["registered"]
            print(f"[cx] the console said it registers {st['result']['count']} protocols, "
                  f"and {len(reg)} answered:")
            for pid, v in sorted(reg.items()):
                print(f"[cx]   {pid:#04x}  version {v}")
            if st["result"]["unknown"]:
                print(f"[cx] unanswered: {[hex(x) for x in st['result']['unknown']]}")
        elif st["replies"]:
            print("[cx] PASS: the console answered on the mesh station protocol")
        else:
            print("[cx] silence throughout")
        record(rec="end", updates=st["updates"], replies=len(st["replies"]), result=st["result"])
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
    ap.add_argument("--count", type=int, default=None,
                    help="the console's protocol count, if already measured; skips the sweep")
    ap.add_argument("--identify", action="store_true",
                    help="after the count, read each candidate protocol's registered version")
    ap.add_argument("--connect", type=int, default=0, metavar="N",
                    help="send N well-formed connection requests and report what comes back")
    ap.add_argument("--connect-gap", type=float, default=2.0)
    ap.add_argument("--join", type=int, default=0, metavar="N",
                    help="after the station handshake, send up to N mesh join requests")
    ap.add_argument("--ack-repeats", type=int, default=3,
                    help="how many times to ack the acceptance; the console repeats it until acked")
    ap.add_argument("--sweep-ids", action="store_true",
                    help="probe all 256 protocol ids, not only the ones the wiki names")
    ap.add_argument("--ids", default=None, help="a comma-separated list of ids to probe instead")
    ap.add_argument("--vary-var", action="store_true",
                    help="after identifying, vary the variable id to find what result 7 tests")
    ap.add_argument("--min-protocols", type=int, default=0)
    ap.add_argument("--max-protocols", type=int, default=40)
    ap.add_argument("--gap", type=float, default=0.4,
                    help="seconds to wait for a reply; every probe gets one, so this is short")
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
