"""The field script that seeds the RNG in the overworld.

These are byte-level checks against the decomp's own command table, because there is no way to
execute a field script offline here - the console's script engine is the only interpreter. So what
is checked is that every byte is the opcode the table names and that the decode round-trips.
"""
import pytest

from frlgsim import gift_composer, lcg, rng_script, rom_map


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


def test_mev07_the_console_built_exactly_what_was_predicted():
    """mev07/bs53, on hardware, first try. The prediction was committed before the console had
    ever seen the seed; this is what came back out of gPlayerParty afterwards. Every bit of the
    personality, all six IVs, the nature and the shininess.

    It also settles the one thing that could not be settled offline: nature 17 is QUIET - DISCRET
    on the console's French screen - so `Random32()` evaluates its LOW half first at CreateBoxMon's
    call site, the same way CreateMonWithNature's does.
    """
    from frlgsim import wonder_card_events
    got = rng_script.predict_wild_mon(wonder_card_events.RNG_DITTO_SEED, 57189, 58811)
    assert got["low_first"]["personality"] == 0x026F38B2
    assert got["low_first"]["nature"] == 17
    assert got["ivs"] == (31, 23, 27, 18, 30, 30)
    assert got["shiny"] is True


# --- reading the seed: the script that prints gRngValue and writes nothing ----------------------
# The write direction was always the easy one. Reading gRngValue in the OVERWORLD is what a
# countdown needs, and it was blocked on one unknown until bs57: the absolute address of
# gSpecialVar_0x8000, because `copybyte` needs a destination ADDRESS where `buffernumberstring`
# only needs a var id.

_OP_SETVADDRESS = 0xB8
_OP_COPYBYTE = 0x15
_OP_BUFFERNUMBERSTRING = 0x83
_OP_VMESSAGE = 0xBD
_OP_LOCK, _OP_FACEPLAYER, _OP_RELEASE, _OP_END = 0x6A, 0x5A, 0x6C, 0x02
_OP_WAITMESSAGE, _OP_WAITBUTTONPRESS, _OP_CLOSEMESSAGE = 0x66, 0x6D, 0x68


def _walk(script):
    """-> [(offset, opcode, operand bytes)] for the fixed-width commands this script uses."""
    widths = {_OP_SETVADDRESS: 4, _OP_COPYBYTE: 8, _OP_BUFFERNUMBERSTRING: 3, _OP_VMESSAGE: 4,
              0x28: 2,                                  # delay, a u16 of frames
              _OP_LOCK: 0, _OP_FACEPLAYER: 0, _OP_RELEASE: 0, _OP_END: 0,
              _OP_WAITMESSAGE: 0, _OP_WAITBUTTONPRESS: 0, _OP_CLOSEMESSAGE: 0}
    out, i = [], 0
    while i < len(script):
        op = script[i]
        if op not in widths:
            break                                   # the text pool starts here
        width = widths[op]
        out.append((i, op, bytes(script[i + 1:i + 1 + width])))
        i += 1 + width
        if op == _OP_END:
            break
    return out


def test_the_seed_read_script_copies_the_four_bytes_of_grngvalue_into_the_two_vars():
    script = gift_composer.build_seed_read_script()
    copies = [(int.from_bytes(operand[:4], "little"), int.from_bytes(operand[4:], "little"))
              for _offset, op, operand in _walk(script) if op == _OP_COPYBYTE]

    assert len(copies) == 4
    for i, (dest, src) in enumerate(copies):
        assert src == rom_map.GRNG_VALUE + i, f"byte {i} does not come from gRngValue"
        assert dest == rom_map.G_SPECIAL_VAR_0X8000 + i, f"byte {i} does not land in the vars"
    # gSpecialVar_0x8000 and 0x8001 are adjacent u16s, so the four destinations are one run of
    # four bytes and the halves reassemble as a little-endian u32 without any further arithmetic.
    assert [dest for dest, _ in copies] == list(
        range(rom_map.G_SPECIAL_VAR_0X8000, rom_map.G_SPECIAL_VAR_0X8000 + 4))


def test_nothing_that_yields_sits_inside_the_read():
    """THE ONE THAT MATTERS. The RNG never idles, so four byte copies spread over four frames
    would tear: the halves would come from different states and the word would be one the console
    never held. copybyte and buffernumberstring both return FALSE and the field engine runs
    commands until one returns TRUE, so the six of them are a single frame - as long as nothing
    else is emitted between them."""
    walked = _walk(gift_composer.build_seed_read_script())
    opcodes = [op for _offset, op, _operand in walked]
    first = opcodes.index(_OP_COPYBYTE)
    last = len(opcodes) - 1 - opcodes[::-1].index(_OP_BUFFERNUMBERSTRING)

    assert set(opcodes[first:last + 1]) == {_OP_COPYBYTE, _OP_BUFFERNUMBERSTRING}
    assert opcodes[first:last + 1] == [_OP_COPYBYTE] * 4 + [_OP_BUFFERNUMBERSTRING] * 2


def test_the_script_writes_nothing_but_the_two_scratch_vars():
    """It is a READ. No setptr, no setvar, no givemon, no battle - and the destinations are the
    two special vars the game itself uses as scratch."""
    walked = _walk(gift_composer.build_seed_read_script())
    for _offset, op, operand in walked:
        assert op != 0x11, "setptr writes memory; this script must not"
        assert op not in (0xB6, 0xB7), "no wild battle in a read-only script"
        if op == _OP_COPYBYTE:
            dest = int.from_bytes(operand[:4], "little")
            assert (rom_map.G_SPECIAL_VAR_0X8000
                    <= dest < rom_map.G_SPECIAL_VAR_0X8000 + 4), f"writes 0x{dest:08X}"


