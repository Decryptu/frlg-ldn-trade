"""The ledger of what the console volunteers about itself.

Every session ships a MysteryGiftLinkGameData and every session before this one printed it and
threw it away. The counters in it (battlesWon, battlesLost, numTrades, the stamps) are the ones a
Battle Count Card would be built on, and a single reading of a counter says nothing at all - only
the difference between two sessions of the SAME console does.
"""

import json
import types

import frlgmg_host
import game_data_read
from frlgsim import charmap, easychat, game_data_log, mg_script, mystery_gift as mg


def _game_data(*, flag_id=0, questionnaire=(), profile=(), battles_won=0, battles_lost=0,
               trades=0, name="GURVAN", trainer_id=57189, stamps=(), version_code=1):
    raw = bytearray(mg_script.GAME_DATA_SIZE)
    raw[0:4] = mg.GAME_DATA_VALID_VAR.to_bytes(4, "little")
    raw[4] = raw[8] = raw[0x0C] = 1
    raw[0x10] = version_code                       # 1 FireRed, 2 LeafGreen
    raw[0x14:0x16] = int(flag_id).to_bytes(2, "little")
    for index, value in enumerate(easychat.resolve_words(questionnaire, 4)):
        raw[0x16 + 2 * index:0x18 + 2 * index] = int(value).to_bytes(2, "little")
    for index, value in enumerate(easychat.resolve_words(profile, 6)):
        raw[0x50 + 2 * index:0x52 + 2 * index] = int(value).to_bytes(2, "little")
    raw[0x20:0x22] = int(battles_won).to_bytes(2, "little")
    raw[0x22:0x24] = int(battles_lost).to_bytes(2, "little")
    raw[0x24:0x26] = int(trades).to_bytes(2, "little")
    for index, (species, stamp_id) in enumerate(stamps):
        raw[0x28 + 2 * index:0x2A + 2 * index] = int(species).to_bytes(2, "little")
        raw[0x36 + 2 * index:0x38 + 2 * index] = int(stamp_id).to_bytes(2, "little")
    raw[0x44] = 7
    # The name field is charmap text with NO terminator slot [PLAYER_NAME_LENGTH 7].
    encoded = charmap.encode(name)[:7]
    raw[0x45:0x4C] = encoded + b"\xff" * (7 - len(encoded))
    raw[0x4C:0x50] = int(trainer_id).to_bytes(4, "little")
    raw[0x5C:0x60] = b"BPRF"
    raw[0x60] = 0x0A
    return mg_script.parse_link_game_data(bytes(raw))


def test_the_record_carries_the_console_identity_and_the_card_counters():
    entry = game_data_log.record(
        _game_data(flag_id=1009, battles_won=3, battles_lost=1, trades=2), tag="mev25")

    assert entry["tag"] == "mev25"
    assert entry["player_name"] == "GURVAN"
    assert entry["trainer_id"] == 57189
    assert entry["version"] == "FireRed" and entry["game_code"] == "BPRF"
    assert (entry["flag_id"], entry["battles_won"], entry["battles_lost"], entry["num_trades"]) \
        == (1009, 3, 1, 2)


def test_a_seven_character_name_reports_no_trainer_id_rather_than_a_wrong_one():
    """The name field has no terminator slot, so a full name's 0xFF lands on playerTrainerId[0]
    [decomp:src/mystery_gift.c:364]. A wrong TID here would be indistinguishable from a real one."""
    entry = game_data_log.record(_game_data(name="GURVANO"))
    assert entry["trainer_id"] is None
    assert game_data_log.record(_game_data(name="GURVAN"))["trainer_id"] == 57189


def test_the_raw_bytes_survive_so_a_later_question_costs_no_run():
    data = _game_data(flag_id=1009, questionnaire=("hello", "friend", "thank_you", "trade"))
    reparsed = game_data_log.parse_raw(game_data_log.record(data))

    assert reparsed.raw == data.raw
    assert reparsed.questionnaire_words == data.questionnaire_words
    assert reparsed.describe() == data.describe()


