#!/usr/bin/env bash
# Run the configured, live Mystery Gift host after read-only hardware checks.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)

# Informational modes do not need hardware checks or root privileges. Every
# other argument is passed through both preflight and the live host.
for argument in "$@"; do
    case "$argument" in
        -h|--help|--print-effective-config)
            exec "$PROJECT_ROOT/.venv/bin/python" \
                "$PROJECT_ROOT/frlgmg_host.py" "$@"
            ;;
    esac
done

"$PROJECT_ROOT/scripts/preflight_pi.sh" "$@"
exec sudo -E "$PROJECT_ROOT/.venv/bin/python" -u "$PROJECT_ROOT/frlgmg_host.py" "$@"
