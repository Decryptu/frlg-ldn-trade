#!/usr/bin/env python3
"""Scan for a Let's Go Pikachu / Eevee LDN session, take a seat, and listen.

Three layers, each a measurement the next one needs:

  1. `--scan-only`: report every advertisement seen and decode the Pia application-data header
     (network id, password CRC32, system communication version, session param). The password CRC
     is what the three-Pokemon link code becomes; read it off a session hosted with a known code.
  2. associate with the 64-byte passphrase read out of the binary and hold the seat for `--hold`
     seconds. A seat in the LDN session is not a seat in the game's session; a quiet screen is
     expected.
  3. while seated, every UDP datagram on port 12345 is recorded to `--capture` as hex and run
     through the version-3 header parser and the session key derived from the advertisement. A
     packet that authenticates prints its plaintext head, which is where the message framing
     (Pia 5.11-5.12 against 5.14-5.17) is read from.

Nothing is sent. `docs/lgpe_session.md` has the constants and their addresses.
"""
import argparse
import json
import os
import select
import socket
import struct
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED_LDN = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED_LDN):
    sys.path.insert(0, BUNDLED_LDN)

import trio
import ldn
from pokeldn.ldn import pia3, pia4
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.host_support import resolve_keys
from pokeldn.lgpe import (COMM_ID_PIKACHU, PASSPHRASE, PIA_PORT, PIA_VERSION, packet_iv,
                          session_keys)
from pokeldn.lgpe.session import APP_HEADER_SIZE

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]

KNOWN = {0x0100000011D90000: "BDSP", 0x0100ABF008968000: "Sword",
         COMM_ID_PIKACHU: "Let's Go Pikachu"}


def cleanup_stale():
    import subprocess
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(net):
    tag = KNOWN.get(net.local_communication_id, "")
    return (f"comm_id=0x{net.local_communication_id:016x}{' (' + tag + ')' if tag else ''} "
            f"scene={net.scene_id} version={net.version} app_version={net.app_version} "
            f"ch={net.channel} {net.num_participants}/{net.max_participants}")


def app_header(app):
    """The Pia 5.9-5.18 application-data header, little-endian, as a dict. Nothing is assumed
    about the game's bytes after it."""
    if len(app) < APP_HEADER_SIZE:
        return {"short": len(app)}
    network_id, crc, sysver, hsize, _pad, param, zero8 = struct.unpack_from("<IIBBHIQ", app, 0)
    return {"network_id": f"{network_id:#010x}", "password_crc32": f"{crc:#010x}",
            "system_comm_version": sysver, "header_size": hsize,
            "session_param": f"{param:#010x}", "zero8": f"{zero8:#x}",
            "game_data": app[hsize:].hex() if hsize <= len(app) else None}


def facts_of(net):
    app = bytes(getattr(net, "application_data", b"") or b"")
    return {
        "ssid": net.ssid.hex(),
        "server_random": bytes(getattr(net, "server_random", b"") or b"").hex(),
        "application_data": app.hex(),
        "app_header": app_header(app),
        "nonce": bytes(getattr(net, "nonce", b"") or b"").hex(),
        "challenge": getattr(net, "challenge", None),
        "local_communication_id": f"{net.local_communication_id:#018x}",
        "scene_id": net.scene_id,
        "version": net.version,
        "app_version": net.app_version,
        "channel": net.channel,
        "num_participants": net.num_participants,
        "max_participants": net.max_participants,
        "address": str(net.address),
        "participants": [
            {"ip": str(getattr(p, "ip_address", "")),
             "mac": bytes(getattr(p, "mac_address", b"") or b"").hex(),
             "name": bytes(getattr(p, "name", b"") or b"").split(b"\0")[0].decode("utf-8", "replace"),
             "connected": bool(getattr(p, "connected", False))}
            for p in (getattr(net, "participants", []) or [])],
    }


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


def try_decrypt(keys, data, macs):
    """-> (header, plaintext or None, source_mac or None). The IV needs the sender's MAC, which the
    datagram does not carry; every MAC the LDN layer knows is tried, with the header's station byte
    and 0 as the source id."""
    hdr = pia4.PiaHeader4.parse(data)
    ct = pia4.ciphertext(data)
    for mac in macs:
        for sid in sorted({hdr.station, 0}):
            iv = packet_iv(keys, mac, hdr.nonce8, source_id=sid)
            pt = pia4.decrypt_payload(keys.session_key, iv, ct, hdr.tag)
            if pt is not None:
                return hdr, pt, mac, sid
    return hdr, None, None, None


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None,
                    help="local_communication_id to join, hex. Omit to join the only unknown one")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11,36,40,44,48")
    ap.add_argument("--dwell", type=float, default=0.8)
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--passphrase", default=None, help="override, as ASCII")
    ap.add_argument("--hold", type=float, default=60.0)
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--facts", default="scratchpad/lgpe_net_facts.json")
    ap.add_argument("--capture", default=None,
                    help="jsonl of every datagram seen while seated, hex, with its verdict")
    return ap


