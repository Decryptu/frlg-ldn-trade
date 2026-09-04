"""Easy-chat phrases: the trainer card's profile quote and the visiting trainer's three lines.

A word is `(group & 0x7F) << 9 | (index & 0x1FF)` [EC_WORD, easy_chat.h:1089]. `easychat_words.WORDS`
holds every printable word, generated from the decomp; `CopyEasyChatWord` prints "???" for any word
its group rejects [easy_chat.c:166], and word 0 is group EC_GROUP_POKEMON_2 index 0 (SPECIES_NONE),
which is rejected -- so an all-zero profile is the "??? ???" the console showed for our card in
u08-u11. The trainer card holds four words [TrainerCardRSE.easyChatProfile, trainer_card.h:28] drawn
as two lines of two; a BattleTowerEReaderTrainer holds three six-word lines [global.h:293].
"""

from .easychat_words import WORDS

PROFILE_LENGTH = 4
TRAINER_LINE_LENGTH = 6         # greeting / farewellPlayerLost / farewellPlayerWon
UNDEFINED = 0xFFFF              # EC_WORD_UNDEFINED: prints nothing, and is never "???"


def word(group, index):
    return ((group & 0x7F) << 9) | (index & 0x1FF)


# "HELLO FRIEND / LET'S TRADE" as close as the word list allows; anything is better than "???".
DEFAULT_QUOTE = ("hello", "friend", "trade", "pokemon")


def resolve_words(names, length):
    """-> `length` word ids. `names` is a comma-separated string or a sequence of keys from WORDS;
    short lists are padded with UNDEFINED, which prints as nothing rather than as "???". An empty
    name is an explicit UNDEFINED, so a word can be skipped mid-line."""
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",")]
    names = list(names)
    if len(names) > length:
        raise ValueError(f"this phrase holds at most {length} words, got {len(names)}")
    out = []
    for name in names:
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        if not key:
            out.append(UNDEFINED)
            continue
        if key not in WORDS:
            raise ValueError(f"unknown easy-chat word {name!r}")
        out.append(WORDS[key])
    return tuple(out + [UNDEFINED] * (length - len(out)))


def resolve_quote(names=None):
    """-> four word ids for a trainer card profile."""
    return resolve_words(DEFAULT_QUOTE if names is None else names, PROFILE_LENGTH)


def resolve_line(names):
    """-> six word ids for one visiting-trainer line."""
    return resolve_words(names, TRAINER_LINE_LENGTH)
