---
title: Raspberry Pi host
parent: Hardware and setup
nav_order: 2
---

# Raspberry Pi 4 Mystery Gift host

A 64-bit Raspberry Pi 4 with the TP-Link Archer T3U / AC1300 USB adapter
(`2357:012d`, `rtw88_8822bu`) hosts Mystery Gift. The patched LDN
implementation is in `vendor/LDN`; the unpatched PyPI package must not be
installed on the Pi.

Deployment transfers committed Git objects through an SSH alias to a bare Git
repository on the Pi. It does not use GitHub or `rsync`, and it transfers no
ignored files: reference repositories, `.venv`, captures, Pokemon files,
Switch keys.

## First deployment

On the desktop, with the SSH alias and the Pi login user (`--path` and
`--repo` change the default layout):

```bash
cd /path/to/pokeldn
git status
git add -A
git commit -m "Prepare Raspberry Pi deployment"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

`deploy_pi.sh` refuses a dirty desktop checkout, runs the configuration and
documentation tests, creates `/home/PI_USER/repos/pokeldn.git` on the Pi if
needed, pushes the current commit to its `deploy` branch, and creates or
fast-forwards `/home/PI_USER/pokeldn`. It never force-resets a Pi checkout;
a Pi checkout with uncommitted files is rejected.

If the SSH alias already specifies the remote user, provide the paths:

```bash
./scripts/deploy_pi.sh --host pi-ldn \
  --path /home/PI_USER/pokeldn \
  --repo /home/PI_USER/repos/pokeldn.git
```

After the first deployment, connect to the Pi and bootstrap it:

```bash
ssh pi-ldn
cd ~/pokeldn
./scripts/setup_pi.sh
```

The setup script requires 64-bit Raspberry Pi OS (`aarch64`) and Python 3.11
or newer (Bookworm supplies 3.11; Trixie supplies 3.13). It installs the
virtual environment from `requirements.txt` (which uses `vendor/LDN`),
installs the system tools, and tells NetworkManager to leave `ldnclient`,
`ldn`, `ldn-mon`, and `ldn-tap` alone. `--no-apt` skips the system
dependencies; `--no-networkmanager` skips the exclusion.

Keep SSH on Ethernet or the Pi's built-in Wi-Fi. Hosting takes exclusive
control of the TP-Link adapter.

## Machine-local configuration and Switch keys

`config/host.toml` is tracked and defaults to the TP-Link live profile:

```toml
[host]
live = true
skip_encryption = true
accept_decrypted_ccmp = true

[ldn]
phy = "auto"
```

The ignored `config/host.local.toml` holds settings that vary by machine. The
key path must be absolute; the host runs under `sudo`:

```toml
[ldn]
keys_path = "/home/PI_USER/.switch/prod.keys"
```

`prod.keys` is never copied by deployment; the installer and the SSH
streaming example are in [Switch key setup](hardware_switch_keys.md). For a
key file already on the Pi:

```bash
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

## Verify and run

Plug in the TP-Link adapter, then run:

```bash
cd ~/pokeldn
./scripts/preflight_pi.sh
./scripts/run_mystery_gift.sh
```

Preflight is read-only. It verifies Python and the vendored LDN package,
loads `config/host.toml` plus optional `config/host.local.toml`, verifies the
TP-Link USB ID and `rtw88_8822bu` driver, checks AP and monitor support, checks
the NetworkManager exclusion, and verifies that the configured key file is
mode `0600`. It rejects an effective TP-Link invocation that disables either
`skip_encryption` or `accept_decrypted_ccmp`, including arguments passed
through `run_mystery_gift.sh`. It supplies Debian's `sbin` paths itself, so it
behaves the same in an interactive shell and through a one-line SSH command.

`run_mystery_gift.sh` runs preflight once, then supervises short-lived root
host processes. Each process gets a random TID/SID, and the wrapper restarts
it after a successful delivery, an unsuccessful attempt, or five minutes
without a Switch join or Pia/RFU traffic. Ctrl-C once stops the supervisor.
A host option after the script name is passed through.

