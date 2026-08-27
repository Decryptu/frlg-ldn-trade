#!/usr/bin/env bash
# Read-only checks for the Pi's TP-Link Archer T3U / rtw88_8822bu host setup.
set -euo pipefail

# Debian may omit sbin directories from PATH for non-interactive SSH commands,
# even though tools such as iw and modinfo are installed there.  Preflight is
# normally launched that way by the desktop workflow, so use the normal system
# command locations explicitly.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin${PATH:+:$PATH}"

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PYTHON=${PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}
FAILURES=0

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    FAILURES=$((FAILURES + 1))
}

pass() {
    printf 'OK: %s\n' "$*"
}

if [[ ! -x "$PYTHON" ]]; then
    fail "virtual environment not found; run scripts/setup_pi.sh"
elif ! "$PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    fail "Python 3.11+ is required"
else
    pass "Python $($PYTHON -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
fi

if [[ ! -d "$PROJECT_ROOT/vendor/LDN/ldn" ]]; then
    fail "vendored LDN is missing from $PROJECT_ROOT/vendor/LDN"
elif [[ -x "$PYTHON" ]] && "$PYTHON" - "$PROJECT_ROOT" <<'PY'
import pathlib
import sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / "vendor" / "LDN"))
import ldn
if root / "vendor" / "LDN" not in pathlib.Path(ldn.__file__).resolve().parents:
    raise SystemExit(1)
print(pathlib.Path(ldn.__file__).resolve())
PY
then
    pass "LDN resolves to vendored source"
else
    fail "Python does not resolve ldn from vendor/LDN"
fi

CONFIG_VALUES=""
USE_EXPLICIT_PHY=false
if [[ -x "$PYTHON" ]]; then
    if "$PYTHON" "$PROJECT_ROOT/frlgmg_host.py" \
            --print-effective-config "$@" >/dev/null; then
        pass "Mystery Gift CLI accepts the effective TOML configuration"
    else
        fail "Mystery Gift CLI cannot load the effective TOML configuration"
    fi
    if ! CONFIG_VALUES=$("$PYTHON" - "$PROJECT_ROOT" "$@" <<'PY'
import pathlib
import sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
import frlgmg_host
from frlgsim import host_cli

argv = sys.argv[2:]
file_config, shared_path, local_path = host_cli.load_host_file_config_from_argv(argv)
parser = frlgmg_host.build_parser(
    file_config, shared_path=shared_path, local_path=local_path)
args = parser.parse_args(argv)
_profile, ldn, options = host_cli.build_host_config(parser, args)
print(ldn.adapter)
print(ldn.phy)
print(ldn.keys_path)
print(pathlib.Path(ldn.keys_path).expanduser())
print(str(args.live).lower())
print(str(options.skip_encryption).lower())
print(str(options.accept_decrypted_ccmp).lower())
PY
); then
        fail "unable to load config/host.toml (and optional host.local.toml)"
    fi
fi

if [[ -n "$CONFIG_VALUES" ]]; then
    mapfile -t CONFIG_LINES <<<"$CONFIG_VALUES"
    ADAPTER=${CONFIG_LINES[0]}
    CONFIG_PHY=${CONFIG_LINES[1]}
    CONFIG_KEYS_PATH=${CONFIG_LINES[2]}
    KEYS_PATH=${CONFIG_LINES[3]}
    LIVE=${CONFIG_LINES[4]}
    SKIP_ENCRYPTION=${CONFIG_LINES[5]}
    ACCEPT_DECRYPTED_CCMP=${CONFIG_LINES[6]}
    if [[ "$CONFIG_PHY" != "auto" ]]; then
        USE_EXPLICIT_PHY=true
    fi
    if [[ "$LIVE" == true && "$SKIP_ENCRYPTION" == true ]]; then
        pass "live hosting and delegated transmit CCMP are enabled"
    else
        fail "host profile requires live=true and skip_encryption=true"
    fi
    if [[ "$USE_EXPLICIT_PHY" == false ]]; then
        if [[ "$ACCEPT_DECRYPTED_CCMP" != true ]]; then
            fail "TP-Link profile requires accept_decrypted_ccmp=true"
        else
            pass "TP-Link retained-CCMP receive normalization is enabled"
        fi
        if [[ "$ADAPTER" != "tplink-archer-t3u" ]]; then
            fail "adapter is $ADAPTER; expected tplink-archer-t3u when phy is auto"
        else
            pass "configured TP-Link Archer T3U profile"
        fi
    else
        pass "configured explicit host phy $CONFIG_PHY (named adapter is bypassed)"
    fi
else
    KEYS_PATH=""
    CONFIG_KEYS_PATH=""
    CONFIG_PHY="auto"
fi

find_tplink_phy() {
    local phy_dir current vendor product
    for phy_dir in /sys/class/ieee80211/phy*; do
        [[ -e "$phy_dir/device" ]] || continue
        current=$(readlink -f "$phy_dir/device")
        while [[ "$current" != / && -n "$current" ]]; do
            if [[ -r "$current/idVendor" && -r "$current/idProduct" ]]; then
                vendor=$(<"$current/idVendor")
                product=$(<"$current/idProduct")
                if [[ "$vendor:$product" == "2357:012d" ]]; then
                    basename "$phy_dir"
                    return 0
                fi
            fi
            current=$(dirname "$current")
        done
    done
    return 1
}

