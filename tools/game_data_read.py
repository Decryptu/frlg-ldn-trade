#!/usr/bin/env python3
"""Read back the ledger `--game-data-log` writes: what each console said about itself, and what
moved between its sessions. Offline; it never touches a console."""
import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from frlgsim import easychat, easychat_french, game_data_log      # noqa: E402


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="the jsonl ledger --game-data-log wrote")
    parser.add_argument("--json", action="store_true",
                        help="print the records themselves rather than the summary")
    parser.add_argument("--session", type=int, default=None, metavar="N",
                        help="re-parse session N's raw bytes and print every field of it")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    entries = game_data_log.read(args.path)
    if not entries:
        print(f"{args.path}: no sessions recorded")
        return 1

    if args.session is not None:
        if not 1 <= args.session <= len(entries):
            print(f"session must be between 1 and {len(entries)}")
            return 1
        entry = entries[args.session - 1]
        data = game_data_log.parse_raw(entry)
        print(f"session {args.session} ({entry.get('tag') or entry['time']}): {data.describe()}")
        for line in data.describe_extras():
            print("  " + line)
        for label, words in (("questionnaire", data.questionnaire_words),
                             ("battle profile", data.easy_chat_profile)):
            words = [word for word in words if word not in (0, easychat.UNDEFINED)]
            if words:
                print(f"  {label} in French: {easychat_french.render(words)}")
        unknown = game_data_log.unknown_words(entry)
        if unknown:
            print("  unrendered slots: "
                  + ", ".join(easychat.describe_word(value) for value in unknown))
        return 0

    if args.json:
        for entry in entries:
            print(json.dumps(entry, ensure_ascii=False))
        return 0

    for line in game_data_log.summary(entries):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
