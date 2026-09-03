"""Save-format facts [decomp:src/save.c, include/save.h, include/global.h:759]: 32 sectors x 4096 B (3968 data +
footer: id @0xFF4 u16, checksum @0xFF6 u16, signature 0x08012025 @0xFF8, counter @0xFFC); two slots of 14 sectors;
sector roles rotate, so the footer id, not the physical index, says what a sector holds, and the live slot has the
greatest counter [decomp:src/save.c:466]. SaveBlock1 (0x3D68 B) spans ids 1..4; mysteryGift @0x3120 and ramScript
@0x361C both lie in id 4 (checksummed size 3816 B); cardCrc is at +448 and the card at +452 of MysteryGiftSave.
The deliveryman runs the script iff cardCrc == crc16(card), ValidateWonderCard passes, and the RamScript has magic 51,
map 0xFF/0xFF, objectId 0xFF and checksum == crc16(RamScriptData[999]) [decomp:src/script.c:554]. The save must
already have Mystery Gift enabled; injection does not unlock it."""

from .gift_registry import GIFT_REGISTRY, add_flag_id_argument, resolve_flag_id
from .mystery_gift import crc16, CARD_TYPE_COUNT, NUM_WONDER_BGS, SEND_TYPE_DISALLOWED, \
    SEND_TYPE_ALLOWED, SEND_TYPE_ALLOWED_ALWAYS
from .wonder_card import (
    GIFT_BEAST_CUTSCENE, WONDER_CARD_SIZE,
)

# Flash sector geometry [include/save.h].
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

# SaveBlock1 layout [include/global.h:759].
SB1_SIZE = 0x3D68
SB1_MYSTERYGIFT_OFF = 0x3120
SB1_RAMSCRIPT_OFF = 0x361C
WONDER_NEWS_SIZE = 444                                    # u16 id + 2 u8 + 40 + 10*40
MYSTERYGIFT_CARDCRC_OFF = SB1_MYSTERYGIFT_OFF + 4 + WONDER_NEWS_SIZE          # 0x3120 + 448
MYSTERYGIFT_CARD_OFF = MYSTERYGIFT_CARDCRC_OFF + 4                            # 0x3120 + 452

SECTOR_ID_SAVEBLOCK1_START = 1
SECTOR_ID_SAVEBLOCK1_END = 4
SAVEBLOCK1_END_CHUNK = SECTOR_ID_SAVEBLOCK1_END - SECTOR_ID_SAVEBLOCK1_START
SAVEBLOCK1_END_CHUNK_BASE = SAVEBLOCK1_END_CHUNK * SECTOR_DATA_SIZE

# RamScript layout [include/global.h RamScript/RamScriptData, src/script.c].
RAM_SCRIPT_MAGIC = 51                                     # src/script.c:12
RAM_SCRIPT_MAP_UNDEFINED_BYTE = 0xFF                     # MAP_GROUP/MAP_NUM(MAP_UNDEFINED == 0xFFFF)
RAM_SCRIPT_OBJECT_ID = 0xFF                              # InitRamScript_NoObjectEvent
RAM_SCRIPT_BODY_MAX = 995                                # sizeof RamScriptData.script
RAM_SCRIPT_DATA_SIZE = 4 + RAM_SCRIPT_BODY_MAX          # magic+mapGroup+mapNum+objectId + script = 999


def sb1_chunk_size(chunk_index):
    """SAVEBLOCK_CHUNK size [decomp:src/save.c:44]; the last chunk is short."""
    off = chunk_index * SECTOR_DATA_SIZE
    if SB1_SIZE < off:
        return 0
    return min(SB1_SIZE - off, SECTOR_DATA_SIZE)


def sector_checksum(sector_data, size):
    """CalculateChecksum [decomp:src/save.c:614]: u32-word sum over `size` bytes folded to a u16."""
    total = 0
    for i in range(size // 4):
        total = (total + int.from_bytes(sector_data[i * 4:i * 4 + 4], "little")) & 0xFFFFFFFF
    return ((total >> 16) + total) & 0xFFFF


def build_ram_script_struct(script_bytes):
    """Returns (RamScriptData_999, crc16): magic 51, MAP_UNDEFINED bytes, objectId 0xFF, zero-padded script."""
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
    """Physical index of the active slot's id-4 sector (greatest counter among signed sectors); returns
    (phys_index, counter)."""
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
    """Returns (new_save_bytes, metadata); the input is not modified."""
    if len(card) != WONDER_CARD_SIZE:
        raise ValueError(f"card is {len(card)} B; must be {WONDER_CARD_SIZE}")
    phys, counter = find_saveblock1_end_sector(sav_bytes)
    sav = bytearray(sav_bytes)
    base = phys * SECTOR_SIZE

    cardcrc_off = MYSTERYGIFT_CARDCRC_OFF - SAVEBLOCK1_END_CHUNK_BASE
    card_off = MYSTERYGIFT_CARD_OFF - SAVEBLOCK1_END_CHUNK_BASE
    ramchk_off = SB1_RAMSCRIPT_OFF - SAVEBLOCK1_END_CHUNK_BASE
    ramdata_off = ramchk_off + 4

    card_crc = crc16(card)
    ram_data, ram_crc = build_ram_script_struct(script)

    # u32 fields; crc16 is a u16 so the high halfword stays zero.
    sav[base + cardcrc_off:base + cardcrc_off + 4] = card_crc.to_bytes(4, "little")
    sav[base + card_off:base + card_off + WONDER_CARD_SIZE] = card
    sav[base + ramchk_off:base + ramchk_off + 4] = ram_crc.to_bytes(4, "little")
    sav[base + ramdata_off:base + ramdata_off + RAM_SCRIPT_DATA_SIZE] = ram_data

    size = sb1_chunk_size(SAVEBLOCK1_END_CHUNK)
    chk = sector_checksum(sav[base:base + SECTOR_DATA_SIZE], size)
    sav[base + SECTOR_CHECKSUM_OFF:base + SECTOR_CHECKSUM_OFF + 2] = chk.to_bytes(2, "little")

    return bytes(sav), {
        "phys_sector": phys, "slot": phys // NUM_SECTORS_PER_SLOT, "counter": counter,
        "card_crc": card_crc, "ram_crc": ram_crc, "sector_checksum": chk, "checksum_size": size,
    }


def inject_selected_gift(sav_bytes, gift=GIFT_BEAST_CUTSCENE, *, flag_id=1003):
    card, script = GIFT_REGISTRY.build_static(gift, flag_id=flag_id)
    return inject_gift(sav_bytes, card, script)



def read_saved_wonder_card(sav):
    phys, _ = find_saveblock1_end_sector(sav)
    base = phys * SECTOR_SIZE
    cardcrc_off = MYSTERYGIFT_CARDCRC_OFF - SAVEBLOCK1_END_CHUNK_BASE
    card_off = MYSTERYGIFT_CARD_OFF - SAVEBLOCK1_END_CHUNK_BASE
    stored = int.from_bytes(sav[base + cardcrc_off:base + cardcrc_off + 2], "little")
    card = bytes(sav[base + card_off:base + card_off + WONDER_CARD_SIZE])
    return card, (stored == crc16(card))


def validate_wonder_card(card):
    """ValidateWonderCard [decomp:src/mystery_gift.c:193]."""
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
    """GetSavedRamScriptIfValid [decomp:src/script.c:554]: the script body the console would run, else None."""
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
