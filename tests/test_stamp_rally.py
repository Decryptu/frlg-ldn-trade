"""Offline coverage for the two live-host Stamp Rally distributions."""

from dataclasses import FrozenInstanceError
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import frlgmg_host  # noqa: E402
from frlgsim import charmap, config, mg_script, mg_server, mystery_gift, stamp_rally, wonder_card  # noqa: E402
from test_mystery_gift_flow import ConsoleClientModel, _drive, _game_data  # noqa: E402
from test_mystery_gift_end_to_end import _run_full_stack  # noqa: E402


def _metadata(stamps=(), *, icon=stamp_rally.SPECIES_CLAYDOL, max_stamps=2,
              flag_id=stamp_rally.STAMP_RALLY_FLAG_ID):
    return _game_data(
        flag_id=flag_id, max_stamps=max_stamps,
        metadata_icon=icon, stamps=stamps)


def _run_server(distribution, game_data, *, toss_response=0):
    server = mg_server.MysteryGiftServer(
        distribution.card, distribution.ram_script,
        stamp=distribution.stamp,
        activation_script=distribution.activation_script,
        install_activation_script=distribution.install_activation_script)
    sent = []
    for _ in range(64):
        action = server.run()
        if action[0] == "done":
            return server, sent, action[1]
        if action[0] == "send":
            sent.append((action[1], action[2]))
            server.on_sent()
        elif action[1] == mystery_gift.MG_LINKID_GAME_DATA:
            server.on_received(action[1], game_data)
        elif action[1] == mystery_gift.MG_LINKID_RESPONSE:
            server.on_received(action[1], toss_response.to_bytes(4, "little"))
        else:
            server.on_received(action[1], b"\x00" * 1024)
    raise AssertionError("stamp server did not terminate")


def test_shared_card_layout_and_stamp_encodings_are_exact():
    solrock = stamp_rally.build_solrock_stamp_event()
    lunatone = stamp_rally.build_lunatone_stamp_event()
    assert solrock.card == lunatone.card
    card = solrock.card
    assert len(card) == wonder_card.WONDER_CARD_SIZE
    assert int.from_bytes(card[0:2], "little") == 1006
    assert int.from_bytes(card[2:4], "little") == stamp_rally.SPECIES_CLAYDOL
    assert int.from_bytes(card[4:8], "little") == 6
    assert card[8] & 0x3 == mystery_gift.CARD_TYPE_STAMP
    assert card[9] == 2
    assert charmap.decode(card[10:50]) == "SUN AND MOON RALLY"
    assert charmap.decode(card[50:90]) == "Collect both stamps!"
    assert [charmap.decode(card[offset:offset + 40])
            for offset in range(90, 250, 40)] == [
                "Collect SOLROCK and LUNATONE",
                "stamps from event hosts.",
                "Claim each Pokemon, then",
                "receive a special grand prize!",
            ]
    assert solrock.stamp == bytes.fromhex("5d010100")
    assert lunatone.stamp == bytes.fromhex("5c010200")
    assert mystery_gift.crc16(card) == 0x2FE9


def test_hardware_one_solrock_stamp_payload_matches_without_tossing_card():
    """Regression from lunatone-stamp.jsonl after collecting Solrock.

    agbcc aligns WonderCardMetadata to 0x20; treating the struct as packed read
    icon/maxStamps as zero and incorrectly entered the destructive toss flow.
    """
    raw = bytes.fromhex(
        "0101000001000000010000000100000002000000ee0309020b1430102a100000"
        "0000000000003f015d010000000000000000000000000100000000000000000000"
        "00000002c1ccbfbfc8ff0050108b1a290a20100e02330a00000000425047450a000000")
    assert len(raw) == mg_script.GAME_DATA_SIZE == 0x64
    parsed = mg_script.parse_link_game_data(raw)
    assert parsed.flag_id == 1006
    assert parsed.max_stamps == 2
    assert parsed.metadata_icon_species == stamp_rally.SPECIES_CLAYDOL
    assert parsed.stamps == ((stamp_rally.SPECIES_SOLROCK, 1),)
    assert parsed.player_name == "GREEN"

    distribution = stamp_rally.build_lunatone_stamp_event()
    server, sent, result = _run_server(distribution, raw)
    assert result == mg_server.SVR_MSG_STAMP_SENT
    assert ("rally_card", mg_script.HAS_SAME_CARD) in server.trace
    assert mystery_gift.MG_LINKID_CARD not in [ident for ident, _ in sent]
    assert [ident for ident, _ in sent][-2:] == [
        mystery_gift.MG_LINKID_STAMP,
        mystery_gift.MG_LINKID_RAM_SCRIPT,
    ]


