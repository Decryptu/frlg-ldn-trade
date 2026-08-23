#!/usr/bin/env bash
# Bootstrap a Raspberry Pi OS 64-bit checkout.  Safe to run again after an
# update: it only installs missing system packages and refreshes this checkout's
# virtual environment.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
INSTALL_SYSTEM_PACKAGES=true
CONFIGURE_NETWORKMANAGER=true

usage() {
    cat <<'USAGE'
Usage: scripts/setup_pi.sh [--no-apt] [--no-networkmanager]

Set up this checked-out project on 64-bit Raspberry Pi OS.  This does not
install or copy Switch keys; run scripts/install_switch_keys.sh separately.
USAGE
}

while (($#)); do
    case "$1" in
        --no-apt) INSTALL_SYSTEM_PACKAGES=false ;;
        --no-networkmanager) CONFIGURE_NETWORKMANAGER=false ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

case "$(uname -m)" in
    aarch64|arm64) ;;
    *)
        printf 'This installer is for 64-bit Raspberry Pi OS (aarch64); found %s.\n' \
            "$(uname -m)" >&2
        exit 1
        ;;
esac

if [[ "$INSTALL_SYSTEM_PACKAGES" == true ]]; then
    if ! command -v apt-get >/dev/null 2>&1; then
        printf 'apt-get is required for automatic system package installation.\n' >&2
        exit 1
    fi
    sudo apt-get update
    sudo apt-get install -y \
        python3 python3-venv python3-dev build-essential git iw rfkill usbutils \
        network-manager
fi

PYTHON=${PYTHON:-python3}
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    printf 'Python 3 is required.\n' >&2
    exit 1
fi
PYTHON_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! $PYTHON -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    printf 'Python 3.11 or newer is required; found %s. Install current 64-bit Raspberry Pi OS, then retry.\n' \
        "$PYTHON_VERSION" >&2
    exit 1
fi

if [[ ! -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    "$PYTHON" -m venv "$PROJECT_ROOT/.venv"
fi
"$PROJECT_ROOT/.venv/bin/python" -m pip install --upgrade pip
(
    # Editable paths in requirements.txt are relative to the invoking working
    # directory, so anchor pip here even when update_pi.sh was called elsewhere.
    cd "$PROJECT_ROOT"
    "$PROJECT_ROOT/.venv/bin/python" -m pip install -r requirements.txt
)

if [[ "$CONFIGURE_NETWORKMANAGER" == true ]]; then
    if ! command -v systemctl >/dev/null 2>&1 || ! systemctl list-unit-files NetworkManager.service >/dev/null 2>&1; then
        printf 'NetworkManager is not available; use --no-networkmanager only if another manager owns these interfaces.\n' >&2
        exit 1
    fi
    sudo install -d -m 0755 /etc/NetworkManager/conf.d
    sudo tee /etc/NetworkManager/conf.d/zz-frlg-ldn-unmanaged.conf >/dev/null <<'EOF'
[keyfile]
unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap
EOF
    sudo systemctl reload NetworkManager || sudo systemctl restart NetworkManager
fi

printf '\nPi setup complete. Next: %s\n' \
    "$PROJECT_ROOT/scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys"
printf 'Then run: %s\n' "$PROJECT_ROOT/scripts/preflight_pi.sh"
