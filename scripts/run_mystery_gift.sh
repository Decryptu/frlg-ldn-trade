#!/usr/bin/env bash
# Run the configured, live Mystery Gift host after read-only hardware checks.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)

"$PROJECT_ROOT/scripts/preflight_pi.sh" "$@"
exec sudo -E "$PROJECT_ROOT/.venv/bin/python" -u "$PROJECT_ROOT/frlgmg_host.py" "$@"
