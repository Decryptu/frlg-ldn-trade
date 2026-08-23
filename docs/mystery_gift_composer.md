# Composable Mystery Gift Authoring

`frlgsim.gift_composer` builds Wonder Cards and deliveryman scripts from immutable Python
definitions. The live `beast-cutscene`, `celebi`, `porygon-tm-gift`, and Sun/Moon Stamp Rally
entries are registered as composed gifts. The byte-exact legacy Celebi and legendary-beast builders
remain in `frlgsim.wonder_card` for compatibility tests and older callers.

## One top-level gift type

Every composed event is a `WonderGift`:

```python
WonderGift(
    slug="event-slug",
    card=WonderCardSpec(...),
    intro_message="The deliveryman introduces the event.",
    event=GiftSpec() or StampRallySpec(...),
    delivery=DeliveryPlan(delivery=(...shared stages...)),
    completed_message="The event is already complete.",
)
```

`GiftSpec` contains only behavior exclusive to an ordinary gift: whether it is repeatable and
whether the received Wonder Card may be shared onward. Card presentation, dialogue, and reward
stages belong to `WonderGift`. `StampRallySpec` contains only rally orchestration: slots and
completion hooks.

`DeliveryPlan` always has three immutable stage sequences:

```python
DeliveryPlan(
    pre_stages=(...),
    delivery=(...),
    post_stages=(...),
)
```

Their roles depend on where the plan appears:

- `WonderGift.delivery` uses only `delivery`; it is the reusable middle of the event.
- `StampSlot.delivery` uses only `pre_stages` and `post_stages`.
- `StampRallySpec.completion` uses only `pre_stages` and `post_stages`.

The compiler rejects stages in an unsupported section instead of silently ignoring them.

## Ordinary gifts

An ordinary gift selects `GiftSpec` and puts its stages in the shared middle:

```python
from frlgsim.gift_composer import (
    AnyOf, BattlePokemon, DeliveryPlan, DeliveryStage, GiftSpec, GiveItem,
    Message, Not, RelativeToPlayer, ShowSprite, VarEquals, WonderCardSpec,
    WonderGift,
)

MEWTWO_GIFT = WonderGift(
    slug="mewtwo-encounter",
    card=WonderCardSpec(
        icon_species=150,
        title="MYSTERIOUS ENCOUNTER",
        subtitle="A powerful presence",
        body=("Visit the deliveryman.",),
        footer1="frlg-ldn-trade",
        default_flag_id=1008,
    ),
    intro_message="A powerful presence is waiting!",
    event=GiftSpec(shareable="once"),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message("Take this before you go."),
            GiveItem(1),  # Master Ball
        ),
        DeliveryStage(
            ShowSprite(0, RelativeToPlayer(dx=1)),
            Message("Prepare yourself!"),
            BattlePokemon(150, level=70),
        ),
    )),
    completed_message="That mysterious encounter is over.",
)
```

The compiler shows `intro_message`, resumes the top-level stages using `VAR_MYSTERY_GIFT_1`, and
sets `FLAG_MYSTERY_GIFT_DONE` plus the card receipt flag on success. A later visit shows only
`completed_message`. `GiftSpec(repeatable=True)` resets the cursor instead.

`GiftSpec.shareable` maps to the Wonder Card `sendType` bits:

| Value | Game behavior |
|---|---|
| `"never"` | Cannot be shared onward. |
| `"once"` | Can be shared once; the receiving game flips the card to not shareable. |
| `"always"` | Can continue to be shared after receipt. |

Each `DeliveryStage` is one checkpoint. If its fallible reward fails, that stage is offered again;
successful earlier stages are skipped. Do not put two fallible rewards (`GiveItem`, `GivePokemon`,
or `GiveEgg`) in one stage.

A stage may have `condition=...`. When the condition is false, the compiler skips that stage's
actions but still advances the cursor by one. This is useful for mutually exclusive branches that
must not be re-tested after a later stage fails. Supported condition expressions are `VarEquals`,
`FlagSet`, `Not`, `AllOf`, and `AnyOf`:

```python
DeliveryStage(
    ShowSprite(142, RelativeToPlayer(dx=1)),
    condition=VarEquals(0x4031, 0),  # VAR_STARTER_MON == Bulbasaur
)
DeliveryStage(
    BattlePokemon(243, level=65),
    condition=Not(AnyOf((VarEquals(0x4031, 0), VarEquals(0x4031, 1)))),
)
```

## Stamp rallies