def test_the_counters_are_reported_as_a_difference_not_as_a_number(tmp_path):
    path = tmp_path / "game_data.jsonl"
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=2, trades=1), tag="u34")
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=3, trades=2), tag="u35")
    first, second = game_data_log.read(path)

    assert game_data_log.console_key(first) == game_data_log.console_key(second)
    moved = game_data_log.changes(first, second)
    assert "battles won 2 -> 3" in moved
    assert "trades 1 -> 2" in moved
    assert not any("flagId" in line for line in moved)


def test_a_counter_that_moved_across_a_card_change_is_reported_with_the_change():
    before = game_data_log.record(_game_data(flag_id=1009, battles_won=2))
    after = game_data_log.record(_game_data(flag_id=1010, battles_won=0))
    moved = game_data_log.changes(before, after)

    assert moved[0] == "card flagId 1009 -> 1010"
    assert "battles won 2 -> 0" in moved


def test_two_identical_sessions_report_nothing_moved():
    entry = game_data_log.record(_game_data(flag_id=1009, battles_won=2, trades=1))
    assert game_data_log.changes(entry, dict(entry)) == ()


def test_a_new_questionnaire_is_a_change_because_it_is_new_vocabulary():
    before = game_data_log.record(_game_data(questionnaire=("hello", "friend", "thank_you",
                                                            "trade")))
    after = game_data_log.record(_game_data(questionnaire=("hello", "friend", "thank_you",
                                                           "hi")))
    assert any("questionnaire" in line for line in game_data_log.changes(before, after))


def test_a_slot_no_french_console_has_rendered_is_named_for_one_question():
    entry = game_data_log.record(_game_data(questionnaire=("hello", "friend", "thank_you",
                                                           "trade")))
    unknown = game_data_log.unknown_words(entry)
    # Whatever is unknown must be genuinely unknown: `french` is what the gate and every card
    # composed for this player is checked against.
    from frlgsim import easychat_french
    assert all(easychat_french.french(value) is None for value in unknown)


def test_a_species_word_is_never_flagged_because_it_needs_no_language():
    """EC_GROUP_POKEMON prints from gSpeciesNames, so the console prints its own localized name
    [decomp:src/easy_chat.c:155]."""
    entry = game_data_log.record(_game_data(profile=()))
    entry["easy_chat_profile"] = [easychat.species_word(55), easychat.move_word(177)]
    assert game_data_log.unknown_words(entry) == ()


def test_an_all_zero_battle_profile_reads_as_empty_not_as_six_rejected_words():
    """Word 0 is EC_GROUP_POKEMON_2 index 0; the console rejects it and prints "???"
    [decomp:src/easy_chat.c:118], so it is an empty field, not vocabulary."""
    entry = game_data_log.record(_game_data(flag_id=1009))
    lines = game_data_log.summary([entry])

    assert any(line.strip() == "battle profile: (none)" for line in lines), lines
    assert game_data_log.unknown_words(entry) == ()


def test_a_half_written_last_line_does_not_lose_the_sessions_before_it(tmp_path):
    """The Mystery Gift host is stopped with a signal, so a truncated final line is an ordinary
    way for the ledger to end (CLAUDE.md: the dump file only lands when the host exits cleanly)."""
    path = tmp_path / "game_data.jsonl"
    game_data_log.append(path, _game_data(flag_id=1009), tag="u34")
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"time": "2026-09-05T18:0')

    entries = game_data_log.read(path)
    assert len(entries) == 1 and entries[0]["tag"] == "u34"


def test_the_summary_separates_the_two_cartridges(tmp_path):
    path = tmp_path / "game_data.jsonl"
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=1), tag="fr70")
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=4), tag="fr71")
    leafgreen = _game_data(flag_id=1010, name="ARWEN", trainer_id=12345, version_code=2)
    lines = game_data_log.summary(game_data_log.read(path)
                                  + (game_data_log.record(leafgreen, tag="lg180"),))

    assert any("'GURVAN'" in line and "2 session(s)" in line for line in lines)
    assert any("'ARWEN'" in line and "LeafGreen" in line and "1 session(s)" in line
               for line in lines)
    assert any("battles won 1 -> 4" in line for line in lines)