check_phy_modes() {
    local phy=$1 label=$2 phy_info
    if ! command -v iw >/dev/null 2>&1; then
        fail "iw is not installed"
        return
    fi
    phy_info=$(iw phy "$phy" info 2>/dev/null || true)
    if grep -qE '^[[:space:]]*\* AP$' <<<"$phy_info"; then
        pass "$label supports AP mode"
    else
        fail "$label does not report AP mode"
    fi
    if grep -qE '^[[:space:]]*\* monitor$' <<<"$phy_info"; then
        pass "$label supports monitor mode"
    else
        fail "$label does not report monitor mode"
    fi
}

if [[ "$USE_EXPLICIT_PHY" == true ]]; then
    SELECTED_PHY=$CONFIG_PHY
    if [[ ! -d "/sys/class/ieee80211/$SELECTED_PHY" ]]; then
        fail "configured phy $SELECTED_PHY does not exist"
    else
        DRIVER_LINK="/sys/class/ieee80211/$SELECTED_PHY/device/driver"
        DRIVER=""
        [[ -L "$DRIVER_LINK" ]] && DRIVER=$(basename "$(readlink -f "$DRIVER_LINK")")
        pass "selected phy is $SELECTED_PHY (${DRIVER:-unknown} driver)"
        case "$DRIVER" in
            mt76x0u)
                if [[ "$ACCEPT_DECRYPTED_CCMP" == false ]]; then
                    pass "mt76x0u uses standard CCMP receive frames"
                else
                    fail "mt76x0u requires accept_decrypted_ccmp=false"
                fi
                ;;
            rtw88_8822bu)
                if [[ "$ACCEPT_DECRYPTED_CCMP" == true ]]; then
                    pass "rtw88_8822bu retained-CCMP receive normalization is enabled"
                else
                    fail "rtw88_8822bu requires accept_decrypted_ccmp=true"
                fi
                ;;
            *)
                pass "selected phy has no built-in CCMP receive profile"
                ;;
        esac
        check_phy_modes "$SELECTED_PHY" "selected phy $SELECTED_PHY"
    fi
else
    if command -v lsusb >/dev/null 2>&1 && lsusb -d 2357:012d >/dev/null; then
        pass "TP-Link USB 2357:012d is attached"
    else
        fail "TP-Link Archer T3U (USB 2357:012d) is not attached"
    fi

    if command -v modinfo >/dev/null 2>&1 && modinfo rtw88_8822bu >/dev/null; then
        pass "rtw88_8822bu kernel module is available"
    else
        fail "rtw88_8822bu kernel module is unavailable"
    fi

    TP_LINK_PHY=$(find_tplink_phy || true)
    if [[ -z "$TP_LINK_PHY" ]]; then
        fail "could not map USB 2357:012d to an ieee80211 phy"
    fi
    if [[ -n "$TP_LINK_PHY" ]]; then
        pass "TP-Link is $TP_LINK_PHY"
        DRIVER_LINK="/sys/class/ieee80211/$TP_LINK_PHY/device/driver"
        DRIVER=""
        [[ -L "$DRIVER_LINK" ]] && DRIVER=$(basename "$(readlink -f "$DRIVER_LINK")")
        if [[ "$DRIVER" == "rtw88_8822bu" ]]; then
            pass "TP-Link phy uses rtw88_8822bu"
        else
            fail "TP-Link phy driver is ${DRIVER:-unknown}; expected rtw88_8822bu"
        fi
        check_phy_modes "$TP_LINK_PHY" "TP-Link phy"
    fi
fi

if [[ -n "$KEYS_PATH" ]]; then
    if [[ "$CONFIG_KEYS_PATH" != /* ]]; then
        fail "[ldn].keys_path must be an absolute Pi path; set it in config/host.local.toml"
    elif [[ ! -f "$KEYS_PATH" ]]; then
        fail "Switch keys are missing (install with scripts/install_switch_keys.sh)"
    elif [[ $(stat -c '%a' "$KEYS_PATH") != "600" ]]; then
        fail "Switch keys must have mode 600"
    else
        pass "Switch keys are installed with mode 600"
    fi
fi

NM_CONF=/etc/NetworkManager/conf.d/zz-frlg-ldn-unmanaged.conf
if [[ -r "$NM_CONF" ]] && grep -q 'interface-name:ldn-mon' "$NM_CONF" \
        && grep -q 'interface-name:ldn-tap' "$NM_CONF"; then
    pass "NetworkManager ignores LDN-created interfaces"
else
    fail "NetworkManager LDN exclusion is missing; run scripts/setup_pi.sh"
fi

if ((FAILURES)); then
    printf '\nPreflight failed (%d check(s)). Fix the items above before hosting.\n' "$FAILURES" >&2
    exit 1
fi
printf '\nPi preflight passed. Start with scripts/run_mystery_gift.sh\n'