def test_distribution_and_payload_models_are_immutable_with_role_specific_defaults():
    normal = config.MysteryGiftPayload(gift=wonder_card.GIFT_CELEBI)
    solrock = config.MysteryGiftPayload(gift=stamp_rally.GIFT_SOLROCK_STAMP)
    lunatone = config.MysteryGiftPayload(gift=stamp_rally.GIFT_LUNATONE_STAMP,
                                        flag_id=1008)
    assert normal.flag_id == 1003
    assert solrock.flag_id == 1006
    assert lunatone.flag_id == 1008
    distribution = solrock.build_distribution()
    assert distribution.is_stamp
    for obj, name, value in ((solrock, "flag_id", 1007),
                             (distribution, "stamp", b"bad")):
        try:
            setattr(obj, name, value)
        except FrozenInstanceError:
            pass
        else:
            raise AssertionError(f"{type(obj).__name__} accepted mutation")


def test_live_cli_adds_stamp_choices_and_dynamic_flag_default_only():
    parser = frlgmg_host.build_parser()
    sol = frlgmg_host.build_run_config(
        parser, parser.parse_args(["--live", "--gift", "solrock-stamp"]))
    luna = frlgmg_host.build_run_config(
        parser, parser.parse_args([
            "--live", "--gift", "lunatone-stamp", "--flag-id", "1009"]))
    assert sol.payload.flag_id == 1006
    assert luna.payload.flag_id == 1009
    explicit_legacy = frlgmg_host.build_run_config(
        parser, parser.parse_args([
            "--live", "--gift", "solrock-stamp", "--flag-id", "1003"]))
    assert explicit_legacy.payload.flag_id == 1003
    assert wonder_card.GIFT_CHOICES == ("beast-cutscene", "celebi")


def test_activation_wrappers_modify_only_the_intended_state():
    receipt = wonder_card.flag_for_flag_id(1006)
    ordinary = stamp_rally.build_stamp_activation_script(
        stamp_rally.VAR_MYSTERY_GIFT_1, flag_id=1006)
    install = stamp_rally.build_stamp_activation_script(
        stamp_rally.VAR_MYSTERY_GIFT_2, flag_id=1006, install=True)
    assert ordinary == (bytes.fromhex("05060000000216")
                        + stamp_rally.VAR_MYSTERY_GIFT_1.to_bytes(2, "little")
                        + bytes.fromhex("010002"))
    assert install == (bytes.fromhex("0506000000022a")
                       + receipt.to_bytes(2, "little")
                       + bytes.fromhex("16")
                       + stamp_rally.VAR_MYSTERY_GIFT_2.to_bytes(2, "little")
                       + bytes.fromhex("010002"))
    assert receipt.to_bytes(2, "little") not in ordinary


def test_server_installs_card_script_stamp_then_activation_when_no_card():
    distribution = stamp_rally.build_solrock_stamp_event()
    _server, sent, result = _run_server(distribution, _game_data())
    assert result == mg_server.SVR_MSG_STAMP_SENT
    assert [ident for ident, _payload in sent] == [
        mystery_gift.MG_LINKID_CLIENT_SCRIPT,
        mystery_gift.MG_LINKID_CLIENT_SCRIPT,
        mystery_gift.MG_LINKID_CARD,
        mystery_gift.MG_LINKID_RAM_SCRIPT,
        mystery_gift.MG_LINKID_STAMP,
        mystery_gift.MG_LINKID_RAM_SCRIPT,
    ]
    assert sent[-2][1] == distribution.stamp
    assert sent[-1][1] == distribution.install_activation_script


def test_server_appends_stamp_to_matching_claydol_card_in_either_order():
    cases = (
        (stamp_rally.build_solrock_stamp_event(),
         ((stamp_rally.SPECIES_LUNATONE, stamp_rally.LUNATONE_STAMP_ID),)),
        (stamp_rally.build_lunatone_stamp_event(),
         ((stamp_rally.SPECIES_SOLROCK, stamp_rally.SOLROCK_STAMP_ID),)),
    )
    for distribution, existing in cases:
        _server, sent, result = _run_server(distribution, _metadata(existing))
        assert result == mg_server.SVR_MSG_STAMP_SENT
        assert [ident for ident, _payload in sent] == [
            mystery_gift.MG_LINKID_CLIENT_SCRIPT,
            mystery_gift.MG_LINKID_CLIENT_SCRIPT,
            mystery_gift.MG_LINKID_STAMP,
            mystery_gift.MG_LINKID_RAM_SCRIPT,
        ]
        assert sent[-1][1] == distribution.activation_script


