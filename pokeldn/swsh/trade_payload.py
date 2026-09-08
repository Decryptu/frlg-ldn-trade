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


SHORT_LENGTH = 2965                   # session 58's concatenation: 1404 + 1404 + 157 compressed
FRAGMENT_2_END = 2808                 # where its third fragment begins


def inflate_short(payload):
    """-> a whole payload from one of session 58's short files, which are what is on disk.

    A payload saved before the compressed fragment was understood is 2965 bytes with its third
    fragment still deflated. Nothing about those files is wrong except that they stop early, so
    they are repaired rather than thrown away - the party in them is a real console's.
    """
    payload = bytes(payload)
    if len(payload) == PAYLOAD_LENGTH:
        return payload
    if len(payload) != SHORT_LENGTH:
        raise ValueError(f"{len(payload)} bytes: neither whole ({PAYLOAD_LENGTH}) nor one of "
                         f"session 58's short files ({SHORT_LENGTH})")
    whole = payload[:FRAGMENT_2_END] + zlib.decompress(payload[FRAGMENT_2_END:])
    if len(whole) != PAYLOAD_LENGTH:
        raise ValueError(f"repaired to {len(whole)} bytes, expected {PAYLOAD_LENGTH}")
    return whole


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


ACCOUNT_ID_LENGTH = 10                # the repeated id either side of the tail's name field


def tail_account_id(payload, name):
    """-> the id the tail's player record repeats, or None when the record is not that shape.

    Structural, not an offset: the ten bytes after the name's terminator, checked against the ten
    that precede the record. A payload where those two do not agree is one this has not read.
    """
    at = bytes(payload).find(name.encode("utf-16-le") + b"\x00\x00", TAIL_OFFSET)
    if at < 0:
        return None
    after = bytes(payload[at + len(name) * 2 + 2:][:ACCOUNT_ID_LENGTH])
    return after if len(after) == ACCOUNT_ID_LENGTH and payload.count(after) == 2 else None


