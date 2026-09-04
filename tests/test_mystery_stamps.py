#!/usr/bin/env python3
"""Focused regressions for the legendary-beast Mystery Gift branch."""

import hashlib
import os
import sys
from dataclasses import fields

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frlgmg_host  # noqa: E402
from frlgsim import (  # noqa: E402
    gift_composer as gc,
    gift_registry,
    gift_to_bin,
    mystery_gift,
    save_inject,
    wonder_card,
    wonder_card_events,
)
from test_gift_composer import ScriptVM  # noqa: E402


CARD_SHA256 = "288a9780be48923c4b1b4898ca0f20fc75aa5c42f3cd6550886b4bf3762be959"
SCRIPT_SHA256 = "23108fe1f4a28045d19fa9a2a68679fe81286371af4a681b28c4ccddd99f031c"


def _giveitem(item):
    return bytes.fromhex("1a0080") + item.to_bytes(2, "little") \
        + bytes.fromhex("1a018001000900")


def _make_synthetic_save(slot0_counter=10, slot1_counter=9):
    """Build two valid, rotated FRLG save slots with zeroed sector data."""
    sav = bytearray(save_inject.SECTORS_COUNT * save_inject.SECTOR_SIZE)
    for slot, counter in ((0, slot0_counter), (1, slot1_counter)):
        for within in range(save_inject.NUM_SECTORS_PER_SLOT):
            physical = slot * save_inject.NUM_SECTORS_PER_SLOT + within
            base = physical * save_inject.SECTOR_SIZE
            sector_id = (within + 5) % save_inject.NUM_SECTORS_PER_SLOT
            sav[base + save_inject.SECTOR_ID_OFF:
                base + save_inject.SECTOR_ID_OFF + 2] = sector_id.to_bytes(2, "little")
            sav[base + save_inject.SECTOR_SIGNATURE_OFF:
                base + save_inject.SECTOR_SIGNATURE_OFF + 4] = \
                save_inject.SECTOR_SIGNATURE.to_bytes(4, "little")
            sav[base + save_inject.SECTOR_COUNTER_OFF:
                base + save_inject.SECTOR_COUNTER_OFF + 4] = counter.to_bytes(4, "little")
    return bytes(sav)


def test_cutscene_matches_the_authoritative_hardware_tested_payload():
    card, script = wonder_card.build_legendary_beast_cutscene_gift()
    assert len(card) == wonder_card.WONDER_CARD_SIZE == 332
    assert len(script) == 360 <= save_inject.RAM_SCRIPT_BODY_MAX
    assert hashlib.sha256(card).hexdigest() == CARD_SHA256
    assert hashlib.sha256(script).hexdigest() == SCRIPT_SHA256
    assert mystery_gift.crc16(card) == 0xC542
    _ram_data, ram_crc = save_inject.build_ram_script_struct(script)
    assert ram_crc == 0x4C2E


def test_starter_branches_select_the_preserved_beasts_and_graphics():
    _card, script = wonder_card.build_legendary_beast_cutscene_gift()
    # Bulbasaur and Squirtle branch; Charmander is the first/fallthrough block.
    assert script[57:64] == bytes.fromhex("2131400000bb01")
    assert int.from_bytes(script[64:68], "little") == 120
    assert script[68:75] == bytes.fromhex("2131400100bb01")
    assert int.from_bytes(script[75:79], "little") == 161
    blocks = (
        (79, wonder_card.SPECIES_RAIKOU, wonder_card.OBJ_EVENT_GFX_RAIKOU),
        (120, wonder_card.SPECIES_SUICUNE, wonder_card.OBJ_EVENT_GFX_SUICUNE),
        (161, wonder_card.SPECIES_ENTEI, wonder_card.OBJ_EVENT_GFX_ENTEI),
    )
    for offset, species, graphics in blocks:
        assert script[offset:offset + 3] == bytes([0xAA, graphics, 0])
        assert script[offset + 33:offset + 39] == \
            bytes([0xB6]) + species.to_bytes(2, "little") + bytes([65, 0, 0])
        assert script[offset + 39:offset + 41] == bytes([0xB7, 0x02])