def test_a_session_that_changed_nothing_is_counted_not_printed(tmp_path):
    path = tmp_path / "game_data.jsonl"
    for tag in ("u34", "u35", "u36"):
        game_data_log.append(path, _game_data(flag_id=1009, battles_won=2), tag=tag)
    lines = game_data_log.summary(game_data_log.read(path))

    assert any("(2 session(s) changed nothing)" in line for line in lines)
    assert not any(line.strip().startswith("u3") for line in lines)


def test_the_reader_prints_the_summary_and_one_session_in_full(tmp_path, capsys):
    path = tmp_path / "game_data.jsonl"
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=1), tag="fr70")
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=2), tag="fr71")

    assert game_data_read.main([str(path)]) == 0
    assert "battles won 1 -> 2" in capsys.readouterr().out

    assert game_data_read.main([str(path), "--session", "2"]) == 0
    out = capsys.readouterr().out
    assert "'GURVAN'" in out and "holding card flagId 1009" in out

    assert game_data_read.main([str(path), "--json"]) == 0
    dumped = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [entry["tag"] for entry in dumped] == ["fr70", "fr71"]


def test_the_reader_says_so_rather_than_failing_on_an_empty_ledger(tmp_path, capsys):
    path = tmp_path / "game_data.jsonl"
    path.write_text("")
    assert game_data_read.main([str(path)]) == 1
    assert "no sessions recorded" in capsys.readouterr().out


def _host_app_stub(path, capture=None):
    """The app seam _record_game_data uses: a config with the ledger path and an info sink."""
    lines = []
    app = types.SimpleNamespace(
        config=types.SimpleNamespace(game_data_log=path,
                                     ldn=types.SimpleNamespace(capture_path=capture)),
        info=lines.append)
    return app, lines


def test_the_host_writes_one_record_per_session_and_names_the_run_tag(tmp_path):
    from frlgsim.host_mg_app import MysteryGiftHostApplication
    path = str(tmp_path / "game_data.jsonl")
    app, lines = _host_app_stub(path, capture="scratchpad/mev25.pcap")
    engine = types.SimpleNamespace(server=types.SimpleNamespace(
        game_data=_game_data(flag_id=1009, battles_won=2)))

    MysteryGiftHostApplication._record_game_data(app, engine)

    entries = game_data_log.read(path)
    assert len(entries) == 1 and entries[0]["tag"] == "mev25"
    assert any("session 1" in line for line in lines)


def test_the_host_says_what_moved_since_the_last_session_of_that_console(tmp_path):
    from frlgsim.host_mg_app import MysteryGiftHostApplication
    path = str(tmp_path / "game_data.jsonl")
    game_data_log.append(path, _game_data(flag_id=1009, battles_won=2, trades=1), tag="u34")
    app, lines = _host_app_stub(path, capture="scratchpad/u35.pcap")
    engine = types.SimpleNamespace(server=types.SimpleNamespace(
        game_data=_game_data(flag_id=1009, battles_won=2, trades=2)))

    MysteryGiftHostApplication._record_game_data(app, engine)

    assert any("trades 1 -> 2" in line for line in lines)
    assert not any("battles won" in line for line in lines)


def test_a_session_the_console_never_identified_itself_in_writes_nothing(tmp_path):
    from frlgsim.host_mg_app import MysteryGiftHostApplication
    path = str(tmp_path / "game_data.jsonl")
    app, lines = _host_app_stub(path)

    MysteryGiftHostApplication._record_game_data(app, types.SimpleNamespace(server=None))
    MysteryGiftHostApplication._record_game_data(app, None)

    assert not lines and not (tmp_path / "game_data.jsonl").exists()


def test_the_ledger_is_off_unless_the_run_asks_for_it():
    parser = frlgmg_host.build_parser()
    default = frlgmg_host.build_run_config(parser, parser.parse_args(["--live"]))
    asked = frlgmg_host.build_run_config(
        parser, parser.parse_args(["--live", "--game-data-log", "scratchpad/game_data.jsonl"]))

    assert default.game_data_log is None
    assert asked.game_data_log == "scratchpad/game_data.jsonl"
