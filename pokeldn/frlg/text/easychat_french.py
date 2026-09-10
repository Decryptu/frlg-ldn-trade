"""What a FRENCH console actually prints for an Easy Chat word id.

An id is `(group << 9) | index`, a slot rather than a word, and every localized ROM carries its
own `gEasyChatGroup_*` tables. `CONFIRMED` holds slots seen rendered on a real French console;
`DIVERGENT` holds slots where the French word is not the English one the decomp promises
(EC_WORD_ENJOY renders as STRESSE). Compose out of `CONFIRMED`.

The four groups `CopyEasyChatWord` prints from `gSpeciesNames` / `gMoveNames`
[decomp:src/easy_chat.c:155] need no verification in any language; `easychat.is_language_safe`
recognises them. docs/frlg_rom_map.md.
"""

from pokeldn.frlg.text.easychat import UNDEFINED, WORDS, describe_word, is_language_safe
from pokeldn.frlg.text.easychat_french_words import WORDS as ROM_WORDS

# What the console's own ROM says, read out of sEasyChatGroup_* with `--buffer-script
# string-gather`. This is the table the game itself indexes; a render proves one slot at a time and
# needs a player to read the screen. `CONFIRMED` below was gathered independently, and
# tests/test_easychat_french.py requires the two to agree wherever they overlap.

# slot id -> the word a French console prints there. Only entries actually seen on hardware.
CONFIRMED = {
    WORDS["hello"]: "SALUT",                # GREETINGS/15, matches
    WORDS["i_ve_arrived"]: "JE SUIS LA",    # GREETINGS/18, matches
    WORDS["thank_you"]: "MERCI",            # GREETINGS/17, matches
    WORDS["friend"]: "AMIS",                # PEOPLE/51,    matches
    WORDS["why"]: "POURQUOI",               # MISC/37,      matches
    WORDS["enjoy"]: "STRESSE",              # FEELINGS/42,  not "enjoy"
    WORDS["done"]: "FURAX",                 # FEELINGS/60,  not "done"
    # These four came back from the encode direction, which is stronger than a render: the player
    # retyped the game's own default questionnaire phrase and the console sent these four slots in
    # that order. Word i is slot i because the questionnaire stores four words in order
    # [mystery_gift.c:84].
    WORDS["link"]: "CONNEXION",             # TRAINER/9,    matches
    WORDS["with"]: "AVEC",                  # ENDINGS/48,   matches
    WORDS["case"]: "LES",                   # SPEECH/12,    not "case"
    # The ROM holds DRESSEUR, singular; no DRESSEURS exists in the vocabulary. The phrase renders
    # CONNEXION AVEC LES DRESSEUR.
    WORDS["trainer"]: "DRESSEUR",           # TRAINER/11,   from the table, not from a render
}

# Slots whose French word is not a translation of the English name in `WORDS`. Never compose with
# these unless the French word is the one you want.
#
# Eight of eleven observed slots match the English table and three do not, spread over two groups.
# There is no shortcut; verify each slot you intend to use.
DIVERGENT = frozenset({WORDS["enjoy"], WORDS["done"], WORDS["case"]})


# The phrase the French FireRed holds in its Poke Mart questionnaire, read off the console: the
# game's own default French phrase. `SVR_CHECK_QUESTIONNAIRE` compares all four ids in order, so
# this is the key to `MysteryGiftServer(..., questionnaire=...)`. Every Mystery Gift session logs
# the console's current four ("Console questionnaire words: ..."); re-read them rather than
# trusting this line.
CONSOLE_QUESTIONNAIRE = (0x0209, 0x1030, 0x0E0C, 0x020B)     # CONNEXION AVEC LES DRESSEUR
# A custom phrase the console has held, which is what proved the gate refuses a wrong phrase and
# accepts a right one.
CONSOLE_QUESTIONNAIRE_CUSTOM = (0x2A37, 0x123C, 0x24B1, 0x1E25)   # AKWAKWAK FURAX AEROBLAST POURQUOI


class UnverifiedFrenchWord(Exception):
    """A slot nobody has yet seen rendered on the French console."""


def french(value):
    """-> what the French console prints for this id, or None if it is not known yet.

    The ROM table is asked first: it covers a whole group at a time and comes from the console's
    own data rather than from someone reading a screen.
    """
    value = int(value) & 0xFFFF
    word = ROM_WORDS.get(value)
    return CONFIRMED.get(value) if word is None else word


def render(values):
    """-> the French line, with a '?' for every slot still unobserved."""
    out = []
    for value in values:
        value = int(value) & 0xFFFF
        if value == UNDEFINED:
            continue
        word = french(value)
        out.append(f"?{describe_word(value)}?" if word is None else word)
    return " ".join(out)


def check(values, *, strict=False):
    """-> the ids that have never been seen on a French console.

    With `strict`, raise instead. Use it on anything a French player will read: composing from the
    English table is a guess, and `EC_WORD_ENJOY` is the standing proof that the guess can be
    wrong.
    """
    unknown = tuple(int(value) & 0xFFFF for value in values
                    if int(value) & 0xFFFF != UNDEFINED
                    and not is_language_safe(value)
                    and french(value) is None)
    if unknown and strict:
        raise UnverifiedFrenchWord(
            "these slots have never been seen rendered on the French console: "
            + ", ".join(describe_word(value) for value in unknown))
    return unknown


def observe(value, word, *, divergent=None):
    """Record what the console printed for a slot. Returns True when this is news."""
    value = int(value) & 0xFFFF
    known = CONFIRMED.get(value)
    if known == word:
        return False
    CONFIRMED[value] = word
    return known is None or known != word


__all__ = [
    "CONFIRMED", "DIVERGENT", "ROM_WORDS", "CONSOLE_QUESTIONNAIRE", "CONSOLE_QUESTIONNAIRE_CUSTOM", "UnverifiedFrenchWord", "check", "french", "observe", "render",
]
