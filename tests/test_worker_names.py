"""Naming the workers from the decomp's call order, and the two cartridges not being mixed.

bs84 read a handler's workers off a 1 KB window by hand: every ScrCmd body is
`VarGet(ScriptReadHalfword(ctx))` per argument and then one call, so the `bl`s come out in the
decomp's own call order and name themselves. bs111, bs112 and bs121 did the same for three more
tables. `scripts/gen_worker_names.py` is that reading mechanised, and these are the checks that
decide whether what it produces is evidence: evaluation order, the right preprocessor branch, an
equal call count, an anchor that lands back on its own name, callers that agree, and the link
script's own order over the whole ROM.

THE BUG THESE TESTS EXIST FOR, session 42: `--with-every-dump` folded lg191's 16 KB of LeafGreen
into the same image as the FireRed dumps. LeafGreen keeps that code at FireRed's address minus 0x2C,
so the image answered with whichever cartridge's copy it had placed there, and a body read out of
the wrong one calls that cartridge's workers. It named nothing wrong only because the anchor check
threw those bodies out - `AddBagItem` came back 0x2C low - but it is where most of "127 call targets
with no name" came from.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))

from frlgsim import decomp_source, rom_map, worker_names   # noqa: E402
from script_read import dump_console                       # noqa: E402
import gen_worker_names                                    # noqa: E402

ROM_START, ROM_END = 0x08000000, 0x0A000000


# --- the parser: what agbcc emits, not what the source reads like -------------------------------

def test_an_argument_is_called_before_the_call_it_feeds():
    # `VarGet(ScriptReadHalfword(ctx))` is `bl ScriptReadHalfword` then `bl VarGet`, and reading it
    # left to right would misalign nearly every ScrCmd body in the table.
    assert decomp_source.call_sequence("{ a = VarGet(ScriptReadHalfword(ctx)); }") == [
        "ScriptReadHalfword", "VarGet"]


def test_a_cast_before_a_parenthesis_is_not_a_call_through_a_pointer():
    assert decomp_source.call_sequence("{ x = (u8)(y + 1); }") == []
    assert decomp_source.call_sequence("{ u16 (*const *p)(void) = &gSpecials[0]; }") == []


def test_a_condition_followed_by_a_statement_is_not_a_call_through_a_pointer():
    # ScrCmd_special: `if (specialPtr < gSpecialsEnd)\n    (*specialPtr)();` - the `(` of the
    # statement follows the `)` of the condition, which read as one call too many until the keyword
    # before the group was checked.
    body = "{ if (p < gSpecialsEnd) (*p)(); }"
    assert decomp_source.call_sequence(body) == [decomp_source.INDIRECT]


def test_a_call_through_a_table_keeps_its_slot():
    # agbcc turns it into `bl` a veneer, so it holds a place in the measured list and names nothing.
    assert decomp_source.call_sequence("{ gSpecials[i](); }") == [decomp_source.INDIRECT]


def test_the_switch_build_is_the_one_that_is_read():
    source = """
