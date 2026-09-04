"""The visiting trainer: the 188-byte BattleTowerEReaderTrainer, and the Mystery Gift session that
pushes it into gSaveBlock2Ptr->battleTower.ereaderTrainer.

Every offset here is read off struct BattleTowerEReaderTrainer [decomp:include/global.h:286] and
struct BattleTowerPokemon [decomp:include/pokemon.h:143] rather than from our own packer, so a
layout mistake fails instead of round-tripping.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from frlgsim import (  # noqa: E402
    charmap, easychat, ereader_trainer, gift_composer, gift_registry, mg_script, mg_server,
    wonder_card_events,
)
from frlgsim.ereader_trainer import (  # noqa: E402
    EReaderTrainerError, TrainerMon, VisitingTrainer,
)


def _mon(**overrides):
    fields = dict(species=25, nickname="PIKACHU", level=50, moves=(85,))
    fields.update(overrides)
    return TrainerMon(**fields)


def _trainer(**overrides):
    fields = dict(name="RED", trainer_class="red", party=(_mon(), _mon(), _mon()))
    fields.update(overrides)
    return VisitingTrainer(**fields)


# --- struct layout ----------------------------------------------------------------------------
def test_the_packed_trainer_is_exactly_the_struct_size():
    packed = _trainer().pack()
    assert len(packed) == ereader_trainer.TRAINER_SIZE == 0xBC
    # party[3] starts at 0x34 and the checksum is the last word.
    assert 0x34 + 3 * ereader_trainer.MON_SIZE == 0xB8


def test_header_fields_land_at_the_struct_offsets():
    packed = _trainer(name="LEAF", trainer_class="leaf", trainer_id=0x11223344,
                      win_streak=7, unk0=1).pack()
    assert packed[0x00] == 1                                            # unk0
    assert packed[0x01] == ereader_trainer.FACILITY_CLASSES["leaf"]     # trainerClass
    assert int.from_bytes(packed[0x02:0x04], "little") == 7             # winStreak
    assert charmap.decode(packed[0x04:0x0C]) == "LEAF"                  # name[8]
    assert int.from_bytes(packed[0x0C:0x10], "little") == 0x11223344    # trainerId[4]


def test_the_three_phrases_are_six_easy_chat_words_each_in_struct_order():
    trainer = _trainer(greeting=("hello",), farewell_player_lost=("darn",),
                       farewell_player_won=("wow",))
    packed = trainer.pack()

    def words(offset):
        return tuple(int.from_bytes(packed[offset + i * 2:offset + i * 2 + 2], "little")
                     for i in range(easychat.TRAINER_LINE_LENGTH))

    pad = (easychat.UNDEFINED,) * 5
    assert words(0x10) == (easychat.WORDS["hello"],) + pad      # greeting
    assert words(0x1C) == (easychat.WORDS["darn"],) + pad       # farewellPlayerLost
    assert words(0x28) == (easychat.WORDS["wow"],) + pad        # farewellPlayerWon


def test_a_mon_packs_every_field_the_console_reads_back():
    """CreateBattleTowerMon copies all of these straight onto the party mon
    [decomp:src/pokemon.c CreateBattleTowerMon]."""
    mon = _mon(species=6, nickname="CHARIZARD", level=70, held_item=200,
               moves=(53, 337, 332, 89), evs=(1, 2, 3, 4, 5, 6),
               ivs=(31, 30, 29, 28, 27, 26), ability_num=1, friendship=200,
               pp_bonuses=0xFF, personality=0xDEADBEEF, ot_id=0xCAFEF00D)
    packed = mon.pack()
    assert len(packed) == ereader_trainer.MON_SIZE == 0x2C
    assert int.from_bytes(packed[0x00:0x02], "little") == 6
    assert int.from_bytes(packed[0x02:0x04], "little") == 200
    assert [int.from_bytes(packed[0x04 + i * 2:0x06 + i * 2], "little")
            for i in range(4)] == [53, 337, 332, 89]
    assert packed[0x0C] == 70
    assert packed[0x0D] == 0xFF
    assert list(packed[0x0E:0x14]) == [1, 2, 3, 4, 5, 6]        # hp/atk/def/spe/spa/spd EVs
    assert int.from_bytes(packed[0x14:0x18], "little") == 0xCAFEF00D
    bits = int.from_bytes(packed[0x18:0x1C], "little")
    assert [(bits >> (5 * i)) & 0x1F for i in range(6)] == [31, 30, 29, 28, 27, 26]
    assert (bits >> 31) & 1 == 1                                 # abilityNum
    assert int.from_bytes(packed[0x1C:0x20], "little") == 0xDEADBEEF
    assert charmap.decode(packed[0x20:0x2B]) == "CHARIZARD"
    assert packed[0x2B] == 200


def test_unused_move_slots_are_zero():
    packed = _mon(moves=(85, 98)).pack()
    assert int.from_bytes(packed[0x08:0x0A], "little") == 0
    assert int.from_bytes(packed[0x0A:0x0C], "little") == 0


# --- validation the console performs ------------------------------------------------------------
def test_the_checksum_is_the_sum_of_every_word_but_the_last():
    packed = _trainer().pack()
    expected = sum(int.from_bytes(packed[off:off + 4], "little")
                   for off in range(0, ereader_trainer.TRAINER_SIZE - 4, 4)) & 0xFFFFFFFF
    assert int.from_bytes(packed[0xB8:0xBC], "little") == expected
    assert ereader_trainer.validate(packed)


def test_a_corrupted_struct_is_rejected_the_way_the_console_rejects_it():
    packed = bytearray(_trainer().pack())
    packed[0x04] ^= 0x01                    # one byte of the name
    assert not ereader_trainer.validate(bytes(packed))
    assert not ereader_trainer.validate(bytes(ereader_trainer.TRAINER_SIZE))


def test_validate_insists_on_the_exact_length():
    with pytest.raises(EReaderTrainerError):
        ereader_trainer.validate(b"\x00" * 100)


# --- authoring guardrails -----------------------------------------------------------------------
def test_the_party_must_be_exactly_three():
    with pytest.raises(EReaderTrainerError):
        _trainer(party=(_mon(), _mon())).pack()


def test_a_mon_needs_at_least_one_move():
    with pytest.raises(EReaderTrainerError):
        _mon(moves=()).pack()


def test_out_of_range_fields_are_refused():
    for kwargs in (dict(level=0), dict(level=101), dict(ivs=32), dict(evs=256),
                   dict(ability_num=2), dict(species=0)):
        with pytest.raises(EReaderTrainerError):
            _mon(**kwargs).pack()


def test_an_unknown_class_or_nature_is_refused():
    with pytest.raises(EReaderTrainerError):
        _trainer(trainer_class="gym leader giovanni").pack()
    with pytest.raises(EReaderTrainerError):
        ereader_trainer.personality_for("splendid")


def test_a_name_longer_than_the_field_is_refused_and_five_characters_are_displayed():
    with pytest.raises(EReaderTrainerError):
        _trainer(name="ABCDEFGH").pack()
    # CopyEReaderTrainerName5 shows five [decomp:src/battle_tower.c:1343].
    assert _trainer(name="MERCURY").display_name == "MERCU"


def test_personality_picks_the_nature_and_can_force_a_shiny():
    for index, nature in enumerate(ereader_trainer.NATURES):
        assert ereader_trainer.personality_for(nature) % 25 == index
    shiny = ereader_trainer.personality_for("jolly", ot_id=0x1234, shiny=True)
    assert shiny % 25 == ereader_trainer.NATURES.index("jolly")
    assert ereader_trainer.is_shiny(shiny, 0x1234)
    assert not ereader_trainer.is_shiny(ereader_trainer.personality_for("jolly"), 0xFFFF0000)


# --- the registered gift --------------------------------------------------------------------
def test_the_visiting_trainer_gift_carries_a_valid_trainer():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("visiting-trainer")
    assert distribution.has_trainer
    assert ereader_trainer.validate(distribution.trainer)
    assert len(distribution.card) == 332
    # The card the player keeps is an ordinary Wonder Card; the trainer rides beside it.
    assert distribution.trainer[0x01] == ereader_trainer.FACILITY_CLASSES["red"]
    assert charmap.decode(distribution.trainer[0x04:0x0C]) == "RED"


def test_the_gift_flag_id_stays_out_of_the_ticket_flags():
    """sReceivedGiftFlags[0..2] are FLAG_RECEIVED_AURORA_TICKET, _MYSTIC_TICKET and _OLD_SEA_MAP
    [decomp:src/mystery_gift.c:30]; only 1003 and up are spare."""
    assert wonder_card_events.VISITING_TRAINER_FLAG_ID >= 1003


def test_a_definition_with_a_broken_trainer_is_refused():
    import dataclasses
    broken = dataclasses.replace(
        wonder_card_events.VISITING_TRAINER_GIFT,
        trainer=bytes(ereader_trainer.TRAINER_SIZE))
    with pytest.raises(gift_composer.GiftValidationError):
        gift_composer.validate_definition(broken)
    with pytest.raises(gift_composer.GiftValidationError):
        gift_composer.validate_definition(
            dataclasses.replace(wonder_card_events.VISITING_TRAINER_GIFT, trainer=b"\x01\x02"))


# --- the session ----------------------------------------------------------------------------
def _server(**kwargs):
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("visiting-trainer")
    return mg_server.MysteryGiftServer(
        distribution.card, distribution.ram_script, trainer=distribution.trainer, **kwargs)


def test_the_server_picks_the_visiting_trainer_script_when_a_trainer_is_present():
    server = _server()
    assert server.is_trainer_distribution
    assert server.script is mg_server.SCRIPT_SEND_VISITING_TRAINER


def test_the_server_refuses_a_trainer_the_console_would_clear():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("visiting-trainer")
    with pytest.raises(mg_server.MysteryGiftServerError):
        mg_server.MysteryGiftServer(distribution.card, distribution.ram_script,
                                    trainer=bytes(ereader_trainer.TRAINER_SIZE))
    with pytest.raises(mg_server.MysteryGiftServerError):
        mg_server.MysteryGiftServer(distribution.card, distribution.ram_script,
                                    trainer=b"\x01" * 10)


def test_the_client_scripts_end_on_the_trainer_message():
    def commands(script):
        return [int.from_bytes(script[i:i + 4], "little") for i in range(0, len(script), 8)]

    card_and_trainer = commands(mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_TRAINER)
    assert card_and_trainer == [
        mg_script.CLI_RECV, mg_script.CLI_SAVE_CARD,
        mg_script.CLI_RECV, mg_script.CLI_SAVE_RAM_SCRIPT,
        mg_script.CLI_RECV, mg_script.CLI_RECV_EREADER_TRAINER,
        mg_script.CLI_SEND_READY_END, mg_script.CLI_RETURN,
    ]
    assert commands(mg_script.CLIENT_SCRIPT_SAVE_TRAINER) == [
        mg_script.CLI_RECV, mg_script.CLI_RECV_EREADER_TRAINER,
        mg_script.CLI_SEND_READY_END, mg_script.CLI_RETURN,
    ]
    # CLI_MSG_TRAINER_RECEIVED is a success message, so the console saves afterwards
    # [GetClientResultMessage, decomp:src/mystery_gift_menu.c:939].
    for script in (mg_script.CLIENT_SCRIPT_SAVE_CARD_AND_TRAINER,
                   mg_script.CLIENT_SCRIPT_SAVE_TRAINER):
        assert int.from_bytes(script[-4:], "little") == mg_script.CLI_MSG_TRAINER_RECEIVED


def test_the_host_engine_takes_the_trainer_from_the_distribution():
    from frlgsim import host_mystery_gift, linkplayer
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("visiting-trainer")
    engine = host_mystery_gift.HostMysteryGiftEngine(
        distribution=distribution,
        link_player=linkplayer.LinkPlayer(name="EMU", version=linkplayer.VERSION_FIRE_RED))
    assert engine.server.trainer == distribution.trainer
    assert engine.server.script is mg_server.SCRIPT_SEND_VISITING_TRAINER


def test_a_stamp_rally_and_a_trainer_cannot_share_a_session():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("solrock-stamp")
    with pytest.raises(mg_server.MysteryGiftServerError):
        mg_server.MysteryGiftServer(
            distribution.card, distribution.ram_script,
            stamp=distribution.stamp,
            activation_script=distribution.activation_script,
            install_activation_script=distribution.install_activation_script,
            trainer=gift_registry.GIFT_REGISTRY.build_distribution(
                "visiting-trainer").trainer)


def test_the_delivery_man_says_both_lines_in_one_conversation():
    """Each DeliveryStage costs the player another interaction, so the two informational lines
    belong to one stage."""
    plan = wonder_card_events.VISITING_TRAINER_GIFT.delivery
    assert len(plan.delivery) == 1
    assert len(plan.delivery[0].actions) == 2
