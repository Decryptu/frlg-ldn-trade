from .gift_composer import (
    AnyOf,
    AllOf,
    BattleLegendary,
    DeliveryPlan,
    DeliveryStage,
    Exit,
    GiftSpec,
    SHARE_ALWAYS,
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
    build_draw_count_script,
    build_seed_rate_script,
    build_seed_read_script,
    build_talk_script,
)
import dataclasses

from . import rng_script
from . import ereader_trainer, mevent_pokemon, mystery_event, stamp_rally, wonder_card


# pokefirered/include/constants/{items,species,event_objects}.h
ITEM_TM29_PSYCHIC = 317
ITEM_TM46_THIEF = 334
SPECIES_BALTOY = 318
SPECIES_CLAYDOL = 319
SPECIES_PORYGON = 137        # 13 is WEEDLE; the card icon showed an Aspicot on mev01
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

# Same card and script, but the receiving console may pass it on (Mystery Gift -> Wonder Cards -> SEND).
LEGENDARY_BEAST_GIFT_SHARE = dataclasses.replace(
    LEGENDARY_BEAST_GIFT,
    slug="beast-cutscene-share",
    event=GiftSpec(repeatable=True, shareable=SHARE_ALWAYS),
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


# The visiting trainer. The official event was a Wonder Card that pointed the player at a Poke Mart
# questionnaire and delivered the trainer in a later session [MysteryEventScript_VisitingTrainer,
# data/mystery_event_msg.s:113]; we send the card and the trainer together, because our host chooses
# both halves of the session. The card is the explanation -- the trainer is the payload, and it lands
# in gSaveBlock2Ptr->battleTower.ereaderTrainer whatever the player then does with the card.
VISITING_TRAINER_FLAG_ID = 1008
GIFT_VISITING_TRAINER = "visiting-trainer"

VISITING_TRAINER_GIFT = WonderGift(
    slug=GIFT_VISITING_TRAINER,
    card=WonderCardSpec(
        icon_species=ereader_trainer.SPECIES_PIKACHU,
        title="VISITING TRAINER",
        subtitle="A challenger has come to KANTO",
        body=(
            "A TRAINER has arrived in the SEVII",
            "ISLANDS looking for you.",
            "Go to the house on SEVEN ISLAND and",
            "talk to the old woman to battle.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=VISITING_TRAINER_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    # One stage: the delivery man says both lines in a single conversation, and `repeatable` lets
    # the player hear them again. The trainer itself already arrived at the Mystery Gift menu.
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "A TRAINER has arrived in the SEVII\n"
                "ISLANDS looking for you."),
            Message(
                "{PLAYER}, go to the house on SEVEN\n"
                "ISLAND to take up the challenge."),
        ),
    )),
    completed_message=(
        "The visiting TRAINER is waiting on\n"
        "SEVEN ISLAND."),
    trainer=ereader_trainer.build("red"),
)


# --- The Mystery Event VM ------------------------------------------------------------------------

GIFT_MEVENT_PROBE = "mystery-event-probe"
MEVENT_PROBE_FLAG_ID = 1009

# Marker status. Anything but 42 coming back names which of our assumptions was wrong, so this one
# script distinguishes every failure mode without a second hardware run:
#   42  the chain ran to the end AND pointer operands are offsets into our own buffer.
#   1   the chain ran, but the relocated pointers did not land on our probe bytes.
#   2   givenationaldex ran and nothing after it did (setstatus never reached).
#   0   the VM was entered but no command executed.
#   no response at all: the client script shape, not the VM, is what is wrong.
MEVENT_PROBE_STATUS = 42
MEVENT_PROBE_BYTES = b"MEVENT-PROBE-01"


def build_mevent_probe_script(*, status=MEVENT_PROBE_STATUS, probe=MEVENT_PROBE_BYTES):
    """givenationaldex, then a marker status, then a read-only checksum over our own bytes.

    Nothing here writes anything the player could lose. `givenationaldex` is a strict upgrade and a
    no-op on a save that already has it; `checksum` only reads. It is terminal (it returns TRUE and
    data[3] is 0 without checkcompat), which is exactly why it goes last: it reports on the
    relocation without disturbing the status the commands before it left.
    """
    script = mystery_event.MysteryEventScript()
    marker = script.blob(probe)
    script.givenationaldex().setstatus(status).checksum(marker)
    return script.assemble()