void f(void)
{
#if REVISION >= 0xA
    OnTheSwitch();
#else
    OnTheCartridge();
#endif
#if defined(LEAFGREEN)
    NotThisGame();
#endif
}
"""
    assert decomp_source.call_sequence(decomp_source.functions(source)[0][2]) == ["OnTheSwitch"]


def test_an_assert_compiles_to_nothing_and_takes_its_arguments_with_it():
    # NDEBUG is a measurement here: ScrCmd_special's body on the cartridge makes two calls, and the
    # assert branch would add a third [include/gba/isagbprint.h:53].
    body = '{ AGB_ASSERT_EX(0, ABSPATH("scrcmd.c"), 241); Real(); }'
    assert decomp_source.call_sequence(body) == ["Real"]


def test_a_macro_that_expands_to_arithmetic_emits_no_call():
    # `#define ScriptReadByte(ctx) (*(ctx->scriptPtr++))` [include/script.h:24]. Reading it as a
    # call put a phantom `bl` in 151 bodies - nearly half of everything that failed to align.
    assert decomp_source.call_sequence("{ x = ScriptReadByte(ctx); Real(); }") == ["Real"]
    assert decomp_source.call_sequence("{ SetWarp(MAP_GROUP(PALLET_TOWN), MAP_NUM(X)); }") == [
        "SetWarp"]


def test_the_dispatch_macros_resolve_to_the_symbol_the_rom_holds():
    # GetMonData is `CAT(GetMonData, NARG_8(...))` [include/pokemon.h:343] and GetMonData2 is an
    # alias of GetMonData3 [pokemon.c:2970]: one address, and the source calls it by a third name.
    assert decomp_source.call_sequence("{ GetMonData(mon, MON_DATA_SPECIES, NULL); }") == [
        "GetMonData3"]


def test_a_definition_is_found_with_its_brace_on_either_line():
    source = "void OnTheNextLine(void)\n{\n    A();\n}\n\nvoid svc_Same(u32 x) {\n    B();\n}\n"
    assert [name for name, _line, _body in decomp_source.functions(source)] == [
        "OnTheNextLine", "svc_Same"]


def test_definition_order_is_kept_because_that_is_what_the_rom_holds():
    source = "void First(void)\n{\n}\n\nvoid Second(void)\n{\n}\n"
    assert [name for name, _line, _body in decomp_source.functions(source)] == ["First", "Second"]


# --- the checks on top --------------------------------------------------------------------------

def test_a_project_name_matches_by_shape_only_when_it_is_one_we_coined():
    assert gen_worker_names.same_function("SCRIPT_READ_WORD", "ScriptReadWord")
    assert gen_worker_names.same_function("ScrCmd_end", "ScrCmd_end")
    # `gMysteryEventScriptCmdTable` is kept by OPCODE name, and the opcode `enableresetrtc` is not
    # event_data.c's `EnableResetRTC` however alike the two look with the underscores taken out.
    assert not gen_worker_names.same_function("enableresetrtc", "EnableResetRTC")


def test_the_longest_ascending_chain_wins_not_the_first():
    # One name a megabyte out of place must not throw out the ones that agree with each other.
    points = [(0, 0, 0x08046D78, "A", True), (0, 1, 0x08129844, "Wrong", True),
              (0, 2, 0x08046DF4, "B", True), (0, 3, 0x0804713C, "C", True)]
    assert [point[3] for point in gen_worker_names.ascending_outliers(points)] == ["Wrong"]


def test_the_link_script_is_what_orders_two_different_files():
    decomp = pathlib.Path("~/pokefirered").expanduser()
    if not (decomp / "ld_script_rev10.ld").exists():
        pytest.skip("no decomp checkout to read ld_script_rev10.ld from")
    order = gen_worker_names.link_order(decomp)
    # sloopsvc.o is laid down immediately before string_util.o [ld_script_rev10.ld:69], which is
    # what puts svc_SetStarter below StringGet_Nickname and makes that pair checkable.
    assert order["sloopsvc.c"] < order["string_util.c"] < order["link.c"]


# --- the table that was generated ---------------------------------------------------------------

def test_every_worker_is_a_rom_address_named_once():
    assert len(worker_names.WORKERS) >= 180
    assert all(ROM_START <= address < ROM_END for address in worker_names.WORKERS)
    assert all(address % 2 == 0 for address in worker_names.WORKERS)
    assert len(set(worker_names.WORKERS.values())) == len(worker_names.WORKERS)
    assert worker_names.WORKER_ADDRESSES == {name: address
                                             for address, name in worker_names.WORKERS.items()}


def test_no_worker_contradicts_an_address_a_run_measured():
    # A name here is a reading; a name in rom_map cost a hardware run. The generator drops the whole
    # body when the two disagree, so nothing in this table may sit on a measured address.
    # Against the addresses rom_map names as FUNCTIONS. A constant that is a limit rather than a
    # name is not one of them: SHARED_WITH_LEAFGREEN_THROUGH is 0x0807AF04 because that is the
    # highest call target that did not move between the cartridges, and the function there has a
    # name of its own.
    measured = set(rom_map.CALLABLE.values()) | set(rom_map.DECOMP_NAMES)
    assert not (set(worker_names.WORKERS) & {address & ~1 for address in measured})


def test_the_decomp_names_this_project_coined_are_the_ones_the_bodies_agreed_on():
    # Session 42, from the alignment: four addresses this project had named itself, each confirmed
    # by every body that reaches it. `SetupNativeScript` is eleven of them.
    assert rom_map.DECOMP_NAMES[rom_map.SCRIPT_CONTEXT_SET_NATIVE] == "SetupNativeScript"
    assert rom_map.DECOMP_NAMES[rom_map.GET_MON_DATA] == "GetMonData3"
    assert rom_map.DECOMP_NAMES[rom_map.SET_RESPAWN] == "SetLastHealLocationWarp"
    assert all(address in vars(rom_map).values() or address & ~1 in vars(rom_map).values()
               for address in rom_map.DECOMP_NAMES)


def test_a_worker_several_bodies_agreed_about_carries_that_count():
    for name, (source_file, _index, callers) in worker_names.SOURCES.items():
        assert source_file.endswith(".c")
        assert callers >= 1, name
    assert max(callers for _f, _i, callers in worker_names.SOURCES.values()) >= 5


# --- one cartridge at a time --------------------------------------------------------------------

def test_a_run_says_which_cartridge_it_was_against():
    assert dump_console("bs121", "--expect-console firered --dump-address 0x0806DBD4") == "firered"
    assert dump_console("lg192", "--expect-console leafgreen") == "leafgreen"
    # The runs that predate the flag are classified the way run_mg_fast.sh classifies them.
    assert dump_console("lg178", "--dump-address 0x08600000") == "leafgreen"
    assert dump_console("bs93", "--dump-address 0x081639FC") == "firered"
    assert dump_console("mev25", "--dump-address 0x08000000") == "firered"


def test_the_dumps_of_one_cartridge_are_not_placed_at_the_other_s_addresses(tmp_path):
    logs = tmp_path / "launcher_logs"
    logs.mkdir()
    (logs / "bs120_launcher.log").write_text("--expect-console firered --dump-address 0x08081CC8")
    (tmp_path / "bs120_dump.bin").write_bytes(b"\x01" * 16)
    (logs / "lg191_launcher.log").write_text("--expect-console leafgreen --dump-address 0x08081C9C")
    (tmp_path / "lg191_dump.bin").write_bytes(b"\x02" * 16)

    from script_read import every_dump
    assert every_dump(str(tmp_path)) == [(0x08081CC8, b"\x01" * 16)]
    assert every_dump(str(tmp_path), "leafgreen") == [(0x08081C9C, b"\x02" * 16)]
    assert len(every_dump(str(tmp_path), None)) == 2


def test_a_scattered_run_is_placed_block_by_block(tmp_path):
    """`memory-dump-scatter` sends UNRELATED regions in one session and the host appends them, so
    the file holds them end to end and one `--dump-address` would put every block after the first
    in the wrong place. The run's own list of bases is what says where each one belongs."""
    logs = tmp_path / "launcher_logs"
    logs.mkdir()
    (logs / "bs122_launcher.log").write_text(
        "--expect-console firered --buffer-script memory-dump-scatter "
        "--dump-scatter 0x080CE040,0x0804A2A0 --dump-size 1024")
    (tmp_path / "bs122_dump.bin").write_bytes(b"\xAA" * 1024 + b"\xBB" * 1024)

    from script_read import dumps
    placed = dumps(str(tmp_path))
    assert [(tag, base, block[0]) for tag, _console, base, block in placed] == [
        ("bs122[0]", 0x080CE040, 0xAA), ("bs122[1]", 0x0804A2A0, 0xBB)]


