#!/usr/bin/env bash
# Install (or refresh) the systemd unit that supervises the Mystery Gift host.
# Safe to re-run: it rewrites the unit from this script, reloads systemd, and
# restarts the service so a fresh checkout's run_mystery_gift.sh takes effect.
# scripts/deploy_pi.sh calls this after updating the Pi checkout.
set -euo pipefail

SERVICE_NAME="fr-ldn-mystery-gift"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
# Resolve the checkout from this script's own location so the unit gets an
# absolute WorkingDirectory/ExecStart no matter the caller's CWD (systemd does
# not expand ~, and a relative path would break the service).
PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
RUNNER="${PROJECT_DIR}/scripts/run_mystery_gift.sh"

if [[ ! -f "${RUNNER}" ]]; then
    echo "Error: ${RUNNER} does not exist." >&2
    exit 1
fi

chmod +x "${RUNNER}"

echo "Installing ${SERVICE_NAME} service using project directory:"
echo "  ${PROJECT_DIR}"

# Unquoted heredoc so ${PROJECT_DIR}/${RUNNER} expand now; every runtime shell
# token inside ExecStartPre is \$-escaped so systemd receives them literally and
# evaluates them at start time (wait up to 60s for an AP-capable Wi-Fi phy;
# --phy is omitted so the host auto-selects it).
sudo tee "${SERVICE_FILE}" >/dev/null <<EOF
[Unit]
Description=FR-LDN Mystery Gift Host
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}

ExecStartPre=/bin/sh -c 'for _ in \$(seq 1 60); do for p in /sys/class/ieee80211/phy*; do [ -e "\$p" ] && iw phy "\$(basename "\$p")" info 2>/dev/null | grep -q "\* AP\$" && exit 0; done; sleep 1; done; exit 1'

ExecStart=${RUNNER} --gift worlds-xp

# Restart if the script exits for any reason.
Restart=always
RestartSec=5

# Give the script time to clean up its wireless interfaces.
KillSignal=SIGINT
TimeoutStopSec=20

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}.service"
sudo systemctl restart "${SERVICE_NAME}.service"

echo
echo "Service installed and restarted."
echo "  Status:  systemctl status ${SERVICE_NAME}.service"
echo "  Logs:    journalctl -u ${SERVICE_NAME}.service -f"
