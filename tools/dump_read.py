#!/usr/bin/env python3
"""Decode a save dump taken with `bin/frlgmg_host.py --buffer-script save-dump`.

    ./.venv/bin/python tools/dump_read.py DUMP.bin [--block sav1|sav2] [--offset 0x38]

`--block` and `--offset` are whatever the run asked for. SaveBlock2 at offset 0 holds the player
name, gender, play time and the 32-bit trainer id [decomp:include/global.h:327]; SaveBlock1 at 0x34
holds playerPartyCount followed by playerParty[6] [decomp:include/global.h:772].

Party mons are stored the way a .ek3 stores them, so frlgsim.mon decodes them unchanged: the
48-byte region at offset 0x20 is XORed with PID^OTID and its four substructs are shuffled by
PID % 24. The IVs, the nature and the shiny flag all come out of that region, and none of them is
printed anywhere in the game.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import charmap, mon as monlib
from frlgsim.rng_countdown import NATURE_NAMES

PARTY_OFFSET = 0x38
PARTY_COUNT_OFFSET = 0x34


def _substructs(raw):
    """The decrypted, unshuffled 48 bytes as {G, A, E, M}."""
    pid = int.from_bytes(raw[0:4], "little")
    key = pid ^ int.from_bytes(raw[4:8], "little")
    sec = bytearray(raw[32:80])
    for i in range(12):
        v = int.from_bytes(sec[i * 4:i * 4 + 4], "little") ^ key
        sec[i * 4:i * 4 + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    order = monlib.SUBSTRUCT_ORDER[pid % 24]
    return {k: bytes(sec[order.index(k) * 12:][:12]) for k in "GAEM"}


def read_party(data, first_offset, tid, sid):
    """first_offset is where SaveBlock1 0x38 lands inside this dump."""
    rows = []
    for slot in range(6):
        start = first_offset + slot * monlib.PARTY_MON_SIZE
        raw = data[start:start + monlib.PARTY_MON_SIZE]
        if len(raw) < 80:
            rows.append((slot, None, f"only {len(raw)} of 100 bytes in this dump"))
            break
        info = monlib.decode_mon(raw)
        if info is None or info["species"] == 0:
            rows.append((slot, None, "empty"))
            continue
        sub = _substructs(raw)
        ivs_word = int.from_bytes(sub["M"][4:8], "little")
        ivs = [(ivs_word >> (5 * i)) & 31 for i in range(6)]      # HP ATK DEF SPE SPA SPD
        pid = info["pid"]
        shiny = (tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF)) < 8 if tid is not None else None
        info.update(ivs=ivs, is_egg=bool((ivs_word >> 30) & 1), shiny=shiny,
                    nature=NATURE_NAMES[pid % len(NATURE_NAMES)],
                    friendship=sub["G"][9], ppbonus=sub["A"][8])
        rows.append((slot, info, None))
    return rows


def _print_trainer(data):
    trainer_id = int.from_bytes(data[0x0A:0x0E], "little")
    print(f"  playerName    {charmap.decode(data[0:8])!r}")
    print(f"  gender        {'girl' if data[8] else 'boy'}")
    print(f"  trainerId     0x{trainer_id:08X}  TID {trainer_id & 0xFFFF}  SID {trainer_id >> 16}")
    print(f"  playTime      {int.from_bytes(data[0x0E:0x10], 'little')}h "
          f"{data[0x10]}m {data[0x11]}s")


def _print_party(data, offset, tid, sid):
    if tid is None:
        print("  no trainer id given (--tid/--sid); the shiny column is left blank")
    if offset <= PARTY_COUNT_OFFSET < offset + len(data):
        print(f"  playerPartyCount {data[PARTY_COUNT_OFFSET - offset]}")
    party_at = PARTY_OFFSET - offset
    if party_at < 0 or party_at >= len(data):
        print("  SaveBlock1 0x38 (playerParty) is not inside this dump; nothing to decode")
        return
    for slot, info, why in read_party(data, party_at, tid, sid):
        if info is None:
            print(f"  slot {slot + 1}: {why}")
            continue
        shiny = "" if info["shiny"] is None else ("  SHINY" if info["shiny"] else "")
        print(f"  slot {slot + 1}: {info['species_name']:<12} Lv{info['level'] or '?':<3} "
              f"{'EGG ' if info['is_egg'] else ''}"
              f"nick={info['nickname']!r} OT={info['otName']!r} "
              f"PID=0x{info['pid']:08X} {info['nature']:<8} IVs={info['ivs']} "
              f"{'checksum ok' if info['checksum_ok'] else 'CHECKSUM BAD'}{shiny}")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path")
    ap.add_argument("--block", choices=("sav1", "sav2"), default=None,
                    help="which save block the dump came from (default: guessed)")
    ap.add_argument("--offset", type=lambda v: int(v, 0), default=0,
                    help="the --dump-offset the run used")
    ap.add_argument("--tid", type=int, default=None,
                    help="trainer id for the shiny test, if this dump does not carry it")
    ap.add_argument("--sid", type=int, default=None, help="secret id, likewise")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    with open(a.path, "rb") as fh:
        data = fh.read()
    print(f"{a.path}: {len(data)} bytes from {a.block or 'unknown block'} + 0x{a.offset:x}")

    block = a.block
    if block is None:
        block = "sav2" if a.offset == 0 and 0xFF in data[:8] else "sav1"
        print(f"  (guessed {block}; pass --block to be sure)")

    if block == "sav2" and a.offset == 0 and len(data) >= 0x12:
        _print_trainer(data)
        return
    _print_party(data, a.offset, a.tid, a.sid)


if __name__ == "__main__":
    main()
