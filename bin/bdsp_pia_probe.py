#!/usr/bin/env python3
"""Hold an LDN seat in a BDSP session and SPEAK to the console on Pia's port instead of listening.

BDSP's Pia session key depends on state the console never advertises, so passive decryption is the
wrong goal; the way in is joining and speaking. This is the first step of that: take the seat
we can take, then find out whether the console answers anything we send.

What it sends is deliberately minimal and UNENCRYPTED (the version byte's 0x80 bit clear). We cannot
produce a valid tag, so an encrypted packet would be rejected on the MAC before it was even parsed;
an unencrypted one at least reaches the header check that main.bin 0x01681ee4 performs. A reply, an
error, or a disconnect are all evidence. Silence is evidence too, and is the expected first outcome.
"""
import argparse, os, socket, struct, sys, time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
BUNDLED = os.path.join(PROJECT_ROOT, 'vendor', 'LDN')
if os.path.isdir(BUNDLED): sys.path.insert(0, BUNDLED)

import trio, ldn
from pokeldn.ldn.pia5 import PiaHeader5, is_pia5, HEADER_SIZE, CT_OFF
from pokeldn.ldn.transport import find_ap_phy
from pokeldn.host_support import resolve_keys

BDSP_PASSPHRASE = b"WirelessStrongCryptoKey2021"
PIA_PORT = 12345


def cleanup():
    import subprocess
    for v in ("ldn", "ldn-mon", "ldn-tap", "ldnclient"):
        subprocess.run(["iw", "dev", v, "del"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_socket(ifname, our_ip):
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


def probes(our_var, seen_src):
    """The packets worth sending, cheapest hypothesis first."""
    out = []
    h = PiaHeader5(dst_var=0, src_var=our_var, packet_id=0, encrypted=False)
    out.append(("header-only, dst=0, plaintext", h.pack()))
    if seen_src is not None:
        h2 = PiaHeader5(dst_var=seen_src, src_var=our_var, packet_id=1, encrypted=False)
        out.append(("header-only, dst=console's src_var, plaintext", h2.pack()))
    h3 = PiaHeader5(dst_var=0, src_var=our_var, packet_id=2, encrypted=False)
    out.append(("header + 16 zero bytes, plaintext", h3.pack() + b"\0" * 16))
    return out


async def main_async(args):
    keys = ldn.load_keys(resolve_keys(args.keys))
    phy = find_ap_phy(log=print) if args.phy == "auto" else args.phy
    cleanup()
    nets = await ldn.scan(keys, phyname=phy, channels=[int(c) for c in args.channels.split(",")],
                          dwell_time=0.8)
    want = int(args.comm_id, 16)
    net = next((n for n in nets if n.local_communication_id == want), None)
    if net is None:
        print("[probe] target network not seen"); return 3
    print(f"[probe] joining ssid={net.ssid.hex()} ch={net.channel} "
          f"{net.num_participants}/{net.max_participants}")

    param = ldn.ConnectNetworkParam()
    param.keys, param.network, param.password = keys, net, BDSP_PASSPHRASE
    param.name, param.app_version = args.name.encode(), net.app_version
    param.phyname, param.ifname = phy, args.ifname

    async with ldn.connect(param) as network:
        info = network.info()
        parts = list(getattr(info, "participants", []) or [])
        host = parts[0] if parts else None
        host_ip = host.ip_address if host else "169.254.54.1"
        ours = next((p for p in parts[1:] if getattr(p, "connected", False)), None)
        our_ip = ours.ip_address if ours else host_ip.rsplit(".", 1)[0] + ".2"
        bcast = our_ip.rsplit(".", 1)[0] + ".255"
        print(f"[probe] seat taken: us={our_ip} host={host_ip} bcast={bcast}")

        sock = make_socket(args.ifname, our_ip)
        rx = {"broadcast": 0, "unicast": 0}
        seen_src = None
        our_var = 0x7A5B0001
        t0 = time.monotonic()
        sent = []

        async def receiver():
            nonlocal seen_src
            while time.monotonic() - t0 < args.hold:
                await trio.lowlevel.wait_readable(sock)
                try:
                    data, addr = sock.recvfrom(4096)
                except BlockingIOError:
                    continue
                if not is_pia5(data):
                    print(f"[rx] {addr[0]} {len(data)}B non-Pia {data[:16].hex()}")
                    continue
                if addr[0] == our_ip:
                    continue          # our own broadcast, looped back - not an answer
                h = PiaHeader5.parse(data)
                if seen_src is None:
                    seen_src = h.src_var
                    print(f"[rx] first Pia packet from {addr[0]}: {h}")
                # a packet addressed to a non-zero destination is the interesting one
                if h.dst_var != 0:
                    rx["unicast"] += 1
                    print(f"[rx] *** ADDRESSED PACKET from {addr[0]}: {h}")
                else:
                    rx["broadcast"] += 1

        async def sender():
            await trio.sleep(args.listen_first)
            for label, pkt in probes(our_var, seen_src):
                for dst in (host_ip, bcast):
                    print(f"[tx] {label} -> {dst} ({len(pkt)} B)")
                    try:
                        sock.sendto(pkt, (dst, PIA_PORT))
                    except OSError as e:
                        print(f"[tx] send failed: {e}")
                    sent.append((label, dst))
                    await trio.sleep(args.gap)
            print("[tx] all probes sent; listening for the rest of the hold")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(receiver)
            nursery.start_soon(sender)
            await trio.sleep(args.hold)
            nursery.cancel_scope.cancel()

        print(f"\n[probe] sent {len(sent)} packet(s); received "
              f"{rx['broadcast']} to dst=0, {rx['unicast']} ADDRESSED")
        print("[probe] an ADDRESSED count above zero means the console answered us")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comm-id", default="0100000011d90000")
    ap.add_argument("--keys", default="~/.switch/prod.keys")
    ap.add_argument("--phy", default="auto")
    ap.add_argument("--ifname", default="ldnclient")
    ap.add_argument("--channels", default="6")
    ap.add_argument("--name", default="PkCamp")
    ap.add_argument("--hold", type=float, default=60.0)
    ap.add_argument("--listen-first", type=float, default=5.0)
    ap.add_argument("--gap", type=float, default=1.5)
    args = ap.parse_args()
    if os.geteuid() != 0:
        ap.error("must run as root")
    return trio.run(main_async, args)


if __name__ == "__main__":
    sys.exit(main())
