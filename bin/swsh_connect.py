#!/usr/bin/env python3
"""Answer a Sword/Shield console's station announcement - the first version-4 packet OUT.

Everything sw01 learned came from the console talking: we took a seat in its LDN session and all 484
of its Pia packets authenticated. Nothing of ours has ever been on the wire above LDN. This sends
one message and reads one answer.

WHAT IT SENDS, and why it is the cheapest possible first packet. The console broadcasts a Local
Protocol (0x24) *update session* ten times a second and, on BDSP, repeats it until every station
acknowledges it - so the ack's pass signal needs nothing on the console's screen and nothing above
Pia: THE REBROADCAST STOPS. That is exactly the shape session 46 used to prove a BDSP console
accepts our packets, and Sword's announcement parses field-for-field with the same parser
(`pokeldn.ldn.local_protocol`): version 1, type 0x11, 0x30 fixed bytes, eight 9-byte seats, and the
two seats it lists are 169.254.14.1 (the console, ranking 0) and 169.254.14.2 (us, ranking 1).

THE ONE FIELD WE HAVE TO CHOOSE is the header byte at 0x05. The console sends 0 on every packet of
sw01, and the GCM IV's source-id byte is 0 on every packet too - which is 5.27's rule, where that
IV byte is the low byte of the header's own source id. HYPOTHESIS: the byte at 0x05 IS the source
station, and the IV follows it. So `--station` sets both together, and `--station-sweep` walks the
readings in turn: 0 mirrors the console exactly, 1 is our own seat index in its table. Whichever is
in flight when the rebroadcast stops is the answer, and the log timestamps say which.

Never pass --verbose to a live run (there is none); use --capture. docs/swsh.md, docs/pia.md.
"""
import argparse, json, os, socket, struct, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED):
    sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import (local_protocol as lp, mesh_protocol as mesh, pia4, reliable4,
                        reliable5, rtt_protocol as rtt, station4,
                        station_protocol as stp)
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.swsh import COMM_ID, PASSPHRASE, PIA_PORT, packet_iv, session_keys

SCENE_ACCEPTING = 60001           # what sw01 recorded; kept for the log line, not a gate


def _expand(spec):
    """"0-15" or "5,1,0" -> a list of strings, so a sweep and a single value are the same flag."""
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part[1:]:
            lo, _, hi = part.partition("-")
            out += [str(v) for v in range(int(lo, 0), int(hi, 0) + 1)]
        elif part:
            out.append(part)
    return out


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


def wrap(keys, our_mac, our_constant, nonce8, payload, protocol, station, port=0,
         message_flags=pia4.MESSAGE_FLAGS, destination=0):
    """A version-4 packet carrying one message, framed the way the console frames its own.

    The station byte goes in the header AND in the IV's source-id byte - the coupling 5.27 makes
    and the reason `--station` moves one knob rather than two.

    `destination` is a station BITMAP, not an index: every 0x58 and 0x7C message the console sent us
    in sw29 carries 2, the bit for station index 1, which is our seat. Ours back at it is 1.
    """
    body = pia4.build_message(payload, protocol=protocol, source=our_constant, port=port,
                              message_flags=message_flags, destination=destination)
    iv = packet_iv(keys, our_mac, nonce8, source_id=station)
    return pia4.build_packet(keys.session_key, iv, body, station=station, nonce8=nonce8)


