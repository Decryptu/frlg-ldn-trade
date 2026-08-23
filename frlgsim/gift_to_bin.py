"""Export the Mystery Gift payload as the paired `.bin` files that
comradesean's `pokemon-gen3-mysterygift-tool` reads and injects into a Gen-3 save:

  https://github.com/comradesean/pokemon-gen3-mysterygift-tool
  (format: WONDERCARD_STRUCTURE.md in that repo)

The tool discovers `Tickets/<NAME>_WonderCard.bin` + `<NAME>_Script.bin` pairs and,
on inject, writes the payload into SaveBlock1 section 4 (FRLG card @ +0x460, script @
+0x79C) and recomputes the save's checksums. So unlike `save_inject.py` (which patches a
whole `.sav`), this just emits the two payload blobs the tool consumes.

Byte layouts (verified against the repo's official AURORA/MYSTIC tickets):

  <NAME>_WonderCard.bin  -- 336 B (0x150)
    0x000  u16  CRC-16 of the 332-B payload (game CalcCRC16: reflected 0x1021,
                init 0x1121, final one's-complement) -- little-endian
    0x002  u16  padding (0x0000)
    0x004  332  WonderCard payload == wonder_card.build_wonder_card(...)
    (the shipped tickets leave the CRC 0x0000 and let the tool recompute it; we write
     the real CRC, which is correct whether or not the tool recomputes.)

  <NAME>_Script.bin      -- 1004 B (sizeof struct RamScript, u32-aligned)
    0x000  u16  CRC-16 of the 999-B RamScriptData -- little-endian
    0x002  u16  padding (0x0000) -- together the struct's u32 `checksum`
    0x004  999  struct RamScriptData: magic 51, mapGroup/mapNum/objectId 0xFF,
                then the 995-B (zero-padded) deliveryman script body
    0x3EB  1    trailing pad byte (struct RamScript rounded up to 1004)
"""

import os

from .gift_registry import GIFT_REGISTRY, add_flag_id_argument, resolve_flag_id
from .mystery_gift import crc16
from .wonder_card import (
    GIFT_BEAST_CUTSCENE, GIFT_CELEBI, WONDER_CARD_SIZE,
)
from .save_inject import build_ram_script_struct, RAM_SCRIPT_DATA_SIZE

# --- selectable gift payloads (--gift) -------------------------------------------------------
GIFT_NAMES = {
    GIFT_BEAST_CUTSCENE: "BEASTCUTSCENE_FRLG",
    GIFT_CELEBI: "CELEBI_FRLG",
}

# --- tool .bin geometry (WONDERCARD_STRUCTURE.md) --------------------------------------------
BIN_HEADER_SIZE = 4                                    # u16 crc + u16 pad
WONDER_CARD_BIN_SIZE = BIN_HEADER_SIZE + WONDER_CARD_SIZE            # 336
SCRIPT_BIN_SIZE = 1004                                 # sizeof(struct RamScript), u32-aligned


def build_wonder_card_bin(card):
    """The 336-B `<NAME>_WonderCard.bin`: crc16(payload) + pad + the 332-B WonderCard."""
    if len(card) != WONDER_CARD_SIZE:
        raise ValueError(f"card is {len(card)} B; must be {WONDER_CARD_SIZE}")
    out = crc16(card).to_bytes(2, "little") + b"\x00\x00" + bytes(card)
    assert len(out) == WONDER_CARD_BIN_SIZE, len(out)
    return out


def build_script_bin(script):
    """The 1004-B `<NAME>_Script.bin`: crc16(RamScriptData) + pad + the 999-B RamScriptData,
    trailing-padded to the u32-aligned sizeof(struct RamScript)."""
    ram_data, ram_crc = build_ram_script_struct(script)
    out = ram_crc.to_bytes(2, "little") + b"\x00\x00" + ram_data
    out += b"\x00" * (SCRIPT_BIN_SIZE - len(out))
    assert len(out) == SCRIPT_BIN_SIZE, len(out)
    return out


def build_gift_bins(card, script):
    """Return (wonder_card_bin_336, script_bin_1004) for a card + raw script body."""
    return build_wonder_card_bin(card), build_script_bin(script)


def write_gift_bins(out_dir, name, card, script):
    """Write `<out_dir>/<name>_WonderCard.bin` and `<name>_Script.bin`. Returns their paths."""
    wc_bin, sc_bin = build_gift_bins(card, script)
    os.makedirs(out_dir, exist_ok=True)
    wc_path = os.path.join(out_dir, f"{name}_WonderCard.bin")
    sc_path = os.path.join(out_dir, f"{name}_Script.bin")
    with open(wc_path, "wb") as fh:
        fh.write(wc_bin)
    with open(sc_path, "wb") as fh:
        fh.write(sc_bin)
    return wc_path, sc_path


def build_parser():
    import argparse
    ap = argparse.ArgumentParser(
        description="Export the Mystery Gift payload as the WonderCard/Script .bin pair for "
                    "comradesean's pokemon-gen3-mysterygift-tool")
    ap.add_argument("-g", "--gift", choices=GIFT_REGISTRY.static_choices,
                    default=GIFT_BEAST_CUTSCENE,
                    help="which gift payload to export (default: beast-cutscene)")
    add_flag_id_argument(ap)
    ap.add_argument("-o", "--out-dir", default=".",
                    help="directory to write the .bin pair into (default: cwd)")
    ap.add_argument("-n", "--name", default=None,
                    help="ticket base name (default: per-gift); files are "
                         "<name>_WonderCard.bin / <name>_Script.bin")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)

    try:
        card, script = GIFT_REGISTRY.build_static(
            args.gift, flag_id=resolve_flag_id(args))
    except ValueError as exc:
        ap.error(str(exc))
    name = args.name or GIFT_NAMES.get(
        args.gift, args.gift.replace("-", "_").upper() + "_FRLG")
    wc_path, sc_path = write_gift_bins(args.out_dir, name, card, script)
    print(f"wrote {wc_path} ({WONDER_CARD_BIN_SIZE} B: cardCrc=0x{crc16(card):04X})")
    _, ram_crc = build_ram_script_struct(script)
    print(f"wrote {sc_path} ({SCRIPT_BIN_SIZE} B: ramCrc=0x{ram_crc:04X}, "
          f"{RAM_SCRIPT_DATA_SIZE}-B RamScriptData)")
    print("drop both into the tool's Tickets/ directory, then select the preset and inject.")


if __name__ == "__main__":
    main()
