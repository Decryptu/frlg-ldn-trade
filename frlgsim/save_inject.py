"""Inject a Mystery Gift Wonder Card + delivery RAM script into an FRLG save.

The generated save exercises exactly the same card and RAM-script bytes as the
live LDN distributor without requiring a console link. Always keep a backup of
the original save.

Save-format facts (from the pokefirered decomp; offsets are decomp line-cited):

  Flash layout [src/save.c, include/save.h]
    - 32 physical sectors of SECTOR_SIZE = 4096 B each: SECTOR_DATA_SIZE = 3968 B of
      data + a 128-B footer whose last 12 B are used:
          id @ 0xFF4 (u16), checksum @ 0xFF6 (u16), signature @ 0xFF8 (u32), counter @ 0xFFC (u32)
    - SECTOR_SIGNATURE = 0x08012025 marks a written sector.
    - Two save slots: physical sectors 0..13 (slot 0) and 14..27 (slot 1); 14 sectors
      each. The game rotates which physical sector holds which logical `id`, so the
      footer `id` — not the physical index — says what a sector contains.
    - The active slot is the SAVE_STATUS_OK slot with the greatest footer `counter`
      (GetSaveValidStatus, save.c:466); the loaded slot is `counter % NUM_SAVE_SLOTS`,
      which is exactly where that greatest-counter sector physically sits.
    - Sector checksum (CalculateChecksum, save.c:614): sum the data as u32 words over
      `locations[id].size` bytes, then fold `(sum >> 16) + sum` into a u16.

  SaveBlock1 [include/global.h:759, sizeof 0x3D68]
    - Spans logical sector ids 1..4 (chunk indices 0..3), 3968 B per chunk.
    - mysteryGift @ 0x3120 (struct MysteryGiftSave) and ramScript @ 0x361C (struct
      RamScript) both fall in chunk 3 == sector id 4, so a single sector's checksum
      covers both writes. For id 4 the checksummed size is
          min(0x3D68 - 3*3968, 3968) = 3816 B,
      and every byte we touch lies inside it.
    - Within MysteryGiftSave [global.h:680]: u32 newsCrc, WonderNews news (444 B),
      u32 cardCrc, WonderCard card (332 B), ... — so cardCrc is at +448 and the card
      at +452.

  Delivery gate [src/scrcmd.c ScrCmd_trywondercardscript -> src/script.c
  GetSavedRamScriptIfValid:554]: the Mystery Gift man runs our script iff
    - ValidateSavedWonderCard() [mystery_gift.c:180]: cardCrc == crc16(card) AND
      ValidateWonderCard(card) AND ValidateRamScript(); and
    - the RAM script's magic == RAM_SCRIPT_MAGIC (51), mapGroup/mapNum == the halves of
      MAP_UNDEFINED (both 0xFF), objectId == 0xFF, and
      checksum == crc16(&ramScript.data, sizeof(RamScriptData) == 999).
  So a valid card requires a valid RAM script too — we always inject both, together.

In-game prerequisite: the save must already have Mystery Gift enabled (the deliveryman
present on Pokemon Center 2F). Injection makes the card/script valid; it does not by
itself unlock the feature on a save that never enabled it.
"""

from .gift_registry import GIFT_REGISTRY, add_flag_id_argument, resolve_flag_id
from .mystery_gift import crc16, CARD_TYPE_COUNT, NUM_WONDER_BGS, SEND_TYPE_DISALLOWED, \
    SEND_TYPE_ALLOWED, SEND_TYPE_ALLOWED_ALWAYS
from .wonder_card import (
    GIFT_BEAST_CUTSCENE, WONDER_CARD_SIZE,
)

# --- flash sector geometry [include/save.h] -------------------------------------------------
SECTOR_DATA_SIZE = 3968
SECTOR_FOOTER_SIZE = 128
SECTOR_SIZE = SECTOR_DATA_SIZE + SECTOR_FOOTER_SIZE      # 4096
SECTOR_ID_OFF = SECTOR_DATA_SIZE + (SECTOR_FOOTER_SIZE - 12)   # 0xFF4
SECTOR_CHECKSUM_OFF = SECTOR_ID_OFF + 2                   # 0xFF6
SECTOR_SIGNATURE_OFF = SECTOR_ID_OFF + 4                  # 0xFF8
SECTOR_COUNTER_OFF = SECTOR_ID_OFF + 8                    # 0xFFC
SECTOR_SIGNATURE = 0x08012025
NUM_SECTORS_PER_SLOT = 14
NUM_SAVE_SLOTS = 2
SECTORS_COUNT = 32

