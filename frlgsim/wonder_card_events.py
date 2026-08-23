"""Composable Wonder Gift definitions shipped by the shared gift registry."""

from .gift_composer import (
    DeliveryPlan,
    DeliveryStage,
    GiftSpec,
    GiveItem,
    Message,
    RelativeToPlayer,
    ShowSprite,
    WonderCardSpec,
    WonderGift,
)


# pokefirered/include/constants/{items,species,event_objects}.h
ITEM_TM29_PSYCHIC = 317
ITEM_TM46_THIEF = 334
SPECIES_PORYGON = 137
OBJ_EVENT_GFX_CLEFAIRY = 113
DIR_WEST = 3

GIFT_PORYGON_TMS = "porygon-tm-gift"
PORYGON_TM_GIFT_FLAG_ID = 1007


PORYGON_TM_GIFT = WonderGift(
    slug=GIFT_PORYGON_TMS,
    card=WonderCardSpec(
        icon_species=SPECIES_PORYGON,
        title="PORYGON TM GIFT",
        subtitle="Two useful techniques",
        body=(
            "CLEFAIRY has two special TMs",
            "waiting for you!",
            "Visit the deliveryman on the",
            "2nd floor of a Pokemon Center.",
        ),
        footer1=" - MercuryEnigma",
        default_flag_id=PORYGON_TM_GIFT_FLAG_ID,
    ),
    intro_message="A special CLEFAIRY delivery has arrived!",
    event=GiftSpec(),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            ShowSprite(
                OBJ_EVENT_GFX_CLEFAIRY,
                RelativeToPlayer(dx=3),
                direction=DIR_WEST,
                delay_frames=20,
            ),
            Message("CLEFAIRY brought you TM29 PSYCHIC!"),
            GiveItem(ITEM_TM29_PSYCHIC),
        ),
        DeliveryStage(
            Message("CLEFAIRY also brought you TM46 THIEF!"),
            GiveItem(ITEM_TM46_THIEF),
        ),
    )),
    completed_message=(
        "CLEFAIRY already delivered both TMs.\n"
        "Use PSYCHIC and THIEF wisely!"),
)


__all__ = [
    "DIR_WEST", "GIFT_PORYGON_TMS", "ITEM_TM29_PSYCHIC",
    "ITEM_TM46_THIEF", "OBJ_EVENT_GFX_CLEFAIRY", "PORYGON_TM_GIFT",
    "PORYGON_TM_GIFT_FLAG_ID", "SPECIES_PORYGON",
]
