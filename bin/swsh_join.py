#!/usr/bin/env python3
"""Scan for a Sword/Shield LDN session and take a seat in it.

Layer under test is LDN ONLY: scan, associate with the game's own 64-byte passphrase, report what
the session says about itself, hold the seat. Nothing Pia - Sword/Shield's Pia header is version 4
and `pokeldn.ldn` implements 6.32+ and 5.27-5.45, so there is nothing above LDN to speak yet.

THE PASSPHRASE IS READ, NOT GUESSED. `mov w2, #0x40` at main.bin 0x006c3ec8 is the length, so the
padding question BDSP had does not arise here and `--pw-mode raw` is the default rather than a
sweep. If raw fails, that is a finding about the reading, not a reason to try paddings blind.

THE LOCAL COMMUNICATION ID IS NOT KNOWN. It is filled at runtime from .bss rather than a literal,
so this scans and reports EVERY network it sees and joins by --comm-id once you have read it off
one run.

POINT THE FIRST SCAN AT A SCREEN WHERE THE CONSOLE HOSTS - a Link Trade over local communication.
The Mystery Gift local-wireless screen reads like a RECEIVER: the game's own French text has
"Recherche de cadeau en cours..." and "Aucun cadeau n'a ete trouve", so on that screen the console
is scanning and has no advertisement for us to read. The comm id is per application, so the id read
off any local-wireless feature is the one the gift path uses. docs/swsh.md.
"""
import argparse
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED_LDN = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED_LDN):
    sys.path.insert(0, BUNDLED_LDN)

import trio
import ldn
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.host_support import resolve_keys
from pokeldn.swsh import PASSPHRASE

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]

# Comm ids this project already knows, so an unexpected one stands out in the scan report.
KNOWN = {0x0100000011D90000: "BDSP"}


def cleanup_stale():
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(net):
    tag = KNOWN.get(net.local_communication_id, "")
    return (f"comm_id=0x{net.local_communication_id:016x}{' (' + tag + ')' if tag else ''} "
            f"scene={net.scene_id} version={net.version} app_version={net.app_version} "
            f"ch={net.channel} {net.num_participants}/{net.max_participants}")


def facts_of(net):
    """Everything the advertisement carries. The session-key seed is not yet known to be in here,
    so record all of it and let a later reading pick."""
    return {
        "ssid": net.ssid.hex(),
        "server_random": bytes(getattr(net, "server_random", b"") or b"").hex(),
        "application_data": bytes(getattr(net, "application_data", b"") or b"").hex(),
        "nonce": bytes(getattr(net, "nonce", b"") or b"").hex(),
        "challenge": getattr(net, "challenge", None),
        "local_communication_id": net.local_communication_id,
        "scene_id": net.scene_id,
        "version": net.version,
        "app_version": net.app_version,
        "channel": net.channel,
        "num_participants": net.num_participants,
        "max_participants": net.max_participants,
        "address": str(net.address),
    }


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default=None,
                    help="local_communication_id to join, hex. Omit to report every network seen "
                         "and join the only unknown one, which is what a first run wants")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11,36,40,44,48")
    ap.add_argument("--dwell", type=float, default=0.8)
    ap.add_argument("--name", default="PkCamp", help="our display name in the session")
    ap.add_argument("--pw-mode", default="raw", choices=["raw", "pad64", "all"],
                    help="the passphrase is 64 bytes already; pad64 is a no-op kept for symmetry")
    ap.add_argument("--passphrase", default=None, help="override, as ASCII")
    ap.add_argument("--hold", type=float, default=60.0,
                    help="seconds to stay in the session once joined")
    ap.add_argument("--scan-only", action="store_true",
                    help="report what is on the air and stop - the first hardware step")
    ap.add_argument("--facts", default="scratchpad/swsh_net_facts.json",
                    help="where to write everything the advertisement tells us")
    return ap


def pick(nets, want):
    if want is not None:
        return next((n for n in nets if n.local_communication_id == want), None)
    unknown = [n for n in nets if n.local_communication_id not in KNOWN]
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
        print("[swsh] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[swsh] prod.keys not found at {keys_path!r}"); return 2

    want = int(args.comm_id, 16) if args.comm_id else None
    base = args.passphrase.encode() if args.passphrase else PASSPHRASE
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[swsh] phy={phy} comm_id={'any unknown' if want is None else f'0x{want:016x}'} "
          f"channels={channels} passphrase={len(base)} B mode={args.pw_mode}")
    cleanup_stale()
    keys = ldn.load_keys(keys_path)

    async def find():
        nets = await ldn.scan(keys, phyname=phy, channels=channels, dwell_time=args.dwell)
        for n in nets:
            print(f"[swsh] saw {describe(n)}")
        return nets

    nets = trio.run(find)
    if not nets:
        print("[swsh] nothing on the air - is the console on the screen under test right now?")
        return 3
    with open(args.facts, "w") as fh:
        json.dump([facts_of(n) for n in nets], fh, indent=2)
    print(f"[swsh] {len(nets)} network(s) -> {args.facts}")

    net = pick(nets, want)
    if net is None:
        print("[swsh] no single target: pass --comm-id with one of the ids above")
        return 4
    print(f"[swsh] target: {describe(net)} ssid={net.ssid.hex()}")
    for k, v in facts_of(net).items():
        print(f"[net] {k:24s} {v}")
    if args.scan_only:
        return 0
    if net.num_participants >= net.max_participants:
        print("[swsh] session is FULL, no seat to take"); return 5

    readings = [("raw", base)]
    if args.pw_mode in ("pad64", "all"):
        readings.append(("pad64", base.ljust(64, b"\0")))
    for label, pw in readings:
        print(f"\n[swsh] --- associating, passphrase reading {label!r} ({len(pw)} B)")
        param = ldn.ConnectNetworkParam()
        param.keys = keys
        param.network = net
        param.password = pw
        param.name = args.name.encode()
        param.app_version = net.app_version
        param.phyname = phy
        param.ifname = args.ifname

        async def attempt():
            async with ldn.connect(param) as network:
                info = network.info()
                print(f"[swsh] *** ASSOCIATED *** ssid={info.ssid.hex()}")
                for i, p in enumerate(getattr(info, "participants", []) or []):
                    name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                    print(f"[swsh]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                          f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                          f"name={name!r} connected={getattr(p, 'connected', '?')}")
                print(f"[swsh] holding the seat for {args.hold:.0f}s - watch the console screen. "
                      f"A seat in the LDN session is NOT a seat in the game's own session, so a "
                      f"quiet screen is expected and is not a failure.")
                await trio.sleep(args.hold)
                print("[swsh] releasing")

        try:
            trio.run(attempt)
            print(f"[swsh] PASSPHRASE READING THAT WORKS: {label} ({len(pw)} B)")
            return 0
        except Exception as e:
            print(f"[swsh] {label} failed: {type(e).__name__}: {e}")
            cleanup_stale()
    print("[swsh] association failed - the passphrase reading is the thing to doubt last, "
          "it came out of the instruction that sets its length")
    return 6


if __name__ == "__main__":
    sys.exit(main())
