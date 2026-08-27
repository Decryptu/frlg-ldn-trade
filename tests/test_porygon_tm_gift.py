#!/usr/bin/env python3
"""Offline coverage for the composed Porygon/Clefairy TM gift."""

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
from frlgsim.gift_composer import (  # noqa: E402
    FLAG_MYSTERY_GIFT_DONE,
    VAR_MYSTERY_GIFT_1,
    compile_definition,
)
from test_gift_composer import ScriptVM  # noqa: E402
from test_mystery_gift_end_to_end import _run_full_stack  # noqa: E402
from frlgsim import mg_script, mg_server  # noqa: E402


def _distribution():
    return compile_definition(event.PORYGON_TM_GIFT)


def test_definition_compiles_to_the_expected_porygon_card_and_cli_entry():
    distribution = _distribution()
    card = distribution.card
    assert len(card) == wonder_card.WONDER_CARD_SIZE
    assert int.from_bytes(card[0:2], "little") == event.PORYGON_TM_GIFT_FLAG_ID
    assert int.from_bytes(card[2:4], "little") == event.SPECIES_PORYGON
    assert int.from_bytes(card[4:8], "little") == 7
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_GIFT
    assert card[9] == 0
    assert charmap.decode(card[10:50]) == "PORYGON TM GIFT"
    assert charmap.decode(card[50:90]) == "Two useful techniques"
    assert [charmap.decode(card[offset:offset + 40])
            for offset in range(90, 250, 40)] == [
                "CLEFAIRY has two special TMs",
                "waiting for you!",
                "Visit the deliveryman on the",
                "2nd floor of a Pokemon Center.",
            ]
    assert len(distribution.ram_script) == 433

    slug = event.GIFT_PORYGON_TMS
    assert slug in gift_registry.GIFT_REGISTRY.live_choices
    assert slug in gift_registry.GIFT_REGISTRY.static_choices
    assert slug in frlgmg_host.build_parser()._option_string_actions["--gift"].choices
    assert slug in gift_to_bin.build_parser()._option_string_actions["--gift"].choices
    assert slug in save_inject.build_parser()._option_string_actions["--gift"].choices

    host_parser = frlgmg_host.build_parser()
    host_config = frlgmg_host.build_run_config(
        host_parser, host_parser.parse_args(["--live", "--gift", slug]))
    export_args = gift_to_bin.build_parser().parse_args(["--gift", slug])
    inject_args = save_inject.build_parser().parse_args(["game.sav", "--gift", slug])
    assert host_config.payload.flag_id == event.PORYGON_TM_GIFT_FLAG_ID
    assert gift_registry.resolve_flag_id(export_args) == event.PORYGON_TM_GIFT_FLAG_ID
    assert gift_registry.resolve_flag_id(inject_args) == event.PORYGON_TM_GIFT_FLAG_ID

    override = gift_to_bin.build_parser().parse_args([
        "--gift", slug, "--flag-id", "1012"])
    assert gift_registry.resolve_flag_id(override) == 1012
    assert int.from_bytes(
        gift_registry.GIFT_REGISTRY.build_static(slug, flag_id=1012)[0][4:8], "little") == 12


def test_delivery_places_clefairy_three_tiles_right_then_gives_both_tms():
    run = ScriptVM(_distribution().ram_script).run()
    assert run.sprites == [(
        event.OBJ_EVENT_GFX_CLEFAIRY, 0, 13, 20, 3, event.DIR_WEST)]
    assert run.items == [
        (event.ITEM_TM29_PSYCHIC, 1),
        (event.ITEM_TM46_THIEF, 1),
    ]
    assert run.vars[VAR_MYSTERY_GIFT_1] == 2
    assert FLAG_MYSTERY_GIFT_DONE in run.flags
    assert wonder_card.flag_for_flag_id(event.PORYGON_TM_GIFT_FLAG_ID) in run.flags
    assert [charmap.decode(message) for message in run.messages] == [
        "A special CLEFAIRY delivery has arrived!",
        "CLEFAIRY brought you TM29 PSYCHIC!",
        "CLEFAIRY also brought you TM46 THIEF!",
    ]

    revisit = ScriptVM(
        _distribution().ram_script, variables=run.vars, flags=run.flags).run()
    assert revisit.items == revisit.sprites == []
    assert len(revisit.messages) == 1
    assert [charmap.decode(line) for line in revisit.messages[0].split(b"\xFE")] == [
        "CLEFAIRY already delivered both TMs.",
        "Use PSYCHIC and THIEF wisely!",
    ]


def test_thief_bag_failure_resumes_without_duplicate_psychic():
    script = _distribution().ram_script
    failed = ScriptVM(script, bag_space=(True, False)).run()
    assert failed.items == [(event.ITEM_TM29_PSYCHIC, 1)]
    assert failed.vars[VAR_MYSTERY_GIFT_1] == 1
    assert FLAG_MYSTERY_GIFT_DONE not in failed.flags

    retry = ScriptVM(
        script, variables=failed.vars, flags=failed.flags, bag_space=True).run()
    assert retry.items == [(event.ITEM_TM46_THIEF, 1)]
    assert retry.sprites == []
    assert retry.vars[VAR_MYSTERY_GIFT_1] == 2
    assert FLAG_MYSTERY_GIFT_DONE in retry.flags


def test_distribution_survives_the_impaired_reliable_rfu_stack():
    distribution = _distribution()
    run = _run_full_stack(payload=distribution, max_ms=9000)
    assert run.engine.result == mg_server.SVR_MSG_CARD_SENT
    assert run.console.result == mg_script.CLI_MSG_CARD_RECEIVED
    assert run.console.saved_card == distribution.card
    assert run.console.saved_ram_script.startswith(distribution.ram_script)
    assert run.console.saved_ram_script[len(distribution.ram_script):] == \
        b"\x00" * (995 - len(distribution.ram_script))
    assert run.console.dropped_inits == run.console.dropped_fragments == 0
    assert run.radio.dropped and run.radio.duplicated


if __name__ == "__main__":
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for name, test in tests:
        test()
        print("ok   ", name)
    print(f"\n{len(tests)}/{len(tests)} passed")
