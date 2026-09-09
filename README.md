# pokeldn

A computer speaking Nintendo Switch local wireless (LDN) to Pokémon games running on a real
Switch / Switch 2.

Two kinds of target share one wireless layer:

- **FireRed and LeafGreen** — a GBA ROM inside the Switch's emulator. Trading, Mystery Gift, Union
  Room battles and native code on the console all work end to end on retail hardware.
- **Native Switch titles** — **Brilliant Diamond / Shining Pearl** and **Sword / Shield**. Both have
  completed a trade with a retail console: a character this project invented walks in a BDSP Union
  Room and the game runs its own trade flow against it, and a Sword accepted a Pokémon, gave one of
  its own and wrote its save.

The full protocol documentation is at [decryptu.github.io/pokeldn](https://decryptu.github.io/pokeldn/).

The package is layered by what a module is true of, so the game-independent part is visible from the
import line: `pokeldn.ldn` is the wireless layer every Switch title shares, `pokeldn.gba` is the GBA
wireless adapter's protocol that a GBA title speaks on top of it, and `pokeldn.frlg`, `pokeldn.bdsp`
and `pokeldn.swsh` are the games. Entry points are named for the game they drive.

---

## Why?

This project basically exists to prove that it can be done. From here, I'm hoping the community takes notice so that we can get things like an unofficial GTS and online battling going. It should serve as a pretty good reference for anyone interested in pursuing these goals or anything else related to multiplayer within these games. AI tools were used to reverse engineer the protocol and to write parts of the code. If you'd like to contribute to the effort, join the [Discord!](https://discord.gg/PyvaVYnpXC)

## Demonstration
https://github.com/user-attachments/assets/b0df878e-67f0-483d-ae81-583cfc2a8692

This demo was recorded using the **ALFA AWUS036ACHM**. The RZ616 is half as fast on average and sometimes deadlocks before gracefully exiting.

## Features

- End-to-end trading with a real game on a real Switch, in both directions
- `.pk3` / `.ek3` input and output
- Mystery Gift distribution: Wonder Cards with scripted deliveryman gifts, Wonder News, and a
  visiting Battle Tower trainer
- Union Room: greetings, trading-board trades, live chat, and full link battles
- Native code on the console through the gift link: reading and writing its save, mapping its ROM,
  and calling its own functions
- Native Switch titles: LDN discovery, association and a completed trade against Brilliant Diamond /
  Shining Pearl and Sword / Shield, plus an offline toolkit for reading a retail title's own code

## Requirements

- Linux
- Python 3.11+, and a venv with `requirements.txt` installed
- A compatible Wi-Fi card (see below)
- A Switch or Switch 2 with FRLG, played to the point where the Direct Corner has been unlocked
  (~20–40 minutes)
- At least 2 `.pk3` files to serve as party members / trade fodder
- Switch `prod.keys` (default location `~/.switch/prod.keys`)

The required LDN implementation is included in [`vendor/LDN`](vendor/LDN) and is installed
automatically by `pip install -r requirements.txt`. Do not replace it with the similarly versioned
PyPI `ldn` package, which does not contain this project's adapter compatibility fixes.

### Wi-Fi cards

| model | type | driver | reliability |
|---|---|---|---|
| TP-Link Archer T3U (`2357:012d`) | external | `rtw88_8822bu` | high |
| ALFA AWUS036ACHM | external | `mt76x0u` | high |
| Realtek RTL8821CE | internal PCIe | `rtw88_8821ce` | high |
| AMD RZ616 | internal M.2 | `mt7921e` | low |

Known problematic: Intel AX200 (`iwlwifi`) and Atheros AR9271 (`ath9k_htc`) cannot be assigned an IP.

See [Adapters](docs/hardware_adapters.md) for the configuration each one needs.

## Setup

1. Create a Python venv and install `requirements.txt`.
2. Keep NetworkManager away from the LDN interfaces. Marking the Wi-Fi card unmanaged is **not
   enough**: a join creates a fresh `ldnclient` interface mid-run, NetworkManager grabs it and points
   wpa_supplicant at it, and the join fails with `[Errno 114] Match already configured`. Install a
   config that excludes the LDN interfaces by name:

   ```
   # /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
   [keyfile]
   unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap
   ```

   then `sudo systemctl restart NetworkManager`. Name the file `zz-*` so it sorts last: some distros
   ship a later-sorting file that sets `unmanaged-devices=none` and silently overrides yours. Verify
   with `NetworkManager --print-config | grep unmanaged`.
3. Ensure you can become root. The entry points require it.

## Layout

| | |
|---|---|
| [`bin/`](bin) | what you run against a console. FireRed/LeafGreen: `frlg_mg_host.py` (Mystery Gift, Wonder News and native code), `frlg_mg_client.py` (receive a card from a console), `frlg_trade_host.py` (trade and Union Room host), `frlg_trade_join.py` (trade joiner). Native titles: `bdsp_join.py`, `bdsp_pia_probe.py`, `swsh_join.py`, `swsh_connect.py` |
| [`tools/ldn/`](tools/ldn) | the radio, for any target: `ldn_scan.py`, `sniff.py`, `joyspot_probe.py`, `ldn_debug_report.sh` |
| [`tools/frlg/`](tools/frlg) | reading what a FireRed console sent back, offline: `dump_read.py`, `script_read.py`, `rom_functions.py`, `cartridge_pair.py`, `game_data_read.py`, `english_build.py` |
| [`tools/switch/`](tools/switch) | reading a retail Switch title's own code, offline: `xci_read.py`, `romfs_read.py`, `nso_read.py`, `nso_relocs.py`, `nso_imports.py`, `rtti_names.py`, `arm64_xref.py`, `arm64_dis.py` |
| [`pokeldn/`](pokeldn) | the package everything above is made of: `ldn/` the wireless layer, `gba/` the GBA link above it, `frlg/` `bdsp/` `swsh/` the games, `gen8.py` the entity format the two native titles share |
| [`asm/`](asm) | ARM sources for the payloads the console runs; `scripts/gen_buffer_scripts.py` assembles them into `pokeldn/frlg/rom/buffer_payloads.py` |
| [`scripts/`](scripts) | setup, deployment and code generation — not things you point at a console |
| [`config/`](config) | host profiles (`host.toml`, and `host.local.toml` for this machine) |
| [`docs/`](docs) | the protocol findings, each with its citations; published at [decryptu.github.io/pokeldn](https://decryptu.github.io/pokeldn/) |
| [`tests/`](tests) | `python -m pytest tests/ -q` |
| [`vendor/`](vendor) | the bundled LDN implementation and the mt7601u AP-mode driver |

Run the entry points from the repo root: `sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py ...`. They
put the root on `sys.path` themselves, so they work from anywhere, but config files and default output
paths resolve against the working directory.

## Usage

### Join a Switch-hosted trade

```bash
sudo -E ./.venv/bin/python bin/frlg_trade_join.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

### Host a Direct Corner trade

```bash
sudo -E ./.venv/bin/python bin/frlg_trade_host.py -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

Linux advertises the group and acts as the trade leader. With the default settings it offers the
second supplied party member (`PARTY2.pk3`) and writes the Pokémon received from the Switch to
`output.pk3`. Host defaults come from `config/host.toml`, then the optional ignored
`config/host.local.toml`; command-line flags override both.
`bin/frlg_trade_host.py --print-effective-config` inspects the resolved profile without root or Wi-Fi
hardware.

Then:

1. Run the host command and wait for `Hosting Direct Corner`.
2. On the Switch, enter the Direct Corner and choose **Join Group**.
3. Select the Linux trainer and join. The leader performs its room-entry route automatically; wait
   until the host reports that trade selection is active.
4. On the Switch, select the Pokémon to trade away and accept the confirmation.
5. After the trade and save sequence returns to the trade menu, wait for the host prompt, then select
   **CANCEL** and confirm **YES**.
6. Allow the automated room exit and disconnect to finish. The received Pokémon is saved to
   `output.pk3` (or the path passed to `--out`).

Some optional flags:

| flag | options | purpose |
|---|---|---|
| `--verbose` | | verbose protocol output |
| `--phy` | phy name, e.g. `phy1` | Wi-Fi PHY selection |
| `--keys` | `/path/to/prod.keys` | non-default `prod.keys` location |
| `--slot` | zero-based party index | host party member offered in the trade |
| `--capture` | output path | JSONL diagnostic capture |
| `--config` | TOML path | replace the tracked shared host profile |
| `--local-config` / `--no-local-config` | TOML path / | select or disable the machine-local layer |
| `--print-effective-config` | | print the redacted resolved profile and exit |
| `--skip-encryption` | | delegate transmit CCMP to mac80211/hardware; traffic stays encrypted over the air |
| `--accept-decrypted-ccmp` | | accept driver-decrypted RX plaintext with retained CCMP metadata |
| `--ot` | Gen III trainer name | override the default trainer name for this run |
| `--version` | `firered` or `leafgreen` | override the configured game version |
| `--id` | decimal `TID[:SID]` | override the trainer ID, and optionally the secret ID |

`--help` is the authoritative list for each entry point.

### Host a Union Room

`--union-room` advertises on the middle NPC's path instead of the Direct Corner's, which is a
different accept list on the console rather than a different transport.

```bash
sudo -E ./.venv/bin/python bin/frlg_trade_host.py --union-room --union-room-keepalive 120 \
  PARTY1.pk3 PARTY2.pk3
```

The console takes about ten seconds to appear to itself as connected; that wait is the RFU library's
and not a fault. Add `--board-type normal` to register the offered Pokémon on the trading board,
`--union-room-chat` with `--chat-message` or `--chat-file` for chat, and
`--union-room-battle --battle-fight` for a link battle. In a battle the console elects itself master
and computes everything, so the host answers its controller commands rather than running any battle
logic; it needs two non-egg Pokémon at level 30 or lower in its own party or it refuses on its own
screen.

See [The link protocol](docs/frlg_link.md) for the connect sequence, the activity bytes and the link
buffer protocol.

### Trainer identity

All three entry points start from `DEFAULT_TRAINER` in [`pokeldn/config.py`](pokeldn/config.py). Use
`--ot`, `--version` and `--id` for per-run overrides; the ID format is decimal `TID[:SID]`:

```bash
# Set TID to 12345 and retain DEFAULT_TRAINER.sid
./.venv/bin/python bin/frlg_trade_join.py --live --id=12345 PARTY1.pk3 PARTY2.pk3

# Set TID to 12345 and SID to 34567 while hosting
sudo -E ./.venv/bin/python bin/frlg_trade_host.py --live --id=12345:34567 PARTY1.pk3 PARTY2.pk3
```

Each component must be between 0 and 65535, and the resulting 32-bit LinkPlayer ID is
`(SID << 16) | TID`. The resolved profile is used consistently by discovery, Pia Session, RFU game
data, LinkPlayer and trainer-card identity. Edit `DEFAULT_TRAINER` for gender, language, National Dex
or game-completion defaults that have no CLI flag.

### Distribute a Mystery Gift

`bin/frlg_mg_host.py` advertises on the Friend path and sends a Wonder Card plus a delivery RAM
script. The default payload is the repeatable legendary-beast cutscene.

```bash
sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
  --gift beast-cutscene --flag-id 1005 \
  --capture mystery-gift.jsonl
```

On the Switch choose **Mystery Gift → Wonder Cards → Friend**, then select the Linux host. The save
must already have Mystery Gift unlocked. `--make-artifact` writes a `.ram.lst` audit listing of the
exact card and delivery-script bytes a run sent.

The beast depends on the receiving save's starter: Bulbasaur gives Suicune, Squirtle gives Entei,
Charmander gives Raikou. The live host also distributes the two halves of a shared Stamp Rally card
(`--gift solrock-stamp` and `--gift lunatone-stamp`, in either order).

See [Mystery Gift](docs/frlg_gift.md) for the protocol flow, the gift catalogue, the authoring system,
and why the Switch requires the Friend path rather than Wireless Communication.

### Distribute Wonder News

The console's Mystery Gift menu has a second column, and `--news` serves it. Wonder News is 444 bytes
of title and body with no flag ID, no delivery script and no gift attached: the reward is a berry from
the man in the house in Cerulean City. On the Switch choose **Mystery Gift → Wonder News → Friend** — a
Wonder Card host is not listed on that screen, and vice versa.

```bash
sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py --news
sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py --news berry --news-id 7
```

A console keeps news only when it differs from what it already holds, so re-sending identical text is
a deliberate no-op; `--news-id N` makes the same text land again.

### Read the console's save

A Mystery Gift session can run native ARM code on the console, which is enough to read its live save
back — including the two things the game never shows you, the **secret ID** and every party Pokémon's
PID, IVs and nature.

```bash
sudo -E ./.venv/bin/python -u bin/frlg_mg_host.py \
  --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

./.venv/bin/python tools/frlg/dump_read.py dump.bin --block sav2
```

The console stays on its Mystery Gift menu, nothing is written and no Wonder Card changes hands. See
[Code on the console](docs/frlg_rom.md) for the mechanism and the other payloads.

### Native Switch titles

Discovery needs only `prod.keys`; association additionally needs the title's LDN passphrase, which
`bin/bdsp_join.py` and `bin/swsh_join.py` already carry.

**Brilliant Diamond / Shining Pearl.** On the console: any Pokémon Center → 2F → the left attendant →
the plain "yes" (not the password or group option), then wait in the Union Room.

```bash
# see the session without joining it
sudo -E ./.venv/bin/python tools/ldn/ldn_scan.py --channels 1,6,11,36,40,44,48 --dwell 0.8

# associate and hold a seat, logging everything the advertisement says
sudo -E ./.venv/bin/python bin/bdsp_join.py --channels 6 --hold 90
```

A successful join prints the participant table with the console as participant 0 and this machine as
participant 1. **Nothing happens on the console's screen, and that is expected** — LDN association is
below the game.

**Sword / Shield.** Its local communication id is filled at runtime, so the first run is a scan:

```bash
# on the console: Y-Comm -> Link Trade over LOCAL communication, which puts it on the air
sudo -E ./.venv/bin/python bin/swsh_join.py --scan-only
```

Point the scan at a screen where the console **hosts**. On the Mystery Gift local-wireless screen it
is a receiver searching and has nothing to advertise. Everything each advertisement carries is written
to `scratchpad/swsh_net_facts.json`; once the id is known, `--comm-id <hex>` joins it.

### Diagnostics

- `tools/ldn/ldn_scan.py` prints discoverable LDN networks and decoded FRLG application data.
- `tools/ldn/sniff.py` captures advertisement and management traffic from a monitor-capable radio.
- `tools/ldn/ldn_debug_report.sh` records local radio, interface, route and NetworkManager state.
- `--capture FILE` on either host writes the protocol trace as JSONL.

See [Host implementation](docs/frlg_host.md) for the component boundaries, protocol flow, timing
ownership and shutdown sequence.

## Credits

- [kinnay](https://github.com/kinnay) — for the [LDN library](https://github.com/kinnay/LDN) this is
  built upon, and the [NintendoClients wiki](https://github.com/kinnay/NintendoClients/wiki)
- [pokefirered](https://github.com/pret/pokefirered) — a full decompilation of FireRed/LeafGreen,
  including the Switch port

## License

AGPLv3
