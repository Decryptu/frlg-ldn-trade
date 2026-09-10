---
title: Switch keys on the Pi
parent: Hardware and setup
nav_order: 3
---

# Installing Switch keys on the Raspberry Pi

`prod.keys` is a credential for your own Switch, required by the live LDN host.
It is not part of this repository or its deployment workflow. Do not commit
it, paste it into configuration, include it in a capture, or copy a desktop
virtual environment to the Pi.

The normal per-user location is:

```text
/home/PI_USER/.switch/prod.keys
```

The host is started with `sudo`; use this absolute path in the Pi's ignored
local configuration. `~` does not resolve to the login account under `sudo`.

## Install locally on the Pi

Run the installer as the Pi login user. It creates `~/.switch` with
mode `0700`, installs the file with mode `0600`, and never displays the
contents:

```bash
cd ~/pokeldn
./scripts/install_switch_keys.sh --source /absolute/path/to/prod.keys
```

Re-running it retains an identical existing key file and repairs its
permissions. The source must be a readable regular file at an absolute path.
The installer also reads standard input, which transfers the key over an SSH
tunnel with no staging copy:

```bash
# Run on the desktop. pi-ldn is your existing SSH alias/tunnel.
KEY_SOURCE="$HOME/.switch/prod.keys"
ssh pi-ldn 'cd ~/pokeldn && ./scripts/install_switch_keys.sh --stdin' \
  < "$KEY_SOURCE"
```

Invoked with `sudo`, the installer restarts as `$SUDO_USER`; the source must
still be readable by the Pi login user.

## SCP through an SSH alias

With SCP, stage inside a private directory and remove the staging file after
installation:

```bash
# Run on the desktop; pi-ldn is your SSH alias/tunnel.
KEY_SOURCE="$HOME/.switch/prod.keys"
ssh pi-ldn 'install -d -m 700 "$HOME/.frlg-ldn-provision"'
scp -p "$KEY_SOURCE" pi-ldn:.frlg-ldn-provision/prod.keys
ssh pi-ldn 'cd ~/pokeldn && \
  ./scripts/install_switch_keys.sh --source "$HOME/.frlg-ldn-provision/prod.keys" && \
  rm -f "$HOME/.frlg-ldn-provision/prod.keys" && \
  rmdir "$HOME/.frlg-ldn-provision"'
```

`scp -p` preserves the local file mode. Do not stage in a shared directory
such as `/tmp`.

After either method, verify ownership and permissions:

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

Keep that override ignored by Git. A deployment updates code only; it does
not overwrite or transfer `prod.keys`.
