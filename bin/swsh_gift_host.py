#!/usr/bin/env python3
"""Distribute a Sword/Shield Mystery Gift by advertising it on LDN.

The gift screen does not join anything: it scans, and a distributor advertises a network whose
0x180-byte advertise data carries the card. This hosts such a network and walks the card's fragments
across successive advertisements. See docs/swsh_gift.md.

    sudo ./bin/swsh_gift_host.py --species 25 --level 25 --nickname PKCAMP --ot GURVAN
    sudo ./bin/swsh_gift_host.py --record scratchpad/card.bin --dwell 0.5

    (them) Mystery Gift -> Recevoir un Cadeau Mystere -> Via communication sans fil locale

Nothing is sent until the console scans, and the console is the only thing that decides to take it.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scratchpad"))

from pokeldn.ldn.transport import HostTransport
from pokeldn.swsh import COMM_ID, PASSPHRASE

import swsh_beacon_message as message
import swsh_wc8 as wc8

SCENE_ID = 0            # the console's scan filter keys on the communication id, not the scene
APP_VERSION = 4


def build_record(args):
    if args.record:
        rec = open(args.record, "rb").read()
        if len(rec) != wc8.RECORD:
            raise SystemExit(f"{args.record} is {len(rec)} bytes, not {wc8.RECORD}")
        return rec
    return wc8.pokemon_card(
        species=args.species, level=args.level, form=args.form,
        moves=(args.move1, args.move2, args.move3, args.move4),
        nickname=args.nickname, ot=args.ot, card_id=args.card_id,
        region_mask=args.region_mask, language=args.language)


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
    p.add_argument("--language", type=int, default=2)
    p.add_argument("--card-id", type=lambda s: int(s, 0), default=0x270F)
    p.add_argument("--region-mask", type=lambda s: int(s, 0), default=0xFFFF)
    p.add_argument("--dwell", type=float, default=0.5,
                   help="seconds each fragment stays on the air")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--channel", type=int, default=None)
    p.add_argument("--phy", default="phy0")
    p.add_argument("--nickname-host", default="PkCamp", help="the network's own name")
    p.add_argument("--keys", default="~/.switch/prod.keys")
    p.add_argument("--scene-id", type=int, default=SCENE_ID)
    p.add_argument("--dump", help="write the record and its fragments here and exit")
    args = p.parse_args()

    record = build_record(args)
    fragments = message.build_message(record)
    print(f"record {len(record)} bytes, checksum {wc8.record_crc(record):#06x}, "
          f"{len(fragments)} fragments")

    if args.dump:
        open(args.dump, "wb").write(record)
        for i, f in enumerate(fragments):
            open(f"{args.dump}.frag{i}", "wb").write(f)
        print(f"wrote {args.dump} and {len(fragments)} fragments")
        return 0

    host = HostTransport(
        app_data=fragments[0], password=PASSPHRASE, nickname=args.nickname_host,
        keys_path=args.keys, local_comm_id=COMM_ID, scene_id=args.scene_id,
        app_version=APP_VERSION, max_participants=8, phyname=args.phy, channel=args.channel)
    host.start()
    if host.error():
        print(f"host failed: {host.error()}", file=sys.stderr)
        return 1
    print(f"advertising comm id {COMM_ID:#018x}, scene {args.scene_id}, "
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
