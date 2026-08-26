"""Offline regressions for the bounded Stage 1 JoySpot discovery probe."""

from dataclasses import FrozenInstanceError
from contextlib import redirect_stderr, redirect_stdout
import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import joyspot_probe
from frlgsim import beacon, charmap, transport
from frlgsim.host_beacon import CAPTURED_TRADE_BEACON
from frlgsim.config import DEFAULT_TRAINER, TrainerProfile
from frlgsim.joyspot_probe import JoySpotProbeApplication, JoySpotProbeConfig
from frlgsim.joyspot_discovery import (
    JOYSPOT_CANDIDATES,
    JOYSPOT_LOCAL_COMMUNICATION_ID,
    JOYSPOT_MAX_PARTICIPANTS,
    JOYSPOT_SERIAL,
    SEARCH_ACTIVITY_MASK,
    SEARCH_HAS_CARD,
    SEARCH_STARTED_ACTIVITY,
    SEARCH_UNKNOWN_BIT7,
    SERIAL_PLACEMENT_OFFSETS,
    JoySpotCandidate,
    build_joyspot_app_data,
    candidate_by_name,
    candidates_for_stage,
    decode_joyspot_app_data,
)


EXPECTED_STAGE_1_1 = (
    "wireless_activity21_no_card",
    "wireless_activity21_card",
    "wireless_activity4_card",
    "wireless_activity0_card",
)

EXPECTED_STAGE_1_2 = (
    "serial_be_12",
    "serial_be_14",
    "serial_be_18",
    "serial_be_20",
    "serial_be_22",
    "serial_le_13",
    "serial_le_19",
    "search_bit7_clear",
)

EXPECTED_CANDIDATES = EXPECTED_STAGE_1_1 + EXPECTED_STAGE_1_2 + ("friend_control",)

REMOVED_STAGE_1_0_CANDIDATES = (
    "baseline",
    "scene_0",
    "scene_21",
    "scene_7f7d",
    "app_version_7f7d",
    "pia_app_version_7f7d",
    "record_word_12",
    "record_word_14",
    "record_word_18",
    "record_word_20",
    "record_word_22",
)


def _candidate(name):
    return next(candidate for candidate in JOYSPOT_CANDIDATES
                if candidate.name == name)


def _record(app_data):
    return transport._b85_decode(
        app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]


def _captured_identity_profile():
    # The captured Switch nickname is Chase, while its Gen III trainer is GREEN.
    # Only the decoded RFU record matters to this preservation regression.
    return TrainerProfile(
        name="GREEN", tid=0x1050, sid=0, gender=0,
        version="leafgreen", language="english")


def test_candidate_matrix_is_exact_ordered_and_immutable():
    assert isinstance(JOYSPOT_CANDIDATES, tuple)
    assert tuple(candidate.name for candidate in JOYSPOT_CANDIDATES) \
        == EXPECTED_CANDIDATES
    assert len({candidate.name for candidate in JOYSPOT_CANDIDATES}) \
        == len(JOYSPOT_CANDIDATES)

    candidate = JOYSPOT_CANDIDATES[0]
    try:
        candidate.name = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("JoySpotCandidate must be immutable")

    for candidate in JOYSPOT_CANDIDATES:
        assert candidate_by_name(candidate.name) is candidate
    try:
        candidate_by_name("not_a_candidate")
    except ValueError as error:
        assert "not_a_candidate" in str(error)
    else:
        raise AssertionError("unknown candidate was accepted")