`bin/frlg_mg_host.py` lifecycle controls: `--end-on-success` ends after the
post-delivery close sequence; `--idle-timeout SECONDS` ends after that period
without Switch traffic. The wrapper always uses `--end-on-success
--idle-timeout 300` and owns `--id`, so a saved `--id` cannot reuse an old
identity.

Each joined attempt is appended to the ignored daily CSV ledger
`logs/mystery-gift-attempts-YYYY-MM-DD.csv`. Columns: `attempt`,
`received_result`, `time`, `trainer_name`, `trainer_ot`. `received_result` is
`true` only when the host sent a Wonder Card or Stamp; the trainer name and
five-digit trainer ID come from the Switch's LinkPlayer block. An attempt that
fails before that block arrives is retained with blank identity fields. For
direct `bin/frlg_mg_host.py` usage, `--attempt-log-dir logs` enables the same
ledger.

Every `bin/frlg_mg_host.py` option is forwarded by the wrapper. The list,
without preflight or root:

```bash
./scripts/run_mystery_gift.sh --help
./scripts/run_mystery_gift.sh --print-effective-config
```

Event controls: `--gift`, `--flag-id`, `--verbose`, `--capture`, `--ot`,
`--version`, `--id`. `--client-ready-idle-frames N` is a timing diagnostic for
hardware tests; leave it unset otherwise.

```bash
./scripts/run_mystery_gift.sh --gift celebi --verbose
./scripts/run_mystery_gift.sh --gift solrock-stamp \
  --client-ready-idle-frames 45 --capture /tmp/solrock-45.jsonl
```

`--make-artifact` writes a deterministic `.ram.lst` listing under
`artifacts/` (`--artifact-dir DIR` redirects it):

```bash
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact \
  --artifact-dir /home/chase/mystery-gift-artifacts
```

The listing records the compiled RAM script bytes, decoded instructions,
checksums, branch/message destinations, and the delivery-stage summary.
`--no-make-artifact` disables it in a saved command.

Leave `--phy`, `--adapter`, `--skip-encryption`, and
`--accept-decrypted-ccmp` at their tracked TP-Link defaults unless diagnosing
different hardware.

For the ALFA `mt76x0u` adapter, select its current PHY and disable the
TP-Link receive normalization:

```bash
./scripts/run_mystery_gift.sh --gift worlds-xp --phy phy1 \
  --no-accept-decrypted-ccmp --capture /tmp/gen5.jsonl
```

An explicit `--phy` bypasses the named TP-Link selector. Preflight then checks
that PHY's AP and monitor modes and verifies the `mt76x0u` CCMP profile. `iw
dev` gives the current PHY; the number changes after a replug.

### MT7601U adapter with the custom AP driver

The stock `mt7601u` driver has monitor mode and no AP mode. Hosting needs the
project-pinned `mt7601u-ap` DKMS module, source under `vendor/mt7601u-ap-1.0`,
built on the Pi for the running ARM64 kernel. Do not copy a desktop-built
`.ko`.

Install it from the desktop:

```bash
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER --install-mt7601u-ap
```

or on the Pi:

```bash
cd ~/pokeldn
./scripts/setup_pi.sh --install-mt7601u-ap --no-networkmanager
```

This installs the APT packages `dkms` and `linux-headers-rpi-v8`, then
registers a DKMS module for every installed kernel with matching headers (APT
can install a newer kernel before the Pi reboots). If the running kernel lacks
matching headers, the installer stops. Replug the MT7601U adapter (or reboot),
read its new PHY number from `iw dev`, then:

```bash
./scripts/run_mystery_gift.sh --gift worlds-xp --phy phyN \
  --no-accept-decrypted-ccmp --capture /tmp/mt7601u.jsonl
```

Preflight confirms that the selected `mt7601u` module comes from
`updates/dkms` and exposes both AP and monitor mode.

## Later desktop changes

For each committed change on the desktop:

```bash
git add -A
git commit -m "Describe the change"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

The helper fast-forwards code only. If dependency files or `vendor/LDN`
change, the Pi refreshes its virtual environment. To update manually on the
Pi after a push:

```bash
cd ~/pokeldn
./scripts/update_pi.sh
```

Do not edit tracked source files on the Pi. Keep `config/host.local.toml`,
Switch keys, and diagnostic captures Pi-local and ignored.
