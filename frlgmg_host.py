#!/usr/bin/env python3
"""Distribute a FireRed/LeafGreen Wonder Card over LDN (Mystery Gift, Friend path): the console picks us
from Mystery Gift -> Wonder Cards -> Friend and collects the gift from the delivery man in any Pokemon Center.

    sudo -E ./.venv/bin/python -u frlgmg_host.py --live

With --news the same host serves the other half of the console's Mystery Gift menu instead: the
console picks us from Mystery Gift -> Wonder News -> Friend and the man in the house in CERULEAN CITY
hands over a BERRY for what it read.

    sudo -E ./.venv/bin/python -u frlgmg_host.py --live --news
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import (buffer_script, config as configmod, easychat, gift_artifact,  # noqa: E402
                     gift_registry, host_cli, trade_runtime, wonder_news)
from frlgsim.host_mg_app import (  # noqa: E402
    BufferScriptHostApplication, MysteryGiftHostApplication, WonderNewsHostApplication)
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
    payload_group = parser.add_mutually_exclusive_group()
    payload_group.add_argument(
        "--gift", choices=gift_registry.GIFT_REGISTRY.live_choices,
        default=GIFT_BEAST_CUTSCENE,
        help=gift_registry.GIFT_REGISTRY.format_live_gift_help())
    payload_group.add_argument(
        "--news", nargs="?", const=wonder_news.DEFAULT_NEWS, default=None,
        choices=wonder_news.news_choices(), metavar="NAME",
        help=wonder_news.format_news_help())
    payload_group.add_argument(
        "--buffer-script", nargs="?", const=buffer_script.TRAINER_ID_PROBE, default=None,
        choices=buffer_script.script_choices(), metavar="NAME",
        help=("run native ARM code on the console through CLI_RUN_BUFFER_SCRIPT instead of "
              "sending a gift: " + buffer_script.format_script_help()))
    parser.add_argument(
        "--dump-address", type=lambda v: int(v, 0), default=None, metavar="ADDR",
        help=("with --buffer-script memory-dump: the console address to read out (0x02000000 "
              "EWRAM, 0x03000000 IWRAM, 0x08000000 ROM). Accepts 0x hex"))
    parser.add_argument(
        "--dump-size", type=int, default=buffer_script.MAX_BUFFER_SCRIPT_SIZE, metavar="N",
        help=("with --buffer-script memory-dump: how many bytes to read, 1..%d "
              "(MG_LINK_BUFFER_SIZE)" % buffer_script.MAX_BUFFER_SCRIPT_SIZE))
    parser.add_argument(
        "--dump-block", choices=buffer_script.SAVE_BLOCKS, default=buffer_script.SAVE_BLOCK_2,
        help=("with --buffer-script save-dump: which save block to read; sav2 is name, trainer "
              "id and pokedex, sav1 is party, bag, money, flags and vars"))
    parser.add_argument(
        "--dump-offset", type=lambda v: int(v, 0), default=0, metavar="N",
        help="with --buffer-script save-dump: byte offset into that block. Accepts 0x hex")
    parser.add_argument(
        "--dump-file", default=None, metavar="PATH",
        help="with a dumping --buffer-script: write the bytes that come back to this file")
    parser.add_argument(
        "--write-text", default=None, metavar="TEXT",
        help=("with --buffer-script save-write: ASCII to write into the save block at "
              "--dump-offset. The same region is read back in the same run, so the answer is the "
              "proof. The console saves afterwards, so it reaches flash"))
    parser.add_argument(
        "--write-hex", default=None, metavar="HEX",
        help="with --buffer-script save-write: the bytes to write, as hex")
    parser.add_argument(
        "--write-unsafe", action="store_true",
        help=("allow a save write OUTSIDE struct SaveBlock2's never-read filler regions. This is "
              "the player's live save and the console commits it to flash; without this the write "
              "is refused"))
    gift_registry.add_flag_id_argument(parser)
    parser.add_argument(
        "--questionnaire", default=None, metavar="W1,W2,W3,W4",
        help=("require the console to be holding this four-word Easy Chat phrase in its Poke Mart\n"
              "questionnaire before anything is sent [SVR_CHECK_QUESTIONNAIRE]. Each word is an\n"
              "English word name, `species:N`, `move:N`, `GROUP/INDEX`, or a raw id. Word ids are\n"
              "per-language outside the species and move groups, so read the phrase off the target\n"
              "console first: every session logs the four ids it is holding."))
    parser.add_argument(
        "--denied-message", default=None, metavar="TEXT",
        help=("what a console that does not know the phrase reads (max 63 characters); "
              "the default is 'That is not the phrase.'"))
    parser.add_argument(
        "--news-id", type=int, default=None, metavar="ID",
        help=("override the news id (1..65535). A console keeps news only when it differs from "
              "what it already holds [IsWonderNewsSameAsSaved], so bump this to re-send the same "
              "text to the same console"))
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
        if args.news is not None:
            if args.questionnaire is not None:
                parser.error(
                    "--questionnaire gates a Wonder Card session; the News server script has no "
                    "SVR_CHECK_QUESTIONNAIRE branch")
            if getattr(args, "_flag_id_explicit", False):
                parser.error("--flag-id belongs to a Wonder Card; Wonder News has no flagId")
            payload = configmod.WonderNewsPayload(
                news=args.news, news_id=args.news_id)
        elif args.buffer_script is None and args.dump_address is not None:
            parser.error("--dump-address needs --buffer-script memory-dump")
        elif args.buffer_script is not None:
            if args.questionnaire is not None:
                parser.error(
                    "--questionnaire gates a Wonder Card session; the buffer script server "
                    "script has no SVR_CHECK_QUESTIONNAIRE branch")
            if getattr(args, "_flag_id_explicit", False):
                parser.error("--flag-id belongs to a Wonder Card; a buffer script has no flagId")
            if args.news_id is not None:
                parser.error("--news-id is only meaningful with --news")
            if args.write_text is not None and args.write_hex is not None:
                parser.error("--write-text and --write-hex are two ways to say the same thing")
            write_data = None
            if args.write_text is not None:
                write_data = args.write_text.encode("ascii", "strict")
            elif args.write_hex is not None:
                try:
                    write_data = bytes.fromhex(args.write_hex.replace(" ", ""))
                except ValueError:
                    parser.error("--write-hex takes hex digits")
            if (write_data is not None or args.write_unsafe) \
                    and args.buffer_script != buffer_script.SAVE_WRITE:
                parser.error(f"--write-* belongs to --buffer-script {buffer_script.SAVE_WRITE}")
            payload = configmod.BufferScriptPayload(
                script=args.buffer_script, dump_address=args.dump_address,
                dump_block=args.dump_block, dump_offset=args.dump_offset,
                dump_size=args.dump_size, dump_file=args.dump_file,
                write_data=write_data, write_unsafe=args.write_unsafe)
        else:
            if args.news_id is not None:
                parser.error("--news-id is only meaningful with --news")
            phrase = (None if args.questionnaire is None
                      else easychat.parse_phrase(args.questionnaire))
            payload = configmod.MysteryGiftPayload(
                gift=args.gift, flag_id=gift_registry.resolve_flag_id(args),
                questionnaire=phrase, denied_message=args.denied_message)
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
    if args.make_artifact and args.news is not None:
        parser.error("--make-artifact disassembles a delivery RAM script; Wonder News has none")
    if args.make_artifact and args.buffer_script is not None:
        parser.error(
            "--make-artifact disassembles a delivery RAM script; a buffer script has none")
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
    application = (WonderNewsHostApplication if args.news is not None
                   else BufferScriptHostApplication if args.buffer_script is not None
                   else MysteryGiftHostApplication)
    app = application(
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
