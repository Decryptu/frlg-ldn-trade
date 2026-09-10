"""The 328-byte PB8 a NetTradePokeData carries.

sp82's real Zubat is a capture and stays out of the repository (CLAUDE.md rule 6), so everything
here is built from synthetic bodies. What the real one proved, and what these reproduce, is that
the checksum verifies a decryption and that encrypt is exactly the inverse of decrypt.
"""
import struct

import pytest

from pokeldn.bdsp import netdata, pokemon, room


def a_body(ec=0xCDBEB642, species=41, nickname="Nosferapti", ot="Gurvan", tid=44466, sid=4080):
    """A plain, unshuffled 328-byte body with the named fields set and the rest patterned.

    The filler is deliberately NOT zero: a block permutation and an off-by-one offset both survive
    a body of zeros, and neither survives this.
    """
    plain = bytearray(bytes(range(256)) * 2)[:pokemon.SIZE_STORED]
    struct.pack_into("<I", plain, 0x00, ec)
    struct.pack_into("<H", plain, 0x04, 0)
    struct.pack_into("<H", plain, pokemon.OFF_SPECIES, species)
    struct.pack_into("<H", plain, pokemon.OFF_TID, tid)
    struct.pack_into("<H", plain, pokemon.OFF_SID, sid)
    for offset, value in ((pokemon.OFF_NICKNAME, nickname), (pokemon.OFF_OT_NAME, ot)):
        plain[offset:offset + pokemon.NAME_LENGTH] = \
            value.encode("utf-16-le").ljust(pokemon.NAME_LENGTH, b"\x00")
    return bytes(plain)


def test_encrypt_is_the_inverse_of_decrypt_and_the_checksum_is_written_from_the_body():
    raw = pokemon.encrypt(a_body())
    assert len(raw) == pokemon.SIZE_STORED == 328
    plain = pokemon.decrypt(raw)
    # the header travels in the clear; the body comes back exactly
    assert plain[8:] == a_body()[8:]
    assert struct.unpack_from("<H", raw, 6)[0] == pokemon.checksum(plain)
    assert pokemon.encrypt(plain) == raw


def test_a_corrupted_body_is_refused_by_its_own_checksum():
    """The checksum sums the DECRYPTED body, so nothing wrong about a decryption can pass it."""
    raw = bytearray(pokemon.encrypt(a_body()))
    raw[100] ^= 0xFF
    with pytest.raises(ValueError, match="checksum"):
        pokemon.decrypt(bytes(raw))


def test_a_block_order_that_is_not_its_own_inverse_still_round_trips():
    """sp97 is the run this test exists for.

    Every PB8 the project had decoded came from one Pokemon, whose EC gave sv=21 and the ordering
    (3, 1, 2, 0) - SELF-INVERSE, so decrypt inverting the order was a no-op and nothing complained
    for nine runs. A Keunotor at sv=28, (0, 2, 3, 1), decoded to a Bidoof with no moves and its
    species name in the trainer field. The checksum agreed both times and always will: it is a sum
    over the body, and permuting whole blocks does not change a sum.
    """
    def sv_of(ec):
        return (ec >> 13) & 31

    self_inverse = [ec for ec in range(0, 1 << 20, 0x2000)
                    if pokemon.BLOCK_ORDER[sv_of(ec)] == pokemon.invert(pokemon.BLOCK_ORDER[sv_of(ec)])]
    assert self_inverse, "the old bug needs at least one of these to have hidden behind"

    for ec in range(0, 1 << 20, 0x2000):                      # every one of the 32 sv values
        raw = pokemon.encrypt(a_body(ec=ec))
        r = pokemon.read(raw)
        assert (r["nickname"], r["ot_name"]) == ("Nosferapti", "Gurvan"), \
            f"sv={sv_of(ec)} put the names in the wrong blocks"
        assert r["species"] == 41

    # and the table covers the whole 5-bit index, with 24-31 repeating 0-7 as PKHeX writes it
    assert len(pokemon.BLOCK_ORDER) == 32
    assert pokemon.BLOCK_ORDER[24:] == pokemon.BLOCK_ORDER[:8]


def test_the_block_order_follows_the_encryption_constant():
    """(EC >> 13) & 31 picks one of 24 orderings, so two ECs shuffle the same body differently."""
    body = bytearray(a_body())
    struct.pack_into("<I", body, 0, 0x00000000)
    first = pokemon.encrypt(bytes(body))
    struct.pack_into("<I", body, 0, 0x0000E000)          # (>> 13) & 31 lands on a different order
    second = pokemon.encrypt(bytes(body))
    assert pokemon.BLOCK_ORDER[(0 >> 13) & 31] != pokemon.BLOCK_ORDER[(0xE000 >> 13) & 31]
    assert first[8:] != second[8:]
    # and each still decodes to the body it was built from
    assert pokemon.decrypt(first)[8:] == pokemon.decrypt(second)[8:]


