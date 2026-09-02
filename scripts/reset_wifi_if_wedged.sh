#!/bin/bash
# The TP-Link Archer T3U (rtw88_8822bu) firmware wedges after a long session: dmesg fills with
#   rtw88_8822bu ...: failed to get tx report from firmware
# and the host can no longer transmit reliably. On the wire that looks like host silence, and the
# console leaves ~1s into the trainer-card exchange with 2318-0006 (a healthy barrier takes ~4.9s).
# Reloading the driver clears it; rebooting the console does NOT (w8/w9/w10 all failed right after
# a game restart, w11 succeeded right after this reset). See NOTES.local.md.
#
# Usage: reset_wifi_if_wedged.sh [threshold]   (default 2; --force resets unconditionally)
# Exit 0 whether or not it reset; non-zero only if the reset itself failed.
set -u
MOD=rtw88_8822bu
FORCE=0
if [ "${1:-}" = "--force" ]; then FORCE=1; shift; fi
THRESH="${1:-2}"
SUDO="sudo -S -p ''"
[ -n "${SUDOPASS:-}" ] && SUDO="sudo -S -p '' "
pass() { if [ -n "${SUDOPASS:-}" ] && [ -s "$SUDOPASS" ]; then cat "$SUDOPASS"; else printf '\n'; fi; }

# Count wedge lines logged SINCE the module was last registered - errors from before a previous
# reload are stale and must not trigger another one.
count_since_load() {
    pass | sudo -S -p '' dmesg 2>/dev/null | awk '
        /registered new interface driver '"$MOD"'/ { n = 0; next }
        /failed to get tx report from firmware/    { n++ }
        END { print n + 0 }'
}

if [ "$FORCE" = 1 ]; then
    N=$((THRESH + 1)); echo "reset_wifi: forced"
else
    N=$(count_since_load)
    echo "reset_wifi: $N 'failed to get tx report' since the driver was last loaded (threshold $THRESH)"
fi

if [ "$N" -lt "$THRESH" ]; then
    echo "reset_wifi: adapter looks healthy, not touching it"
    exit 0
fi

echo "reset_wifi: adapter is wedged - reloading $MOD"
for v in ldnclient ldn ldn-mon ldnair; do pass | sudo -S -p '' iw dev "$v" del 2>/dev/null; done
pass | sudo -S -p '' modprobe -r "$MOD" 2>&1 | sed 's/^/reset_wifi: /'
sleep 3
pass | sudo -S -p '' modprobe "$MOD" 2>&1 | sed 's/^/reset_wifi: /'
for _ in $(seq 1 20); do
    iw dev 2>/dev/null | grep -q Interface && break
    sleep 1
done
iw dev 2>/dev/null | grep -q Interface || { echo "reset_wifi: FAILED - no interface after reload" >&2; exit 1; }
echo "reset_wifi: reloaded; $(pass | sudo -S -p '' dmesg 2>/dev/null | grep -c 'Firmware version') firmware loads seen"
exit 0
