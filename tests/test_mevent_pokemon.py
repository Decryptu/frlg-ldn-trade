"""The `givepokemon` payload: a struct Pokemon the console can decrypt, followed by the struct Mail
it reads at +sizeof(struct Pokemon).

The mon is checked through `frlgsim.mon`'s decoder, which is the same wire form the trade host has
been putting on the air since before this feature existed, so a mon that decodes here is a mon the
console has already been shown to accept.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import (  # noqa: E402
    charmap, easychat, gift_registry, mevent_pokemon as mp, mon as monmod, mystery_event,
    wonder_card_events,
)


def _celebi(**kwargs):
    kwargs.setdefault("nickname", "CELEBI")
    return mp.build_party_mon(251, 30, **kwargs)


def test_a_built_mon_round_trips_through_the_wire_decoder():
    mon = _celebi(moves=(93, 105), pp=(25, 20), ot_name="PkCamp")
    decoded = mon.decode()

    assert decoded["checksum_ok"]
    assert decoded["species"] == 251
    assert decoded["nickname"] == "CELEBI"
    assert decoded["otName"] == "PkCamp"
    assert decoded["level"] == 30
    assert decoded["moves"][:2] == [93, 105]
    assert len(mon.party_bytes()) == monmod.PARTY_MON_SIZE


def test_the_party_tail_is_derived_and_not_left_at_zero():
    """A zero tail reads back as level 0 on the receiver; stats.build_party_tail fills it in."""
    raw = _celebi().party_bytes()
    assert raw[84] == 30
    assert int.from_bytes(raw[86:88], "little") > 0        # hp
    assert int.from_bytes(raw[88:90], "little") > 0        # maxHP


def test_the_mail_byte_starts_as_mail_none():
    """A zero there is mail slot 0, which the console would read as real mail the player never got."""
    assert _celebi().raw[85] == mp.MAIL_NONE


def test_the_encryption_key_is_never_zero():
    """personality == otId leaves the secure region in the clear and both .pk3 and .ek3 then
    validate, so a mon could ship unshuffled [frlgsim.mon.Mon.from_pk3]."""
    mon = _celebi(ot_id=0x1234ABCD, personality=0x1234ABCD)
    assert mon.pid != mon.otid
    assert mon.checksum_ok


def test_the_origins_halfword_packs_met_level_game_and_ball():
    canon = monmod.to_decrypted(_celebi(met_level=30).party_bytes())
    origins = int.from_bytes(canon[70:72], "little")
    assert origins & 0x7F == 30                            # metLevel
    assert (origins >> 7) & 0x0F == mp.VERSION_FIRE_RED    # metGame
    assert (origins >> 11) & 0x0F == mp.POKE_BALL


def test_a_nameless_mon_is_refused():
    with pytest.raises(mp.MysteryEventPokemonError, match="nickname"):
        mp.build_party_mon(251, 30)


def test_a_species_with_no_base_stats_is_refused_rather_than_shipped_flat():
    with pytest.raises(mp.MysteryEventPokemonError):
        mp.build_party_mon(0xFFF, 30, nickname="NOPE")


# --- the mail ------------------------------------------------------------------------------

def test_mail_is_the_struct_the_console_reads():
    mail = mp.build_mail(("hello", "friend"), player_name="PkCamp", trainer_id=0x1234,
                         species=251, item_id=mp.ITEM_ORANGE_MAIL)
    assert len(mail) == mp.MAIL_SIZE
    words = [int.from_bytes(mail[i * 2:i * 2 + 2], "little") for i in range(9)]
    assert words[:2] == list(easychat.resolve_words(("hello", "friend"), 2))
    assert words[2:] == [easychat.UNDEFINED] * 7           # never 0: word 0 prints "???"
    assert charmap.decode(mail[0x12:0x1A]) == "PkCamp"
    assert int.from_bytes(mail[0x1A:0x1E], "little") == 0x1234
    assert int.from_bytes(mail[0x1E:0x20], "little") == 251
    assert int.from_bytes(mail[0x20:0x22], "little") == mp.ITEM_ORANGE_MAIL


def test_a_non_mail_item_is_refused():
    with pytest.raises(mp.MysteryEventPokemonError, match="ItemIsMail"):
        mp.build_mail((), item_id=1)


# --- the payload ---------------------------------------------------------------------------

def test_the_payload_is_the_mon_then_the_mail():
    mon = _celebi(held_item=mp.ITEM_ORANGE_MAIL)
    mail = mp.build_mail(("hello",), item_id=mp.ITEM_ORANGE_MAIL)
    payload = mp.build_givepokemon_payload(mon, mail)

    assert len(payload) == monmod.PARTY_MON_SIZE + mp.MAIL_SIZE
    assert payload[:monmod.PARTY_MON_SIZE] == mon.party_bytes()
    assert payload[monmod.PARTY_MON_SIZE:] == mail


def test_mail_on_a_mon_that_cannot_hold_it_is_refused():
    """ItemIsMail gates GiveMailToMon2 [decomp:src/mystery_event_script.c:270], so a mon holding
    anything else would arrive with the mail silently dropped."""
    mon = _celebi(held_item=0)
    with pytest.raises(mp.MysteryEventPokemonError, match="ItemIsMail"):
        mp.build_givepokemon_payload(mon, mp.build_mail(("hello",)))


def test_a_mon_and_its_mail_must_name_the_same_item():
    """GiveMailToMon2 sets the held item from the mail, so a disagreement silently rewrites it."""
    mon = _celebi(held_item=mp.ITEM_ORANGE_MAIL)
    mail = mp.build_mail(("hello",), item_id=mp.ITEM_HARBOR_MAIL)
    with pytest.raises(mp.MysteryEventPokemonError, match="must agree"):
        mp.build_givepokemon_payload(mon, mail)


def test_a_payload_with_no_mail_is_still_the_right_length():
    payload = mp.build_givepokemon_payload(_celebi())
    assert len(payload) == monmod.PARTY_MON_SIZE + mp.MAIL_SIZE


# --- the wired-up gift ---------------------------------------------------------------------

def test_the_celebi_gift_assembles_to_givepokemon_and_nothing_else():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-celebi")
    assert mystery_event.describe(distribution.mevent) == "givepokemon 8; end"
    assert len(distribution.mevent) <= mystery_event.MAX_SCRIPT_SIZE


def test_the_console_would_take_the_mon_and_report_success():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-celebi")
    result = mystery_event.run(distribution.mevent)

    assert result.status == mystery_event.STATUS_SUCCESS
    assert result.stopped_at == "end"
    _, mon, mail = result.effect("givepokemon")
    assert monmod.Mon(mon).decode()["species"] == wonder_card_events.SPECIES_CELEBI_MEVENT
    assert int.from_bytes(mail[0x20:0x22], "little") == mp.ITEM_ORANGE_MAIL
    # Nothing is read outside the buffer we sent.
    assert result.effect("read_past_buffer") is None


def test_a_full_party_is_reported_rather_than_overwritten():
    distribution = gift_registry.GIFT_REGISTRY.build_distribution("mystery-event-celebi")
    result = mystery_event.run(distribution.mevent, party_count=6)

    assert result.status == mystery_event.STATUS_INCOMPATIBLE
    assert result.effect("givepokemon") is None
    assert result.effect("givepokemon_full_party") is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