A rally wraps the shared middle with slot-specific and completion-specific hooks:

```python
from frlgsim.gift_composer import (
    BattlePokemon, DeliveryPlan, DeliveryStage, GivePokemon, Message,
    RelativeToPlayer, ShowSprite, StampRallySpec, StampSlot,
    WonderCardSpec, WonderGift,
)

RALLY = WonderGift(
    slug="example-rally",
    card=WonderCardSpec(
        icon_species=319,  # Claydol
        title="EXAMPLE RALLY",
        default_flag_id=1009,
    ),
    intro_message="Let me inspect your STAMP RALLY card!",
    event=StampRallySpec(
        slots=(
            StampSlot(
                slug="first-stamp",
                stamp_species=349,
                stamp_id=1,
                delivery=DeliveryPlan(
                    pre_stages=(DeliveryStage(Message("The SUN STAMP shines!")),),
                    post_stages=(DeliveryStage(
                        GivePokemon(349, level=30),
                    ),),
                ),
            ),
            StampSlot(
                slug="second-stamp",
                stamp_species=348,
                stamp_id=2,
                delivery=DeliveryPlan(
                    pre_stages=(DeliveryStage(Message("The MOON STAMP glows!")),),
                    post_stages=(DeliveryStage(
                        GivePokemon(348, level=30),
                    ),),
                ),
            ),
        ),
        completion=DeliveryPlan(
            pre_stages=(DeliveryStage(Message("Every STAMP is here!")),),
            post_stages=(DeliveryStage(
                ShowSprite(143, RelativeToPlayer(dx=1)),
                Message("The final guardian appeared!"),
                BattlePokemon(243, level=65),
            ),),
        ),
    ),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(Message("Your celestial record is updated.")),
    )),
    completed_message="The STAMP RALLY is complete.",
)
```

For every active, incomplete slot, the compiler concatenates:

```text
slot.pre_stages + WonderGift.delivery.delivery + slot.post_stages
```

After every slot finishes, it concatenates:

```text
completion.pre_stages + WonderGift.delivery.delivery + completion.post_stages
```

Thus the exact visit-level order is:

1. If not done, show `intro_message` once.
2. For each active slot in definition order, run its pre-stages, shared middle, and post-stages.
3. If all slots are complete, run completion pre-stages, shared middle, and post-stages.
4. If done on a later visit, show only `completed_message`.

The shared middle intentionally runs once for each slot delivery and once for rally completion. Put
content there only when it should be reused in every one of those paths. Put distinct Pokémon or
dialogue in the relevant slot/completion hooks.

The fixed saved-state layout is:

| State | Purpose |
|---|---|
| `VAR_MYSTERY_GIFT_1` | rally completion composed-path cursor |
| `VAR_MYSTERY_GIFT_2` | first stamp-slot composed-path cursor |
| `VAR_MYSTERY_GIFT_3` | second stamp-slot composed-path cursor |
| ... | ... |
| `VAR_MYSTERY_GIFT_7` | sixth stamp-slot composed-path cursor |
| `FLAG_MYSTERY_GIFT_DONE` | overall rally completion |

A slot cursor is `0` before activation, `1` when activated, and advances once after every stage in
its fully concatenated path. Each slot becomes a separate live-host catalog choice but shares its
card and delivery script with the other slots.

Battles are prohibited in a slot path, including the shared middle used by a rally. An
unconditional battle must be in the final stage. Conditional battle stages are allowed as terminal
alternatives; a matching battle checkpoints completion before starting and then routes directly to
the plan finish if control returns.

## Registration and validation

Register a `WonderGift` with the shared catalog:

```python
from frlgsim.gift_registry import GIFT_REGISTRY

GIFT_REGISTRY.register_definition(MEWTWO_GIFT)
GIFT_REGISTRY.register_definition(RALLY)
```

Ordinary gifts support the live host, `.bin` exporter, and save injector. Rally slot entries are
live-host-only. Registration validates and compiles the default flag ID immediately; a runtime
`--flag-id` is validated and compiled again.

Validation covers card text and flags, immutable plan structure, action ranges, stage cursor bounds,
unique stamp data, battle placement, virtual pointers, and the 995-byte saved RAM-script limit.
Errors identify the source section, for example:

```text
example-rally.event.slots[1].delivery.post_stages[0].actions[1]: battles are not allowed in stamp-slot delivery plans
```

Run the focused composer tests with:

```bash
python3 -B tests/test_gift_composer.py
```
