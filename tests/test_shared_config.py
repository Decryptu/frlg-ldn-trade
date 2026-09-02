from dataclasses import FrozenInstanceError

import frlgtrade
from frlgsim import config, linkplayer


def test_default_profile_is_completed_and_matches_configured_identity():
    profile = config.DEFAULT_TRAINER
    assert (profile.name, profile.version) == ("PkCamp", "leafgreen")
    assert (profile.tid, profile.sid) == (0x8822, 0x47ED)
    assert profile.trainer_id == 0x47ED8822
    assert profile.progress_flags == 0x11


def test_trainer_id_accepts_decimal_tid_and_tid_sid():
    assert config.parse_trainer_id("0") == (0, None)
    assert config.parse_trainer_id("65535") == (65535, None)
    assert config.parse_trainer_id("12345:34567") == (12345, 34567)
    one = config.profile_from_overrides(trainer_id=(12345, None))
    both = config.profile_from_overrides(trainer_id=(12345, 34567))
    assert (one.tid, one.sid) == (12345, config.DEFAULT_TRAINER.sid)
    assert (both.tid, both.sid) == (12345, 34567)
    assert both.trainer_id == (34567 << 16) | 12345


def test_trainer_id_rejects_invalid_syntax_and_ranges():
    invalid = ("", "-1", "0x1234", "1:", ":1", "1:2:3", "65536", "1:65536")
    for value in invalid:
        try:
            config.parse_trainer_id(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid trainer ID accepted: {value!r}")


def test_profile_is_immutable_and_serialization_padding_is_role_specific():
    profile = config.profile_from_overrides(
        ot="Red", version="firered", trainer_id=(12345, 34567))
    try:
        profile.name = "Leaf"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("frozen TrainerProfile accepted assignment")
    player = profile.to_link_player()
    assert player.trainer_id == (34567 << 16) | 12345
    assert player.version == linkplayer.VERSION_FIRE_RED
    assert player.pack(name_pad=0x00)[8:16] == bytes.fromhex("CC D9 D8 FF 00 00 00 00")
    assert player.pack(name_pad=0xFF)[8:16] == bytes.fromhex("CC D9 D8 FF FF FF FF FF")


def test_joiner_cli_builds_full_config_from_identity_overrides():
    parser = frlgtrade.build_parser()
    args = parser.parse_args([
        "--live", "--ot", "Red", "--version", "firered",
        "--id=12345:34567", "one.pk3", "two.pk3",
    ])
    run = frlgtrade._build_run_config(parser, args)
    assert (run.profile.name, run.profile.version) == ("Red", "firered")
    assert (run.profile.tid, run.profile.sid) == (12345, 34567)
    assert run.plan.party_paths == ("one.pk3", "two.pk3")
    assert isinstance(run.role, config.JoinerOptions)


def test_latin_languages_are_offered_with_their_decomp_values():
    """include/constants/global.h:21-27. Japanese (1) is deliberately absent: its kana reuse the
    same byte values as the accented Latin range in charmap, so a Japanese name cannot be encoded
    with the international table we ship."""
    assert config.LANGUAGES == {
        "english": 2, "french": 3, "italian": 4, "german": 5, "spanish": 7,
    }
    assert "japanese" not in config.LANGUAGES
    for name in config.LANGUAGES:
        config.TrainerProfile(name="Zoé", tid=1, sid=2, language=name)


def test_accented_names_survive_the_charmap_round_trip():
    """encode() drops unknown characters, so before the accented range was added a French OT name
    went on the wire mangled: "Zoe(acute)" -> "Zo". Names are what the console displays for us."""
    from frlgsim import charmap
    for name in ("Zoé", "Éloïse", "Jürgen", "Muñoz", "Grüße", "José", "Gurvan"):
        encoded = charmap.encode(name, width=8, pad=0x00)
        assert charmap.decode(encoded) == name, name


def test_charmap_never_maps_the_terminator_to_a_glyph():
    """charmap.txt maps 0xFF to '$', but 0xFF is our EOS and fixed-width pad. Mapping it would
    corrupt every name field."""
    from frlgsim import charmap
    assert charmap.EOS == 0xFF and charmap.PAD == 0xFF
    assert 0xFF not in charmap._DEC
    assert "$" not in charmap._ENC


def test_language_override_reaches_the_linkplayer_wire_byte():
    """The dict is useless unless --language can select it and it lands in the struct the console
    actually reads (LinkPlayer[26:28])."""
    from frlgsim import linkplayer
    for name, code in config.LANGUAGES.items():
        profile = config.profile_from_overrides(ot="Zoé", language=name)
        wire = profile.to_link_player().pack()
        assert int.from_bytes(wire[26:28], "little") == code, name
        assert linkplayer.LinkPlayer.unpack(wire).name == "Zoé"
