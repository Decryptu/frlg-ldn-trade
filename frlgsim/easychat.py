"""Easy-chat phrases: the trainer card's profile quote and the visiting trainer's three lines.

A word is `(group & 0x7F) << 9 | (index & 0x1FF)` [EC_WORD, easy_chat.h:1089]. `easychat_words.WORDS`
holds every printable word, generated from the decomp; `CopyEasyChatWord` prints "???" for any word
its group rejects [easy_chat.c:166], and word 0 is group EC_GROUP_POKEMON_2 index 0 (SPECIES_NONE),
which is rejected -- so an all-zero profile is the "??? ???" the console showed for our card in
u08-u11. The trainer card holds four words [TrainerCardRSE.easyChatProfile, trainer_card.h:28] drawn
as two lines of two; a BattleTowerEReaderTrainer holds three six-word lines [global.h:293].
"""

from .easychat_values import (
    MOVE_1_VALUES, MOVE_2_VALUES, POKEMON_2_VALUES, POKEMON_VALUES)
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


# [decomp:include/constants/easy_chat.h:15]
GROUP_NAMES = {
    0x0: "POKEMON_2", 0x1: "TRAINER", 0x2: "STATUS", 0x3: "BATTLE", 0x4: "GREETINGS",
    0x5: "PEOPLE", 0x6: "VOICES", 0x7: "SPEECH", 0x8: "ENDINGS", 0x9: "FEELINGS",
    0xa: "CONDITIONS", 0xb: "ACTIONS", 0xc: "LIFESTYLE", 0xd: "HOBBIES", 0xe: "TIME",
    0xf: "MISC", 0x10: "ADJECTIVES", 0x11: "EVENTS", 0x12: "MOVE_1", 0x13: "MOVE_2",
    0x14: "TRENDY_SAYING", 0x15: "POKEMON",
}

WORD_NAMES = {value: name for name, value in WORDS.items()}


EC_GROUP_POKEMON_2 = 0x0
EC_GROUP_MOVE_1 = 0x12
EC_GROUP_MOVE_2 = 0x13
EC_GROUP_POKEMON = 0x15

# The four groups CopyEasyChatWord prints from gSpeciesNames / gMoveNames rather than from a
# per-language word table [decomp:src/easy_chat.c:155]. Their index is the species number or the
# move id, so the console prints its own localized name and the word means the same thing in every
# language. Everything else in WORDS is an English guess until a console has been seen to render it.
_VALUE_GROUPS = {
    EC_GROUP_POKEMON: POKEMON_VALUES, EC_GROUP_POKEMON_2: POKEMON_2_VALUES,
    EC_GROUP_MOVE_1: MOVE_1_VALUES, EC_GROUP_MOVE_2: MOVE_2_VALUES,
}


def species_word(species):
    """-> the Easy Chat word for a species, printed as that console's own name for it.

    Language-safe by construction. Proven on a French console (mev03): the player typed AKWAKWAK
    and the console stored POKEMON/55, and SPECIES_GOLDUCK is 55.
    """
    species = int(species)
    if species not in POKEMON_VALUES:
        raise ValueError(
            f"species {species} is not in EC_GROUP_POKEMON's value list, so IsECWordInvalid "
            "rejects it and the console prints \"???\"")
    return word(EC_GROUP_POKEMON, species)


def move_word(move):
    """-> the Easy Chat word for a move, printed as that console's own name for it.

    Language-safe by construction. Proven on a French console (mev03): AEROBLAST came back as
    MOVE_1/177, and MOVE_AEROBLAST is 177.
    """
    move = int(move)
    if move in MOVE_1_VALUES:
        return word(EC_GROUP_MOVE_1, move)
    if move in MOVE_2_VALUES:
        return word(EC_GROUP_MOVE_2, move)
    raise ValueError(
        f"move {move} is in neither MOVE group's value list, so IsECWordInvalid rejects it")


def parse_word(spec):
    """One Easy Chat word from a command line.

    Accepts an English word name (`hello`), a language-safe id by concept (`species:55`,
    `move:177`), a group/index pair (`FEELINGS/60`), or a raw number (`0x123c`). The last three
    exist because the English names are only a guess outside the species and move groups, and a
    phrase read off a real console arrives as ids.
    """
    text = str(spec).strip()
    if not text:
        return UNDEFINED
    lowered = text.lower()
    if lowered.startswith("species:"):
        return species_word(int(text.split(":", 1)[1], 0))
    if lowered.startswith("move:"):
        return move_word(int(text.split(":", 1)[1], 0))
    if "/" in text:
        group_name, _, index = text.partition("/")
        groups = {name: value for value, name in GROUP_NAMES.items()}
        group = groups.get(group_name.upper().replace(" ", "_"))
        if group is None:
            raise ValueError(f"unknown Easy Chat group {group_name!r}")
        return word(group, int(index, 0))
    try:
        return int(text, 0) & 0xFFFF
    except ValueError:
        pass
    key = lowered.replace(" ", "_").replace("-", "_")
    if key not in WORDS:
        raise ValueError(f"unknown easy-chat word {spec!r}")
    return WORDS[key]


def parse_phrase(text, length=4):
    """A comma-separated phrase -> `length` word ids."""
    parts = [part for part in str(text).split(",")]
    if len(parts) != length:
        raise ValueError(
            f"a questionnaire phrase is exactly {length} words, got {len(parts)}")
    return tuple(parse_word(part) for part in parts)


def is_language_safe(value):
    """True when the id names a species or a move, which every language prints correctly."""
    value = int(value) & 0xFFFF
    values = _VALUE_GROUPS.get(value >> 9)
    return values is not None and (value & 0x1FF) in values


def describe_word(value):
    """A word id as the console holds it, named as far as the ENGLISH table can name it.

    The localized ROMs carry their own group tables, so an id is only a reliable *slot*; what a
    French console prints there is a separate question. See `easychat_french.CONFIRMED`.
    """
    value = int(value) & 0xFFFF
    if value == UNDEFINED:
        return "-"
    group, index = value >> 9, value & 0x1FF
    slot = f"{GROUP_NAMES.get(group, f'group {group}')}/{index}"
    if is_language_safe(value):
        return f"{slot} (language-safe)"
    name = WORD_NAMES.get(value)
    return f"{name} [{slot}]" if name else f"0x{value:04x} [{slot}]"


def describe_words(values):
    return " ".join(describe_word(value) for value in values)
