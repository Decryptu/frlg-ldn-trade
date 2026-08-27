"""Composable Wonder Gift definitions shipped by the shared gift registry."""

from .gift_composer import (
    AnyOf,
    AllOf,
    BattleLegendary,
    DeliveryPlan,
    DeliveryStage,
    Exit,
    GiftSpec,
    GiveEgg,
    GiveItem,
    GivePokemon,
    Message,
    Not,
    RelativeToPlayer,
    RequireSpecialResult,
    SetVar,
    SPECIAL_HAS_ALL_KANTO_MONS,
    ShowSprite,
    StampRallySpec,
    StampSlot,
    VAR_MYSTERY_GIFT_1,
    VarEquals,
    WonderCardSpec,
    WonderGift,
)
from . import stamp_rally, wonder_card


# pokefirered/include/constants/{items,species,event_objects}.h
ITEM_TM29_PSYCHIC = 317
ITEM_TM46_THIEF = 334
SPECIES_BALTOY = 318
SPECIES_CLAYDOL = 319
SPECIES_PORYGON = 13
OBJ_EVENT_GFX_CLEFAIRY = 113
DIR_WEST = 3
MOVE_ZAP_CANNON = 192
MOVE_ERUPTION = 284
MOVE_REFRESH = 287
MOVE_WATER_SPOUT = 323

GIFT_PORYGON_TMS = "porygon-tm-gift"
GIFT_WORLDS_XP = "worlds-xp"
PORYGON_TM_GIFT_FLAG_ID = 1007
WORLDS_XP_GIFT_FLAG_ID = 1006
VAR_STARTER_MON = 0x4031
WORLDS_XP_STATE_VAR = 0x40BD
WORLDS_XP_STATE_NEW = 0
WORLDS_XP_STATE_BATTLED = 1
WORLDS_XP_STATE_RECEIVED = 2

CELEBI_GIFT = WonderGift(
    slug=wonder_card.GIFT_CELEBI,
    card=WonderCardSpec(
        icon_species=wonder_card.DEFAULT_GIFT_ICON_SPECIES,
        title=wonder_card.DEFAULT_GIFT_TITLE,
        subtitle=wonder_card.DEFAULT_GIFT_SUBTITLE,
        body=wonder_card.DEFAULT_GIFT_BODY,
        footer1=wonder_card.DEFAULT_GIFT_SIGNATURE,
        default_flag_id=1003,
    ),
    intro_message="A special CELEBI delivery has arrived!",
    event=GiftSpec(),
    delivery=DeliveryPlan(delivery=(DeliveryStage(
        GivePokemon(
            wonder_card.SPECIES_CELEBI,
            level=50,
            moves=(
                wonder_card.MOVE_LEECH_SEED,
                wonder_card.MOVE_RECOVER,
                wonder_card.MOVE_HEAL_BELL,
                wonder_card.MOVE_SAFEGUARD,
            ),
            failure_message=(
                "Oh, your party appears to be full.\n"
                "Please make room and come back!"),
        ),
        Message("{PLAYER} received a CELEBI\nfrom the deliveryman!"),
    ),)),
    completed_message="Please look forward to future\nMYSTERY GIFTS!",
)

LEGENDARY_BEAST_GIFT = WonderGift(
    slug=wonder_card.GIFT_BEAST_CUTSCENE,
    card=WonderCardSpec(
        icon_species=wonder_card.SPECIES_CLAYDOL,
        title="LEGENDARY BEAST",
        subtitle="A shocking encounter!",
        body=("Meet the delivery man for", "berries and a beastly battle!"),
        footer1="frlg-ldn-trade",
        default_flag_id=1003,
    ),
    intro_message=(
        "A MYSTERY GIFT arrived!"),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "You must be {PLAYER}!\n"
                "Something is here for you."),
        ),
        DeliveryStage(GiveItem(wonder_card.ITEM_LANSAT_BERRY)),
        DeliveryStage(GiveItem(wonder_card.ITEM_LIECHI_BERRY)),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_SUICUNE,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=VarEquals(VAR_STARTER_MON, 0),
        ),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_ENTEI,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=VarEquals(VAR_STARTER_MON, 1),
        ),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_RAIKOU,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=Not(AnyOf((
                VarEquals(VAR_STARTER_MON, 0),
                VarEquals(VAR_STARTER_MON, 1),
            ))),
        ),
        DeliveryStage(
            Message(
                "A Legendary Beast appeared!\n"
                "Here, take this."),
        ),
        DeliveryStage(GiveItem(wonder_card.ITEM_MASTER_BALL)),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_SUICUNE,
                level=wonder_card.LEGENDARY_BEAST_LEVEL),
            condition=VarEquals(VAR_STARTER_MON, 0),
        ),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_ENTEI,
                level=wonder_card.LEGENDARY_BEAST_LEVEL),
            condition=VarEquals(VAR_STARTER_MON, 1),
        ),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_RAIKOU,
                level=wonder_card.LEGENDARY_BEAST_LEVEL),
            condition=Not(AnyOf((
                VarEquals(VAR_STARTER_MON, 0),
                VarEquals(VAR_STARTER_MON, 1),
            ))),
        ),
    )),
    completed_message="Please enjoy another encounter!",
)

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


