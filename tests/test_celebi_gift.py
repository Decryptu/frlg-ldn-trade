#!/usr/bin/env python3
"""Offline coverage for the composed Celebi Mystery Gift."""

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
    save_inject,
    wonder_card,
    wonder_card_events,
)
from frlgsim import mystery_gift, mg_script, mg_server  # noqa: E402
from frlgsim.gift_composer import (  # noqa: E402
    FLAG_MYSTERY_GIFT_DONE,
    VAR_MYSTERY_GIFT_1,
    compile_definition,
)
from test_gift_composer import ScriptVM  # noqa: E402
from test_mystery_gift_end_to_end import _run_full_stack  # noqa: E402


def _distribution():
    return compile_definition(wonder_card_events.CELEBI_GIFT)


def test_definition_compiles_to_the_expected_celebi_card_and_cli_entry():
    distribution = _distribution()
    card = distribution.card
    assert len(card) == wonder_card.WONDER_CARD_SIZE
    assert int.from_bytes(card[0:2], "little") == 1003
    assert int.from_bytes(card[2:4], "little") == wonder_card.SPECIES_CELEBI
    assert int.from_bytes(card[4:8], "little") == 3
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_GIFT
    assert card[9] == 0
    assert charmap.decode(card[10:50]) == "CELEBI GIFT"
    assert len(distribution.ram_script) == 355

    slug = wonder_card.GIFT_CELEBI
    assert slug in gift_registry.GIFT_REGISTRY.live_choices
    assert slug in gift_registry.GIFT_REGISTRY.static_choices
    assert slug in frlgmg_host.build_parser()._option_string_actions["--gift"].choices
    assert slug in gift_to_bin.build_parser()._option_string_actions["--gift"].choices
    assert slug in save_inject.build_parser()._option_string_actions["--gift"].choices
    assert gift_registry.GIFT_REGISTRY.describe(slug) == "composed gift 'CELEBI GIFT'"


def test_delivery_gives_one_celebi_with_custom_moves():
    run = ScriptVM(_distribution().ram_script).run()
    assert run.mons == [(wonder_card.SPECIES_CELEBI, 50, 0)]
    assert run.moves == [
        (7, 0, wonder_card.MOVE_LEECH_SEED),
        (7, 1, wonder_card.MOVE_RECOVER),
        (7, 2, wonder_card.MOVE_HEAL_BELL),
        (7, 3, wonder_card.MOVE_SAFEGUARD),
    ]
    assert run.vars[VAR_MYSTERY_GIFT_1] == 1
    assert FLAG_MYSTERY_GIFT_DONE in run.flags
    assert wonder_card.flag_for_flag_id(1003) in run.flags
    assert charmap.decode(run.messages[0]) == \
        "A special CELEBI delivery has arrived!"
    assert run.messages[1] == (
        b"\xfd\x01"
        + charmap.encode(" received a CELEBI")
        + b"\xfe"
        + charmap.encode("from the deliveryman!"))

    revisit = ScriptVM(
        _distribution().ram_script, variables=run.vars, flags=run.flags).run()
    assert revisit.mons == revisit.moves == []
    assert [[charmap.decode(line) for line in message.split(b"\xfe")]
            for message in revisit.messages] == [[
                "Please look forward to future",
                "MYSTERY GIFTS!",
            ]]


def test_party_full_retry_does_not_mark_the_gift_complete():
    script = _distribution().ram_script
    full = ScriptVM(script, party_size=6).run()
    assert full.mons == full.moves == []
    assert full.vars.get(VAR_MYSTERY_GIFT_1, 0) == 0
    assert FLAG_MYSTERY_GIFT_DONE not in full.flags
    assert wonder_card.flag_for_flag_id(1003) not in full.flags
    assert [[charmap.decode(line) for line in message.split(b"\xfe")]
            for message in full.messages] == [
                ["A special CELEBI delivery has arrived!"],
                ["Oh, your party appears to be full.",
                 "Please make room and come back!"],
            ]

    retry = ScriptVM(script, variables=full.vars, flags=full.flags, party_size=5).run()
    assert retry.mons == [(wonder_card.SPECIES_CELEBI, 50, 0)]
    assert retry.vars[VAR_MYSTERY_GIFT_1] == 1
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


if __name__ == "__main__":
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for name, test in tests:
        test()
        print("ok   ", name)
    print(f"\n{len(tests)}/{len(tests)} passed")
