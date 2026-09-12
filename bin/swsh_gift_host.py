#!/usr/bin/env python3
"""Distribute a Sword/Shield Mystery Gift by advertising it on LDN.

The gift screen does not join anything: it scans, and a distributor advertises a network whose
0x180-byte advertise data carries the card. This hosts such a network and walks the card's fragments
across successive advertisements. See docs/swsh_gift.md.

    sudo ./bin/swsh_gift_host.py --species 25 --level 25 --nickname PKCAMP --ot POKELDN
    sudo ./bin/swsh_gift_host.py --record scratchpad/card.bin --dwell 0.5

    (them) Mystery Gift -> Recevoir un Cadeau Mystere -> Via communication sans fil locale

Nothing is sent until the console scans, and the console is the only thing that decides to take it.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokeldn import config
from pokeldn.ldn import transport
from pokeldn.ldn.transport import HostTransport
from pokeldn.swsh import COMM_ID, PASSPHRASE, beacon, wc8

SCENE_ID = 0            # the console's scan filter keys on the communication id, not the scene
APP_VERSION = 4
LDN_PROTOCOL = 1        # the retail gift screen advertises protocol 1 (AES-CTR); the GBA app uses 3


def build_record(args):
    rec = _base_record(args)
    for item in args.patch or ():
        off, _, data = item.partition("=")
        rec = bytearray(rec)
        rec[int(off, 0):int(off, 0) + len(data) // 2] = bytes.fromhex(data)
        rec = wc8.seal(rec)
    return bytes(rec)


def _base_record(args):
    if args.record:
        rec = open(args.record, "rb").read()
        if len(rec) != wc8.RECORD:
            raise SystemExit(f"{args.record} is {len(rec)} bytes, not {wc8.RECORD}")
        return rec
    fields = {"ot_gender": 2}            # every card a console has taken carried 2 at +0x272
    for item in args.set or ():
        name, _, value = item.partition("=")
        if name not in wc8.POKEMON:
            raise SystemExit(f"--set {name}: not a record field; one of {', '.join(wc8.POKEMON)}")
        fields[name] = int(value, 0)
    return wc8.pokemon_card(
        species=args.species, level=args.level, form=args.form,
        moves=(args.move1, args.move2, args.move3, args.move4),
        nickname=args.nickname, ot=args.ot, card_id=args.card_id,
        region_mask=args.region_mask, ribbons=args.ribbon or (), **fields)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--record", help="a 720-byte record to send instead of building one")
    p.add_argument("--species", type=int, default=25)
    p.add_argument("--level", type=int, default=25, help="0 makes the game roll one")
    p.add_argument("--form", type=int, default=0)
    p.add_argument("--move1", type=int, default=0)
    p.add_argument("--move2", type=int, default=0)
    p.add_argument("--move3", type=int, default=0)
    p.add_argument("--move4", type=int, default=0)
    p.add_argument("--nickname", default=None)
    p.add_argument("--ot", default=None)
    p.add_argument("--set", action="append", metavar="FIELD=VALUE",
                   help="any other record field by name: shiny_type=3, ball=1, held_item=236, "
                        "gender=1, nature=10, ability_type=2, iv_hp=31, dynamax_level=10, "
                        "gigantamax=1, tid=12345, sid=54321 ...")
    p.add_argument("--ribbon", action="append", type=int, help="a ribbon index; repeatable")
    p.add_argument("--patch", action="append", metavar="OFFSET=HEX",
                   help="bytes written over the record at OFFSET before sealing, for the fields "
                        "no name covers (0x15=0b for the title index); repeatable")
    p.add_argument("--card-id", type=lambda s: int(s, 0), default=0x270F)
    p.add_argument("--region-mask", type=lambda s: int(s, 0), default=0xFFFF)
    p.add_argument("--dwell", type=float, default=0.5,
                   help="seconds each fragment stays on the air")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--channel", type=int, default=None)
    p.add_argument("--phy", default="auto", help="the phy renumbers on every driver reload")
    p.add_argument("--nickname-host", default="PkCamp", help="the network's own name")
    p.add_argument("--keys", default=None, help="prod.keys; default from config/host.toml")
    p.add_argument("--scene-id", type=int, default=SCENE_ID)
    p.add_argument("--app-version", type=int, default=APP_VERSION)
    p.add_argument("--protocol", type=int, default=LDN_PROTOCOL, choices=(1, 3),
                   help="LDN advertisement protocol version")
    p.add_argument("--dump", help="write the record and its fragments here and exit")
    args = p.parse_args()

    record = build_record(args)
    fragments = beacon.build_message(record)
    print(f"record {len(record)} bytes, checksum {wc8.record_crc(record):#06x}, "
          f"{len(fragments)} fragments")

    if args.dump:
        open(args.dump, "wb").write(record)
        for i, f in enumerate(fragments):
            open(f"{args.dump}.frag{i}", "wb").write(f)
        print(f"wrote {args.dump} and {len(fragments)} fragments")
        return 0

    # The adapter's Wi-Fi profile and the keys path come from config/host.toml and host.local.toml,
    # the same layer every other host on this machine runs with (docs/hardware_adapters.md).
    machine = config.load_project_host_file_config()
    phy = transport.find_ap_phy(log=print) if args.phy == "auto" else args.phy
    if phy is None:
        print("no AP-capable phy found", file=sys.stderr)
        return 1
    host = HostTransport(
        app_data=fragments[0], password=PASSPHRASE, nickname=args.nickname_host,
        keys_path=os.path.expanduser(args.keys or machine.keys_path), local_comm_id=COMM_ID,
        scene_id=args.scene_id, app_version=args.app_version, max_participants=8,
        protocol=args.protocol,
        phyname=phy, channel=args.channel,
        skip_encryption=machine.skip_encryption,
        accept_decrypted_ccmp=machine.accept_decrypted_ccmp)
    host.start()          # raises when the AP does not come up
    print(f"advertising comm id {COMM_ID:#018x}, scene {args.scene_id}, protocol {args.protocol}, "
          f"walking {len(fragments)} fragments every {args.dwell}s")
    try:
        deadline, i = time.time() + args.seconds, 0
        while time.time() < deadline:
            host.set_app_data_later(fragments[i % len(fragments)])
            i += 1
            time.sleep(args.dwell)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        host.stop()
    print(f"served {i} advertisements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
