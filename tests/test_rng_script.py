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
