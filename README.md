# frlg-ldn-trade

A proof-of-concept demonstrating that it is indeed possible for a computer to interact with Gen 3 Pokémon games running on Switch/Switch 2 via local wireless (LDN).

---

## Why?

This project basically exists to prove that it can be done. From here, I'm hoping the community takes notice so that we can get things like an unofficial GTS and online battling going. It should serve as a pretty good reference for anyone interested in pursuing these goals or anything else related to multiplayer within these games. And before you ask, yes, **AI tools were used extensively during the creation of this project**. Difficult to call it "vibe coding" though, Claude required A LOT of steering and was basically lost without me laying out the path forward step-by-step. The main benefit was massively speeding up the reverse engineering work. If you'd like to contribute to the effort, join the [Discord!](https://discord.gg/PyvaVYnpXC)

## Demonstration
https://github.com/user-attachments/assets/b0df878e-67f0-483d-ae81-583cfc2a8692

This demo was recorded using the **ALFA AWUS036ACHM**. The RZ616 is half as fast on average and sometimes deadlocks before gracefully exiting.

## Features

- End-to-end trading with a real game running on a real Switch
- .pk3/.ek3 input and output
- Mystery Gift distribution with a Wonder Card and scripted deliveryman gift

## Requirements
- Linux
- Python 3.12+, and a venv with requirements installed (see requirements.txt)
- a compatible WiFi card (see below)
- A Switch or Switch 2 with FRLG, played to the point where the Direct Corner has been unlocked (~20-40 minutes)
- At least 2 .pk3 files to serve as simulated party members/trade fodder
- Switch prod.keys (the default location is ``~/.switch/prod.keys``)

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

## Usage

### Join a Switch-hosted trade

Use the original joiner when the Switch is the Direct Corner leader:

```bash
sudo -E ./.venv/bin/python frlgtrade.py --live -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

### Host a Direct Corner trade

Start a Direct Corner host with:

```bash
sudo -E ./.venv/bin/python frlgtrade_host.py --live \
  --skip-encryption --no-accept-decrypted-ccmp \
  -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

Linux advertises the group and acts as the trade leader. With the default settings it offers the
second supplied party member (`PARTY2.pk3`) and writes the Pokémon received from the Switch to
`output.pk3`. Run `frlgtrade_host.py --help` for the complete operational CLI.

**Optional Flags (not comprehensive):**

| Flag         | Options          | Purpose        |
|--------------|------------------|----------------|
| `--verbose` | N/A | Verbose protocol output |
| `--phy` | phy name (for example `phy1`) | Wi-Fi PHY selection |
| `--keys` | `/path/to/prod.keys` | Non-default prod.keys location |
| `--slot` | zero-based party index | Host party member offered in the trade |
| `--capture` | output path | Optional JSONL diagnostic capture |
| `--skip-encryption` | N/A | Delegate transmit CCMP to mac80211/hardware; traffic remains encrypted over the air |
| `--accept-decrypted-ccmp` | N/A | Accept driver-decrypted RX plaintext with retained CCMP metadata |
| `--ot` | Gen III trainer name | Override `DEFAULT_TRAINER.name` for this run |
| `--version` | `firered` or `leafgreen` | Override the configured game version |
| `--id` | decimal `TID[:SID]` | Override the trainer ID, and optionally secret ID |

The command above selects the ALFA profile. The help output is the authoritative list of supported
options for each entry point.

### Hosting Wi-Fi adapter profiles

These profiles apply when Linux is hosting with `frlgtrade_host.py` or `frlgmg_host.py`; they do not
change the Switch-hosted `frlgtrade.py` joiner.

| Adapter | Linux identity | Required host flags |
|---|---|---|
| ALFA AWUS036ACHM | `mt76x0u` | `--skip-encryption --no-accept-decrypted-ccmp` |
| TP-Link Archer T3U | USB `2357:012d`, `rtw88_8822bu` | `--skip-encryption --accept-decrypted-ccmp` |

For the ALFA, run the Direct Corner command shown above. For the TP-Link, use:

```bash
sudo -E ./.venv/bin/python frlgtrade_host.py --live \
  --skip-encryption --accept-decrypted-ccmp \
  -o output.pk3 PARTY1.pk3 PARTY2.pk3
```

Despite its historical name, `--skip-encryption` does not make the wireless connection plaintext.
It skips LDN's Python CCMP step and asks mac80211/hardware to apply CCMP once. Both proven adapters
need that transmit mode. The TP-Link's `rtw88_8822bu` monitor interface additionally reports a
Protected frame with its CCMP header and MIC retained around already-decrypted receive data, so it
also needs `--accept-decrypted-ccmp`. That opt-in path trusts the driver's completed decryption and
removes the retained MIC before forwarding the plaintext to `ldn-tap`; keep it disabled for the ALFA.

`--phy auto` selects an AP-capable PHY. If both adapters are attached, pass the intended PHY
explicitly (for example, `--phy phy0`) after checking `iw dev`. Startup now prints the detected known
adapter profile, the active TX/RX modes, and a warning if its flags do not match the proven profile.

**Setup**
1. Create a Python venv and install all requirements in ``requirements.txt``
2. Keep NetworkManager away from the LDN interfaces. Marking your WiFi card unmanaged is **not enough**: the join creates a fresh `ldnclient` interface mid-run, NetworkManager grabs it and points wpa_supplicant at it, and the join then fails with `[Errno 114] Match already configured`. Install a config that excludes the LDN interfaces by name:

   ```
   # /etc/NetworkManager/conf.d/zz-ldn-unmanaged.conf
   [keyfile]
   unmanaged-devices=interface-name:ldnclient;interface-name:ldn;interface-name:ldn-mon;interface-name:ldn-tap
   ```

   then `sudo systemctl restart NetworkManager`. Name the file `zz-*` so it sorts last: some distros (e.g. Linux Mint's `ubuntu-system-adjustments.conf`) ship a later-sorting file that sets `unmanaged-devices=none` and silently overrides yours. Verify with `NetworkManager --print-config | grep unmanaged` — it must show the `interface-name:ldn...` list. (Stopping NetworkManager entirely also works, but the config file is a one-time setup that survives reboots.)
3. Ensure you can become root. The script requires root to run.

### Trainer identity

All three entry points start from `DEFAULT_TRAINER` in
[`frlgsim/config.py`](frlgsim/config.py). Use `--ot`, `--version`, and `--id` for per-run overrides.
The ID format is decimal `TID[:SID]`:

```bash
# Set TID to 12345 and retain DEFAULT_TRAINER.sid
./.venv/bin/python frlgtrade.py --live --id=12345 PARTY1.pk3 PARTY2.pk3

# Set TID to 12345 and SID to 34567 while hosting
sudo -E ./.venv/bin/python frlgtrade_host.py --live --id=12345:34567 PARTY1.pk3 PARTY2.pk3
```

Each component must be between 0 and 65535. The resulting 32-bit LinkPlayer ID is encoded as
`(SID << 16) | TID`. The resolved profile is used consistently by discovery, Pia Session, RFU game
data, LinkPlayer, and trainer-card identity. Edit `DEFAULT_TRAINER` for gender, language, National
Dex, or game-completion defaults that do not have CLI flags.

### Distribute a Mystery Gift

`frlgmg_host.py` advertises on the hardware-compatible Friend path and sends a Wonder Card plus a
delivery RAM script. On `mystery_stamps`, the default payload is the repeatable legendary-beast
cutscene; use `--gift celebi` for the original level-50 Celebi card.

```bash
sudo -E ./.venv/bin/python -u frlgmg_host.py --live \
  --gift beast-cutscene --flag-id 1005 \
  --capture mystery-stamps-hardware.jsonl
```

That command uses Mystery Gift's ALFA-compatible defaults. With the TP-Link Archer T3U, add
`--accept-decrypted-ccmp`; the adapter-profile section above gives both complete flag sets.

On the Switch choose **Mystery Gift → Wonder Cards → Friend**, then select the Linux host. The save
must already have Mystery Gift unlocked. The host accepts the same `--ot`, `--version`, and decimal
`--id TID[:SID]` identity overrides as the trade programs; run `frlgmg_host.py --help` for all gift
and transport options.

The beast depends on the receiving save's starter: Bulbasaur gives Suicune, Squirtle gives Entei,
and Charmander gives Raikou. See [the legendary-beast gift guide](docs/legendary_beast_gift.md) for
the reward sequence, binary export, and save-injection tools.

The live host also distributes the two halves of a shared Stamp Rally card. Run it once with
`--gift solrock-stamp` and later with `--gift lunatone-stamp` (in either order). Stamp events
default to card flag ID `1006`; after each stamp, the deliveryman gives its level-30 Pokémon, then
gives level-50 Celebi when both rewards have been collected. See the
[Stamp Rally guide](docs/stamp_rally.md) for state, protocol pseudocode, and hardware checks. These
dynamic events are intentionally unavailable in the static `.bin` exporter and save injector.

The composed `--gift porygon-tm-gift` event displays a Porygon card, makes Clefairy appear three
tiles to the player's right, and delivers TM29 Psychic followed by TM46 Thief. See the
[Porygon TM Gift guide](docs/porygon_tm_gift.md) for live, export, injection, and test commands.

See [the Mystery Gift distributor guide](MYSTERY_GIFT_DISTRIBUTOR.md) for the protocol flow, payload,
test commands, and why the Switch requires the Friend path rather than Wireless Communication.
New events can be assembled from validated delivery stages, rewards, messages, sprites, battles,
and up to six stamp slots; see the [composable gift authoring guide](docs/mystery_gift_composer.md).

### Hosting diagnostics

- `ldn_scan.py` prints discoverable LDN networks and decoded FRLG application data.
- `sniff.py` captures advertisement and management traffic from a monitor-capable radio.
- `ldn_debug_report.sh` records local radio, interface, route, and NetworkManager state for debugging.
- `frlgtrade_host.py --capture FILE` writes the host protocol trace as JSONL.
- `frlgmg_host.py --capture FILE` writes the Mystery Gift host trace as JSONL.

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