def test_the_shipped_table_is_what_this_decomp_and_these_dumps_still_say():
    """A generated module that nobody can reproduce is a claim, not a measurement. This regenerates
    the naming from the decomp and the dumps on this machine and demands every shipped name back.

    A SUBSET rather than equality: a dump taken later adds names, and that is not a failure. A name
    that no longer comes out is - it means the alignment behind it stopped holding."""
    decomp = pathlib.Path("~/pokefirered").expanduser()
    scratchpad = pathlib.Path(__file__).resolve().parent.parent / "scratchpad"
    if not (decomp / "src").is_dir() or not (scratchpad / "launcher_logs").is_dir():
        pytest.skip("no decomp checkout or no dumps to regenerate from")

    from frlgsim import scrcmd
    from script_read import every_dump
    from rom_functions import known_names as all_known_names

    calls, where = decomp_source.read_tree(sorted(decomp.glob("src/**/*.c")))
    memory = scrcmd.Memory(every_dump(str(scratchpad), "firered"))
    names = {address: gen_worker_names.entry_name(label)
             for address, label in all_known_names(with_workers=False).items()
             if gen_worker_names.entry_name(label) not in gen_worker_names.MARKERS}
    names.update(rom_map.DECOMP_NAMES)
    proposals, _corrections, _dropped = gen_worker_names.align(calls, memory, names, set(where))
    accepted, _rejected = gen_worker_names.resolve(proposals, where, names,
                                                   gen_worker_names.link_order(decomp))
    for address, name in worker_names.WORKERS.items():
        assert accepted.get(address) == name, f"0x{address:08X} no longer comes back as {name}"


def test_a_gap_between_two_anchors_is_forced_even_when_the_counts_differ():
    """The length rule drops a body where agbcc inlined something or emitted `__umodsi3`. A gap
    BETWEEN two anchors holding exactly one unnamed target and exactly one source call is still
    forced: there is one way to fill it, whatever happened elsewhere in the body."""
    names = {0x08000100: "FlagSet", 0x08000200: "FlagGet"}
    measured = [0x08000100, 0x08000300, 0x08000200, 0x08000400]
    source = ["FlagSet", "TheOneInTheGap", "FlagGet", "AfterTheLastAnchor", "AndAnother"]
    assert gen_worker_names.closed_gaps(measured, source, names,
                                        {"FlagSet", "FlagGet", "TheOneInTheGap",
                                         "AfterTheLastAnchor", "AndAnother"}) == [
        (0x08000300, "TheOneInTheGap")]


def test_an_open_gap_names_nothing():
    # Before the first anchor and after the last, nothing bounds the gap, so nothing is forced.
    names = {0x08000200: "FlagGet"}
    measured = [0x08000100, 0x08000200, 0x08000400]
    source = ["Something", "FlagGet", "Another", "AndMore"]
    assert gen_worker_names.closed_gaps(measured, source, names,
                                        {"FlagGet", "Something", "Another", "AndMore"}) == []


def test_a_repeated_call_cannot_pull_the_alignment_sideways():
    # The anchors come from a longest common subsequence, so a name that appears twice matches in
    # order rather than at the first place it fits.
    measured_names = ["GetMonData3", None, "GetMonData3"]
    source = ["GetMonData3", "GetMonGender", "GetMonData3"]
    assert gen_worker_names.anchor_pairs(measured_names, source) == [(0, 0), (2, 2)]
