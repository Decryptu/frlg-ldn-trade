"""Test-time import paths.

The four launchers moved to `bin/` in the reorganisation, and fifteen test modules import them by
name (`import frlgmg_host`) to reach their `build_parser()` and their config plumbing. Before the
move that worked because pytest is run from the repo root, which puts the root on sys.path; the
launchers are not a package and there is nothing to import them as. This puts `bin/` where the root
used to be, so those imports keep meaning the same thing.

`tools/` is here for the same reason (test_joyspot_discovery imports `joyspot_probe`), and the repo
root itself for `frlgsim` and for the tests that reach `vendor/LDN`.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

for path in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "bin"), ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
