"""Shared host CLI, Mystery Gift config, and Gate 1 fixture regressions."""

from contextlib import redirect_stderr
from dataclasses import FrozenInstanceError
import hashlib
import io
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frlgmg_host
import frlgtrade_host
from frlgsim import beacon, charmap, config, linkplayer, mg_script, transport
from frlgsim.host_beacon import build_wonder_card_app_data
from frlgsim.host_mg_app import MysteryGiftHostApplication
from frlgsim.host_mystery_gift import HostMysteryGiftEngine
from frlgsim.host_pia import HostPeerProtocol


SESSION_ID = b"\x7b\xf1"


def _build_mg(argv):
    parser = frlgmg_host.build_parser()
    return frlgmg_host.build_run_config(parser, parser.parse_args(argv))


def _build_trade(argv):
    parser = frlgtrade_host.build_parser()
    return frlgtrade_host.build_run_config(parser, parser.parse_args(argv))


def _record(app_data):
    return transport._b85_decode(app_data[beacon.PIA_HDR:])[:beacon.RECORD_SIZE]


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def test_mystery_gift_models_are_immutable_and_composed():
    payload = config.MysteryGiftPayload()
    run = config.MysteryGiftRunConfig(payload=payload)
    assert run.profile is config.DEFAULT_TRAINER
    assert run.payload is payload
    assert isinstance(run.ldn, config.LdnConfig)
    assert isinstance(run.role, config.HostOptions)
    for obj, attribute, value in (
            (payload, "flag_id", 1004),
            (run, "trust_pia", False)):
        try:
            setattr(obj, attribute, value)
        except FrozenInstanceError:
            continue
        raise AssertionError(f"{type(obj).__name__} accepted mutation")


def test_flag_validation_is_centralized_in_the_payload():
    assert config.MysteryGiftPayload(flag_id=1000).receipt_flag == 0x2A7
    assert config.MysteryGiftPayload(flag_id=1019).receipt_flag == 0x2BA
    for bad in (999, 1020, -1):
        try:
            config.MysteryGiftPayload(flag_id=bad)
        except ValueError as exc:
            assert "flagId" in str(exc)
        else:
            raise AssertionError(f"invalid flag id accepted: {bad}")


def test_both_host_clis_use_the_same_explicit_transport_parsing():
    common = [
        "--live", "--ot", "MGHOST", "--version", "firered",
        "--id=12345:34567", "--password", "a1b2", "--phy", "phy7",
        "--keys", "/keys", "--comm-id", "01006fa0233f8000",
        "--capture", "trace.jsonl", "--channel", "6", "--scene", "1234",
        "--max-participants", "7", "--skip-preflight", "--skip-encryption",
        "--accept-decrypted-ccmp",
        "--native-nonce-sequence", "--session-response-first",
    ]
    gift = _build_mg(common)
    trade = _build_trade(common + ["one.pk3", "two.pk3"])
    assert gift.profile == trade.profile
    assert gift.ldn == trade.ldn
    assert gift.role == trade.role
    assert gift.role.accept_decrypted_ccmp is True
    assert gift.profile.trainer_id == (34567 << 16) | 12345


def test_role_defaults_use_the_checked_in_tp_link_profile():
    gift = _build_mg(["--live"])
    trade = _build_trade(["--live", "one.pk3", "two.pk3"])
    assert (gift.role.skip_encryption,
            gift.role.native_nonce_sequence,
            gift.role.session_response_first) == (True, True, True)
    assert (trade.role.skip_encryption,
            trade.role.native_nonce_sequence,
            trade.role.session_response_first) == (True, True, True)
    assert gift.role.accept_decrypted_ccmp is True
    assert trade.role.accept_decrypted_ccmp is True
    assert gift.ldn.phy == trade.ldn.phy == "auto"


def test_shared_host_parser_rejects_bad_hex_values():
    for argv in (["--live", "--password", "xyz"],
                 ["--live", "--comm-id", "not-hex"]):
        parser = frlgmg_host.build_parser()
        args = parser.parse_args(argv)
        try:
            with redirect_stderr(io.StringIO()):
                frlgmg_host.build_run_config(parser, args)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"invalid host option accepted: {argv}")


