"""Test-time import paths: `bin/` and `tools/` for the launchers the tests import by name
(`import frlgmg_host`), and the repo root for `frlgsim` and `vendor/LDN`."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for path in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "bin"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
