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
import argparse, json, os, socket, struct, sys, time, traceback, zlib

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED):
    sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.host_support import resolve_keys
from pokeldn.ldn import (broadcast4, local_protocol as lp, mesh_protocol as mesh, pia4, reliable4,
                        reliable5, rtt_protocol as rtt, station4,
                        station_protocol as stp)
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.swsh import COMM_ID, PASSPHRASE, PIA_PORT, packet_iv, session_keys
from pokeldn.swsh import trade as swsh_trade
from pokeldn.swsh import pokemon as swsh_pokemon
from pokeldn.swsh import trade_payload

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
              "reliable_last": None, "broadcast_in": 0, "data_out": 0, "data_acked": None,
              "broadcast_ack_ids": set(), "broadcast_stray_ids": set(), "windows": {},
              "their_ack_id": 0, "data_seqs": 0,
              "their_payload": None, "ack_by_proto": {}, "said_by_proto": {},
              "seen_by_proto": {}, "answer_queue": [],
              "snapshot_in": 0, "snapshot_total": None, "snapshot_indexes": set(),
              "their_sequence": None, "snapshot_out": 0, "snapshot_acked": None,
              "snapshot_acks_out": 0, "snapshot_rx": broadcast4.Receiver(),
              "snapshot_fragments": 0, "snapshot_done_sent": False, "snapshot_seq": 0,
              "offered_pk8": None, "our_pk8": None, "offer_pending": None, "offer_seq": None,
              "said_by_port": {}, "ack_by_port": {}, "rpc_out": 0, "rpc_acked": None,
              "trade_ready_sent": False, "box_open_sent": False, "pk8_offer_sent": False,
              "our_index": None, "host_index": None, "last_update_mesh": None, "rpc_queue": [],
              "selection_sent": False, "box_queue": [], "box_seen": [], "box_next": 0.0,
              "we_are_host": False, "update_mesh_out": 0,
              "migration_pending": None, "migration_out": 0, "migration_acked": None,
              "said_serial": 0, "serial_by_proto": {}, "serial_by_port": {},
              "rpc_seen": {}, "rpc_pair_sent": set(), "offer_status_answered": set(),
              "rpc_bodies_answered": set(), "confirmation_opened": False, "rpc_pair_delta": {},
              "confirm_status_answered": set(),
              "confirm_queue": None,
              "block_out": 0, "block_acked": None}

        accepted = trio.Event()           # set when the station handshake closes, which is the
                                          # only moment a mesh join has ever been answered
        nonce = int.from_bytes(os.urandom(8), "big")

        def next_nonce():
            nonlocal nonce
            nonce = (nonce + 1) & ((1 << 64) - 1)
            return nonce.to_bytes(8, "big")

        def open_phase(offset, label):
            """Queue an RPC pair that OPENS a phase, built from the console's own 40030 envelope.

            WHEN THIS GOES OUT IS THE WHOLE QUESTION, and sw89 got it wrong. It sent the 40050 pair
            on the migration start - which is the console's TEARDOWN, the last thing it ever says -
            so the pair went out after the console had stopped reading, was never acked, and the
            run tested nothing. A phase is opened while the conversation is still running.
            """
            if st["selection_sent"]:
                return
            last = st["said_by_port"].get((reliable5.PROTOCOL, args.rpc_port))
            got = swsh_trade.parse_rpc(last) if last else None
            if got is None or got.get("clock") is None:
                print("[tx]     no 40030 pair seen on port 1; cannot build a phase opener")
                return
            clock = got["clock"] + args.rpc_clock_delta
            pair = swsh_trade.build_rpc_pair(offset, our_constant, clock)
            if args.offer_on_50 and st["our_pk8"] is not None:
                # AND PUT THE POKEMON IN IT. Content 50 is `PokemonTradeDataHolder` - the transfer
                # itself - where content 30, everything this project has done since sw75, is the
                # BOX exchange that shows each other a Pokemon. nxldn-lab reads a 344-byte PK8 out
                # of field 5 of a 40050 envelope, so field 5 is a variable slot and on this content
                # it carries the entity. sw93 sent this pair with the 40030 pair's four-byte bodies
                # and the console ignored it; an empty envelope on the transfer content is an
                # envelope with nothing in it.
                pair = (pair[0], swsh_trade.build_rpc_pokemon(
                    offset, swsh_trade.RPC_BASES[1], our_constant, clock, st["our_pk8"]))
                print(f"[tx]     the second member carries our PK8 in field "
                      f"{swsh_trade.RPC_POKEMON_FIELD}, {len(pair[1])} bytes")
            st["rpc_queue"].extend(pair)
            st["selection_sent"] = True
            print(f"\n[tx]     *** OPENING THE {label} PHASE *** {40000 + offset} pair on "
                  f"0x7c port {args.rpc_port}, clock {clock}\n"
                  f"[tx]       {pair[0].hex()}\n[tx]       {pair[1].hex()}")


        def _opener_for(offset):
            """-> what to send on content `offset`'s 10000-base holder to open it.

            SX49B IS WHY THIS IS NOT ALWAYS A PING. `--open-content 30,50` sent `422700000a00` -
            an EMPTY PokemonTradeDataHolder - and the console went further than it ever had: it
            sent id 120 and the 40040 pair, which `docs/swsh.md` says cannot exist before the
            exchange has completed. It had accepted the empty record AS our Pokemon, which is why
            the player was asked to trade their Pomdrapi for an **Oeuf**. `0x010d81d0` takes the
            default-instance branch when the body carries no field 1 and calls the listener
            anyway, so a ping and a Pokemon reach the same handler and only one of them carries a
            Pokemon. With `--open-content-offer` the opener for a content we have a PK8 for is the
            PK8.
            """
            if args.open_content_offer and st["our_pk8"] is not None:
                return swsh_trade.pokemon_offer(offset, st["our_pk8"])
            return swsh_trade.open_content(offset)


        def reliable_window(protocol, port, body, now):
            """One version-4 reliable window, on whatever protocol and port it arrives.

            THERE IS MORE THAN ONE. 0x7C port 0 is the game's, and sw59 found a SECOND on the mesh
            protocol's own reliable port (0x18 port 1, `mesh.PORT_RELIABLE`) - the console opened it
            0.2 s after it acknowledged our first application data, retransmitted its sequence 1
            seventy-six times because nothing here answered it, and tore the mesh down four seconds
            later. An unacknowledged window is a dead session, whichever protocol carries it.

            AND THE WINDOW DOES NOT START AT 1. sw59 rejoined a session the console had never
            dropped and its stream resumed at 292, so a receiver seeded at 0 acks nothing at all:
            `contiguous_through` waits for a sequence 1 that will never come again. The console's
            own rule is the one to copy (`0x01859d20`): the first message carrying
            FLAG_IS_INITIALIZED DEFINES where the stream starts.
            """
            key = (protocol, port)
            w = st["windows"].setdefault(key, {"seqs": set(), "through": None, "acks": 0, "in": 0})
            w["in"] += 1
            try:
                got = reliable4.parse_message(body)
            except ValueError as e:
                print(f"[rx] t={now:6.2f} {protocol:#04x}/{port} {len(body)} B unreadable: {e}")
                return
            st["reliable_last"] = now
            if not (got["flags"] & reliable4.FLAG_APPLICATION_DATA):
                try:
                    shape = [e for e in reliable4.parse_ack_payload(got["payload"])
                             if e["slot"] < 8 and e["ack_id"]]
                except ValueError as e:
                    shape = f"not the version-4 shape: {e}"
                print(f"\n[rx] t={now:6.2f} *** ACK FROM THE CONSOLE on {protocol:#04x}/{port} "
                      f"*** {len(got['payload'])} B, slots 0..7: {shape}")
                record(rec="rx_reliable_ack", t=now, protocol=protocol, port=port,
                       raw=got["payload"].hex())
                for e in (shape if isinstance(shape, list) else []):
                    st["their_ack_id"] = max(st["their_ack_id"], e["ack_id"])
                    st["ack_by_proto"][protocol] = max(st["ack_by_proto"].get(protocol, 0),
                                                       e["ack_id"])
                    # AND PER PORT. sw79 found the console sends its trade RPC pair on 0x7C PORT 1
                    # and its Pokemon offer on port 0, so a single per-protocol counter conflates
                    # two independent windows - and every RPC answer this project sent went out on
                    # the port the console does not read them on.
                    st["ack_by_port"][(protocol, port)] = max(
                        st["ack_by_port"].get((protocol, port), 0), e["ack_id"])
                if (st["data_acked"] is None and st["data_out"]
                        and protocol == args.send_protocol):
                    # THE PASS SIGNAL. The console answers application data and nothing else, so
                    # before sw59 it had never sent one of these at all.
                    st["data_acked"] = now
                    print(f"[rx]     *** IT ANSWERED OUR DATA, t={now:.2f} ***")
                return
            st["their_payload"] = got["payload"]
            st["said_by_proto"][protocol] = got["payload"]
            st["said_by_port"][(protocol, port)] = got["payload"]
            # AND THE ONE CUE nxldn-lab ACTS ON THAT WE NEVER HAVE. Its client opens the selection
            # phase itself when the console says `820000001a00` - id 130, pingSynced - and only
            # then answers the console's own burst. Our captures carry that payload 0.3 s ahead of
            # the burst every run (sx45r1_6, t=31.30 against t=31.60), and this project has only
            # ever echoed it. `open_phase` latches, so this fires once.
            if args.selection_start and got["payload"] == swsh_trade.sync(
                    130, swsh_trade.PING_SYNCED):
                open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION, ON THE 130 PINGSYNCED")
            # THE 40030 RPC IS A PAIR AND WE HAVE ONLY EVER ANSWERED HALF OF IT. The console sends
            # TWO members, one per base - 10000 and 20000 - and `said_by_port` keeps only the LAST
            # thing said, so sx15 sent 459 copies of one member and never the other. Keep each
            # member by its BASE so the sender can answer both.
            #
            # NOT BY nxldn-lab's KIND BYTE. That client tests `payload[5] in (0x19, 0x1A)`, which is
            # the INNER LENGTH, and the length depends on how many bytes the sender's station id
            # varint takes: sx15's console sent 0x19/0x1A and sx16's sent 0x1A/0x1B. Their constant
            # is an artefact of the capture they worked from. The base is a field, so read it.
            if protocol == reliable5.PROTOCOL:
                member = swsh_trade.parse_rpc(got["payload"])
                if member is not None and member["base"] in swsh_trade.RPC_BASES:
                    # KEYED BY ENVELOPE AND BASE. Each phase has its own envelope - 40030 the offer,
                    # 40050 the selection, 40040 the confirmation - and each sends the same two
                    # members. sx17 answered 40030's pair, the console opened the selection phase,
                    # and then sent 40050 pairs to a client that only knew about 40030.
                    st["rpc_seen"][(member["envelope"], member["base"])] = got["payload"]
                    # AND THE SAME CUE ONE CONTENT ALONG, WHICH sx51b MEASURED AND ONLY HALF
                    # ANSWERED. With the selection ladder climbed the console sends a 40040/20000
                    # member whose body also ends `0100` - the confirmation content saying the same
                    # thing the selection content said. Its log says exactly what happened to it:
                    # line 367 fired the selection cue, spending `offer_status_answered`, which is
                    # ONE latch for the whole run; line 443 then answered the 40040 body through
                    # the generic `--rpc-bodies` branch below. So the STATUS was answered on port 1
                    # and NOTHING was ever sent on port 0. In the selection phase it took both.
                    #
                    # THE ANSWER IS NOT ANOTHER POKEMON. Content 40's 10000-base holder parses with
                    # `0x010df6d0`, which takes `SyncSaveDataHolder{syncCommand{data:int32}}` and
                    # nothing else - session 64, read out of the image and agreeing with the game's
                    # own descriptors. `swsh_trade.SYNC_COMMANDS` says which values its own state
                    # machine sends. Its own latch, so the two cues cannot swallow each other.
                    #
                    # AND IT IS A HANDSHAKE, SO ONE COMMAND IS NOT ENOUGH. sx53: with the pair
                    # re-armed the console climbed two more steps on its own - its elementId-20000
                    # body went `00000100` -> `01000100` -> `01000200`, two counters moving - and
                    # then stopped. Its own machine sends 0, 1, 2, 3 and parks after each, so
                    # `--confirm-commands 0,1,2,3` sends the NEXT one on each new step. The trigger
                    # cannot stay "the body ends 0100": `01000200` does not, and that is the step
                    # the run ended on. Any new four-byte body on the confirmation content's
                    # elementId 20000 is a step.
                    answered_confirmation = False
                    if st["confirm_queue"] is None:
                        st["confirm_queue"] = (
                            [int(c, 0) for c in args.confirm_commands.split(",") if c.strip()]
                            if args.confirm_commands
                            else ([args.confirm_command] if args.confirm_command is not None
                                  else []))
                    if (st["confirm_queue"]
                            and member["envelope"] == (swsh_trade.RPC_ENVELOPE_BASE
                                                       + swsh_trade.CONFIRMATION_OFFSET)
                            and member["base"] == swsh_trade.RPC_BASES[1]
                            and len(member["body"]) == 4
                            and (args.confirm_commands
                                 or member["body"][-2:] == b"\x01\x00")
                            and (member["envelope"], member["base"], bytes(member["body"]))
                            not in st["confirm_status_answered"]):
                        st["confirm_status_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        command = st["confirm_queue"].pop(0)
                        answered_confirmation = True
                        st["box_queue"] = st["box_queue"] + [
                            swsh_trade.sync_command(member["offset"], command)]
                        st["box_next"] = 0.0
                        status = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                       args.rpc_clock_delta)
                        if status is not None:
                            st["rpc_queue"] = [status] + st["rpc_queue"]
                        st["rpc_bodies_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        print(f"[tx]     *** THE CONFIRMATION STATUS *** sending "
                              f"syncCommand{{data:{command}}} on "
                              f"{swsh_trade.CONTENT_BASE_LOW + member['offset']} port 0 and "
                              f"answering the status on port 1, triggered by "
                              f"{got['payload'].hex()}")
                    # AND THE STATUS THAT FOLLOWS THE CONSOLE'S OWN POKEMON. sx20: once the 40050
                    # pair is answered the console puts a 344-byte PK8 in field 5 of a 40050
                    # envelope and then sends a status whose four-byte body ends `0100` instead of
                    # the `18fc` every other member carries. That status is the cue to offer ours
                    # on the 10000-base holder of the SAME content - id 10050, reliable port 0 -
                    # and to answer the status itself on port 1.
                    if (args.selection_offer and not answered_confirmation
                            and member["base"] == swsh_trade.RPC_BASES[1]
                            and member["body"][-2:] == b"\x01\x00" and len(member["body"]) == 4
                            and not st["offer_status_answered"]
                            and st["our_pk8"] is not None):
                        # A HARD LATCH, NOT A PER-ENVELOPE SET. sx23 printed this branch 48 times
                        # in a run where exactly ONE payload satisfies the condition - re-checked
                        # offline against every RPC payload in its own log. Whatever the cause, a
                        # set keyed on a parsed field was not holding it, and this project has lost
                        # more runs to a message repeated than to any message missing. One offer
                        # per run, and the trigger is printed so the next log can be read.
                        st["offer_status_answered"].add(True)
                        # THE POKEMON GOES OUT ON THE PORT-0 WINDOW and the status answer on the
                        # port-1 one; `box_queue` drains into `offer_pending` on port 0 and
                        # `rpc_queue` is the port-1 sender's own.
                        if args.selection_offer_sweep:
                            # swsh_trade.SELECTION_SWEEP_NOTE says what is left and why these go
                            # out together. Spaced through box_queue, behind the mirror shape.
                            st["box_queue"] = (st["box_queue"]
                                               + list(swsh_trade.selection_sweep(
                                                   member["offset"], st["our_pk8"])))
                            st["box_next"] = 0.0
                        elif args.selection_offer_high:
                            # THE 20000-BASE HOLDER. The box phase's own Pokemon rides 20030, one
                            # content over, and that is the exchange the player sees. 10050 (sx34),
                            # a five-field Data on 40050 (sx36) and the console's own three-field
                            # one (sx37) are all acknowledged and all inert.
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.pokemon_offer_high(member["offset"], st["our_pk8"])]
                            st["box_next"] = 0.0
                        elif args.selection_offer_mirror:
                            # sx36, MEASURED: the console's own Pokemon-carrying 40050 decodes to
                            # fields 1, 4 and 5 and nothing else. Ours carried all five, was
                            # acknowledged at the transport on every sequence, and moved nothing.
                            # And the identity is ruled out - our ownerId was the id the console
                            # addressed a reliable ack TO in the same run. The field set is what
                            # is left to vary, so this is the console's own.
                            clock = (member["clock"] or 0) + args.rpc_clock_delta
                            st["rpc_queue"] = [swsh_trade.mirror_pokemon_offer(
                                member["offset"], clock, st["our_pk8"])] + st["rpc_queue"]
                        elif args.selection_offer_data:
                            # SESSION 62, READ OUT OF THE BINARY. Content 50's receive handler,
                            # `0x010d5e40`, resolves the SENDER to a station index before it looks
                            # at a body and returns silently when it cannot - and the envelope is
                            # `gflnet.p2p.sync.pb.Data`, whose field 3 the game itself calls
                            # `ownerId`. `pokemon_offer` is a PokemonTradeDataHolder on 10050 with
                            # no owner in it at all. This is the console's own shape instead: the
                            # PK8 in `body` of a 40050 whose ownerId is ours, on the RPC port the
                            # console sends its own on. `docs/swsh.md`, "A content is three holders".
                            clock = (member["clock"] or 0) + args.rpc_clock_delta
                            st["rpc_queue"] = [swsh_trade.build_rpc_pokemon(
                                member["offset"], swsh_trade.RPC_BASES[1], our_constant,
                                clock, st["our_pk8"])] + st["rpc_queue"]
                        else:
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.pokemon_offer(member["offset"], st["our_pk8"])]
                            st["box_next"] = 0.0
                        if args.sync_after_offer is not None:
                            # THE OPENER, WHERE IT CAN ACTUALLY FIRE. --sync-after-hash lives in
                            # the "a new body arrived" chain, and this branch has already latched
                            # that body and added it to rpc_bodies_answered, so that elif is dead
                            # whenever --selection-offer is on: sx42 printed no STARTING SYNC line
                            # at all. This queues it behind our own Pokemon instead.
                            st["box_queue"] = st["box_queue"] + [
                                swsh_trade.sync(args.sync_after_offer, args.sync_field)]
                            st["box_next"] = 0.0
                            print(f"[tx]     *** SYNC {args.sync_after_offer} FIELD "
                                  f"{args.sync_field} BEHIND OUR OFFER ***")
                        status = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                       args.rpc_clock_delta)
                        if status is not None:
                            st["rpc_queue"] = [status] + st["rpc_queue"]
                        st["rpc_bodies_answered"].add(
                            (member["envelope"], member["base"], bytes(member["body"])))
                        where = (f"as a PokemonTradeDataHolder on "
                                 f"{swsh_trade.RPC_BASES[1] + member['offset']} port 0"
                                 if args.selection_offer_high else
                                 f"as the console's own field set on "
                                 f"{swsh_trade.RPC_ENVELOPE_BASE + member['offset']} port "
                                 f"{args.rpc_port}" if args.selection_offer_mirror else
                                 f"as a Data on {swsh_trade.RPC_ENVELOPE_BASE + member['offset']}"
                                 f" port {args.rpc_port} with our ownerId"
                                 if args.selection_offer_data else
                                 f"on {swsh_trade.CONTENT_BASE_LOW + member['offset']} port 0")
                        print(f"[tx]     *** THE SELECTION OFFER STATUS *** offering our "
                              f"Pokemon {where} and answering the status on port 1, triggered by "
                              f"{got['payload'].hex()}")
                    # AND EVERY OTHER DISTINCT BODY, ONCE. sx21: with the pair answered and our
                    # Pokemon offered, the console echoes ours back and then sends a member whose
                    # field 5 is a HASH - `c7772899` where every earlier member carried `00000000`
                    # or `000018fc`. The per-envelope guard had already fired, so nothing answered
                    # it. The clock advances on every message, so the payload cannot be the key;
                    # (envelope, base, BODY) can, and it answers each new thing the console says
                    # exactly once while ignoring the retransmissions.
                    elif (args.rpc_bodies and member["clock"] is not None
                            and len(member["body"]) == 4):
                        seen_body = (member["envelope"], member["base"],
                                     bytes(member["body"]))
                        if (seen_body not in st["rpc_bodies_answered"]
                                and bytes(member["body"]) not in (b"\x00\x00\x00\x00",
                                                                  b"\x00\x00\x18\xfc")):
                            # AND THE SAME LADDER ON THE CONFIRMATION CONTENT. sx52e: with
                            # `--confirm-command 0` answered, content 40 ran the selection content's
                            # ladder exactly - the pair, then a member on elementId 1, then a hash
                            # (`b22d6f50`) - and then went quiet for 124 s. The elementId-1 echo and
                            # the hash are the signature that only ever appeared once our record
                            # genuinely reached a content's receive event, so the command LANDED and
                            # the phase stalled where the selection phase stalled before its own
                            # re-arm existed. Same move, same reason, its own flag.
                            if (args.confirm_final_delta
                                    and member["envelope"] ==
                                    swsh_trade.RPC_ENVELOPE_BASE
                                    + swsh_trade.CONFIRMATION_OFFSET):
                                st["rpc_pair_sent"].discard(member["envelope"])
                                st["rpc_pair_delta"][member["envelope"]] = \
                                    args.confirm_final_delta
                                print(f"[tx]     *** THE CONFIRMATION HASH - RE-ARMING THE "
                                      f"{member['envelope']} PAIR AT CLOCK "
                                      f"+{args.confirm_final_delta} ***")
                            if (args.selection_final_delta
                                    and member["envelope"] ==
                                    swsh_trade.RPC_ENVELOPE_BASE + swsh_trade.SELECTION_OFFSET):
                                # THE LADDER nxldn-lab CLIMBS AND WE STOP HALFWAY UP. After the
                                # offer it answers the HASH with one member, and then the NEXT
                                # 40050 pair with BOTH members at a larger clock delta - its
                                # `selection_final_delta`, 9. `--rpc-pair` latches per envelope, so
                                # the second pair has never gone out. sx50d is where this matters:
                                # our Pokemon reached content 50 (the confirmation named it instead
                                # of an Oeuf) and the console answered with a hash and an echo of
                                # our own record on elementId 1, which is the verification step.
                                st["rpc_pair_sent"].discard(member["envelope"])
                                st["rpc_pair_delta"][member["envelope"]] = \
                                    args.selection_final_delta
                                print(f"[tx]     *** THE HASH - RE-ARMING THE {member['envelope']}"
                                      f" PAIR AT CLOCK +{args.selection_final_delta} ***")
                            reply = swsh_trade.answer_rpc(got["payload"], our_constant,
                                                          args.rpc_clock_delta)
                            if reply is not None:
                                st["rpc_bodies_answered"].add(seen_body)
                                st["rpc_queue"] = st["rpc_queue"] + [reply]
                                # AND OPEN THE NEXT PHASE, BECAUSE NOBODY ELSE WILL. sx24: the
                                # console stopped sending 40050 ENTIRELY the moment this answer
                                # went out - no retransmission, which in Pia means satisfied, not
                                # ignored. It then said nothing at all. `nxldn-lab`'s client opens
                                # the confirmation itself with `ping` on the content's 10000-base
                                # holder (`382700000a00`, id 10040), and this project has never
                                # opened a phase unprompted.
                                if (args.pair_after_hash is not None
                                        and not st["confirmation_opened"]):
                                    # OPEN THE PHASE THE WAY THIS CONSOLE OPENS ONE: WITH A PAIR.
                                    # sx28 and sx31 both measured the negatives - a bare `ping` on
                                    # content 40's 10000-base holder (`382700000a00`) and a bare
                                    # sync-120 ping (`780000000a00`) were each ignored completely.
                                    # What HAS opened a phase on this console, twice, is the two
                                    # RPC members with the standard bodies: 40030 opened the offer
                                    # and 40050 the selection, both as a pair on the RPC window.
                                    # `build_rpc_pair` builds ours with our own station id and the
                                    # clock the console is already using.
                                    st["confirmation_opened"] = True
                                    clock = (member["clock"] or 0) + args.rpc_clock_delta
                                    pair = swsh_trade.build_rpc_pair(
                                        args.pair_after_hash, our_constant, clock)
                                    st["rpc_queue"] = st["rpc_queue"] + list(pair)
                                    print(f"[tx]     *** OPENING THE {40000 + args.pair_after_hash}"
                                          f" PHASE WITH A PAIR *** {[p.hex() for p in pair]}")
                                elif (args.sync_after_hash is not None
                                        and not st["confirmation_opened"]):
                                    # START THE SYNC NOBODY HAS EVER STARTED. sx28: the chain runs
                                    # 97 -> 60000 -> 110 -> 130, and the console opens the
                                    # SELECTION phase itself the moment 130's pingSynced lands.
                                    # **id 120 never appears at all** - and 120 is the confirmation's
                                    # trigger. The console started 110 and 130; nothing has ever
                                    # started 120, and `SYNC_ANSWERS` only knows how to ANSWER it.
                                    # Opening content 40 directly (sx28, `382700000a00`) changed
                                    # nothing, which fits: the phase follows its sync, not the ping.
                                    st["confirmation_opened"] = True
                                    # sx31 SENT THE WRONG FIELD. This project's own note of
                                    # nxldn-lab's trace says the confirmation opens on
                                    # `780000001a00` - field 3, pingSynced - and sx31 sent
                                    # `780000000a00`, field 1, a plain ping. --sync-field
                                    # picks which one goes out.
                                    opener = swsh_trade.sync(args.sync_after_hash,
                                                             args.sync_field)
                                    st["box_queue"] = st["box_queue"] + [opener]
                                    st["box_next"] = 0.0
                                    print(f"[tx]     *** STARTING SYNC {args.sync_after_hash} "
                                          f"AFTER THE HASH *** {opener.hex()}")
                                print(f"[tx]     *** ANSWERING A NEW {member['envelope']} BODY "
                                      f"{bytes(member['body']).hex()} *** {reply.hex()}")
            # AND WHEN IT SAID IT. `--answer-once` needs to tell "the console has said something
            # new" from "the console said that once, a minute ago" - see its argument help. The
            # senders read the payload AND this counter, and a sender that has already answered
            # this counter has nothing to say.
            st["said_serial"] += 1
            st["serial_by_proto"][protocol] = st["said_serial"]
            st["serial_by_port"][(protocol, port)] = st["said_serial"]
            # THE MESH RIDES INSIDE THIS WINDOW. 0x18 port 1 is the mesh protocol's RELIABLE port,
            # so a payload here is a mesh message, not an application one - and the one the console
            # sends when the player accepts the trade is MIGRATION_START. See mesh_protocol.
            if protocol == mesh.PROTOCOL:
                start = mesh.parse_migration_start(got["payload"])
                if start is not None:
                    print(f"\n[rx] t={now:6.2f} *** THE CONSOLE IS MIGRATING THE MESH TO US *** "
                          f"host {start['host_index']} names station "
                          f"{start['new_host_index']} as the next host")
                    record(rec="rx_migration_start", t=now, **start)
                    if args.box_on_accept:
                        # THE ONLY WAY TO SPEAK AFTER THE ACCEPT. The migration start is the one
                        # signal that says the player pressed the button, and sx05 shows the
                        # console keeps acking for about five seconds after it - so there IS a
                        # window, and this project has never put anything in it. Everything tried
                        # so far landed BEFORE the accept, which is a different state.
                        st["box_queue"] = [swsh_trade.box_sync_state(int(c, 0))
                                           for c in args.box_on_accept.split(",")]
                        st["box_next"] = 0.0
                        st["offer_pending"] = None
                        print(f"[tx]     *** ANSWERING THE ACCEPT *** box commands "
                              f"{args.box_on_accept}: "
                              f"{[p.hex() for p in st['box_queue']]}")
                    # AND IT IS THE ONLY RELIABLE "THE PLAYER ACCEPTED" SIGNAL WE HAVE. It arrives
                    # once, seconds after the accept, in every run where the player pressed it and
                    # in no other. The console never retransmits it - one transport ack satisfies
                    # it - so it is a notification, not a question, and using it to TIME something
                    # is worth more than answering it. sw84, sw87 and sw88 each answered it a
                    # different way and each made the console give up sooner than ignoring it did.
                    if args.send_selection == "migration":
                        open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION")
                    if args.answer_migration and st["migration_pending"] is None:
                        index = st["our_index"]
                        if index is None:
                            index = start["new_host_index"]
                            print("[tx]     no join response gave us an index; using the one the "
                                  "migration start names")
                        # WHICH MESSAGE DEPENDS ON WHETHER IT NAMED US, and sw84 is why. A
                        # MIGRATION_RESPONSE travels TO the new host - `0x017c3250` takes the
                        # destination in w1 and its caller passes the new host index - so a station
                        # that has just been named the next host owes a FINISH, not a response.
                        # sw84 sent 0x48 to the console: it acked it at the transport, stepped its
                        # update session 3 -> 4, stopped answering RTT and dropped the link 3.6 s
                        # later with 2-ALZAA-0016 in front of the player. It was waiting to be told
                        # the migration was over.
                        if args.migration_answer == "response" or (
                                args.migration_answer == "auto"
                                and start["new_host_index"] != index):
                            st["migration_pending"] = mesh.build_migration_response(index)
                            print(f"[tx]     *** ANSWERING WITH MIGRATION_RESPONSE *** "
                                  f"{st['migration_pending'].hex()} (our station index {index})")
                        else:
                            st["migration_pending"] = mesh.build_migration_finish(index)
                            st["we_are_host"] = True
                            print(f"[tx]     *** IT NAMED US THE NEXT HOST - SENDING "
                                  f"MIGRATION_FINISH *** {st['migration_pending'].hex()} "
                                  f"(we are station {index} and therefore the host now)")
                finish = mesh.parse_migration_finish(got["payload"])
                if finish is not None:
                    print(f"\n[rx] t={now:6.2f} *** MIGRATION FINISHED *** host "
                          f"{finish['host_index']} flag {finish['flag']}")
                    record(rec="rx_migration_finish", t=now, **finish)
            # EVERY DISTINCT PAYLOAD, not just the last. `--sync-answers` has a rule for some of
            # them and the ones it has no rule for are the finding: they are what the console says
            # next, in its own ids, and they are what turns another project's table into ours.
            command = swsh_trade.parse_box_command(got["payload"])
            if command is not None:
                st["box_seen"].append((round(now, 2), command))
                print(f"\n[rx] t={now:6.2f} *** BOX SYNC STATE COMMAND {command} *** on the trade "
                      f"holder - the console naming its own state machine")
                record(rec="rx_box_command", t=now, command=command)
            offered = swsh_trade.offered_pokemon(got["payload"])
            if offered is not None and st["offered_pk8"] is None:
                st["offered_pk8"] = offered
                read = swsh_pokemon.read(offered)
                print(f"\n[rx]     *** THE CONSOLE OFFERED US A POKEMON *** species "
                      f"{read['species']} {read['nickname']!r} level {read['level']} "
                      f"OT {read['ot_name']!r} ({read['trainer_id']}/{read['secret_id']})")
                if args.save_offered:
                    open(args.save_offered, "wb").write(offered)
                    print(f"[rx]     saved to {args.save_offered}")
                # AND ANSWER IT, AHEAD OF EVERYTHING ELSE. The sender otherwise looks only at what
                # the console said LAST, and the console goes on sending its RPC pair several times
                # a second - so sw78 saw the offer, printed it, and then answered an RPC instead,
                # every time. An offer is a one-shot and it has to outrank the running mirror.
                if args.offer_echo:
                    # OFFER ITS OWN RECORD BACK, UNCHANGED. sw89: between its offer and the
                    # teardown the console sends nothing but acks for four and a half seconds - it
                    # is not waiting to be told something, it is rejecting something - and the only
                    # thing we put in front of it is a Pokemon. Ours is the player's own level-100
                    # Ectoplasma wearing an OT we wrote, so its met data, memories and handler
                    # records name a trainer its ids no longer do. The PK8 the console just sent us
                    # is byte-perfect and came out of its own save, so a run that offers THAT and
                    # still aborts says the record is not the problem. `nxldn-lab` ships this as
                    # its `--echo` mode and its default Pokemon is 344 zero bytes, which is a hint
                    # about what that client could actually get accepted.
                    st["our_pk8"] = offered
                    print("[tx]     *** ECHOING ITS OWN RECORD BACK, unchanged ***")
                if st["our_pk8"] is not None:
                    st["offer_pending"] = swsh_trade.pokemon_trade(st["our_pk8"])
                    st["pk8_offer_sent"] = True
                    ours = swsh_pokemon.read(st["our_pk8"])
                    print(f"[tx]     *** OFFERING species {ours['species']} "
                          f"{ours['nickname']!r} level {ours['level']} BACK ***")
            seen = st["seen_by_proto"].setdefault(protocol, [])
            if got["payload"] not in seen:
                seen.append(got["payload"])
                if args.sync_answers and not swsh_trade.answers_for(got["payload"]):
                    print(f"[rx]     *** NO RULE for {got['payload'].hex()} on {protocol:#04x} "
                          f"- id {swsh_trade.parse(got['payload'])[0] if len(got['payload']) >= 4 else '?'} ***")
            if w["through"] is None:
                w["through"] = got["sequence_id"] - 1
                print(f"\n[rx] t={now:6.2f} {protocol:#04x}/{port} stream opens at seq "
                      f"{got['sequence_id']} stream {got['stream_id']} flags {got['flag_names']} "
                      f"payload {got['payload'].hex()}")
            w["seqs"].add(got["sequence_id"])
            through = reliable5.contiguous_through(w["seqs"], w["through"])
            if through == w["through"]:
                return                        # nothing new is contiguous; do not re-ack
            w["through"] = through
            ack = reliable4.build_ack_message(through + 1, stream_id=got["stream_id"],
                                              slots=args.ack_slots,
                                              lowest_pending=args.ack_lowest_pending)
            sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), ack, protocol,
                             args.connect_station_first, port=port,
                             message_flags=reliable5.MESSAGE_FLAGS,
                             destination=args.data_destination),
                        (host_ip, PIA_PORT))
            w["acks"] += 1
            record(rec="tx_reliable_ack", t=now, protocol=protocol, port=port, through=through,
                   ack=ack.hex())
            if w["acks"] <= 3 or w["acks"] % 50 == 0:
                print(f"[tx]     acked {protocol:#04x}/{port} through seq {through} "
                      f"(ack id {through + 1}), {w['acks']} acks on this window")

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
                    elif f["protocol"] == mesh.PROTOCOL and f["port"] == mesh.PORT_RELIABLE:
                        # 0x18 PORT 1 IS THE MESH PROTOCOL'S OWN RELIABLE PORT, and both halves
                        # of that matter. The version-4 reliable header is the TRANSPORT, which is
                        # what sw59 found when the console opened this window; the payload inside
                        # it is a MESH message, which is what session 60 found when the console
                        # sent `440001` - MIGRATION_START - the moment the player accepted the
                        # trade. `reliable_window` reads both layers.
                        st["mesh_in"] += 1
                        if args.ack_reliable:
                            reliable_window(mesh.PROTOCOL, mesh.PORT_RELIABLE, body, now)
                        else:
                            print(f"\n[rx] t={now:6.2f} *** 0x18 PORT 1 *** {len(body)} B "
                                  f"{body[:32].hex()} - not acked, --ack-reliable is off")
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
                                st["our_index"] = got["our_index"]
                                st["host_index"] = got["host_index"]
                            st["join_response"] = st["join_response"] or (now, body.hex())
                            record(rec="rx_join_response", t=now, parsed=got, raw=body.hex())
                        elif kind == mesh.UPDATE_MESH:
                            st["updates_mesh"] += 1
                            # KEEP THE LAST ONE. After a migration WE send these, and the cheapest
                            # correct one to send is the console's own with the host index changed.
                            st["last_update_mesh"] = body
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
                        # 0x7C, the game's own window. THE PASS SIGNAL IS THE RETRANSMITS STOPPING,
                        # the same shape as every other layer here.
                        st["reliable_in"] += 1
                        reliable_window(reliable5.PROTOCOL, f["port"], body, now)
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
                        if got["is_ack"] and len(got["payload"]) == reliable4.ACK_PAYLOAD_SIZE:
                            # THE PASS SIGNAL ON 0x80, and it is one number in ONE PLACE. Slots
                            # 0..7 are the mesh's real stations (8 is max_total from the join
                            # response) and every one of them says 1 in sw29, sw52 and sw58 alike -
                            # a window that has received nothing.
                            #
                            # SLOTS ABOVE 7 ARE NOT AN ACK AND MUST NOT BE READ AS ONE. sw52 and
                            # sw58 both carry a stray byte at slots 18/21/23/31 whose VALUE is our
                            # own 0x7C ack id - it tracks what we last sent, exactly, on every
                            # occurrence. sw58 spent a whole association on that: the sender saw
                            # "the window moved" at t=11.7, two seconds before it had sent
                            # anything, and never transmitted a byte.
                            entries = reliable4.parse_ack_payload(got["payload"])
                            real = {e["ack_id"] for e in entries
                                    if e["slot"] < 8 and e["ack_id"]}
                            stray = {e["ack_id"] for e in entries
                                     if e["slot"] >= 8 and e["ack_id"]}
                            fresh = real - st["broadcast_ack_ids"]
                            st["broadcast_ack_ids"] |= real
                            st["broadcast_stray_ids"] |= stray
                            moved = {i for i in real if i > args.send_sequence}
                            if (moved and st["data_acked"] is None and st["data_out"]
                                    and args.send_protocol == reliable4.BROADCAST_PROTOCOL):
                                st["data_acked"] = now
                                print(f"\n[rx] t={now:6.2f} *** THE BROADCAST WINDOW MOVED: ack "
                                      f"ids {sorted(moved)} in slots 0..7, past our sequence "
                                      f"{args.send_sequence} for the first time ***")
                            elif fresh and st["broadcast_in"] > 1:
                                print(f"[rx] t={now:6.2f} 0x80 ack ids now {sorted(real)}")
                        if got["flags"] & reliable4.FLAG_APPLICATION_DATA and args.ack_reliable:
                            # 0x80 CARRIES APPLICATION DATA TOO, and sw65 is where it first did:
                            # the console opened its broadcast window at t=13.42 with sequence 1
                            # and retransmitted it 3013 times because nothing here acked it.
                            reliable_window(reliable4.BROADCAST_PROTOCOL, f["port"], body, now)
                        record(rec="rx_broadcast", t=now, parsed={
                            k: (v if not isinstance(v, bytes) else v.hex())
                            for k, v in got.items() if k != "payload"})
                    elif f["protocol"] == broadcast4.PROTOCOL:
                        # 0x84, ReliableBroadcastProtocol - the console's trade snapshot. It
                        # retransmits the whole thing until something acks it, so the count runs
                        # into the tens of thousands; what is worth keeping is its sequence, which
                        # every message of OURS has to echo back in its peer-sequence field.
                        st["snapshot_in"] += 1
                        try:
                            got = broadcast4.parse(body)
                        except ValueError:
                            continue
                        st["their_sequence"] = got["sequence"]
                        if got["is_control"] and st["snapshot_total"] is None:
                            st["snapshot_total"] = got["total"]
                            print(f"\n[rx] t={now:6.2f} *** 0x84 SNAPSHOT INCOMING *** "
                                  f"{got['total']} bytes in chunks of {got['chunk_size']}")
                        if got["is_data"] and got["index"] not in st["snapshot_indexes"]:
                            st["snapshot_indexes"].add(got["index"])
                            print(f"[rx]     fragment {got['index']} of the snapshot, "
                                  f"{len(got['body'])} B on the wire")
                        if got["kind"] == broadcast4.KIND_ACK:
                            if st["snapshot_acked"] is None:
                                st["snapshot_acked"] = now
                                print(f"\n[rx] t={now:6.2f} *** IT ACKED OUR SNAPSHOT: base "
                                      f"{got['base']} mask {got['mask']:#x} *** - the first 0x84 "
                                      f"ack this project has ever been sent")
                                if ((args.box_open or args.open_early)
                                        and not st["box_open_sent"]):
                                    # THE OPENER GOES HERE BECAUSE ORDER IS WHAT KILLED sx10.
                                    # The game emits its own command 3 on the FIRST FRAME after the
                                    # trade session is built (0x010c9bb0, gated on the role bit at
                                    # session+0x419) - before either player has picked anything.
                                    # sx10 sent 3 after both offers instead and the console left
                                    # while the player was still in the menu, the same shape command
                                    # 2 produced at sx03. The snapshot ack is the earliest one-shot
                                    # this client has, and it lands about ten seconds before the
                                    # console's own offer.
                                    st["box_open_sent"] = True
                                    st["box_queue"] = ([swsh_trade.box_sync_state(int(c, 0))
                                                        for c in (args.box_open or "").split(",")
                                                        if c.strip()]
                                                       + [swsh_trade.open_content(int(c, 0))
                                                          for c in (args.open_early or "").split(",")
                                                          if c.strip()]
                                                       + st["box_queue"])
                                    st["box_next"] = 0.0
                                    print(f"[tx]     *** OPENING WITH box {args.box_open}, "
                                          f"content {args.open_early} *** "
                                          f"{[p.hex() for p in st['box_queue']]}")
                            # ITS BASE IS A COUNT OF WHAT IT HOLDS, and when that reaches all of
                            # our fragments the transfer is done and the sender says so ONCE with
                            # a 0x19. sw74 watched the base walk 0 -> 1 -> 2 -> 3 and then repeat
                            # 3 four hundred times: it had the whole snapshot and was waiting for
                            # a word we never said.
                            if (st["snapshot_fragments"]
                                    and got["base"] >= st["snapshot_fragments"]
                                    and not st["snapshot_done_sent"]):
                                st["snapshot_done_sent"] = True
                                done = broadcast4.build_done(st["snapshot_seq"], got["sequence"])
                                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), done,
                                                 broadcast4.PROTOCOL,
                                                 args.connect_station_first, port=f["port"],
                                                 message_flags=pia4.MESSAGE_FLAGS,
                                                 destination=args.data_destination),
                                            (host_ip, PIA_PORT))
                                print(f"\n[tx] *** IT HAS ALL {got['base']} OF OUR FRAGMENTS - "
                                      f"sending 0x19, the transfer is complete *** {done.hex()}")
                        elif got["kind"] in (broadcast4.KIND_DONE, broadcast4.KIND_DONE_ACK):
                            print(f"[rx] t={now:6.2f} 0x84 kind {got['kind']:#04x} "
                                  f"seq {got['sequence']}")
                        # ACK IT. Nothing in this project had ever acked 0x84 and the console
                        # retransmits until something does - 19142 messages of one snapshot on
                        # sw71. Every other window here had to be answered before the layer above
                        # it would move; there is no reason this one is different.
                        if args.ack_snapshot:
                            # `body` is already inflated: pia4 acts on the message's own 0x10 flag
                            # before this point, the same way it does for 0x80.
                            for reply in st["snapshot_rx"].feed(body):
                                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), reply,
                                                 broadcast4.PROTOCOL,
                                                 args.connect_station_first, port=f["port"],
                                                 message_flags=pia4.MESSAGE_FLAGS,
                                                 destination=args.data_destination),
                                            (host_ip, PIA_PORT))
                                st["snapshot_acks_out"] += 1
                                if st["snapshot_acks_out"] <= 4:
                                    print(f"[tx]     acked 0x84 {reply[:16].hex()}")
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


        async def data_sender():
            """The FIRST APPLICATION DATA of the project, on 0x7C or on 0x80.

            Every layer under this one is closed in both directions and the game has not moved: 455
            messages in sw52 carrying one payload, `61 00 00 00 0a 00`, repeated while it waits for
            something we have never sent. Both reliable windows are waiting for our sequence 1 - the
            console's broadcast ack asks for it once a second and its 0x7C window has never had an
            ack to send because we have never given it data to acknowledge.

            THE FIRST MESSAGE MUST CARRY FLAG_IS_INITIALIZED (reliable4.FIRST_DATA_FLAGS): while a
            station's stream is unopened the handler at 0x01859ca0 does `tbz w9, #3` and drops
            anything without it in silence, with nothing on the wire to say why.

            It retransmits until the ack comes back, which is what a sliding window does and what
            the console itself did through 1637 messages.
            """
            if args.send_data is None:
                return
            payload = bytes.fromhex(args.send_data)
            with trio.move_on_after(args.send_wait):
                await accepted.wait()
            if not accepted.is_set():
                print(f"\n[tx] no station acceptance in {args.send_wait:.0f}s - sending no data. "
                      f"Data before the mesh is up is an unclassifiable run.")
                return
            await trio.sleep(args.send_after)
            want = args.send_destinations
            if want == "auto":
                want = "console" if args.send_protocol == reliable4.BROADCAST_PROTOCOL else "none"
            dests = [host_constant] if want == "console" else []
            body = reliable4.build_data_message(payload, sequence_id=args.send_sequence,
                                                destinations=dests,
                                                stream_id=args.send_stream)
            flags = pia4.MESSAGE_FLAGS
            wire = body
            if args.send_zlib:
                # The console compresses every 0x80 message it sends and none of its 0x7C ones.
                # The flag is the Pia MESSAGE's, not the window's, so it is a free variable here.
                wire = zlib.compress(body)
                flags |= pia4.MESSAGE_FLAG_ZLIB
            st["phase"] = "data"
            print(f"\n[tx] *** APPLICATION DATA on {args.send_protocol:#04x} *** seq "
                  f"{args.send_sequence} flags {reliable5.flag_names(body[0])} to "
                  f"{[hex(d) for d in dests] or 'everyone (count 0)'}, payload {payload.hex()}"
                  f"{f' zlib {len(body)}->{len(wire)} B' if args.send_zlib else ''}")
            print(f"[tx]     the message: {body.hex()}")
            # A STREAM, NOT ONE MESSAGE. The console sends its own heartbeat 583 times in 180 s
            # and sw61 answered it once; `--send-count` is how many of ours it gets, each new
            # sequence sent only once the last is acknowledged, which is what a window is for.
            deadline = time.monotonic() + args.send_seconds
            seq = args.send_sequence
            answered_serial = None
            while time.monotonic() < deadline:
                if seq - args.send_sequence >= args.send_count:
                    break
                said = st["said_by_proto"].get(args.send_protocol)
                if (args.answer_once and st["offer_pending"] is None
                        and not st["answer_queue"]):
                    # AN ANSWER IS A REPLY TO SOMETHING, NOT A HEARTBEAT. `said` is the last thing
                    # the console put on this protocol and it stays set for the rest of the run, so
                    # every 0.3 s tick re-derives an answer to a payload already answered. sw83
                    # sent our Pokemon offer 859 times over 260 seconds and the trade RPC answer
                    # 1024 times, where the console sent each of its own messages once; the three
                    # payloads this run repeated are exactly the three phases that stalled, and
                    # every message that moved the game on went out exactly once.
                    # AND NEVER WHILE A QUEUED ANSWER IS WAITING. sw85: a rule may be more than
                    # one payload - `ping` is answered `pingReply` then `ping` - and a guard that
                    # looked only at the serial sent the first, starved the second, and left the
                    # console repeating its ping ten times at the very first holder. One message
                    # out in a 327-second run. The queue is work already owed; only an empty one
                    # means there is nothing to say.
                    serial = st["serial_by_proto"].get(args.send_protocol)
                    if serial is not None and serial == answered_serial:
                        await trio.sleep(args.send_period)
                        continue
                    answered_serial = serial
                if (st["offer_pending"] is None and st["box_queue"]
                        and time.monotonic() >= st["box_next"]):
                    # THE QUEUE IS DRAINED HERE, WHERE A PAYLOAD IS CHOSEN, and not in the ack
                    # branch. sx02 put the timer in the ack branch, which only runs on the ack of a
                    # QUEUED payload: the first gate that said "not yet" left nothing pending, so
                    # nothing was queued, so no queued payload was ever acked again and the drain
                    # never ran a second time. One command in 46 seconds where eight were meant to
                    # span the accept. This loop runs every period regardless of what was sent, so
                    # the timer belongs in it.
                    st["offer_pending"] = st["box_queue"].pop(0)
                    st["box_next"] = time.monotonic() + args.box_period
                    print(f"[tx]     *** QUEUED PAYLOAD *** {st['offer_pending'].hex()} "
                          f"({len(st['box_queue'])} left)")
                if st["offer_pending"] is not None:
                    # STICKY UNTIL THE WINDOW MOVES PAST IT. A payload swapped out mid-sequence is
                    # a payload the console may never have seen whole.
                    payload = st["offer_pending"]
                    st["offer_seq"] = seq
                elif args.sync_answers and said:
                    # THE TABLE ON TOP OF THE MIRROR, NEVER INSTEAD OF IT. sw68 and sw70 got the
                    # trade snapshot with a plain per-protocol echo, and that is the only answer
                    # policy this project has ever proven. `SYNC_ANSWERS` covers four payloads and
                    # would leave the other two of sw70's unanswered, so a rule REPLACES the echo
                    # where it has one and the echo stands everywhere else. The one variable this
                    # changes against sw70 is what we say to `ping` and to `pingSynced`.
                    payload, st["answer_queue"] = swsh_trade.next_answer(
                        said, st["answer_queue"], station_id=our_constant,
                        clock_delta=args.rpc_clock_delta, offer_pk8=st["our_pk8"])
                elif args.send_mirror and said:
                    # MIRROR WHAT IT IS SAYING NOW, not what it said first. sw64 moved the game
                    # from state 0x0a to 0x12 and left it there; a peer that follows the state it
                    # is being told is the next thing it can be given.
                    # PER PROTOCOL. A single "what it last said" is shared between windows, so
                    # once the console spoke on 0x80 the 0x7C mirror started echoing THAT back on
                    # 0x7C: sw68 answered `result{}` on 0x7C and got the trainer data, sw69
                    # answered `imReady` there instead and got nothing, and the flag was the only
                    # difference between the two runs.
                    payload = st["said_by_proto"][args.send_protocol]
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests,
                                                    stream_id=args.send_stream)
                wire = zlib.compress(body) if args.send_zlib else body
                for port in [int(p, 0) for p in _expand(args.send_port)]:
                    sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), wire,
                                     args.send_protocol, args.connect_station_first, port=port,
                                     message_flags=flags, destination=args.data_destination),
                                (host_ip, PIA_PORT))
                    st["data_out"] += 1
                record(rec="tx_data", t=time.monotonic() - t0, protocol=args.send_protocol,
                       sequence=seq, message=body.hex(), payload=payload.hex())
                await trio.sleep(args.send_period)
                if st["ack_by_proto"].get(args.send_protocol, 0) > seq:
                    if st["offer_seq"] == seq:
                        print(f"[tx]     *** OUR OFFER WAS ACKNOWLEDGED at sequence {seq} ***")
                        st["offer_pending"], st["offer_seq"] = None, None
                        if args.send_selection == "offer":
                            # EARLY, WHILE IT IS STILL TALKING. The console acks our offer and then
                            # goes quiet until the accept; that quiet window is the only room a
                            # phase opener has, and sw89 spent its pair after the window shut.
                            open_phase(swsh_trade.SELECTION_OFFSET, "SELECTION")
                        if st["box_queue"]:
                            # DRAINED IN THE SENDER LOOP NOW - see the note there. Nothing to do.
                            # THE QUEUE HOLDS PAYLOADS, NOT RECIPES, AND THAT IS THE WHOLE FIX.
                            # sw95 seeded it with built payloads for `--open-content` and with
                            # plain ints for `--box-commands`, and the drain branch called the
                            # command builder on whatever it found. The second opener went in as
                            # bytes, came out through `box_sync_state`, raised, and killed the
                            # nursery at t=25.6 - which the player saw as the console's own error,
                            # seconds after our Pokemon appeared on their screen. Twice in one
                            # session a queue of two different things has cost a run; it holds one
                            # kind of thing now.
                            pass
                        elif (st["pk8_offer_sent"] and not st["trade_ready_sent"]
                                and (args.open_content or args.box_commands)):
                            # ONLY AFTER THE POKEMON, AND sx11 IS WHY. `--box-open` (session 61)
                            # puts a payload in the same queue ten seconds earlier, its ack came
                            # through this branch, and command 1 went out at t=14 with no offer
                            # behind it - so nothing was said after the real offer at t=24 and the
                            # player sat on "en attente d'une reponse" for the whole hold. The
                            # branch means "after OUR POKEMON was acknowledged", never "after any
                            # queued payload was".
                            st["trade_ready_sent"] = True
                            # BOX COMMANDS FIRST, THEN THE OPENERS, AND THE ORDER IS MEASURED.
                            # sw97 sent the 10040/10050 openers INSTEAD of the box command and the
                            # console never displayed our Pokemon at all - it sat on "en attente
                            # d'une reponse" and, notably, did NOT give up: still acking at t=70,
                            # where every earlier run had torn down seconds after the accept. So
                            # `3e4e000012020801` after our offer is what makes the console show it
                            # to the player, and it is not optional.
                            # SWEEP THE COMMAND, BECAUSE A REFUSAL IS AN INSTRUMENT; OPEN THE
                            # PHASES NOBODY HAS OPENED, because a content at offset N has an id at
                            # 10000+N and nxldn-lab's client opens the confirmation with `ping` on
                            # 10040, unprompted.
                            st["box_queue"] = (
                                [swsh_trade.box_sync_state(int(c, 0))
                                 for c in (args.box_commands or "").split(",") if c.strip()]
                                + [_opener_for(int(c, 0))
                                   for c in (args.open_content or "").split(",") if c.strip()])
                            print(f"[tx]     *** AFTER THE OFFER: box {args.box_commands}, "
                                  f"open {args.open_content} *** "
                                  f"{[p.hex() for p in st['box_queue']]}")
                            st["box_next"] = 0.0        # the sender loop takes it from here
                        elif (args.trade_ready and st["pk8_offer_sent"]
                                and not st["trade_ready_sent"]):
                            st["trade_ready_sent"] = True
                            # AND SAY WE ARE READY, on the trade holder. The console has never sent
                            # us these bytes and nxldn-lab's client waits for them before offering,
                            # so either it wants them from us or the roles differ. It is the same
                            # shape that released the snapshot, one holder further along.
                            st["offer_pending"] = swsh_trade.trade_ready()
                            print(f"[tx]     *** SAYING imReady ON THE TRADE HOLDER *** "
                                  f"{st['offer_pending'].hex()}")
                    seq += 1
                    st["data_seqs"] += 1
                    if st["data_seqs"] <= 3 or st["data_seqs"] % 25 == 0:
                        print(f"[tx]     sequence {seq - 1} acknowledged, sending {seq} "
                              f"({st['data_seqs']} of ours acked)")
            if st["data_acked"] is None:
                print(f"\n[tx] {st['data_out']} data messages out, NOTHING acknowledged them. "
                      f"0x80 ack ids seen: {sorted(st['broadcast_ack_ids'])}")
            st["phase"] = "hold"


        async def snapshot_sender():
            """OUR OWN trade snapshot, back at the console on 0x84.

            THE CLEAN NEGATIVE THAT ASKED FOR THIS: sw71 answered the whole sync set and the
            console still sent nothing past its snapshot - the same five payloads as sw70. Both
            published clients that get further send a snapshot of their own before anything else
            happens, and neither of them ever reaches the trade without it. So the hypothesis is
            that a trade is symmetric and the console is waiting for OURS.

            What goes out is the console's own snapshot with the identity moved - a name and a
            trainer id that are not its own, in MyStatus, the trainer card and every party record at
            once (`swsh.trade_payload.rewrite`). Every byte this project has never read stays a real
            byte from a real save, which is the same reason `build_from` exists for one Pokemon.
            """
            if args.send_snapshot is None:
                return
            payload = open(args.send_snapshot, "rb").read()
            if len(payload) != trade_payload.PAYLOAD_LENGTH:
                payload = trade_payload.inflate_short(payload)
            was = trade_payload.read(payload)["trainer_name"]
            # AND THE ACCOUNT ID THE TAIL REPEATS. It is the console's own, and every snapshot
            # before session 60 handed it straight back - which the trade screen never shows,
            # because it draws the partner from MyStatus.
            theirs = trade_payload.tail_account_id(payload, was)
            ours = (bytes(a ^ b for a, b in zip(theirs, b"\x5a" * len(theirs)))
                    if theirs and args.snapshot_account else None)
            payload = trade_payload.rewrite(payload, old_name=was, account_id=ours,
                                            trainer_name=args.snapshot_name,
                                            trainer_id=args.snapshot_tid,
                                            secret_id=args.snapshot_sid)
            fields = trade_payload.read(payload)
            if args.offer_slot:
                # THE POKEMON WE OFFER COMES OUT OF THE PARTY WE ADVERTISED. Offering one the
                # console never saw in our snapshot would be a second difference in the same run,
                # and this way the trainer, the party and the offer all tell one story.
                at = (args.offer_slot - 1) * swsh_pokemon.SIZE_PARTY
                st["our_pk8"] = payload[at:at + swsh_pokemon.SIZE_PARTY]
                ours = swsh_pokemon.read(st["our_pk8"])
                print(f"[tx] we will offer slot {args.offer_slot}: species {ours['species']} "
                      f"{ours['nickname']!r} level {ours['level']}")
            left = payload.count(was.encode("utf-16-le")) if was else 0
            print(f"[tx] the snapshot was {was!r}; {left} copies of that name left in it, "
                  f"and {payload.count(theirs) if theirs else '?'} of its account id "
                  f"{theirs.hex() if theirs else '(not found)'}")
            print(f"\n[tx] our snapshot: trainer {fields['trainer_name']!r} "
                  f"{fields['trainer_id']}/{fields['secret_id']}, party "
                  f"{[p['nickname'] for p in fields['party'] if p]}, "
                  f"consistent {trade_payload.party_matches_trainer(fields)}")

            deadline = time.monotonic() + args.send_seconds + args.send_after + args.send_wait
            while st["snapshot_in"] == 0:
                if time.monotonic() > deadline:
                    print("\n[tx] the console never sent its snapshot; ours stayed home")
                    return
                await trio.sleep(0.2)
            print(f"\n[tx] *** SENDING OUR SNAPSHOT on {broadcast4.PROTOCOL:#04x} *** "
                  f"{len(payload)} bytes")
            sender4 = broadcast4.Sender()
            st["snapshot_fragments"] = len(broadcast4.split(payload, sender4.chunk_size))
            while time.monotonic() < deadline:
                if st["snapshot_done_sent"]:
                    # THE CONSOLE HAS IT ALL AND HAS BEEN TOLD SO. Retransmitting past that is how
                    # a sender talks over the answer it was waiting for.
                    print(f"\n[tx] snapshot complete and acknowledged after "
                          f"{st['snapshot_out']} messages; the window is quiet now")
                    return
                if st["their_sequence"] is not None:
                    sender4.saw(st["their_sequence"])
                st["snapshot_seq"] = sender4.sequence
                for message, compressed in sender4.transfer(payload):
                    flags = pia4.MESSAGE_FLAGS | (pia4.MESSAGE_FLAG_ZLIB if compressed else 0)
                    for port in [int(p, 0) for p in _expand(args.snapshot_port)]:
                        sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), message,
                                         broadcast4.PROTOCOL, args.connect_station_first,
                                         port=port, message_flags=flags,
                                         destination=args.data_destination),
                                    (host_ip, PIA_PORT))
                        st["snapshot_out"] += 1
                    record(rec="tx_snapshot", t=time.monotonic() - t0,
                           message=message[:16].hex(), compressed=compressed)
                    await trio.sleep(args.snapshot_period)
                print(f"[tx]     snapshot sent, {st['snapshot_out']} messages out so far")
                await trio.sleep(args.snapshot_repeat)
            print(f"\n[tx] {st['snapshot_out']} snapshot messages out")


        async def rpc_sender():
            """Answer the trade RPC pair ON THE PORT THE CONSOLE SENDS IT.

            sw79 counted 19145 of these on 0x7C **port 1** while every other application message -
            the ping, the block messages, the Pokemon offer - came in on port 0. Every RPC answer
            before this went out on port 0, which is a window the console does not read them on, so
            the runs that "answered the RPC" had in fact said nothing the game could hear.

            The window on port 1 is its own: its own sequence, its own acks. `reliable_window`
            already keys by (protocol, port); the ack counter now does too.
            """
            if not args.rpc_port_answers:
                return
            port = args.rpc_port
            key = (reliable5.PROTOCOL, port)
            dests = [host_constant] if args.send_destinations != "none" else []
            deadline = time.monotonic() + args.send_seconds + args.send_after + args.send_wait
            seq = reliable4.FIRST_SEQUENCE
            last_answered = None
            answered_serial = None
            while time.monotonic() < deadline:
                said = st["said_by_port"].get(key)
                # A QUEUED MESSAGE OUTRANKS AN ANSWER, and travels on the same window: this port
                # has one sequence and one ack counter, so a phase we OPEN has to go through here
                # rather than beside it.
                if args.rpc_pair:
                    # BOTH MEMBERS, IN ORDER, ONCE PER ENVELOPE. The pair is one act; half of it
                    # repeated is not a slower version of it. Each phase gets answered exactly once.
                    for envelope in sorted({e for e, _ in st["rpc_seen"]}):
                        if envelope in st["rpc_pair_sent"]:
                            continue
                        # NOT `keys` - that name is the session crypto in this scope, and sx19
                        # rebound it to a list of tuples and killed the sender one line later.
                        members = [(envelope, b) for b in swsh_trade.RPC_BASES]
                        if not all(k in st["rpc_seen"] for k in members):
                            continue
                        delta = st["rpc_pair_delta"].get(envelope, args.rpc_clock_delta)
                        both = [swsh_trade.answer_rpc(st["rpc_seen"][k], our_constant, delta)
                                for k in members]
                        if all(b is not None for b in both):
                            st["rpc_pair_sent"].add(envelope)
                            queued = list(both)
                            print(f"[tx]     *** ANSWERING THE {envelope} PAIR, BOTH MEMBERS *** "
                                  f"{[b.hex() for b in both]}")
                            if args.rpc_pair_advance:
                                # THE SAME PAIR AGAIN, ONE STATE LATER. `0x006d59f0` routes a
                                # 40000-family Data on (elementId, ownerId) and hands the body and
                                # the CLOCK to the sub-element that owns that pair; the console's
                                # own pair goes out three times with the clock +2 each burst, and
                                # ours has always gone out once and then been retransmitted
                                # unchanged. A repeated clock is a repeated state.
                                again = [swsh_trade.answer_rpc(
                                    st["rpc_seen"][k], our_constant,
                                    args.rpc_clock_delta + args.rpc_pair_advance)
                                    for k in members]
                                if all(a is not None for a in again):
                                    queued += list(again)
                                    print(f"[tx]     *** AND THE {envelope} PAIR AGAIN AT CLOCK "
                                          f"+{args.rpc_pair_advance} *** "
                                          f"{[a.hex() for a in again]}")
                            # PREPENDED, as sx17 did it - the run that got past the commit. A
                            # phase answer outranks whatever else is waiting on this window.
                            st["rpc_queue"] = queued + st["rpc_queue"]
                pending = st["rpc_queue"][0] if st["rpc_queue"] else None
                answer = pending if pending is not None else (
                    swsh_trade.answer_rpc(said, our_constant, args.rpc_clock_delta)
                    if said else None)
                if answer is None:
                    await trio.sleep(0.1)
                    continue
                if args.rpc_pair and pending is None and st["rpc_pair_sent"]:
                    # Every phase seen so far has been answered; anything further on this window is
                    # the flood sx15 measured. A NEW envelope re-arms the branch above.
                    # ANSWERED ONCE AND THAT IS THE WHOLE ANSWER. Anything further on this window
                    # is the flood sx15 measured.
                    await trio.sleep(args.rpc_period)
                    continue
                if args.answer_once and pending is None:
                    # THE SAME RULE AS THE DATA SENDER, and this window is where it cost the most:
                    # sw83 answered a trade RPC 1024 times, roughly fifty of them on their own
                    # sequence ids, to a console that had asked six times.
                    serial = st["serial_by_port"].get(key)
                    if serial is not None and serial == answered_serial:
                        await trio.sleep(args.rpc_period)
                        continue
                    answered_serial = serial
                if answer != last_answered:
                    last_answered = answer
                body = reliable4.build_data_message(answer, sequence_id=seq, destinations=dests,
                                                   stream_id=args.send_stream)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 reliable5.PROTOCOL, args.connect_station_first, port=port,
                                 message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["rpc_out"] += 1
                if st["rpc_out"] == 1:
                    print(f"\n[tx] *** ANSWERING THE TRADE RPC on 0x7c port {port} *** "
                          f"{answer.hex()}")
                record(rec="tx_rpc", t=time.monotonic() - t0, port=port, sequence=seq,
                       payload=answer.hex())
                await trio.sleep(args.rpc_period)
                if st["ack_by_port"].get(key, 0) > seq:
                    if pending is not None and st["rpc_queue"] and st["rpc_queue"][0] is pending:
                        st["rpc_queue"].pop(0)
                    if st["rpc_acked"] is None:
                        st["rpc_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** THE CONSOLE ACKED OUR RPC on port {port} *** "
                              f"sequence {seq}")
                    seq += 1
            print(f"\n[tx] {st['rpc_out']} RPC answers out on port {port}, "
                  f"{'acknowledged' if st['rpc_acked'] else 'NOTHING acknowledged them'}")


        async def migration_sender():
            """Answer MIGRATION_START on the mesh protocol's reliable port, and keep answering
            until the console acknowledges it.

            THIS IS THE LAST THING THE CONSOLE EVER SAYS. sw81 and sw83 are the only two runs where
            the player pressed accept and they are the only two that carry `440001` on 0x18 port 1;
            in both, the console then went silent on every window for the rest of the run. It is
            not waiting on the application layer at all - it is waiting for a two-byte mesh
            message, and nothing in this project or in any of the four published clients has ever
            sent one. `mesh_protocol` carries the handler addresses.

            The window is its own, like the RPC's: protocol 0x18, port 1, its own sequence and its
            own acks, which `reliable_window` and `ack_by_port` already key correctly.
            """
            if not args.answer_migration:
                return
            key = (mesh.PROTOCOL, mesh.PORT_RELIABLE)
            dests = [host_constant] if args.send_destinations != "none" else []
            deadline = time.monotonic() + args.send_seconds + args.send_after + args.send_wait
            seq = reliable4.FIRST_SEQUENCE
            while time.monotonic() < deadline:
                payload = st["migration_pending"]
                if payload is None:
                    await trio.sleep(0.1)
                    continue
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests,
                                                   stream_id=args.send_stream)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 mesh.PROTOCOL, args.connect_station_first,
                                 port=mesh.PORT_RELIABLE, message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["migration_out"] += 1
                if st["migration_out"] == 1:
                    print(f"\n[tx] *** MIGRATION_RESPONSE on 0x18 port {mesh.PORT_RELIABLE} *** "
                          f"seq {seq}: {body.hex()}")
                record(rec="tx_migration", t=time.monotonic() - t0, sequence=seq,
                       payload=payload.hex())
                await trio.sleep(args.migration_period)
                if st["ack_by_port"].get(key, 0) > seq:
                    if st["migration_acked"] is None:
                        st["migration_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** IT ACKED OUR MIGRATION RESPONSE, "
                              f"t={st['migration_acked']:.2f} ***")
                    # ONE MESSAGE, NOT A STREAM. Repeating a state transition past its ack is
                    # the mistake sw83 made with the Pokemon offer.
                    st["migration_pending"] = None
                    return
            if st["migration_out"] and st["migration_acked"] is None:
                print(f"\n[tx] {st['migration_out']} migration responses out, nothing acked them")


        async def update_mesh_sender():
            """Once we are the host, do the host's job: broadcast UPDATE_MESH.

            sw87 is the whole argument. The console answered our MIGRATION_FINISH and stayed
            healthy - RTT still going, our data still acked, its update session counter unchanged,
            none of sw84's freeze - and then it **stopped sending UPDATE_MESH**, because it had
            just handed that job to us. 1.3 seconds later the link was gone. It had been sending
            one roughly every 2 seconds for the whole run.

            We send the console's own last one with byte [2] set to our index and the counter
            advancing, on 0x18 PORT 0, which is where every one of its own arrived. Building the
            station table from nothing would mean building two 64-byte locations; editing the one
            it has been broadcasting all run means every byte we have not read stays its own.
            """
            if not args.update_mesh:
                return
            deadline = time.monotonic() + args.send_seconds + args.send_after + args.send_wait
            counter = None
            while time.monotonic() < deadline:
                if not (st["we_are_host"] and st["last_update_mesh"] and st["our_index"] is not None):
                    await trio.sleep(0.1)
                    continue
                if counter is None:
                    try:
                        counter = mesh.parse_update_mesh(st["last_update_mesh"],
                                                         version4=True)["update_counter"]
                    except (IndexError, ValueError) as e:
                        print(f"[tx] cannot read the console's update mesh: {e}")
                        return
                counter += 1
                body = mesh.rewrite_update_mesh(st["last_update_mesh"], st["our_index"], counter)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 mesh.PROTOCOL, args.connect_station_first, port=0,
                                 message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["update_mesh_out"] += 1
                if st["update_mesh_out"] == 1:
                    print(f"\n[tx] *** WE ARE THE HOST NOW - UPDATE_MESH on 0x18 port 0 *** "
                          f"{len(body)} B, host index {st['our_index']}, counter {counter}")
                record(rec="tx_update_mesh", t=time.monotonic() - t0, counter=counter,
                       raw=body.hex())
                await trio.sleep(args.update_mesh_period)


        async def block_sender():
            """The SECOND stream, on the protocol the console chose for it.

            sw67 read the whole conversation off the game's own schema: message 97 is
            `gflnet.p2p.sync.ping.pb.SyncPingDataHolder` and message 60000 is
            `gflnet.p2p.block.pb.BlockDataHolder`. The console pings, we answer, it walks
            ping -> pingReply -> pingSynced, and then it says `imReady { isReady: true }` on its
            BROADCAST window and waits. `60ea000012020801` is those bytes; nothing here has ever
            said them back.
            """
            if args.send2_data is None:
                return
            payload = bytes.fromhex(args.send2_data)
            trigger = bytes.fromhex(args.send2_trigger) if args.send2_trigger else None
            deadline = time.monotonic() + args.send_seconds + args.send_after + args.send_wait
            while trigger is not None:
                if st["said_by_proto"].get(args.send2_protocol) == trigger:
                    print(f"\n[tx] the console said {trigger.hex()} on "
                          f"{args.send2_protocol:#04x} - answering it")
                    break
                if time.monotonic() > deadline:
                    print(f"\n[tx] it never said {trigger.hex()} on {args.send2_protocol:#04x}; "
                          f"nothing sent on that window")
                    return
                await trio.sleep(0.2)
            dests = [host_constant] if args.send_destinations != "none" else []
            seq = reliable4.FIRST_SEQUENCE
            while time.monotonic() < deadline:
                if seq - reliable4.FIRST_SEQUENCE >= args.send2_count:
                    break
                body = reliable4.build_data_message(payload, sequence_id=seq, destinations=dests)
                sock.sendto(wrap(keys, our_mac, our_constant, next_nonce(), body,
                                 args.send2_protocol, args.connect_station_first,
                                 port=args.send2_port, message_flags=pia4.MESSAGE_FLAGS,
                                 destination=args.data_destination),
                            (host_ip, PIA_PORT))
                st["block_out"] += 1
                record(rec="tx_block", t=time.monotonic() - t0, protocol=args.send2_protocol,
                       sequence=seq, message=body.hex(), payload=payload.hex())
                if st["block_out"] == 1:
                    print(f"[tx] *** {payload.hex()} on {args.send2_protocol:#04x} *** "
                          f"seq {seq}: {body.hex()}")
                await trio.sleep(args.send_period)
                if st["ack_by_proto"].get(args.send2_protocol, 0) > seq:
                    if st["block_acked"] is None:
                        st["block_acked"] = time.monotonic() - t0
                        print(f"\n[rx] *** IT ACKNOWLEDGED THAT TOO, t={st['block_acked']:.2f} ***")
                    seq += 1
            if st["block_acked"] is None and st["block_out"]:
                print(f"\n[tx] {st['block_out']} out on {args.send2_protocol:#04x}, not acked")

        async def guarded(name, task):
            """Run one sender and SURVIVE its bugs.

            A LIVE RUN MUST NOT DIE OF OUR OWN EXCEPTION. Session 59 hardened every reader for this
            and session 60 was killed twice by senders instead: sw85 by a starved queue, sw95 by a
            builder called on the wrong kind of queue entry. Both times the nursery went down, the
            transmit stopped mid-trade, and what the player saw was the console reporting the
            communication as interrupted - which is exactly what had happened, and it was us who
            left. A task that raises now says so and the rest of the run carries on, so the capture
            is still worth reading and the association is not wasted.
            """
            try:
                await task()
            except Exception as exc:                      # noqa: BLE001 - the whole point
                traceback.print_exc()
                print(f"\n[tx] *** {name} DIED: {exc!r} *** the run continues without it")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(receiver)
            nursery.start_soon(guarded, "joiner", joiner)
            nursery.start_soon(guarded, "data_sender", data_sender)
            nursery.start_soon(guarded, "block_sender", block_sender)
            nursery.start_soon(guarded, "snapshot_sender", snapshot_sender)
            nursery.start_soon(guarded, "rpc_sender", rpc_sender)
            nursery.start_soon(guarded, "migration_sender", migration_sender)
            nursery.start_soon(guarded, "update_mesh_sender", update_mesh_sender)
            await sender()
            await trio.sleep(args.hold)
            nursery.cancel_scope.cancel()

        windows = " / ".join(
            f"{p:#04x}:{port} {w['in']} in {w['acks']} acked through {w['through']}"
            for (p, port), w in sorted(st["windows"].items())) or "no reliable window opened"
        answered = ("NOT acknowledged" if st["data_acked"] is None
                    else f"acknowledged at t={st['data_acked']:.2f}")
        print(f"\n[cx] === {st['rx']} packets in, {st['undecrypted']} that did not decrypt, "
              f"{st['updates']} update sessions, {st['acks']} acks out, "
              f"{st['requests']} connection requests, {st['station_replies']} messages on 0x14, "
              f"{st['requests_in']} of them requests, {st['responses_in']} connection responses "
              f"in, {st['responses']} responses out, {st['acks_out']} station acks out, "
              f"{st['joins_out']} join requests out, {st['mesh_in']} messages on 0x18, "
              f"{st['mesh_acks']} mesh acks out, {st['rtt_in']} RTT in / {st['rtt_out']} answered, "
              f"{st['reliable_in']} reliable in, {windows}, {st['broadcast_in']} on 0x80, "
              f"{st['data_out']} application data out over {st['data_seqs'] + 1} "
              f"sequence ids, {answered}")
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
               windows={f"{p:#04x}:{port}": {"in": w["in"], "acks": w["acks"],
                                              "through": w["through"],
                                              "seqs": sorted(w["seqs"])}
                        for (p, port), w in st["windows"].items()},
               broadcast_in=st["broadcast_in"], data_out=st["data_out"],
               data_acked=st["data_acked"], data_seqs=st["data_seqs"],
               block_out=st["block_out"], block_acked=st["block_acked"],
               their_ack_id=st["their_ack_id"],
               broadcast_ack_ids=sorted(st["broadcast_ack_ids"]),
               broadcast_stray_ids=sorted(st["broadcast_stray_ids"]))
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
    ap.add_argument("--send-data", default=None, metavar="HEX",
                    help="send APPLICATION DATA once the mesh is up - the first of the project. "
                         "The payload as hex; \"610000000a00\" is the six bytes the console "
                         "repeats at us on 0x7C. Nothing is sent without this flag")
    ap.add_argument("--send-protocol", type=lambda s: int(s, 0),
                    default=reliable4.BROADCAST_PROTOCOL,
                    help="0x80 (the broadcast reliable window, the default: it asks us for "
                         "sequence 1 once a second) or 0x7c (the unicast one, which has never had "
                         "an ack to send us because it has never had our data)")
    ap.add_argument("--send-sequence", type=lambda s: int(s, 0), default=reliable4.FIRST_SEQUENCE,
                    help="the sequence id. 1 is what both windows ask for; the first message also "
                         "carries FLAG_IS_INITIALIZED and DEFINES where the stream starts")
    ap.add_argument("--send-stream", type=lambda s: int(s, 0), default=0,
                    help="the stream id. 0 is what the console sends on both protocols")
    ap.add_argument("--send-destinations", choices=("auto", "none", "console"), default="auto",
                    help="the header's destination list. \"console\" names its station constant "
                         "id, which is what its own broadcast acks do to us; \"none\" sends "
                         "count 0, which 0x01859578 never filters and every 0x7C message carries. "
                         "\"auto\" mirrors the console per protocol: none on 0x7C, the console "
                         "on 0x80")
    ap.add_argument("--send-zlib", action="store_true",
                    help="compress the message, the way the console compresses every 0x80 message "
                         "it sends. The flag is the Pia message's (0x10 at version 4), so this is "
                         "free either way - and it is one variable, so sweep it alone")
    ap.add_argument("--send-port", default="0",
                    help="the Pia message port. The console sends its 0x80 acks on 0 AND 1, each "
                         "packet carrying both; \"0,1\" mirrors that")
    ap.add_argument("--send-wait", type=float, default=60.0,
                    help="how long to wait for the station handshake before giving up on sending")
    ap.add_argument("--send-after", type=float, default=5.0,
                    help="seconds after acceptance before the first data message, so the mesh join "
                         "and the RTT exchange are already running when it lands")
    ap.add_argument("--send2-data", default=None, metavar="HEX",
                    help="a SECOND stream, on --send2-protocol, sent once the console says "
                         "--send2-trigger. `60ea000012020801` is BlockDataHolder{imReady:true}, "
                         "which the console says on 0x80 and waits on")
    ap.add_argument("--send2-protocol", type=lambda s: int(s, 0),
                    default=reliable4.BROADCAST_PROTOCOL)
    ap.add_argument("--send2-port", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--send2-trigger", default=None, metavar="HEX",
                    help="wait for this payload on --send2-protocol before sending; omit to send "
                         "as soon as the mesh is up")
    ap.add_argument("--send2-count", type=lambda s: int(s, 0), default=200)
    ap.add_argument("--trade-ready", action="store_true",
                    help="after our offer is acknowledged, send imReady on the TRADE holder "
                         "(20030). The console has never sent these bytes and the published client "
                         "waits for them before it offers, so it may be our turn to say them")
    ap.add_argument("--rpc-port-answers", action="store_true",
                    help="answer the trade RPC on its OWN Pia port with its own reliable window. "
                         "sw79: the console sends 19145 of them on 0x7C port 1 and every answer "
                         "this project had sent went out on port 0, where it does not read them")
    ap.add_argument("--rpc-port", type=lambda s: int(s, 0), default=1)
    ap.add_argument("--rpc-period", type=float, default=0.3)
    ap.add_argument("--answer-migration", action="store_true",
                    help="answer the console's MIGRATION_START on 0x18 port 1 with a "
                         "MIGRATION_RESPONSE. sw81 and sw83 are the only runs where the player "
                         "pressed accept and the only two that carry `440001` there, and in both "
                         "the console then went silent everywhere: the last thing it asks for is "
                         "not an application message at all, it is two bytes of mesh")
    ap.add_argument("--migration-answer", choices=("auto", "finish", "response"), default="auto",
                    help="what to send when the console migrates the mesh. \"auto\" sends "
                         "MIGRATION_FINISH when the start names US as the next host and a "
                         "MIGRATION_RESPONSE when it names anyone else, which is what the binary "
                         "says; \"response\" is sw84's behaviour, kept so the two can be compared")
    ap.add_argument("--open-content", default=None, metavar="N,N,...",
                    help="after our offer is acknowledged, send `ping` on content N's 10000-base "
                         "holder for each N - `382700000a00` for 40, which is exactly the opener "
                         "nxldn-lab's client sends to start the confirmation phase, rebuilt here "
                         "from our own content registry rather than copied")
    ap.add_argument("--confirm-command", type=lambda s: int(s, 0), default=None,
                    metavar="N",
                    help="when the CONFIRMATION envelope (40040) sends a four-byte status whose "
                         "body ends `0100` - the same cue the selection content sends before its "
                         "Pokemon - reply with SyncSaveDataHolder{syncCommand{data:N}} on that "
                         "content's 10000-base holder, id 10040, reliable port 0, and answer the "
                         "status itself on port 1. Content 40 takes a command and not a Pokemon: "
                         "its parser 0x010df6d0 accepts one submessage carrying one int32. Its own "
                         "machine sends 0, 1, 2 and 3 in that order (swsh_trade.SYNC_COMMANDS)")
    ap.add_argument("--confirm-commands", default=None, metavar="N,N,...",
                    help="the handshake form of --confirm-command: send the NEXT of these on each "
                         "new four-byte body the confirmation content puts on elementId 20000. "
                         "Content 40's own machine sends 0,1,2,3 and parks after each, and sx53 "
                         "showed the console climbing two steps and stopping with one command sent")
    ap.add_argument("--confirm-final-delta", type=lambda s: int(s, 0), default=0,
                    metavar="N",
                    help="after the CONFIRMATION content answers our syncCommand with a hash, "
                         "re-arm the 40040 pair and send BOTH members again at this clock delta - "
                         "the move --selection-final-delta makes on 40050, which is what carried "
                         "the selection phase past its own hash. sx52e stalled here")
    ap.add_argument("--selection-final-delta", type=lambda s: int(s, 0), default=0,
                    help="after the selection HASH is answered, send the 40050 pair AGAIN - both "
                         "members - at this clock delta. nxldn-lab's `selection_final_delta` is 9 "
                         "and it is the rung of the ladder we have never climbed: --rpc-pair "
                         "latches per envelope, so our second pair has never gone out. 0 is off")
    ap.add_argument("--open-content-offer", action="store_true",
                    help="make --open-content send our PK8 on the 10000-base holder instead of an "
                         "empty `ping`. sx49b: the ping opened content 50 AND was taken as our "
                         "Pokemon - the console reached the confirmation phase and asked the "
                         "player to trade theirs for an Oeuf, an empty record. Same moment, same "
                         "holder, a Pokemon in it")
    ap.add_argument("--box-on-accept", default=None, metavar="N,N,...",
                    help="send these box commands the moment MIGRATION_START arrives - the only "
                         "signal that says the player pressed accept. sx05: the console keeps "
                         "acking for about five seconds after it, and nothing has ever been sent "
                         "into that window. Every command tried so far landed before the accept, "
                         "which is a different state of the same machine")
    ap.add_argument("--box-period", type=float, default=0.0,
                    help="seconds to wait between the queued post-offer payloads. THE POINT IS TO "
                         "SPAN THE ACCEPT. sw91 sent eight box commands inside 2.5 s, so every one "
                         "of them landed BEFORE the player pressed accept; the console tears down "
                         "on the accept, not on a timer, so a command that only means something "
                         "after it has never been sent. Spread them and the player accepts in the "
                         "middle of the sweep")
    ap.add_argument("--selection-offer", action="store_true",
                    help="when the console follows its selection-phase Pokemon with the status "
                         "whose body ends `0100`, offer OUR Pokemon on that content's 10000-base "
                         "holder (id 10050) on reliable port 0 and answer the status on port 1. "
                         "sx20 is where the console first sent that pair of things and held")
    ap.add_argument("--pair-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, open content N's phase by sending "
                         "the two-member RPC pair for it - 40 is the confirmation, so `689c...`. "
                         "THIS IS THE ONLY THING THAT HAS EVER OPENED A PHASE ON THIS CONSOLE: "
                         "40030 opened the offer and 40050 the selection, both as a pair. sx28 "
                         "ruled out a bare content ping (`382700000a00`) and sx31 a bare sync-120 "
                         "ping (`780000000a00`) - the console answered neither")
    ap.add_argument("--sync-after-offer", type=int, default=None, metavar="N",
                    help="queue a sync on holder N right behind our selection offer, in "
                         "the branch that actually runs when --selection-offer is on. "
                         "--sync-after-hash cannot fire there: this one can")
    ap.add_argument("--sync-field", type=int, default=1, choices=(1, 2, 3),
                    help="which SyncPingDataHolder field --sync-after-hash sends: 1 ping "
                         "(sx31, and the wrong one), 2 pingReply, 3 pingSynced - which is "
                         "what the trace this project follows records, `780000001a00`")
    ap.add_argument("--sync-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, send `ping` on sync holder N (120 "
                         "is the confirmation's) on port 0. sx28 measured the whole chain: the "
                         "console drives 97, 60000, 110 and 130 itself and opens the selection "
                         "phase the instant 130's pingSynced lands - and **120 never appears at "
                         "all**. `SYNC_ANSWERS` knows how to answer 120; nothing has ever started "
                         "it. Opening content 40 directly did nothing, which fits: the phase "
                         "follows its sync")
    ap.add_argument("--open-after-hash", type=int, default=None, metavar="N",
                    help="once a hash body has been answered, `ping` content N's 10000-base holder "
                         "on port 0 to open the next phase - 40 is the confirmation, so this sends "
                         "`382700000a00`. sx24 is why: the console stopped sending 40050 the "
                         "instant our hash answer went out and then said nothing at all, and Pia "
                         "retransmits anything it is still waiting on, so silence there means "
                         "satisfied. Something has to open the phase after it")
    ap.add_argument("--rpc-bodies", action="store_true",
                    help="answer every DISTINCT (envelope, base, field-5 body) in the 40000 band "
                         "once, on top of the opening pair. The clock advances on every message so "
                         "the payload cannot be the key, but the body can: `00000000` and "
                         "`000018fc` are the openers and anything else is something new. sx21 "
                         "stalled on a 40050 member whose body was the hash `c7772899`, which the "
                         "per-envelope guard had already stopped answering")
    ap.add_argument("--rpc-pair", action="store_true",
                    help="answer the console's 40030 RPC as the PAIR it is: collect both members "
                         "one per base, 10000 then 20000 - keyed on the BASE FIELD, because "
                         "nxldn-lab's `payload[5] in (0x19, 0x1A)` is the inner length and it moves "
                         "with the sender's station-id varint: sx16's console sent 0x1A/0x1B - "
                         "send both once in that order, and then say nothing more on this window. "
                         "sx15 measured what we do instead - 459 copies of ONE member and never "
                         "the other - because `said_by_port` keeps only the last thing said. "
                         "`nxldn-lab`, which completes trades against a real console, sends the "
                         "pair once and only when both members are in hand")
    ap.add_argument("--open-early", default=None, metavar="N,N,...",
                    help="`ping` content N's 10000-base holder at the 0x84 snapshot ack, before "
                         "either side offers. **CONTENT 30 HAS NEVER BEEN OPENED** - sw98 tried 40 "
                         "and 50 and nobody tried the box content's own. The console's box SEND is "
                         "gated on a ready bool at content+0x4c which only `0x010ce040` sets, on a "
                         "zero result code, and until it is set every command the game tries to "
                         "send is parked in content+0x48 and never goes out. A parked command that "
                         "does not match the next one sets the error byte +0x4d, and the session "
                         "update `0x010c9bb0` turns that into trade state 9 - error, abort, nothing "
                         "on the application layer. That is the observed failure exactly")
    ap.add_argument("--box-open", default=None, metavar="N,N,...",
                    help="send these box commands as soon as the console acks our 0x84 snapshot - "
                         "BEFORE either side offers a Pokemon. The game sends command 3 exactly "
                         "once, on the first frame after its trade session is built and only when "
                         "the role bit at session+0x419 is clear (0x010c9bb0), so one of the two "
                         "sides owes the other an opener before anything else happens. sx10 sent 3 "
                         "AFTER both offers and the console left while the player was still "
                         "picking - the value may be right and the order wrong")
    ap.add_argument("--box-commands", default=None, metavar="N,N,...",
                    help="after our offer is acknowledged, send boxSyncStateCommand{data:N} on the "
                         "trade holder for each N in turn, one per acknowledged sequence. 20030 is "
                         "a BoxSyncStateDataHolder and its field 2 is a command enum; this project "
                         "has only ever sent 1, and nxldn-lab's capture of a real trade has 4 too")
    ap.add_argument("--snapshot-account", action="store_true",
                    help="replace the ten-byte account id the snapshot's tail repeats either side "
                         "of the trainer name. It is the CONSOLE'S OWN and we have been handing it "
                         "back all along; a console that refuses to trade with itself would refuse "
                         "exactly where this one does, after the screen has already drawn PkCamp")
    ap.add_argument("--selection-offer-data", action="store_true",
                    help="with --selection-offer, answer the console's selection status with our "
                         "PK8 in field 5 (`body`) of a 40050 Data carrying OUR ownerId, on the RPC "
                         "port, instead of a PokemonTradeDataHolder on 10050 port 0. Session 62: "
                         "content 50's receive handler resolves the sender to a station index and "
                         "drops silently when it cannot, and the holder shape carries no owner")
    ap.add_argument("--selection-offer-sweep", action="store_true",
                    help="send the shapes sx34-sx44 have not tried: our PK8 as a Data on "
                         "elementId 10000, and as a holder on the 30000-base id (30050), "
                         "which the binary says every content registers and nobody here "
                         "has ever put on the air. Deliberately not one variable")
    ap.add_argument("--selection-offer-high", action="store_true",
                    help="with --selection-offer, answer the selection status with our PK8 as a "
                         "PokemonTradeDataHolder on the 20000-base holder (id 20050), which is "
                         "where the BOX phase's own Pokemon rides one content over. Overrides "
                         "--selection-offer-mirror and --selection-offer-data")
    ap.add_argument("--selection-offer-mirror", action="store_true",
                    help="with --selection-offer, answer the selection status with our PK8 in a "
                         "40050 carrying the console's OWN field set - syncId, clock, body, and "
                         "neither elementId nor ownerId, which is how its own selection offer "
                         "decodes (sx36). Overrides --selection-offer-data")
    ap.add_argument("--offer-echo", action="store_true",
                    help="offer back the exact PK8 the console just offered us, unchanged, instead "
                         "of one out of --send-snapshot. The control for \"is it our record it is "
                         "refusing\": these bytes came out of its own save and cannot be illegal")
    ap.add_argument("--offer-on-50", action="store_true",
                    help="put our PK8 in field 5 of the 40050 pair's second member. Content 50 is "
                         "PokemonTradeDataHolder - the transfer - where content 30 is the box "
                         "exchange this project has been doing since sw75; nxldn-lab reads a "
                         "344-byte PK8 out of exactly that field")
    ap.add_argument("--send-selection", default=None, choices=("offer", "migration"),
                    help="WHEN to open the selection phase with a 40050 pair on 0x7c port 1. "
                         "\"offer\" sends it as soon as our offer is acknowledged, which is the "
                         "only window the console is still reading in; \"migration\" is sw89's "
                         "timing and went out after the console had already stopped. OPEN the "
                         "40050 pair on 0x7c port 1. It is the same envelope as the 40030 the "
                         "console sends us, at offset 50 with our own station id - our builder "
                         "reproduces its 40030 pair byte for byte, so only the offset is new")
    ap.add_argument("--update-mesh", action="store_true",
                    help="once the migration makes us the host, broadcast UPDATE_MESH the way the "
                         "console did - its own last one with the host index set to ours. sw87: "
                         "the console accepted our MIGRATION_FINISH, stopped sending these, and "
                         "the mesh was gone 1.3 s later because nothing took over")
    ap.add_argument("--update-mesh-period", type=float, default=1.0,
                    help="how often to broadcast it; the console sent one about every 2 s")
    ap.add_argument("--migration-period", type=float, default=0.3,
                    help="how often to retransmit the migration response until it is acked")
    ap.add_argument("--answer-once", action="store_true",
                    help="answer each payload the console sends ONCE instead of re-deriving an "
                         "answer to its last payload every period. sw83 sent the Pokemon offer "
                         "859 times and the trade RPC answer 1024 times because `said` never "
                         "clears; the console sends each of its own messages once, and so does "
                         "every published client")
    ap.add_argument("--offer-slot", type=lambda s: int(s, 0), default=0,
                    help="which party slot of --send-snapshot to offer back, 1-6; 0 offers "
                         "nothing and only records what the console offers us")
    ap.add_argument("--save-offered", default=None, metavar="FILE",
                    help="write the PK8 the console offers to this file")
    ap.add_argument("--rpc-clock-delta", type=lambda s: int(s, 0), default=5,
                    help="how far to advance a trade RPC's clock in our answer. 5 is nxldn-lab's "
                         "and is the one number in this path nothing here has measured")
    ap.add_argument("--rpc-pair-advance", type=lambda s: int(s, 0), default=0,
                    help="after answering an RPC pair, send BOTH members again with the clock "
                         "advanced by this much. The console advances its own pair's clock by 2 "
                         "each burst (sx45r1_6: b41c, b61c, b81c) and every answer this project "
                         "has sent carries ONE clock, repeated - so our state never moves. "
                         "nxldn-lab sends the pair and then the pair again at +2, which is the "
                         "only thing in its selection sequence we have never done. 0 is off")
    ap.add_argument("--selection-start", action="store_true",
                    help="send our own 40050 pair the moment the console says id 130 pingSynced, "
                         "before its own selection burst. nxldn-lab's client opens the selection "
                         "phase this way and nothing here has ever opened one; the console sends "
                         "820000001a00 in our own captures 0.3 s before its 40050 burst")
    ap.add_argument("--ack-snapshot", action="store_true",
                    help="ACK the console's 0x84 fragments (kind 0x21, a contiguous base and a "
                         "bitmask). Nothing here has ever acked this protocol, which is why the "
                         "console retransmits one snapshot 19142 times and never moves on")
    ap.add_argument("--send-snapshot", default=None, metavar="FILE",
                    help="a 3456-byte trade snapshot to send back on 0x84 once the console sends "
                         "its own. A short session-58 payload is inflated first. The identity is "
                         "REWRITTEN by --snapshot-name/-tid/-sid so we are not the console")
    ap.add_argument("--snapshot-name", default="PkCamp")
    ap.add_argument("--snapshot-tid", type=lambda s: int(s, 0), default=12345)
    ap.add_argument("--snapshot-sid", type=lambda s: int(s, 0), default=54321)
    ap.add_argument("--snapshot-port", default="0",
                    help="Pia port(s) for our 0x84 messages; the console sends on 0")
    ap.add_argument("--snapshot-period", type=float, default=0.05,
                    help="between our own fragments")
    ap.add_argument("--snapshot-repeat", type=float, default=2.0,
                    help="between whole re-sends; the console retransmits its own until acked")
    ap.add_argument("--sync-answers", action="store_true",
                    help="answer with `pokeldn.swsh.trade.SYNC_ANSWERS` instead of echoing one "
                         "payload: the ping, and the three other sync holders the console is "
                         "expected to raise after the trade snapshot. A payload with no rule is "
                         "REPORTED and left unanswered - that report is the point of the run")
    ap.add_argument("--send-mirror", action="store_true",
                    help="send back whatever the console last said on this protocol, rather than "
                         "the fixed --send-data. --send-data is still the FIRST payload, before it "
                         "has said anything")
    ap.add_argument("--send-count", type=lambda s: int(s, 0), default=1,
                    help="how many sequence ids of ours to send in all. 1 is sw61's single "
                         "message; a larger number mirrors the console, which sends its own "
                         "heartbeat 583 times in 180 s and had exactly one back")
    ap.add_argument("--send-period", type=float, default=1.0,
                    help="the retransmit interval. A window retransmits until it is acked")
    ap.add_argument("--send-seconds", type=float, default=60.0,
                    help="how long to keep retransmitting if nothing acknowledges it")
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
