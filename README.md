# frlg-ldn-trade

A proof-of-concept demonstrating that it is indeed possible for a computer to interact with Gen 3 Pokémon games running on Switch/Switch 2 via local wireless (LDN).

---

## Why?

This project basically exists to prove that it can be done. From here, I'm hoping the community takes notice so that we can get things like an unofficial GTS and online battling going. It should serve as a pretty good reference for anyone interested in pursuing these goals or anything else related to multiplayer within these games. AI tools were used to reverse engineer the protocol and to write parts of the code. If you'd like to contribute to the effort, join the [Discord!](https://discord.gg/PyvaVYnpXC)

## Demonstration
https://github.com/user-attachments/assets/b0df878e-67f0-483d-ae81-583cfc2a8692

This demo was recorded using the **ALFA AWUS036ACHM**. The RZ616 is half as fast on average and sometimes deadlocks before gracefully exiting.

## Features

- End-to-end trading with a real game running on a real Switch, in both directions
- .pk3/.ek3 input and output
- Mystery Gift distribution: Wonder Cards with scripted deliveryman gifts, Wonder News, and a
  visiting Battle Tower trainer
- Union Room: greetings, trading-board trades, live chat, and full link battles
- Native code on the console through the gift link: reading and writing its save, mapping its ROM,
  and calling its own functions. See [the documentation site](https://decryptu.github.io/frlg-ldn-trade/)

## Requirements
- Linux
- Python 3.11+, and a venv with requirements installed (see requirements.txt)
- a compatible WiFi card (see below)
- A Switch or Switch 2 with FRLG, played to the point where the Direct Corner has been unlocked (~20-40 minutes)
- At least 2 .pk3 files to serve as simulated party members/trade fodder
- Switch prod.keys (the default location is ``~/.switch/prod.keys``)

The required LDN implementation is included in [`vendor/LDN`](vendor/LDN).
It is installed automatically by `pip install -r requirements.txt`; do not
replace it with the similarly versioned PyPI `ldn` package, which does not
contain this project's adapter compatibility fixes.

### Tested WiFi Cards

| Model            | Type           | Driver  | Reliability  |
|------------------|----------------|---------|---------------
| AMD RZ616        | Internal (M.2) | mt7921e | Low          |
| ALFA AWUS036ACHM | External       | mt76x0u | High         |
| TP-Link Archer T3U (`2357:012d`) | External | rtw88_8822bu | High |
| Realtek RTL8821CE | Internal (PCIe 1x) | rtw88_8821ce | High |

### Known Problematic WiFi Cards

| Model            | Type           | Driver  | Issue        |
|------------------|----------------|---------|---------------
| Intel AX200        | Internal (M.2) | iwlwifi | Unable to be assigned ip |
| Atheros AR9271 | External       | ath9k_htc | Unable to be assigned ip (most of the time) |

## Layout

| | |
|---|---|
| [`bin/`](bin) | the four things you run against a console: `frlgmg_host.py` (Mystery Gift, Wonder News and native code), `frlgmg_client.py` (receive a card from a console), `frlgtrade_host.py` (trade and Union Room host), `frlgtrade.py` (trade joiner) |
| [`tools/`](tools) | offline helpers: `dump_read.py` (decode a save dump), plus the radio diagnostics `ldn_scan.py`, `sniff.py`, `joyspot_probe.py`, `ldn_debug_report.sh` |
| [`frlgsim/`](frlgsim) | the package everything above is made of: the LDN/Pia transport, the RFU link, the Mystery Gift server and client, the payload builders |
| [`asm/`](asm) | ARM sources for the payloads the console runs (`scripts/gen_buffer_scripts.py` assembles them into `frlgsim/buffer_payloads.py`) |
| [`scripts/`](scripts) | setup, deployment and code generation - not things you point at a console |
| [`config/`](config) | host profiles (`host.toml`, and `host.local.toml` for this machine) |
| [`docs/`](docs) | the protocol findings, each with its decomp citations; published at [decryptu.github.io/frlg-ldn-trade](https://decryptu.github.io/frlg-ldn-trade/) |
| [`tests/`](tests) | `python -m pytest tests/ -q` |
| [`vendor/`](vendor) | the bundled LDN implementation and the mt7601u AP-mode driver |

Run the entry points from the repo root: `sudo -E ./.venv/bin/python -u bin/frlgmg_host.py ...`.
They put the root on `sys.path` themselves, so they work from anywhere, but the config files and
the default output paths are resolved relative to the working directory.

## Usage

### Join a Switch-hosted trade

Use the original joiner when the Switch is the Direct Corner leader:

```bash
sudo -E ./.venv/bin/python bin/frlgtrade.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

### Host a Direct Corner trade

Start a Direct Corner host with:

```bash
sudo -E ./.venv/bin/python bin/frlgtrade_host.py \
  -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

Linux advertises the group and acts as the trade leader. With the default settings it offers the
second supplied party member (`PARTY2.pk3`) and writes the Pokémon received from the Switch to
`output.pk3`. Host defaults are loaded from `config/host.toml`, then optional ignored
`config/host.local.toml`; command-line flags override both. Run
`bin/frlgtrade_host.py --print-effective-config` to inspect the safe effective profile without root
or Wi-Fi hardware.

**Optional Flags (not comprehensive):**

| Flag         | Options          | Purpose        |
|--------------|------------------|----------------|
| `--verbose` | N/A | Verbose protocol output |
| `--phy` | phy name (for example `phy1`) | Wi-Fi PHY selection |
| `--keys` | `/path/to/prod.keys` | Non-default prod.keys location |
| `--slot` | zero-based party index | Host party member offered in the trade |
| `--capture` | output path | Optional JSONL diagnostic capture |
| `--config` | TOML path | Replace the tracked shared host profile |
| `--local-config` / `--no-local-config` | TOML path / N/A | Select or disable the machine-local layer |
| `--print-effective-config` | N/A | Print the redacted resolved profile and exit |
| `--skip-encryption` | N/A | Delegate transmit CCMP to mac80211/hardware; traffic remains encrypted over the air |
| `--accept-decrypted-ccmp` | N/A | Accept driver-decrypted RX plaintext with retained CCMP metadata |
| `--ot` | Gen III trainer name | Override `DEFAULT_TRAINER.name` for this run |
| `--version` | `firered` or `leafgreen` | Override the configured game version |
| `--id` | decimal `TID[:SID]` | Override the trainer ID, and optionally secret ID |

The command above selects the ALFA profile. The help output is the authoritative list of supported
options for each entry point.

### Host a Union Room

`--union-room` advertises on the middle NPC's path instead of the Direct Corner's, which is a
different accept list on the console rather than a different transport. From the room the console
can greet us, trade off the trading board, chat, or start a full link battle.

```bash
sudo -E ./.venv/bin/python bin/frlgtrade_host.py --union-room --union-room-keepalive 120 \
  PARTY1.pk3 PARTY2.pk3
```

The console takes about ten seconds to appear to itself as connected; that wait is the RFU library's
and not a fault. Add `--board-type normal` to register the offered Pokémon on the trading board,
`--union-room-chat` with `--chat-message` or `--chat-file` for chat, and `--union-room-battle
--battle-fight` for a link battle. In a battle the console elects itself master and computes
everything, so we answer its controller commands rather than running any battle logic; it needs two
non-egg Pokémon at level 30 or lower in its own party or it refuses on its own screen.

See [Console protocol notes](docs/joiner_protocol_notes.md) for the connect sequence, the activity
bytes, and the link buffer protocol.

### Hosting Wi-Fi adapter profiles

These profiles apply when Linux is hosting with `bin/frlgtrade_host.py` or `bin/frlgmg_host.py`; they do not
change the Switch-hosted `bin/frlgtrade.py` joiner.

| Adapter | Linux identity | Normal host configuration |
|---|---|---|
| ALFA AWUS036ACHM | `mt76x0u` | Pass its explicit `--phy phyN`, plus `--skip-encryption --no-accept-decrypted-ccmp` |
| TP-Link Archer T3U | USB `2357:012d`, `rtw88_8822bu` | The checked-in `config/host.toml` profile; no Wi-Fi flags required |

For the TP-Link, use the Direct Corner command shown above. With `phy = "auto"`, its named
adapter profile resolves only the matching `rtw88_8822bu` USB `2357:012d` device; it fails clearly
if the adapter is missing or more than one matches. An explicit `--phy phyN` always wins.

For the ALFA, select its actual PHY explicitly and override the receive compatibility mode:

```bash
sudo -E ./.venv/bin/python bin/frlgtrade_host.py --phy phyN \
  --skip-encryption --no-accept-decrypted-ccmp \
  -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

Despite its historical name, `--skip-encryption` does not make the wireless connection plaintext.
It skips LDN's Python CCMP step and asks mac80211/hardware to apply CCMP once. Both proven adapters
need that transmit mode. The TP-Link's `rtw88_8822bu` monitor interface additionally reports a
Protected frame with its CCMP header and MIC retained around already-decrypted receive data, so it
also needs `--accept-decrypted-ccmp`. That opt-in path trusts the driver's completed decryption and
removes the retained MIC before forwarding the plaintext to `ldn-tap`; keep it disabled for the ALFA.

For an unusual adapter, pass its explicit PHY (for example, `--phy phy0`) after checking `iw dev`.
Startup prints the detected known adapter profile, the active TX/RX modes, and a warning if its flags
do not match the proven profile.

**Setup**
1. Create a Python venv and install all requirements in ``requirements.txt``
2. Keep NetworkManager away from the LDN interfaces. Marking your WiFi card unmanaged is **not enough**: the join creates a fresh `ldnclient` interface mid-run, NetworkManager grabs it and points wpa_supplicant at it, and the join then fails with `[Errno 114] Match already configured`. Install a config that excludes the LDN interfaces by name:

   ```
   # /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
   [keyfile]
   unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap
   ```

   then `sudo systemctl restart NetworkManager`. Name the file `zz-*` so it sorts last: some distros (e.g. Linux Mint's `ubuntu-system-adjustments.conf`) ship a later-sorting file that sets `unmanaged-devices=none` and silently overrides yours. Verify with `NetworkManager --print-config | grep unmanaged` - it must show the `interface-name:ldn...` list. (Stopping NetworkManager entirely also works, but the config file is a one-time setup that survives reboots.)
3. Ensure you can become root. The script requires root to run.

### Trainer identity

All three entry points start from `DEFAULT_TRAINER` in
[`frlgsim/config.py`](frlgsim/config.py). Use `--ot`, `--version`, and `--id` for per-run overrides.
The ID format is decimal `TID[:SID]`:

```bash
# Set TID to 12345 and retain DEFAULT_TRAINER.sid
./.venv/bin/python bin/frlgtrade.py --live --id=12345 PARTY1.pk3 PARTY2.pk3

# Set TID to 12345 and SID to 34567 while hosting
sudo -E ./.venv/bin/python bin/frlgtrade_host.py --live --id=12345:34567 PARTY1.pk3 PARTY2.pk3
```

Each component must be between 0 and 65535. The resulting 32-bit LinkPlayer ID is encoded as
`(SID << 16) | TID`. The resolved profile is used consistently by discovery, Pia Session, RFU game
data, LinkPlayer, and trainer-card identity. Edit `DEFAULT_TRAINER` for gender, language, National
Dex, or game-completion defaults that do not have CLI flags.

### Distribute a Mystery Gift

`bin/frlgmg_host.py` advertises on the hardware-compatible Friend path and sends a Wonder Card plus a
delivery RAM script. The default payload is the repeatable legendary-beast cutscene; use
`--gift celebi` for the composed level-50 Celebi card.

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
  --gift beast-cutscene --flag-id 1005 \
  --capture mystery-stamps-hardware.jsonl
```

That command uses the checked-in TP-Link Archer T3U profile: live hosting, delegated transmit CCMP,
and retained-CCMP receive normalization are already enabled. For the ALFA, provide its explicit
`--phy phyN --skip-encryption --no-accept-decrypted-ccmp` overrides instead.

On the Switch choose **Mystery Gift → Wonder Cards → Friend**, then select the Linux host. The save
must already have Mystery Gift unlocked. The host accepts the same `--ot`, `--version`, and decimal
`--id TID[:SID]` identity overrides as the trade programs; run `bin/frlgmg_host.py --help` for all gift
and transport options.

To retain a readable audit listing of the exact Wonder Card and delivery-script
bytes sent by a run, add `--make-artifact`. It is disabled by default and writes
to `artifacts/`; choose another destination with `--artifact-dir DIR`:

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
  --gift worlds-xp --make-artifact --artifact-dir artifacts
```

The generated `.ram.lst` file includes raw opcode bytes, decoded field
instructions, branch/message targets, checksums, and the source delivery-stage
plan. Use `--no-make-artifact` to explicitly disable it in an automated command.

The beast depends on the receiving save's starter: Bulbasaur gives Suicune, Squirtle gives Entei,
and Charmander gives Raikou. See [the legendary-beast gift guide](docs/legendary_beast_gift.md) for
the reward sequence, binary export, and save-injection tools.

The live host also distributes the two halves of a shared Stamp Rally card. Run it once with
`--gift solrock-stamp` and later with `--gift lunatone-stamp` (in either order). Stamp events
default to card flag ID `1006`; after each stamp, the deliveryman gives its level-30 Pokémon, then
gives level-50 Celebi when both rewards have been collected. See the
[Stamp Rally guide](docs/stamp_rally.md) for state, protocol pseudocode, and hardware checks. These
dynamic events are intentionally unavailable in the static `.bin` exporter and save injector.

The composed `--gift celebi` and `--gift porygon-tm-gift` events use the shared delivery-stage
compiler. Porygon displays a Porygon card, makes Clefairy appear three tiles to the player's right,
and delivers TM29 Psychic followed by TM46 Thief. See the [Porygon TM Gift
guide](docs/porygon_tm_gift.md) for live, export, injection, and test commands.

### Distribute Wonder News

The console's Mystery Gift menu has a second column, and `--news` serves it. Wonder News is 444
bytes of title and body with no flag ID, no delivery script and no gift attached: the reward is a
BERRY from the man in the house in Cerulean City. On the Switch choose **Mystery Gift → Wonder News
→ Friend** - a Wonder Card host is not listed on that screen, and vice versa.

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py --news
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py --news berry --news-id 7
```

A console keeps news only when it differs from what it already holds, so re-sending the identical
text is a deliberate no-op; `--news-id N` changes one field and makes the same text land again. See
[the Wonder News guide](docs/wonder_news.md) for the struct, the advertisement change it needs, and
the one place where the console answers the host back.

### Read the console's save

A Mystery Gift session can run native ARM code on the console, which is enough to read its live save
back. That covers the two things the game never shows you: the **secret ID**, and every party
Pokémon's PID, IVs and nature.

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
  --buffer-script save-dump --dump-block sav2 --dump-size 64 --dump-file dump.bin

./.venv/bin/python tools/dump_read.py dump.bin --block sav2
```

The console stays on its Mystery Gift menu, nothing is written and no Wonder Card changes hands. See
[Reading the save](docs/reading_the_save.md) for the party dump, the gotchas, and what else the same
payload reaches; [Native code on the console](docs/buffer_script.md) has the mechanism and the other
payloads built on it.

See [the Mystery Gift distributor guide](docs/mystery_gift_distributor.md) for the protocol flow, payload,
test commands, and why the Switch requires the Friend path rather than Wireless Communication.
New events can be assembled from validated delivery stages, rewards, messages, sprites, battles,
and up to six stamp slots; see the [composable gift authoring guide](docs/mystery_gift_composer.md).

### Hosting diagnostics

- `tools/ldn_scan.py` prints discoverable LDN networks and decoded FRLG application data.
- `tools/sniff.py` captures advertisement and management traffic from a monitor-capable radio.
- `tools/ldn_debug_report.sh` records local radio, interface, route, and NetworkManager state for debugging.
- `bin/frlgtrade_host.py --capture FILE` writes the host protocol trace as JSONL.
- `bin/frlgmg_host.py --capture FILE` writes the Mystery Gift host trace as JSONL.

See [the host design document](docs/frlgtrade_host_design.md) for the component boundaries, protocol
flow, timing ownership, trainer propagation, and shutdown sequence.

**Step-by-step Usage**

1. Run the host command and wait for `Hosting Direct Corner`.
2. On the Switch, enter the Direct Corner and choose **Join Group**.
3. Select the Linux trainer (`EMU` by default) and join. The Linux leader performs its room-entry
   route automatically; wait until the host reports that trade selection is active.
4. On the Switch, select the Pokémon to trade away and accept the confirmation. With the example
   command, the Switch receives `PARTY2.pk3`.
5. After the trade and save sequence returns to the trade menu, wait for the host prompt, then select
   **CANCEL** and confirm **YES**.
6. Allow the automated room exit and disconnect to finish. The received Pokémon is saved as
   `output.pk3` (or the path passed to `--out`).

## Credits
- [kinnay](https://github.com/kinnay) - For the [LDN library](https://github.com/kinnay/LDN) this is built upon, and the excellent [NintendoClients Wiki](https://github.com/kinnay/NintendoClients/wiki)
- [pokefirered](https://github.com/pret/pokefirered) - A full decompilation of FireRed/LeafGreen, including the Switch port. It served as an important reference.

## License
AGPLv3
