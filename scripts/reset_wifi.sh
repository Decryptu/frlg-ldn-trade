#!/bin/bash
# Reload rtw88_8822bu so every live run starts from a fresh adapter. Exit non-zero only if no
# interface comes back.
set -u
MOD=rtw88_8822bu
pass() { if [ -n "${SUDOPASS:-}" ] && [ -s "$SUDOPASS" ]; then cat "$SUDOPASS"; else printf '\n'; fi; }
for v in ldnclient ldn ldn-mon ldnair; do pass | sudo -S -p '' iw dev "$v" del 2>/dev/null; done
pass | sudo -S -p '' modprobe -r "$MOD" 2>&1 | sed 's/^/reset_wifi: /'
sleep 3
pass | sudo -S -p '' modprobe "$MOD" 2>&1 | sed 's/^/reset_wifi: /'
for _ in $(seq 1 20); do
    iw dev 2>/dev/null | grep -q Interface && { echo "reset_wifi: $MOD reloaded"; exit 0; }
    sleep 1
done
echo "reset_wifi: FAILED - no interface after reload" >&2
exit 1
