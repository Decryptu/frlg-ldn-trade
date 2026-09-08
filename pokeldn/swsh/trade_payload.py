"""The 3456-byte trade snapshot a Sword sends on protocol 0x84.

sw68 and sw70 caught this payload and session 58 read the party out of it. Session 59 found the rest
of it NAMED, in two published clients that had solved the same problem first - `kwsch/PokePiaSWSH`
(C#) and `lincoln-lm/swsh-lan-client` (Python), both over LAN mode rather than local wireless. The
layout below is theirs; what verified it here is our own capture, field for field.

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, start date at 0x170
    0xAEC  660 bytes NOT named by any client read so far
                                                            -> 0xD80 = 3456

**AND THE PAYLOAD IS 3456, NOT THE 2965 THIS PROJECT RECORDED.** The third fragment is COMPRESSED -
Pia's message flag 0x10, the same version-4 zlib flag `docs/pia.md` documents for protocol 0x80 -
and session 58 concatenated it raw. 1404 + 1404 + 157 gave 2965 and looked like a whole payload
because nothing said what the length should be; inflated, the third fragment is 648 bytes and the
total is exactly 3456. The "raw deflate stream in the trailer at 0xAF9" written up as an open
question WAS that fragment, sitting unread in the middle of the record.

THE LESSON, AND IT IS THE SAME ONE AS THE BLOCK ORDER: a reassembly that produces a plausible
length is not a reassembly that is right. `reassemble` refuses anything but 3456 for exactly that
reason - sw68 and sw70 would both have raised, a session before the party was read.

WHAT VERIFIED THE LAYOUT ON OUR OWN BYTES, none of it a checksum:

  - the party count reads 3, and slots 4-6 are the ones with a zero encryption constant;
  - MyStatus gives TID 56909 and SID 48474, and **those are the ids inside all three PK8s**;
  - the trainer name is at both named offsets, and matches the OT name in the party;
  - the start date at TrainerCard+0x170 is 2019-11-15, which is where session 58's unexplained
    "save date at 0xA94" came from - 0x924 + 0x170 IS 0xA94.
"""
import struct
import zlib

from pokeldn import gen8
from pokeldn.swsh import pokemon

PAYLOAD_LENGTH = 3456
FRAGMENT_COUNT = 3

PARTY_OFFSET = 0
PARTY_COUNT_OFFSET = PARTY_OFFSET + pokemon.PARTY_BLOCK          # 0x810
MY_STATUS_OFFSET = PARTY_COUNT_OFFSET + 4                        # 0x814
MY_STATUS_LENGTH = 272
TRAINER_CARD_OFFSET = MY_STATUS_OFFSET + MY_STATUS_LENGTH        # 0x924
TRAINER_CARD_LENGTH = 456
TAIL_OFFSET = TRAINER_CARD_OFFSET + TRAINER_CARD_LENGTH          # 0xAEC, 660 bytes, UNNAMED

# into MyStatus, from PKHeX `Saves/Substructures/Gen8/SWSH/MyStatus8.cs`
MY_STATUS_TID = 0xA0
MY_STATUS_SID = 0xA2
MY_STATUS_GAME = 0xA4
MY_STATUS_GENDER = 0xA5
MY_STATUS_NAME = 0xB0
# into TrainerCard, from `TrainerCard8.cs`
TRAINER_CARD_NAME = 0x00
TRAINER_CARD_LANGUAGE = 0x1B
TRAINER_CARD_STARTED = 0x170                                     # u16 year, then month, day
NAME_LENGTH = 0x1A


def inflate(fragment):
    """-> a 0x84 fragment body decompressed, or unchanged if it is not a zlib stream.

    The console sets Pia's message flag 0x10 on the compressed one; a receiver that reads the flag
    should not need this. It is here because our capture path did not, and because a payload
    already on disk can be repaired without another association.
    """
    try:
        return zlib.decompress(fragment)
    except zlib.error:
        return fragment


def reassemble(fragments):
    """-> the whole 3456-byte payload from its three fragment bodies, compressed ones inflated.

    RAISES on any other total. That refusal is the whole point of this function: session 58's
    2965-byte concatenation was wrong and nothing in it said so.
    """
    if len(fragments) != FRAGMENT_COUNT:
        raise ValueError(f"{len(fragments)} fragments, expected {FRAGMENT_COUNT}")
    payload = b"".join(inflate(f) for f in fragments)
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"reassembled {len(payload)} bytes, expected {PAYLOAD_LENGTH} - a fragment "
                         f"is missing, or a compressed one was concatenated raw")
    return payload


def _text(data, offset):
    return data[offset:offset + NAME_LENGTH].decode("utf-16-le", "replace").split("\x00")[0]


def read(payload):
    """-> the party and the trainer behind it. `party` is `swsh.pokemon.party`'s six slots."""
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"{len(payload)} bytes, expected {PAYLOAD_LENGTH}")
    status = payload[MY_STATUS_OFFSET:MY_STATUS_OFFSET + MY_STATUS_LENGTH]
    card = payload[TRAINER_CARD_OFFSET:TRAINER_CARD_OFFSET + TRAINER_CARD_LENGTH]
    year, month, day = struct.unpack_from("<HBB", card, TRAINER_CARD_STARTED)
    return {
        "party": pokemon.party(payload[PARTY_OFFSET:PARTY_OFFSET + pokemon.PARTY_BLOCK]),
        "party_count": struct.unpack_from("<I", payload, PARTY_COUNT_OFFSET)[0],
        "trainer_name": _text(status, MY_STATUS_NAME),
        "trainer_id": struct.unpack_from("<H", status, MY_STATUS_TID)[0],
        "secret_id": struct.unpack_from("<H", status, MY_STATUS_SID)[0],
        "game": status[MY_STATUS_GAME],
        "gender": status[MY_STATUS_GENDER],
        "card_name": _text(card, TRAINER_CARD_NAME),
        "card_language": card[TRAINER_CARD_LANGUAGE],
        "started": (year, month, day),
        # 660 bytes nothing has named. Kept whole rather than guessed at.
        "tail": payload[TAIL_OFFSET:],
    }


def party_matches_trainer(fields):
    """-> True when every party member carries the trainer's own ids.

    A cheap check with real content: the party records and MyStatus are different blocks of the
    payload, and on sw68 and sw70 they agree on 56909/48474. A reassembly that had slipped would
    not.
    """
    ids = (fields["trainer_id"], fields["secret_id"])
    return all((p["trainer_id"], p["secret_id"]) == ids
               for p in fields["party"] if p is not None)


assert TAIL_OFFSET == 0xAEC and PAYLOAD_LENGTH - TAIL_OFFSET == 660, "the layout must close"
assert gen8.SIZE_PARTY * 6 == PARTY_COUNT_OFFSET, "the party block is six party-form records"