async def main_async(args):
    keys_file = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    nets = await ldn.scan(keys_file, phyname=phy,
                          channels=[int(c) for c in args.channels.split(",")],
                          dwell_time=args.dwell)
    want = int(args.comm_id, 16) if args.comm_id else COMM_ID
    for n in nets:
        print(f"[cx] saw comm_id=0x{n.local_communication_id:016x} ch={n.channel} "
              f"scene={n.scene_id} {n.num_participants}/{n.max_participants}")
    net = next((n for n in nets if n.local_communication_id == want), None)
    if net is None:
        print("[cx] target not on the air - is the console on Y-Comm -> Link Trade -> local RIGHT "
              "NOW? It stops advertising a minute or so after a seat is released.")
        return 3
    if net.num_participants >= net.max_participants:
        print("[cx] the session is FULL, no seat to take")
        return 5
    keys = session_keys(net)
    print(f"[cx] target ssid={net.ssid.hex()} ch={net.channel} scene={net.scene_id} "
          f"app_version={net.app_version}")
    # The scene id is RECORDED, not acted on. sw01/sw02/sw03 associated against 60001 and a scan
    # during the sw04-sw09 failures showed 65535, but no failing run's own advertisement was ever
    # read, so what the field means here is UNKNOWN and nothing branches on it.
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

    record(rec="target", comm_id=net.local_communication_id, channel=net.channel,
           scene_id=net.scene_id, ssid=net.ssid.hex(),
           application_data=bytes(getattr(net, "application_data", b"") or b"").hex(),
           session_key=keys.session_key.hex(), session_param=keys.session_param)

    async with ldn.connect(param) as network:
        info = network.info()
        parts = list(getattr(info, "participants", []) or [])
        host = parts[0] if parts else None
        host_ip = getattr(host, "ip_address", None) or "169.254.14.1"
        host_mac = bytes(getattr(host, "mac_address", b"") or b"")
        ours = next((p for p in parts[1:] if getattr(p, "connected", False)), None)
        our_ip = getattr(ours, "ip_address", None) or host_ip.rsplit(".", 1)[0] + ".2"
        our_mac = bytes(getattr(ours, "mac_address", b"") or b"")
        bcast = our_ip.rsplit(".", 1)[0] + ".255"
        print(f"[cx] *** ASSOCIATED *** us={our_ip} ({our_mac.hex()}) "
              f"host={host_ip} ({host_mac.hex()})")
        if len(our_mac) != 6 or len(host_mac) != 6:
            print("[cx] a MAC is missing - the IV and the constant ids cannot be built")
            return 6
        our_constant = stp.ldn_constant_id(our_mac)
        host_constant = stp.ldn_constant_id(host_mac)
        print(f"[cx] our constant id  {our_constant:#018x}")
        print(f"[cx] host constant id {host_constant:#018x}  (from its MAC)")
        record(rec="seat", us=our_ip, our_mac=our_mac.hex(), host=host_ip,
               host_mac=host_mac.hex(), our_constant=our_constant, host_constant=host_constant)

        sock = make_socket(args.ifname)
        t0 = time.monotonic()
        st = {"seq": None, "host_var": None, "host_constant_seen": None, "last_update": None,
              "updates": 0, "phase": "listen", "station": None, "acks": 0,
              "rx": 0, "undecrypted": 0, "other": [], "answer": None, "station_replies": 0,
              "requests": 0, "requests_in": 0, "responses": 0, "their_request": None,
              "our_variable_id": 0, "responses_in": 0, "acks_out": 0,
              "joins_out": 0, "mesh_in": 0, "join_response": None, "mesh_acks": 0,
              "updates_mesh": 0, "rtt_in": 0, "rtt_out": 0, "reliable_in": 0,
              "reliable_seqs": set(), "reliable_acks": 0, "acked_through": 0,
              "reliable_last": None, "broadcast_in": 0}

        accepted = trio.Event()           # set when the station handshake closes, which is the
                                          # only moment a mesh join has ever been answered
        nonce = int.from_bytes(os.urandom(8), "big")

        def next_nonce():
            nonlocal nonce
            nonce = (nonce + 1) & ((1 << 64) - 1)
            return nonce.to_bytes(8, "big")

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
                if not pia4.is_pia4(data):
                    record(rec="rx_nonpia", t=now, src=addr[0], data=data[:64].hex())
                    continue
                st["rx"] += 1
                h = pia4.PiaHeader4.parse(data)
                iv = packet_iv(keys, host_mac, h.nonce8, source_id=h.station)
                pt = pia4.decrypt_payload(keys.session_key, iv, pia4.ciphertext(data), h.tag)
                if pt is None:
                    st["undecrypted"] += 1
                    record(rec="rx_undecrypted", t=now, src=addr[0], station=h.station,
                           raw=data[:48].hex())
                    continue
                msgs = pia4.parse_packet(pt)
                record(rec="rx", t=now, src=addr[0], station=h.station, session=h.session_id,
                       phase=st["phase"],
                       msgs=[{k: (sorted(v) if k == "inherited" else
                                  v.hex() if isinstance(v, (bytes, bytearray)) else v)
                              for k, v in m.items()} for m in msgs])
                for f in msgs:
                    body = f["payload"]
                    if f["protocol"] == lp.PROTOCOL and len(body) >= 2 \
                            and body[1] == lp.UPDATE_SESSION:
                        us = lp.parse_update_session(body)
                        st["last_update"], st["updates"] = now, st["updates"] + 1
                        st["host_var"] = us.host_variable_id
                        st["host_constant_seen"] = int.from_bytes(us.host_constant_id, "little")
                        if st["seq"] != us.sequence_id:
                            st["seq"] = us.sequence_id
                            seats = ", ".join(f"{n.ip}:{n.port}#{n.ranking}" for n in us.occupied)
                            print(f"[rx] t={now:6.2f} update session seq={us.sequence_id} "
                                  f"host_var={us.host_variable_id:#010x} seats: {seats}")
                    elif f["protocol"] == lp.PROTOCOL:
                        kind = body[1] if len(body) >= 2 else None
                        st["other"].append((now, "local", kind, body.hex()))
                        print(f"[rx] t={now:6.2f} local protocol type {kind:#04x}, "
                              f"{len(body)} B, phase {st['phase']}")
                    elif f["protocol"] == station4.PROTOCOL:
                        kind, result = station4.parse_reply(body)
                        st["station_replies"] += 1
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        st["other"].append((now, "station", kind, body.hex()))
                        verdict = station4.RESULT_NAMES.get(result, result)
                        print(f"\n[rx] t={now:6.2f} *** STATION PROTOCOL 0x14, type {kind}, "
                              f"result {verdict} *** phase {st['phase']}\n     {body.hex()}")
                        if kind == station4.CONNECTION_REQUEST and args.respond:
                            try:
                                got = station4.parse_incoming_request(body)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                continue
                            them = got["station"]
                            st["their_request"] = got
                            if st["requests_in"] == 0:
                                print(f"[rx]     it is addressed to our constant "
                                      f"{got['constant_id']:#018x} and our variable "
                                      f"{got['variable_id']:#010x}; its own location says "
                                      f"{them['ip']}:{them['port']} constant "
                                      f"{them['constant_id']:#018x} variable "
                                      f"{them['variable_id']:#010x} nat "
                                      f"{them['nat_flags']}/{them['nat_location']} ack "
                                      f"{got['ack_id']}")
                            st["requests_in"] += 1
                            # WHOSE ids belong in the response is a deduction, so alternate the two
                            # readings across retransmits and let the console pick.
                            mine = args.respond_with == "ours" or (
                                args.respond_with == "both" and st["responses"] % 2)
                            cid = our_constant if mine else them["constant_id"]
                            vid = (st["our_variable_id"] if mine else them["variable_id"])
                            reply = station4.build_connection_response(args.respond_result, cid, vid)
                            pkt = wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                       station4.PROTOCOL, args.connect_station_first)
                            sock.sendto(pkt, (addr[0], PIA_PORT))
                            st["responses"] += 1
                            record(rec="tx_response", t=now, ids="ours" if mine else "theirs",
                                   response=reply.hex())
                            print(f"[tx]     answered with result {args.respond_result}, "
                                  f"{'our' if mine else 'their'} ids: {reply.hex()}")
                        elif kind == station4.CONNECTION_RESPONSE and args.respond:
                            # THE CONSOLE ACCEPTED US AND REPEATS UNTIL IT IS ACKED - the same
                            # pass/fail the update session gives, one layer up. Two readings of
                            # which u32 belongs in the ack, alternated across the retransmits.
                            st["responses_in"] += 1
                            if result == 0 and st["responses_in"] == 1:
                                print(f"[rx]     *** ACCEPTED INTO THE MESH *** {len(body)} B")
                            if result == 0:
                                accepted.set()
                            trailing = station4.ack_id_of(body)
                            theirs = (st["their_request"] or {}).get("station", {}).get(
                                "variable_id", 0)
                            use_trailing = st["acks_out"] % 2 == 0
                            ack_id = trailing if use_trailing else theirs
                            ack = station4.build_ack(ack_id)
                            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), ack,
                                             station4.PROTOCOL, args.connect_station_first),
                                        (addr[0], PIA_PORT))
                            st["acks_out"] += 1
                            record(rec="tx_station_ack", t=now, ack_id=ack_id,
                                   reading="trailing" if use_trailing else "their_variable_id")
                            if st["acks_out"] <= 4:
                                print(f"[tx]     acked with {ack_id:#010x} "
                                      f"({'the message tail' if use_trailing else 'their variable id'})")
                    elif f["protocol"] == mesh.PROTOCOL:
                        # 0x18. The join response carries the whole mesh; version 4's entries are
                        # 64 bytes with the index at 0x3E, which is the one thing that differs from
                        # BDSP's (mesh_protocol, main.bin 0x017b4830).
                        st["mesh_in"] += 1
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        kind, kname = mesh.parse_message(body)
                        st["other"].append((now, "mesh", kind, body.hex()))
                        print(f"\n[rx] t={now:6.2f} *** MESH PROTOCOL 0x18, {kname} *** "
                              f"{len(body)} B, phase {st['phase']}\n     {body[:64].hex()}")
                        if kind == mesh.JOIN_RESPONSE:
                            try:
                                got = mesh.parse_join_response(body, version4=True)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                got = None
                            if got and got.get("refused"):
                                print(f"[rx]     REFUSED, reason {got['reason']}")
                            elif got:
                                print(f"[rx]     stations={got['stations']} "
                                      f"host_index={got['host_index']} "
                                      f"our_index={got['our_index']} "
                                      f"fragment {got['fragment_index'] + 1}/{got['fragments']} "
                                      f"counter={got['update_counter']}")
                                for e in got["station_info"]:
                                    loc = e.get("location") or {}
                                    print(f"[rx]       index {e['station_index']}: "
                                          f"{loc.get('private')} constant "
                                          f"{loc.get('constant_id', 0):#018x}")
                            st["join_response"] = st["join_response"] or (now, body.hex())
                            record(rec="rx_join_response", t=now, parsed=got, raw=body.hex())
                        elif kind == mesh.UPDATE_MESH:
                            st["updates_mesh"] += 1
                            try:
                                got = mesh.parse_update_mesh(body, version4=True)
                            except (IndexError, ValueError) as e:
                                print(f"[rx]     could not parse it: {e}")
                                continue
                            if st["updates_mesh"] == 1:
                                print(f"[rx]     stations={got['stations']} "
                                      f"host_index={got['host_index']} "
                                      f"counter={got['update_counter']} "
                                      f"({len(body)} B; {mesh.UPDATE_MESH_SIZE_V4} is the full "
                                      f"eight seats at version 4)")
                            record(rec="rx_update_mesh", t=now, parsed=got, raw=body.hex())
                        reply = mesh.ack_for(body)
                        if reply and args.join:
                            proto, payload = reply
                            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                             proto, args.connect_station_first),
                                        (addr[0], PIA_PORT))
                            st["mesh_acks"] += 1
                            record(rec="tx_mesh_ack", t=now, protocol=proto, ack=payload.hex())
                            print(f"[tx]     acked it on {proto:#04x}: {payload.hex()}")
                    elif f["protocol"] == rtt.PROTOCOL and args.answer_rtt:
                        # 0x58. Sixteen bytes at version 4, not BDSP's thirteen, and the answer
                        # echoes every byte we do not read (rtt_protocol.response_for_v4).
                        st["rtt_in"] += 1
                        try:
                            got = rtt.parse_v4(body)
                        except ValueError as e:
                            print(f"[rx] t={now:6.2f} 0x58 {len(body)} B, not the shape read off "
                                  f"the binary: {e}")
                            continue
                        if got["kind"] != rtt.REQUEST:
                            continue
                        reply = rtt.response_for_v4(body)
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                         rtt.PROTOCOL, args.connect_station_first,
                                         message_flags=rtt.MESSAGE_FLAGS,
                                         destination=args.data_destination),
                                    (addr[0], PIA_PORT))
                        st["rtt_out"] += 1
                        record(rec="tx_rtt", t=now, timestamp=got["timestamp"], reply=reply.hex())
                        if st["rtt_out"] <= 3:
                            print(f"[rx] t={now:6.2f} 0x58 RTT request, timestamp "
                                  f"{got['timestamp']:#014x}")
                            print(f"[tx]     answered: {reply.hex()}")
                    elif f["protocol"] == reliable5.PROTOCOL and args.ack_reliable:
                        # 0x7C. reliable5 was written for BDSP and reads version 4 unchanged.
                        # THE PASS SIGNAL IS THE RETRANSMITS STOPPING, the same shape as every
                        # other layer here: the console repeats a sequence until it is acked.
                        st["reliable_in"] += 1
                        try:
                            got = reliable5.parse(body)
                        except ValueError as e:
                            print(f"[rx] t={now:6.2f} 0x7c {len(body)} B unreadable: {e}")
                            continue
                        st["reliable_last"] = now
                        if not (got["flags"] & reliable5.FLAG_APPLICATION_DATA):
                            try:
                                shape = reliable4.parse_ack_payload(got["payload"])
                                shape = [e for e in shape if e["stream_id"] != 0xFF]
                            except ValueError as e:
                                shape = f"not the version-4 shape: {e}"
                            print(f"\n[rx] t={now:6.2f} *** 0x7c ACK FROM THE CONSOLE *** "
                                  f"{len(got['payload'])} B: {shape}")
                            record(rec="rx_reliable_ack", t=now, raw=got["payload"].hex())
                            continue
                        st["reliable_seqs"].add(got["sequence_id"])
                        through = reliable5.contiguous_through(st["reliable_seqs"],
                                                              st["acked_through"])
                        if through == st["acked_through"]:
                            continue                  # nothing new is contiguous; do not re-ack
                        st["acked_through"] = through
                        if st["reliable_acks"] == 0:
                            print(f"\n[rx] t={now:6.2f} 0x7c seq {got['sequence_id']} stream "
                                  f"{got['stream_id']} flags {got['flag_names']} payload "
                                  f"{got['payload'].hex()}")
                        ack = reliable4.build_ack_message(
                            through + 1, stream_id=got["stream_id"],
                            slots=args.ack_slots, lowest_pending=args.ack_lowest_pending)
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), ack,
                                         reliable5.PROTOCOL, args.connect_station_first,
                                         message_flags=reliable5.MESSAGE_FLAGS,
                                         destination=args.data_destination),
                                    (addr[0], PIA_PORT))
                        st["reliable_acks"] += 1
                        record(rec="tx_reliable_ack", t=now, through=through, ack=ack.hex())
                        print(f"[tx]     acked 0x7c through seq {through} "
                              f"(ack id {through + 1}): {ack.hex()}")
                    elif f["protocol"] == reliable4.BROADCAST_PROTOCOL:
                        # 0x80, BroadcastReliableProtocol. Every one of these is zlib compressed
                        # (pia4.MESSAGE_FLAG_ZLIB) and pia4 has already decompressed it; read raw
                        # its 42 bytes look like a message claiming a payload of 0x6260.
                        st["broadcast_in"] += 1
                        try:
                            got = reliable4.parse_broadcast_message(body)
                        except ValueError as e:
                            print(f"[rx] t={now:6.2f} 0x80 {len(body)} B unreadable: {e}")
                            continue
                        if st["broadcast_in"] == 1:
                            print(f"\n[rx] t={now:6.2f} *** 0x80 BROADCAST RELIABLE *** "
                                  f"{'ACK' if got['is_ack'] else 'DATA'} seq {got['sequence_id']:#06x} "
                                  f"lowest_pending {got['lowest_pending']} to "
                                  f"{[hex(d) for d in got['destinations']]}")
                            if got["is_ack"]:
                                ents = reliable4.parse_ack_payload(got["payload"])
                                live = [e for e in ents if e["ack_id"]]
                                print(f"[rx]     acking slots "
                                      f"{[e['slot'] for e in live]} at id "
                                      f"{sorted({e['ack_id'] for e in live})}")
                        record(rec="rx_broadcast", t=now, parsed={
                            k: (v if not isinstance(v, bytes) else v.hex())
                            for k, v in got.items() if k != "payload"})
                    else:
                        # ANYTHING on a protocol the console has never used with us is the finding
                        st["other"].append((now, "proto", f["protocol"], body.hex()))
                        st["answer"] = st["answer"] or (now, st["phase"], f["protocol"])
                        print(f"\n[rx] t={now:6.2f} *** PROTOCOL {f['protocol']:#04x}, "
                              f"{len(body)} B, phase {st['phase']} *** {body[:32].hex()}")

        async def sender():
            await trio.sleep(args.listen_first)
            if st["seq"] is None:
                print("[cx] no update session seen - the console is not hosting a Pia network. "
                      "Nothing to answer; holding so the capture says so.")
                return
            dst = host_ip if args.unicast else bcast
            stopped = False
            for station in [int(s, 0) for s in args.station_sweep.split(",")]:
                st["phase"], st["station"] = f"ack:station={station}", station
                print(f"\n[tx] acking seq={st['seq'] + args.seq_delta} "
                      f"{'(THE CONTROL: not a sequence the console sent) ' if args.seq_delta else ''}"
                      f"with station byte {station} -> {dst} "
                      f"(the IV's source id follows it)")
                deadline = time.monotonic() + args.ack_seconds
                while time.monotonic() < deadline:
                    payload = lp.build_ack(st["seq"] + args.seq_delta)
                    pkt = wrap(keys, our_mac, our_constant, next_nonce(), payload,
                               lp.PROTOCOL, station)
                    sock.sendto(pkt, (dst, PIA_PORT))
                    st["acks"] += 1
                    record(rec="tx_ack", t=time.monotonic() - t0, seq=st["seq"] + args.seq_delta,
                           station=station, dst=dst, packet=pkt.hex())
                    await trio.sleep(args.period)
                    quiet = time.monotonic() - t0 - (st["last_update"] or 0)
                    if st["updates"] > 3 and quiet > args.quiet_for:
                        print(f"\n[tx] *** THE REBROADCAST STOPPED *** ({quiet:.2f}s quiet, "
                              f"station byte {station}, {st['acks']} acks sent)")
                        st["phase"] = f"stopped:station={station}"
                        stopped = True
                        break
                if stopped:
                    break                 # the ack landed; do NOT leave the sender, the sweep is
                                          # what the association was spent on. sw10 returned here
                                          # and threw a working seat away.
                print(f"[tx] station byte {station}: the rebroadcast did not stop "
                      f"({st['updates']} update sessions so far)")
            if args.connect:
                await connect_sweep(dst)
            st["phase"] = "hold"

        async def connect_sweep(dst):
            """Sweep the one pair of bytes a version-4 connection request cannot know in advance.

            [1] and [0x10] are the TARGET's nat flags and nat location, and we have never seen the
            console's station location - it travels on the Mesh Protocol, which has not spoken to
            us. A mismatch is silence and a match is the console's first word on 0x14, which is
            exactly how BDSP's protocol count was measured."""
            variable_id = args.src_var if args.src_var is not None else \
                int.from_bytes(os.urandom(4), "big")
            st["our_variable_id"] = variable_id
            location = stp.station_location(our_ip, PIA_PORT, our_constant, variable_id,
                                            stp.ldn_service_variable_id(our_mac))
            target_constant = st["host_constant_seen"] or stp.ldn_constant_id(host_mac)
            target_var = st["host_var"] or 0
            flags = [int(x, 0) for x in _expand(args.nat_flags)]
            locs = [int(x, 0) for x in _expand(args.nat_location)]
            print(f"\n[tx] connection requests on 0x14 -> {host_ip}: target constant "
                  f"{target_constant:#018x} variable {target_var:#010x}, our variable id "
                  f"{variable_id:#010x}")
            print(f"[tx] sweeping platform {args.request_platform} x "
                  f"message flags {args.request_flags} x station "
                  f"{args.connect_station} x nat flags {flags} x nat location {locs}, "
                  f"{args.request_gap:.2f}s apart")
            platforms = [int(x, 0) for x in _expand(args.request_platform)]
            framings = [int(x, 0) for x in _expand(args.request_flags)]
            stations = [int(x, 0) for x in _expand(args.connect_station)]
            for mf in framings:
                for stn in stations:
                    for pf in platforms:
                      for nl in locs:
                        for nf in flags:
                            st["phase"] = (f"connect:platform={pf},msgflags={mf:#04x},"
                                           f"station={stn},nat={nf}/{nl}")
                            payload = station4.build_connection_request(
                                target_constant, target_var, location, nat_flags=nf,
                                nat_location=nl, platform=pf,
                                with_variable_id=not args.no_variable_id)
                            pkt = wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                       station4.PROTOCOL, stn, message_flags=mf)
                            sock.sendto(pkt, (host_ip if args.request_unicast else bcast,
                                              PIA_PORT))
                            st["requests"] += 1
                            record(rec="tx_request", t=time.monotonic() - t0, nat_flags=nf,
                                   nat_location=nl, message_flags=mf, station=stn, platform=pf,
                                   request=payload.hex())
                            await trio.sleep(args.request_gap)
                            if st["station_replies"]:
                                print(f"[tx] a 0x14 reply arrived at platform={pf} "
                                      f"msgflags={mf:#04x} station={stn} nat={nf}/{nl} - stopping "
                                      f"the sweep so the capture is unambiguous")
                                return
            if st["station_replies"]:
                return
            print(f"[tx] {st['requests']} requests, no 0x14 reply. Silence is what a wrong "
                  f"constant id, a wrong count or a malformed location all look like.")

        async def joiner():
            """The six-byte join request, once the station handshake has closed.

            THE ORDER IS THE FINDING BDSP LEFT: nothing is answered on 0x18 until the console has
            accepted us as a station on 0x14, so this waits for that acceptance rather than firing
            on a timer. Pia's own joiner retransmits every 500 ms and gives up after ten seconds,
            and the response is acked on 0x14 - the mesh protocol never acks with a mesh message
            (`mesh_protocol.ack_for`, and version 4 builds the same eight bytes at 0x017c6dd0).
            """
            if not args.join:
                return
            with trio.move_on_after(args.join_wait):
                await accepted.wait()
            if not accepted.is_set():
                print(f"\n[tx] no station acceptance in {args.join_wait:.0f}s - not joining. "
                      f"A join before the handshake closes is silence, and an unclassifiable run.")
                return
            ack_id = args.join_ack_id if args.join_ack_id is not None else \
                int.from_bytes(os.urandom(4), "big")
            payload = mesh.build_join_request(ack_id, station_index=args.join_station_index)
            st["phase"] = "join"
            print(f"\n[tx] *** MESH JOIN on 0x18 *** {payload.hex()} (ack id {ack_id:#010x}, "
                  f"calling ourselves {args.join_station_index}) -> {host_ip}, every "
                  f"{args.join_gap:.2f}s for {args.join_seconds:.0f}s")
            deadline = time.monotonic() + args.join_seconds
            while time.monotonic() < deadline and st["join_response"] is None:
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), payload,
                                 mesh.PROTOCOL, args.connect_station_first,
                                 port=args.join_port),
                            (host_ip, PIA_PORT))
                st["joins_out"] += 1
                record(rec="tx_join", t=time.monotonic() - t0, ack_id=ack_id,
                       port=args.join_port, request=payload.hex())
                await trio.sleep(args.join_gap)
            if st["join_response"] is None:
                print(f"[tx] {st['joins_out']} join requests, nothing back on 0x18. "
                      f"{st['mesh_in']} mesh messages in all.")
            st["phase"] = "hold"

        async with trio.open_nursery() as nursery:
            nursery.start_soon(receiver)
            nursery.start_soon(joiner)
            await sender()
            await trio.sleep(args.hold)
            nursery.cancel_scope.cancel()

        print(f"\n[cx] === {st['rx']} packets in, {st['undecrypted']} that did not decrypt, "
              f"{st['updates']} update sessions, {st['acks']} acks out, "
              f"{st['requests']} connection requests, {st['station_replies']} messages on 0x14, "
              f"{st['requests_in']} of them requests, {st['responses_in']} connection responses "
              f"in, {st['responses']} responses out, {st['acks_out']} station acks out, "
              f"{st['joins_out']} join requests out, {st['mesh_in']} messages on 0x18, "
              f"{st['mesh_acks']} mesh acks out, {st['rtt_in']} RTT in / {st['rtt_out']} answered, "
              f"{st['reliable_in']} reliable in over "
              f"{len(st['reliable_seqs'])} sequence ids, {st['reliable_acks']} acked "
              f"(through {st['acked_through']}), {st['broadcast_in']} on 0x80")
        if st["answer"]:
            now, phase, proto = st["answer"]
            print(f"[cx] FIRST TRAFFIC ON A NEW PROTOCOL: {proto:#04x} at t={now:.2f} in {phase}")
        record(rec="end", updates=st["updates"], acks=st["acks"], rx=st["rx"],
               undecrypted=st["undecrypted"], phase=st["phase"], answer=st["answer"],
               requests=st["requests"], station_replies=st["station_replies"],
               requests_in=st["requests_in"], responses=st["responses"],
               responses_in=st["responses_in"], acks_out=st["acks_out"],
               joins_out=st["joins_out"], mesh_in=st["mesh_in"],
               mesh_acks=st["mesh_acks"], join_response=st["join_response"],
               rtt_in=st["rtt_in"], rtt_out=st["rtt_out"], reliable_in=st["reliable_in"],
               reliable_acks=st["reliable_acks"], acked_through=st["acked_through"],
               reliable_seqs=sorted(st["reliable_seqs"]),
               broadcast_in=st["broadcast_in"])
    if cap:
        cap.close()
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None, help="hex; defaults to Sword's 0x0100abf008968000")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11")
    ap.add_argument("--dwell", type=float, default=1.5)
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--listen-first", type=float, default=6.0,
                    help="seconds of listening before the first packet out, so the capture holds "
                         "the console's own rate to compare against")
    ap.add_argument("--station-sweep", default="0,1",
                    help="readings of the header byte at 0x05, in order; the IV's source id "
                         "follows each one")
    ap.add_argument("--ack-seconds", type=float, default=12.0, help="per reading")
    ap.add_argument("--period", type=float, default=0.1)
    ap.add_argument("--quiet-for", type=float, default=1.5,
                    help="seconds without an update session that count as the rebroadcast stopping "
                         "- the console sends ten a second, so this is fifteen missed")
    ap.add_argument("--seq-delta", type=int, default=0,
                    help="THE CONTROL. Ack a sequence id the console never sent: a rebroadcast "
                         "that carries on under --seq-delta 1 is what attributes a stop under 0 to "
                         "the ack's CONTENT rather than to our merely having transmitted")
    ap.add_argument("--connect", action="store_true",
                    help="after the ack, sweep the version-4 connection request on protocol 0x14")
    ap.add_argument("--nat-flags", default="0-15", help="values for byte [1], list or LO-HI")
    ap.add_argument("--nat-location", default="0-3", help="values for byte [0x10]")
    ap.add_argument("--request-gap", type=float, default=0.25,
                    help="seconds between requests; the console answered BDSP's in 40 ms")
    ap.add_argument("--connect-station", default="0",
                    help="values for the header byte at 0x05 on the requests, and their IV source "
                         "id; list or LO-HI")
    ap.add_argument("--respond", action="store_true",
                    help="answer a connection request the CONSOLE sends us with a connection "
                         "response. sw20 drew one and had nothing to say back")
    ap.add_argument("--respond-result", type=int, default=0, help="0 is accepted")
    ap.add_argument("--respond-with", default="theirs", choices=["theirs", "ours", "both"],
                    help="whose constant and variable id go in the response's two id fields - a "
                         "deduction, so 'both' alternates them across the retransmits")
    ap.add_argument("--request-platform", default="9",
                    help="values for the platform byte at [2]. 9 is the real one; ANY other value "
                         "is answered with a connection response rather than dropped, which is the "
                         "probe for whether our message reaches the 0x14 handler at all")
    ap.add_argument("--request-flags", default="0x09",
                    help="values for the MESSAGE flags byte. 0x09 is what the console puts on its "
                         "own Local Protocol messages; BDSP's station requests carry 0x11")
    ap.add_argument("--request-unicast", action="store_true", default=True,
                    help="send the requests to the console rather than the broadcast address")
    ap.add_argument("--request-broadcast", dest="request_unicast", action="store_false",
                    help="send them to the broadcast address instead")
    ap.add_argument("--src-var", type=lambda s: int(s, 0), default=None,
                    help="our own station variable id; fresh random when omitted, because a reused "
                         "one is 'already one of my stations' on BDSP")
    ap.add_argument("--no-variable-id", action="store_true",
                    help="clear [3], which makes the console skip the variable-id comparison")
    ap.add_argument("--unicast", action="store_true",
                    help="send to the console rather than the broadcast address")
    ap.add_argument("--join", action="store_true",
                    help="after the station handshake closes, send the Mesh Protocol (0x18) join "
                         "request and ack whatever comes back")
    ap.add_argument("--join-wait", type=float, default=45.0,
                    help="how long to wait for the station acceptance before giving up on joining")
    ap.add_argument("--join-seconds", type=float, default=10.0,
                    help="how long to retransmit the join request; Pia's own joiner gives up at 10")
    ap.add_argument("--join-gap", type=float, default=0.5,
                    help="Pia retransmits an unacknowledged join request every 500 ms")
    ap.add_argument("--join-port", type=int, default=mesh.PORT_UNRELIABLE,
                    help="the Pia port the join travels on; the update mesh uses the reliable one")
    ap.add_argument("--join-station-index", type=lambda s: int(s, 0),
                    default=mesh.STATION_INDEX_INVALID,
                    help="byte [1]. 0xFD is what 0x017c1700 compares against; anything else is the "
                         "instrument that says the handler was reached")
    ap.add_argument("--join-ack-id", type=lambda s: int(s, 0), default=None,
                    help="fixed ack id for the join request; random when omitted")
    ap.add_argument("--answer-rtt", action="store_true",
                    help="answer the console's 0x58 RTT requests. Sixteen bytes at version 4, and "
                         "the reply echoes the seven bytes nothing has read yet")
    ap.add_argument("--ack-reliable", action="store_true",
                    help="acknowledge the 0x7C reliable window. The pass signal is the "
                         "retransmits STOPPING and the sequence ids moving on")
    ap.add_argument("--ack-slots", default=None,
                    type=lambda v: None if v in ("", "all") else [int(x, 0) for x in v.split(",")],
                    help="which of the 32 ack slots to fill; \"all\" (the default) fills every "
                         "one, because only the slot at some station index is read and whose index "
                         "it is has not been settled. \"0\" is the console, \"1\" is us")
    ap.add_argument("--ack-lowest-pending", type=lambda s: int(s, 0), default=1,
                    help="the header's own 'lowest sequence pending ack'. We have sent nothing on "
                         "this protocol, so 1 (the next id we would use) and 0 are both readings; "
                         "the console itself sends 1 while waiting on its own first message")
    ap.add_argument("--data-destination", type=lambda s: int(s, 0), default=1,
                    help="the station BITMAP on 0x58 and 0x7C. The console sends 2 to us, station "
                         "index 1; 1 is the bit for station 0, which is the console")
    ap.add_argument("--hold", type=float, default=30.0)
    ap.add_argument("--capture", default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.connect_station_first = int(_expand(args.connect_station)[0], 0)
    if os.geteuid() != 0:
        build_parser().error("must run as root (LDN needs the raw radio)")
    try:
        return trio.run(main_async, args)
    except BaseException as e:
        print(f"[cx] {type(e).__name__}: {e}")
        for sub in getattr(e, "exceptions", ()) or ():
            print(f"[cx]   caused by: {type(sub).__name__}: {sub}")
        cleanup()
        raise


if __name__ == "__main__":
    sys.exit(main())