def pick(nets, want):
    if want is not None:
        return next((n for n in nets if n.local_communication_id == want), None)
    unknown = [n for n in nets if n.local_communication_id not in KNOWN
               or n.local_communication_id == COMM_ID_PIKACHU]
    if len(unknown) == 1:
        return unknown[0]
    return None


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if os.geteuid() != 0:
        ap.error("must run as root (LDN needs the raw radio)")
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[lg] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[lg] prod.keys not found at {keys_path!r}"); return 2

    want = int(args.comm_id, 16) if args.comm_id else None
    pw = args.passphrase.encode() if args.passphrase else PASSPHRASE
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[lg] phy={phy} comm_id={'any unknown' if want is None else f'0x{want:016x}'} "
          f"channels={channels} passphrase={len(pw)} B")
    cleanup_stale()
    keys_file = ldn.load_keys(keys_path)

    async def find():
        nets = await ldn.scan(keys_file, phyname=phy, channels=channels, dwell_time=args.dwell)
        for n in nets:
            print(f"[lg] saw {describe(n)}")
        return nets

    nets = trio.run(find)
    if not nets:
        print("[lg] nothing on the air - is the console on the link-trade search screen right now?")
        return 3
    with open(args.facts, "w") as fh:
        json.dump([facts_of(n) for n in nets], fh, indent=2)
    print(f"[lg] {len(nets)} network(s) -> {args.facts}")

    net = pick(nets, want)
    if net is None:
        print("[lg] no single target: pass --comm-id with one of the ids above")
        return 4
    facts = facts_of(net)
    print(f"[lg] target: {describe(net)} ssid={net.ssid.hex()}")
    for k, v in facts.items():
        print(f"[net] {k:24s} {v}")
    if args.scan_only:
        return 0
    if net.num_participants >= net.max_participants:
        print("[lg] session is FULL, no seat to take"); return 5

    keys = session_keys(net)
    print(f"[lg] {keys}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys_file, net, pw
    param.name, param.app_version = args.name.encode(), net.app_version
    param.phyname, param.ifname = phy, args.ifname

    cap = open(args.capture, "w") if args.capture else None

    def record(**kw):
        if cap:
            cap.write(json.dumps(kw) + "\n"); cap.flush()

    record(rec="target", **facts, session_key=keys.session_key.hex())

    async def attempt():
        async with ldn.connect(param) as network:
            info = network.info()
            parts = list(getattr(info, "participants", []) or [])
            macs = [bytes(getattr(p, "mac_address", b"") or b"") for p in parts]
            macs = [m for m in macs if len(m) == 6]
            print(f"[lg] *** ASSOCIATED *** ssid={info.ssid.hex()}")
            for i, p in enumerate(parts):
                name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                print(f"[lg]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                      f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                      f"name={name!r} connected={getattr(p, 'connected', '?')}")
            record(rec="seat", macs=[m.hex() for m in macs])
            sock = make_socket(args.ifname)
            t0 = time.monotonic()
            n_rx = n_ok = n_v3 = 0
            versions = {}
            print(f"[lg] listening on :{PIA_PORT} for {args.hold:.0f}s")
            while time.monotonic() - t0 < args.hold:
                r, _, _ = select.select([sock], [], [], 0.2)
                if not r:
                    await trio.sleep(0)
                    continue
                data, addr = sock.recvfrom(4096)
                n_rx += 1
                entry = {"rec": "rx", "t": round(time.monotonic() - t0, 3), "from": addr[0],
                         "len": len(data), "data": data.hex()}
                if pia4.is_pia4(data) or (len(data) >= 8 and data[:4] == b"\x32\xab\x98\x64"):
                    hdr, pt, mac, sid = try_decrypt(keys, data, macs)
                    versions[hdr.version] = versions.get(hdr.version, 0) + 1
                    if hdr.version == PIA_VERSION:
                        n_v3 += 1
                    entry.update(version=hdr.version, station=hdr.station,
                                 session_id=hdr.session_id, nonce=hdr.nonce8.hex())
                    if pt is not None:
                        n_ok += 1
                        msgs = pia3.parse_packet(pt)
                        entry.update(plaintext=pt.hex(), source_mac=mac.hex(), source_id=sid,
                                     messages=[{"protocol": m["protocol"], "port": m["port"],
                                                "flags": m["flags"], "version": m["version"],
                                                "size": m["size"]} for m in msgs])
                        if n_ok <= 8:
                            print(f"[rx] v{hdr.version} st={hdr.station} sid={hdr.session_id:#x} "
                                  f"{len(data)}B from {addr[0]} AUTH mac={mac.hex()} "
                                  f"pt[:32]={pt[:32].hex()} msgs="
                                  + ",".join(f"{m['protocol']:#x}:{m['port']}/{m['size']}"
                                             for m in msgs))
                    elif n_rx <= 8:
                        print(f"[rx] v{hdr.version} st={hdr.station} sid={hdr.session_id:#x} "
                              f"{len(data)}B from {addr[0]} no key fits")
                elif n_rx <= 8:
                    print(f"[rx] {len(data)}B from {addr[0]} not Pia: {data[:16].hex()}")
                record(**entry)
            print(f"[lg] {n_rx} datagrams, {n_v3} with header version {PIA_VERSION}, "
                  f"{n_ok} authenticated; versions seen {versions}")
            print("[lg] releasing")

    try:
        trio.run(attempt)
        return 0
    except BaseException as e:
        print(f"[lg] failed: {type(e).__name__}: {e}")
        for sub in getattr(e, "exceptions", ()) or ():
            print(f"[lg]   caused by: {type(sub).__name__}: {sub}")
        import traceback; traceback.print_exc()
        cleanup_stale()
        return 6


if __name__ == "__main__":
    sys.exit(main())
