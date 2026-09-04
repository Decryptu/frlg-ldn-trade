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
