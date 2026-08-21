#!/usr/bin/env python3
"""Host a FireRed/LeafGreen Direct Corner trade over LDN.

Trainer identity starts from ``frlgsim.config.DEFAULT_TRAINER`` and may be
overridden per run. This entry point only translates command-line options
into the shared ``TradeRunConfig``.

Example::

    sudo -E ./.venv/bin/python -u frlgtrade_host.py --live dummy.pk3 Lola.pk3
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# Prefer the bundled LDN checkout.  It contains the host-side encryption mode
# used by the mt7601u/mac80211 setup without requiring a system installation.
BUNDLED_LDN = os.path.join(PROJECT_ROOT, "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import config as configmod, host_cli, trade_runtime  # noqa: E402
from frlgsim.host_app import HostApplication  # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("party", nargs="+", metavar="MON",
                        help="1..6 host party .pk3/.ek3 files")
    parser.add_argument("-o", "--out", default="received.pk3",
                        help="received-mon output path")
    parser.add_argument("--out-size", type=int, choices=(80, 100), default=100)
    parser.add_argument("--out-format", choices=("pk3", "ek3"), default="pk3")
    parser.add_argument("--slot", type=int, default=1,
                        help="0-based host party slot offered for one trade (default: 1)")
    parser.add_argument("--slots", default="",
                        help="comma-separated 0-based offered slots for multiple trades")
    parser.add_argument("--trades", type=int, default=1, choices=range(1, 7), metavar="N")
    parser.add_argument("--anim-delay", type=int, default=None,
                        help="override the proven trade-animation frame delay")
    host_cli.add_host_arguments(
        parser,
        option_defaults=configmod.HostOptions(),
        ldn_defaults=configmod.LdnConfig(phy="auto"),
        scene_help="LDN scene; default is the known Direct Corner scene",
    )
    return parser


def _offered_slots(parser, args):
    try:
        explicit = trade_runtime.parse_slots(args.slots, args.trades, len(args.party))
    except ValueError as exc:
        parser.error(str(exc))
    if explicit is not None:
        return tuple(explicit)
    slots = tuple(range(args.slot, args.slot + args.trades))
    if any(slot < 0 or slot >= len(args.party) for slot in slots):
        parser.error(
            f"default offered slots {list(slots)} exceed party size {len(args.party)}; "
            "adjust --slot or supply --slots")
    return slots


def build_run_config(parser, args):
    profile, ldn, options = host_cli.build_host_config(parser, args)
    try:
        plan = configmod.TradePlan(
            party_paths=tuple(args.party), output_path=args.out,
            output_size=args.out_size, output_format=args.out_format,
            trade_slot=args.slot, offered_slots=_offered_slots(parser, args),
            trades=args.trades, anim_delay=args.anim_delay,
            trust_pia=args.trust_pia)
        return configmod.TradeRunConfig(profile, plan, ldn, options)
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")
    run_config = build_run_config(parser, args)
    joined = HostApplication(
        run_config, log=trade_runtime.ConsoleLog(args.verbose)).run()
    return 0 if joined else 130


if __name__ == "__main__":
    sys.exit(main())
