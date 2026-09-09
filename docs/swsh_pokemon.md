---
title: The party and the PK8
parent: Sword and Shield
nav_order: 3
---

# The party on 0x84, and the record inside it

The entity format both native titles share is in `pokeldn/gen8.py`; this is how a Sword puts
its party on the air.

## The party on 0x84, and it is a PK8

FACT, sw68 and sw70. Protocol 0x84 is `nn::pia::transport::ReliableBroadcastProtocol` - the class
`docs/pia.md` warns is NOT 0x80 - and it had never spoken in this project. It carries **3456 bytes
in three fragments**, repeated until acked, and only three of those bytes differ between two runs a
session apart.

**THE THIRD FRAGMENT IS COMPRESSED, AND THIS PROJECT MISSED IT FOR A SESSION.** Pia's message flag
0x10 - version 4's zlib flag, the same one that hid protocol 0x80 for two sessions - is set on it.
Concatenated raw the three fragments give 1404 + 1404 + 157 = 2965, which looks like a whole
payload because nothing in it states a length; inflated, the third is 648 bytes and the total is
exactly 3456. What session 58 wrote up as "a raw-deflate stream at 0xAF9 in the trailer" was that
fragment, unread, in the middle of the record. `pokeldn/swsh/trade_payload.py` refuses any
reassembly that is not 3456 bytes, which is the check that was missing.

**THE WHOLE LAYOUT IS NAMED**, and not by us: `kwsch/PokePiaSWSH` and `lincoln-lm/swsh-lan-client`
are published clients that read this payload over Sword's LAN mode, and session 59 found them by
searching the game key this project had held since session 53. What verified their layout is our
own capture, field for field.

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, start date at 0x170
    0xAEC  660 bytes NOT named by any published client       -> 0xD80 = 3456

MyStatus and TrainerCard are PKHeX save blocks (`Saves/Substructures/Gen8/SWSH/`), so their fields
come with a map. Ours reads trainer `Gurvan`, ids 56909/48474, game 44 (Sword), language 3, started
2019-11-15 - **and 0x924 + 0x170 IS 0xA94**, which is where session 58's unexplained "save date"
came from. It is the date the save was started, not the date it was written.

**THE PARTY IS THE FIRST 0x810: six PK8 records at a 0x158 stride.** The stride and the count are
one reading rather than two guesses, because 6 * 0x158 is 0x810 exactly. Empty slots are zero-filled
and an empty slot is **an encryption constant of zero**, not a species of zero - and the explicit
count at 0x810 agrees with that rule on both runs.

**AND THE TWO HALVES CORROBORATE EACH OTHER**: MyStatus gives ids 56909/48474 and all three PK8s
carry those same ids, from a different block of the payload.

The format is the Gen-8 entity, the same one BDSP trades - in PKHeX, `PK8` and `PB8` are both
`G8PKM` and neither overrides a shared offset. `pokeldn/gen8.py` is that format and
`pokeldn/swsh/pokemon.py` is what is true of Sword alone: **it sends the PARTY form, 0x158, where a
BDSP trade sends the 0x148 stored form.**

    0x00  u32  encryption constant, in the clear. Seeds the cipher and the block order
    0x06  u16  checksum, in the clear, over the decrypted body ONLY
    0x08       four 80-byte blocks, LCG-encrypted and permuted by (EC >> 13) & 31
    0x148      the party stats, LCG-encrypted with the stream RESTARTED, and never permuted

**THE PARTY STATS RESTART THE LCG.** `PokeCrypto.Decrypt8` calls `CryptArray` twice, both seeded
from the encryption constant; the stream does not run on across 0x148. A tail decrypted with the
continued stream gives nothing, which is what levels of 110 and 118 were.

**AND THE BLOCK ORDER IS APPLIED, NOT INVERTED** - `BLOCK_ORDER[sv]` names the block that becomes
block *i*. This project has now made that same mistake twice, in two modules, three sessions apart
(session 54 in BDSP's trade path, session 58 in the first 0x84 reader), and both times the checksum
agreed every single time, because it is a sum of 16-bit words and permuting whole blocks does not
change a sum. **Sixteen of the 32 sv values - ten of the 24 distinct orderings - are their own
inverse, so a wrong direction reads perfectly for those and garbles the rest** - which is exactly the shape sw70 showed: one slot right, two
wrong, six checksums verifying throughout. The format module is shared now so there is one place
left to get it wrong.

**WHAT THE PARTY READ IS CORROBORATED BY, and not one of them is a checksum:**

- the nicknames decode as French species names, in the console's own language;
- the species numbers match those names - 94, 254, 149;
- the levels are 100, 75 and 73, **which the player named before the payload was read**, and they
  come out of the party-stat tail, a region outside the four shuffled blocks and so independent
  evidence about the shuffle rather than a restatement of it;
- the experience agrees with the level on each one's own growth curve;
- and the **hyper-training byte at 0x126 agrees with the IV word at 0x8C, bit for bit**: slot 1
  reads `0x24`, DEF and SPE, and DEF and SPE are exactly and only the two IVs below 31. Two fields
  in different blocks, telling the same story about one Pokemon.

Both runs decode to the same three Pokemon. `scratchpad/sw84_read.py <payload.bin>` is the viewer.

**WHAT IS STILL UNREAD**: the 660-byte tail at 0xAEC, which no published client names either. 154
of its bytes are nonzero, the trainer name appears in it a third time, and FACT, from the two runs:
**exactly three bytes of the whole 3456 differ between sw68 and sw70**, one per 17-byte record in a
run of three otherwise identical ones. Within a run the byte DECREMENTS by one down the three;
between the runs it rose by 19, `4b 4a 49` to `5e 5d 5c`.

HYPOTHESIS, and it is one data point: it counts minutes. The two captures start 19 minutes apart
(12:25:04 and 12:44:25) and the value moved by 19. THE MEASUREMENT THAT SETTLES IT COSTS NOTHING -
every future run's payload is a third point, and a run taken an hour later should move it by about
60. Do not write this down as a clock until one does. 0x84's own message header is `11`/`12` as a type
byte, a counter at [4], and a total of 3456 at [10] that is a capacity and **not** the payload
length, which is 2965 in three fragments, always.
