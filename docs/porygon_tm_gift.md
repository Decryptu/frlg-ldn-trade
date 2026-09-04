---
title: Porygon TM gift
parent: Mystery Gift
nav_order: 5
---

# Porygon TM Gift

`porygon-tm-gift` is an ordinary composed Wonder Gift containing:

- A Wonder Card with Porygon as its icon.
- A Clefairy overworld sprite three tiles to the player's right, facing west.
- TM29 Psychic followed by TM46 Thief.
- Separate delivery checkpoints so retrying Thief cannot duplicate Psychic.

The card defaults to flag ID `1007`, so the Wonder Card viewer shows `7` in its top-right number.
An explicit `--flag-id` changes both the saved card flag and the displayed `flag_id % 100` number.

## Live host

Use a save with Mystery Gift already unlocked:

```bash
sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
  --live \
  --gift porygon-tm-gift \
  --capture porygon-tm-gift-hardware.jsonl
```

On the Switch choose **Mystery Gift → Wonder Cards → Friend**, select the host, save the card, and
visit the deliveryman on the second floor of a Pokemon Center. Confirm:

1. The card displays Porygon and numeric ID `7`.
2. Clefairy appears three tiles to the player's right.
3. The deliveryman gives TM29 Psychic, then TM46 Thief.
4. A later interaction shows the completed message and gives no duplicate TMs.

This event has offline protocol coverage, but hardware success should be recorded only after the
command above succeeds on a Switch.

## Static tools

Because this is an ordinary composed gift, it is also available to the `.bin` exporter and save
injector:

```bash
./.venv/bin/python -m frlgsim.gift_to_bin --gift porygon-tm-gift

./.venv/bin/python -m frlgsim.save_inject \
  input.sav --out output.sav --gift porygon-tm-gift
```

Always back up a save before injection.

## Offline test

```bash
./.venv/bin/python -B tests/test_porygon_tm_gift.py
```

The focused test verifies card fields, catalog/CLI exposure, exact sprite placement, TM ordering,
completion behavior, Bag-full resume behavior, and an impaired Reliable/RFU transfer.