def test_server_treats_same_flag_with_wrong_identity_as_a_different_card():
    distribution = stamp_rally.build_solrock_stamp_event()
    for data in (
            _metadata(flag_id=1005),
            _metadata(icon=stamp_rally.SPECIES_SOLROCK),
            _metadata(max_stamps=1)):
        _server, sent, result = _run_server(
            distribution, data, toss_response=1)
        assert result == mg_server.SVR_MSG_CLIENT_CANCELED
        assert mystery_gift.MG_LINKID_STAMP not in [i for i, _ in sent]

        _server, sent, result = _run_server(
            distribution, data, toss_response=0)
        assert result == mg_server.SVR_MSG_STAMP_SENT
        assert mystery_gift.MG_LINKID_CARD in [i for i, _ in sent]


def test_server_duplicate_and_full_branches_never_send_activation():
    solrock = stamp_rally.build_solrock_stamp_event()
    duplicate_cases = (
        ((stamp_rally.SPECIES_SOLROCK, 77),),
        ((10, stamp_rally.SOLROCK_STAMP_ID),),
        ((stamp_rally.SPECIES_SOLROCK, stamp_rally.SOLROCK_STAMP_ID),
         (stamp_rally.SPECIES_LUNATONE, stamp_rally.LUNATONE_STAMP_ID)),
    )
    for stamps in duplicate_cases:
        _server, sent, result = _run_server(solrock, _metadata(stamps))
        assert result == mg_server.SVR_MSG_HAS_STAMP
        assert mystery_gift.MG_LINKID_STAMP not in [i for i, _ in sent]
    _server, sent, result = _run_server(solrock, _metadata(((1, 10), (2, 11))))
    assert result == mg_server.SVR_MSG_NO_ROOM_STAMPS
    assert mystery_gift.MG_LINKID_RAM_SCRIPT not in [i for i, _ in sent]


def test_console_model_installs_card_stamp_and_immediate_eligibility():
    distribution = stamp_rally.build_solrock_stamp_event()
    console = ConsoleClientModel(flag_id=0)
    receipt = wonder_card.flag_for_flag_id(1006)
    console.flags.add(receipt)
    console.flags.add(stamp_rally.FLAG_MYSTERY_GIFT_DONE)
    console.vars[stamp_rally.VAR_MYSTERY_GIFT_1] = stamp_rally.STAMP_RECEIVED
    console.vars[stamp_rally.VAR_MYSTERY_GIFT_2] = stamp_rally.STAMP_RECEIVED
    engine, _frames = _drive(console, distribution=distribution, max_frames=7000)
    assert engine.result == mg_server.SVR_MSG_STAMP_SENT
    assert console.saved_card == distribution.card
    assert console.metadata_icon == stamp_rally.SPECIES_CLAYDOL
    assert console.saved_ram_script.startswith(distribution.ram_script)
    assert console.stamps == [(stamp_rally.SPECIES_SOLROCK, 1)]
    assert console.vars == {
        stamp_rally.VAR_MYSTERY_GIFT_1: stamp_rally.STAMP_ELIGIBLE,
        stamp_rally.VAR_MYSTERY_GIFT_2: stamp_rally.STAMP_ABSENT,
    }
    assert stamp_rally.FLAG_MYSTERY_GIFT_DONE not in console.flags
    assert receipt not in console.flags


def test_console_model_existing_card_preserves_first_reward_and_activates_second():
    distribution = stamp_rally.build_lunatone_stamp_event()
    console = ConsoleClientModel(
        flag_id=1006, max_stamps=2, metadata_icon=stamp_rally.SPECIES_CLAYDOL,
        stamps=((stamp_rally.SPECIES_SOLROCK, 1),))
    console.vars[stamp_rally.VAR_MYSTERY_GIFT_1] = stamp_rally.STAMP_RECEIVED
    engine, _frames = _drive(console, distribution=distribution, max_frames=7000)
    assert engine.result == mg_server.SVR_MSG_STAMP_SENT
    assert console.saved_card is None
    assert console.stamps[-1] == (stamp_rally.SPECIES_LUNATONE, 2)
    assert console.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == stamp_rally.STAMP_RECEIVED
    assert console.vars[stamp_rally.VAR_MYSTERY_GIFT_2] == stamp_rally.STAMP_ELIGIBLE