MEVENT_PROBE_GIFT = WonderGift(
    slug=GIFT_MEVENT_PROBE,
    card=WonderCardSpec(
        icon_species=SPECIES_PORYGON,
        title="MYSTERY EVENT",
        subtitle="A gift from the MYSTERY EVENT",
        body=(
            "The MYSTERY EVENT system has sent",
            "something to your POKEDEX.",
            "Check whether it can now record",
            "POKEMON from other regions.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=MEVENT_PROBE_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "The MYSTERY EVENT has already been\n"
                "delivered to your POKEDEX."),
        ),
    )),
    completed_message=(
        "The MYSTERY EVENT has already been\n"
        "delivered."),
    mevent=build_mevent_probe_script(),
)


GIFT_MEVENT_CELEBI = "mystery-event-celebi"
MEVENT_CELEBI_FLAG_ID = 1010

SPECIES_CELEBI_MEVENT = 251
SPECIES_CLEFAIRY_MEVENT = 35
MOVE_CONFUSION = 93
MOVE_RECOVER = 105
MOVE_HEAL_BELL = 215
MOVE_ANCIENT_POWER = 246

# Read as three lines of three on the console's mail screen.
MEVENT_CELEBI_MAIL_WORDS = (
    "hello", "friend", "",
    "i_ve_arrived", "", "",
    "thank_you", "enjoy", "",
)


def build_mevent_celebi_script(*, nickname="CELEBI", level=30):
    """`givepokemon`: a whole struct Pokemon plus the struct Mail that follows it.

    The only route on this link to a Pokemon carrying Mail, and the only one that writes the
    Pokedex itself. No `setstatus` follows it on purpose - `givepokemon` leaves 2 for success and 3
    for a full party, and that is exactly the answer worth reading back.
    """
    mon = mevent_pokemon.build_party_mon(
        SPECIES_CELEBI_MEVENT, level,
        moves=(MOVE_CONFUSION, MOVE_RECOVER, MOVE_HEAL_BELL, MOVE_ANCIENT_POWER),
        pp=(25, 20, 5, 5),
        nickname=nickname,
        ot_name="PkCamp",
        held_item=mevent_pokemon.ITEM_ORANGE_MAIL)
    mail = mevent_pokemon.build_mail(
        MEVENT_CELEBI_MAIL_WORDS, player_name="PkCamp",
        species=SPECIES_CELEBI_MEVENT, item_id=mevent_pokemon.ITEM_ORANGE_MAIL)
    payload = mevent_pokemon.build_givepokemon_payload(mon, mail)

    script = mystery_event.MysteryEventScript()
    script.givepokemon(script.blob(payload)).end()
    return script.assemble()


MEVENT_CELEBI_GIFT = WonderGift(
    slug=GIFT_MEVENT_CELEBI,
    card=WonderCardSpec(
        icon_species=SPECIES_CELEBI_MEVENT,
        title="MYSTERY EVENT",
        subtitle="A POKEMON with a letter",
        body=(
            "A POKEMON has been sent straight to",
            "your party, and it is carrying MAIL.",
            "There is no need to visit a POKEMON",
            "CENTER for this one.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=MEVENT_CELEBI_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "The POKEMON was sent straight to\n"
                "your party, {PLAYER}."),
            Message(
                "Read the MAIL it is holding to see\n"
                "the message that came with it."),
        ),
    )),
    completed_message=(
        "The POKEMON went straight to your\n"
        "party."),
    mevent=build_mevent_celebi_script(),
)


GIFT_MEVENT_NPC = "mystery-event-npc"
MEVENT_NPC_FLAG_ID = 1011

# PALLET TOWN, group 3 map 0 [data/maps/map_groups.json]. Local ids are assigned in map.json order
# and start at 1, so the FAT MAN standing at (13,17) is object 2 and the SIGN LADY is object 1
# [data/maps/PalletTown/map.json]. Neither is plot-critical and both are outdoors in a Fly town.
MAP_GROUP_PALLET_TOWN = 3
MAP_NUM_PALLET_TOWN = 0
PALLET_TOWN_OBJECT_SIGN_LADY = 1
PALLET_TOWN_OBJECT_FAT_MAN = 2

