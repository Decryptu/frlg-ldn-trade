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

This module is the ground truth as it accumulates, one observation at a time. `CONFIRMED` holds
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

from .easychat import UNDEFINED, WORDS, describe_word

# slot id -> the word a French console prints there. Only entries actually seen on hardware.
CONFIRMED = {
    WORDS["hello"]: "SALUT",                # GREETINGS/15, mev02
    WORDS["friend"]: "AMIS",                # PEOPLE/51,    mev02
    WORDS["i_ve_arrived"]: "JE SUIS LA",    # GREETINGS/18, mev02
    WORDS["thank_you"]: "MERCI",            # GREETINGS/17, mev02
    WORDS["enjoy"]: "STRESSE",              # FEELINGS/42,  mev02 - NOT "enjoy"
}

# Slots whose French word is not a translation of the English name in `WORDS`. Never compose with
# these unless the French word is the one you want.
DIVERGENT = frozenset({WORDS["enjoy"]})


class UnverifiedFrenchWord(Exception):
    """A slot nobody has yet seen rendered on the French console."""


def french(value):
    """-> what the French console prints for this id, or None if it has never been observed."""
    return CONFIRMED.get(int(value) & 0xFFFF)


def render(values):
    """-> the French line, with a '?' for every slot still unobserved."""
    out = []
    for value in values:
        value = int(value) & 0xFFFF
        if value == UNDEFINED:
            continue
        out.append(CONFIRMED.get(value, f"?{describe_word(value)}?"))
    return " ".join(out)


def check(values, *, strict=False):
    """-> the ids that have never been seen on a French console.

    With `strict`, raise instead. Use it on anything a French player will read: composing from the
    English table is a guess, and `EC_WORD_ENJOY` is the standing proof that the guess can be
    wrong.
    """
    unknown = tuple(int(value) & 0xFFFF for value in values
                    if int(value) & 0xFFFF != UNDEFINED
                    and (int(value) & 0xFFFF) not in CONFIRMED)
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
    "CONFIRMED", "DIVERGENT", "UnverifiedFrenchWord", "check", "french", "observe", "render",
]
