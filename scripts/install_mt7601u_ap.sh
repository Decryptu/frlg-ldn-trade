#!/usr/bin/env bash
# Install the project-pinned MT7601U AP-mode DKMS module for the running Pi
# kernel. This is deliberately an explicit, privileged operation.
set -euo pipefail

PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
PACKAGE_NAME=mt7601u-ap
PACKAGE_VERSION=1.0
SOURCE_DIR="$PROJECT_ROOT/vendor/$PACKAGE_NAME-$PACKAGE_VERSION"
SYSTEM_SOURCE_DIR="/usr/src/$PACKAGE_NAME-$PACKAGE_VERSION"
KERNEL_RELEASE=$(uname -r)
KERNEL_BUILD="/lib/modules/$KERNEL_RELEASE/build"

usage() {
    cat <<'USAGE'
Usage: sudo scripts/install_mt7601u_ap.sh

Build and install this project's custom mt7601u AP-mode DKMS module for the
currently running Raspberry Pi OS kernel. Unplug and reconnect the MT7601U
adapter (or reboot) after success so it loads the replacement module.
USAGE
}

if (($#)); then
    case "$1" in
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
fi

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    printf 'Run this installer through sudo.\n' >&2
    exit 1
fi
case "$(uname -m)" in
    aarch64|arm64) ;;
    *) printf 'This installer supports 64-bit Raspberry Pi OS only; found %s.\n' "$(uname -m)" >&2; exit 1 ;;
esac
[[ -d "$SOURCE_DIR" ]] || { printf 'Missing tracked driver source: %s\n' "$SOURCE_DIR" >&2; exit 1; }
[[ -f "$SOURCE_DIR/dkms.conf" && -f "$SOURCE_DIR/init.c" ]] || {
    printf 'Driver source is incomplete: %s\n' "$SOURCE_DIR" >&2; exit 1;
}
grep -Fq 'BIT(NL80211_IFTYPE_STATION) | BIT(NL80211_IFTYPE_AP)' "$SOURCE_DIR/init.c" || {
    printf 'Refusing to install a source tree without the MT7601U AP-mode patch.\n' >&2; exit 1;
}
command -v dkms >/dev/null 2>&1 || {
    printf 'DKMS is not installed. Run scripts/setup_pi.sh --install-mt7601u-ap.\n' >&2; exit 1;
}
[[ -f "$KERNEL_BUILD/Makefile" ]] || {
    printf 'Matching kernel headers are unavailable for %s (%s). Install linux-headers-rpi-v8, reboot into a matching kernel, then retry.\n' \
        "$KERNEL_RELEASE" "$KERNEL_BUILD" >&2
    exit 1
}

# APT may install a newer Pi kernel and its headers while the older kernel is
# still running. Build for every installed kernel with headers so the first
# reboot after setup does not fall back to the stock mt7601u module.
KERNEL_RELEASES=()
for kernel_build in /lib/modules/*/build; do
    [[ -f "$kernel_build/Makefile" ]] || continue
    KERNEL_RELEASES+=("$(basename "$(dirname "$kernel_build")")")
done
((${#KERNEL_RELEASES[@]})) || {
    printf 'No installed kernels have usable headers.\n' >&2
    exit 1
}

# Remove only the same named/versioned DKMS registration.  The source directory
# is then refreshed from the committed checkout so stale files cannot survive a
# future source update.
dkms remove -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION" --all >/dev/null 2>&1 || true
rm -rf -- "$SYSTEM_SOURCE_DIR"
install -d -m 0755 "$SYSTEM_SOURCE_DIR"
cp -a "$SOURCE_DIR/." "$SYSTEM_SOURCE_DIR/"

dkms add -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION"
for kernel_release in "${KERNEL_RELEASES[@]}"; do
    dkms build -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION" -k "$kernel_release"
    dkms install -m "$PACKAGE_NAME" -v "$PACKAGE_VERSION" -k "$kernel_release"
    depmod -a "$kernel_release"
done

MODULE_PATH=$(modinfo -k "$KERNEL_RELEASE" -n mt7601u 2>/dev/null || true)
if [[ "$MODULE_PATH" != */updates/dkms/mt7601u.ko* ]]; then
    printf 'DKMS finished but mt7601u does not resolve to updates/dkms: %s\n' \
        "${MODULE_PATH:-not found}" >&2
    exit 1
fi

printf 'Installed %s/%s for %s: %s\n' \
    "$PACKAGE_NAME" "$PACKAGE_VERSION" "$KERNEL_RELEASE" "$MODULE_PATH"
printf 'Unplug and reconnect the MT7601U adapter, then run: %s/scripts/preflight_pi.sh --phy phyN --no-accept-decrypted-ccmp\n' \
    "$PROJECT_ROOT"