def test_candidate_matrix_changes_only_the_bounded_surface():
    expected = {
        "wireless_activity21_no_card": (21, False, 22287, 88, 88, False),
        "wireless_activity21_card": (21, True, 22287, 88, 88, False),
        "wireless_activity4_card": (4, True, 22287, 88, 88, False),
        "wireless_activity0_card": (0, True, 22287, 88, 88, False),
        "serial_be_12": (21, True, 22287, 88, 88, False),
        "serial_be_14": (21, True, 22287, 88, 88, False),
        "serial_be_18": (21, True, 22287, 88, 88, False),
        "serial_be_20": (21, True, 22287, 88, 88, False),
        "serial_be_22": (21, True, 22287, 88, 88, False),
        "serial_le_13": (21, True, 22287, 88, 88, False),
        "serial_le_19": (21, True, 22287, 88, 88, False),
        "search_bit7_clear": (21, False, 22287, 88, 88, False),
        "friend_control": (21, False, 22287, 88, 88, True),
    }
    for candidate in JOYSPOT_CANDIDATES:
        assert (
            candidate.activity,
            candidate.has_card,
            candidate.scene_id,
            candidate.app_version,
            candidate.pia_app_version,
            candidate.friend_control,
        ) == expected[candidate.name]
        assert not hasattr(candidate, "record_word_offset")

    # Candidate selection must never alter the title-wide communication ID.
    assert JOYSPOT_LOCAL_COMMUNICATION_ID \
        == transport.HostTransport.LOCAL_COMMUNICATION_ID
    assert JOYSPOT_MAX_PARTICIPANTS == 2
    assert all(candidate.scene_id == transport.HostTransport.SCENE_ID
               for candidate in JOYSPOT_CANDIDATES)
    assert all(candidate.app_version == transport.HostTransport.APPLICATION_VERSION
               for candidate in JOYSPOT_CANDIDATES)
    assert SEARCH_ACTIVITY_MASK == 0x007F
    assert SEARCH_HAS_CARD == 0x4000
    assert SEARCH_STARTED_ACTIVITY == 0x8000


def test_wireless_activity21_no_card_preserves_unknown_record_bytes():
    original = _record(CAPTURED_TRADE_BEACON)
    profile = _captured_identity_profile()
    built = build_joyspot_app_data(
        profile, original[10:12], _candidate("wireless_activity21_no_card"))
    actual = _record(built)

    expected = bytearray(original)
    # Identity fields are deliberately normalized by the profile.  In
    # particular, Gen III names use all-FF padding even though this capture had
    # two trailing zeroes after its terminator.
    expected[0:2] = profile.discovery_trainer_id.to_bytes(2, "little")
    expected[2:10] = charmap.encode(
        profile.discovery_name, width=8, pad=0xFF)
    expected[10:12] = original[10:12]
    search_word = int.from_bytes(expected[16:18], "little")
    search_word &= ~(
        SEARCH_ACTIVITY_MASK | SEARCH_HAS_CARD | SEARCH_STARTED_ACTIVITY)
    search_word |= 21
    expected[16:18] = search_word.to_bytes(2, "little")
    assert actual == bytes(expected)


def test_wireless_activity21_no_card_preserves_unknown_pia_header_bytes():
    # Match the captured Pia nickname so there are no intentional header
    # mutations; every byte must survive the clone-and-patch path.
    profile = TrainerProfile(
        name="Chase", tid=0x1050, sid=0, gender=0,
        version="leafgreen", language="english")
    original_record = _record(CAPTURED_TRADE_BEACON)
    built = build_joyspot_app_data(
        profile, original_record[10:12],
        _candidate("wireless_activity21_no_card"))
    assert built[:beacon.PIA_HDR] == CAPTURED_TRADE_BEACON[:beacon.PIA_HDR]


def test_identity_and_rfu_parent_id_are_the_only_identity_mutations():
    host_session_id = b"\xb7\xf1"
    app_data = build_joyspot_app_data(
        DEFAULT_TRAINER, host_session_id,
        _candidate("wireless_activity21_no_card"))
    record = _record(app_data)

    assert int.from_bytes(record[0:2], "little") \
        == DEFAULT_TRAINER.discovery_trainer_id
    assert record[2:10] == charmap.encode(
        DEFAULT_TRAINER.discovery_name, width=8, pad=0xFF)
    assert record[10:12] == host_session_id
    assert record[10:12] != b"\x7d\x7f"
    assert record == bytes.fromhex(
        "2288cadfbdd5e1e4ffffb7f1000000009515000000000000")
    assert beacon.decode_pia_header(app_data)["nickname"] \
        == DEFAULT_TRAINER.session_name

    decoded = decode_joyspot_app_data(app_data)
    assert decoded.record == record
    assert decoded.trainer_id == DEFAULT_TRAINER.discovery_trainer_id
    assert decoded.name == DEFAULT_TRAINER.discovery_name
    assert decoded.rfu_session_id == host_session_id


