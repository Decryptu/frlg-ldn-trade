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
from pokeldn.bdsp import COMM_ID, PASSPHRASE, PIA_PORT, room, session_keys
from pokeldn.ldn import (local_protocol as lp, mesh_protocol as mp, reliable5 as rl,
                        rtt_protocol as rtt, station_protocol as stp)
from pokeldn.ldn.pia5 import (PiaHeader5, is_pia5, ciphertext, gcm_iv, ldn_nonce_crc,
                              build_message, pad_payload, parse_messages, encrypt_payload,
                              decrypt_payload)
from pokeldn.ldn.transport import find_ap_phy

UNRELIABLE_PROTOCOL = 0x68        # the console's own list; its payload is the game's live state
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
         destination=lp.BROADCAST, message_flags=lp.MESSAGE_FLAGS, packet_id=0):
    """A Pia message in a Pia packet, in the framing session 46 proved the console accepts."""
    body = pad_payload(build_message(payload, protocol=protocol, port=port,
                                     message_flags=message_flags, destination=destination))
    iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, our_mac), src_var, nonce8)
    ct, tag = encrypt_payload(keys.session_key, iv, body)
    return PiaHeader5(dst_var=dst_var, src_var=src_var, packet_id=packet_id, footer_size=0,
                      nonce8=nonce8, tag=tag[:8], encrypted=True).pack() + ct