def test_the_message_pointer_is_relative_to_the_script_not_absolute():
    """gSaveBlock1Ptr carries a random 4-aligned offset re-rolled on every battle and load, so a
    RAM script cannot hold an absolute pointer to its own text. setvaddress makes vmessage's
    operand an offset from wherever the script actually landed."""
    script = gift_composer.build_seed_read_script()
    walked = _walk(script)
    (_offset, first_op, base_operand) = walked[0]
    pointers = [int.from_bytes(operand, "little")
                for _o, op, operand in walked if op == _OP_VMESSAGE]

    assert first_op == _OP_SETVADDRESS, "setvaddress must come first: it uses its own address"
    virtual_base = int.from_bytes(base_operand, "little")
    assert len(pointers) == 1
    text_at = pointers[0] - virtual_base
    assert 0 < text_at < len(script)
    assert script[text_at:].endswith(b"\xFF")        # a field string, terminated
    assert b"\xFD\x02" in script[text_at:] and b"\xFD\x03" in script[text_at:]


def test_the_script_ends_with_end_so_the_npc_can_be_asked_again():
    """`endram` (0x0d) calls ClearRamScript; `end` (0x02) does not. A miss costing nothing depends
    entirely on being able to ask a second time."""
    script = gift_composer.build_seed_read_script()
    opcodes = [op for _o, op, _operand in _walk(script)]

    assert opcodes[-1] == _OP_END
    assert 0x0D not in opcodes


def test_the_printed_halves_reassemble_into_grngvalue():
    assert rng_script.seed_from_printed(0x5678, 0x1234) == 0x12345678
    with pytest.raises(rng_script.RngScriptError):
        rng_script.seed_from_printed(0x10000, 0)


def test_two_readings_prove_the_address_without_any_clock():
    """A distance ALWAYS exists - the LCG is a permutation of 2**32 states - so the distance is
    only evidence when it is small. Two readings seconds apart are thousands of turns apart; two
    unrelated numbers are ~2**31."""
    first = 0x12345678
    second = lcg.advance(first, 2400)

    good = rng_script.check_two_readings(first, second, seconds=20)
    bad = rng_script.check_two_readings(0xDEADBEEF, 0x0BADF00D)

    assert any("CONSISTENT" in line for line in good)
    assert any("2,400 turns" in line for line in good)
    assert any("NOT consistent" in line for line in bad)


# --- the rate probe: the clock removed rather than improved -------------------------------------
# Every earlier attempt at the overworld rate divided an exact turn count by a hand-timed elapsed,
# and one of them divided by a number that had itself been computed from the answer. `delay` waits
# an exact number of frames [decomp:src/scrcmd.c:651], so both sides of the division are exact.

_OP_DELAY = 0x28


def test_the_rate_probe_reads_twice_into_different_vars_with_the_delay_between():
    script = gift_composer.build_seed_rate_script(frames=600)
    walked = _walk(script)
    opcodes = [op for _o, op, _operand in walked]
    copies = [(int.from_bytes(operand[:4], "little"), int.from_bytes(operand[4:], "little"))
              for _o, op, operand in walked if op == _OP_COPYBYTE]

    assert len(copies) == 8, "two readings of four bytes each"
    assert all(src == rom_map.GRNG_VALUE + (i % 4) for i, (_dest, src) in enumerate(copies))
    base = rom_map.G_SPECIAL_VAR_0X8000
    assert [dest for dest, _src in copies] == list(range(base, base + 8)), \
        "the two readings must not land on top of each other"
    # The delay is between them, and it is the only yielding command in the measured interval.
    assert opcodes.count(_OP_DELAY) == 1
    delay_at = opcodes.index(_OP_DELAY)
    assert opcodes[delay_at - 4:delay_at] == [_OP_COPYBYTE] * 4
    assert opcodes[delay_at + 1:delay_at + 5] == [_OP_COPYBYTE] * 4


def test_the_delay_operand_is_the_frame_count_asked_for():
    for frames in (1, 600, 0xFFFF):
        walked = _walk(gift_composer.build_seed_rate_script(frames=frames))
        operand = next(o for _off, op, o in walked if op == _OP_DELAY)
        assert int.from_bytes(operand, "little") == frames
    with pytest.raises(gift_composer.GiftValidationError):
        gift_composer.build_seed_rate_script(frames=0x10000)


def test_the_rate_is_two_exact_numbers_divided():
    """No clock anywhere: distance is exact arithmetic and frames is what delay was told."""
    before = 0x124D683F
    after = lcg.advance(before, 1200)

    lines = rng_script.measure_rate(before, after, 600)

    assert any("1,200" in line for line in lines)
    assert any("EXACTLY 2 per frame" in line for line in lines)
    assert any("2.000000 turns/frame" in line for line in lines)


def test_a_rate_that_is_not_two_is_reported_as_such_rather_than_rounded():
    before = 0x124D683F
    after = lcg.advance(before, 1307)

    lines = rng_script.measure_rate(before, after, 600)

    assert any("2.178333" in line for line in lines)
    assert any("+107" in line for line in lines)
    assert not any("EXACTLY" in line for line in lines)
    with pytest.raises(rng_script.RngScriptError):
        rng_script.measure_rate(before, after, 0)