def test_reading_back_what_was_written():
    r = pokemon.read(pokemon.encrypt(a_body()))
    assert r["species"] == 41
    assert r["nickname"] == "Nosferapti"
    assert r["ot_name"] == "Gurvan"
    assert r["trainer_id"] == 44466
    assert r["secret_id"] == 4080


def test_building_from_a_template_changes_only_what_was_asked_for():
    """A Pokemon we send is a real one with named fields moved - every other byte stays a console's."""
    template = pokemon.encrypt(a_body())
    made = pokemon.build_from(template, species=25, nickname="PIKA", ot_name="PkCamp",
                              ivs=(31, 31, 31, 31, 31, 31))
    r = pokemon.read(made)
    assert (r["species"], r["nickname"], r["ot_name"]) == (25, "PIKA", "PkCamp")
    assert r["ivs"] == (31, 31, 31, 31, 31, 31)
    # untouched fields still hold the template's values
    assert r["trainer_id"] == 44466 and r["secret_id"] == 4080
    before, after = pokemon.decrypt(template), pokemon.decrypt(made)
    untouched = [i for i in range(0xA0, 0xF8) if before[i] != after[i]]
    assert untouched == [], f"bytes changed that nothing asked for: {untouched}"
    with pytest.raises(ValueError, match="unknown field"):
        pokemon.build_from(template, sparkly=1)


def test_a_nickname_sets_the_flag_that_makes_the_console_draw_it():
    """sp92's whole visible edit was lost to this: the name field is only shown when IV32 bit 31 is
    set, and a PB8 always carries a name string, so a nickname with the flag clear is invisible."""
    template = pokemon.encrypt(a_body())
    plain = bytearray(a_body())
    struct.pack_into("<I", plain, pokemon.OFF_IVS, 0x14A65C08)      # flag clear, as sp82's was
    template = pokemon.encrypt(bytes(plain))
    assert pokemon.read(template)["is_nicknamed"] is False

    made = pokemon.build_from(template, nickname="PKCAMP")
    r = pokemon.read(made)
    assert r["nickname"] == "PKCAMP" and r["is_nicknamed"] is True
    assert r["ivs"] == pokemon.read(template)["ivs"], "the IVs share the word with the flag"

    # an explicit value after the nickname still wins, for the run that wants the string unshown
    quiet = pokemon.read(pokemon.build_from(template, nickname="PKCAMP", is_nicknamed=False))
    assert quiet["nickname"] == "PKCAMP" and quiet["is_nicknamed"] is False


def test_the_fields_pkhex_names_survive_a_round_trip():
    """The offsets beyond sp82's twelve come from PKHeX's G8PKM, where all twelve agree."""
    template = pokemon.encrypt(a_body())
    edits = dict(moves=(71, 48, 0, 0), move_pp=(25, 20, 0, 0), relearn=(1, 2, 3, 4),
                 ball=4, met_level=4, met_location=357, egg_location=65535, language=3,
                 version=49, ot_friendship=50, met_date=(21, 11, 21), gender=1,
                 current_handler=0, is_egg=False)
    r = pokemon.read(pokemon.build_from(template, **edits))
    for key, value in edits.items():
        assert r[key] == value, f"{key} did not survive"
    # met_level and ot_gender share a byte and must not tread on each other
    both = pokemon.read(pokemon.build_from(template, met_level=100, ot_gender=1))
    assert (both["met_level"], both["ot_gender"]) == (100, 1)


def test_a_name_too_long_for_its_field_is_refused_rather_than_truncated():
    template = pokemon.encrypt(a_body())
    with pytest.raises(ValueError, match="too long"):
        pokemon.build_from(template, nickname="A" * 13)
    with pytest.raises(ValueError, match="too long"):
        room.build_trade_traner("A" * 13, 1, 2)


def test_the_trade_messages_wrap_the_payloads_the_console_wraps_them_in():
    raw = pokemon.encrypt(a_body())
    msg = room.build_trade_poke(raw)
    assert msg[:3].hex() == "130148"                     # id 0x13, length 0x148 = 328
    assert room.parse(msg)["name"] == "NetTradePokeData"
    assert msg[3:] == raw
    with pytest.raises(ValueError, match="328-byte"):
        room.build_trade_poke(raw[:-1])
    rec = room.build_trade_traner("Gurvan", 44466, 4080)
    assert room.parse_trade_traner(rec[3:])["trainer_id"] == 44466


# the two trainer records this project has seen, sp82 and sp83. They differ at 0x18.
TRADE_TRANER_SP82 = bytes.fromhex(
    "470075007200760061006e000000000018a4010014a401000000b2adf00f3103")
TRADE_TRANER_SP83 = bytes.fromhex(
    "470075007200760061006e000000000018a4010014a401006e3db2adf00f3103")


