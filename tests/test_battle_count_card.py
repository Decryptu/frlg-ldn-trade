#!/usr/bin/env python3
"""Offline coverage for the Battle Count Card, and for the thing that arms it.

`MysteryEventScript_BattleCard` [decomp:data/mystery_event_msg.s:162] only READS a counter. The
counters themselves are switched on by the PARTNER'S trainer card: `Task_ExchangeCards` passes the
u16 that follows the 96-byte card in the BLOCK_REQ_SIZE_100 buffer to
`MysteryGift_TryEnableStatsByFlagId`, which arms nothing unless it equals the flag id of the card
the console is holding [decomp:src/union_room.c:1777]. That u16 is ours to set.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import frlgmg_host  # noqa: E402
import frlgtrade_host  # noqa: E402
from frlgsim import (  # noqa: E402
    buffer_script,
    config as configmod,
    gift_registry,
    host_cli,
    linkplayer,
    mon,
    mystery_gift,
    wonder_card,
    wonder_card_events as event,
)
from frlgsim.gift_composer import (  # noqa: E402
    GET_CARD_BATTLES_WON, SPECIAL_GET_MYSTERY_GIFT_CARD_STAT, VAR_MYSTERY_GIFT_1,
    compile_definition,
)
from frlgsim.scrcmd import VAR_0x8008, VAR_RESULT  # noqa: E402
from test_gift_composer import ScriptVM  # noqa: E402


def _script():
    return compile_definition(event.BATTLE_COUNT_GIFT).ram_script


def _talk(wins, *, prize_taken=0):
    """One conversation, with the console reporting `wins` from GetMysteryGiftCardStat."""
    vm = ScriptVM(
        _script(),
        variables={VAR_MYSTERY_GIFT_1: 0, event.BATTLE_COUNT_PRIZE_TAKEN: prize_taken},
        special_results={SPECIAL_GET_MYSTERY_GIFT_CARD_STAT: wins})
    vm.run()
    return vm


def test_the_card_declares_the_type_that_makes_the_counters_move():
    """`IncrementCardStat` returns without writing unless the held card is CARD_TYPE_LINK_STAT
    [decomp:src/mystery_gift.c:461]. bs76 and bs78 are what a CARD_TYPE_GIFT card reads: zero,
    after a trade that had every other condition right."""
    card = compile_definition(event.BATTLE_COUNT_GIFT).card
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_LINK_STAT == 2

    from frlgsim.gift_composer import GiftValidationError
    import dataclasses
    stamped = dataclasses.replace(event.BATTLE_COUNT_GIFT.card, card_type=mystery_gift.CARD_TYPE_STAMP)
    try:
        compile_definition(dataclasses.replace(event.BATTLE_COUNT_GIFT, card=stamped))
    except GiftValidationError:
        pass
    else:
        raise AssertionError("a stamp card must come from the rally compiler")


def test_the_card_is_registered_and_reads_the_wins_selector():
    distribution = compile_definition(event.BATTLE_COUNT_GIFT)
    assert int.from_bytes(distribution.card[0:2], "little") == event.BATTLE_COUNT_FLAG_ID
    assert event.GIFT_BATTLE_COUNT in gift_registry.GIFT_REGISTRY.live_choices
    assert event.GIFT_BATTLE_COUNT in \
        frlgmg_host.build_parser()._option_string_actions["--gift"].choices

    # setvar VAR_RESULT, GET_CARD_BATTLES_WON then specialvar VAR_0x8008, the special: the selector
    # has to be in place before the special runs [decomp:src/field_specials.c:1957].
    selector = bytes([0x16]) + VAR_RESULT.to_bytes(2, "little") \
        + GET_CARD_BATTLES_WON.to_bytes(2, "little")
    read = bytes([0x26]) + VAR_0x8008.to_bytes(2, "little") \
        + SPECIAL_GET_MYSTERY_GIFT_CARD_STAT.to_bytes(2, "little")
    script = _script()
    assert script.index(selector) + len(selector) == script.index(read)


def test_under_three_wins_the_card_only_talks():
    for wins in (0, 1, 2):
        vm = _talk(wins)
        assert vm.items == [], f"a prize was given at {wins} wins"
        assert vm.vars[event.BATTLE_COUNT_PRIZE_TAKEN] == 0
        assert vm.messages


def test_at_three_wins_the_prize_is_given_once():
    vm = _talk(3)
    assert vm.items == [(event.ITEM_POTION, 1)]
    assert vm.vars[event.BATTLE_COUNT_PRIZE_TAKEN] == 1

    again = _talk(3, prize_taken=1)
    assert again.items == [], "the prize is once, as in the official script"
    assert again.messages


def test_a_count_past_three_is_not_a_prize_either():
    """`vgoto_if_ne VAR_0x8008, 3` [decomp:data/mystery_event_msg.s:167] is an equality, not a
    threshold: a fourth win takes the card past the payout, exactly as the official one does."""
    assert _talk(4).items == []
    assert _talk(9).items == []


def test_our_trainer_card_is_what_arms_the_console():
    profile = configmod.TrainerProfile(
        name="PkCamp", tid=0x8822, sid=0x47ED, card_flag_id=event.BATTLE_COUNT_FLAG_ID)
    card = profile.build_trainer_card()

    assert len(card) == linkplayer.TRAINER_CARD_BLOCK_SIZE == 100
    assert linkplayer.TC_OFF_WONDER_CARD == 96
    assert int.from_bytes(card[96:98], "little") == event.BATTLE_COUNT_FLAG_ID
    # The default arms nothing: flagId 0 returns FALSE before anything else is checked
    # [decomp:src/mystery_gift.c:551].
    assert int.from_bytes(configmod.DEFAULT_TRAINER.build_trainer_card()[96:98], "little") == 0


def test_the_trade_host_sends_the_flag_id_it_was_given():
    parser = frlgtrade_host.build_parser()
    args = parser.parse_args(["--live", "--card-flag-id", "1005", "x.pk3"])
    profile, _, _ = host_cli.build_host_config(parser, args)
    assert profile.card_flag_id == 1005

    from frlgsim.host_trade import HostTradeEngine
    party = [mon.Mon(b"\x01" + b"\x00" * 99)]
    engine = HostTradeEngine(party, profile=profile)
    assert engine.card_flag_id == 1005
    assert int.from_bytes(engine.trainer_card[96:98], "little") == 1005

    default = HostTradeEngine(party, profile=configmod.DEFAULT_TRAINER)
    assert int.from_bytes(default.trainer_card[96:98], "little") == 0


def test_the_counters_can_be_read_and_written_where_the_console_keeps_them():
    """SaveBlock1.mysteryGift.cardMetadata [decomp:include/global.h:681]. `MysteryGift_GetCardStat`
    reads it with no CRC check, so a save-dump reads the counter and a save-write sets it."""
    assert buffer_script.SAV1_MYSTERY_GIFT == 0x3120
    assert buffer_script.SAV1_CARD_METADATA == 0x3434
    assert (buffer_script.SAV1_CARD_BATTLES_WON,
            buffer_script.SAV1_CARD_BATTLES_LOST,
            buffer_script.SAV1_CARD_NUM_TRADES) == (0x3434, 0x3436, 0x3438)
    # The metadata sits between the card and the questionnaire words, whose offset the Mystery Gift
    # link data already agrees on.
    assert buffer_script.SAV1_CARD_METADATA - buffer_script.SAV1_MYSTERY_GIFT == 0x314
