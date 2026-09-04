"""The ROM addresses read off the console, and the checks that keep them honest.

Nothing in frlgsim/rom_map.py is inferred from the decomp's English rev-10 build. These tests hold
the map to the evidence: the two dumps that produced it are in scratchpad/ (gitignored, so the tests
that need them skip when they are absent), and the internal consistency is checked either way.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import rom_map  # noqa: E402


SCRATCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scratchpad")


def _dump(name):
    path = os.path.join(SCRATCH, name)
    if not os.path.exists(path):
        pytest.skip(f"{name} is a hardware capture; not in the repo")
    with open(path, "rb") as handle:
        return handle.read()


def test_the_table_and_the_anchor_agree():
    """bs08 measured Client_RunBufferScript's return address from the CPU; bs12 read the function's
    address out of sClientFuncs. They are the same function reached two different ways, so the entry
    must be the function and the anchor must be inside it."""
    assert rom_map.client_func("Client_RunBufferScript") == rom_map.CLIENT_RUN_BUFFER_SCRIPT
    assert 0 < (rom_map.CLIENT_RUN_BUFFER_SCRIPT_RETURN
                - rom_map.CLIENT_RUN_BUFFER_SCRIPT) < 0x40
    # The table stores THUMB pointers; a bx to an even address would land in ARM state and crash.
    assert rom_map.thumb(rom_map.CLIENT_RUN_BUFFER_SCRIPT) & 1


def test_every_client_func_is_a_plausible_thumb_function_in_order():
    addresses = [address for _name, address in rom_map.CLIENT_FUNCS]
    assert addresses == sorted(addresses), "sClientFuncs follows source order in mystery_gift_client.c"
    for name, address in rom_map.CLIENT_FUNCS:
        assert 0x08000000 <= address < 0x0A000000, f"{name} is not in the cartridge"
        assert address % 2 == 0, f"{name} is stored with the THUMB bit already set"


def test_the_server_table_follows_the_client_table_and_names_five():
    """sFuncTable is 5 entries [FUNC_INIT..FUNC_RUN] and sits directly after sClientFuncs's 8, which
    is how bs12's single dump caught both."""
    assert rom_map.S_SERVER_FUNCS == rom_map.S_CLIENT_FUNCS + 4 * len(rom_map.CLIENT_FUNCS)
    assert len(rom_map.SERVER_FUNCS) == 5
    addresses = [address for _name, address in rom_map.SERVER_FUNCS]
    assert addresses == sorted(addresses)
    assert all(0x08000000 <= a < 0x0A000000 and a % 2 == 0 for a in addresses)
    assert rom_map.client_func("Server_Init") == 0x08148DF0


def test_the_server_table_is_where_bs12_read_it():
    dump = _dump("bs12_dump.bin")
    start = 4 * len(rom_map.CLIENT_FUNCS)
    for i, (_name, address) in enumerate(rom_map.SERVER_FUNCS):
        value = int.from_bytes(dump[start + 4 * i:start + 4 * i + 4], "little")
        assert value == address | 1


def test_the_map_says_which_build_it_belongs_to():
    assert (rom_map.GAME_CODE, rom_map.SOFTWARE_VERSION) == (b"BPRF", 0x0A)
    assert rom_map.client_func("Client_Init")
    with pytest.raises(KeyError, match="sClientFuncs"):
        rom_map.client_func("Client_Nope")


def test_the_cartridge_header_bs07_read_is_the_build_the_map_describes():
    lines = "\n".join(rom_map.describe_header(_dump("bs07_dump.bin")))
    assert "b'POKEMON FIRE'" in lines
    assert "b'BPRF'" in lines
    assert "version    0x0A" in lines
    assert "recomputed 0x5D -> VALID" in lines
    assert "the build rom_map.py describes" in lines
    assert "NOT the build" not in lines


def test_a_header_from_another_build_is_rejected():
    header = bytearray(_dump("bs07_dump.bin"))
    header[0xAC:0xB0] = b"BPGF"                 # LeafGreen, French
    lines = "\n".join(rom_map.describe_header(bytes(header)))
    assert "NOT the build rom_map.py describes" in lines
    assert "MISMATCH: this is not a whole header" in lines   # the checksum no longer covers it


def test_the_client_func_table_bs12_read_is_the_one_in_the_map():
    """The self-check that mattered: entry 7 read out of ROM is the function whose return address
    the CPU handed us in bs08, and every entry lands where bs11's disassembly shows a prologue."""
    read = rom_map.read_client_funcs(_dump("bs12_dump.bin"))

    assert [(name, address) for name, address, _thumb in read] == list(rom_map.CLIENT_FUNCS)
    assert all(is_thumb for _n, _a, is_thumb in read)
    assert read[7][1] == rom_map.CLIENT_RUN_BUFFER_SCRIPT


