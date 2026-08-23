"""Static safety checks for the Pi key installation helper.

These deliberately do not create, read, or copy any Nintendo Switch key
material. Runtime validation belongs on the target machine with the owner's
explicit source file.
"""

from pathlib import Path


INSTALLER = Path("scripts/install_switch_keys.sh")
GUIDE = Path("docs/switch_keys.md")


def test_key_installer_uses_private_modes_and_explicit_sources():
    text = INSTALLER.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "--source" in text
    assert "--stdin" in text
    assert "--destination" in text
    assert "umask 077" in text
    assert "chmod 0700 \"$target_dir\"" in text
    assert "chmod 0600 \"$destination\"" in text
    assert "SUDO_USER" in text
    assert "runuser" in text
    assert text.index("exec runuser") < text.index("while (($#))")
    assert "cmp -s" in text
    assert "cat >" not in text


def test_key_guide_covers_streaming_and_scp_over_an_ssh_alias():
    text = GUIDE.read_text(encoding="utf-8")
    assert "pi-ldn" in text
    assert "--stdin" in text
    assert "scp -p" in text
    assert "mode `0700`" in text
    assert "mode `0600`" in text


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
    print("Switch key installer tests: OK")
