---
title: Legendary-beast gift
nav_order: 9
---

# Legendary-Beast Mystery Gift

One focused payload of the hardware-proven Mystery Gift host: a
deliveryman cutscene that gives two rare berries and a Master Ball, then starts a wild legendary
beast battle. The host, binary exporter, and save injector all select this payload by default.
Their only gift-specific controls are `--gift` and `--flag-id`; each named gift owns all of its
card text, graphics, rewards, encounter parameters, and delivery-script behavior. The live event is
authored with the composable delivery system; the older byte-exact builder remains available in
`frlgsim.wonder_card` for compatibility checks.

## Live Switch distribution

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
  --live \
  --gift beast-cutscene \
  --flag-id 1005 \
  --capture mystery-stamps-hardware.jsonl
```

On the Switch, choose **Mystery Gift → Wonder Cards → Friend**, select the distributor, and save the
card. Talk to the deliveryman on the second floor of a Pokémon Center to start the event.

The receiving save's starter determines the encounter:

| Starter | Legendary beast |
|---|---|
| Bulbasaur | Suicune |
| Squirtle | Entei |
| Charmander | Raikou |

The script gives the Lansat Berry and Liechi Berry before choosing the starter branch. Conditional
stages show the matching beast, then a shared stage gives a Master Ball, and a conditional terminal
battle stage starts the selected encounter. The saved script remains available and the deliveryman
event can be triggered again. Back up the save before testing a repeat run.

The encounter is fixed at level 65. `--flag-id` uses the shared Wonder Card range 1000 through
1019. The composed level-50 Celebi payload remains available with `--gift celebi`.

## Export the paired `.bin` files

```bash
./.venv/bin/python -m frlgsim.gift_to_bin \
  --gift beast-cutscene --flag-id 1005 \
  --out-dir exported-gift
```

This writes a 336-byte Wonder Card file and a 1004-byte RAM-script file, including the checksums and
padding expected by `pokemon-gen3-mysterygift-tool`. Use `--name NAME` to choose the filename stem.

## Inject a test save

Always preserve an untouched backup. By default, the injector writes a new `<save>.gift.sav` file:

```bash
./.venv/bin/python -m frlgsim.save_inject game.sav \
  --gift beast-cutscene --flag-id 1005
```

The injector selects the active FRLG save slot, writes the Wonder Card and RAM script, and rebuilds
the card CRC, RAM-script CRC, and affected flash-sector checksum. `--in-place` is available only
when overwriting the source save is intentional.

## Offline verification

```bash
./.venv/bin/python tests/test_mystery_stamps.py
./.venv/bin/python tests/test_mystery_gift_end_to_end.py
```

The focused tests lock the authoritative cutscene bytes and cover all three starter branches,
virtual-address relocation, reward ordering, repeatability, payload size and CRCs, `.bin` geometry,
save validation, CLI defaults, and the impaired full-stack Mystery Gift flow.