BS39_DUMP_AT = 0x0824CDC0            # --dump-address bs39 was launched with


def test_the_species_table_address_reproduces_bs38s_three_hits():
    """The map's address and stride ARE bs38's measurement: the three species whose base stats are
    all 100 must land exactly on the three addresses the scan returned, with no slack. A wrong
    stride or a base off by one entry breaks this immediately."""
    computed = tuple(rom_map.GSPECIES_INFO + rom_map.SPECIES_INFO_STRIDE * species
                     for species in rom_map.SPECIES_INFO_ALL_100)

    assert computed == rom_map.BS38_SPECIES_INFO_HITS
    # and the gaps are what said the stride is 28 rather than the decomp's 26
    gaps = [b - a for a, b in zip(computed, computed[1:])]
    assert gaps == [100 * 28, 158 * 28] == [2800, 4424]


def test_the_species_table_sits_below_the_easy_chat_data_link_order_predicted():
    """src/pokemon.o is the 26th .rodata entry and src/easy_chat.o the 104th, so the whole table
    must end below the word data bs17 measured at 0x083DE2C8."""
    end = rom_map.GSPECIES_INFO + rom_map.SPECIES_INFO_STRIDE * rom_map.SPECIES_INFO_SLOTS

    assert rom_map.GSPECIES_INFO > 0x08200000        # in .rodata, past all of .text
    assert end < 0x083DE2C8


def test_the_pokemon_functions_are_ordered_as_pokemon_c_declares_them():
    """CreateMon is defined immediately before CreateBoxMon and calls it [pokemon.c:1755-1766],
    and every one of them is below src/random.o, which link order puts two objects later."""
    assert rom_map.ZERO_MON_DATA < rom_map.CREATE_MON < rom_map.CREATE_BOX_MON
    assert rom_map.CREATE_BOX_MON < rom_map.CALCULATE_MON_STATS < rom_map.SET_MON_DATA
    assert rom_map.SET_MON_DATA < rom_map.RANDOM


def test_create_mon_is_thumb_and_callable():
    """--trace-call takes a THUMB pointer; an even address here would fault the console."""
    for address in (rom_map.CREATE_MON, rom_map.CREATE_BOX_MON, rom_map.CALCULATE_MON_STATS):
        assert address % 2 == 0
        assert rom_map.thumb(address) == address + 1


def test_the_species_table_dump_is_the_table():
    """bs39 dumped 1024 bytes from 60 before the base. Bulbasaur is species 1, so its entry must
    start exactly one stride in, and its base stats are fixed game data."""
    dump = _dump("bs39_dump.bin")
    start = rom_map.GSPECIES_INFO - BS39_DUMP_AT

    bulbasaur = dump[start + rom_map.SPECIES_INFO_STRIDE:][:10]
    assert list(bulbasaur) == [45, 49, 49, 45, 65, 65, 12, 3, 45, 64]
    # species 0 is the SPECIES_NONE placeholder and is all zeros on the console
    assert dump[start:start + rom_map.SPECIES_INFO_STRIDE] == bytes(rom_map.SPECIES_INFO_STRIDE)
    # the two bytes the decomp does not declare are padding, on every entry the dump covers
    for species in range(1, 34):
        entry = dump[start + species * rom_map.SPECIES_INFO_STRIDE:][:rom_map.SPECIES_INFO_STRIDE]
        assert entry[26:28] == b"\x00\x00", species


def test_the_two_parties_are_adjacent_as_the_decomp_declares_them():
    """gEnemyParty[6] is declared immediately before gPlayerParty[6] [decomp:src/pokemon.c:61-62],
    so they are exactly 600 bytes apart. bs42 read both out of two literal pools and bs47 confirmed
    the player's by finding the player's Chansey in it, so this is two routes to one answer."""
    assert rom_map.GPLAYER_PARTY - rom_map.GENEMY_PARTY == 6 * 100
    assert rom_map.GPLAYER_PARTY_COUNT < rom_map.GENEMY_PARTY, (
        "the count bytes are declared before both arrays")
    for address in (rom_map.GPLAYER_PARTY, rom_map.GPLAYER_PARTY_COUNT, rom_map.GENEMY_PARTY):
        assert 0x02000000 <= address < 0x02040000, "EWRAM"
    # And they are NOT the save block's copy: every gSaveBlock1Ptr this project has seen is far
    # above them, and those move while these do not.
    assert all(seen > rom_map.GPLAYER_PARTY + 600 for seen in rom_map.GSAVEBLOCK1_SEEN)