WORLDS_XP_GIFT = WonderGift(
    slug=GIFT_WORLDS_XP,
    card=WonderCardSpec(
        icon_species=SPECIES_CLAYDOL,
        bg_type=1,
        title="FANtastic Mystery Gift - WORLDS 26",
        subtitle="A Legendary Experience!",
        body=(
            "An EGG of ruins is waiting. Talk to the",
            "deliveryman to see why it is attracting",
            "a LEGENDARY aura.",
            "We hope you enjoy this fan-made event!",
        ),
        footer1=" - MercuryEnigma.github.io/pkcamp",
        footer2="NOTE. not official use at your own risk",
        default_flag_id=WORLDS_XP_GIFT_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\nGIFT System."),
        #     intro_message=(
        # "Come to Pokemon Worlds in San Francisco!\n"
        # "See what LEGENDARY gift awaits."),
    event=GiftSpec(repeatable=True, shareable="always"),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Exit(),
            condition=VarEquals(WORLDS_XP_STATE_VAR, WORLDS_XP_STATE_RECEIVED),
        ),
        DeliveryStage(
            SetVar(VAR_MYSTERY_GIFT_1, 0),
            RequireSpecialResult(
                SPECIAL_HAS_ALL_KANTO_MONS,
                1,
                "Finish the DEX!",
            ),
            GivePokemon(
                wonder_card.SPECIES_CELEBI,
                level=50,
            ),
            Message("Congrats! Here is a CELEBI."),
            SetVar(WORLDS_XP_STATE_VAR, WORLDS_XP_STATE_RECEIVED),
            Exit(),
            condition=VarEquals(WORLDS_XP_STATE_VAR, WORLDS_XP_STATE_BATTLED),
        ),
        DeliveryStage(
            GiveEgg(
                SPECIES_BALTOY,
                moves=(
                    MOVE_REFRESH,
                    MOVE_ZAP_CANNON,
                    MOVE_ERUPTION,
                    MOVE_WATER_SPOUT,
                ),
            ),
            Message("This egg has the power of\n"
                    "3 beasts from a time of ruins."),
        ),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_SUICUNE,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=VarEquals(VAR_STARTER_MON, 0),
        ),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_ENTEI,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=VarEquals(VAR_STARTER_MON, 1),
        ),
        DeliveryStage(
            ShowSprite(
                wonder_card.OBJ_EVENT_GFX_RAIKOU,
                RelativeToPlayer(dx=1),
                direction=wonder_card.DIR_WEST,
                delay_frames=30,
            ),
            condition=Not(AnyOf((
                VarEquals(VAR_STARTER_MON, 0),
                VarEquals(VAR_STARTER_MON, 1),
            ))),
        ),
        DeliveryStage(
            Message("What is that?"),
            GiveItem(wonder_card.ITEM_MASTER_BALL),
            SetVar(WORLDS_XP_STATE_VAR, WORLDS_XP_STATE_BATTLED),
        ),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_SUICUNE,
                level=wonder_card.LEGENDARY_BEAST_LEVEL,
            ),
            condition=VarEquals(VAR_STARTER_MON, 0),
        ),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_ENTEI,
                level=wonder_card.LEGENDARY_BEAST_LEVEL,
            ),
            condition=VarEquals(VAR_STARTER_MON, 1),
        ),
        DeliveryStage(
            BattleLegendary(
                wonder_card.SPECIES_RAIKOU,
                level=wonder_card.LEGENDARY_BEAST_LEVEL,
            ),
            condition=Not(AnyOf((
                VarEquals(VAR_STARTER_MON, 0),
                VarEquals(VAR_STARTER_MON, 1),
            ))),
        ),
    )),
    completed_message="Visit MercuryEnigma.github.io/pkcamp",
)


__all__ = [
    "CELEBI_GIFT", "DIR_WEST", "GIFT_PORYGON_TMS", "GIFT_WORLDS_XP",
    "ITEM_TM29_PSYCHIC",
    "ITEM_TM46_THIEF", "LEGENDARY_BEAST_GIFT", "OBJ_EVENT_GFX_CLEFAIRY",
    "PORYGON_TM_GIFT", "PORYGON_TM_GIFT_FLAG_ID", "SPECIES_BALTOY",
    "SPECIES_PORYGON", "SUN_MOON_RALLY", "VAR_STARTER_MON",
    "WORLDS_XP_STATE_BATTLED", "WORLDS_XP_STATE_NEW", "WORLDS_XP_STATE_RECEIVED",
    "WORLDS_XP_STATE_VAR",
    "WORLDS_XP_GIFT", "WORLDS_XP_GIFT_FLAG_ID",
]
