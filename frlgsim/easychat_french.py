"""What a FRENCH console actually prints for an Easy Chat word id.

`easychat_words.WORDS` is generated from the English decompilation, and an id is
`(group << 9) | index` — a **slot**, not a word. Every localized ROM carries its own
`gEasyChatGroup_*` tables, so the same slot can hold a different word in each language, and the
decomp cannot tell us the French one.

That is not a theory. Run `mev02` put nine word ids into a `struct Mail` and the console rendered:

    SALUT AMIS / JE SUIS LA / MERCI STRESSE

Four of the five slots we filled held the word the English table promised. The fifth,
`EC_WORD_ENJOY` (FEELINGS/42), printed **STRESSE** — an unrelated word. So the English table is
mostly right and occasionally wrong, which is the worst kind of wrong: nothing warns you.

**There is one part of the vocabulary that needs no verification at all.** `CopyEasyChatWord`
prints EC_GROUP_POKEMON, POKEMON_2, MOVE_1 and MOVE_2 out of `gSpeciesNames` / `gMoveNames`
[decomp:src/easy_chat.c:155], indexed by the species number or the move id — so the console prints
its own localized name and the word means the same thing in every language. `easychat.species_word`
and `easychat.move_word` build those, and `easychat.is_language_safe` recognises them. mev03 proved
it: the player typed AKWAKWAK and the console stored POKEMON/55 (SPECIES_GOLDUCK), and AEROBLAST
came back as MOVE_1/177 (MOVE_AEROBLAST). Prefer these for anything a player will read.

This module is the ground truth for the rest, as it accumulates, one observation at a time. `CONFIRMED` holds
slots seen rendered on a real French console; `DIVERGENT` holds slots where the French word is not
the English one. Compose messages out of `CONFIRMED` and the console says what you meant.

Two ways to add to it, both cheap:

- **Write and read back.** Put ids in a mail, a trainer-card profile or a visiting trainer's lines
  and have the player read the screen. Nine, four and eighteen slots per run.
- **Let the console tell us.** The Poke Mart questionnaire stores four Easy Chat words in
  `gSaveBlock1Ptr->mysteryGift.questionnaireWords` [decomp:src/mystery_gift.c:84], and every
  Mystery Gift session ships them to us inside `MysteryGiftLinkGameData` [`:361`]. A player who
  fills the questionnaire with four French words hands us their exact ids on the next run, at no
  extra cost. The host logs them; `SVR_CHECK_QUESTIONNAIRE` is what makes them a password gate.
"""

from .easychat import UNDEFINED, WORDS, describe_word, is_language_safe
from .easychat_french_words import WORDS as ROM_WORDS

# What the console's OWN ROM says, read out of sEasyChatGroup_* with `--buffer-script
# string-gather` (bs16 found the table, bs17 read it, bs18 onwards read the words). This is
# stronger evidence than a render: a render proves one slot at a time and needs a player to read
# the screen, while this is the table the game itself indexes. `CONFIRMED` below is kept because
# it was gathered independently, and tests/test_easychat_french.py requires the two to agree
# wherever they overlap - which is what makes either of them trustworthy.

# slot id -> the word a French console prints there. Only entries actually seen on hardware.
CONFIRMED = {
    WORDS["hello"]: "SALUT",                # GREETINGS/15, mev02, matches
    WORDS["i_ve_arrived"]: "JE SUIS LA",    # GREETINGS/18, mev02, matches
    WORDS["thank_you"]: "MERCI",            # GREETINGS/17, mev02, matches
    WORDS["friend"]: "AMIS",                # PEOPLE/51,    mev02, matches
    WORDS["why"]: "POURQUOI",               # MISC/37,      mev03, matches
    WORDS["enjoy"]: "STRESSE",              # FEELINGS/42,  mev02 - NOT "enjoy"
    WORDS["done"]: "FURAX",                 # FEELINGS/60,  mev03 - NOT "done"
    # bs07, and by the ENCODE direction, which is stronger than a render: the player retyped the
    # game's own default questionnaire phrase, CONNEXION AVEC LES DRESSEURS, and the console shipped
    # us these four slots in that order. Word i is slot i because the questionnaire stores four words
    # in order [mystery_gift.c:84].
    WORDS["link"]: "CONNEXION",             # TRAINER/9,    bs07, matches
    WORDS["with"]: "AVEC",                  # ENDINGS/48,   bs07, matches
    WORDS["case"]: "LES",                   # SPEECH/12,    bs07 - NOT "case"
    # bs20 CORRECTED THIS ONE: the ROM holds DRESSEUR, singular, and no DRESSEURS exists anywhere
    # in the vocabulary. bs07 recorded the plural because it was written down from the phrase on
    # the console's screen, and a phrase read by eye is weaker evidence than the table the game
    # indexes. The four questionnaire IDS are untouched and the gate is unaffected - only the
    # gloss was wrong. The phrase really renders CONNEXION AVEC LES DRESSEUR.
    WORDS["trainer"]: "DRESSEUR",           # TRAINER/11,   bs07 render, CORRECTED by bs20
}

# Slots whose French word is not a translation of the English name in `WORDS`. Never compose with
# these unless the French word is the one you want.
#
# HYPOTHESIS, WEAKENED by bs07 and kept only as a lead: the first two divergences were both in
# EC_GROUP_FEELINGS, but the third is SPEECH/12, so "only FEELINGS diverges" is dead. Eight of eleven
# observed slots match the English table and three do not, spread over two groups. There is no
# shortcut; verify each slot you intend to use.
DIVERGENT = frozenset({WORDS["enjoy"], WORDS["done"], WORDS["case"]})


# The phrase this project's French FireRed currently holds in its Poke Mart questionnaire, read off
# the console in mev03. `SVR_CHECK_QUESTIONNAIRE` compares all four ids in order, so this is the key
# to `MysteryGiftServer(..., questionnaire=...)`.
# What the player's console currently answers with, read off it in bs07: the game's own DEFAULT French
# phrase, CONNEXION AVEC LES DRESSEURS. The player reverted it from the custom one, so this is what
# any `--questionnaire` gate must be set to now. Every Mystery Gift session logs the current four
# ("Console questionnaire words: ..."), so re-read them rather than trusting this line.
CONSOLE_QUESTIONNAIRE = (0x0209, 0x1030, 0x0E0C, 0x020B)     # CONNEXION AVEC LES DRESSEUR
# The custom phrase the console held for mev04-mev06, kept because those runs are the proof that the
# gate refuses a wrong phrase and accepts a right one.
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
