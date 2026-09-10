"""A Sword/Shield Pokemon on the wire: the 0x158-byte PK8, and the party of six it arrives in.

Measured on the air. Once `imReady` is answered the console opens
`nn::pia::transport::ReliableBroadcastProtocol` - protocol 0x84, which had never spoken in this
project - and sends 2965 bytes in three fragments. **The first 0x810 of that is the player's party:
six PK8 records at a 0x158 stride**, and 6 * 0x158 IS 0x810 exactly, so the stride and the count
are one reading and not two guesses.

The format is `pokeldn.gen8`, unchanged - in PKHeX, PK8 and BDSP's PB8 are the same `G8PKM` class
with one extra field each. What is true of Sword and of nothing else is HERE:

  - **it sends the PARTY form, 0x158**, where a BDSP trade sends the 0x148 stored form. The extra
    0x10 is the battle stats, encrypted with the LCG RESTARTED and never permuted.
  - the party arrives as a fixed six slots, empty ones zero-filled, not a counted list.

The level is in that tail, and it is what settles the block order. A party first read out
at levels 110 and 118 - impossible ones - from a tail nothing had decrypted, behind a body whose
block order was inverted. With both fixed the same bytes give Ectoplasma 100, Jungko 75 and
Dracolosse 73: **the player's own team, in party order, at the levels they named**, and the levels
come from a region outside the four shuffled blocks, so they are independent evidence for the
shuffle rather than a restatement of it. The experience field agrees separately - 1059860 is
exactly Medium Slow's level 100.

PK8 stores experience and not a level in its body; a stored-form PK8 therefore needs the growth
table to give a level, and a party-form one does not. `docs/swsh.md`.
"""
import struct

from pokeldn import gen8
from pokeldn.gen8 import OFF_DYNAMAX_TYPE, SIZE_PARTY, SIZE_STORED   # noqa: F401 - the PK8 view

PARTY_SLOTS = 6
PARTY_BLOCK = PARTY_SLOTS * SIZE_PARTY        # 0x810, and the payload's first 0x810 is exactly this


def decrypt(raw):
    """-> the plain, unshuffled record. Party or stored form; raises on a bad checksum."""
    return gen8.decrypt(raw)


def encrypt(plain):
    """-> the bytes to put on the wire, with the checksum written from the body itself."""
    return gen8.encrypt(plain)


def read(raw):
    """-> what one PK8 says about itself, party stats included when it is the party form."""
    return gen8.read(gen8.decrypt(raw))


def build_from(template_raw, **fields):
    """-> an encrypted PK8 made by editing a REAL one - see `gen8.write` for the fields.

    Nothing of ours has been on 0x84 yet, and when it goes it goes as an edit of a record the
    console itself sent: 0x158 bytes hold ribbons, memories, met data and handler records this
    project has never read, and a template keeps every one of them a real byte from a real save.
    """
    return encrypt(gen8.write(decrypt(template_raw), **fields))


def party(blob, slots=PARTY_SLOTS):
    """-> one entry per party slot of a 0x84 payload: the read fields, or None for an empty slot.

    An empty slot is an encryption constant of ZERO, which is how slots 4-6 arrive from a player
    carrying three Pokemon. Do not read emptiness out of a species of 0 instead: a first
    reading called slot 3 empty when it held a Dracolosse, because a wrong block order had put the
    species word somewhere else and the checksum could not see it.
    """
    if len(blob) < slots * SIZE_PARTY:
        raise ValueError(f"{len(blob)} bytes, need {slots * SIZE_PARTY} for {slots} slots")
    out = []
    for slot in range(slots):
        raw = blob[slot * SIZE_PARTY:(slot + 1) * SIZE_PARTY]
        if struct.unpack_from("<I", raw, 0)[0] == 0:
            out.append(None)
            continue
        fields = read(raw)
        fields["slot"] = slot + 1
        out.append(fields)
    return out