# --- SaveBlock1 layout [include/global.h:759] ------------------------------------------------
SB1_SIZE = 0x3D68
SB1_MYSTERYGIFT_OFF = 0x3120
SB1_RAMSCRIPT_OFF = 0x361C
WONDER_NEWS_SIZE = 444                                    # u16 id + 2 u8 + 40 + 10*40
MYSTERYGIFT_CARDCRC_OFF = SB1_MYSTERYGIFT_OFF + 4 + WONDER_NEWS_SIZE          # 0x3120 + 448
MYSTERYGIFT_CARD_OFF = MYSTERYGIFT_CARDCRC_OFF + 4                            # 0x3120 + 452

SECTOR_ID_SAVEBLOCK1_START = 1
SECTOR_ID_SAVEBLOCK1_END = 4                              # chunk index 3
SAVEBLOCK1_END_CHUNK = SECTOR_ID_SAVEBLOCK1_END - SECTOR_ID_SAVEBLOCK1_START  # 3
SAVEBLOCK1_END_CHUNK_BASE = SAVEBLOCK1_END_CHUNK * SECTOR_DATA_SIZE           # 11904

# --- RamScript layout [include/global.h RamScript/RamScriptData, src/script.c] ----------------
RAM_SCRIPT_MAGIC = 51                                     # src/script.c:12
RAM_SCRIPT_MAP_UNDEFINED_BYTE = 0xFF                     # MAP_GROUP/MAP_NUM(MAP_UNDEFINED == 0xFFFF)
RAM_SCRIPT_OBJECT_ID = 0xFF                              # InitRamScript_NoObjectEvent
RAM_SCRIPT_BODY_MAX = 995                                # sizeof RamScriptData.script
RAM_SCRIPT_DATA_SIZE = 4 + RAM_SCRIPT_BODY_MAX          # magic+mapGroup+mapNum+objectId + script = 999


def sb1_chunk_size(chunk_index):
    """SAVEBLOCK_CHUNK size for a SaveBlock1 chunk (save.c:44). The last chunk is short."""
    off = chunk_index * SECTOR_DATA_SIZE
    if SB1_SIZE < off:
        return 0
    return min(SB1_SIZE - off, SECTOR_DATA_SIZE)


