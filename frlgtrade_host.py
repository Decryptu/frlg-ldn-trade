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
        help="host for the Union Room (the MIDDLE NPC on Pokemon Center 2F) instead of the trade "
             "centre's THIRD NPC; use with --union-room-keepalive 120 and --board-type")
    parser.add_argument(
        "--union-room-activity", choices=sorted(configmod.UNION_ROOM_ACTIVITIES), default=None,
        help="which activity --union-room advertises; default 'in-room', the bare IN_UNION_ROOM a "
             "console standing in the room connects to. 'search' is what the screen BEFORE the "
             "room looks for (untested)")
    parser.add_argument(
        "--union-room-keepalive", type=int, default=0, metavar="N",
        help="Union Room: re-present a parent NI_START for N VBlanks before the first UNI frame; "
             "the room child drops the link after five unanswered frames, and enters UNI 480 "
             "frames after the last NI_START. 120 is proven")
    parser.add_argument(
        "--board-type", choices=sorted(beaconmod.TYPE_NAMES), default=None,
        help="Union Room trading board: register the offered Pokemon (its species and level) and "
             "ask for this type in return, so the console's board lists us. The console must have "
             "a Pokemon of that type to start the trade")
    parser.add_argument("--board-level", type=int, default=None, metavar="N",
                        help="override the level shown on the trading board")
    parser.add_argument(
        "--union-room-chat", action="store_true",
        help="Union Room: accept the console's 'Tchat' instead of declining it. Both sides send a "
             "JOIN block, then the console's keyboard opens and every line it types is logged")
    parser.add_argument(
        "--union-room-battle", action="store_true",
        help="Union Room: accept the console's Combat instead of declining it. The console needs "
             "two non-egg party mons at level 30 or lower or it refuses on its own screen; it is "
             "master and runs the battle, we answer its controller commands")
    parser.add_argument(
        "--battle-fight", action="store_true",
        help="Union Room battle: pick FIGHT with the first move instead of forfeiting at the first "
             "action prompt. Only the forfeit path has been proven on hardware")
    parser.add_argument(
        "--chat-file", default=None, metavar="PATH",
        help="Union Room chat: tail this file while the host runs and send every line appended to "
             "it, so the chat can be answered live instead of queued at launch")
    parser.add_argument(
        "--chat-message", action="append", default=None, metavar="TEXT",
        help="Union Room chat: a line to send once the chat opens, repeatable. Up to 15 Gen-3 "
             "charmap characters each, the console's own keyboard limit and the width its chat "
             "line can draw; they go out one at a time, 1.5s apart")
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
