# Solrock and Lunatone Stamp Rally

The live Mystery Gift host has two Stamp Rally events:

```bash
sudo -E ./.venv/bin/python -u frlgmg_host.py --live \
  --gift solrock-stamp --capture solrock-stamp.jsonl

sudo -E ./.venv/bin/python -u frlgmg_host.py --live \
  --gift lunatone-stamp --capture lunatone-stamp.jsonl
```

Both events use one `SUN AND MOON RALLY` card with a Claydol card/metadata icon, two stamp slots,
a suppressed numeric card ID, and default flag ID `1006`. An explicit `--flag-id 1000..1019` overrides that
default for both events. Receive the events in either order. The host installs the shared card if
there is no card, offers FRLG's normal toss prompt for a different card, or appends a new stamp to
a matching rally card.

The rally events are live-host-only. `gift_to_bin.py` and `save_inject.py` continue to support only
`beast-cutscene` and `celebi`, because an individual stamp is a stateful protocol exchange rather
than a static card/script pair.

## Saved state and rewards

| State | Meaning |
|---|---|
| `VAR_MYSTERY_GIFT_1 = 0/1/2` | Solrock absent / eligible / received |
| `VAR_MYSTERY_GIFT_2 = 0/1/2` | Lunatone absent / eligible / received |
| `FLAG_MYSTERY_GIFT_DONE` | Celebi received |
| card receipt flag | synchronized when Celebi succeeds |

This hardware-proven legacy rally intentionally retains its original two-variable layout. New
rallies authored with the [composable gift system](mystery_gift_composer.md) reserve
`VAR_MYSTERY_GIFT_1` for completion stages and assign stamp slots to
`VAR_MYSTERY_GIFT_2..7`.

The deliveryman gives Solrock at level 30 for its stamp and Lunatone at level 30 for its stamp.
Once both are received, he gives Celebi at level 50. All use standard `givemon`, so they receive the
player's OT/TID, default level-up moves, no held item, and a normal random personality. A Pokémon
sent to either the party or PC counts as success. If both are full, no state advances and the player
can make room and retry. If both stamps are pending, all three Pokémon are delivered in one visit.

Installing a new rally card uses FRLG's normal card-save cleanup to clear the two state variables
and `FLAG_MYSTERY_GIFT_DONE`. Its installation activation also clears the receipt flag selected by
the card's flag ID, so a deliberate reinstall starts a fresh rally.

## Host distribution pseudocode

```text
send SEND_GAME_DATA client script
receive and validate GAME_DATA

matching =
    saved flag ID == distribution flag ID
    and max stamps == 2
    and metadata icon species == CLAYDOL

if no card:
    install shared card + persistent delivery script + selected stamp
    run install activation (clear receipt flag, mark selected reward eligible)
else if not matching:
    ask whether to toss the existing card
    if declined: cancel
    if accepted: perform the new-card installation above
else if selected stamp species or ID already exists:
    return HAS_STAMP without running activation
else if neither stamp slot is fully empty:
    return NO_ROOM_STAMPS without running activation
else:
    save selected stamp
    run ordinary activation (mark only selected reward eligible)
    return STAMP_RECEIVED
```

The activation data is a Mystery Event wrapper containing `runscript`, followed by an embedded
ordinary field script. It is sent only after the server has established that the stamp is new and
that the metadata contains a genuinely empty slot.

## Delivery RAM-script pseudocode

```text
lock; faceplayer

if DONE:
    synchronize card receipt flag
    explain that the rally is complete
    release; end

if SOLROCK_STATE == ELIGIBLE:
    explain the Solrock reward
    givemon SOLROCK, 30
    if party and PC are full: explain, then release; end
    SOLROCK_STATE = RECEIVED

if LUNATONE_STATE == ELIGIBLE:
    explain the Lunatone reward
    givemon LUNATONE, 30
    if party and PC are full: explain, then release; end
    LUNATONE_STATE = RECEIVED

if both states == RECEIVED:
    announce the grand prize
    givemon CELEBI, 50
    if party and PC are full: explain, then release; end
    set DONE and the card receipt flag
    announce completion
else:
    explain which stamp is still needed (or welcome the player)

release; end
```

The generated script uses `setvaddress`, virtual branches/messages, and persistent `end`. It never
executes `endram`, so incomplete rewards remain available on later deliveryman visits.

## Hardware sequence

Use a backed-up save with Mystery Gift unlocked. Receive `solrock-stamp`, collect Solrock, then
receive `lunatone-stamp` without tossing the shared card. The next deliveryman visit should give
Lunatone and Celebi. A later visit must show the completion dialogue without another Pokémon.
Repeat with the events reversed where practical. Preserve both JSONL traces when diagnosing any
failure; the normal close grace and host cleanup should complete after each distribution.