def test_candidate_status_words_are_exact_and_decode_consistently():
    expected = {
        "wireless_activity21_no_card": (0x1595, 21, False),
        "wireless_activity21_card": (0x5595, 21, True),
        "wireless_activity4_card": (0x5584, 4, True),
        "wireless_activity0_card": (0x5580, 0, True),
        "serial_be_12": (0x5595, 21, True),
        "serial_be_14": (0x5595, 21, True),
        "serial_be_18": (0x5595, 21, True),
        "serial_be_20": (0x5595, 21, True),
        "serial_be_22": (0x5595, 21, True),
        "serial_le_13": (0x5595, 21, True),
        "serial_le_19": (0x5595, 21, True),
        # Only bit 7 differs from the proven Friend bytes (0x1595).
        "search_bit7_clear": (0x1515, 21, False),
        "friend_control": (0x1595, 21, False),
    }
    for candidate in JOYSPOT_CANDIDATES:
        app_data = build_joyspot_app_data(
            DEFAULT_TRAINER, b"\xa0\xf1", candidate)
        decoded = decode_joyspot_app_data(app_data)
        status, activity, has_card = expected[candidate.name]
        assert int.from_bytes(_record(app_data)[16:18], "little") == status
        assert decoded.search_word == status
        assert decoded.activity == activity
        assert decoded.has_card is has_card
        assert decoded.started_activity is False


def test_all_candidates_preserve_bytes_outside_identity_session_and_status():
    original = _record(CAPTURED_TRADE_BEACON)
    parent_id = b"\xa2\xf1"
    for candidate in JOYSPOT_CANDIDATES:
        app_data = build_joyspot_app_data(
            DEFAULT_TRAINER, parent_id, candidate)
        actual = _record(app_data)
        expected = bytearray(original)
        expected[0:2] = DEFAULT_TRAINER.discovery_trainer_id.to_bytes(
            2, "little")
        expected[2:10] = charmap.encode(
            DEFAULT_TRAINER.discovery_name, width=8, pad=0xFF)
        expected[10:12] = parent_id
        expected[16:18] = actual[16:18]
        if candidate.serial_offset is not None:
            offset = candidate.serial_offset
            expected[offset:offset + 2] = JOYSPOT_SERIAL.to_bytes(
                2, candidate.serial_endian)
        assert actual == bytes(expected), candidate.name
        assert app_data[:beacon.PIA_HDR] == build_joyspot_app_data(
            DEFAULT_TRAINER, parent_id,
            _candidate("wireless_activity21_no_card"))[:beacon.PIA_HDR]


def test_stage_1_2_serial_placements_never_touch_proven_fields():
    parent_id = b"\xa5\xf1"
    for candidate in candidates_for_stage("1.2"):
        if candidate.serial_offset is None:
            continue
        record = _record(build_joyspot_app_data(
            DEFAULT_TRAINER, parent_id, candidate))
        offset = candidate.serial_offset
        assert record[offset:offset + 2] == JOYSPOT_SERIAL.to_bytes(
            2, candidate.serial_endian), candidate.name
        # Identity, the RFU parent id, and the proven search word survive.
        assert record[0:2] == DEFAULT_TRAINER.discovery_trainer_id.to_bytes(
            2, "little")
        assert record[2:10] == charmap.encode(
            DEFAULT_TRAINER.discovery_name, width=8, pad=0xFF)
        assert record[10:12] == parent_id
        assert int.from_bytes(record[16:18], "little") & SEARCH_ACTIVITY_MASK == 21
        # Stage 1.0 already covered every little-endian aligned placement.
        assert (candidate.serial_endian == "big"
                or candidate.serial_offset not in (12, 14, 18, 20, 22))


