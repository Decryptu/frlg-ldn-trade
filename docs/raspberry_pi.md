# Raspberry Pi 4 Mystery Gift host

This project can host Mystery Gift on a 64-bit Raspberry Pi 4 using the
TP-Link Archer T3U / AC1300 USB adapter (`2357:012d`, `rtw88_8822bu`).  The
repository includes the patched LDN implementation in `vendor/LDN`, so a Pi
does not need a second LDN checkout and must not install the unpatched PyPI
package instead.

The normal deployment transfers committed Git objects through your SSH alias
to a bare Git repository on the Pi. It does not use GitHub, `rsync`, or a copy
of the desktop working tree. Consequently it also does not transfer ignored
reference repositories, `.venv`, captures, Pokemon files, or Switch keys.

## First deployment

On the desktop, choose the existing SSH alias/tunnel and the Pi login user.
The paths below are defaults used by the deployment helper; change them with
`--path` and `--repo` if your Pi uses a different layout.

```bash
cd /path/to/frlg-ldn-trade
git status
git add -A
git commit -m "Prepare Raspberry Pi deployment"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

`deploy_pi.sh` refuses a dirty desktop checkout, runs the configuration and
documentation tests, creates `/home/PI_USER/repos/frlg-ldn-trade.git` on the
Pi if needed, pushes the current commit to its `deploy` branch, and creates or
fast-forwards `/home/PI_USER/frlg-ldn-trade`. It never force-resets a Pi
checkout. A Pi checkout with its own uncommitted files is rejected rather than
overwritten.

If the SSH alias already specifies the remote user, explicitly provide the
paths instead:

```bash
./scripts/deploy_pi.sh --host pi-ldn \
  --path /home/PI_USER/frlg-ldn-trade \
  --repo /home/PI_USER/repos/frlg-ldn-trade.git
```

After the first deployment, connect to the Pi and bootstrap it:

```bash
ssh pi-ldn
cd ~/frlg-ldn-trade
./scripts/setup_pi.sh
```

The setup script requires 64-bit Raspberry Pi OS (`aarch64`) and Python 3.11
or newer (Bookworm supplies Python 3.11; current Trixie supplies Python 3.13). It installs the Python virtual environment from `requirements.txt`,
which uses `vendor/LDN`, installs the required system tools, and tells
NetworkManager to leave `ldnclient`, `ldn`, `ldn-mon`, and `ldn-tap` alone.
Use `--no-apt` only after system dependencies are already installed. Use
`--no-networkmanager` only when another network manager is deliberately
responsible for those interfaces.

Keep SSH on Ethernet or the Pi's built-in Wi-Fi. Hosting takes exclusive
control of the TP-Link adapter.

## Machine-local configuration and Switch keys

`config/host.toml` is tracked and already defaults to the proven TP-Link live
profile:

```toml
[host]
live = true
skip_encryption = true
accept_decrypted_ccmp = true

[ldn]
phy = "auto"
```

Create the ignored `config/host.local.toml` on the Pi only when a setting must
vary by machine. Use an absolute key path because the host runs under `sudo`:

```toml
[ldn]
keys_path = "/home/PI_USER/.switch/prod.keys"
```

Install your own `prod.keys` separately. It is never copied by deployment;
the safe installer and SSH streaming example are in [Switch key setup](switch_keys.md).
For a key file already accessible on the Pi:

```bash
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

## Verify and run

Plug in the TP-Link adapter, then run:

```bash
cd ~/frlg-ldn-trade
./scripts/preflight_pi.sh
./scripts/run_mystery_gift.sh
```

Preflight is read-only. It verifies Python and the vendored LDN package,
loads `config/host.toml` plus optional `config/host.local.toml`, verifies the
TP-Link USB ID and `rtw88_8822bu` driver, checks AP and monitor support, checks
the NetworkManager exclusion, and verifies that the configured key file is
mode `0600`. It also rejects an effective TP-Link invocation that disables
either `skip_encryption` or `accept_decrypted_ccmp`; arguments passed through
`run_mystery_gift.sh` are included in that check. The script supplies Debian's
standard `sbin` command paths itself, so it behaves the same in an interactive
shell and through a one-line SSH command.

The normal run command has no Wi-Fi flags because those safe, tested defaults
come from TOML. `run_mystery_gift.sh` runs preflight first and then starts the
live host with root privileges. For a temporary diagnostic override, pass a
normal host option after the script name, for example `--verbose`.

Every `frlgmg_host.py` option is forwarded by the wrapper. View the
authoritative list without running preflight or using root:

```bash
./scripts/run_mystery_gift.sh --help
./scripts/run_mystery_gift.sh --print-effective-config
```

The normal event controls are `--gift`, `--flag-id`, `--verbose`, `--capture`,
`--ot`, `--version`, and `--id`. `--client-ready-idle-frames N` is a Mystery
Gift timing diagnostic for hardware tests; leave it unset for normal use. For
example:

```bash
./scripts/run_mystery_gift.sh --gift celebi --verbose
./scripts/run_mystery_gift.sh --gift solrock-stamp \
  --client-ready-idle-frames 45 --capture /tmp/solrock-45.jsonl
```

To keep an annotated byte listing for a run, add `--make-artifact`. It is off
by default, writes a deterministic `.ram.lst` file under `artifacts/`, and can
be redirected with `--artifact-dir DIR`:

```bash
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact
./scripts/run_mystery_gift.sh --gift worlds-xp --make-artifact \
  --artifact-dir /home/chase/mystery-gift-artifacts
```

The listing records the exact compiled RAM script bytes, decoded instructions,
checksums, branch/message destinations, and its source delivery-stage summary.
Pass `--no-make-artifact` to explicitly disable generation in a saved command.

Leave `--phy`, `--adapter`, `--skip-encryption`, and
`--accept-decrypted-ccmp` at their tracked TP-Link defaults unless diagnosing
different hardware.

## Later desktop changes

For each committed change on the desktop:

```bash
git add -A
git commit -m "Describe the change"
./scripts/deploy_pi.sh --host pi-ldn --user PI_USER
```

The helper fast-forwards code only. If dependency files or `vendor/LDN` change,
the Pi refreshes its virtual environment automatically. To update manually on
the Pi after a successful push, run:

```bash
cd ~/frlg-ldn-trade
./scripts/update_pi.sh
```

Do not edit tracked source files directly on the Pi. Make and test changes on
the desktop, commit them, and deploy. Keep `config/host.local.toml`, Switch
keys, and diagnostic captures Pi-local and ignored.
