"""CLI wiring tests for layered host TOML configuration and adapter selection."""

from contextlib import redirect_stdout
from pathlib import Path
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import frlgmg_host
import frlgtrade_host
from frlgsim import config, host_cli, transport
from frlgsim.host_app import HostApplication


def _write(path, contents):
    path.write_text(contents, encoding="utf-8")
    return path


def test_cli_config_path_uses_sibling_local_layer_and_no_local_disables_it():
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        shared = _write(directory / "host.toml", """
[host]
live = false
skip_encryption = false
accept_decrypted_ccmp = false

[ldn]
phy = "phy8"
""")
        _write(directory / "host.local.toml", """
[host]
live = true
skip_encryption = true
""")
        loaded, shared_path, local_path = host_cli.load_host_file_config_from_argv(
            ["--config", str(shared)])
        assert shared_path == shared
        assert local_path == directory / "host.local.toml"
        assert (loaded.live, loaded.skip_encryption,
                loaded.accept_decrypted_ccmp, loaded.phy) == (True, True, False, "phy8")

        no_local, _shared, no_local_path = host_cli.load_host_file_config_from_argv(
            ["--config", str(shared), "--no-local-config"])
        assert no_local_path is None
        assert (no_local.live, no_local.skip_encryption) == (False, False)

        parser = frlgmg_host.build_parser(no_local)
        assert parser.parse_args([]).live is False
        assert parser.parse_args(["--live"]).live is True
        assert parser.parse_args(["--live", "--no-live"]).live is False


def test_mystery_gift_no_flag_profile_and_cli_boolean_overrides_are_effective():
    parser = frlgmg_host.build_parser()
    args = parser.parse_args([])
    run = frlgmg_host.build_run_config(parser, args)
    assert args.live is True
    assert run.role.skip_encryption is True
    assert run.role.accept_decrypted_ccmp is True

    args = parser.parse_args([
        "--no-live", "--no-skip-encryption", "--no-accept-decrypted-ccmp"])
    assert (args.live, args.skip_encryption, args.accept_decrypted_ccmp) == (
        False, False, False)


def test_print_effective_config_is_safe_and_requires_no_root_or_party_files():
    output = io.StringIO()
    with redirect_stdout(output):
        assert frlgmg_host.main([
            "--keys", "/private/pi/prod.keys", "--password", "deadbeef",
            "--print-effective-config"]) == 0
    rendered = output.getvalue()
    assert "live = true" in rendered
    assert "skip_encryption = true" in rendered
    assert "accept_decrypted_ccmp = true" in rendered
    assert 'keys_path = "<redacted>"' in rendered
    assert 'password = "<redacted>"' in rendered
    assert "/private/pi/prod.keys" not in rendered

    output = io.StringIO()
    with redirect_stdout(output):
        assert frlgtrade_host.main(["--print-effective-config"]) == 0
    assert "adapter = \"tplink-archer-t3u\"" in output.getvalue()


def test_print_effective_config_validates_transport_options():
    for argv, expected in (
            (["--print-effective-config", "--comm-id", "not-hex"],
             "--comm-id must be a hexadecimal integer"),
            (["--print-effective-config", "--adapter", ""],
             "adapter must be a non-empty string")):
        try:
            frlgmg_host.main(argv)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("invalid --print-effective-config input was accepted")


def test_adapter_profile_resolves_exactly_one_physical_tplink(monkeypatch=None):
    # Avoid adding a test-framework dependency: temporarily replace the
    # diagnostic seam directly, as the standalone test scripts do elsewhere.
    old_describe = transport.describe_phys
    try:
        transport.describe_phys = lambda: [
            ("phy0", "brcmfmac", None),
            ("phy3", "rtw88_8822bu", "2357:012d"),
        ]
        logs = []
        assert transport.find_adapter_phy("tplink-archer-t3u", log=logs.append) == "phy3"
        assert "phy3" in logs[0]

        transport.describe_phys = lambda: [
            ("phy0", "brcmfmac", None),
        ]
        try:
            transport.find_adapter_phy("tplink-archer-t3u")
        except RuntimeError as exc:
            assert "was not found" in str(exc)
            assert "--phy phyN" in str(exc)
        else:
            raise AssertionError("missing TP-Link adapter was accepted")

        transport.describe_phys = lambda: [
            ("phy1", "rtw88_8822bu", "2357:012d"),
            ("phy2", "rtw88_8822bu", "2357:012d"),
        ]
        try:
            transport.find_adapter_phy("tplink-archer-t3u")
        except RuntimeError as exc:
            assert "ambiguous" in str(exc)
        else:
            raise AssertionError("ambiguous TP-Link adapters were accepted")
    finally:
        transport.describe_phys = old_describe


def test_explicit_phy_wins_over_the_named_adapter_profile():
    run = config.TradeRunConfig(
        profile=config.DEFAULT_TRAINER,
        plan=config.TradePlan(
            party_paths=("one.pk3",), trade_slot=0, offered_slots=(0,)),
        ldn=config.LdnConfig(
            phy="phy9", adapter="tplink-archer-t3u", keys_path=__file__),
        role=config.HostOptions(),
    )
    app = HostApplication(run, log=lambda *parts: None)
    old_find = transport.find_adapter_phy
    try:
        transport.find_adapter_phy = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("named adapter lookup should not run for explicit --phy"))
        phy, keys = app._resolve_phy_and_keys()
    finally:
        transport.find_adapter_phy = old_find
    assert phy == "phy9"
    assert keys == __file__


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("Host CLI TOML wiring tests: OK")
