#!/usr/bin/env python3
"""Distribute a FireRed/LeafGreen Wonder Card over LDN (Mystery Gift, Friend path): the console picks us
from Mystery Gift -> Wonder Cards -> Friend and collects the gift from the delivery man in any Pokemon Center.

    sudo -E ./.venv/bin/python -u bin/frlgmg_host.py --live

With --news the same host serves the other half of the console's Mystery Gift menu instead: the
console picks us from Mystery Gift -> Wonder News -> Friend and the man in the house in CERULEAN CITY
hands over a BERRY for what it read.

    sudo -E ./.venv/bin/python -u bin/frlgmg_host.py --live --news
"""

import argparse
import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# This launcher lives in bin/; the frlgsim package and vendor/ are at the repo root.
sys.path.insert(0, PROJECT_ROOT)

BUNDLED_LDN = os.path.join(PROJECT_ROOT, "vendor", "LDN")
if os.path.isdir(os.path.join(BUNDLED_LDN, "ldn")):
    sys.path.insert(0, BUNDLED_LDN)

from frlgsim import (buffer_script, config as configmod, easychat, gift_artifact,  # noqa: E402
                     gift_registry, host_cli, native_script, rom_map, trade_runtime,
                     wonder_news)
from frlgsim.host_mg_app import (  # noqa: E402
    BufferScriptHostApplication, MysteryGiftHostApplication, WonderNewsHostApplication)
