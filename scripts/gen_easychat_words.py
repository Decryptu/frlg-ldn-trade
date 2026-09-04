#!/usr/bin/env python3
"""Regenerate frlgsim/easychat_words.py from the pokefirered decomp.

    ./scripts/gen_easychat_words.py [~/pokefirered]

The POKEMON and MOVE groups are skipped: IsECWordInvalid validates those against a value list
rather than a word count [decomp:src/easy_chat.c:118], so an arbitrary species or move id is not
necessarily a legal Easy Chat word.
"""
import os
import re
import sys

SKIP_GROUPS = ("POKEMON", "POKEMON_2", "MOVE_1", "MOVE_2")
GROUP_ORDER = (
    "TRAINER", "STATUS", "BATTLE", "GREETINGS", "PEOPLE", "VOICES", "SPEECH", "ENDINGS",
    "FEELINGS", "CONDITIONS", "ACTIONS", "LIFESTYLE", "HOBBIES", "TIME", "MISC",
    "ADJECTIVES", "EVENTS", "TRENDY_SAYING",
)
HEADER = '''"""Every Easy Chat word FRLG can print, generated from the decomp.

Keys are the `EC_WORD_*` constant name lower-cased [decomp:include/constants/easy_chat.h];
values are `(group << 9) | index` [EC_WORD, easy_chat.h:1089]. The POKEMON and MOVE groups are
left out on purpose: they are validated against a value list rather than a count
[IsECWordInvalid, easy_chat.c:118], so a species or move id is not automatically a legal word.
Regenerate with scripts/gen_easychat_words.py.
"""

WORDS = {'''


def generate(header_text):
    groups = {name: int(value, 16) for name, value in
              re.findall(r"#define EC_GROUP_(\w+)\s+0x([0-9a-fA-F]+)", header_text)}
    entries, seen = [], set()
    for name, group, index in re.findall(
            r"#define EC_WORD_(\w+)\s+\(EC_GROUP_(\w+) << 9\) \| 0x([0-9a-fA-F]+)", header_text):
        if group in SKIP_GROUPS:
            continue
        key = name.lower()
        if key in seen:
            raise SystemExit(f"duplicate easy-chat word {key!r}")
        seen.add(key)
        entries.append((key, (groups[group] << 9) | int(index, 16), group))
    found = {group for _, _, group in entries}
    if found != set(GROUP_ORDER):
        raise SystemExit(f"group set changed: {found ^ set(GROUP_ORDER)}")

    out = [HEADER]
    for group in GROUP_ORDER:
        out.append(f"    # EC_GROUP_{group}")
        line = "   "
        for key, value, owner in entries:
            if owner != group:
                continue
            piece = f' "{key}": 0x{value:04x},'
            if len(line) + len(piece) > 98:
                out.append(line)
                line = "   "
            line += piece
        if line.strip():
            out.append(line)
    out.append("}")
    return "\n".join(out) + "\n", len(entries)


def main(argv):
    decomp = os.path.expanduser(argv[1] if len(argv) > 1 else "~/pokefirered")
    header = os.path.join(decomp, "include", "constants", "easy_chat.h")
    with open(header) as fp:
        text = fp.read()
    body, count = generate(text)
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          os.pardir, "frlgsim", "easychat_words.py")
    with open(os.path.normpath(target), "w") as fp:
        fp.write(body)
    print(f"wrote {count} easy-chat words to {os.path.normpath(target)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
