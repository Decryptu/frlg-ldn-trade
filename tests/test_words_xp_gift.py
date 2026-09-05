#!/usr/bin/env python3
"""Offline coverage for the composed worlds-xp Mystery Gift."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import frlgmg_host  # noqa: E402
from frlgsim import (  # noqa: E402
    charmap,
    gift_registry,
    gift_to_bin,
    mystery_gift,
    save_inject,
    wonder_card,
    wonder_card_events as event,
)
from frlgsim import mg_script, mg_server  # noqa: E402
from frlgsim.gift_composer import (  # noqa: E402
    BattleLegendary,
    FLAG_MYSTERY_GIFT_DONE,
    SPECIAL_HAS_ALL_KANTO_MONS,
    VAR_MYSTERY_GIFT_1,
    compile_definition,
)
from test_gift_composer import ScriptVM  # noqa: E402
from test_mystery_gift_end_to_end import _run_full_stack  # noqa: E402


def _distribution():
    return compile_definition(event.WORLDS_XP_GIFT)


def test_definition_compiles_to_the_expected_card_and_cli_entry():
    distribution = _distribution()
    card = distribution.card
    assert len(card) == wonder_card.WONDER_CARD_SIZE
    assert int.from_bytes(card[0:2], "little") == event.WORLDS_XP_GIFT_FLAG_ID
    assert int.from_bytes(card[2:4], "little") == event.SPECIES_CLAYDOL
    assert int.from_bytes(card[4:8], "little") == event.WORLDS_XP_GIFT_FLAG_ID - 1000
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_GIFT
    assert (card[8] >> 6) & 0x3 == mystery_gift.SEND_TYPE_ALLOWED_ALWAYS
    assert card[9] == 0
    assert charmap.decode(card[10:50]) == event.WORLDS_XP_GIFT.card.title
    assert len(distribution.ram_script) <= 995
    battle_actions = tuple(
        stage.actions[-1]
        for stage in event.WORLDS_XP_GIFT.delivery.delivery[7:10]
    )
    assert all(isinstance(action, BattleLegendary) for action in battle_actions)
    for species in (
        wonder_card.SPECIES_SUICUNE,
        wonder_card.SPECIES_ENTEI,
        wonder_card.SPECIES_RAIKOU,
    ):
        expected_tail = (
            bytes([0xB6]) + species.to_bytes(2, "little")
            + bytes([
                wonder_card.LEGENDARY_BEAST_LEVEL,
                0, 0, 0x25, 0x38, 0x01, 0x02,
            ])
        )
        assert expected_tail in distribution.ram_script

    slug = event.GIFT_WORLDS_XP
    assert slug in gift_registry.GIFT_REGISTRY.live_choices
    assert slug in gift_registry.GIFT_REGISTRY.static_choices
    assert slug in frlgmg_host.build_parser()._option_string_actions["--gift"].choices
    assert slug in gift_to_bin.build_parser()._option_string_actions["--gift"].choices
    assert slug in save_inject.build_parser()._option_string_actions["--gift"].choices


def test_first_visit_gives_the_baltoy_egg_then_starts_the_matching_beast_battle():
    cases = (
        (0, wonder_card.OBJ_EVENT_GFX_SUICUNE, wonder_card.SPECIES_SUICUNE, 0),
        (1, wonder_card.OBJ_EVENT_GFX_ENTEI, wonder_card.SPECIES_ENTEI, 1),
        (2, wonder_card.OBJ_EVENT_GFX_RAIKOU, wonder_card.SPECIES_RAIKOU, 2),
    )
    script = _distribution().ram_script
    for starter, graphics, species, sprite_id in cases:
        run = ScriptVM(script, variables={event.VAR_STARTER_MON: starter}).run()
        assert run.eggs == [event.SPECIES_BALTOY]
        assert run.items == [(wonder_card.ITEM_MASTER_BALL, 1)]
        assert run.moves == [(7, 0, 287), (7, 1, 192), (7, 2, 284), (7, 3, 323)]
        assert run.sprites == [(graphics, sprite_id, 11, 20, 3, wonder_card.DIR_WEST)]
        assert run.battles == [(species, wonder_card.LEGENDARY_BEAST_LEVEL, 0)]
        assert run.vars[VAR_MYSTERY_GIFT_1] == 0
        assert run.vars[event.WORLDS_XP_STATE_VAR] == event.WORLDS_XP_STATE_BATTLED
        assert FLAG_MYSTERY_GIFT_DONE not in run.flags


def test_revisit_requires_the_kanto_pokedex_then_gives_celebi():
    script = _distribution().ram_script
    first = ScriptVM(script, variables={event.VAR_STARTER_MON: 0}).run()
    assert first.vars[VAR_MYSTERY_GIFT_1] == 0
    assert first.vars[event.WORLDS_XP_STATE_VAR] == event.WORLDS_XP_STATE_BATTLED

    blocked = ScriptVM(
        script,
        variables={**first.vars, event.VAR_STARTER_MON: 0},
        flags=first.flags,
        special_results={SPECIAL_HAS_ALL_KANTO_MONS: 0},
    ).run()
    assert blocked.eggs == blocked.mons == blocked.battles == blocked.items == []
    assert blocked.vars[VAR_MYSTERY_GIFT_1] == 0
    assert blocked.vars[event.WORLDS_XP_STATE_VAR] == event.WORLDS_XP_STATE_BATTLED
    assert FLAG_MYSTERY_GIFT_DONE not in blocked.flags
    assert [charmap.decode(line) for line in blocked.messages[-1].split(b"\xfe")] == [
        "Finish the DEX!",
    ]

    complete = ScriptVM(
        script,
        variables={**blocked.vars, event.VAR_STARTER_MON: 0},
        flags=blocked.flags,
        special_results={SPECIAL_HAS_ALL_KANTO_MONS: 1},
    ).run()
    assert complete.mons == [(wonder_card.SPECIES_CELEBI, 50, 0)]
    assert complete.sprites == []
    assert complete.moves == []
    assert complete.vars[VAR_MYSTERY_GIFT_1] == 0
    assert complete.vars[event.WORLDS_XP_STATE_VAR] == event.WORLDS_XP_STATE_RECEIVED
    assert FLAG_MYSTERY_GIFT_DONE not in complete.flags

    later = ScriptVM(
        script,
        variables={**complete.vars, event.VAR_STARTER_MON: 0},
        flags=complete.flags,
    ).run()
    assert later.eggs == later.mons == later.battles == later.items == []
    assert [charmap.decode(line) for line in later.messages[-1].split(b"\xfe")] == [
        "Visit MercuryEnigma.github.io/pkcamp",
    ]


def test_distribution_survives_the_impaired_reliable_rfu_stack():
    distribution = _distribution()
    run = _run_full_stack(payload=distribution, max_ms=9000)
    assert run.engine.result == mg_server.SVR_MSG_CARD_SENT
    assert run.console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert run.console.saved_card == distribution.card
    assert run.console.saved_ram_script.startswith(distribution.ram_script)
    assert run.console.saved_ram_script[len(distribution.ram_script):] == \
        b"\x00" * (995 - len(distribution.ram_script))
