"""The trainer card's profile quote [TrainerCardRSE.easyChatProfile, include/trainer_card.h:28].

u08-u11: the console rendered our card's quote as "??? ???". A word is
(group & 0x7F) << 9 | (index & 0x1FF) [EC_WORD, easy_chat.h:1089], and an all-zero profile is word
0 = group EC_GROUP_POKEMON_2 index 0 (SPECIES_NONE), which IsECWordInvalid rejects, so
CopyEasyChatWord prints gText_ThreeQuestionMarks [easy_chat.c:166-171].
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from frlgsim import easychat, linkplayer  # noqa: E402


def _quote_of(card):
    return [int.from_bytes(card[easychat_off + i * 2:easychat_off + 2 + i * 2], "little")
            for i in range(easychat.PROFILE_LENGTH)]


easychat_off = linkplayer.TC_OFF_EASY_CHAT


def test_the_word_encoding_matches_the_decomp_macro():
    assert easychat.word(0x4, 0x0F) == (0x4 << 9) | 0x0F == 2063     # EC_WORD_HELLO
    assert easychat.WORDS["hello"] == 2063
    assert easychat.WORDS["friend"] == (0x5 << 9) | 0x33             # EC_WORD_FRIEND
    assert easychat.WORDS["trade"] == (0x1 << 9) | 0x02              # EC_WORD_TRADE


def test_the_default_card_no_longer_carries_the_word_that_prints_question_marks():
    card = linkplayer.build_trainer_card(
        linkplayer.LinkPlayer(name="PkCamp", version=linkplayer.VERSION_FIRE_RED))
    words = _quote_of(card)
    assert 0 not in words, "word 0 is rejected by IsECWordInvalid and prints as ???"
    assert words == list(easychat.resolve_quote())


def test_a_short_quote_is_padded_with_undefined_not_with_zero():
    """EC_WORD_UNDEFINED prints nothing; zero prints "???"."""
    assert easychat.resolve_quote("hi,friend") == (
        easychat.WORDS["hi"], easychat.WORDS["friend"],
        easychat.UNDEFINED, easychat.UNDEFINED)


def test_an_unknown_or_oversized_quote_is_refused():
    with pytest.raises(ValueError):
        easychat.resolve_quote("hello,nonsense")
    with pytest.raises(ValueError):
        easychat.resolve_quote("hi,hi,hi,hi,hi")


def test_the_quote_does_not_disturb_the_rest_of_the_card():
    p = linkplayer.LinkPlayer(name="PkCamp", version=linkplayer.VERSION_FIRE_RED)
    plain = bytearray(linkplayer.build_trainer_card(p, mon_species=[1, 2, 3]))
    quoted = bytearray(linkplayer.build_trainer_card(p, mon_species=[1, 2, 3], quote="hi"))
    lo, hi = easychat_off, easychat_off + 2 * easychat.PROFILE_LENGTH
    assert plain[:lo] == quoted[:lo] and plain[hi:] == quoted[hi:]
    assert len(quoted) == len(plain)
