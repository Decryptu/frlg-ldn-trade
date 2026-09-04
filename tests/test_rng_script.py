"""The field script that seeds the RNG in the overworld.

These are byte-level checks against the decomp's own command table, because there is no way to
execute a field script offline here - the console's script engine is the only interpreter. So what
is checked is that every byte is the opcode the table names and that the decode round-trips.
"""
import pytest

from frlgsim import rng_script, rom_map


def test_the_opcodes_are_the_ones_the_command_table_names():
    # data/script_cmd_table.inc, read out of the decomp rather than remembered.
    assert (rng_script.SCR_END, rng_script.SCR_SETPTR) == (0x02, 0x11)
    assert (rng_script.SCR_PLAYSE, rng_script.SCR_WAITSE) == (0x2F, 0x30)


def test_setptr_is_an_immediate_byte_and_an_absolute_address():
    assert rng_script.setptr(0xDE, 0x03004220) == bytes.fromhex("11de20420003")
    with pytest.raises(rng_script.RngScriptError):
        rng_script.setptr(0x100, 0x03004220)        # setptr writes ONE byte


def test_the_seed_script_writes_grngvalue_little_endian_and_ends_without_clearing():
    script = rng_script.build_seed_script(0xC0DE)
    assert len(script) == 29
    for index, byte in enumerate((0xDE, 0xC0, 0x00, 0x00)):
        assert script[6 * index:6 * index + 6] == \
            rng_script.setptr(byte, rom_map.GRNG_VALUE + index)
    assert script[-1] == rng_script.SCR_END, "endram (0x0d) would clear the binding"
    assert rng_script.SCR_ENDRAM not in script, "0x0d anywhere would clear the binding"


def test_the_script_decodes_back_to_the_word_it_was_asked_for():
    for value in (0, 1, 0xC0DE, 0x41C64E6D, 0xFFFFFFFF):
        lines = rng_script.describe_seed_script(rng_script.build_seed_script(value))
        assert any(f"= 0x{value:08X}" in line for line in lines), lines
        assert any("gRngValue" in line for line in lines)


def test_it_targets_the_address_bs14_read_out_of_random_s_literal_pool():
    """gRngValue may be named as a constant precisely because it does NOT move: it is a link-time
    IWRAM global, unlike a save block, which carries a random offset re-rolled on every battle."""
    assert rom_map.GRNG_VALUE == 0x03004220
    assert rng_script.build_seed_script(0).find((0x03004220).to_bytes(4, "little")) == 2


def test_a_silent_script_is_shorter_and_still_writes_the_word():
    quiet = rng_script.build_seed_script(0xC0DE, sound=None)
    assert len(quiet) == 25
    assert any("= 0x0000C0DE" in line for line in rng_script.describe_seed_script(quiet))


def test_it_refuses_a_misaligned_target():
    with pytest.raises(rng_script.RngScriptError):
        rng_script.build_seed_script(0, address=rom_map.GRNG_VALUE + 1)


def test_it_fits_the_ram_script_the_save_actually_has_room_for():
    assert rng_script.MAX_RAM_SCRIPT_SIZE == 995     # sizeof(RamScriptData.script)
    assert len(rng_script.build_seed_script(0xFFFFFFFF)) < rng_script.MAX_RAM_SCRIPT_SIZE


# --- the RNG owned: seed and generate in the same frame -------------------------------------------

def test_the_wild_battle_script_is_the_seed_then_the_two_battle_commands():
    script = rng_script.build_wild_battle_script(0x81F6816D, 132, 50)
    assert len(script) == 31
    assert script[:24] == rng_script.build_seed_script(0x81F6816D, sound=None)[:24]
    assert script[24] == rng_script.SCR_SETWILDBATTLE == 0xB6
    assert int.from_bytes(script[25:27], "little") == 132       # DITTO
    assert script[27] == 50                                     # level
    assert int.from_bytes(script[28:30], "little") == 0         # no held item
    assert script[30] == rng_script.SCR_DOWILDBATTLE == 0xB7


def test_nothing_that_yields_sits_between_the_seed_and_the_generation():
    """The whole design rests on setptr and setwildbattle running back to back in ONE frame: both
    return FALSE, so the field engine does not yield between them and no draw can creep in. A
    playse/waitse in there would break exactly that, silently."""
    script = rng_script.build_wild_battle_script(0x81F6816D, 132, 50)
    upto_generation = script[:script.index(bytes([rng_script.SCR_SETWILDBATTLE]))]
    assert rng_script.SCR_PLAYSE not in upto_generation
    assert rng_script.SCR_WAITSE not in upto_generation
    assert rng_script.SCR_END not in upto_generation


def test_the_chosen_seed_makes_a_shiny_ditto_for_this_console():
    from frlgsim import wonder_card_events
    got = rng_script.predict_wild_mon(wonder_card_events.RNG_DITTO_SEED, 57189, 58811)
    assert got["shiny"] is True
    assert got["low_first"]["shiny_value"] == got["high_first"]["shiny_value"] == 3
    assert got["ivs"] == (31, 23, 27, 18, 30, 30)
    assert got["iv_total"] == 159


def test_shininess_and_ivs_do_not_depend_on_the_half_order_but_nature_does():
    """Random32 is `Random() | (Random() << 16)` and C does not order the operands, so the half
    order is the compiler's. It does not put the result at risk: the shiny test XORs both halves
    together, and the IVs come from the two draws after."""
    got = rng_script.predict_wild_mon(0x81F6816D, 57189, 58811)
    assert got["low_first"]["shiny"] == got["high_first"]["shiny"]
    assert got["low_first"]["personality"] != got["high_first"]["personality"]
    assert got["low_first"]["nature"] != got["high_first"]["nature"]


def test_it_refuses_a_species_or_level_the_operands_cannot_carry():
    for bad in ((0, 50), (9999, 50), (132, 0), (132, 101)):
        with pytest.raises(rng_script.RngScriptError):
            rng_script.build_wild_battle_script(0, *bad)


def test_the_gift_carries_that_script_and_binds_it_to_the_pallet_town_man():
    from frlgsim import gift_registry, wonder_card_events
    assert wonder_card_events.GIFT_RNG_SHINY_DITTO in gift_registry.GIFT_REGISTRY.live_choices
    mevent = wonder_card_events.build_rng_shiny_ditto_script()
    inner = rng_script.build_wild_battle_script(
        wonder_card_events.RNG_DITTO_SEED, wonder_card_events.SPECIES_DITTO,
        wonder_card_events.RNG_DITTO_LEVEL)
    assert inner in mevent, "the field script must reach the console verbatim"


def test_a_field_script_and_lines_are_not_both_accepted():
    from frlgsim import wonder_card_events
    with pytest.raises(ValueError):
        wonder_card_events.build_mevent_npc_script(lines=("hi",), field_script=b"\x02")