MEVENT_NPC_STATUS = 55          # our marker; initramscript leaves the status untouched

# WHERE TO BIND A SCRIPT THAT WILL BE TALKED TO ON A TIMER, and it is not where mev03 put one.
# BOTH Pallet Town NPCs are MOVEMENT_TYPE_WANDER_AROUND [decomp:data/maps/PalletTown/map.json], so
# the fat man walks off mid-countdown and the player has to chase him to press A - which ruins the
# timing it was pressed for. The player's mother is MOVEMENT_TYPE_FACE_LEFT with flag 0: she never
# moves, she is never hidden, and she is a step from where the player stands indoors.
# Group and map numbers are indices into data/maps/map_groups.json; group 3 / num 0 for Pallet Town
# is confirmed by mev03 and every run since, which is what makes group 4 / num 0 trustworthy.
MAP_GROUP_PLAYERS_HOUSE = 4
MAP_NUM_PLAYERS_HOUSE = 0
PLAYERS_HOUSE_OBJECT_MOM = 1


def _at_mom(kwargs):
    """Bind to the mother unless the caller says otherwise: a stationary object is a hard
    requirement for anything the player has to talk to at a chosen moment."""
    return {"map_group": MAP_GROUP_PLAYERS_HOUSE, "map_num": MAP_NUM_PLAYERS_HOUSE,
            "object_id": PLAYERS_HOUSE_OBJECT_MOM, **kwargs}


def build_mevent_npc_script(*, map_group=MAP_GROUP_PALLET_TOWN, map_num=MAP_NUM_PALLET_TOWN,
                            object_id=PALLET_TOWN_OBJECT_FAT_MAN, lines=None,
                            field_script=None):
    """`initramscript`: bind a field script to ANY map and ANY object event, not just the Mystery
    Gift delivery man.

    `CLI_SAVE_RAM_SCRIPT`, which every gift we have ever sent uses, calls
    `InitRamScript_NoObjectEvent` -- MAP_UNDEFINED and object 0xFF [decomp:src/script.c:578]. Those
    never satisfy `GetRamScript`'s map and object checks [`:514`]; they exist to satisfy
    `GetSavedRamScriptIfValid` [`:554`], which is the delivery man's own script command and which
    also requires a valid Wonder Card.

    `initramscript` writes real coordinates instead, which puts the script on the OTHER dispatch
    path: `GetRamScript(gSpecialVar_LastTalked, script)` in the field
    [decomp:src/field_control_avatar.c:458] runs our script INSTEAD of the object's own whenever the
    player talks to that object on that map. It does not consult the Wonder Card at all, so a script
    installed this way outlives the card.

    There is one RAM script slot, so this replaces the delivery man's script; any later Wonder Card
    takes the slot back.

    TRAP, confirmed on hardware (mev03): while this is installed the console reports that it holds
    NO Wonder Card. `ValidateSavedWonderCard` requires `ValidateRamScript`
    [decomp:src/mystery_gift.c:186], which only passes for MAP_UNDEFINED / object 0xFF. The card is
    intact in the save; the menu just will not show it, and the next session sees HAS_NO_CARD.
    """
    if field_script is None:
        lines = lines or (
            "The MYSTERY EVENT reached me before\n"
            "it reached you, {PLAYER}.",
            "Nobody told me what to say, so I am\n"
            "saying this instead.",
        )
        field_script = build_talk_script(lines, slug=GIFT_MEVENT_NPC)
    elif lines is not None:
        raise ValueError("give lines or a field_script, not both")

    script = mystery_event.MysteryEventScript()
    # initramscript sets no status of its own, so it would answer 0 whether it ran or not. A marker
    # after it turns the readback into "the chain reached past initramscript".
    script.initramscript(map_group, map_num, object_id, script.blob(field_script))
    script.setstatus(MEVENT_NPC_STATUS).end()
    return script.assemble()


