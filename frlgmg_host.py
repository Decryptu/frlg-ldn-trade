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

from frlgsim import config as configmod, gift_registry, host_cli, trade_runtime  # noqa: E402
from frlgsim.host_mg_app import MysteryGiftHostApplication  # noqa: E402
from frlgsim.wonder_card import GIFT_BEAST_CUTSCENE  # noqa: E402

# Compatibility snapshot for callers that imported the old constant. Parser
# construction reads the registry dynamically so newly registered definitions
# appear without re-importing this module.
HOST_GIFT_CHOICES = gift_registry.GIFT_REGISTRY.live_choices


def build_parser():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    defaults = configmod.MysteryGiftRunConfig()
    parser.add_argument("--gift", choices=gift_registry.GIFT_REGISTRY.live_choices,
                        default=GIFT_BEAST_CUTSCENE,
                        help="gift payload to distribute (default: beast-cutscene)")
    gift_registry.add_flag_id_argument(parser)
    host_cli.add_host_arguments(
        parser,
        option_defaults=defaults.role,
        ldn_defaults=defaults.ldn,
        scene_help="LDN scene; default is the known FRLG scene",
    )
    return parser


def build_run_config(parser, args):
    profile, ldn, role = host_cli.build_host_config(parser, args)
    try:
        flag_id = gift_registry.resolve_flag_id(args)
        payload = configmod.MysteryGiftPayload(
            gift=args.gift, flag_id=flag_id)
        return configmod.MysteryGiftRunConfig(
            profile=profile, ldn=ldn, role=role,
            payload=payload, trust_pia=args.trust_pia)
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")
    config = build_run_config(parser, args)
    joined = MysteryGiftHostApplication(
        config, log=trade_runtime.ConsoleLog(args.verbose)).run()
    return 0 if joined else 130


if __name__ == "__main__":
    sys.exit(main())
