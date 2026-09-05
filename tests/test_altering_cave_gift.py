#!/usr/bin/env python3
"""Offline coverage for the Altering Cave event, ported from the official script.

`MysteryEventScript_AlteringCave` [decomp:data/mystery_event_msg.s:325] is four commands and a
message: add one to VAR_ALTERING_CAVE_WILD_SET, wrap it, and say something. The var is read at the
encounter, where `i += alteringCaveId` picks one of NUM_ALTERING_CAVE_TABLES consecutive wild
headers for MAP_SIX_ISLAND_ALTERING_CAVE [decomp:src/wild_encounter.c:192].
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import frlgmg_host  # noqa: E402
from frlgsim import (  # noqa: E402
    buffer_script,
    charmap,
    gift_registry,
    gift_to_bin,
    mystery_gift,
    save_inject,
    wonder_card,
    wonder_card_events as event,
)
from frlgsim.gift_composer import VAR_MYSTERY_GIFT_1, compile_definition  # noqa: E402
from test_gift_composer import ScriptVM  # noqa: E402


def _distribution():
    return compile_definition(event.ALTERING_CAVE_GIFT)


def _talk(script, variables):
    """One conversation with the delivery man, from a given save state."""
    vm = ScriptVM(script, variables=dict(variables))
    vm.run()
    return vm


def test_the_card_is_registered_and_reaches_every_launcher():
    distribution = _distribution()
    card = distribution.card

    assert len(card) == wonder_card.WONDER_CARD_SIZE
    assert int.from_bytes(card[0:2], "little") == event.ALTERING_CAVE_FLAG_ID == 1004
    assert int.from_bytes(card[2:4], "little") == event.SPECIES_ZUBAT
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_GIFT
    assert charmap.decode(card[50:90]) == "Rumors from ALTERING CAVE"

    slug = event.GIFT_ALTERING_CAVE
    assert slug in gift_registry.GIFT_REGISTRY.live_choices
    assert slug in gift_registry.GIFT_REGISTRY.static_choices
    assert slug in frlgmg_host.build_parser()._option_string_actions["--gift"].choices
    assert slug in gift_to_bin.build_parser()._option_string_actions["--gift"].choices
    assert slug in save_inject.build_parser()._option_string_actions["--gift"].choices


def test_one_talk_advances_the_wild_set_by_exactly_one():
    script = _distribution().ram_script
    vm = _talk(script, {event.VAR_ALTERING_CAVE_WILD_SET: 0, VAR_MYSTERY_GIFT_1: 0})

    assert vm.vars[event.VAR_ALTERING_CAVE_WILD_SET] == 1
    assert vm.messages, "the player is told something happened"


def test_the_var_walks_the_whole_cycle_and_wraps_where_the_official_script_wraps():
    """The official script resets at 10, not at NUM_ALTERING_CAVE_TABLES (9)
    [decomp:data/mystery_event_msg.s:328], so a full cycle passes through an id the encounter
    reader clamps back to table 0 [decomp:src/wild_encounter.c:193]."""
    script = _distribution().ram_script
    state = {event.VAR_ALTERING_CAVE_WILD_SET: 0, VAR_MYSTERY_GIFT_1: 0}
    seen = []
    for _ in range(12):
        vm = _talk(script, state)
        state = dict(vm.vars)
        seen.append(state[event.VAR_ALTERING_CAVE_WILD_SET])

    assert seen == [1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 1, 2]
    assert event.ALTERING_CAVE_WRAP == 10
    assert event.NUM_ALTERING_CAVE_TABLES == 9


def test_the_binding_survives_so_the_cave_can_be_rotated_more_than_once():
    """`end` (0x02), never `endram` (0x0D): ScrCmd_endram calls ClearRamScript
    [decomp:src/scrcmd.c:262] and the second talk would find nothing bound."""
    script = _distribution().ram_script
    # The code runs up to the first message the script points at; the text pool follows it.
    code = script[:min(int.from_bytes(script[pos + 1:pos + 5], "little") - 0x08000000
                       for pos in range(len(script) - 4) if script[pos] == 0xBD)]

    assert code.endswith(bytes([0x6C, 0x02]))          # release, end
    assert 0x0D not in code                            # never endram

    vm = _talk(script, {event.VAR_ALTERING_CAVE_WILD_SET: 4, VAR_MYSTERY_GIFT_1: 0})
    assert vm.vars[VAR_MYSTERY_GIFT_1] == 0, "the cursor is reset, so the next talk replays it"
    assert vm.vars[event.VAR_ALTERING_CAVE_WILD_SET] == 5


def test_nothing_but_the_cave_var_and_the_card_bookkeeping_is_touched():
    """A card the player keeps must not move anything else in their save."""
    script = _distribution().ram_script
    before = {event.VAR_ALTERING_CAVE_WILD_SET: 3, VAR_MYSTERY_GIFT_1: 0}
    vm = _talk(script, before)

    touched = {name for name, value in vm.vars.items() if before.get(name) != value}
    assert touched == {event.VAR_ALTERING_CAVE_WILD_SET}
    assert vm.items == [] and vm.mons == [] and vm.battles == [] and vm.sprites == []
    assert vm.flags == {wonder_card.flag_for_flag_id(event.ALTERING_CAVE_FLAG_ID)}


def test_the_run_is_checked_by_reading_the_var_out_of_the_save():
    """Six Island may be unreachable in the save; the var itself is not. It sits in
    SaveBlock1.vars [decomp:include/global.h:791], which save-dump can read."""
    assert buffer_script.sav1_var_offset(event.VAR_ALTERING_CAVE_WILD_SET) == 0x1048
    assert buffer_script.sav1_var_offset(0x4000) == buffer_script.SAV1_VARS
    for bad in (0x3FFF, 0x4100, 0x8000):
        try:
            buffer_script.sav1_var_offset(bad)
        except ValueError:
            continue
        raise AssertionError(f"0x{bad:04X} was accepted as a saved var")
