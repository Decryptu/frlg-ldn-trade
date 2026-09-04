#!/usr/bin/env bash
# Supervise one-at-a-time Mystery Gift hosts after read-only hardware checks.
# Each host is deliberately short-lived: it receives a fresh trainer identity
# and starts a clean LDN/RFU session after success, failure, or five idle minutes.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PYTHON="$PROJECT_ROOT/.venv/bin/python"
IDLE_TIMEOUT_SECONDS=300
RESTART_DELAY_SECONDS=1
ATTEMPT_LOG_DIR="$PROJECT_ROOT/logs"

# Informational modes do not need hardware checks or root privileges. Every
# other argument is passed through both preflight and the live host.
for argument in "$@"; do
    case "$argument" in
        -h|--help|--print-effective-config)
            exec "$PYTHON" \
                "$PROJECT_ROOT/bin/frlgmg_host.py" "$@"
            ;;
    esac
done

"$PROJECT_ROOT/scripts/preflight_pi.sh" "$@"

# The supervisor owns the per-run trainer identity.  Ignore an explicit --id
# from a saved command so every advertised run has a genuinely new TID/SID.
HOST_ARGS=()
while (($#)); do
    case "$1" in
        --id)
            [[ $# -ge 2 ]] || { printf '--id requires TID[:SID]\n' >&2; exit 2; }
            shift 2
            ;;
        --id=*) shift ;;
        *) HOST_ARGS+=("$1"); shift ;;
    esac
done

new_identity() {
    "$PYTHON" -c 'import secrets; print(f"{secrets.randbelow(65536)}:{secrets.randbelow(65536)}")'
}

stop_supervisor() {
    printf '\nStopping Mystery Gift supervisor.\n'
    exit 130
}
trap stop_supervisor INT TERM

attempt=0
while true; do
    attempt=$((attempt + 1))
    identity=$(new_identity)
    printf '\n[supervisor] Starting attempt %d with fresh TID:SID %s\n' \
        "$attempt" "$identity"

    set +e
    sudo -E "$PYTHON" -u "$PROJECT_ROOT/bin/frlgmg_host.py" \
        "${HOST_ARGS[@]}" --id "$identity" --end-on-success \
        --idle-timeout "$IDLE_TIMEOUT_SECONDS" \
        --attempt-log-dir "$ATTEMPT_LOG_DIR"
    status=$?
    set -e

    case "$status" in
        0) reason="successful distribution" ;;
        1) reason="unsuccessful distribution attempt" ;;
        124) reason="${IDLE_TIMEOUT_SECONDS}s without meaningful Switch traffic" ;;
        130) printf '[supervisor] Host interrupted; not restarting.\n'; exit 130 ;;
        2) printf '[supervisor] Host configuration error; not restarting.\n' >&2; exit 2 ;;
        *) reason="host process exit status $status" ;;
    esac
    printf '[supervisor] Restarting after %s.\n' "$reason"
    sleep "$RESTART_DELAY_SECONDS"
done