def test_rewards_precede_release_and_terminal_battle_in_every_branch():
    _card, script = wonder_card.build_legendary_beast_cutscene_gift()
    lansat = script.index(_giveitem(wonder_card.ITEM_LANSAT_BERRY))
    liechi = script.index(_giveitem(wonder_card.ITEM_LIECHI_BERRY))
    assert (lansat, liechi) == (23, 35)
    assert liechi < 57  # both shared rewards precede starter selection
    for offset in (79, 120, 161):
        master = script.index(_giveitem(wonder_card.ITEM_MASTER_BALL), offset)
        release = script.index(bytes([0x6C]), master)
        battle = script.index(bytes([0xB6]), release)
        assert offset <= master < release < battle < offset + 41
        assert script[offset + 40] == 0x02  # end, never endram


def test_virtual_offsets_are_relocation_safe_and_point_inside_the_script():
    _card, script = wonder_card.build_legendary_beast_cutscene_gift()
    assert script[:5] == bytes([0xB8, 0, 0, 0, 0])
    for opcode_offset, target in (
            (7, 202), (15, 247), (91, 296), (132, 296), (173, 296)):
        assert script[opcode_offset] == 0xBD
        assert int.from_bytes(script[opcode_offset + 1:opcode_offset + 5], "little") == target
        assert 202 <= target < len(script)
        assert 0xFF in script[target:]
    assert 0x0D not in script[:202]  # no endram opcode in executable bytes