def test_both_stamp_events_survive_the_impaired_reliable_rfu_stack():
    solrock = stamp_rally.build_solrock_stamp_event()
    sol_run = _run_full_stack(payload=solrock, max_ms=9000)
    assert sol_run.engine.result == mg_server.SVR_MSG_STAMP_SENT
    assert sol_run.console.result == mg_script.CLI_MSG_STAMP_RECEIVED
    assert sol_run.console.stamps == [(stamp_rally.SPECIES_SOLROCK, 1)]
    assert sol_run.console.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == 1

    luna_console = ConsoleClientModel(
        flag_id=1006, max_stamps=2, metadata_icon=stamp_rally.SPECIES_CLAYDOL,
        stamps=((stamp_rally.SPECIES_SOLROCK, 1),))
    luna_run = _run_full_stack(
        payload=stamp_rally.build_lunatone_stamp_event(),
        console=luna_console, max_ms=9000)
    assert luna_run.engine.result == mg_server.SVR_MSG_STAMP_SENT
    assert luna_run.console.result == mg_script.CLI_MSG_STAMP_RECEIVED
    assert luna_run.console.stamps == [
        (stamp_rally.SPECIES_SOLROCK, 1),
        (stamp_rally.SPECIES_LUNATONE, 2),
    ]
    assert luna_run.console.dropped_inits == luna_run.console.dropped_fragments == 0
    assert luna_run.radio.dropped and luna_run.radio.duplicated


class _DeliveryModel:
    CONDITIONS = {
        0: lambda result: result < 0,
        1: lambda result: result == 0,
        2: lambda result: result > 0,
        3: lambda result: result <= 0,
        4: lambda result: result >= 0,
        5: lambda result: result != 0,
    }

    def __init__(self, script, *, solrock=0, lunatone=0, done=False,
                 outcomes=()):
        self.script = script
        self.vars = {
            stamp_rally.VAR_MYSTERY_GIFT_1: solrock,
            stamp_rally.VAR_MYSTERY_GIFT_2: lunatone,
            0x800D: 0,
        }
        self.flags = ({stamp_rally.FLAG_MYSTERY_GIFT_DONE} if done else set())
        self.outcomes = list(outcomes)
        self.given = []
        self.messages = []
        self.comparison = 0
        self.pc = 0

    def u16(self):
        value = int.from_bytes(self.script[self.pc:self.pc + 2], "little")
        self.pc += 2
        return value

    def u32(self):
        value = int.from_bytes(self.script[self.pc:self.pc + 4], "little")
        self.pc += 4
        return value

    def jump(self, address):
        self.pc = address - 0x08000000

    def run(self):
        for _ in range(500):
            opcode = self.script[self.pc]
            self.pc += 1
            if opcode in (0x6A, 0x5A, 0x66, 0x6D, 0x6C):
                continue
            if opcode == 0xB8:
                assert self.u32() == 0x08000000
            elif opcode == 0x2B:
                self.comparison = 0 if self.u16() in self.flags else -1
            elif opcode == 0x21:
                actual, expected = self.vars.get(self.u16(), 0), self.u16()
                self.comparison = (actual > expected) - (actual < expected)
            elif opcode == 0xBB:
                condition, address = self.script[self.pc], int.from_bytes(
                    self.script[self.pc + 1:self.pc + 5], "little")
                self.pc += 5
                if self.CONDITIONS[condition](self.comparison):
                    self.jump(address)
            elif opcode == 0xB9:
                self.jump(self.u32())
            elif opcode == 0xBD:
                self.messages.append(self.u32() - 0x08000000)
            elif opcode == 0x79:
                species = self.u16()
                level = self.script[self.pc]
                self.pc += 1 + 2 + 9
                result = self.outcomes.pop(0) if self.outcomes else 0
                self.vars[0x800D] = result
                if result != stamp_rally.MON_CANT_GIVE:
                    self.given.append((species, level))
            elif opcode == 0x16:
                variable, value = self.u16(), self.u16()
                self.vars[variable] = value
            elif opcode == 0x29:
                self.flags.add(self.u16())
            elif opcode == 0x02:
                return self
            else:
                raise AssertionError(f"unhandled delivery opcode {opcode:#x} at {self.pc - 1}")
        raise AssertionError("delivery script did not terminate")


def _delivery(*, solrock=0, lunatone=0, done=False, outcomes=()):
    return _DeliveryModel(
        stamp_rally.build_stamp_rally_delivery_script(),
        solrock=solrock, lunatone=lunatone, done=done,
        outcomes=outcomes).run()


