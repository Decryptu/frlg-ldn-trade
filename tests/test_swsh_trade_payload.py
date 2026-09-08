"""The 3456-byte trade snapshot a Sword sends on protocol 0x84.

sw68 and sw70 are captures and stay out of the repository (CLAUDE.md rule 6), so the payload here is
synthetic. What the real ones proved - and what these reproduce - is that the third fragment is
compressed, that a concatenation which skips that is short and must be refused, and that the party
records and the trainer block agree on one trainer.
"""
import struct
import zlib

import pytest

from pokeldn import gen8
from pokeldn.swsh import pokemon, trade_payload


def a_payload(count=2, tid=56909, sid=48474, name="Gurvan", started=(2019, 11, 15)):
    """A whole 3456-byte snapshot: `count` party records, then the two trainer blocks."""
    out = bytearray(PATTERN * (trade_payload.PAYLOAD_LENGTH // len(PATTERN) + 1))
    out = out[:trade_payload.PAYLOAD_LENGTH]

    for slot in range(pokemon.PARTY_SLOTS):
        plain = bytearray(bytes(range(256)) * 2)[:gen8.SIZE_PARTY]
        if slot >= count:
            out[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY] = bytes(gen8.SIZE_PARTY)
            continue
        struct.pack_into("<I", plain, 0x00, 0x39C5F2CC + slot)
        struct.pack_into("<H", plain, 0x04, 0)
        struct.pack_into("<H", plain, gen8.OFF_SPECIES, 94 + slot)
        struct.pack_into("<H", plain, gen8.OFF_TID, tid)
        struct.pack_into("<H", plain, gen8.OFF_SID, sid)
        plain[gen8.OFF_STAT_LEVEL] = 100 - slot
        raw = pokemon.encrypt(bytes(plain))
        out[slot * gen8.SIZE_PARTY:(slot + 1) * gen8.SIZE_PARTY] = raw

    struct.pack_into("<I", out, trade_payload.PARTY_COUNT_OFFSET, count)

    ms = trade_payload.MY_STATUS_OFFSET
    struct.pack_into("<H", out, ms + trade_payload.MY_STATUS_TID, tid)
    struct.pack_into("<H", out, ms + trade_payload.MY_STATUS_SID, sid)
    out[ms + trade_payload.MY_STATUS_GAME] = 44                    # PKHeX GameVersion.SW
    out[ms + trade_payload.MY_STATUS_GENDER] = 0
    encoded = name.encode("utf-16-le").ljust(trade_payload.NAME_LENGTH, b"\x00")
    out[ms + trade_payload.MY_STATUS_NAME:ms + trade_payload.MY_STATUS_NAME + len(encoded)] = encoded

    tc = trade_payload.TRAINER_CARD_OFFSET
    out[tc:tc + len(encoded)] = encoded
    out[tc + trade_payload.TRAINER_CARD_LANGUAGE] = 3
    struct.pack_into("<HBB", out, tc + trade_payload.TRAINER_CARD_STARTED, *started)
    return bytes(out)


PATTERN = bytes(range(256))


def fragments_of(payload, compress_last=True):
    """The payload as the console sends it: 1404, 1404, and a compressed remainder."""
    first, second, rest = payload[:1404], payload[1404:2808], payload[2808:]
    return [first, second, zlib.compress(rest) if compress_last else rest]


def test_the_third_fragment_is_compressed_and_the_whole_payload_is_3456():
    payload = a_payload()
    frags = fragments_of(payload)
    assert len(frags[2]) < len(payload) - 2808, "the third fragment should compress"
    assert trade_payload.reassemble(frags) == payload
    assert len(payload) == trade_payload.PAYLOAD_LENGTH == 3456


def test_concatenating_the_compressed_fragment_raw_is_refused():
    """Session 58's bug, exactly: 1404 + 1404 + 157 gave 2965 and nothing said it was wrong."""
    frags = fragments_of(a_payload())
    short = b"".join(frags)
    assert len(short) < trade_payload.PAYLOAD_LENGTH
    with pytest.raises(ValueError, match="expected 3456"):
        trade_payload.read(short)


def test_a_missing_fragment_is_refused_rather_than_read_as_a_short_payload():
    frags = fragments_of(a_payload())
    with pytest.raises(ValueError, match="expected 3"):
        trade_payload.reassemble(frags[:2])
    with pytest.raises(ValueError, match="a fragment is missing"):
        trade_payload.reassemble([frags[0], frags[1], frags[2][:8]])


def test_an_uncompressed_third_fragment_still_reassembles():
    """`inflate` leaves a fragment alone when it is not a zlib stream, so a receiver that reads
    Pia's 0x10 flag itself and hands over plain bodies gets the same answer."""
    payload = a_payload()
    assert trade_payload.reassemble(fragments_of(payload, compress_last=False)) == payload


def test_the_trainer_blocks_and_the_party_name_one_trainer():
    fields = trade_payload.read(a_payload(count=3))
    assert fields["party_count"] == 3
    assert [p is not None for p in fields["party"]] == [True, True, True, False, False, False]
    assert fields["trainer_name"] == fields["card_name"] == "Gurvan"
    assert (fields["trainer_id"], fields["secret_id"]) == (56909, 48474)
    assert fields["game"] == 44 and fields["card_language"] == 3
    assert fields["started"] == (2019, 11, 15)
    assert trade_payload.party_matches_trainer(fields) is True


def test_a_party_carrying_another_trainers_ids_is_visible_as_such():
    """The check has content only if it can fail: MyStatus and the PK8s are different blocks."""
    payload = bytearray(a_payload(count=1))
    ms = trade_payload.MY_STATUS_OFFSET
    struct.pack_into("<H", payload, ms + trade_payload.MY_STATUS_TID, 1)
    assert trade_payload.party_matches_trainer(trade_payload.read(bytes(payload))) is False


def test_the_named_blocks_tile_the_payload_without_overlapping():
    assert trade_payload.PARTY_COUNT_OFFSET == 0x810
    assert trade_payload.MY_STATUS_OFFSET == 0x814
    assert trade_payload.TRAINER_CARD_OFFSET == 0x924
    assert trade_payload.TAIL_OFFSET == 0xAEC
    # session 58 read a date at 0xA94 and could not say what it was: it is the start date
    assert trade_payload.TRAINER_CARD_OFFSET + trade_payload.TRAINER_CARD_STARTED == 0xA94
    assert len(trade_payload.read(a_payload())["tail"]) == 660


def test_our_snapshot_survives_the_round_trip_the_console_will_put_it_through():
    """Build it, frame it on 0x84, take it apart the way a receiver does, and read it back.

    This is the whole outgoing path offline, and it is what an association would otherwise pay to
    discover. `reassemble` is the receiver's rule, so if the sender's chunking disagrees with it the
    test fails here rather than on the air.
    """
    from pokeldn.ldn import broadcast4

    ours = trade_payload.rewrite(a_payload(count=3), trainer_name="PkCamp",
                                 trainer_id=12345, secret_id=54321)
    messages = broadcast4.Sender().transfer(ours)
    control = broadcast4.parse(messages[0][0])
    assert control["is_control"] and control["total"] == trade_payload.PAYLOAD_LENGTH

    fragments = []
    for message, compressed in messages[1:]:
        got = broadcast4.parse(message)
        fragments.append(zlib.decompress(got["body"]) if compressed else got["body"])
    assert len(fragments) == trade_payload.FRAGMENT_COUNT
    assert trade_payload.reassemble(fragments) == ours

    back = trade_payload.read(ours)
    assert back["trainer_name"] == back["card_name"] == "PkCamp"
    assert (back["trainer_id"], back["secret_id"]) == (12345, 54321)
    assert trade_payload.party_matches_trainer(back), "the party must name the trainer we became"
    assert [p["ot_name"] for p in back["party"] if p] == ["PkCamp"] * 3
    assert back["party_count"] == 3


def test_a_short_session_58_payload_is_repaired_and_anything_else_is_refused():
    frags = fragments_of(a_payload())
    short = b"".join(frags)
    with pytest.raises(ValueError, match="neither whole"):
        trade_payload.inflate_short(short)          # our synthetic one is not 2965 bytes
    with pytest.raises(ValueError, match="neither whole"):
        trade_payload.inflate_short(b"\x00" * 100)


# --- The fourth copy of the name, session 60 ---------------------------------------------------
#
# sw70's payload carries the trainer name a FOURTH time, at 0xB14, between two copies of an
# eight-byte account token - the shape of a player record - inside the 660-byte tail this project
# had never read. Every snapshot sent before session 60 therefore said PkCamp in MyStatus, the
# trainer card and all six Pokemon, and Gurvan in the tail. `party_matches_trainer` cannot see it:
# it only compares the party against MyStatus.

TAIL_NAME_AT = 0xB14                  # where it lands in sw70's payload; searched for, not assumed


def a_payload_with_a_tail_name(name="Gurvan", **kw):
    out = bytearray(a_payload(name=name, **kw))
    planted = name.encode("utf-16-le") + b"\x00\x00"
    out[TAIL_NAME_AT:TAIL_NAME_AT + len(planted)] = planted
    return bytes(out)


def test_the_tail_carries_a_fourth_copy_of_the_trainer_name():
    payload = a_payload_with_a_tail_name()
    was = trade_payload.read(payload)["trainer_name"]
    assert payload.find(was.encode("utf-16-le"), trade_payload.TAIL_OFFSET) == TAIL_NAME_AT

    out = trade_payload.rewrite(payload, old_name=was, trainer_name="PkCamp",
                                trainer_id=12345, secret_id=54321)
    assert out.find(was.encode("utf-16-le")) < 0          # nowhere in the payload at all
    assert out.count("PkCamp".encode("utf-16-le")) == 3   # status, card, and the tail
    assert len(out) == len(payload)
    assert trade_payload.party_matches_trainer(trade_payload.read(out))


def test_the_tail_copy_is_written_in_place_and_takes_no_extra_bytes():
    payload = a_payload_with_a_tail_name()
    out = trade_payload.rewrite(payload, old_name="Gurvan", trainer_name="PkCam")
    # "Gurvan\0" is 14 bytes and "PkCam\0" is 12, so the two spare bytes are zeroed rather than
    # left holding the tail of the old name.
    assert out[TAIL_NAME_AT:TAIL_NAME_AT + 14] == "PkCam".encode("utf-16-le") + b"\x00" * 4
    assert out[TAIL_NAME_AT + 14:TAIL_NAME_AT + 22] == payload[TAIL_NAME_AT + 14:TAIL_NAME_AT + 22]


def test_the_tail_is_left_alone_without_an_old_name():
    payload = a_payload_with_a_tail_name()
    out = trade_payload.rewrite(payload, trainer_name="PkCamp")
    assert out.find("Gurvan".encode("utf-16-le"), trade_payload.TAIL_OFFSET) == TAIL_NAME_AT


def test_a_longer_name_cannot_overwrite_the_tail_record():
    payload = a_payload_with_a_tail_name()
    with pytest.raises(ValueError):
        trade_payload.rewrite(payload, old_name="Gurvan", trainer_name="Gurvanne")


def a_payload_with_a_player_record(name="Gurvan", account=b"\x6a\x95\xe0\x43\x55\xa2\xd4\x7b\x04\x10"):
    """The tail record sw70's payload carries: id, key, name, id - around 0xB14."""
    out = bytearray(a_payload(name=name))
    at = TAIL_NAME_AT
    out[at - trade_payload.ACCOUNT_ID_LENGTH - 16:at - 16] = account
    out[at - 16:at] = bytes(range(0x40, 0x50))
    planted = name.encode("utf-16-le") + b"\x00\x00"
    out[at:at + len(planted)] = planted
    out[at + len(planted):at + len(planted) + trade_payload.ACCOUNT_ID_LENGTH] = account
    return bytes(out)


def test_the_tail_record_repeats_an_account_id_either_side_of_the_name():
    payload = a_payload_with_a_player_record()
    got = trade_payload.tail_account_id(payload, "Gurvan")
    assert got == bytes.fromhex("6a95e04355a2d47b0410")
    assert payload.count(got) == 2


def test_replacing_the_account_id_leaves_none_of_the_consoles_own():
    payload = a_payload_with_a_player_record()
    theirs = trade_payload.tail_account_id(payload, "Gurvan")
    ours = bytes(a ^ 0x5A for a in theirs)
    out = trade_payload.rewrite(payload, old_name="Gurvan", trainer_name="PkCamp",
                                account_id=ours)
    assert out.count(theirs) == 0 and out.count(ours) == 2
    assert len(out) == len(payload)


def test_an_account_id_needs_the_name_it_sits_around_and_the_right_length():
    payload = a_payload_with_a_player_record()
    with pytest.raises(ValueError):
        trade_payload.rewrite(payload, trainer_name="PkCamp", account_id=bytes(10))
    with pytest.raises(ValueError):
        trade_payload.rewrite(payload, old_name="Gurvan", trainer_name="PkCamp",
                              account_id=bytes(9))


def test_a_tail_without_the_repeated_id_reads_as_none():
    # The name is there but nothing repeats around it, which is a payload this has not read.
    assert trade_payload.tail_account_id(a_payload_with_a_tail_name(), "Gurvan") is None