def test_serial_placement_offsets_exclude_every_proven_field():
    for offset in SERIAL_PLACEMENT_OFFSETS:
        assert 12 <= offset <= 22
        # A two-byte write must stay clear of the parent id and search word.
        assert not (offset < 12 or 10 <= offset <= 11)
        assert offset + 1 < 16 or offset >= 18
    for bad in (0, 2, 8, 10, 11, 15, 16, 17, 23, -1):
        try:
            JoySpotCandidate("bad", "invalid", stage="1.2", serial_offset=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"serial_offset {bad} was accepted")
    try:
        JoySpotCandidate(
            "bad", "invalid", stage="1.2", serial_offset=12, serial_endian="middle")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid serial_endian was accepted")


def test_search_bit7_is_preserved_unless_a_candidate_opts_in():
    parent_id = b"\xa6\xf1"
    captured_bit7 = bool(
        int.from_bytes(_record(CAPTURED_TRADE_BEACON)[16:18], "little")
        & SEARCH_UNKNOWN_BIT7)
    assert captured_bit7 is True
    for candidate in JOYSPOT_CANDIDATES:
        decoded = decode_joyspot_app_data(
            build_joyspot_app_data(DEFAULT_TRAINER, parent_id, candidate))
        if candidate.search_bit7 is None:
            assert decoded.search_bit7 is captured_bit7, candidate.name
        else:
            assert decoded.search_bit7 is candidate.search_bit7, candidate.name


def test_stage_selection_is_ordered_and_always_ends_with_the_control():
    for stage in ("1.1", "1.2"):
        candidates = candidates_for_stage(stage)
        assert candidates[-1].name == "friend_control"
        assert all(c.stage == stage for c in candidates[:-1])
        assert len({c.name for c in candidates}) == len(candidates)
    assert tuple(c.name for c in candidates_for_stage("1.1")) \
        == EXPECTED_STAGE_1_1 + ("friend_control",)
    assert tuple(c.name for c in candidates_for_stage("1.2")) \
        == EXPECTED_STAGE_1_2 + ("friend_control",)
    assert candidates_for_stage("all") == JOYSPOT_CANDIDATES
    try:
        candidates_for_stage("2.0")
    except ValueError as error:
        assert "2.0" in str(error)
    else:
        raise AssertionError("unknown stage was accepted")


def test_wireless_no_card_and_friend_control_are_byte_identical():
    parent_id = b"\xa3\xf1"
    wireless = build_joyspot_app_data(
        DEFAULT_TRAINER, parent_id,
        _candidate("wireless_activity21_no_card"))
    friend = build_joyspot_app_data(
        DEFAULT_TRAINER, parent_id, _candidate("friend_control"))
    assert wireless == friend
    assert _record(wireless)[16:18] == b"\x95\x15"


def test_all_candidates_keep_application_size_and_parent_identity():
    parent_id = b"\xaf\xf1"
    for candidate in JOYSPOT_CANDIDATES:
        app_data = build_joyspot_app_data(
            DEFAULT_TRAINER, parent_id, candidate)
        assert len(app_data) == 122, candidate.name
        assert _record(app_data)[10:12] == parent_id, candidate.name


def test_probe_cli_exposes_one_candidate_at_a_time_and_fixed_network_shape():
    parser = joyspot_probe.build_parser()
    exposed = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert {
        "--candidate", "--all-candidates", "--list-candidates", "--live", "--phy", "--keys",
        "--password", "--capture", "--channel",
        "--skip-preflight", "--skip-encryption", "--accept-decrypted-ccmp",
    } <= exposed
    assert {
        "--comm-id", "--max-participants", "--scene", "--app-version",
        "--native-nonce-sequence", "--session-response-first",
    }.isdisjoint(exposed)

    help_text = parser.format_help()
    for name in EXPECTED_CANDIDATES:
        assert name in help_text
    for name in REMOVED_STAGE_1_0_CANDIDATES:
        assert name not in help_text
    args = parser.parse_args(
        ["--live", "--candidate", "wireless_activity4_card"])
    assert args.candidate == "wireless_activity4_card"