def test_delivery_script_handles_every_saved_state_without_duplicate_rewards():
    receipt = wonder_card.flag_for_flag_id(1006)
    for solrock in range(3):
        for lunatone in range(3):
            completed = _delivery(solrock=solrock, lunatone=lunatone, done=True)
            assert completed.given == []
            assert receipt in completed.flags

    expected = {
        (0, 0): [],
        (0, 1): [(stamp_rally.SPECIES_LUNATONE, 30)],
        (0, 2): [],
        (1, 0): [(stamp_rally.SPECIES_SOLROCK, 30)],
        (1, 1): [(stamp_rally.SPECIES_SOLROCK, 30),
                 (stamp_rally.SPECIES_LUNATONE, 30),
                 (wonder_card.SPECIES_CELEBI, 50)],
        (1, 2): [(stamp_rally.SPECIES_SOLROCK, 30),
                 (wonder_card.SPECIES_CELEBI, 50)],
        (2, 0): [],
        (2, 1): [(stamp_rally.SPECIES_LUNATONE, 30),
                 (wonder_card.SPECIES_CELEBI, 50)],
        (2, 2): [(wonder_card.SPECIES_CELEBI, 50)],
    }
    for states, rewards in expected.items():
        assert _delivery(solrock=states[0], lunatone=states[1]).given == rewards

    both = _delivery(solrock=1, lunatone=1)
    assert both.given == [
        (stamp_rally.SPECIES_SOLROCK, 30),
        (stamp_rally.SPECIES_LUNATONE, 30),
        (wonder_card.SPECIES_CELEBI, 50),
    ]
    assert both.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == 2
    assert both.vars[stamp_rally.VAR_MYSTERY_GIFT_2] == 2
    assert stamp_rally.FLAG_MYSTERY_GIFT_DONE in both.flags
    assert receipt in both.flags

    sol_only = _delivery(solrock=1)
    luna_only = _delivery(lunatone=1)
    assert sol_only.given == [(stamp_rally.SPECIES_SOLROCK, 30)]
    assert luna_only.given == [(stamp_rally.SPECIES_LUNATONE, 30)]
    assert stamp_rally.FLAG_MYSTERY_GIFT_DONE not in sol_only.flags | luna_only.flags

    grand_prize = _delivery(solrock=2, lunatone=2)
    assert grand_prize.given == [(wonder_card.SPECIES_CELEBI, 50)]


def test_delivery_script_preserves_retry_state_at_each_storage_failure():
    sol_fail = _delivery(solrock=1, lunatone=1, outcomes=(2,))
    assert sol_fail.given == []
    assert sol_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == 1
    assert sol_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_2] == 1

    luna_fail = _delivery(solrock=1, lunatone=1, outcomes=(0, 2))
    assert luna_fail.given == [(stamp_rally.SPECIES_SOLROCK, 30)]
    assert luna_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == 2
    assert luna_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_2] == 1

    celebi_fail = _delivery(solrock=1, lunatone=1, outcomes=(0, 1, 2))
    assert celebi_fail.given == [
        (stamp_rally.SPECIES_SOLROCK, 30),
        (stamp_rally.SPECIES_LUNATONE, 30),
    ]
    assert celebi_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_1] == 2
    assert celebi_fail.vars[stamp_rally.VAR_MYSTERY_GIFT_2] == 2
    assert stamp_rally.FLAG_MYSTERY_GIFT_DONE not in celebi_fail.flags
    assert wonder_card.flag_for_flag_id(1006) not in celebi_fail.flags


def test_delivery_script_contains_dialogue_for_every_outcome_and_fits_the_save():
    script = stamp_rally.build_stamp_rally_delivery_script()
    assert len(script) == 820 and len(script) <= mg_server.MysteryGiftServer.MAX_RAM_SCRIPT_SIZE
    for text in (
            "Your SOLROCK STAMP checks out!",
            "Your LUNATONE STAMP checks out!",
            "Both STAMP rewards are yours!",
            "Congratulations! CELEBI is yours!",
            "SOLROCK is yours!",
            "LUNATONE is yours!",
            "Welcome to the STAMP RALLY!",
            "You completed the STAMP RALLY!",
            "Your party and PC BOXES are full."):
        assert charmap.encode(text) in script


if __name__ == "__main__":
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failures = 0
    for name, test in tests:
        try:
            test()
            print("ok   ", name)
        except Exception as exc:
            failures += 1
            print("FAIL ", name, f"{type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    raise SystemExit(bool(failures))