from frlgsim import wonder_card_events  # noqa: E402
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
        "--table-delta", type=lambda v: int(v, 0), default=None, metavar="D",
        help=("with --buffer-script table-scan: what each word of the run must exceed the one "
              "before it by. 2 finds a table of pointers to consecutive u16s, which is what "
              "gSpecialVars is. Accepts 0x hex"))
    parser.add_argument(
        "--table-runlen", type=int, default=buffer_script.SPECIAL_VARS_RUN_LENGTH, metavar="N",
        help=("with --buffer-script table-scan: how many words in a row make a run worth "
              "reporting (default %d, the twelve gSpecialVar_0x8000..0x800B entries)"
              % buffer_script.SPECIAL_VARS_RUN_LENGTH))
    parser.add_argument(
        "--table-start", type=lambda v: int(v, 0), default=buffer_script.SCAN_ROM_START,
        metavar="ADDR",
        help=("with --buffer-script table-scan: where to start, 16-byte aligned "
              "(default 0x%08X, the cartridge)" % buffer_script.SCAN_ROM_START))
    parser.add_argument(
        "--table-end", type=lambda v: int(v, 0), default=buffer_script.SCAN_ROM_END,
        metavar="ADDR",
        help=("with --buffer-script table-scan: one past the last address to read "
              "(default 0x%08X)" % buffer_script.SCAN_ROM_END))
    parser.add_argument(
        "--table-blocks", type=int, default=buffer_script.TABLE_SCAN_DEFAULT_BLOCKS, metavar="N",
        help=("with --buffer-script table-scan: 16-byte blocks scanned per frame (default %d, "
              "the same instruction load on the frame that memory-scan's 512 costs)"
              % buffer_script.TABLE_SCAN_DEFAULT_BLOCKS))
    parser.add_argument(
        "--table-max-calls", type=int, default=None, metavar="N",
        help="with --buffer-script table-scan: the watchdog, in calls (= frames)")
    parser.add_argument(
        "--scan-word", type=lambda v: int(v, 0), default=None, metavar="VALUE",
        help=("with --buffer-script memory-scan: the 32-bit value to search for. The payload "
              "returns 0 to be called again next frame, so one run scans a whole range instead "
              "of the 1024 bytes a dump reads. Accepts 0x hex"))
    parser.add_argument(
        "--scan-start", type=lambda v: int(v, 0), default=buffer_script.SCAN_ROM_START,
        metavar="ADDR",
        help=("with --buffer-script memory-scan: where to start, 32-byte aligned "
              "(default 0x%08X, the cartridge)" % buffer_script.SCAN_ROM_START))
    parser.add_argument(
        "--scan-end", type=lambda v: int(v, 0), default=buffer_script.SCAN_ROM_END,
        metavar="ADDR",
        help=("with --buffer-script memory-scan: one past the last address to read "
              "(default 0x%08X, the end of a 16 MB cartridge)" % buffer_script.SCAN_ROM_END))
    parser.add_argument(
        "--scan-blocks", type=int, default=buffer_script.SCAN_DEFAULT_BLOCKS, metavar="N",
        help=("with --buffer-script memory-scan: 32-byte blocks scanned per frame, the budget "
              "the console's link has to live with (default %d, about 3 ms of a 16 ms frame)"
              % buffer_script.SCAN_DEFAULT_BLOCKS))
    parser.add_argument(
        "--scan-max-calls", type=int, default=None, metavar="N",
        help=("with --buffer-script memory-scan: the watchdog. A payload that never returns 1 "
              "hangs the Mystery Gift menu, so the scan gives up and answers after this many "
              "frames (default: what the range needs, plus two)"))
    parser.add_argument(
        "--gather-address", type=lambda v: int(v, 0), default=None, metavar="ADDR",
        help=("with --buffer-script string-gather: the address of the FIRST POINTER in an array "
              "to follow. The answer is the strings themselves, back to back, so one run carries "
              "a whole table instead of a window of mostly-pointers. Accepts 0x hex"))
    parser.add_argument(
        "--gather-count", type=int, default=1, metavar="N",
        help="with --buffer-script string-gather: how many pointers to follow at most")
    parser.add_argument(
        "--gather-stride", type=int, default=12, metavar="N",
        help=("with --buffer-script string-gather: bytes from one pointer to the next (default "
              "12, struct EasyChatWordInfo, whose `text` is at offset 0; a plain array of "
              "`const u8 *` is 4)"))
    parser.add_argument(
        "--gather-maxlen", type=int, default=buffer_script.GATHER_DEFAULT_MAXLEN, metavar="N",
        help=("with --buffer-script string-gather: longest string accepted, terminator included. "
              "A pointer that is not a string would otherwise be copied until it met an 0xFF "
              "(default %d)" % buffer_script.GATHER_DEFAULT_MAXLEN))
    parser.add_argument(
        "--trace-address", type=lambda v: int(v, 0), default=None, metavar="ADDR",
        help=("with --buffer-script rng-trace: the word to sample once a frame. "
              "0x03004220 is gRngValue on this build [rom_map.py]. Accepts 0x hex"))
    parser.add_argument(
        "--trace-call", type=lambda v: int(v, 0), default=0, metavar="ADDR",
        help=("with --buffer-script rng-trace: a ROM function to CALL between the two reads of "
              "each sample, as a THUMB pointer (bit 0 set), or 0 for none. 0x080486B1 is Random; "
              "the recurrence between the two reads is then the proof that both addresses are "
              "what we say they are"))
    parser.add_argument(
        "--trace-samples", type=int, default=buffer_script.TRACE_SAMPLE_CAPACITY, metavar="N",
        help=("with --buffer-script rng-trace: how many frames to sample, 1..%d"
              % buffer_script.TRACE_SAMPLE_CAPACITY))
    parser.add_argument(
        "--call-address", type=lambda v: int(v, 0), default=None, metavar="ADDR",
        help=("with --buffer-script call: the ROM function to call, as a THUMB pointer (bit 0 "
              "set). 0x%08X is SeedRng and 0x%08X is Random [rom_map.py, read off this console in "
              "bs14]. 0 calls nothing, which checks the send path with the ROM left out"
              % (rom_map.thumb(rom_map.SEED_RNG), rom_map.thumb(rom_map.RANDOM))))
    parser.add_argument(
        "--call-arg", type=lambda v: int(v, 0), action="append", default=None, metavar="VALUE",
        help=("with --buffer-script call: one argument word, repeatable, up to eight. The first "
              "four go in r0..r3 and the rest on the stack at [sp+0..12], which is where bs42 "
              "read CreateMon's own prologue taking them and what bs43/bs44 proved on hardware"))
    parser.add_argument(
        "--call-watch", type=lambda v: int(v, 0), default=0, metavar="ADDR",
        help=("with --buffer-script call: one word read immediately BEFORE and immediately AFTER "
              "the call, both returned. 0x%08X is gRngValue. For a function that returns nothing, "
              "such as SeedRng, this is the only evidence the call did what it was called for"
              % rom_map.GRNG_VALUE))
    parser.add_argument(
        "--create-mon-call", type=lambda v: int(v, 0), default=None, metavar="ADDR",
        help=("with --buffer-script create-mon: the ROM function to call with EIGHT arguments, a "
              "THUMB pointer. The default is CreateMon at 0x%08X, read off this console in bs42; "
              "0 calls nothing, which checks the send path with the ROM left out"
              % rom_map.thumb(rom_map.CREATE_MON)))
    parser.add_argument(
        "--create-mon-species", type=lambda v: int(v, 0), default=1, metavar="N",
        help=("with --buffer-script create-mon: the species number, 1..%d (internal numbering, "
              "not the National Dex)" % buffer_script.MAX_SPECIES))
    parser.add_argument(
        "--create-mon-level", type=lambda v: int(v, 0), default=5, metavar="N",
        help="with --buffer-script create-mon: the level, 1..%d" % buffer_script.MAX_LEVEL)
    parser.add_argument(
        "--create-mon-iv", type=lambda v: int(v, 0), default=buffer_script.USE_RANDOM_IVS,
        metavar="N",
        help=("with --buffer-script create-mon: every IV set to this, 0..31. %d or more rolls "
              "them instead [USE_RANDOM_IVS], which makes the run non-deterministic"
              % buffer_script.USE_RANDOM_IVS))
    parser.add_argument(
        "--create-mon-personality", type=lambda v: int(v, 0), default=None, metavar="VALUE",
        help=("with --buffer-script create-mon: the 32-bit personality value, which fixes the "
              "nature, the gender, the ability slot and - with the trainer ids bs01 read - "
              "whether the mon is SHINY. Omitted, the console rolls one with Random32"))
    parser.add_argument(
        "--create-mon-ot-id-type", type=int, default=buffer_script.OT_ID_PLAYER_ID,
        choices=buffer_script.OT_ID_TYPES,
        help=("with --buffer-script create-mon: %d = the OT is the player and the id comes off "
              "the real save, %d = use --create-mon-ot-id, %d = rolled until not shiny"
              % buffer_script.OT_ID_TYPES))
    parser.add_argument(
        "--create-mon-ot-id", type=lambda v: int(v, 0), default=0, metavar="VALUE",
        help="with --buffer-script create-mon --create-mon-ot-id-type 1: the OT id to use")
    parser.add_argument(
        "--create-mon-append", action="store_true",
        help=("with --buffer-script create-mon: APPEND the finished mon to the player's party. "
              "The slot is computed from gSaveBlock1Ptr, never given, and it is always the first "
              "FREE one - playerParty[playerPartyCount] - so an occupied slot is never touched and "
              "no Pokemon can be destroyed. A full party writes nothing and says so. This is the "
              "player's LIVE SAVE and the console commits it to flash: needs --write-unsafe"))
    parser.add_argument(
        "--create-mon-append-dry-run", action="store_true",
        help=("with --buffer-script create-mon: the SAME run as --create-mon-append - the same "
              "call, the same arithmetic on the same gSaveBlock1Ptr - with the two stores that "
              "would change the save left out. It reports the party count and the address it "
              "WOULD have written, and reads that slot's current 100 bytes back so the answer "
              "says what a real run would overwrite. Writes nothing, so it needs no override"))
    parser.add_argument(
        "--create-mon-destination", type=lambda v: int(v, 0), default=0, metavar="ADDR",
        help=("with --buffer-script create-mon: copy the finished 100 bytes to this address in "
              "the console's memory. The mon is BUILT in our own image either way, so without "
              "this nothing on the console is written at all. Needs --write-unsafe"))
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
        "--hunt-nature", default=None, metavar="NAMES",
        help=("with --gift %s: which natures the search will accept, comma separated\n"
              "(%s), or plain ids. Without this it takes any."
              % (wonder_card_events.GIFT_RNG_MON_HUNT, ", ".join(native_script.NATURE_NAMES[:6])
                 + ", ...")))
    parser.add_argument(
        "--hunt-iv", action="append", default=None, metavar="STAT=N",
        help=("with --gift %s: a floor under one IV, repeatable (speed=31, attack=20). The stats\n"
              "are %s, named in the order the ROM DRAWS them - which is not the order the summary\n"
              "screen shows."
              % (wonder_card_events.GIFT_RNG_MON_HUNT, ", ".join(native_script.IV_FIELDS))))
    parser.add_argument(
        "--hunt-cap", type=lambda v: int(v, 0), default=None, metavar="N",
        help=("with --gift %s: how many states the stub may try before giving up and leaving the\n"
              "RNG alone. The default is the smallest cap that finds one %d times in 100."
              % (wonder_card_events.GIFT_RNG_MON_HUNT,
                 round(100 * native_script.SEARCH_CONFIDENCE))))
    parser.add_argument(
        "--hunt-freeze-frames", type=int, default=native_script.MAX_FREEZE_FRAMES, metavar="N",
        help=("with --gift %s: how long the search may block the overworld in the WORST case,\n"
              "in frames (default %d, about %.0f s). The field engine has not returned while it\n"
              "searches, so the player sees a still frame with the music playing; criteria whose\n"
              "search could take longer than this are refused before the card is built."
              % (wonder_card_events.GIFT_RNG_MON_HUNT, native_script.MAX_FREEZE_FRAMES,
                 native_script.MAX_FREEZE_FRAMES / 59.7275)))
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