def test_all_candidates_is_mutually_exclusive_with_candidate_and_keeps_default():
    parser = joyspot_probe.build_parser()
    default_args = parser.parse_args(["--live"])
    assert default_args.candidate == "wireless_activity21_no_card"
    assert default_args.all_candidates is False

    sweep_args = parser.parse_args(["--live", "--all-candidates"])
    assert sweep_args.all_candidates is True

    errors = io.StringIO()
    try:
        with redirect_stderr(errors):
            parser.parse_args([
                "--live", "--candidate", "wireless_activity21_card",
                "--all-candidates",
            ])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("--candidate and --all-candidates were accepted together")
    assert "not allowed with argument" in errors.getvalue()


class _CliProbeApplication:
    """Fake application that exercises a live decision prompt without radio."""

    instances = []

    def __init__(self, config, profile, *, log):
        self.config = config
        self.profile = profile
        self.log = log
        self.run_calls = 0
        self.decision = None
        self.__class__.instances.append(self)

    def run(self, *, decision_prompt=None):
        self.run_calls += 1
        if decision_prompt is not None:
            self.decision = decision_prompt()
        return False

    def stop(self):
        raise AssertionError(
            "CLI must not own probe cleanup; JoySpotProbeApplication.run does")


def _run_fake_cli(argv, answers=()):
    _CliProbeApplication.instances = []
    answers = iter(answers)
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        try:
            return next(answers)
        except StopIteration:
            raise AssertionError("CLI requested more visibility answers than expected")

    output = io.StringIO()
    with (
        patch.object(joyspot_probe.os, "geteuid", return_value=0),
        patch.object(
            joyspot_probe, "JoySpotProbeApplication", _CliProbeApplication),
        patch("builtins.input", side_effect=answer),
        redirect_stdout(output),
    ):
        result = joyspot_probe.main(argv)
    try:
        next(answers)
    except StopIteration:
        pass
    else:
        raise AssertionError("CLI did not consume every supplied visibility answer")
    return result, _CliProbeApplication.instances, prompts, output.getvalue()


def test_all_candidates_runs_ordered_fresh_applications_and_summarizes():
    expected = candidates_for_stage("all")
    # The first invalid reply proves each prompt enforces a simple Y/N answer.
    answers = ["not yet", "  y  "] + [
        "Y" if index % 2 else "n"
        for index in range(1, len(expected))
    ]
    result, applications, prompts, output = _run_fake_cli(
        ["--live", "--all-candidates", "--stage", "all"], answers)

    assert result == 0
    assert len(applications) == len(expected)
    assert tuple(app.config.candidate for app in applications) == expected
    assert len({id(app) for app in applications}) == len(applications)
    assert len({id(app.config) for app in applications}) == len(applications)
    assert all(app.run_calls == 1 for app in applications)
    assert applications[0].decision is True
    assert tuple(app.decision for app in applications[1:]) == tuple(
        index % 2 == 1
        for index in range(1, len(expected)))

    assert len(prompts) == len(expected) + 1
    assert "Please answer Y or N" in output
    assert "summary" in output.lower()
    summary_start = output.lower().rfind("summary")
    summary = output[summary_start:]
    for candidate in expected:
        assert candidate.name in summary
    assert "friend_control" in summary


def test_default_sweep_runs_stage_1_2_and_warns_on_a_failed_control():
    expected = candidates_for_stage("1.2")
    result, applications, _prompts, output = _run_fake_cli(
        ["--live", "--all-candidates"], ["n"] * len(expected))

    assert result == 0
    assert tuple(app.config.candidate for app in applications) == expected
    assert applications[-1].config.candidate.name == "friend_control"
    # A silent Friend control invalidates every negative in the same run.
    assert "WARNING" in output and "positive control" in output


def test_all_candidates_derives_unique_jsonl_capture_paths():
    expected = candidates_for_stage("1.2")
    result, applications, _prompts, _output = _run_fake_cli(
        [
            "--live", "--all-candidates",
            "--capture", "joyspot_1.2_sweep.jsonl",
        ],
        ["n"] * len(expected),
    )
    assert result == 0
    assert tuple(app.config.capture_path for app in applications) == tuple(
        f"joyspot_1.2_sweep_{candidate.name}.jsonl"
        for candidate in expected
    )
    assert len({app.config.capture_path for app in applications}) \
        == len(applications)


