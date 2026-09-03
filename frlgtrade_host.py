#!/usr/bin/env python3
"""Host a FireRed/LeafGreen Direct Corner trade over LDN.

    sudo -E ./.venv/bin/python -u frlgtrade_host.py --live dummy.pk3 Lola.pk3
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import beacon as beaconmod, config as configmod, host_cli, trade_runtime  # noqa: E402
from frlgsim.host_app import HostApplication  # noqa: E402


def build_parser(file_config=None, *, shared_path=None, local_path=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if file_config is None:
        file_config = configmod.load_project_host_file_config()
    parser.add_argument("party", nargs="*", metavar="MON",
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
    parser.add_argument(
        "--union-room", action="store_true",
        help="advertise ACTIVITY_SEARCH so the Union Room NPC (the MIDDLE NPC on Pokemon Center 2F) "
             "can list us, instead of the wireless club trade centre's THIRD NPC. UNTESTED on "
             "hardware: the Union Room search accepts only ACTIVITY_SEARCH "
             "(sAcceptedActivityIds_Init), which is why the normal trade beacon is invisible there")
    parser.add_argument(
        "--union-room-activity", choices=sorted(configmod.UNION_ROOM_ACTIVITIES), default=None,
        help="which activity --union-room advertises. 'search' (default) is what the console looks "
             "for on the screen BEFORE entering the room (Task_InitUnionRoom). Use an 'in-room' "
             "value for a console already STANDING in the room: it runs Task_RunUnionRoom and its "
             "search accepts IN_UNION_ROOM | activity instead")
    parser.add_argument(
        "--hold-beacon", action="store_true",
        help="Union Room probe: keep the pre-join advertisement after the console joins instead of "
             "switching to the started-activity form (a real Union Room parent only sets "
             "startedActivity at RFUSTATE_UR_FINALIZE, after the child's name)")
    parser.add_argument(
        "--union-room-keepalive", type=int, default=0, metavar="N",
        help="Union Room probe: after the child's name NI, re-present a parent NI_START for N "
             "VBlanks (the console mirrors those in the room) before the first UNI frame; the 'D' "
             "in u03-u05 came after exactly five unanswered parent frames")
    parser.add_argument(
        "--board-type", choices=sorted(beaconmod.TYPE_NAMES), default=None,
        help="Union Room trading board: register the offered Pokemon (its species and level) and "
             "ask for this type in return, so the console's board lists us. The console must have "
             "a Pokemon of that type to start the trade")
    parser.add_argument("--board-level", type=int, default=None, metavar="N",
                        help="override the level shown on the trading board")
    parser.add_argument("--anim-delay", type=int, default=None,
                        help="override the proven trade-animation frame delay")
    parser.add_argument(
        "--player-ids-repeat-frames", type=int, default=None, metavar="N",
        help=("diagnostic: consecutive polls the opening SEND_PLAYER_IDS burst "
              "occupies before the LinkPlayer block request; default is the "
              "built-in timing"))
    parser.add_argument(
        "--link-player-idle-frames", type=int, default=None, metavar="N",
        help=("diagnostic: quiet console polls after the LinkPlayer exchange "
              "before the leader starts the trainer-card exchange itself"))
    host_cli.add_host_config_arguments(
        parser, shared_path=shared_path, local_path=local_path)
    host_cli.add_host_arguments(
        parser,
        option_defaults=file_config.to_host_options(),
        ldn_defaults=file_config.to_ldn_config(),
        trust_pia_default=file_config.trust_pia,
        live_default=file_config.live,
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
            player_ids_repeat_frames=args.player_ids_repeat_frames,
            link_player_idle_frames=args.link_player_idle_frames,
            trust_pia=args.trust_pia)
        return configmod.TradeRunConfig(profile, plan, ldn, options)
    except ValueError as exc:
        parser.error(str(exc))


def main(argv=None):
    try:
        file_config, shared_path, local_path = \
            host_cli.load_host_file_config_from_argv(argv)
    except (ValueError, SystemExit) as exc:
        print(f"frlgtrade_host.py: error: {exc}", file=sys.stderr)
        return 2
    parser = build_parser(
        file_config, shared_path=shared_path, local_path=local_path)
    args = parser.parse_args(argv)
    if args.print_effective_config:
        host_cli.build_host_config(parser, args)
        print(host_cli.format_effective_config(args), end="")
        return 0
    if not args.party:
        parser.error("the following arguments are required: MON")
    if not args.live:
        parser.error("hosting only supports live mode; omit --no-live")
    if os.geteuid() != 0:
        parser.error("live LDN hosting requires root; run with sudo -E")
    run_config = build_run_config(parser, args)
    joined = HostApplication(
        run_config, log=trade_runtime.ConsoleLog(args.verbose)).run()
    return 0 if joined else 130


if __name__ == "__main__":
    sys.exit(main())
