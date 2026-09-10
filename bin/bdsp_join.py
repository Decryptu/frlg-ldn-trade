#!/usr/bin/env python3
"""Join a native Switch title's LDN session (first target: BDSP, comm id 0100000011d90000).

Layer under test is LDN ONLY: scan, then associate with the title's 64-byte passphrase and report
what the session says about itself. Nothing Pia, nothing game-level. A successful association is
the milestone - `vendor/LDN` already reads these advertisements with prod.keys alone, so the
passphrase is the only thing between us and a seat in the session.

The passphrase length is NOT settled: the NintendoClients wiki gives BDSP as the ASCII string
`WirelessStrongCryptoKey2021` and spells out padding only for Mario Kart 8 Deluxe, so --pw-mode
tries the readings. derive_data_key() hashes server_random + password, so the byte count matters.
"""
import argparse
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

STALE_VIFS = ["ldn", "ldn-mon", "ldn-tap", "ldnclient"]

# NintendoClients wiki, "LDN Passphrases", row "Pokemon Brilliant Diamond". Shining Pearl shares
# Brilliant Diamond's local_communication_id, so it shares the passphrase.
BDSP_PASSPHRASE = b"WirelessStrongCryptoKey2021"


def pw_variants(base, mode):
    """The readings of a wiki passphrase row worth trying, cheapest first."""
    v = {
        "raw":    base,                                  # the string is the whole passphrase
        "pad64":  base.ljust(64, b"\0"),                 # nn::ldn's 64-byte buffer, null padded
        "pad32":  base.ljust(32, b"\0"),                 # MK8D's row is 15 chars + 17 nulls = 32
    }
    if mode == "all":
        return list(v.items())
    return [(mode, v[mode])]


def cleanup_stale():
    for name in STALE_VIFS:
        subprocess.run(["iw", "dev", name, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def describe(net):
    return (f"comm_id=0x{net.local_communication_id:016x} scene={net.scene_id} "
            f"version={net.version} app_version={net.app_version} ch={net.channel} "
            f"{net.num_participants}/{net.max_participants}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default="0100000011d90000",
                    help="local_communication_id to join, hex (default: BDSP)")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="1,6,11,36,40,44,48")
    ap.add_argument("--dwell", type=float, default=0.8)
    ap.add_argument("--name", default="PkCamp", help="our display name in the session")
    ap.add_argument("--pw-mode", default="all", choices=["all", "raw", "pad64", "pad32"])
    ap.add_argument("--passphrase", default=None,
                    help="override, as ASCII (default: the BDSP wiki value)")
    ap.add_argument("--hold", type=float, default=60.0,
                    help="seconds to stay in the session once joined")
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--facts", default="scratchpad/bdsp_net_facts.json",
                    help="where to write everything the advertisement tells us")
    args = ap.parse_args()

    if os.geteuid() != 0:
        ap.error("must run as root (LDN needs the raw radio)")

    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("[join] no AP-capable phy"); return 1
    keys_path = resolve_keys(args.keys)
    if not os.path.exists(keys_path):
        print(f"[join] prod.keys not found at {keys_path!r}"); return 2

    want = int(args.comm_id, 16)
    base = args.passphrase.encode() if args.passphrase else BDSP_PASSPHRASE
    channels = [int(c) for c in args.channels.split(",") if c.strip()]
    print(f"[join] phy={phy} comm_id=0x{want:016x} channels={channels} "
          f"passphrase={base!r} ({len(base)} B) mode={args.pw_mode}")
    cleanup_stale()
    keys = ldn.load_keys(keys_path)

    async def find():
        nets = await ldn.scan(keys, phyname=phy, channels=channels, dwell_time=args.dwell)
        for n in nets:
            print(f"[join] saw {describe(n)}")
        return next((n for n in nets if n.local_communication_id == want), None)

    net = trio.run(find)
    if net is None:
        print("[join] target network not seen - is the console sitting in the room right now?")
        return 3
    print(f"[join] target: {describe(net)} ssid={net.ssid.hex()}")
    # Everything the session's key derivation could be built from. The HMAC path
    # (main.bin 0x1693714) takes a 32-BYTE input, and ssid||server_random is the only 32 bytes LDN
    # gives every station; a capture without server_random cannot test it.
    import json as _json
    facts = {
        "ssid": net.ssid.hex(),
        "server_random": bytes(getattr(net, "server_random", b"")).hex(),
        "application_data": bytes(getattr(net, "application_data", b"") or b"").hex(),
        "nonce": bytes(getattr(net, "nonce", b"") or b"").hex(),
        "challenge": getattr(net, "challenge", None),
        "local_communication_id": net.local_communication_id,
        "scene_id": net.scene_id, "version": net.version,
        "app_version": net.app_version, "channel": net.channel,
        "address": str(net.address),
    }
    for k, v in facts.items():
        print(f"[net] {k:24s} {v}")
    with open(args.facts, "w") as fh:
        _json.dump(facts, fh, indent=2)
    print(f"[join] network facts -> {args.facts}")
    if net.num_participants >= net.max_participants:
        print("[join] session is FULL, no seat to take"); return 4
    if args.scan_only:
        return 0

    for label, pw in pw_variants(base, args.pw_mode):
        print(f"\n[join] --- attempting association, passphrase reading {label!r} ({len(pw)} B)")
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
                print(f"[join] *** ASSOCIATED *** ssid={info.ssid.hex()}")
                for i, p in enumerate(getattr(info, "participants", []) or []):
                    name = bytes(getattr(p, "name", b"") or b"").split(b"\0")[0]
                    print(f"[join]   participant {i}: ip={getattr(p, 'ip_address', '?')} "
                          f"mac={bytes(getattr(p, 'mac_address', b'')).hex()} "
                          f"name={name!r} connected={getattr(p, 'connected', '?')}")
                print(f"[join] holding the seat for {args.hold:.0f}s - watch the console screen")
                await trio.sleep(args.hold)
                print("[join] releasing")

        try:
            trio.run(attempt)
            print(f"[join] PASSPHRASE READING THAT WORKS: {label} ({len(pw)} B)")
            return 0
        except Exception as e:
            print(f"[join] {label} failed: {type(e).__name__}: {e}")
            cleanup_stale()
    print("[join] every passphrase reading failed")
    return 5


if __name__ == "__main__":
    sys.exit(main())
