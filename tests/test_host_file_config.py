"""Regression tests for the strict layered host TOML configuration."""

from pathlib import Path
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import config


def _write(directory, name, contents):
    path = Path(directory) / name
    path.write_text(contents, encoding="utf-8")
    return path


def _raises(callable_, text):
    try:
        callable_()
    except ValueError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError(f"expected ValueError containing {text!r}")


def test_tracked_host_profile_is_the_tp_link_live_default():
    loaded = config.load_project_host_file_config()
    assert loaded.live is True
    assert loaded.adapter == "tplink-archer-t3u"
    assert loaded.skip_encryption is True
    assert loaded.accept_decrypted_ccmp is False
    assert loaded.native_nonce_sequence is True
    assert loaded.session_response_first is True
    assert loaded.phy == "auto"
    assert loaded.to_host_options() == config.HostOptions(
        skip_encryption=True,
        accept_decrypted_ccmp=False,
        native_nonce_sequence=True,
        session_response_first=True,
    )


def test_layering_is_builtins_then_shared_then_local_then_overrides():
    with tempfile.TemporaryDirectory() as directory:
        shared = _write(directory, "host.toml", """
[host]
channel = 6
skip_encryption = false

[ldn]
phy = "phy7"
keys_path = "/shared/keys"
""")
        local = _write(directory, "host.local.toml", """
[host]
skip_encryption = true
accept_decrypted_ccmp = false

[ldn]
keys_path = "/local/keys"
""")
        loaded = config.load_host_file_config(
            shared,
            local_path=local,
            overrides={
                "host": {"channel": 11, "accept_decrypted_ccmp": True},
                "ldn": {"capture_path": "/tmp/ldn.jsonl"},
            },
        )
    assert loaded.channel == 11
    assert loaded.skip_encryption is True
    assert loaded.accept_decrypted_ccmp is True
    assert loaded.phy == "phy7"
    assert loaded.keys_path == "/local/keys"
    assert loaded.capture_path == "/tmp/ldn.jsonl"
    assert loaded.live is True  # inherited built-in


def test_missing_optional_local_config_is_accepted():
    with tempfile.TemporaryDirectory() as directory:
        shared = _write(directory, "host.toml", "[host]\nchannel = 3\n")
        loaded = config.load_host_file_config(
            shared, local_path=Path(directory) / "does-not-exist.toml")
    assert loaded.channel == 3


def test_loader_rejects_unknown_sections_and_keys():
    with tempfile.TemporaryDirectory() as directory:
        unknown_section = _write(directory, "unknown-section.toml", "[mystery]\ngift = 'x'\n")
        unknown_key = _write(directory, "unknown-key.toml", "[host]\ncheannel = 1\n")
        _raises(lambda: config.load_host_file_config(unknown_section), "unknown host configuration section")
        _raises(lambda: config.load_host_file_config(unknown_key), "unknown key")


def test_loader_rejects_incorrect_types_and_ranges():
    with tempfile.TemporaryDirectory() as directory:
        bad_bool = _write(directory, "bad-bool.toml", "[host]\nlive = 1\n")
        bad_channel = _write(directory, "bad-channel.toml", "[host]\nchannel = 15\n")
        bad_section = _write(directory, "bad-section.toml", "host = true\n")
        _raises(lambda: config.load_host_file_config(bad_bool), "host.live must be a boolean")
        _raises(lambda: config.load_host_file_config(bad_channel), "host.channel")
        _raises(lambda: config.load_host_file_config(bad_section), "[host] must be a TOML table")


def test_loader_reports_missing_and_invalid_shared_toml_cleanly():
    with tempfile.TemporaryDirectory() as directory:
        missing = Path(directory) / "missing.toml"
        invalid = _write(directory, "invalid.toml", "[host\n")
        _raises(lambda: config.load_host_file_config(missing), "does not exist")
        _raises(lambda: config.load_host_file_config(invalid), "invalid TOML")


def test_public_override_api_is_strict_and_converts_to_runtime_models():
    loaded = config.BUILTIN_HOST_FILE_CONFIG.with_overrides({
        "host": {"channel": 9, "scene_id": 1234, "max_participants": 7},
        "ldn": {
            "phy": "phy2",
            "keys_path": "/keys/prod.keys",
            "local_comm_id": 0x1006FA0233F8000,
        },
    })
    options = loaded.to_host_options()
    ldn = loaded.to_ldn_config()
    assert (options.channel, options.scene_id, options.max_participants) == (9, 1234, 7)
    assert (ldn.phy, ldn.keys_path, ldn.local_comm_id) == (
        "phy2", "/keys/prod.keys", 0x1006FA0233F8000)
    _raises(lambda: loaded.with_overrides({"host": {"channel": True}}),
            "host.channel")


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("Host TOML configuration tests: OK")