def test_the_trainer_record_is_parsed_from_the_game_message_not_the_reliable_frame():
    """sp83 handed the parser the reliable frame and the exception took the station down.

    The console reads a station that vanishes mid-trade as a cancellation, which is exactly what
    the player saw. The parser must refuse a wrong length loudly - it did - and the caller must
    pass the game message alone.
    """
    message = room.build(room.TRADE_TRANER, TRADE_TRANER_SP83)
    assert room.parse(message)["data_id"] == room.TRADE_TRANER
    body = message[room.HEADER_SIZE:]
    assert len(body) == room.TRADE_TRANER_SIZE
    assert room.parse_trade_traner(body)["name"] == "Gurvan"
    # a reliable header left on the front is a length error, not a silent misparse
    with pytest.raises(ValueError, match="expected 32"):
        room.parse_trade_traner(b"\x00" * 9 + body)


def test_the_bytes_behind_the_name_vary_between_sessions_and_no_field_is_read_out_of_them():
    """sp82 and sp83 differ only in the slack, and every declared field holds still.

    The record is a marshalled struct out of an uncleared `AllocHGlobal` block, so what follows the
    name's terminator is heap residue. It is carried, not interpreted.
    """
    sp82 = room.parse_trade_traner(TRADE_TRANER_SP82)
    sp83 = room.parse_trade_traner(TRADE_TRANER_SP83)
    assert sp82["slack"] != sp83["slack"]
    assert sp82["name"] == sp83["name"] == "Gurvan"
    assert sp82["trainer_id"] == sp83["trainer_id"] == 44466
    assert sp82["secret_id"] == sp83["secret_id"] == 4080
    assert sp82["casset_version"] == sp83["casset_version"] == 0x31
    assert sp82["lang_id"] == sp83["lang_id"] == 3


def test_the_trainer_record_we_build_is_the_console_s_own_bytes():
    """Byte-identical to sp82: the layout is not just readable, it is reproducible."""
    assert room.build_trade_traner("Gurvan", 44466, 4080)[3:] == TRADE_TRANER_SP82
    parsed = room.parse(room.build(room.TRADE_TRANER, TRADE_TRANER_SP83))
    assert parsed["traner"]["name"] == "Gurvan"


def test_the_measured_layouts_are_no_longer_reported_opaque():
    """0x02, 0x13, 0x22 and 0x24 are the OPAQUE ids a capture holds, and all four are decided."""
    for data_id in room.MEASURED:
        assert data_id in netdata.OPAQUE
        assert room.parse(room.build(data_id, b"\x00" * 32))["opaque"] is False
    assert room.parse(room.build(0x42, b"\x00" * 8))["opaque"] is True


def test_every_opaque_payload_has_its_marshalled_size():
    """The executable's Il2CppTypeDefinitionSizes decides all twelve, and the wire agrees on the
    four it has carried: 72, 328, 20 and 32 bytes."""
    assert set(room.NATIVE_SIZES) == set(netdata.OPAQUE)
    assert room.NATIVE_SIZES[room.POS] == room.POS_POINTS * room.POS_POINT_SIZE
    assert room.NATIVE_SIZES[room.TRADE_POKE] == 328
    assert room.NATIVE_SIZES[room.STANDBY_LIST] == room.STANDBY_SLOTS * room.STANDBY_SIZE
    assert room.NATIVE_SIZES[room.TRADE_TRANER] == room.TRADE_TRANER_SIZE


def test_the_standby_list_reads_the_record_the_console_sent_back():
    """`22 0014 01 00 01 03` + 16 zero bytes: station 1, French, in slot 0, after it was added."""
    msg = room.parse(bytes.fromhex("2200140100010300000000000000000000000000000000"))
    assert msg["standby"][0] == {"is_add_player": 1, "host_index": 0, "my_index": 1, "lang_id": 3}
    assert msg["standby"][1]["is_add_player"] == 0 and len(msg["standby"]) == 5


def test_the_handler_block_is_readable_and_settable():
    """sp99 gave a console a Pokemon whose OT was not the player and asked for it back.

    Eleven bytes changed: the handler name at 0xA8, language at 0xC3, CurrentHandler at 0xC4,
    friendship at 0xC8, and the checksum. 0xC6 - which PKHeX carries as `// unused?` - stayed zero
    while everything around it was written, so it is unused in BDSP.
    """
    # a_body's filler is a byte pattern, not zeros, so an untraded Pokemon has to be made one:
    # IsUntraded is literally "the handler name field is empty".
    template = pokemon.encrypt(a_body())
    template = pokemon.build_from(template, ht_name="")
    assert pokemon.read(template)["is_untraded"] is True

    traded = pokemon.build_from(template, ht_name="Gurvan", ht_language=3,
                                current_handler=1, ht_friendship=50)
    r = pokemon.read(traded)
    assert (r["ht_name"], r["ht_language"], r["current_handler"], r["ht_friendship"]) \
        == ("Gurvan", 3, 1, 50)
    assert r["is_untraded"] is False
    assert r["ot_name"] == "Gurvan", "the OT is not the handler and must not move"