def test_builder_alias_flag_validation_and_custom_level():
    assert wonder_card.build_raikou_cutscene_gift() == \
        wonder_card.build_legendary_beast_cutscene_gift()
    card, script = wonder_card.build_legendary_beast_cutscene_gift(
        level=100, flag_id=1019)
    assert int.from_bytes(card[:2], "little") == 1019
    for offset in (79, 120, 161):
        assert script[offset + 36] == 100
    for bad in (999, 1020):
        try:
            wonder_card.build_legendary_beast_cutscene_gift(flag_id=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid flag id accepted: {bad}")
    for bad in (0, 101):
        try:
            wonder_card.build_legendary_beast_cutscene_gift(level=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid level accepted: {bad}")


def test_exported_binary_geometry_and_checksums():
    card, script = wonder_card.build_legendary_beast_cutscene_gift()
    card_bin, script_bin = gift_to_bin.build_gift_bins(card, script)
    assert len(card_bin) == gift_to_bin.WONDER_CARD_BIN_SIZE == 336
    assert card_bin[:2] == bytes.fromhex("42c5") and card_bin[2:4] == b"\x00\x00"
    assert card_bin[4:] == card
    assert len(script_bin) == gift_to_bin.SCRIPT_BIN_SIZE == 1004
    assert script_bin[:2] == bytes.fromhex("2e4c") and script_bin[2:4] == b"\x00\x00"
    ram_data, _crc = save_inject.build_ram_script_struct(script)
    assert script_bin[4:1003] == ram_data and script_bin[1003:] == b"\x00"


def test_save_injection_is_valid_checksums_are_rebuilt_and_other_sectors_untouched():
    before = _make_synthetic_save()
    after, info = save_inject.inject_selected_gift(before, flag_id=1005)
    assert info["slot"] == 0 and info["phys_sector"] == 13
    card, crc_ok = save_inject.read_saved_wonder_card(after)
    expected = gift_registry.GIFT_REGISTRY.build_distribution(
        wonder_card.GIFT_BEAST_CUTSCENE, flag_id=1005)
    expected_card, expected_script = expected.card, expected.ram_script
    assert crc_ok and card == expected_card and save_inject.validate_wonder_card(card)
    saved_script = save_inject.get_saved_ram_script_if_valid(after)
    assert saved_script[:len(expected_script)] == expected_script
    base = info["phys_sector"] * save_inject.SECTOR_SIZE
    stored = int.from_bytes(
        after[base + save_inject.SECTOR_CHECKSUM_OFF:
              base + save_inject.SECTOR_CHECKSUM_OFF + 2], "little")
    assert stored == info["sector_checksum"] == save_inject.sector_checksum(
        after[base:base + save_inject.SECTOR_DATA_SIZE], info["checksum_size"])
    for physical in range(save_inject.SECTORS_COUNT):
        if physical == info["phys_sector"]:
            continue
        lo = physical * save_inject.SECTOR_SIZE
        hi = lo + save_inject.SECTOR_SIZE
        assert after[lo:hi] == before[lo:hi]


def test_composed_cutscene_registry_uses_conditions_for_starter_branch():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution(
        wonder_card.GIFT_BEAST_CUTSCENE)
    legacy_card, legacy_script = wonder_card.build_legendary_beast_cutscene_gift()
    assert distribution.card == legacy_card
    assert distribution.ram_script != legacy_script
    assert 0 < len(distribution.ram_script) <= gc.MAX_RAM_SCRIPT_SIZE
    assert gift_registry.GIFT_REGISTRY.describe(wonder_card.GIFT_BEAST_CUTSCENE) == \
        "composed gift 'LEGENDARY BEAST'"

    cases = (
        (0, wonder_card.SPECIES_SUICUNE, wonder_card.OBJ_EVENT_GFX_SUICUNE),
        (1, wonder_card.SPECIES_ENTEI, wonder_card.OBJ_EVENT_GFX_ENTEI),
        (2, wonder_card.SPECIES_RAIKOU, wonder_card.OBJ_EVENT_GFX_RAIKOU),
        (9, wonder_card.SPECIES_RAIKOU, wonder_card.OBJ_EVENT_GFX_RAIKOU),
    )
    for starter, species, graphics in cases:
        run = ScriptVM(
            distribution.ram_script,
            variables={wonder_card_events.VAR_STARTER_MON: starter}).run()
        assert run.items == [
            (wonder_card.ITEM_LANSAT_BERRY, 1),
            (wonder_card.ITEM_LIECHI_BERRY, 1),
            (wonder_card.ITEM_MASTER_BALL, 1),
        ]
        assert len(run.sprites) == 1
        assert run.sprites[0][0] == graphics
        assert run.sprites[0][2:] == (11, 20, 3, wonder_card.DIR_WEST)
        assert run.battles == [(species, wonder_card.LEGENDARY_BEAST_LEVEL, 0)]
        assert run.vars[gc.VAR_MYSTERY_GIFT_1] == 0
        assert gc.FLAG_MYSTERY_GIFT_DONE not in run.flags
        assert wonder_card.flag_for_flag_id(1003) in run.flags


def test_all_three_clis_default_to_the_composed_fixed_level_65_cutscene():
    host_args = frlgmg_host.build_parser().parse_args(["--live"])
    export_args = gift_to_bin.build_parser().parse_args([])
    inject_args = save_inject.build_parser().parse_args(["game.sav"])
    parsers_and_args = (
        (frlgmg_host.build_parser(), host_args),
        (gift_to_bin.build_parser(), export_args),
        (save_inject.build_parser(), inject_args),
    )
    for parser, args in parsers_and_args:
        assert args.gift == wonder_card.GIFT_BEAST_CUTSCENE
        assert args.flag_id == 1003
        options = {
            option
            for action in parser._actions
            for option in action.option_strings
        }
        assert not {"--level", "--item", "--title", "--subtitle"} & options
    host_config = frlgmg_host.build_run_config(
        frlgmg_host.build_parser(), host_args)
    # The payload names WHICH gift, never how it is built; anything shaping the card itself belongs
    # in the composed definition. `questionnaire` and `denied_message` are session gating, not gift
    # content, which is why they are allowed here [SVR_CHECK_QUESTIONNAIRE, mg_server.py].
    assert [field.name for field in fields(host_config.payload)] == [
        "gift", "flag_id", "questionnaire", "denied_message"]
    assert host_config.payload.questionnaire is None
    card, script = host_config.payload.build()
    legacy_card, legacy_script = wonder_card.build_legendary_beast_cutscene_gift()
    assert card == legacy_card
    assert script != legacy_script
    assert script == gift_registry.GIFT_REGISTRY.build_distribution(
        wonder_card.GIFT_BEAST_CUTSCENE).ram_script


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print(f"ok    {name}")
    print("Legendary-beast Mystery Gift tests: OK")
