"""Paired .bin files for comradesean's pokemon-gen3-mysterygift-tool (WONDERCARD_STRUCTURE.md):
WonderCard.bin = u16 crc16(card) LE + u16 pad + 332-B card (336 B);
Script.bin = u16 crc16(RamScriptData) LE + u16 pad + 999-B RamScriptData + 1 pad (1004 B = sizeof RamScript)."""

import os

from .gift_registry import GIFT_REGISTRY, add_flag_id_argument, resolve_flag_id
from .mystery_gift import crc16
from .wonder_card import (
    GIFT_BEAST_CUTSCENE, GIFT_CELEBI, WONDER_CARD_SIZE,
)
from .save_inject import build_ram_script_struct, RAM_SCRIPT_DATA_SIZE

GIFT_NAMES = {
    GIFT_BEAST_CUTSCENE: "BEASTCUTSCENE_FRLG",
    GIFT_CELEBI: "CELEBI_FRLG",
}

BIN_HEADER_SIZE = 4
WONDER_CARD_BIN_SIZE = BIN_HEADER_SIZE + WONDER_CARD_SIZE
SCRIPT_BIN_SIZE = 1004


def build_wonder_card_bin(card):
    if len(card) != WONDER_CARD_SIZE:
        raise ValueError(f"card is {len(card)} B; must be {WONDER_CARD_SIZE}")
    out = crc16(card).to_bytes(2, "little") + b"\x00\x00" + bytes(card)
    assert len(out) == WONDER_CARD_BIN_SIZE, len(out)
    return out


def build_script_bin(script):
    ram_data, ram_crc = build_ram_script_struct(script)
    out = ram_crc.to_bytes(2, "little") + b"\x00\x00" + ram_data
    out += b"\x00" * (SCRIPT_BIN_SIZE - len(out))
    assert len(out) == SCRIPT_BIN_SIZE, len(out)
    return out


def build_gift_bins(card, script):
    return build_wonder_card_bin(card), build_script_bin(script)


def write_gift_bins(out_dir, name, card, script):
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
