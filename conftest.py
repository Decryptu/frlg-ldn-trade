"""Test-time import paths: `bin/` and the `tools/` subdirectories for the launchers the tests import by name
(`import frlg_mg_host`), and the repo root for `pokeldn` and `vendor/LDN`."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for path in (os.path.join(ROOT, "tools", "frlg"), os.path.join(ROOT, "tools", "ldn"),
             os.path.join(ROOT, "bin"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