MEVENT_NPC_GIFT = WonderGift(
    slug=GIFT_MEVENT_NPC,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="Someone in PALLET TOWN knows",
        body=(
            "Word of the MYSTERY EVENT has",
            "reached PALLET TOWN already.",
            "Talk to the man in the south of",
            "town to hear what he was told.",
        ),
        # The console will not display this card while the event's script is installed; it is here
        # because a Wonder Card session must carry one, and to name the event in the log.
        footer1="frlg-ldn-trade",
        default_flag_id=MEVENT_NPC_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    # The delivery man's own script is the one this event REPLACES, so it never runs. It is here
    # because a Wonder Card session must carry a RAM script, and because a later card restores it.
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "Someone in PALLET TOWN has heard\n"
                "about the MYSTERY EVENT."),
        ),
    )),
    completed_message=(
        "Talk to the man in the south of\n"
        "PALLET TOWN."),
    mevent=build_mevent_npc_script(),
)


GIFT_RNG_SHINY_DITTO = "rng-shiny-ditto"
RNG_SHINY_DITTO_FLAG_ID = 1013

SPECIES_DITTO = 132
RNG_DITTO_LEVEL = 50

# The seed is not a nice round number and could not be: it is the ANSWER to "which gRngValue makes
# CreateMon's next four draws a shiny Ditto with these IVs", found by walking the LCG orbit with a
# sliding window over 25 million candidates. For GURVAN's TID 57189 / SID 58811 it gives shiny
# value 3 (SHINY needs < 8) and IVs 31/23/27/18/30/30 - 159 of 186, with a perfect HP.
# lcg.draws(seed, 4) recomputes all of it; rng_script.predict_wild_mon states it.
RNG_DITTO_SEED = 0x81F6816D


def build_rng_shiny_ditto_script(seed=RNG_DITTO_SEED, species=SPECIES_DITTO,
                                 level=RNG_DITTO_LEVEL, **kwargs):
    """The Mystery Event that installs "talk to this man and fight a Pokemon we chose".

    The field script sets gRngValue and calls setwildbattle in the SAME FRAME, so the four draws
    that build the mon are a pure function of the seed - no timing, no frame precision, nothing
    asked of the player but to talk to an NPC. See frlgsim/rng_script.py for why there is no drift.
    """
    return build_mevent_npc_script(
        field_script=rng_script.build_wild_battle_script(seed, species, level), **kwargs)


RNG_SHINY_DITTO_GIFT = WonderGift(
    slug=GIFT_RNG_SHINY_DITTO,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="A rare POKEMON in PALLET TOWN",
        body=(
            "Something strange has been seen",
            "in the south of PALLET TOWN.",
            "Talk to the man there, and bring",
            "a POKE BALL.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=RNG_SHINY_DITTO_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "Something strange was seen in\n"
                "the south of PALLET TOWN."),
        ),
    )),
    completed_message=(
        "Talk to the man in the south of\n"
        "PALLET TOWN."),
    mevent=build_rng_shiny_ditto_script(),
)


GIFT_RNG_SEED_READER = "rng-seed-reader"
RNG_SEED_READER_FLAG_ID = 1015


def build_rng_seed_reader_script(**kwargs):
    """The Mystery Event that installs "talk to this man and he tells you the RNG seed".

    The other direction from rng-shiny-ditto, and the one that matters for READ-ONLY work: the
    field script copies the four bytes of gRngValue into gSpecialVar_0x8000/0x8001 and prints them,
    in one frame, and writes nothing at all. `gift_composer.build_seed_read_script` is the body and
    says why the read cannot tear.

    The address it needs, gSpecialVar_0x8000 = 0x020370B4, is bs57's (frlgsim/rom_map.py). This
    script is also its confirmation: `rng_script.check_two_readings` on two visits to the NPC.
    """
    return build_mevent_npc_script(
        field_script=build_seed_read_script(), **_at_mom(kwargs))


