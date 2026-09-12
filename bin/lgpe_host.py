#!/usr/bin/env python3
"""Host a Let's Go Pikachu trade session, so the console joins us and speaks first.

The console's trade screen alternates hosting and scanning every few seconds, so it will find and
join a network that carries Let's Go's own title, passphrase and advertisement. A joining Let's Go
drives the session: it sends the station connection request, the mesh join request, its clone
announcements and, once the game is satisfied, the first message of the game's own protocol, which
is the thing a joiner of ours cannot synthesise.

    sudo ./.venv/bin/python bin/lgpe_host.py --seconds 180 --player-name PkCamp

    (them) Let's Go Pikachu: menu -> Communiquer -> Communication locale -> Echange,
           link code Pikachu, Pikachu, Pikachu, then wait on the search screen.

Every datagram in and out goes to --capture as one JSON line, and any game payload the console
sends is written beside it. docs/lgpe_session.md has every layout this speaks.
"""
import argparse
import json
import os
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn.ldn import clone, pia3, pia4, reliable3, station4, station9, sync_clock
from pokeldn.ldn import local_protocol as lp
from pokeldn.ldn import mesh_protocol as mp
from pokeldn.ldn import rtt_protocol as rtt
from pokeldn.ldn.station_protocol import ldn_constant_id, ldn_service_variable_id, station_location
from pokeldn.ldn.transport import HostTransport, find_ap_phy
from pokeldn.host_support import resolve_keys
from pokeldn.lgpe import (APPLICATION_VERSION, COMM_ID_PIKACHU, MAX_PARTICIPANTS, PASSPHRASE,
                          PIA_PORT, SCENE_ID, SSID, build_advertise_data, packet_iv, session_keys)
from pokeldn.lgpe import local_host, mesh_host

HOST_INDEX = 0
JOINER_INDEX = 1
HOST_BIT = 1 << HOST_INDEX
JOINER_BIT = 1 << JOINER_INDEX
KEEPALIVE_PROTOCOL = 0x08