async def main_async(args):
    keys_file = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    nets = await ldn.scan(keys_file, phyname=phy,
                          channels=[int(c) for c in args.channels.split(",")],
                          dwell_time=args.dwell)
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
              "reply_payload": None, "result": None,
              "join_responses": 0, "last_join_response": None, "join_response": None,
              "rtt_requests": 0, "rtt_answers": 0, "reliable": 0, "unreliable": 0,
              "join_acks": 0, "dst_ip": bcast, "dst_var": 0,
              "rel_max_seq": 0, "rel_streams": set(), "rel_control": [],
              "rel_handshaken": False, "rel_acks": 0, "their_position": None, "their_ack_id": 0,
              "requests": 0, "request_answers": 0, "last_request": None, "talk_answers": 0,
              "state_requests": 0, "their_state": None, "their_recruiting": 0,
              "reserves_sent": 0, "reserve_results": 0, "match_wait_sent": 0,
              "reserve_accepted": False, "room_done": False}

        nonce = int.from_bytes(os.urandom(8), "big")

        def next_nonce():
            nonlocal nonce
            nonce = (nonce + 1) & ((1 << 64) - 1)
            return nonce.to_bytes(8, "big")

        def decode(data, addr, now):
            h = PiaHeader5.parse(data)
            iv = gcm_iv(ldn_nonce_crc(keys.network_id_le, host_mac), h.src_var, h.nonce8)
            # the footer - one halfword per recipient - is NOT covered by the tag, and leaving it
            # in is what made 111 of sp36's packets look undecryptable
            pt = decrypt_payload(keys.session_key, iv, ciphertext(data, h.footer_size), h.tag)
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
                            # the host repeats this every 500 ms until it is acknowledged, so the
                            # count and the time of the last one are the pass signal for the ack.
                            # Ack from HERE, not from the sender: sp36's sender broke out of the
                            # join loop on the station ack for our join REQUEST, which arrives
                            # first, and had no join response in hand when it looked.
                            st["join_responses"] += 1
                            st["last_join_response"] = now
                            st["join_response"] = m.payload
                            print(f"[rx]     {mp.parse_join_response(m.payload)}")
                            ack = mp.ack_for(m.payload) if args.join_ack else None
                            if ack is not None:
                                proto, payload = ack
                                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"],
                                                 next_nonce(), payload, proto,
                                                 port=stp.PORT_UNRELIABLE),
                                            (st["dst_ip"], PIA_PORT))
                                st["join_acks"] += 1
                                record(rec="tx_mesh_ack", t=now, protocol=proto,
                                       ack_id=mp.read_ack_id(m.payload), payload=payload.hex())
                                print(f"[tx]     acked it on protocol {proto:#04x}, ack id "
                                      f"{mp.read_ack_id(m.payload):#010x} "
                                      f"({st['join_acks']} so far)")
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
                    elif m.protocol == rtt.PROTOCOL:
                        st["rtt_requests"] += 1
                        reply = rtt.response_for(m.payload) if args.rtt else None
                        d = rtt.parse(m.payload) if len(m.payload) >= rtt.SIZE else None
                        if reply is not None:
                            sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"],
                                             next_nonce(), reply, rtt.PROTOCOL, port=rtt.PORT),
                                        (st["dst_ip"], PIA_PORT))
                            st["rtt_answers"] += 1
                        record(rec="rtt", t=now, phase=st["phase"], payload=m.payload.hex(),
                               parsed=d, answered=reply is not None)
                        if st["rtt_requests"] <= 3 or st["rtt_requests"] % 20 == 0:
                            print(f"[rx] t={now:6.2f} RTT {d['name'] if d else '?'} "
                                  f"#{st['rtt_requests']}"
                                  + (f" -> answered {st['rtt_answers']}" if reply else ""))
                    elif m.protocol == rl.PROTOCOL:
                        # THE RELIABLE PROTOCOL, and its payload is the game. Read it; nothing
                        # acknowledges it yet, which is why the console repeats each message.
                        st["reliable"] += 1
                        try:
                            d = rl.parse(m.payload)
                        except ValueError as exc:
                            print(f"[rx] t={now:6.2f} RELIABLE, unparsed: {exc}")
                            record(rec="reliable_bad", t=now, payload=m.payload.hex(),
                                   error=str(exc))
                            continue
                        body = (rl.parse_ack_payload(d["payload"]) if d["is_ack"]
                                and len(d["payload"]) >= 2 else None)
                        print(f"\n[rx] t={now:6.2f} *** RELIABLE seq {d['sequence_id']} "
                              f"stream {d['stream_id']} pending {d['lowest_pending']} "
                              f"[{'|'.join(d['flag_names'])}] {d['payload_size']} B ***")
                        print(f"[rx]     {d['payload'].hex(' ')}\n")
                        if d["flags"] & rl.FLAG_APPLICATION_DATA:
                            st["rel_max_seq"] = max(st["rel_max_seq"], d["sequence_id"])
                            st["rel_streams"].add(d["stream_id"])
                            g = room.parse(d["payload"]) if len(d["payload"]) >= 3 else None
                            if g:
                                record(rec="game_message", t=now, data_id=g["data_id"],
                                       name=g["name"], fields=g.get("fields"),
                                       payload=d["payload"].hex())
                            if g and "join" in g:
                                st["their_position"] = g["join"]
                                print(f"[rx] t={now:6.2f} {g['name']}: avatar "
                                      f"{g['join']['avatar_id']} at "
                                      f"({g['join']['x']:.2f}, {g['join']['z']:.2f}) "
                                      f"facing {g['join']['rot_y']}")
                            elif g and g.get("fields") is not None:
                                print(f"[rx] t={now:6.2f} {g['name']}: {g['fields']}")
                            elif g:
                                print(f"[rx] t={now:6.2f} {g['name']}, "
                                      f"{g['length']} B{' (opaque)' if g['opaque'] else ''}")
                            if g and g["data_id"] == room.REQUEST and g.get("fields"):
                                # THE CONSOLE HAS BEEN ASKING US FOR A MESSAGE SINCE THE FIRST JOIN.
                                # `RequestData.RequestDataID` names a data id, and 0x23 is the one
                                # it answers itself. Nothing this project sent had ever answered it.
                                st["requests"] += 1
                                st["last_request"] = g["fields"]["RequestDataID"]
                                if g["fields"]["RequestDataID"] == room.STATE:
                                    # A REQUEST FOR NetCharacterStateData IS THE GAME SAYING IT
                                    # CREATED A CHARACTER FROM US. Across thirteen runs that sent
                                    # anything, the four where an avatar appeared on the screen all
                                    # asked for it and the six where nothing appeared never did,
                                    # over 265 sends. It is the first signal in the CAPTURE that
                                    # says what previously only the screen could.
                                    if not st["state_requests"]:
                                        print(f"\n[rx] t={now:6.2f} *** IT ASKED FOR "
                                              f"NetCharacterStateData - THE GAME HAS CREATED A "
                                              f"CHARACTER FROM US ***\n")
                                    st["state_requests"] += 1
                                if args.answer_requests:
                                    await answer_the_request(g, now, via="reliable")
                            if g and g["data_id"] == room.STATE and g.get("fields"):
                                note_their_state(g["fields"], now)
                            if g and g["data_id"] == room.TALK_RESERVE_RESULT and g.get("fields"):
                                st["reserve_results"] += 1
                                # IsCanTalk READS BACKWARDS: 0 accepts, 1 declines. sp79 was
                                # answered 0 and sp80 answered 1, and sp80 sent its follow-up
                                # anyway - two seconds later the game crashed.
                                st["reserve_accepted"] = g["fields"].get("IsCanTalk") == 0
                                print(f"\n[rx] t={now:6.2f} *** IT ANSWERED OUR APPROACH - "
                                      f"NetDataTalkReserveResultData {g['fields']} ***\n")
                                record(rec="reserve_result", t=now, fields=g["fields"])
                            if (g and g["data_id"] == room.TALK_RESERVE
                                    and args.answer_talk):
                                # THE PLAYER PRESSED A ON OUR CHARACTER. sp70 got this message for
                                # the first time and answered nothing, and the player's own
                                # character froze until the game was rebooted - the talk is a
                                # request/response and the console blocks on ours.
                                await answer_the_talk(now)
                            if args.reliable_auto_ack and st["rel_handshaken"]:
                                ack = rl.build_ack_message(st["rel_max_seq"] + 1,
                                                           stream_id=d["stream_id"])
                                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"],
                                                 next_nonce(), ack, rl.PROTOCOL, port=rl.PORT),
                                            (st["dst_ip"], PIA_PORT))
                                st["rel_acks"] += 1
                        else:
                            # a control message - reset, reset ack or a bulk ack. THIS is the
                            # positive signal: an answer, not the absence of one
                            st["rel_control"].append((now, d["flags"], m.payload.hex()))
                            if len(d["payload"]) >= 2:
                                try:
                                    body = rl.parse_ack_payload(d["payload"])
                                except ValueError:
                                    body = None
                                if body and body["entries"]:
                                    st["their_ack_id"] = max(
                                        st["their_ack_id"],
                                        max(e["ack_id"] for e in body["entries"]))
                            print(f"[rx] t={now:6.2f} *** RELIABLE CONTROL "
                                  f"[{'|'.join(d['flag_names']) or 'no flags'}] "
                                  f"{m.payload.hex()} ***")
                        record(rec="reliable", t=now, phase=st["phase"], flags=d["flags"],
                               stream=d["stream_id"], seq=d["sequence_id"],
                               pending=d["lowest_pending"], payload=d["payload"].hex(),
                               is_ack=d["is_ack"],
                               ack={"count": body["count"]} if body else None)
                    elif m.protocol == UNRELIABLE_PROTOCOL:
                        # THE GAME'S LIVE STATE. These are the packets sp36 could not read: they
                        # carry a footer and the footer is not covered by the GCM tag.
                        st["unreliable"] += 1
                        record(rec="unreliable", t=now, phase=st["phase"], port=m.port,
                               dest=m.destination, payload=m.payload.hex())
                        # EVERY unreliable payload in the archive is a whole game message - 968 of
                        # them, three types, no exceptions - and the five-byte one this project
                        # called a keepalive is NetCharacterStateData. So parse them here as well,
                        # which is where the 0x04 request lives: all 55 of them came in on THIS
                        # protocol and none on the reliable one.
                        g = room.parse(m.payload) if len(m.payload) >= room.HEADER_SIZE else None
                        if g and not g["truncated"] and g["length"] + room.HEADER_SIZE == len(m.payload):
                            record(rec="game_message", t=now, via="unreliable",
                                   data_id=g["data_id"], name=g["name"], fields=g.get("fields"),
                                   payload=m.payload.hex())
                            if g["data_id"] == room.REQUEST and g.get("fields"):
                                st["requests"] += 1
                                st["last_request"] = g["fields"]["RequestDataID"]
                                if g["fields"]["RequestDataID"] == room.STATE:
                                    if not st["state_requests"]:
                                        print(f"\n[rx] t={now:6.2f} *** IT ASKED FOR "
                                              f"NetCharacterStateData - THE GAME HAS CREATED A "
                                              f"CHARACTER FROM US ***\n")
                                    st["state_requests"] += 1
                                if args.answer_requests:
                                    await answer_the_request(g, now, via="unreliable")
                            if g["data_id"] == room.STATE and g.get("fields"):
                                note_their_state(g["fields"], now)
                        else:
                            g = None
                        if st["unreliable"] <= 5 or st["unreliable"] % 25 == 0:
                            print(f"[rx] t={now:6.2f} UNRELIABLE #{st['unreliable']} "
                                  f"({len(m.payload)} B) "
                                  + (f"{g['name']} {g.get('fields', '')}" if g
                                     else m.payload[:32].hex(' ')))
                    else:
                        print(f"[rx] t={now:6.2f} protocol {m.protocol} port {m.port} "
                              f"({len(m.payload)} B) - something new")

        async def sweep_reliable_ack():
            """Ack the reliable data, sweeping the two bytes the binary does not spell out.

            The bulk-ack payload's shape is the serialiser's, byte for byte (main.bin 0x0159718c,
            size 0x0159716c = 2 + 21n). Two fields are not read: the payload's first byte - the
            consumer tests its bit 0 at 0x01596c98 and sets a flag at protocol+0x738, so it is a
            bitfield and not a version - and the entry's second halfword, which comes from the
            window's own field 0x50 and is filed per station at protocol+0x7b8.

            The verdict is free and fast: an ack that lands stops the retransmission, and the
            console is retransmitting several times a second. Silence IS the pass here, so each
            candidate is only believed after the traffic has been flowing right up to it.
            """
            if not st["rel_max_seq"]:
                print("[cx] no reliable data to ack yet")
                return
            ack_id, streams = st["rel_max_seq"], sorted(st["rel_streams"]) or [0]

            # sp40 swept the two unread bytes and sp41/sp42 swept five framings, all refused. The
            # binary says why, and it is neither: on a RESET the byte at offset 1 is a COUNTER, and
            # 0x0159fa24 rejects it outright when it EQUALS the value the console holds for us,
            # 0x0159fa4c when it is not exactly one more. Every reset we sent carried 0. So sweep
            # that byte, in the framing everything else already works in.
            def send(msg, label):
                st["phase"] = label
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                 rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))

            def state():
                return (st["reliable"], len(st["rel_control"]), st["rel_max_seq"])

            # THE PROBE WITH A POSITIVE SIGNAL: send DATA, not an ack. A sliding window that
            # accepts an application message has to acknowledge it, and that acknowledgement is a
            # reliable message with the application-data flag clear - something we can see. An ack
            # of our own, by contrast, is only ever judged on silence, and silence is what every
            # sweep so far has produced. Sequence ids sweep because the console's receive window
            # expects one particular next id and we have never been told which.
            print(f"\n[tx] --- application data, sweeping the sequence id. The console must "
                  f"acknowledge one it accepts, so the answer is a REPLY and not a silence.")
            for seq in range(args.reliable_sweep):
                payload = bytes.fromhex("12000123")     # its own four bytes, echoed back
                msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                       | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                       seq, len(payload), lowest_pending=seq) + payload)
                before = state()
                send(msg, f"data seq={seq}")
                record(rec="tx_reliable_data", t=time.monotonic() - t0, seq=seq,
                       message=msg.hex())
                await trio.sleep(1.0)
                control = st["rel_control"][before[1]:]
                print(f"[tx]   DATA  seq={seq}: "
                      + (f"*** ANSWERED {[hex(c[1]) for c in control]} ***" if control
                         else "no control message back"))
                record(rec="reliable_data_result", seq=seq,
                       control=[c[1] for c in control], data=state()[0] - before[0])
                if control:
                    print(f"\n[cx] *** THE CONSOLE ACKNOWLEDGED OUR DATA at sequence {seq} ***")
                    for _, flags, raw in control:
                        d = rl.parse(bytes.fromhex(raw))
                        if d["is_ack"] and len(d["payload"]) >= 2:
                            print(f"[cx]     {rl.parse_ack_payload(d['payload'])}")
                    print("\n[tx] --- and now its own data, acked back in the same shape")
                    ok = await ack_the_console()
                    st["rel_handshaken"] = ok
                    if ok and args.room_walk:
                        await walk_the_room(seq + 1)
                    return

            print("[cx] the data probe was never answered; not acking blind")

        async def answer_the_talk(now):
            """Answer a NetDataTalkReserveData, on the reliable stream it arrived on."""
            reply = room.build_talk_reserve_result(can_talk=args.can_talk,
                                                   is_recruitment=args.recruiting,
                                                   emoticon_state=args.state)
            seq = st["their_ack_id"]
            if not seq:
                record(rec="talk_unanswered_no_seq", t=now)
                return
            msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                   | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                   seq, len(reply), lowest_pending=seq) + reply)
            sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                             rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
            st["talk_answers"] += 1
            print(f"\n[tx] t={now:6.2f} *** IT ASKED TO TALK - answered "
                  f"NetDataTalkReserveResultData at seq {seq}: {reply.hex(' ')} ***\n")
            record(rec="talk_answered", t=now, seq=seq, reply=reply.hex())
            # AND WHATEVER THE RUN WANTS TO SAY NEXT. The console parks in TalkState GREETING and
            # waits to be advanced; which message does it is not decided by anything readable, so
            # this is the sweep handle. One --after-talk is one message, in order, on the reliable
            # stream, at the sequence id the console is asking for at the time.
            for spec in args.after_talk:
                await trio.sleep(args.after_talk_gap)
                data_id, _, body_hex = spec.partition(":")
                payload = room.build(int(data_id, 0), bytes.fromhex(body_hex))
                seq = st["their_ack_id"]
                if not seq:
                    record(rec="after_talk_no_seq", t=now, spec=spec)
                    continue
                m = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                     | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                     seq, len(payload), lowest_pending=seq) + payload)
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), m,
                                 rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                now2 = time.monotonic() - t0
                print(f"[tx] t={now2:6.2f}   after-talk {room.name(payload[0])} at seq {seq}: "
                      f"{payload.hex(' ')}")
                record(rec="after_talk_sent", t=now2, spec=spec, seq=seq, message=payload.hex())

        async def answer_the_request(message, now, via="reliable"):
            """Answer a NetRequestData with the message it names, ON THE PROTOCOL IT ARRIVED ON.

            THE STREAM DECIDES THE STREAM. All 4333 requests for 0x23 came in on the reliable
            protocol and all 55 for 0x04 on the unreliable one, with no crossover in nineteen runs,
            and each is where the console puts its own answer - so replying on the other one would
            be a framing mistake of exactly the kind sp40-sp43 spent four runs on.

            On the reliable stream the sequence id is taken FRESH: the window is shared with the
            console's own sends and anything below its ack id is discarded in silence (sp53). One
            send, no retransmission - the console repeats the request, so a lost answer costs
            nothing and the next request is another chance.
            """
            reply = room.answer(message, state=args.state, is_recruitment=args.recruiting,
                                match_wait=args.match_wait)
            wanted = message["fields"]["RequestDataID"]
            if reply is None:
                print(f"[tx] t={now:6.2f} it asked for {room.name(wanted)} and this table cannot "
                      f"build one")
                record(rec="request_unanswerable", t=now, requested=wanted)
                return
            if via == "unreliable":
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), reply,
                                 UNRELIABLE_PROTOCOL, port=0, destination=0xFFFFFFFF,
                                 message_flags=rl.MESSAGE_FLAGS), (st["dst_ip"], PIA_PORT))
                st["request_answers"] += 1
                print(f"[tx] t={now:6.2f} answered its request for {room.name(wanted)} on the "
                      f"unreliable stream: {reply.hex(' ')}")
                record(rec="request_answered", t=now, requested=wanted, via=via,
                       reply=reply.hex())
                return
            seq = st["their_ack_id"]
            if not seq:
                record(rec="request_unanswered_no_seq", t=now, requested=wanted)
                return
            msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                   | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                   seq, len(reply), lowest_pending=seq) + reply)
            sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                             rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
            st["request_answers"] += 1
            print(f"[tx] t={now:6.2f} answered its request for {room.name(wanted)} at seq {seq}: "
                  f"{reply.hex(' ')}")
            record(rec="request_answered", t=now, requested=wanted, via=via, seq=seq,
                   reply=reply.hex())

        async def walk_the_room(seq):
            """Put a position of OUR OWN into the room, and see whether the game draws it.

            Everything until now has been below the game. A position message is the first thing this
            project has sent that the GAME could act on, so the signal is the console's SCREEN, not
            the capture. It walks a small square around wherever the console's own avatar last was,
            so anything that appears is next to the player rather than across the room.
            """
            here = st["their_position"] or {"x": 0.0, "z": 0.0}
            print(f"\n[tx] --- WALKING: {args.room_walk} positions around "
                  f"({here['x']:.2f}, {here['z']:.2f}). WATCH THE CONSOLE'S SCREEN.")
            # sp47 put four avatars in the room from four distinct positions, so the next question
            # is what the game thinks the IDENTITY is. A LINE answers it: one avatar walking says
            # the identity is the station, a trail of them says it is the position.
            async def send_reliable(payload, seq, label, tries=12):
                """Send one reliable message and RETRANSMIT until the console's ack covers it.

                sp50 sent a single join and nothing appeared; sp47 and sp48 sent twenty-odd and the
                room filled up. One message gets one chance, and this project had never retransmitted
                anything - which is the entire point of a sliding window. The console's ack id is a
                positive signal, so this says whether the join LANDED, separately from whether the
                game drew it.
                """
                # THE ACK ID IS THE SEQUENCE THE CONSOLE WANTS NEXT, and anything below it is
                # discarded in silence. sp53 is the proof: its ack sat at 13, we sent 1 through 20,
                # and EXACTLY EIGHT avatars appeared - 13 through 20. sp47 and sp48 filled a room by
                # spanning the number without knowing it; sp50 to sp52 sent one message below it and
                # got nothing at all. So take the sequence id from the ack, every time.
                # THE SEQUENCE SPACE IS SHARED WITH THE CONSOLE'S OWN SENDS. Its ack id is the
                # next number in the whole window, not a count of what we have sent: sp53's ack sat
                # at 13 while its own data was at 12, we sent 1 through 20, and exactly the eight
                # from 13 up became avatars. So take the id FRESH on every attempt - a value read
                # before its last message is already stale, which is how sp55 sent a join at 1 into
                # a window that wanted 16.
                for attempt in range(tries):
                    seq = st["their_ack_id"]
                    if not seq:
                        await trio.sleep(0.4)
                        continue
                    msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                           | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                           seq, len(payload), lowest_pending=seq) + payload)
                    st["phase"] = f"{label} seq={seq} try={attempt}"
                    sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                     rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                    record(rec="tx_reliable_data", t=time.monotonic() - t0, label=label, seq=seq,
                           attempt=attempt, message=msg.hex())
                    await trio.sleep(0.4)
                    if st["their_ack_id"] > seq:
                        print(f"[tx]   {label}: landed at seq {seq} on try {attempt + 1} "
                              f"(their ack id -> {st['their_ack_id']})")
                        record(rec="reliable_data_acked", label=label, seq=seq,
                               attempts=attempt + 1, ack_id=st["their_ack_id"])
                        return True
                print(f"[tx]   {label} seq={seq}: never acked in {tries} tries "
                      f"(their ack id {st['their_ack_id']})")
                record(rec="reliable_data_unacked", label=label, seq=seq, ack_id=st["their_ack_id"])
                return False

            if args.room_pattern == "fixed":
                # A BURST OF JOINS, ALL AT ONE SPOT, each at the sequence id the console is asking
                # for. Whatever lands stacks in one place, so the screen shows one avatar rather
                # than a crowd - and then the movement updates have something unambiguous to move.
                x0, z0 = here["x"] + args.join_offset_x, here["z"] + args.join_offset_z
                # AND WHERE, WHICH IS NOT FREE. The offset has always been +2.0 on x, which is one
                # side of the player - so a player standing against the wall on that side gets a
                # character spawned THROUGH it. sp80: the user watched ours appear out of bounds
                # and the game crashed shortly after. There is no collision for us and no map here,
                # so the offset is the run's to choose and the player should stand clear.
                # WHO SHE IS, not where. `OpcManager.CreateCharaData(ANetData<JoinData>)` builds a
                # CharaData{stationIndex, assetName, colorId, avatarId, sexId} out of THIS message:
                # avatarId indexes `UnionCharacterTable.SheetSheet1{ID, AssetName}` and the asset
                # name is what `OpLoadCharacter` loads from "persons/field/". GetSexId and
                # GetNpcColorId hang off the same value. Every run this project has ever done sent
                # avatar 8, which is why every character has been the same girl.
                join = room.build_join(x0, 0.0, z0, rot_y=90,
                                       avatar_id=args.join_avatar, color_id=args.join_color)
                print(f"[tx]   {args.room_walk} joins, ALL at ({x0:.2f}, {z0:.2f}), "
                      f"avatar {args.join_avatar} colour {args.join_color}")
                for i in range(args.room_walk):
                    seq = st["their_ack_id"]
                    if not seq:
                        await trio.sleep(0.4)
                        continue
                    msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                           | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                           seq, len(join), lowest_pending=seq) + join)
                    st["phase"] = f"burst seq={seq}"
                    sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                     rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                    record(rec="tx_reliable_data", t=time.monotonic() - t0, label="burst", seq=seq,
                           attempt=i, message=msg.hex())
                    if i % 4 == 0:
                        print(f"[tx]     join {i} at seq {seq}")
                    await trio.sleep(0.4)
                print(f"\n[tx]   --- now moving whatever is standing there, to the RIGHT")
                # sp66 WALKED OUT OF THE ROOM. Sixty steps of 0.93 is 55.8 units, so the character
                # crossed the floor, was pushed back by the game's own collision, moonwalked and
                # left through the far wall - all of it off the only instrument there is, the
                # screen. A walk has to END INSIDE THE ROOM to be watched.
                for i in range(args.room_walk_steps):
                    # AT THE CONSOLE'S OWN SPEED. Measured over 80 of its NetPosData messages, a
                    # real player covers 0.93 units per message every 0.41 s; this used to send
                    # 0.1 units every 0.35 s with the twelve points 0.008 apart, which is a ninth
                    # of walking pace and is the whole of what the screen showed as a stutter.
                    stride = args.room_walk_stride
                    x, x_next = x0 + stride * i, x0 + stride * (i + 1)
                    body = room.build_pos(room.pos_span((x, z0), (x_next, z0), 90))
                    sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(),
                                     body, UNRELIABLE_PROTOCOL, port=0,
                                     destination=0xFFFFFFFF, message_flags=rl.MESSAGE_FLAGS),
                                (st["dst_ip"], PIA_PORT))
                    record(rec="tx_pos", t=time.monotonic() - t0, x=x, z=z0, message=body.hex())
                    if i % 15 == 0:
                        print(f"[tx]     pos {i}: ({x:.2f}, {z0:.2f})")
                    await trio.sleep(args.room_walk_period)

                if args.send_card:
                    # THE PROBE: the game draws a BODY for us and has no record to hang on it -
                    # no name, no dialogue, the default model. `NetDataTranerCardData` is the
                    # message that carries what a player LOOKS like (fashionId, bodyType,
                    # genderid) and no console in this project's 42 captures has ever sent one,
                    # so there is no template and the layout is opendpr's alone. It goes on the
                    # RELIABLE stream, which is where a join goes, and it is retransmitted until
                    # the console's ack covers it - so the capture says whether it LANDED
                    # separately from whether the screen changed.
                    card = room.build_trainer_card(fashion_id=args.card_fashion,
                                                   body_type=args.card_body,
                                                   gender_id=args.card_gender,
                                                   trainer_id=args.card_trainer_id)
                    print(f"\n[tx]   --- TRAINER CARD: fashion {args.card_fashion}, body "
                          f"{args.card_body}, gender {args.card_gender}, id "
                          f"{args.card_trainer_id}. WATCH HER APPEARANCE.")
                    await send_reliable(card, st["their_ack_id"], "trainer-card")
                st["room_done"] = True
                return

            if args.room_pattern == "move":
                # ONE join, then NetPosData on the UNRELIABLE stream - which is how the game moves a
                # player it already knows about. sp47/sp48 spawned a crowd because every message we
                # sent was a JOIN.
                x0, z0 = here["x"] + 1.5, here["z"]
                print(f"[tx]   ONE join at ({x0:.2f}, {z0:.2f}), retransmitted until it is acked")
                landed = await send_reliable(room.build_join(x0, 0.0, z0, rot_y=90), seq, "join")
                if not landed:
                    print("[cx] the join never landed; nothing after it can mean anything")
                    return
                print(f"[tx]   ONE avatar should be standing at ({x0:.2f}, {z0:.2f}) now")
                # and now move it, batched the way the console batches: twelve points a message
                for i in range(args.room_walk):
                    # THE TWELVE POINTS SPAN THE STRIDE. sp57 sent them 0.012 apart inside a 0.15
                    # step, so the avatar crept through a twelfth of the way and then jumped the
                    # rest when the next message arrived. A message describes where the player HAS
                    # BEEN since the last one, so its points have to reach the next one's first.
                    stride = args.room_walk_stride
                    x, x_next = x0 + stride * i, x0 + stride * (i + 1)
                    pts = room.pos_span((x, z0), (x_next, z0), 90)
                    body = room.build_pos(pts)
                    sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(),
                                     body, UNRELIABLE_PROTOCOL, port=0,
                                     destination=0xFFFFFFFF, message_flags=rl.MESSAGE_FLAGS),
                                (st["dst_ip"], PIA_PORT))
                    record(rec="tx_pos", t=time.monotonic() - t0, x=x, z=z0, message=body.hex())
                    if i % 8 == 0:
                        print(f"[tx]   pos {i}: ({x:.2f}, {z0:.2f})")
                    await trio.sleep(args.room_walk_gap)
                return

            square = [(1.0, 0.0, 90), (0.0, 1.0, 180), (-1.0, 0.0, 270), (0.0, -1.0, 0)]
            for i in range(args.room_walk):
                if args.room_pattern == "square":
                    dx, dz, angle = square[i % len(square)]
                elif args.room_pattern == "fixed":
                    dx, dz, angle = 2.0, 0.0, 270
                else:                                   # "line": step away, a quarter unit at a time
                    dx, dz, angle = 1.0 + i * 0.25, 0.0, 90
                payload = room.build_join(here["x"] + dx, 0.0, here["z"] + dz, rot_y=angle)
                msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                       | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                       seq + i, len(payload), lowest_pending=seq + i) + payload)
                st["phase"] = f"walk {seq + i}"
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                 rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                record(rec="tx_position", t=time.monotonic() - t0, seq=seq + i,
                       x=here["x"] + dx, z=here["z"] + dz, angle=angle, message=msg.hex())
                print(f"[tx]   position seq={seq + i}: "
                      f"({here['x'] + dx:.2f}, {here['z'] + dz:.2f}) facing {angle}")
                await trio.sleep(args.room_walk_gap)

        async def ack_the_console(stream_id=0):
            """Ack the console's own reliable data, in the shape it acked ours with (sp44)."""
            for delta in (1, 0, 2):
                ack_id = st["rel_max_seq"] + delta
                msg = rl.build_ack_message(ack_id, stream_id=stream_id)
                before = st["reliable"]
                st["phase"] = f"ack {ack_id}"
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                 rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                record(rec="tx_reliable_ack", t=time.monotonic() - t0, ack_id=ack_id,
                       message=msg.hex())
                await trio.sleep(args.reliable_ack_wait)
                got = st["reliable"] - before
                print(f"[tx]   ACK   up to {ack_id}: {got} reliable message(s) after it"
                      + ("   *** THE RETRANSMIT STOPPED ***" if got == 0 else ""))
                record(rec="reliable_ack_result", ack_id=ack_id, after=got)
                if got == 0:
                    print(f"\n[cx] *** THE CONSOLE'S RELIABLE DATA IS ACKED, up to {ack_id} ***")
                    return True
            return False

        async def sender():
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
                # KEEP WAITING PAST AN ACK. The console acknowledges our request before it answers
                # it, and returning on the first reply reads that ack as "something else" and throws
                # a real acceptance away - which is what sp54 did, twice, to a console that had said
                # yes both times.
                deadline = time.monotonic() + (timeout or args.gap)
                while True:
                    with trio.move_on_at(trio.current_time()
                                         + max(0.0, deadline - time.monotonic())):
                        await st["waiter"].wait()
                    got = st["reply"]
                    if got is None:
                        return None                # silence, which is itself an answer
                    kind, result = got
                    if kind == stp.CONNECTION_RESPONSE:
                        st["waiter"] = None
                        return result
                    if time.monotonic() >= deadline:
                        st["waiter"] = None
                        return ("other", kind)     # only after waiting the whole timeout out
                    st["reply"] = None
                    st["waiter"] = trio.Event()

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
            st["dst_ip"], st["dst_var"] = dst_ip, dst_var
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
                    # 4 s, not 2: sp38 caught the console taking over three seconds to accept when
                    # it had a stale station of ours to time out first, and a 2 s wait walked past
                    # the acceptance and left it repeating unanswered
                    got = await ask(payload, stp.PROTOCOL, f"connect#{attempt}",
                                    timeout=args.connect_timeout)
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
                            req = mp.build_join_request(attempt + 1)
                            sock.sendto(wrap(keys, our_mac, args.src_var, dst_var, next_nonce(),
                                             req, mp.PROTOCOL, port=mp.PORT_UNRELIABLE),
                                        (dst_ip, PIA_PORT))
                            record(rec="tx_join", t=time.monotonic() - t0, attempt=attempt,
                                   request=req.hex())
                            # WAIT FOR THE JOIN RESPONSE, not for any reply. The console acks our
                            # join REQUEST on the station protocol and that arrives first, which is
                            # what sp36's join loop mistook for the answer.
                            deadline = time.monotonic() + 2.0
                            while (st["join_response"] is None
                                   and time.monotonic() < deadline):
                                await trio.sleep(0.05)
                            if st["join_response"] is None:
                                print(f"[tx]   join {attempt}: no join response yet")
                                continue
                            print(f"[tx]   join {attempt}: answered")
                            break
                        st["phase"] = "joined"
                        # ACK THE JOIN RESPONSE. It is NOT acked with a mesh message - BDSP's mesh
                        # handlers read the ack id and hand it to a MeshStationProtocol method
                        # (0x0154b984 -> 0x01550324), so what goes out is the station protocol's
                        # eight-byte type-5 ack on 0x14. mesh_protocol.ack_for() is that rule.
                        # the receiver acks every copy as it arrives; watch for them stopping
                        st["phase"] = "join-ack"
                        quiet_for = max(args.quiet_for, 1.5)   # two missed 500 ms repeats
                        deadline = time.monotonic() + args.join_ack_seconds
                        while time.monotonic() < deadline:
                            await trio.sleep(0.25)
                            if st["last_join_response"] is None:
                                continue
                            quiet = (time.monotonic() - t0) - st["last_join_response"]
                            if quiet > quiet_for:
                                print(f"\n[tx] the join response stopped ({quiet:.2f}s quiet after "
                                      f"{st['join_responses']} copies, {st['join_acks']} acked)")
                                break
                        else:
                            print(f"\n[tx] the join response did NOT stop "
                                  f"({st['join_responses']} copies, {st['join_acks']} acked)")
                        record(rec="join_acked", copies=st["join_responses"],
                               acks=st["join_acks"])
                        st["phase"] = "joined"
                        if args.reliable_ack:
                            await sweep_reliable_ack()
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

        def note_their_state(fields, now):
            """The console broadcasts its OWN OpcState, and an emote is visible in it.

            sp78: state 0 until the player opened the Y menu, `state 4 isRecruiment 1` while the
            trade emote was up (t=74 and t=124), back to 0 when it came down. So the run can SEE
            the console become approachable instead of being told.
            """
            was = st["their_state"]
            st["their_state"] = fields
            if fields.get("state") and fields != was:
                st["their_recruiting"] += 1
                print(f"\n[rx] t={now:6.2f} *** THE PLAYER IS ADVERTISING: {fields} - "
                      f"their character is now approachable ***\n")
                record(rec="their_state", t=now, fields=fields)
            elif was and fields.get("state") == 0 and was.get("state"):
                print(f"[rx] t={now:6.2f}   their emote came down ({fields})")
                record(rec="their_state", t=now, fields=fields)

        async def initiate_the_talk():
            """WALK UP TO THEIR CHARACTER. The roles reversed: they advertise, we approach.

            Picking an emote locks the player in place waiting to be interacted with, so when the
            console is the recruiter nothing can happen until someone approaches it - and every run
            to sp78 had us waiting to be approached instead. `UnionStateController$$SwitchTalkStateMine`
            is the approacher's path and it is the one whose messages we have read.

            Sent only once their broadcast state says they are advertising, so the run cannot spend
            its approach on a player who is still walking around.
            """
            # OUR CHARACTER MUST EXIST FIRST. sp80 approached at t=11.02, while the fifteen
            # joins were still going out, and was DECLINED - sp79 approached at t=57.21, after the
            # walk, and was accepted. An approach from a station the game has not drawn yet is not
            # the experiment.
            while not st["room_done"]:
                await trio.sleep(0.5)
            while not st["their_recruiting"]:
                await trio.sleep(0.5)
            await trio.sleep(args.initiate_delay)
            payload = room.build_talk_reserve()
            print(f"\n[tx] --- APPROACHING THEIR CHARACTER: NetDataTalkReserveData "
                  f"{payload.hex(' ')}, retransmitted until their ack covers it")
            for attempt in range(args.initiate_tries):
                seq = st["their_ack_id"]
                if not seq:
                    await trio.sleep(0.4)
                    continue
                msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                       | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                       seq, len(payload), lowest_pending=seq) + payload)
                sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                 rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                st["reserves_sent"] += 1
                now = time.monotonic() - t0
                print(f"[tx] t={now:6.2f}   approach #{attempt + 1} at seq {seq}")
                record(rec="talk_reserve_sent", t=now, seq=seq, attempt=attempt)
                await trio.sleep(args.initiate_gap)
                if st["reserve_results"]:
                    print("[cx] they answered our approach")
                    if not st["reserve_accepted"]:
                        # A REFUSAL IS AN ANSWER, AND IT IS NOT A GO-AHEAD. IsCanTalk 1 is the
                        # console declining; sp80 pushed a TalkData into a declined conversation
                        # and the game crashed. Whatever else was wrong in that run, this path
                        # must not be taken again.
                        print("[cx] *** THEY DECLINED (IsCanTalk 1). Sending NOTHING further. ***")
                        record(rec="approach_declined", t=time.monotonic() - t0)
                        return
                    # AND NOW THE INITIATOR'S OWN NEXT MESSAGE, if the run was given one.
                    # sp76 sent TalkData{CHECK} as the RESPONDER and the console cancelled; CHECK
                    # is what `UnionStateController$$SwitchTalkStateMine` builds, and that is the
                    # path of the player who WALKED UP. sp79 put us in that role for the first
                    # time, so the same message is now being sent by the side that sends it.
                    for spec in args.after_approach:
                        await trio.sleep(args.after_approach_gap)
                        data_id, _, body_hex = spec.partition(":")
                        payload = room.build(int(data_id, 0), bytes.fromhex(body_hex))
                        # NetDataTalkData{talkState: CHECK} CRASHES THE CONSOLE. Its handler
                        # `UnionStateController$$SwitchSpokenStateMine` sends talkState 0 down a
                        # branch that reads systemController->msgWindow and, when that is null -
                        # which it is for a player standing with an emote up - sets x19 = 0 and
                        # dereferences it at 0x1fd5ec0 with no guard. sp80 and sp81 both died on it.
                        if payload[0] == room.TALK and payload[3 + 1:3 + 5] == b"\x00\x00\x00\x00":
                            print("[cx] *** REFUSING to send NetDataTalkData{talkState: CHECK} - "
                                  "it is a null dereference in SwitchSpokenStateMine (sp80, sp81). "
                                  "Use talkState GREETING (1). ***")
                            record(rec="after_approach_refused", spec=spec, reason="talkstate_check")
                            continue
                        seq = st["their_ack_id"]
                        if not seq:
                            record(rec="after_approach_no_seq", spec=spec)
                            continue
                        m = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                             | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                             seq, len(payload), lowest_pending=seq) + payload)
                        sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(),
                                         m, rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                        now2 = time.monotonic() - t0
                        print(f"[tx] t={now2:6.2f}   after-approach {room.name(payload[0])} "
                              f"at seq {seq}: {payload.hex(' ')}")
                        record(rec="after_approach_sent", t=now2, spec=spec, seq=seq)
                    return
            print(f"[cx] {st['reserves_sent']} approaches, no NetDataTalkReserveResultData back")

        async def keep_saying_match_wait():
            """Repeat NetDataIsMatchWaitData{1} for the whole hold.

            sp77 answered the console's REQUEST for 0x23 and that request comes once, between
            t=8.4 and t=9.4, and never again. The player reaches the trade option in the Y menu
            around a minute in, by which time an answer-only run is silent - and the flag the game
            reads is a piece of live state, not a one-off reply. `StartMatch` is gated on
            `cmp w23,#1` [main.bin 0x01fd56e4] behind two null checks on the
            UnionFrontDeskTradeController, which exists only once the player has entered that flow,
            so the message has to still be arriving THEN.
            """
            await trio.sleep(args.match_wait_period)
            sent = 0
            while True:
                seq = st["their_ack_id"]
                if seq:
                    payload = room.build_match_wait(True)
                    msg = (rl.build_header(rl.FLAG_APPLICATION_DATA | rl.FLAG_MESSAGE_START
                                           | rl.FLAG_MESSAGE_END | rl.FLAG_IS_INITIALIZED,
                                           seq, len(payload), lowest_pending=seq) + payload)
                    sock.sendto(wrap(keys, our_mac, args.src_var, st["dst_var"], next_nonce(), msg,
                                     rl.PROTOCOL, port=rl.PORT), (st["dst_ip"], PIA_PORT))
                    st["match_wait_sent"] = sent = sent + 1
                    record(rec="match_wait_repeat", t=time.monotonic() - t0, seq=seq, n=sent)
                    if sent % 10 == 1:
                        print(f"[tx] t={time.monotonic() - t0:6.2f}   isMatchWait=1 #{sent} "
                              f"at seq {seq}")
                await trio.sleep(args.match_wait_period)

        with trio.move_on_after(args.hold):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(receiver)
                nursery.start_soon(sender)
                if args.match_wait and args.match_wait_period > 0:
                    nursery.start_soon(keep_saying_match_wait)
                if args.initiate_talk:
                    nursery.start_soon(initiate_the_talk)

        print(f"\n[cx] {st['updates']} update session(s), {len(st['replies'])} station-protocol "
              f"reply/replies")
        # the three signals this run exists to read, each a count and not a story
        print(f"[cx] mesh join responses {st['join_responses']}, acked {st['join_acks']} "
              f"(a couple is an ack that landed; eighteen is sp36, unacked)")
        print(f"[cx] RTT requests {st['rtt_requests']}, answered {st['rtt_answers']}")
        print(f"[cx] isMatchWait=1 repeats sent {st.get('match_wait_sent', 0)}")
        print(f"[cx] their advertising state seen {st['their_recruiting']} time(s), "
              f"approaches sent {st['reserves_sent']}, answered {st['reserve_results']}")
        print(f"[cx] reliable messages {st['reliable']} "
              f"(a repeat means it is still waiting to be acked)")
        print(f"[cx] unreliable messages {st['unreliable']} - the game's live state")
        print(f"[cx] reliable acks sent {st['rel_acks']}, their last position "
              f"{st['their_position']}")
        # A REQUEST IS A QUESTION ADDRESSED TO US. If it stops being asked, we answered it.
        print(f"[cx] NetRequestData received {st['requests']}"
              + (f" (last for {room.name(st['last_request'])})" if st["last_request"] else "")
              + f", answered {st['request_answers']}")
        # the verdict a capture can give on its own, without asking anyone to watch the screen
        print(f"[cx] requests for NetCharacterStateData {st['state_requests']} - "
              + ("THE GAME CREATED A CHARACTER FROM US" if st["state_requests"]
                 else "nothing we sent became a character"))
        record(rec="counters", join_responses=st["join_responses"],
               join_acks=st["join_acks"], rtt_requests=st["rtt_requests"],
               rtt_answers=st["rtt_answers"], reliable=st["reliable"],
               unreliable=st["unreliable"], requests=st["requests"],
               request_answers=st["request_answers"], last_request=st["last_request"],
               state_requests=st["state_requests"])
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
    ap.add_argument("--dwell", type=float, default=1.5,
                    help="seconds per channel in the scan; 0.8 missed a live network twice")
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
    ap.add_argument("--reliable-ack", action=argparse.BooleanOptionalAction, default=False,
                    help="after the join, sweep the bulk acknowledgement until the console's "
                         "reliable retransmission stops")
    ap.add_argument("--room-walk", type=int, default=0, metavar="N",
                    help="after the reliable handshake, send N position messages of our own and "
                         "watch the console's screen")
    ap.add_argument("--room-walk-gap", type=float, default=1.0)
    ap.add_argument("--room-walk-steps", type=int, default=60, metavar="N",
                    help="position messages in the burst pattern's walk. At the console's own "
                         "stride, 60 is 55.8 units and leaves the Union Room entirely (sp66); "
                         "pass 8 for a walk that ends where the screen can still see it")
    ap.add_argument("--room-walk-period", type=float, default=room.POS_PERIOD,
                    help="seconds between position messages in the burst pattern. The default is "
                         "the console's own median gap; pass sp63's 0.35 to reproduce that run")
    ap.add_argument("--room-walk-stride", type=float, default=room.POS_STRIDE,
                    help="units one position message spans. The default is what a console's own "
                         "walk measures (0.93 units every 0.41 s, over 80 of its messages); our "
                         "first walks did 0.15 every 0.6 s, which is a ninth of a real player's "
                         "speed and is the whole of the stutter")
    ap.add_argument("--answer-requests", action=argparse.BooleanOptionalAction, default=False,
                    help="answer the console's NetRequestData with the message it names. It has "
                         "asked for data id 0x23 in every capture since the first join and has "
                         "never been answered; this is the probe, so arm it on its own")
    ap.add_argument("--match-wait", action=argparse.BooleanOptionalAction, default=False,
                    help="answer the console's request for NetDataIsMatchWaitData (0x23) with "
                         "isMatchWait=1 instead of 0. ONE comparison in UnionRoomManager$$SetNetData "
                         "gates the trade on it (`cmp w23, #1` at main.bin 0x01fd56e4, then "
                         "UnionFrontDeskTradeController$$StartMatch); every run since session 46 has "
                         "answered 0, which is a station declining to be matched")
    ap.add_argument("--join-offset-x", type=float, default=2.0, metavar="U",
                    help="where our character spawns relative to the console's own, on x. The "
                         "default +2.0 is one fixed side, and a player standing against the wall "
                         "on that side gets a character spawned out of bounds (sp80, followed by a "
                         "crash). Negative puts it on the other side")
    ap.add_argument("--join-offset-z", type=float, default=0.0, metavar="U",
                    help="the same on z")
    ap.add_argument("--initiate-talk", action=argparse.BooleanOptionalAction, default=False,
                    help="APPROACH the console's character instead of waiting to be approached. "
                         "Picking an emote locks a player in place waiting to be interacted with, "
                         "so a recruiting console can only be reached by someone walking up to it. "
                         "Waits for its broadcast state to say it is advertising, then sends "
                         "NetDataTalkReserveData - the console's own bytes, 63 00 01 00")
    ap.add_argument("--after-approach", action="append", default=[], metavar="ID:HEX",
                    help="after THEY answer our approach, send this message - the initiator's own "
                         "next one. `0x06:0000000000` is NetDataTalkData{sexId 0, CHECK}, which is "
                         "what SwitchTalkStateMine builds. Repeatable, sent in order")
    ap.add_argument("--after-approach-gap", type=float, default=1.0, metavar="S",
                    help="seconds between the approach answer and each --after-approach message")
    ap.add_argument("--initiate-delay", type=float, default=2.0, metavar="S",
                    help="seconds to wait after the console starts advertising before approaching")
    ap.add_argument("--initiate-tries", type=int, default=12, metavar="N",
                    help="how many times to retransmit the approach before giving up")
    ap.add_argument("--initiate-gap", type=float, default=1.0, metavar="S",
                    help="seconds between approach retransmissions")
    ap.add_argument("--match-wait-period", type=float, default=2.0, metavar="S",
                    help="with --match-wait, ALSO send NetDataIsMatchWaitData{1} every S seconds "
                         "for the whole hold (0 disables, leaving the answer-on-request of sp77). "
                         "The console requests 0x23 once, at t=8.4-9.4, and the player reaches the "
                         "trade option in the Y menu long after that")
    ap.add_argument("--after-talk", action="append", default=[], metavar="ID:HEX",
                    help="after answering the talk reservation, send this game message on the "
                         "reliable stream - `0x08:00` is NetDataSelectData{index: 0}. Repeatable, "
                         "sent in order. The console parks in TalkState GREETING and waits to be "
                         "advanced, and which message does it is not readable offline: this is the "
                         "sweep handle")
    ap.add_argument("--after-talk-gap", type=float, default=0.6, metavar="S",
                    help="seconds between the talk answer and each --after-talk message")
    ap.add_argument("--answer-talk", action=argparse.BooleanOptionalAction, default=False,
                    help="answer a NetDataTalkReserveData with a NetDataTalkReserveResultData. "
                         "sp70 left it unanswered and the player's character froze")
    ap.add_argument("--can-talk", type=int, default=1, metavar="N",
                    help="NetDataTalkReserveResultData.IsCanTalk - 1 accepts the talk, 0 refuses "
                         "it. A refusal is the SAFE probe: it should release the player rather "
                         "than open a flow we cannot hold up")
    ap.add_argument("--state", type=int, default=room.STATE_NONE, metavar="N",
                    help="the OpcState.OnlineState our character reports when the console asks "
                         "for NetCharacterStateData. 0 NONE is what sp63/sp64 answered with and is "
                         "a character doing nothing; 3 RECRUITMENT_BATTLE, 4 RECRUITMENT_TRADE, "
                         "5 RECRUITMENT_RECORD, 6 RECRUITMENT_GREETINGS, 8 COMMUNICATE")
    ap.add_argument("--recruiting", type=int, default=0, metavar="N",
                    help="StateData.isRecruiment, the second byte of the same answer")
    ap.add_argument("--join-avatar", type=int, default=8, metavar="N",
                    help="NetJoinData.avatarId, which is what picks the MODEL: it indexes "
                         "UnionCharacterTable and OpLoadCharacter loads that asset name. 8 is what "
                         "every run before sp69 sent, and is the girl the screen keeps showing")
    ap.add_argument("--join-color", type=int, default=0, metavar="N",
                    help="NetJoinData.colorId. The game also derives one from the avatar id "
                         "(OpcManager.GetNpcColorId), so this may not be the deciding field")
    ap.add_argument("--send-card", action=argparse.BooleanOptionalAction, default=False,
                    help="after the walk, send a NetDataTranerCardData for our own station. It is "
                         "the message that says what a player LOOKS like, and the probe is whether "
                         "the character the game drew for us changes on screen")
    ap.add_argument("--card-fashion", type=int, default=3, metavar="N")
    ap.add_argument("--card-body", type=int, default=1, metavar="N")
    ap.add_argument("--card-gender", type=int, default=1, metavar="N")
    ap.add_argument("--card-trainer-id", type=int, default=41000, metavar="N")
    ap.add_argument("--room-pattern", choices=("square", "line", "fixed", "move"), default="square",
                    help="square spawns one avatar per corner; line and fixed ask whether the "
                         "game's idea of identity is the station or the position")
    ap.add_argument("--reliable-auto-ack", action=argparse.BooleanOptionalAction, default=True,
                    help="acknowledge the console's reliable data as it arrives")
    ap.add_argument("--reliable-sweep", type=int, default=8,
                    help="how many values of the byte at offset 1 to try")
    ap.add_argument("--reliable-ack-wait", type=float, default=1.5,
                    help="how long silence has to last to count as an ack that landed")
    ap.add_argument("--connect-timeout", type=float, default=4.0,
                    help="how long one connection request waits for its answer")
    ap.add_argument("--rtt", action=argparse.BooleanOptionalAction, default=True,
                    help="answer the console's RTT requests (protocol 0x58) while we hold the seat")
    ap.add_argument("--join-ack", action=argparse.BooleanOptionalAction, default=True,
                    help="ack the mesh join response, on the STATION protocol")
    ap.add_argument("--join-ack-seconds", type=float, default=8.0,
                    help="how long to keep acking the mesh join response; the host repeats it "
                         "every 500 ms until it is acknowledged")
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