RNG_SEED_READER_GIFT = WonderGift(
    slug=GIFT_RNG_SEED_READER,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="A man who reads numbers",
        body=(
            "Your MOM has learned to read a",
            "number nobody is meant to see.",
            "Talk to her at home, and then",
            "talk to her again.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=RNG_SEED_READER_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "A man in PALLET TOWN can read\n"
                "a hidden number."),
        ),
    )),
    completed_message="Talk to your MOM at home.",
    mevent=build_rng_seed_reader_script(),
)


GIFT_RNG_RATE_PROBE = "rng-rate-probe"
RNG_RATE_PROBE_FLAG_ID = 1016


def build_rng_rate_probe_script(frames=None, **kwargs):
    """The Mystery Event that installs "talk to this man and he times the RNG for you".

    The field script reads gRngValue, waits an EXACT number of frames with `delay`, and reads it
    again. Both numbers that go into turns-per-frame are then exact - there is no stopwatch and no
    hand-timed elapsed anywhere, which is what every previous attempt at this rate had in it.
    """
    build = ({} if frames is None else {"frames": frames})
    return build_mevent_npc_script(field_script=build_seed_rate_script(**build),
                                   **_at_mom(kwargs))


RNG_RATE_PROBE_GIFT = WonderGift(
    slug=GIFT_RNG_RATE_PROBE,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="A man who counts",
        body=(
            "Your MOM will read a number,",
            "wait, and read it again. Talk",
            "to her at home and write both",
            "of them down.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=RNG_RATE_PROBE_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "A man in PALLET TOWN counts\n"
                "something nobody can see."),
        ),
    )),
    completed_message="Talk to your MOM at home.",
    mevent=build_rng_rate_probe_script(),
)


GIFT_RNG_RATE_PROBE_LONG = "rng-rate-probe-3000"
RNG_RATE_PROBE_LONG_FLAG_ID = 1017
RNG_RATE_PROBE_LONG_FRAMES = 3000

# mev09 measured 1,202 turns over exactly 600 frames. TWO MODELS FIT THAT ONE POINT and they are
# not the same claim:
#
#   exactly 2 per frame plus a constant 2   -> turns = 2N + 2   -> 6002 at N=3000
#   a rate slightly above 2 (2.003333)      -> turns = 2.0033N  -> 6010 at N=3000
#
# Over an 8192-frame countdown they diverge by ~27 turns against a target ONE STATE wide, so the
# difference is the difference between aiming and missing. Only the frame count changes between
# this probe and the 600-frame one; `lcg.distance` is exact, so the answer is unambiguous.
RNG_RATE_PROBE_LONG_PREDICTIONS = {"constant overhead (2N+2)": 2 * RNG_RATE_PROBE_LONG_FRAMES + 2,
                                   "rate above 2 (2.003333N)": 6010}

RNG_RATE_PROBE_LONG_GIFT = WonderGift(
    slug=GIFT_RNG_RATE_PROBE_LONG,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="The man counts for longer",
        body=(
            "Your MOM will count again, but",
            "five times as long. Talk to her",
            "at home and wait, then press A.",
            "",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=RNG_RATE_PROBE_LONG_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "The man in PALLET TOWN will\n"
                "count for longer this time."),
        ),
    )),
    completed_message="Talk to your MOM at home.",
    mevent=build_rng_rate_probe_script(frames=RNG_RATE_PROBE_LONG_FRAMES),
)


GIFT_RNG_DRAW_COUNT = "rng-draw-count"
RNG_DRAW_COUNT_FLAG_ID = 1018

# Ditto at 50, the same mon mev07 put in front of the player, so the drill is familiar. The species
# is not the point and nothing needs catching: the answer is the two numbers printed BEFORE the
# battle starts. Method 1 predicts a distance of 4; docs/rng.md's unexplained stray draw, if it is
# in this path, shows up as 5 or 6.
RNG_DRAW_COUNT_SPECIES = 132
RNG_DRAW_COUNT_LEVEL = 50
RNG_DRAW_COUNT_PREDICTION = 4


def build_rng_draw_count_script(**kwargs):
    return build_mevent_npc_script(
        field_script=build_draw_count_script(species=RNG_DRAW_COUNT_SPECIES,
                                             level=RNG_DRAW_COUNT_LEVEL), **_at_mom(kwargs))