def rewrite(payload, *, trainer_name=None, trainer_id=None, secret_id=None, old_name=None,
            account_id=None):
    """-> the snapshot with a new trainer identity, and every other byte still the console's own.

    THE POINT OF THE PROJECT NEEDS ONE OF THESE AND IT MUST NOT BE THE CONSOLE'S OWN. 3456 bytes
    hold a trainer card, a status block and six party records, and nearly all of it is fields this
    project has never read. Building one from nothing would mean inventing every one of them, so
    ours is the console's snapshot with the identity moved - the same method `swsh.pokemon.build_from`
    and `bdsp.pokemon.build_from` use on a single Pokemon, for the same reason.

    THE IDENTITY HAS TO MOVE IN FOUR PLACES AT ONCE, AND SESSION 60 FOUND THE FOURTH. MyStatus, the
    trainer card and **every party record** were the three; the fourth is a plain UTF-16 copy of the
    name inside the tail at 0xAEC, the 660 bytes this project had never read. In sw70's payload it
    sits at 0xB14 between two copies of an eight-byte account token, which is the shape of a player
    record - and `nxldn-lab` builds one of those for its own connection response, with its own name
    in it.

    SO EVERY SNAPSHOT THIS PROJECT HAS EVER SENT SAID TWO THINGS AT ONCE: PkCamp in MyStatus, the
    trainer card and all six Pokemon, and Gurvan - the console's own player - in the tail. The
    trade screen draws the partner from MyStatus, which is why it read `partenaire: PKCAMP` while
    the payload still carried its own player's name. `party_matches_trainer` could not see it,
    because it only compares the party against MyStatus.

    The tail copy is found by SEARCHING for the name being replaced rather than by offset: 0xB14 is
    where it lands in one payload and the record around it is not read well enough to promise that
    it is fixed. `old_name` is what to look for; without it the tail is left alone.

    AND THE RECORD AROUND THE NAME CARRIES AN ID, TWICE. In sw70's payload the same ten bytes sit
    immediately before the name's block and immediately after its terminator, and they appear
    nowhere else in the whole snapshot:

        0x0AFA  <10-byte id>                the record opens with it
        0x0B04  16 bytes, high entropy      a key or a hash over the record
        0x0B14  "Gurvan\0" UTF-16           the name, null-terminated
        0x0B22  <the same 10-byte id>       and closes with it

    That is a player record, and it is the CONSOLE'S OWN. Every snapshot this project has sent
    handed the console back its own account identity - which the trade screen never draws, because
    it draws the partner from MyStatus. `account_id` replaces both copies. The sixteen bytes at
    0x0B04 are not understood and are left alone; if they authenticate the id then this cannot be
    made to work by editing, and a run that changes the id and fails the same way says so.
    """
    if len(payload) != PAYLOAD_LENGTH:
        raise ValueError(f"{len(payload)} bytes, expected {PAYLOAD_LENGTH}")
    out = bytearray(payload)

    if trainer_name is not None:
        encoded = trainer_name.encode("utf-16-le")
        if len(encoded) + 2 > NAME_LENGTH:
            raise ValueError(f"{trainer_name!r} is too long for a {NAME_LENGTH}-byte name field")
        encoded = encoded.ljust(NAME_LENGTH, b"\x00")
        ms = MY_STATUS_OFFSET + MY_STATUS_NAME
        out[ms:ms + NAME_LENGTH] = encoded
        tc = TRAINER_CARD_OFFSET + TRAINER_CARD_NAME
        out[tc:tc + NAME_LENGTH] = encoded
        if old_name:
            # THE TAIL COPY. Null-terminated and NOT padded to NAME_LENGTH, so the replacement is
            # written over exactly as many bytes as the old name occupied and the record around it
            # keeps its length. Every occurrence, because one payload is not proof there is one.
            was = old_name.encode("utf-16-le") + b"\x00\x00"
            now = trainer_name.encode("utf-16-le") + b"\x00\x00"
            if len(now) > len(was):
                raise ValueError(f"{trainer_name!r} does not fit where {old_name!r} was")
            now = now.ljust(len(was), b"\x00")
            at = out.find(was, TAIL_OFFSET)
            while at >= 0:
                out[at:at + len(was)] = now
                at = out.find(was, at + len(was))

    if account_id is not None:
        if old_name is None:
            raise ValueError("the tail's account id is found from the name it sits around")
        old_id = tail_account_id(payload, old_name)
        if old_id is None:
            raise ValueError("the tail carries no repeated id around that name")
        account_id = bytes(account_id)
        if len(account_id) != ACCOUNT_ID_LENGTH:
            raise ValueError(f"an account id is {ACCOUNT_ID_LENGTH} bytes")
        at = out.find(old_id)
        while at >= 0:
            out[at:at + ACCOUNT_ID_LENGTH] = account_id
            at = out.find(old_id, at + ACCOUNT_ID_LENGTH)

    if trainer_id is not None:
        struct.pack_into("<H", out, MY_STATUS_OFFSET + MY_STATUS_TID, trainer_id)
    if secret_id is not None:
        struct.pack_into("<H", out, MY_STATUS_OFFSET + MY_STATUS_SID, secret_id)

    edits = {k: v for k, v in (("ot_name", trainer_name), ("trainer_id", trainer_id),
                               ("secret_id", secret_id)) if v is not None}
    if edits:
        for slot in range(pokemon.PARTY_SLOTS):
            at = slot * gen8.SIZE_PARTY
            raw = bytes(out[at:at + gen8.SIZE_PARTY])
            if struct.unpack_from("<I", raw, 0)[0] == 0:        # an empty slot stays empty
                continue
            out[at:at + gen8.SIZE_PARTY] = pokemon.build_from(raw, **edits)
    return bytes(out)


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