def test_overridden_profile_reaches_every_host_identity_surface():
    run = _build_mg([
        "--live", "--ot", "MGHOST", "--version", "firered",
        "--id=12345:34567", "--flag-id", "1004",
    ])
    profile = run.profile
    assert profile.trainer_id == (34567 << 16) | 12345
    assert profile.progress_flags == 0x11

    inactive, _active = build_wonder_card_app_data(profile, SESSION_ID)
    record = _record(inactive)
    search_word = int.from_bytes(
        record[beacon.SEARCH_WORD_OFFSET:beacon.SEARCH_WORD_OFFSET + 2], "little")
    assert int.from_bytes(record[0:2], "little") == profile.tid
    assert record[2:10] == charmap.encode(
        profile.name, width=8, pad=0xFF)
    assert ((search_word & beacon.SEARCH_VERSION_MASK)
            >> beacon.SEARCH_VERSION_SHIFT) == (linkplayer.VERSION_FIRE_RED & 0x7)
    assert ((search_word & beacon.SEARCH_LANGUAGE_MASK)
            >> beacon.SEARCH_LANGUAGE_SHIFT) == linkplayer.LANGUAGE_ENGLISH
    assert beacon.decode_pia_header(inactive)["nickname"] == profile.name

    rfu_game_data = profile.build_rfu_game_data(
        beacon.ACTIVITY_WONDER_CARD, started=False)
    assert int.from_bytes(rfu_game_data[4:6], "little") == profile.tid
    assert rfu_game_data[17:26] == charmap.encode(
        profile.name, width=9, pad=0x00)

    card, script = run.payload.build()
    engine = HostMysteryGiftEngine(
        card, script, link_player=profile.to_link_player())
    assert engine.lp.name == profile.name
    assert engine.lp.trainer_id == profile.trainer_id
    assert engine.lp.progress_flags == engine.lp.progress_flags_copy == 0x11
    assert engine._link_player_block[16:44] == profile.to_link_player().pack(
        name_pad=linkplayer.HOST_NAME_PAD)

    peer = HostPeerProtocol(
        SimpleNamespace(), profile, SimpleNamespace(), inactive)
    assert peer.profile.session_name == profile.name

    logs = []
    app = MysteryGiftHostApplication.__new__(MysteryGiftHostApplication)
    app.config = run
    app.profile = profile
    app.session = SimpleNamespace(rfu=SimpleNamespace(host_session_id=SESSION_ID))
    app.card, app.ram_script, app.info = card, script, logs.append
    app._log_identity(profile.to_link_player())
    assert any("OT='MGHOST'" in line for line in logs)
    assert any("TID=0x3039" in line and "SID=0x8707" in line for line in logs)
    assert any("flagId 1004" in line for line in logs)


def test_gate_1_serialized_fixtures_are_byte_identical():
    card, script = config.MysteryGiftPayload().build()
    inactive, active = build_wonder_card_app_data(config.DEFAULT_TRAINER, SESSION_ID)
    assert (len(card), _sha256(card)) == (
        332, "059aa3d21001787a0fdde5336f70b60e4218bc6c9a8f1467c258470eaebae87c")
    assert (len(script), _sha256(script)) == (
        251, "e8d48201cbffea57bba27e65fa91464da0949e5f8fb0e230424ea7661c898a33")
    assert _sha256(inactive) == "d3e5723cab5472a2d60cc3e8d98feec7af49ed0b8df55b73340bd9db52bbcee3"
    assert _sha256(active) == "bfccd957834fbb0728a367f02f382defdd2180dd93cfad474dde8e5cd9cebb42"
    assert _sha256(mg_script.CLIENT_SCRIPT_SEND_GAME_DATA) \
        == "9ae8de594f9c19e473ace3b34816f337fea3e60f9c9ac64cfb37d87b610d50de"
    assert _sha256(mg_script.CLIENT_SCRIPT_SAVE_CARD) \
        == "64a123dc7732ae4ee506aaa55154e36b563e0af4d68d67f3c152fa5739c5176e"


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("Mystery Gift shared configuration tests: OK")