class Advertisement:
    """What we advertise, and the keys that follow from it."""

    def __init__(self, network_id=None, session_param=None):
        self.network_id = network_id if network_id is not None else random.getrandbits(32)
        self.session_param = (session_param if session_param is not None
                              else random.getrandbits(32))
        self.data = build_advertise_data(self.network_id, self.session_param)
        self.keys = session_keys(self)

    @property
    def application_data(self):
        return self.data


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=180.0, help="how long to host")
    ap.add_argument("--player-name", default="PkCamp",
                    help="the nickname our connection response carries")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldn-tap")
    ap.add_argument("--ap-ifname", default="ldn")
    ap.add_argument("--mon-ifname", default="ldn-mon")
    ap.add_argument("--channel", type=int, default=6)
    ap.add_argument("--no-skip-encryption", action="store_true",
                    help="let the LDN layer encrypt in software. The Archer T3U wants the "
                         "hardware path, which is the default here")
    ap.add_argument("--no-accept-decrypted-ccmp", action="store_true",
                    help="do not accept the frames rtw88 has already decrypted. With this the "
                         "host reads nothing on that adapter")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--capture", default=None, help="every datagram, one JSON line each")
    ap.add_argument("--variable-id", type=lambda s: int(s, 0), default=0x0C0C0C0C,
                    help="our own variable id, any nonzero value")
    ap.add_argument("--protocol", type=int, default=1,
                    help="the LDN advertisement protocol. A title sees only its own: Let's Go "
                         "advertises and scans on 1, measured off the console's own beacon")
    ap.add_argument("--random-ssid", action="store_true",
                    help="let the LDN layer pick the session id. A Let's Go network's is the "
                         "fixed value every console advertises, which is the default here")
    ap.add_argument("--network-id", type=lambda s: int(s, 0), default=None)
    ap.add_argument("--session-param", type=lambda s: int(s, 0), default=None)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if os.geteuid() != 0:
        print("[lgh] must run as root (LDN needs the raw radio)"); return 1
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[lgh] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[lgh] prod.keys not found at {keys_path!r}"); return 2

    adv = Advertisement(args.network_id, args.session_param)
    print(f"[lgh] advertising network id {adv.network_id:#010x} session param "
          f"{adv.session_param:#010x}")
    print(f"[lgh] {adv.keys}")

    cap = open(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n"); cap.flush()

    host = HostTransport(app_data=adv.data, password=PASSPHRASE, nickname=args.player_name,
                         keys_path=keys_path, local_comm_id=COMM_ID_PIKACHU, scene_id=SCENE_ID,
                         app_version=APPLICATION_VERSION, max_participants=MAX_PARTICIPANTS,
                         phyname=phy, ifname=args.ifname, ap_ifname=args.ap_ifname,
                         mon_ifname=args.mon_ifname, channel=args.channel,
                         skip_encryption=not args.no_skip_encryption,
                         accept_decrypted_ccmp=not args.no_accept_decrypted_ccmp,
                         ssid=None if args.random_ssid else SSID, protocol=args.protocol)
    if not host.start():
        print("[lgh] the AP did not come up"); return 3
    print(f"[lgh] hosting: ssid={host.ssid.hex()} us={host.our_ip}/{host.our_mac.hex()}")
    record(rec="target", network_id=adv.network_id, session_param=adv.session_param,
           application_data=adv.data.hex(), session_key=adv.keys.session_key.hex(),
           our_ip=host.our_ip, our_mac=host.our_mac.hex())

    session = Session(host, adv, args, record)
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < args.seconds:
            session.poll()
            time.sleep(0.005)
    except KeyboardInterrupt:
        print("[lgh] interrupted")
    finally:
        host.stop()
        if cap:
            cap.close()
    print(f"[lgh] done: {session.rx} datagrams in, {session.tx} out, "
          f"{len(session.payloads)} game payload(s)")
    return 0


class Session:
    """One console's session, from its connection request to its game payloads."""

    def __init__(self, host, adv, args, record):
        self.host, self.adv, self.args, self.record = host, adv, args, record
        self.keys = adv.keys
        self.t0 = time.monotonic()
        self.rx = self.tx = 0
        self.nonce = 0
        self.peer_ip = None
        self.peer_mac = None
        self.peer_location = None
        self.peer_variable_id = 0
        self.our_const = ldn_constant_id(host.our_mac)
        self.our_location = station_location(host.our_ip, PIA_PORT, self.our_const,
                                             args.variable_id,
                                             ldn_service_variable_id(host.our_mac),
                                             nat_flags=0, nat_location=0, public=False)
        self.ack_id = 1
        self.seen = {}
        self.window = reliable3.Window()
        self.payloads = []
        self.clone = None
        self.update_counter = 0
        self.session_sequence = 1
        self.local_network_id = random.getrandbits(32)
        self.next_update = 0.0
        self.next_rtt = 0.0
        self.joined = False

    # -- plumbing ---------------------------------------------------------------------------
    def now(self):
        return time.monotonic() - self.t0

    def ms(self):
        return int(self.now() * 1000)

    def send(self, payload, protocol, destination=JOINER_BIT,
             flags=pia3.MESSAGE_FLAG_BITMAP, **what):
        """Everything a host sends carries the bitmap flag and its own constant id as the source.
        The station and mesh-join messages are addressed to 0 and the rest to the joiner's bit,
        which is what a retail console does (docs/lgpe_session.md)."""
        if self.peer_ip is None:
            return
        body = pia3.build_message(payload, protocol=protocol, source=self.our_const, port=0,
                                  destination=destination, message_flags=flags)
        self.nonce += 1
        nonce8 = self.nonce.to_bytes(8, "big")
        iv = packet_iv(self.keys, self.host.our_mac, nonce8, source_id=0)
        pkt = pia3.build_packet(self.keys.session_key, iv, body, station=HOST_INDEX,
                                nonce8=nonce8)
        self.host.send(pkt, self.peer_ip)
        self.tx += 1
        self.record(rec="tx", t=round(self.now(), 3), to=self.peer_ip, len=len(pkt),
                    data=pkt.hex(), **what)

    def decrypt(self, data):
        hdr = pia4.PiaHeader4.parse(data)
        ct = pia4.ciphertext(data)
        for mac in (self.peer_mac, self.host.our_mac):
            if not mac:
                continue
            for sid in sorted({hdr.station, 0, JOINER_INDEX}):
                iv = packet_iv(self.keys, mac, hdr.nonce8, source_id=sid)
                pt = pia4.decrypt_payload(self.keys.session_key, iv, ct, hdr.tag)
                if pt is not None:
                    return hdr, pt
        return hdr, None

    # -- the session ------------------------------------------------------------------------
    def poll(self):
        for participant in list(self.host.participants):
            index, ip, mac, name = participant
            if self.peer_ip is None:
                self.peer_ip, self.peer_mac = ip, bytes(mac)
                who = bytes(name).split(b"\0")[0]
                print(f"[lgh] *** CONSOLE JOINED *** idx={index} ip={ip} "
                      f"mac={bytes(mac).hex()} name={who!r}")
                self.record(rec="seat", ip=ip, mac=bytes(mac).hex(), name=bytes(name).hex())
        for payload, src_ip in self.host.recv():
            if not pia3.is_pia3(payload):
                continue
            if self.peer_ip is None:
                self.peer_ip = src_ip
            self.rx += 1
            self.record(rec="rx", t=round(self.now(), 3), src=src_ip, len=len(payload),
                        data=payload.hex())
            hdr, pt = self.decrypt(payload)
            if pt is None:
                if self.rx <= 5:
                    print(f"[lgh] a datagram from {src_ip} did not authenticate")
                continue
            for m in pia3.parse_packet(pt):
                self.handle(m["protocol"], m["payload"])
        self.tick()

    def tick(self):
        now = time.monotonic()
        if self.peer_ip is None:
            return
        # A host speaks first: a console that associates and hears nothing leaves again. The
        # update session goes out from the moment a station is seated, the mesh once it has joined.
        if now >= self.next_update:
            self.next_update = now + 2.0
            self.broadcast_session()
        if not self.joined:
            return
        if now >= self.next_rtt:
            self.next_rtt = now + 1.0
            self.send(rtt.build_v3(rtt.REQUEST, int(now * rtt.TICK_HZ_V3)), rtt.PROTOCOL)
        if self.clone is not None:
            for out in self.clone.poll(now):
                self.send(out, clone.PROTOCOL)

    def broadcast_session(self):
        nodes = [(self.host.our_ip, PIA_PORT, 0)]
        if self.peer_ip:
            nodes.append((self.peer_ip, PIA_PORT, 1))
        body = local_host.build_update_session(
            self.session_sequence, self.local_network_id, self.args.variable_id,
            ldn_service_variable_id(self.host.our_mac), self.our_const.to_bytes(8, "big"), nodes)
        self.session_sequence += 1
        self.send(body, lp.PROTOCOL, destination=0,
                  flags=pia3.MESSAGE_FLAG_BITMAP | pia3.MESSAGE_FLAG_UNBUNDLED)
        if not self.joined:
            return
        self.update_counter += 1
        entries = [(self.our_location, HOST_INDEX)]
        if self.peer_location:
            entries.append((self.peer_location, JOINER_INDEX))
        self.send(mesh_host.build_update_mesh(entries, self.update_counter), mp.PROTOCOL)

    def handle(self, protocol, pl):
        first = pl[0] if pl else -1
        key = (protocol, first)
        if key not in self.seen:
            self.seen[key] = 0
            print(f"[lgh] first {protocol:#04x} type {first:#04x} ({len(pl)}B) {pl[:24].hex()}")
        self.seen[key] += 1
        if protocol == station9.PROTOCOL:
            self.station(pl)
        elif protocol == mp.PROTOCOL:
            self.mesh(pl)
        elif protocol == lp.PROTOCOL:
            pass                                   # the joiner's acks need no answer
        elif protocol == sync_clock.PROTOCOL:
            m = sync_clock.parse_message(pl)
            if m is not None and m[1] == 0:
                self.send(struct.pack(">QQ", m[0], self.ms()), sync_clock.PROTOCOL)
        elif protocol == rtt.PROTOCOL:
            ans = rtt.response_for_v3(pl)
            if ans is not None:
                self.send(ans, rtt.PROTOCOL)
        elif protocol == KEEPALIVE_PROTOCOL:
            self.send(b"", KEEPALIVE_PROTOCOL)
        elif protocol == clone.PROTOCOL:
            if self.clone is None:
                self.clone = clone.Participant(time.monotonic(), dest=JOINER_BIT, own=HOST_BIT,
                                               station=HOST_INDEX)
            for out in self.clone.receive(pl, time.monotonic()):
                self.send(out, clone.PROTOCOL)
        elif protocol == reliable3.PROTOCOL:
            r = reliable3.parse(pl)
            for out in self.window.receive(pl):
                self.send(out, reliable3.PROTOCOL)
            if r and r["size"]:
                self.payloads.append(r["payload"])
                name = f"{self.args.capture or 'scratchpad/lgpe_host'}.payload{len(self.payloads)}.bin"
                open(name, "wb").write(r["payload"])
                print(f"[lgh] *** THE CONSOLE'S GAME PAYLOAD *** {r['size']}B -> {name}")
                print(f"[lgh]     {r['payload'][:48].hex()}")

    def station(self, pl):
        kind = pl[0]
        if kind == station9.CONNECTION_REQUEST:
            ack = station9.ack_id_of(pl)
            self.peer_location = pl[station9.OFF_LOCATION:-4]
            try:
                self.peer_variable_id = station4.parse_station_location(
                    self.peer_location)["variable_id"]
            except Exception:
                self.peer_variable_id = 0
            # what a console does in this order: its own inverse request, the ack, its response
            # the inverse request carries the connection id the peer chose for its own request;
            # the console checks it against the record it keeps for us and drops a zero
            inverse = station9.build_connection_request(
                ldn_constant_id(self.peer_mac) if self.peer_mac else 0, self.peer_variable_id,
                self.our_location, ack_id=self.ack_id, connection_id=0xEC,
                inverse_connection_id=pl[station9.OFF_CONNECTION_ID], is_inverse=True)
            self.ack_id += 1
            self.send(inverse, station9.PROTOCOL, destination=0, kind="inverse_request")
            self.send(station9.build_ack(ack), station9.PROTOCOL, destination=0)
            resp = station9.build_connection_response(
                ldn_constant_id(self.peer_mac) if self.peer_mac else 0,
                self.peer_variable_id, ack_id=self.ack_id,
                network_id=int.from_bytes(self.keys.network_id_le, "little"),
                player_name=self.args.player_name)
            self.ack_id += 1
            self.send(resp, station9.PROTOCOL, destination=0, kind="connection_response")
            print(f"[lgh] answered the console's connection request ({len(resp)} B)")
        elif kind == station9.CONNECTION_RESPONSE:
            self.send(station9.build_ack(station9.ack_id_of(pl)), station9.PROTOCOL,
                      destination=0)

    def mesh(self, pl):
        if pl[0] == mp.JOIN_REQUEST:
            ack = mp.read_ack_id(pl)
            entries = [(self.our_location, HOST_INDEX)]
            if self.peer_location:
                entries.append((self.peer_location, JOINER_INDEX))
            self.send(mesh_host.build_join_response(entries, ack), mp.PROTOCOL,
                      destination=0, kind="join_response")
            self.joined = True
            # the host starts the clone protocol: in a real session its first clock request goes
            # out about 40 ms after the join response
            self.clone = clone.Participant(time.monotonic(), dest=JOINER_BIT, own=HOST_BIT,
                                           station=HOST_INDEX)
            print("[lgh] *** THE CONSOLE JOINED THE MESH *** answered its join request; "
                  "starting the clone protocol")
            self.broadcast_session()


if __name__ == "__main__":
    sys.exit(main())
