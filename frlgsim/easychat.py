"""Easy-chat words for the trainer card's profile quote [include/constants/easy_chat.h].

A word is `(group & 0x7F) << 9 | (index & 0x1FF)` [EC_WORD, easy_chat.h:1089]. The card holds four
of them [TrainerCardRSE.easyChatProfile, trainer_card.h:28] and draws them as two lines of two.
`CopyEasyChatWord` prints "???" for any word its group rejects [easy_chat.c:166], and word 0 is
group EC_GROUP_POKEMON_2 index 0 (SPECIES_NONE), which is rejected -- so an all-zero profile is the
"??? ???" the console showed for our card in u08-u11.
"""

PROFILE_LENGTH = 4
UNDEFINED = 0xFFFF          # EC_WORD_UNDEFINED: prints nothing, and is never "???"

_GROUP_TRAINER = 0x1
_GROUP_STATUS = 0x2
_GROUP_GREETINGS = 0x4
_GROUP_PEOPLE = 0x5
_GROUP_CONDITIONS = 0x11
_GROUP_ACTIONS = 0x13
_GROUP_ADJECTIVES = 0x16


def word(group, index):
    return ((group & 0x7F) << 9) | (index & 0x1FF)


# A curated subset: enough to write a friendly line, every one checked against easy_chat.h.
WORDS = {
    "trade": word(_GROUP_TRAINER, 0x02),
    "link": word(_GROUP_TRAINER, 0x09),
    "pokemon": word(_GROUP_TRAINER, 0x0E),
    "cool": word(_GROUP_STATUS, 0x15),
    "thanks": word(_GROUP_GREETINGS, 0x00),
    "yes": word(_GROUP_GREETINGS, 0x01),
    "hello": word(_GROUP_GREETINGS, 0x0F),
    "no": word(_GROUP_GREETINGS, 0x1D),
    "hi": word(_GROUP_GREETINGS, 0x1E),
    "friend": word(_GROUP_PEOPLE, 0x33),
    "good": word(_GROUP_CONDITIONS, 0x05),
    "together": word(_GROUP_CONDITIONS, 0x0B),
    "please": word(_GROUP_ACTIONS, 0x11),
    "awesome": word(_GROUP_ADJECTIVES, 0x17),
    "": UNDEFINED,
}

# "HELLO FRIEND / LET'S TRADE" as close as the word list allows; anything is better than "???".
DEFAULT_QUOTE = ("hello", "friend", "trade", "pokemon")


def resolve_quote(names=None):
    """-> four word ids. `names` is up to four names from WORDS; short lists are padded with
    UNDEFINED, which prints as nothing rather than as "???"."""
    if names is None:
        names = DEFAULT_QUOTE
    if isinstance(names, str):
        names = [n.strip() for n in names.split(",")]
    names = list(names)
    if len(names) > PROFILE_LENGTH:
        raise ValueError(f"the card quote holds at most {PROFILE_LENGTH} words")
    out = []
    for name in names:
        key = name.strip().lower()
        if key not in WORDS:
            raise ValueError(f"unknown easy-chat word {name!r}; known: "
                             f"{', '.join(sorted(k for k in WORDS if k))}")
        out.append(WORDS[key])
    return tuple(out + [UNDEFINED] * (PROFILE_LENGTH - len(out)))
