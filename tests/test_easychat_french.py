"""The French Easy Chat vocabulary, and the two independent ways it was established.

An Easy Chat id is `(group << 9) | index` - a SLOT. `easychat_words` is generated from the
ENGLISH decomp, so it names the slot and not what a French console prints in it. Two things say
what the console prints, and they were gathered completely differently:

  * a RENDER: ids put into a mail or a script and read off the console's screen by the player
    (mev02, mev03, bs07). One slot at a time, and it needs a human eye.
  * the ROM TABLE: sEasyChatGroup_* read out of the cartridge with `--buffer-script
    string-gather` (bs16 found the table by its own count fingerprint, bs17 read it, bs18 on
    read the words). A whole group a run, and it is the data the game itself indexes.

Neither is worth much alone. Together they are: where they overlap they must agree, and this
file is what enforces that.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import easychat, easychat_french             # noqa: E402
from frlgsim.easychat import WORDS                        # noqa: E402


def test_the_rom_table_agrees_with_every_word_read_off_the_console_screen():
    """The check that makes both sources evidence. A render and a ROM read of the same slot are
    independent all the way down - different runs, different mechanisms, different years of this
    project - so a disagreement means one of them is wrong and neither can be used until it is
    explained."""
    overlap = {slot: (word, easychat_french.ROM_WORDS[slot])
               for slot, word in easychat_french.CONFIRMED.items()
               if slot in easychat_french.ROM_WORDS}

    assert overlap, "no slot has been established both ways yet"
    assert [rendered for rendered, in_rom in overlap.values()] \
        == [in_rom for _rendered, in_rom in overlap.values()], overlap


def test_the_two_feelings_words_the_console_rendered_are_in_the_table_it_was_reading_from():
    """bs18 is the run, and these two slots are why it could be trusted the moment it landed:
    mev02 put EC_WORD_ENJOY in a mail and the console printed STRESSE, mev03 put EC_WORD_DONE in
    a script and it printed FURAX. Both were known before any of sEasyChatGroups was found."""
    assert easychat_french.french(WORDS["enjoy"]) == "STRESSE"
    assert easychat_french.french(WORDS["done"]) == "FURAX"
    assert easychat_french.ROM_WORDS[WORDS["enjoy"]] == "STRESSE"
    assert easychat_french.ROM_WORDS[WORDS["done"]] == "FURAX"


def test_a_group_read_off_the_console_is_read_whole():
    """A gather run that stopped on its budget leaves a group half known, and a half-known group
    is the one thing that would make `check` lie: it would pass a slot nobody has read."""
    from frlgsim import easychat_french_words as table
    for group, (tag, _address, words) in table.GROUPS.items():
        indices = sorted(words)
        assert indices == list(range(len(indices))), \
            f"EC_GROUP {group} ({tag}) has a hole at {set(range(len(indices))) - set(indices)}"


def test_species_and_move_slots_need_no_table_at_all():
    """EC_GROUP_POKEMON, POKEMON_2, MOVE_1 and MOVE_2 print from gSpeciesNames / gMoveNames
    indexed by species number and move id [decomp:src/easy_chat.c:155], so the console prints its
    own localized name and the slot means the same thing in every language. mev03 proved it: the
    player typed AKWAKWAK and the console stored POKEMON/55, SPECIES_GOLDUCK."""
    assert easychat.is_language_safe(easychat.species_word(55))
    assert easychat.is_language_safe(easychat.move_word(177))
    assert easychat_french.check([easychat.species_word(55), easychat.move_word(177)]) == ()


def test_check_still_names_a_slot_nobody_has_read():
    unread = easychat_french.check([WORDS["hot"], WORDS["enjoy"]])

    assert WORDS["enjoy"] not in unread          # bs18 read it
    assert easychat_french.french(WORDS["enjoy"]) == "STRESSE"


def test_render_prefers_what_the_console_prints_over_the_english_slot_name():
    line = easychat_french.render([WORDS["enjoy"], WORDS["done"], WORDS["sad"]])

    assert line.startswith("STRESSE FURAX ")
    assert "enjoy" not in line and "done" not in line