def _hunt_asked(args):
    return any(value is not None for value in (args.hunt_nature, args.hunt_iv, args.hunt_cap))


def _hunt_definition(parser, args):
    """-> the card the command line asked for, composed, or None to send the registered one.

    The cost is printed HERE, before anything is on the air, because the number that matters to
    the player is how long the overworld stops while the stub searches - and a set of criteria
    that would stop it for too long is refused by native_script rather than sent
    [native_script.search_cost]."""
    if not _hunt_asked(args):
        return None
    hunts = (wonder_card_events.GIFT_RNG_MON_HUNT, wonder_card_events.GIFT_RNG_MON_HUNT_FAR,
             wonder_card_events.GIFT_RNG_MON_HUNT_BOTH)
    if args.gift not in hunts:
        parser.error(f"--hunt-* belong to --gift {' or --gift '.join(hunts)}; "
                     f"--gift {args.gift} has no search to steer")
    try:
        criteria = native_script.MonCriteria(
            natures=native_script.parse_natures(args.hunt_nature),
            iv_minimums=native_script.parse_iv_minimums(args.hunt_iv))
        cap = (native_script.cap_for(criteria) if args.hunt_cap is None else args.hunt_cap)
        cost = native_script.search_cost(criteria, cap)
        # Composed HERE, so that a search too slow to be allowed, or a stub too big to stage, is
        # an error on the command line and not one raised at the moment a console joins.
        compose = {
            wonder_card_events.GIFT_RNG_MON_HUNT_FAR: wonder_card_events.build_rng_mon_hunt_far_gift,
            wonder_card_events.GIFT_RNG_MON_HUNT_BOTH: wonder_card_events.build_rng_mon_hunt_both_gift,
        }.get(args.gift, wonder_card_events.build_rng_mon_hunt_gift)
        definition = compose(criteria, cap=args.hunt_cap,
                             max_freeze_frames=args.hunt_freeze_frames)
    except native_script.NativeScriptError as exc:
        parser.error(str(exc))
    print(f"hunting: {criteria.describe()} - 1 state in {1 / cost['probability']:,.0f}, "
          f"cap {cost['cap']:,}")
    print(f"  the overworld stops while it searches: about {cost['expected_seconds']:.1f} s "
          f"typically, {cost['worst_seconds']:.1f} s at the cap "
          f"(found {100 * cost['found_within_cap']:.1f}% of the time). ESTIMATED from the clock.")
    return definition


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
            if _hunt_asked(args):
                parser.error(f"--hunt-* steer --gift {wonder_card_events.GIFT_RNG_MON_HUNT}; "
                             "Wonder News carries no field script")
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
            if _hunt_asked(args):
                parser.error(f"--hunt-* steer --gift {wonder_card_events.GIFT_RNG_MON_HUNT}; "
                             "a buffer script runs in the Mystery Gift menu, not the overworld")
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
            if write_data is not None and args.buffer_script != buffer_script.SAVE_WRITE:
                parser.error(f"--write-* belongs to --buffer-script {buffer_script.SAVE_WRITE}")
            if args.write_unsafe and args.buffer_script not in (
                    buffer_script.SAVE_WRITE, buffer_script.CREATE_MON):
                parser.error(
                    f"--write-unsafe belongs to --buffer-script {buffer_script.SAVE_WRITE} and "
                    f"{buffer_script.CREATE_MON}, the two that write the console's memory")
            if args.buffer_script != buffer_script.CREATE_MON \
                    and (args.create_mon_call is not None or args.create_mon_destination
                         or args.create_mon_append or args.create_mon_append_dry_run):
                parser.error(
                    f"--create-mon-* belongs to --buffer-script {buffer_script.CREATE_MON}")
            if args.buffer_script != buffer_script.MEMORY_SCAN and args.scan_word is not None:
                parser.error(f"--scan-* belongs to --buffer-script {buffer_script.MEMORY_SCAN}")
            if args.buffer_script != buffer_script.TABLE_SCAN and args.table_delta is not None:
                parser.error(f"--table-* belongs to --buffer-script {buffer_script.TABLE_SCAN}")
            if args.buffer_script != buffer_script.RNG_TRACE \
                    and (args.trace_address is not None or args.trace_call):
                parser.error(f"--trace-* belongs to --buffer-script {buffer_script.RNG_TRACE}")
            if args.buffer_script != buffer_script.CALL \
                    and (args.call_address is not None or args.call_arg or args.call_watch):
                parser.error(f"--call-* belongs to --buffer-script {buffer_script.CALL}")
            if args.buffer_script != buffer_script.STRING_GATHER \
                    and args.gather_address is not None:
                parser.error(
                    f"--gather-* belongs to --buffer-script {buffer_script.STRING_GATHER}")
            payload = configmod.BufferScriptPayload(
                script=args.buffer_script, dump_address=args.dump_address,
                dump_block=args.dump_block, dump_offset=args.dump_offset,
                dump_size=args.dump_size, dump_file=args.dump_file,
                write_data=write_data, write_unsafe=args.write_unsafe,
                scan_word=args.scan_word, scan_start=args.scan_start,
                scan_end=args.scan_end, scan_blocks=args.scan_blocks,
                scan_max_calls=args.scan_max_calls,
                table_delta=args.table_delta, table_runlen=args.table_runlen,
                table_start=args.table_start, table_end=args.table_end,
                table_blocks=args.table_blocks, table_max_calls=args.table_max_calls,
                trace_address=args.trace_address, trace_call=args.trace_call,
                trace_samples=args.trace_samples,
                call_address=args.call_address, call_args=tuple(args.call_arg or ()),
                call_watch=args.call_watch,
                gather_address=args.gather_address, gather_count=args.gather_count,
                gather_stride=args.gather_stride, gather_maxlen=args.gather_maxlen,
                create_mon_call=args.create_mon_call,
                create_mon_species=args.create_mon_species,
                create_mon_level=args.create_mon_level,
                create_mon_fixed_iv=args.create_mon_iv,
                create_mon_personality=args.create_mon_personality,
                create_mon_ot_id_type=args.create_mon_ot_id_type,
                create_mon_ot_id=args.create_mon_ot_id,
                create_mon_destination=args.create_mon_destination,
                create_mon_append=args.create_mon_append,
                create_mon_append_dry_run=args.create_mon_append_dry_run)
        else:
            if args.news_id is not None:
                parser.error("--news-id is only meaningful with --news")
            phrase = (None if args.questionnaire is None
                      else easychat.parse_phrase(args.questionnaire))
            payload = configmod.MysteryGiftPayload(
                gift=args.gift, flag_id=gift_registry.resolve_flag_id(args),
                questionnaire=phrase, denied_message=args.denied_message,
                definition=_hunt_definition(parser, args))
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
        print(f"bin/frlgmg_host.py: error: {exc}", file=sys.stderr)
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
        # The artifact must describe what is actually sent: a run given --hunt-* carries its own
        # composed definition, and the registry still holds the one built with the defaults.
        definition = (config.payload.definition
                      or gift_registry.GIFT_REGISTRY.entry(args.gift).definition)
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
