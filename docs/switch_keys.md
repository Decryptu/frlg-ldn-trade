---
title: Switch keys on the Pi
nav_order: 7
---

# Installing Switch keys on the Raspberry Pi

`prod.keys` is a credential for your own Switch. It is required by the live
LDN host, but is deliberately not part of this repository or its deployment
workflow. Do not commit it, paste it into configuration, include it in a
capture, or copy a desktop virtual environment to the Pi.

The normal per-user location is:

```text
/home/PI_USER/.switch/prod.keys
```

The host is commonly started with `sudo`; therefore use this absolute path in
the Pi's ignored local configuration. Do not depend on `~` resolving to the
right account under `sudo`.

## Install locally on the Pi

After the project is deployed, run the installer as the Pi login user. It
creates `~/.switch` with mode `0700`, installs the file with mode `0600`, and
never displays the contents:

```bash
cd ~/frlg-ldn-trade
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

It is safe to run again: an identical existing key file is retained and its
permissions are repaired. The source must be a readable regular file and an
explicit absolute path. The installer also supports standard input, which is
usually the best way to transfer the key over an SSH tunnel:

```bash
# Run on the desktop. pi-ldn is your existing SSH alias/tunnel.
KEY_SOURCE="$HOME/.switch/prod.keys"
ssh pi-ldn 'cd ~/frlg-ldn-trade && ./scripts/install_switch_keys.sh --stdin' \
  < "$KEY_SOURCE"
```

If you invoke the installer with `sudo`, it intentionally restarts as
`$SUDO_USER`, rather than using `/root/.switch` or reading a user-supplied
source as root. Its source therefore still needs to be readable by the Pi
login user. Running it directly as that user is preferred.

## SCP through an SSH alias

Use the streaming method above when possible: it leaves no staging copy on the
Pi. If you need SCP, stage inside a private directory and remove the staging
file immediately after a successful installation:

```bash
# Run on the desktop; pi-ldn is your SSH alias/tunnel.
KEY_SOURCE="$HOME/.switch/prod.keys"
ssh pi-ldn 'install -d -m 700 "$HOME/.frlg-ldn-provision"'
scp -p "$KEY_SOURCE" pi-ldn:.frlg-ldn-provision/prod.keys
ssh pi-ldn 'cd ~/frlg-ldn-trade && \
  ./scripts/install_switch_keys.sh --source "$HOME/.frlg-ldn-provision/prod.keys" && \
  rm -f "$HOME/.frlg-ldn-provision/prod.keys" && \
  rmdir "$HOME/.frlg-ldn-provision"'
```

The private staging directory prevents other local accounts from traversing to
the temporary file. `scp -p` also preserves an already-restrictive local file
mode. Do not use a shared directory such as `/tmp` for the staging copy.

After either method, verify only ownership and permissions—not key contents:

```bash
ssh pi-ldn 'stat -c "%a %U %n" "$HOME/.switch" "$HOME/.switch/prod.keys"'
# Expected: 700 PI_USER /home/PI_USER/.switch
#           600 PI_USER /home/PI_USER/.switch/prod.keys
```

The Pi's machine-local host override should point `keys_path` at the absolute path:

```toml
[ldn]
keys_path = "/home/PI_USER/.switch/prod.keys"
```

Keep that override ignored by Git. A future deployment updates code only; it
does not overwrite or transfer `prod.keys` again.
