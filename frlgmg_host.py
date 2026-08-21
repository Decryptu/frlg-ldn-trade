#!/usr/bin/env python3
"""Distribute a FireRed/LeafGreen Wonder Card over LDN (Mystery Gift, Friend path).

We advertise ACTIVITY_WONDER_CARD and act as the Mystery Gift *server*: the
console picks us from Mystery Gift -> Wonder Cards -> Friend, and we push it the
client script, the Wonder Card and the delivery RAM script. The player then
collects the gift from the delivery man on the second floor of any Pokemon
Center.

The Wireless Communication ("wireless distributor") path is not reachable from a
Switch - see docs/joyspot_discovery_findings.md - but it delivers the identical
gift, so only the discovery step differs.

Trainer identity starts from ``frlgsim.config.DEFAULT_TRAINER`` and may be
overridden per run.

Example::

    sudo -E ./.venv/bin/python -u frlgmg_host.py --live
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Prefer the bundled, host-capable LDN checkout just like frlgtrade_host.py.
BUNDLED_LDN = os.path.join(PROJECT_ROOT, "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import config as configmod, trade_runtime  # noqa: E402
from frlgsim.host_mg_app import (  # noqa: E402
    MysteryGiftHostApplication, MysteryGiftRunConfig,
)
from frlgsim.wonder_card import (  # noqa: E402
    DEFAULT_GIFT_ITEM, DEFAULT_GIFT_SUBTITLE, DEFAULT_GIFT_TITLE,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--item", type=int, default=DEFAULT_GIFT_ITEM, metavar="ID",
                        help="optional item id the delivery script gives on every visit "
                             "(default: no item)")
    parser.add_argument("--flag-id", type=int, default=1003, metavar="ID",
                        help="Wonder Card flagId, 1000..1019; 1003 is the first "
                             "unused receipt-flag slot (default: 1003)")
    parser.add_argument("--title", default=DEFAULT_GIFT_TITLE,
                        help="Wonder Card title line (<=39 characters)")
    parser.add_argument("--subtitle", default=DEFAULT_GIFT_SUBTITLE,
                        help="Wonder Card subtitle line (<=39 characters)")
    configmod.add_identity_arguments(parser)
    parser.add_argument(
        "--trust-pia", action=argparse.BooleanOptionalAction, default=True,
        help="use Pia-backed send-once block delivery (recommended); "
             "--no-trust-pia enables diagnostic RFU retransmits")
    parser.add_argument("--verbose", action="store_true",
                        help="show detailed protocol logging instead of milestones")
    parser.add_argument("--live", action="store_true", required=True,
                        help="host for a real Switch")
    parser.add_argument("--password", default="",
                        help="LDN passphrase hex; default uses the FRLG emulator value")
    parser.add_argument("--phy", default="auto",
                        help="Wi-Fi phy; default selects an AP-capable phy")
    parser.add_argument("--keys", default="~/.switch/prod.keys")
    parser.add_argument("--comm-id",
                        help="LDN local_communication_id in hexadecimal")
    parser.add_argument("--capture", metavar="FILE",
                        help="record an optional JSONL protocol diagnostic")
    parser.add_argument("--channel", type=int, default=1,
                        choices=range(1, 15), metavar="1-14")
    parser.add_argument("--scene", type=int, default=None,
                        help="LDN scene; default is the known FRLG scene")
    parser.add_argument("--max-participants", type=int, default=6,
                        choices=range(2, 9), metavar="2-8")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-encryption", "--skip_encryption",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="delegate CCMP encryption to mac80211/hardware (default); "
                             "--no-skip-encryption enables Python CCMP")
    parser.add_argument("--native-nonce-sequence", "--native_nonce_sequence",
                        action=argparse.BooleanOptionalAction, default=True,
                        help="use FireRed's session-wide incrementing Pia nonce (default)")
    parser.add_argument("--session-response-first", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="send Session type 2 unicast before type 5 broadcast (default)")
    return parser


def _hex_bytes(parser, option, value):
    if not value:
        return None
    try:
        return bytes.fromhex(value)
    except ValueError:
        parser.error(f"{option} must contain hexadecimal bytes")


def _hex_int(parser, option, value):
    if value is None:
        return None
    try:
        return int(value, 16)
    except ValueError:
        parser.error(f"{option} must be a hexadecimal integer")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")

    try:
        profile = configmod.profile_from_overrides(
            ot=args.ot, version=args.version, trainer_id=args.id)
        ldn = configmod.LdnConfig(
            password=_hex_bytes(parser, "--password", args.password),
            phy=args.phy, keys_path=args.keys,
            local_comm_id=_hex_int(parser, "--comm-id", args.comm_id),
            capture_path=args.capture)
        role = configmod.HostOptions(
            channel=args.channel, scene_id=args.scene,
            max_participants=args.max_participants,
            skip_preflight=args.skip_preflight,
            skip_encryption=args.skip_encryption,
            native_nonce_sequence=args.native_nonce_sequence,
            session_response_first=args.session_response_first)
        config = MysteryGiftRunConfig(
            profile=profile, ldn=ldn, role=role,
            item=args.item,
            flag_id=args.flag_id,
            card_title=args.title,
            card_subtitle=args.subtitle,
            trust_pia=args.trust_pia,
        )
    except ValueError as exc:
        parser.error(str(exc))

    joined = MysteryGiftHostApplication(
        config, log=trade_runtime.ConsoleLog(args.verbose)).run()
    return 0 if joined else 130


if __name__ == "__main__":
    sys.exit(main())