def test_default_single_candidate_does_not_prompt():
    result, applications, prompts, _output = _run_fake_cli(["--live"])
    assert result == 0
    assert len(applications) == 1
    assert applications[0].config.candidate.name \
        == "wireless_activity21_no_card"
    assert applications[0].config.capture_path is None
    assert applications[0].decision is None
    assert prompts == []


def test_list_candidates_is_offline_and_complete():
    output = io.StringIO()
    with redirect_stdout(output):
        assert joyspot_probe.main(["--list-candidates"]) == 0
    listed = output.getvalue()
    assert [line.split()[1] for line in listed.splitlines()] \
        == list(EXPECTED_CANDIDATES)


def test_probe_config_validates_offline_inputs():
    config = JoySpotProbeConfig(candidate="wireless_activity21_no_card")
    assert config.candidate is _candidate("wireless_activity21_no_card")
    invalid = (
        {"candidate": object()},
        {"candidate": "unknown"},
        {"candidate": "wireless_activity21_no_card", "channel": 0},
        {"candidate": "wireless_activity21_no_card", "channel": 15},
        {"candidate": "wireless_activity21_no_card", "channel": True},
        {"candidate": "wireless_activity21_no_card", "password": "not-bytes"},
        {"candidate": "wireless_activity21_no_card", "phy": ""},
        {"candidate": "wireless_activity21_no_card", "keys_path": ""},
        {"candidate": "wireless_activity21_no_card", "capture_path": b"trace"},
    )
    for values in invalid:
        try:
            JoySpotProbeConfig(**values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid probe config accepted: {values!r}")


class _ProbeNetwork:
    def __init__(self, participants=(), events=None, incoming=()):
        self.participants = list(participants)
        self.events = events
        self.incoming = list(incoming)
        self.started = 0
        self.stopped = 0
        self.waits = 0

    def start(self, preflight=True):
        self.started += 1
        self.preflight = preflight
        return self

    def stop(self):
        self.stopped += 1
        if self.events is not None:
            self.events.append("network.stop")

    def wait_readable(self, timeout):
        self.waits += 1
        raise KeyboardInterrupt

    def recv(self):
        incoming, self.incoming = self.incoming, []
        return incoming


class _ProbeInjector:
    def __init__(self, *, start_error=None, runtime_error=None, events=None):
        self.start_error = start_error
        self.error = runtime_error
        self.events = events
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        if self.start_error is not None:
            raise self.start_error
        return self

    def stop(self):
        self.stopped += 1
        if self.events is not None:
            self.events.append("injector.stop")


class _OfflineProbeApplication(JoySpotProbeApplication):
    def _resolve_phy_and_keys(self):
        return "phy-test", "/keys-test"


def test_probe_runtime_uses_fixed_network_identity_and_cleans_up():
    cleanup_events = []
    network = _ProbeNetwork(
        [("switch",)], events=cleanup_events,
        incoming=[(b"ignored Pia", "169.254.1.2")])
    injector = _ProbeInjector(events=cleanup_events)
    tracer = SimpleNamespace(closed=0, counts={})

    def close_tracer():
        tracer.closed += 1
        cleanup_events.append("tracer.close")

    tracer.close = close_tracer
    transport_calls = []

    def transport_factory(**kwargs):
        transport_calls.append(kwargs)
        return network

    app = _OfflineProbeApplication(
        JoySpotProbeConfig(
            candidate="wireless_activity4_card", channel=6,
            skip_preflight=True,
            skip_encryption=True, accept_decrypted_ccmp=True,
            capture_path="probe.jsonl"),
        DEFAULT_TRAINER,
        log=lambda *unused: None,
        transport_factory=transport_factory,
        injector_factory=lambda **unused: injector,
        tracer_factory=lambda *unused, **kwargs: tracer,
        parent_id_factory=lambda: b"\xbc\xf1",
    )
    assert app.run() is True
    assert (network.started, network.stopped, network.waits) == (1, 1, 1)
    assert (injector.started, injector.stopped) == (1, 1)
    assert tracer.closed == 1
    assert cleanup_events == ["injector.stop", "network.stop", "tracer.close"]
    assert app.ignored_datagrams == 1

    assert len(transport_calls) == 1
    kwargs = transport_calls[0]
    assert kwargs["local_comm_id"] == JOYSPOT_LOCAL_COMMUNICATION_ID
    assert kwargs["max_participants"] == JOYSPOT_MAX_PARTICIPANTS
    assert kwargs["scene_id"] == transport.HostTransport.SCENE_ID
    assert kwargs["app_version"] == 88
    assert kwargs["phyname"] == "phy-test"
    assert kwargs["channel"] == 6
    assert kwargs["skip_encryption"] is True
    assert kwargs["accept_decrypted_ccmp"] is True
    assert network.preflight is False
    assert _record(kwargs["app_data"])[10:12] == b"\xbc\xf1"


def test_probe_decision_prompt_runs_while_candidate_is_live_then_cleans_up():
    cleanup_events = []
    network = _ProbeNetwork(events=cleanup_events)
    injector = _ProbeInjector(events=cleanup_events)
    prompt_calls = []

    def decision_prompt():
        assert network.started == 1
        assert network.stopped == 0
        assert injector.started == 1
        assert injector.stopped == 0
        prompt_calls.append("prompt")
        return True

    app = _OfflineProbeApplication(
        JoySpotProbeConfig(candidate="wireless_activity21_no_card"),
        DEFAULT_TRAINER,
        log=lambda *unused: None,
        transport_factory=lambda **unused: network,
        injector_factory=lambda **unused: injector,
        parent_id_factory=lambda: b"\xbf\xf1",
    )
    assert app.run(decision_prompt=decision_prompt) is False
    assert prompt_calls == ["prompt"]
    assert network.waits == 0
    assert network.stopped == 1
    assert injector.stopped == 1
    assert cleanup_events == ["injector.stop", "network.stop"]


def test_probe_runtime_cleans_up_after_injector_failure():
    for failure_phase in ("start", "runtime"):
        error = RuntimeError("injector failed")
        cleanup_events = []
        network = _ProbeNetwork(events=cleanup_events)
        injector = _ProbeInjector(
            start_error=error if failure_phase == "start" else None,
            runtime_error=error if failure_phase == "runtime" else None,
            events=cleanup_events,
        )
        app = _OfflineProbeApplication(
            JoySpotProbeConfig(candidate="wireless_activity21_no_card"),
            DEFAULT_TRAINER,
            log=lambda *unused: None,
            transport_factory=lambda **unused: network,
            injector_factory=lambda **unused: injector,
            parent_id_factory=lambda: b"\xbd\xf1",
        )
        try:
            app.run()
        except RuntimeError as caught:
            assert "injector" in str(caught)
        else:
            raise AssertionError("injector failure was swallowed")
        assert network.stopped == 1
        assert injector.stopped == 1
        assert cleanup_events == ["injector.stop", "network.stop"]


def test_probe_construction_failure_closes_created_trace():
    tracer = SimpleNamespace(closed=0, counts={})
    tracer.close = lambda: setattr(tracer, "closed", tracer.closed + 1)

    def fail_transport(**unused):
        raise RuntimeError("transport construction failed")

    app = _OfflineProbeApplication(
        JoySpotProbeConfig(
            candidate="wireless_activity21_no_card",
            capture_path="probe.jsonl"),
        DEFAULT_TRAINER,
        log=lambda *unused: None,
        transport_factory=fail_transport,
        tracer_factory=lambda *unused, **kwargs: tracer,
        parent_id_factory=lambda: b"\xbe\xf1",
    )
    try:
        app.run()
    except RuntimeError as error:
        assert "construction" in str(error)
    else:
        raise AssertionError("transport construction failure was swallowed")
    assert tracer.closed == 1
    assert app.network is None and app.injector is None


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("JoySpot discovery tests: OK")
