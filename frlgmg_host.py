#!/usr/bin/env python3
"""Distribute a FireRed/LeafGreen Wonder Card over LDN (Mystery Gift, Friend path): the console picks us
from Mystery Gift -> Wonder Cards -> Friend and collects the gift from the delivery man in any Pokemon Center.

    sudo -E ./.venv/bin/python -u frlgmg_host.py --live
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import (config as configmod, gift_artifact, gift_registry, host_cli,
                     trade_runtime)  # noqa: E402
from frlgsim.host_mg_app import MysteryGiftHostApplication  # noqa: E402
from frlgsim.wonder_card import GIFT_BEAST_CUTSCENE  # noqa: E402

HOST_GIFT_CHOICES = gift_registry.GIFT_REGISTRY.live_choices


def _client_ready_idle_frames(value):
    try:
        frames = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a decimal frame count") from exc
    if not 0 <= frames <= 600:
        raise argparse.ArgumentTypeError("must be between 0 and 600")
    return frames


def _idle_timeout_seconds(value):
    try:
        seconds = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a decimal number of seconds") from exc
    if not 1 <= seconds <= 24 * 60 * 60:
        raise argparse.ArgumentTypeError("must be between 1 and 86400 seconds")
    return seconds


def build_parser(file_config=None, *, shared_path=None, local_path=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    if file_config is None:
        file_config = configmod.load_project_host_file_config()
    parser.add_argument("--gift", choices=gift_registry.GIFT_REGISTRY.live_choices,
                        default=GIFT_BEAST_CUTSCENE,
                        help=gift_registry.GIFT_REGISTRY.format_live_gift_help())
    gift_registry.add_flag_id_argument(parser)
    parser.add_argument(
        "--client-ready-idle-frames", type=_client_ready_idle_frames,
        default=None, metavar="N",
        help=("diagnostic: quiet child polls after LinkPlayer standby before "
             "the first Mystery Gift message; default is the built-in timing"))
    parser.add_argument(
        "--inter-block-gap-frames", type=_client_ready_idle_frames,
        default=None, metavar="N",
        help=("diagnostic: idle VBlanks between the blocks of one Mystery Gift "
              "message; raise it if a run stalls part-way through a message "
              "(default is the built-in timing)"))
    parser.add_argument(
        "--block-repeat", type=int, default=None, metavar="N", choices=range(1, 9),
        help=("emit each block fragment N times (1-8, default 2); "
              "bounded redundancy against the console's silent datagram drops"))
    parser.add_argument(
        "--ram-script-block-repeat", type=int, default=None, metavar="N", choices=range(1, 9),
        help=("fragment redundancy for the ident-25 delivery script alone (1-8, default 3); "
              "the console never reflects gift blocks, so a lost fragment cannot be resent"))
    parser.add_argument(
        "--end-on-success", action=argparse.BooleanOptionalAction, default=False,
        help=("stop after the post-delivery RFU close sequence; used by the "
              "supervised run_mystery_gift.sh host"))
    parser.add_argument(
        "--idle-timeout", type=_idle_timeout_seconds, metavar="SECONDS", default=None,
        help=("stop after this many seconds without meaningful Switch traffic "
              "(join or Pia/RFU datagram); default: disabled"))
    parser.add_argument(
        "--attempt-log-dir", metavar="DIR", default=None,
        help=("append completed joined-attempt records to daily CSV files in DIR; "
              "default: disabled (the supervised shell host enables logs/)"))
    parser.add_argument(
        "--make-artifact", action=argparse.BooleanOptionalAction, default=False,
        help=("write an annotated listing for the exact Mystery Gift bytes that "
              "will be sent (default: disabled)"))
    parser.add_argument(
        "--artifact-dir", metavar="DIR", default="artifacts",
        help="directory for --make-artifact output (default: artifacts)")
    host_cli.add_host_config_arguments(
        parser, shared_path=shared_path, local_path=local_path)
    host_cli.add_host_arguments(
        parser,
        option_defaults=file_config.to_host_options(),
        ldn_defaults=file_config.to_ldn_config(),
        trust_pia_default=file_config.trust_pia,
        live_default=file_config.live,
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
            payload=payload, trust_pia=args.trust_pia,
            client_ready_idle_frames=args.client_ready_idle_frames,
            inter_block_gap_frames=args.inter_block_gap_frames,
            block_repeat=args.block_repeat,
            ram_script_block_repeat=args.ram_script_block_repeat,
            end_on_success=args.end_on_success,
            idle_timeout_seconds=args.idle_timeout,
            attempt_log_dir=args.attempt_log_dir)
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    try:
        file_config, shared_path, local_path = \
            host_cli.load_host_file_config_from_argv(argv)
    except (ValueError, SystemExit) as exc:
        print(f"frlgmg_host.py: error: {exc}", file=sys.stderr)
        return 2
    parser = build_parser(
        file_config, shared_path=shared_path, local_path=local_path)
    args = parser.parse_args(argv)
    if args.print_effective_config:
        host_cli.build_host_config(parser, args)
        print(host_cli.format_effective_config(args), end="")
        return 0
    if not args.live:
        parser.error("hosting only supports live mode; omit --no-live")
    config = build_run_config(parser, args)
    distribution = None
    if args.make_artifact:
        distribution = config.payload.build_distribution()
        definition = gift_registry.GIFT_REGISTRY.entry(args.gift).definition
        try:
            artifact_path = gift_artifact.write_artifact(
                args.artifact_dir, gift=args.gift, flag_id=config.payload.flag_id,
                distribution=distribution, definition=definition)
        except OSError as exc:
            parser.error(f"could not write --artifact-dir {args.artifact_dir!r}: {exc}")
        print(f"wrote Mystery Gift artifact: {artifact_path}")
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")
    app = MysteryGiftHostApplication(
        config, distribution=distribution,
        log=trade_runtime.ConsoleLog(args.verbose))
    joined = app.run()
    if app.interrupted:
        return 130
    if app.idle_timed_out:
        return 124
    return 0 if app.delivery_succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