def sector_checksum(sector_data, size):
    """CalculateChecksum (save.c:614): fold a u32-word sum over `size` bytes to a u16."""
    total = 0
    for i in range(size // 4):
        total = (total + int.from_bytes(sector_data[i * 4:i * 4 + 4], "little")) & 0xFFFFFFFF
    return ((total >> 16) + total) & 0xFFFF


def build_ram_script_struct(script_bytes):
    """The 999-byte `struct RamScriptData` body + its crc16 checksum for a delivery script.
    Returns (data_999, checksum_u16). The script is a no-object-event RAM script:
    magic 51, map MAP_UNDEFINED, objectId 0xFF, followed by the (zero-padded) script."""
    if len(script_bytes) > RAM_SCRIPT_BODY_MAX:
        raise ValueError(f"RAM script body {len(script_bytes)} B > {RAM_SCRIPT_BODY_MAX} B max")
    body = bytearray(RAM_SCRIPT_BODY_MAX)
    body[:len(script_bytes)] = script_bytes
    data = bytes([RAM_SCRIPT_MAGIC,
                  RAM_SCRIPT_MAP_UNDEFINED_BYTE, RAM_SCRIPT_MAP_UNDEFINED_BYTE,
                  RAM_SCRIPT_OBJECT_ID]) + bytes(body)
    assert len(data) == RAM_SCRIPT_DATA_SIZE, len(data)
    return data, crc16(data)


def _footer(sav, phys):
    base = phys * SECTOR_SIZE
    return {
        "id": int.from_bytes(sav[base + SECTOR_ID_OFF:base + SECTOR_ID_OFF + 2], "little"),
        "checksum": int.from_bytes(sav[base + SECTOR_CHECKSUM_OFF:base + SECTOR_CHECKSUM_OFF + 2], "little"),
        "signature": int.from_bytes(sav[base + SECTOR_SIGNATURE_OFF:base + SECTOR_SIGNATURE_OFF + 4], "little"),
        "counter": int.from_bytes(sav[base + SECTOR_COUNTER_OFF:base + SECTOR_COUNTER_OFF + 4], "little"),
    }


def find_saveblock1_end_sector(sav):
    """Physical sector index holding the active slot's SaveBlock1 chunk 3 (footer id == 4).

    The active slot is the one with the greatest save counter; all its sectors share that
    counter, so the id-4 sector with the greatest counter (among signed sectors) is the one
    the game will load. Returns (phys_index, counter). Raises if none is found."""
    if len(sav) < SECTORS_COUNT * SECTOR_SIZE:
        raise ValueError(f"save is {len(sav)} B; need >= {SECTORS_COUNT * SECTOR_SIZE} B "
                         "(a 128 KiB FLASH1M FireRed/LeafGreen save)")
    best = None
    for phys in range(SECTORS_COUNT):
        f = _footer(sav, phys)
        if f["signature"] != SECTOR_SIGNATURE or f["id"] != SECTOR_ID_SAVEBLOCK1_END:
            continue
        if best is None or f["counter"] > best[1]:
            best = (phys, f["counter"])
    if best is None:
        raise ValueError("no valid SaveBlock1 chunk-3 sector (signature 0x08012025, id 4) found; "
                         "is this a real, saved FireRed/LeafGreen .sav?")
    return best


def inject_gift(sav_bytes, card, script):
    """Return a new save with `card` (332-B WonderCard) + its RAM `script` injected into the
    active slot's SaveBlock1 chunk-3 sector, cardCrc/ram-script checksum/sector checksum all
    fixed. Non-destructive: takes and returns immutable bytes. Also returns metadata about the
    sector written."""
    if len(card) != WONDER_CARD_SIZE:
        raise ValueError(f"card is {len(card)} B; must be {WONDER_CARD_SIZE}")
    phys, counter = find_saveblock1_end_sector(sav_bytes)
    sav = bytearray(sav_bytes)
    base = phys * SECTOR_SIZE

    # In-sector offsets: (absolute SaveBlock1 offset) - (start of chunk 3).
    cardcrc_off = MYSTERYGIFT_CARDCRC_OFF - SAVEBLOCK1_END_CHUNK_BASE
    card_off = MYSTERYGIFT_CARD_OFF - SAVEBLOCK1_END_CHUNK_BASE
    ramchk_off = SB1_RAMSCRIPT_OFF - SAVEBLOCK1_END_CHUNK_BASE
    ramdata_off = ramchk_off + 4

    card_crc = crc16(card)
    ram_data, ram_crc = build_ram_script_struct(script)

    # A u32 field written little-endian; crc16 returns a u16, high halfword stays zero.
    sav[base + cardcrc_off:base + cardcrc_off + 4] = card_crc.to_bytes(4, "little")
    sav[base + card_off:base + card_off + WONDER_CARD_SIZE] = card
    sav[base + ramchk_off:base + ramchk_off + 4] = ram_crc.to_bytes(4, "little")
    sav[base + ramdata_off:base + ramdata_off + RAM_SCRIPT_DATA_SIZE] = ram_data

    # Recompute this sector's footer checksum over the id-4 chunk size (3816 B), counter unchanged.
    size = sb1_chunk_size(SAVEBLOCK1_END_CHUNK)
    chk = sector_checksum(sav[base:base + SECTOR_DATA_SIZE], size)
    sav[base + SECTOR_CHECKSUM_OFF:base + SECTOR_CHECKSUM_OFF + 2] = chk.to_bytes(2, "little")

    return bytes(sav), {
        "phys_sector": phys, "slot": phys // NUM_SECTORS_PER_SLOT, "counter": counter,
        "card_crc": card_crc, "ram_crc": ram_crc, "sector_checksum": chk, "checksum_size": size,
    }


def inject_selected_gift(sav_bytes, gift=GIFT_BEAST_CUTSCENE, *, flag_id=1003):
    """Build and inject a supported gift. Returns ``(save_bytes, metadata)``."""
    card, script = GIFT_REGISTRY.build_static(gift, flag_id=flag_id)
    return inject_gift(sav_bytes, card, script)


# --- console-side model: mirror the game's read path, for offline verification ----------------

def read_saved_wonder_card(sav):
    """Return (card_bytes, cardcrc_ok) as the game would validate on the active slot."""
    phys, _ = find_saveblock1_end_sector(sav)
    base = phys * SECTOR_SIZE
    cardcrc_off = MYSTERYGIFT_CARDCRC_OFF - SAVEBLOCK1_END_CHUNK_BASE
    card_off = MYSTERYGIFT_CARD_OFF - SAVEBLOCK1_END_CHUNK_BASE
    stored = int.from_bytes(sav[base + cardcrc_off:base + cardcrc_off + 2], "little")
    card = bytes(sav[base + card_off:base + card_off + WONDER_CARD_SIZE])
    return card, (stored == crc16(card))


def validate_wonder_card(card):
    """ValidateWonderCard (mystery_gift.c:193): the field-range checks the console applies."""
    flag_id = int.from_bytes(card[0:2], "little")
    bitfield = card[8]
    card_type = bitfield & 0x3
    bg_type = (bitfield >> 2) & 0xF
    send_type = (bitfield >> 6) & 0x3
    max_stamps = card[9]
    return (flag_id != 0 and card_type < CARD_TYPE_COUNT
            and send_type in (SEND_TYPE_DISALLOWED, SEND_TYPE_ALLOWED, SEND_TYPE_ALLOWED_ALWAYS)
            and bg_type < NUM_WONDER_BGS and max_stamps <= 7)


def get_saved_ram_script_if_valid(sav):
    """Mirror GetSavedRamScriptIfValid (script.c:554): the deliveryman gate. Returns the raw
    script body (bytes) if the console would run it, else None."""
    card, crc_ok = read_saved_wonder_card(sav)
    if not (crc_ok and validate_wonder_card(card)):
        return None
    phys, _ = find_saveblock1_end_sector(sav)
    base = phys * SECTOR_SIZE
    ramchk_off = SB1_RAMSCRIPT_OFF - SAVEBLOCK1_END_CHUNK_BASE
    ramdata_off = ramchk_off + 4
    data = bytes(sav[base + ramdata_off:base + ramdata_off + RAM_SCRIPT_DATA_SIZE])
    stored_chk = int.from_bytes(sav[base + ramchk_off:base + ramchk_off + 2], "little")
    magic, map_group, map_num, object_id = data[0], data[1], data[2], data[3]
    if magic != RAM_SCRIPT_MAGIC:
        return None
    if map_group != RAM_SCRIPT_MAP_UNDEFINED_BYTE or map_num != RAM_SCRIPT_MAP_UNDEFINED_BYTE:
        return None
    if object_id != RAM_SCRIPT_OBJECT_ID:
        return None
    if crc16(data) != stored_chk:
        return None
    return data[4:]


def build_parser():
    import argparse
    ap = argparse.ArgumentParser(
        description="Inject a Mystery Gift payload into a FireRed/LeafGreen .sav")
    ap.add_argument("sav", help="path to a FireRed/LeafGreen .sav (128 KiB flash save)")
    ap.add_argument("-g", "--gift", choices=GIFT_REGISTRY.static_choices,
                    default=GIFT_BEAST_CUTSCENE,
                    help="gift payload to inject (default: beast-cutscene)")
    add_flag_id_argument(ap)
    ap.add_argument("-o", "--out", help="output path (default: <sav>.gift.sav)")
    ap.add_argument("--in-place", action="store_true", help="overwrite the input save")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)

    with open(args.sav, "rb") as fh:
        original = fh.read()
    try:
        injected, info = inject_selected_gift(
            original, args.gift, flag_id=resolve_flag_id(args))
    except ValueError as exc:
        ap.error(str(exc))

    # Self-check via the console model before writing anything out.
    script = get_saved_ram_script_if_valid(injected)
    if script is None:
        raise SystemExit("ERROR: injected save fails the console's deliveryman validation")

    out = args.sav if args.in_place else (args.out or args.sav + ".gift.sav")
    with open(out, "wb") as fh:
        fh.write(injected)
    print(f"injected {args.gift} gift into slot {info['slot']} "
          f"(phys sector {info['phys_sector']}, counter {info['counter']})")
    print(f"  cardCrc=0x{info['card_crc']:04X}  ramCrc=0x{info['ram_crc']:04X}  "
          f"sectorChecksum=0x{info['sector_checksum']:04X} over {info['checksum_size']} B")
    print(f"  deliveryman script validates ({len(script)} B body incl. padding)")
    print(f"  wrote {out}")


if __name__ == "__main__":
    main()
