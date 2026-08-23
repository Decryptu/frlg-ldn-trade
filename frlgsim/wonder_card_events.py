"""Composable Wonder Gift definitions shipped by the shared gift registry."""

from .gift_composer import (
    DeliveryPlan,
    DeliveryStage,
    GiftSpec,
    GiveItem,
    GivePokemon,
    Message,
    RelativeToPlayer,
    ShowSprite,
    StampRallySpec,
    StampSlot,
    WonderCardSpec,
    WonderGift,
)
from . import stamp_rally, wonder_card


# pokefirered/include/constants/{items,species,event_objects}.h
ITEM_TM29_PSYCHIC = 317
ITEM_TM46_THIEF = 334
SPECIES_PORYGON = 137
OBJ_EVENT_GFX_CLEFAIRY = 113
DIR_WEST = 3

GIFT_PORYGON_TMS = "porygon-tm-gift"
PORYGON_TM_GIFT_FLAG_ID = 1007

SUN_MOON_RALLY = WonderGift(
    slug="sun-moon-rally",
    card=WonderCardSpec(
        icon_species=wonder_card.SPECIES_CLAYDOL,
        title="SUN AND MOON RALLY",
        subtitle="Collect both stamps!",
        body=(
            "Collect SOLROCK and LUNATONE",
            "stamps from event hosts.",
            "Claim each Pokemon, then",
            "receive a special grand prize!",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=stamp_rally.STAMP_RALLY_FLAG_ID,
    ),
    intro_message="Let me inspect your STAMP RALLY card!",
    event=StampRallySpec(
        slots=(
            StampSlot(
                slug=stamp_rally.GIFT_SOLROCK_STAMP,
                stamp_species=stamp_rally.SPECIES_SOLROCK,
                stamp_id=stamp_rally.SOLROCK_STAMP_ID,
                delivery=DeliveryPlan(
                    pre_stages=(DeliveryStage(
                        Message(
                            "Your SOLROCK STAMP checks out!\n"
                            "Please accept this SOLROCK."),
                        GivePokemon(
                            stamp_rally.SPECIES_SOLROCK,
                            level=stamp_rally.SOLROCK_LEVEL),
                    ),),
                ),
            ),
            StampSlot(
                slug=stamp_rally.GIFT_LUNATONE_STAMP,
                stamp_species=stamp_rally.SPECIES_LUNATONE,
                stamp_id=stamp_rally.LUNATONE_STAMP_ID,
                delivery=DeliveryPlan(
                    pre_stages=(DeliveryStage(
                        Message(
                            "Your LUNATONE STAMP checks out!\n"
                            "Please accept this LUNATONE."),
                        GivePokemon(
                            stamp_rally.SPECIES_LUNATONE,
                            level=stamp_rally.LUNATONE_LEVEL),
                    ),),
                ),
            ),
        ),
        completion=DeliveryPlan(
            pre_stages=(DeliveryStage(
                Message(
                    "Both STAMP rewards are yours!\n"
                    "Please accept the grand prize."),
                GivePokemon(wonder_card.SPECIES_CELEBI,
                            level=stamp_rally.CELEBI_LEVEL),
            ),),
            post_stages=(DeliveryStage(
                Message(
                    "Congratulations! CELEBI is yours!\n"
                    "The STAMP RALLY is complete."),
            ),),
        ),
    ),
    delivery=DeliveryPlan(),
    completed_message=(
        "You completed the STAMP RALLY!\n"
        "Thank you for participating."),
)


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
    "PORYGON_TM_GIFT_FLAG_ID", "SPECIES_PORYGON", "SUN_MOON_RALLY",
]
