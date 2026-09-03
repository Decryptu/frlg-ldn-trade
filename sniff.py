#!/usr/bin/env python3
"""Monitor-mode sniffer: prints every LDN advertisement action frame (Nintendo OUI, payload 7f 00 22 aa 04 00 01 01)
by source MAC and optionally archives all frames to a radiotap pcap. The advertisement body is encrypted, so the
application_data inside is not readable here; the value is presence, cadence and source."""

import argparse
import os
import socket
import struct
import subprocess
import sys
import time

LDN_ACTION_HDR = bytes([0x7F, 0x00, 0x22, 0xAA, 0x04, 0x00, 0x01, 0x01])
ETH_P_ALL = 0x0003

MGMT_SUBTYPES = {0: "assoc-req", 1: "assoc-resp", 4: "probe-req", 5: "probe-resp",
                 8: "beacon", 10: "disassoc", 11: "auth", 12: "deauth", 13: "action"}


def sh(cmd):
    subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def setup_monitor(phy, ifname, channel):
    sh(["iw", "dev", ifname, "del"])
    subprocess.run(["iw", "phy", phy, "interface", "add", ifname, "type", "monitor"], check=True)
    sh(["ip", "link", "set", ifname, "up"])
    subprocess.run(["iw", "dev", ifname, "set", "channel", str(channel)], check=True)


def teardown(ifname):
    sh(["iw", "dev", ifname, "del"])


class PcapWriter:
    """Minimal pcap (not pcapng), linktype 127 = LINKTYPE_IEEE802_11_RADIOTAP."""

    def __init__(self, path):
        self.f = open(path, "wb")
        self.f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 127))

    def write(self, frame):
        ts = time.time()
        sec, usec = int(ts), int((ts % 1) * 1_000_000)
        self.f.write(struct.pack("<IIII", sec, usec, len(frame), len(frame)) + frame)

    def close(self):
        self.f.close()


def parse_frame(frame):
    if len(frame) < 4:
        return None
    rt_len = int.from_bytes(frame[2:4], "little")
    dot11 = frame[rt_len:]
    if len(dot11) < 24:
        return None
    fc = int.from_bytes(dot11[0:2], "little")
    ftype, subtype = (fc >> 2) & 0x3, (fc >> 4) & 0xF
    if ftype != 0:
        return None
    src = dot11[10:16]
    payload = dot11[24:] if subtype == 13 else None
    return MGMT_SUBTYPES.get(subtype, f"mgmt-{subtype}"), src, payload


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phy", default="phy0", help="phy to sniff on (default phy0 = the MT7601U)")
    ap.add_argument("--ifname", default="ldn-sniff", help="monitor vif name to create")
    ap.add_argument("--channel", type=int, default=6, help="channel to park on (host's channel; "
                    "the ldn lib picks from 1/6/11 - pin the host with --channel to match)")
    ap.add_argument("--pcap", default="", help="also archive every captured frame to this pcap")
    ap.add_argument("--mgmt", action="store_true",
                    help="also print per-second counts of ALL mgmt frames (probe reqs = the console "
                    "is scanning; assoc/auth = it is trying to join)")
    args = ap.parse_args()

    if os.geteuid() != 0:
        ap.error("must run as root (monitor mode); re-run with sudo")

    setup_monitor(args.phy, args.ifname, args.channel)
    print(f"[sniff] monitoring {args.phy} ({args.ifname}) on channel {args.channel}; "
          f"filtering LDN advertisements ({LDN_ACTION_HDR.hex()})")
    pcap = PcapWriter(args.pcap) if args.pcap else None

    rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    rx.bind((args.ifname, 0))
    rx.settimeout(1.0)

    seen = {}
    mgmt_counts = {}
    last_report = time.time()
    try:
        while True:
            try:
                frame = rx.recv(65535)
            except socket.timeout:
                frame = None
            if frame:
                if pcap:
                    pcap.write(frame)
                parsed = parse_frame(frame)
                if parsed:
                    subtype, src, payload = parsed
                    mgmt_counts[subtype] = mgmt_counts.get(subtype, 0) + 1
                    if payload and payload.startswith(LDN_ACTION_HDR):
                        mac = ":".join(f"{b:02x}" for b in src)
                        count, last = seen.get(mac, (0, None))
                        if last != payload:
                            print(f"[sniff] LDN advert from {mac} ({len(payload)}B)"
                                  f"{' NEW/CHANGED' if last is not None else ''}:")
                            print(f"        {payload.hex()}")
                        seen[mac] = (count + 1, payload)
            now = time.time()
            if now - last_report >= 5:
                for mac, (count, _b) in seen.items():
                    print(f"[sniff] {mac}: {count} LDN adverts total")
                if args.mgmt and mgmt_counts:
                    print(f"[sniff] mgmt frames seen: {mgmt_counts}")
                last_report = now
    except KeyboardInterrupt:
        print("\n[sniff] stopping...")
    finally:
        rx.close()
        if pcap:
            pcap.close()
            print(f"[sniff] pcap written: {args.pcap}")
        teardown(args.ifname)
        print(f"[sniff] totals: {mgmt_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