RNG_DRAW_COUNT_GIFT = WonderGift(
    slug=GIFT_RNG_DRAW_COUNT,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY EVENT",
        subtitle="The man counts a POKEMON",
        body=(
            "Your MOM will read a number,",
            "make a POKEMON, and read it",
            "again. Write both down, then",
            "fight what turns up.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=RNG_DRAW_COUNT_FLAG_ID,
    ),
    intro_message=(
        "Thank you for using the MYSTERY\n"
        "GIFT System."),
    event=GiftSpec(repeatable=True),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message(
                "A man in PALLET TOWN counts\n"
                "what it costs to make a POKEMON."),
        ),
    )),
    completed_message="Talk to your MOM at home.",
    mevent=build_rng_draw_count_script(),
)


GIFT_MASTER_BALL = "master-ball"
MASTER_BALL_FLAG_ID = 1014

# The one the player spent catching the Ditto mev07 put in front of them. A plain item delivery -
# no cutscene, no sprite, no battle - so the delivery man hands it over and nothing else happens.
# It also takes the RAM script slot back from the Ditto script, which ends that binding.
MASTER_BALL_GIFT = WonderGift(
    slug=GIFT_MASTER_BALL,
    card=WonderCardSpec(
        icon_species=SPECIES_CLEFAIRY_MEVENT,
        title="MYSTERY GIFT",
        subtitle="A replacement MASTER BALL",
        body=(
            "A MASTER BALL is on its way to",
            "replace the one you used.",
            "Talk to the delivery man on the",
            "2nd floor of a POKEMON CENTER.",
        ),
        footer1="frlg-ldn-trade",
        default_flag_id=MASTER_BALL_FLAG_ID,
    ),
    intro_message="A MASTER BALL delivery has arrived!",
    event=GiftSpec(),
    delivery=DeliveryPlan(delivery=(
        DeliveryStage(
            Message("You received a MASTER BALL!"),
            GiveItem(wonder_card.ITEM_MASTER_BALL),
        ),
    )),
    completed_message="You already collected the MASTER BALL.",
)


__all__ = [
    "CELEBI_GIFT", "DIR_WEST", "GIFT_MEVENT_PROBE", "GIFT_PORYGON_TMS",
    "GIFT_VISITING_TRAINER",
    "GIFT_MEVENT_CELEBI", "MEVENT_CELEBI_GIFT", "MEVENT_CELEBI_FLAG_ID",
    "GIFT_MEVENT_NPC", "MEVENT_NPC_GIFT", "MEVENT_NPC_FLAG_ID",
    "GIFT_MASTER_BALL", "MASTER_BALL_GIFT", "MASTER_BALL_FLAG_ID",
    "GIFT_RNG_SHINY_DITTO", "RNG_SHINY_DITTO_GIFT", "RNG_SHINY_DITTO_FLAG_ID",
    "RNG_DITTO_SEED", "SPECIES_DITTO", "build_rng_shiny_ditto_script",
    "build_mevent_npc_script",
    "MEVENT_PROBE_GIFT", "MEVENT_PROBE_FLAG_ID", "MEVENT_PROBE_STATUS",
    "build_mevent_celebi_script",
    "build_mevent_probe_script",
    "GIFT_WORLDS_XP",
    "ITEM_TM29_PSYCHIC",
    "ITEM_TM46_THIEF", "LEGENDARY_BEAST_GIFT", "LEGENDARY_BEAST_GIFT_SHARE", "OBJ_EVENT_GFX_CLEFAIRY",
    "PORYGON_TM_GIFT", "PORYGON_TM_GIFT_FLAG_ID", "SPECIES_BALTOY",
    "SPECIES_PORYGON", "SUN_MOON_RALLY", "VAR_STARTER_MON",
    "WORLDS_XP_STATE_BATTLED", "WORLDS_XP_STATE_NEW", "WORLDS_XP_STATE_RECEIVED",
    "WORLDS_XP_STATE_VAR",
    "VISITING_TRAINER_GIFT", "VISITING_TRAINER_FLAG_ID",
    "WORLDS_XP_GIFT", "WORLDS_XP_GIFT_FLAG_ID",
]
