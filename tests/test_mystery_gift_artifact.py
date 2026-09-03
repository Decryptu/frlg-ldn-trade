#!/usr/bin/env python3
"""Regression coverage for human-readable Mystery Gift artifacts."""

import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import frlgmg_host  # noqa: E402
from frlgsim import gift_artifact, gift_registry  # noqa: E402
from frlgsim.config import MysteryGiftRunConfig  # noqa: E402
from frlgsim.host_mg_app import MysteryGiftHostApplication  # noqa: E402


def test_artifact_boolean_flags_default_off_and_accept_both_variants():
    parser = frlgmg_host.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert {"--make-artifact", "--no-make-artifact", "--artifact-dir"} <= options
    assert parser.parse_args([]).make_artifact is False
    assert parser.parse_args(["--make-artifact"]).make_artifact is True
    assert parser.parse_args(["--make-artifact", "--no-make-artifact"]).make_artifact is False
    assert parser.parse_args([]).artifact_dir == "artifacts"
    assert parser.parse_args(["--artifact-dir", "diagnostics"]).artifact_dir == "diagnostics"


def test_artifact_decodes_exact_compiled_bytes_and_stage_summary():
    entry = gift_registry.GIFT_REGISTRY.entry("worlds-xp")
    distribution = entry.build_distribution()
    rendered = gift_artifact.render_artifact(
        gift=entry.slug, flag_id=entry.default_flag_id,
        distribution=distribution, definition=entry.definition)

    assert f"RAM script: {len(distribution.ram_script)} / 995 bytes" in rendered
    assert "worlds-xp.delivery.delivery[7]" in rendered
    assert "BattleLegendary(species=245, level=65)" in rendered
    assert "setwildbattle species=245, level=65, item=0" in rendered
    assert "25 38 01                 special StartLegendaryBattle (312)" in rendered
    assert bytes.fromhex("b6f50041000025380102") in distribution.ram_script


def test_artifact_writer_uses_the_script_hash_in_a_readable_sidecar_name():
    entry = gift_registry.GIFT_REGISTRY.entry("worlds-xp")
    distribution = entry.build_distribution()
    with tempfile.TemporaryDirectory() as directory:
        path = gift_artifact.write_artifact(
            directory, gift=entry.slug, flag_id=entry.default_flag_id,
            distribution=distribution, definition=entry.definition)
        assert path.parent == Path(directory)
        digest = hashlib.sha256(distribution.ram_script).hexdigest()[:12]
        assert path.name == f"worlds-xp-{entry.default_flag_id}-{digest}.ram.lst"
        assert "Mystery Gift artifact: worlds-xp" in path.read_text(encoding="utf-8")


def test_host_reuses_the_distribution_that_was_written_to_an_artifact():
    entry = gift_registry.GIFT_REGISTRY.entry("worlds-xp")
    distribution = entry.build_distribution()
    app = MysteryGiftHostApplication(
        MysteryGiftRunConfig(), distribution=distribution)
    assert app._build_distribution() is distribution


if __name__ == "__main__":
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for name, test in tests:
        test()
        print("ok   ", name)
    print(f"\n{len(tests)}/{len(tests)} passed")
