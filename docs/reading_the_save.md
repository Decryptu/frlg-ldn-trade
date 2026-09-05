---
title: Reading the save (trainer ID, secret ID, IVs)
parent: Inside the console
nav_order: 7
---

# Reading the save

A Mystery Gift session can read the console's live save and print what the game never shows you: the
**secret ID**, and every party Pokemon's **PID, IVs and nature**. It takes one run, the console never
leaves its Mystery Gift menu, nothing is written and no Wonder Card changes hands.

This uses the native-code path, so read [Native code on the console](buffer_script.md) for how the
payload gets there. The short version: `save-dump` is handed `gSaveBlock2Ptr` and `gSaveBlock1Ptr` by
the console itself, so it needs no addresses and works on any save and either cartridge.

## Trainer ID and secret ID

SaveBlock2 offset 0 holds the player name, gender, the 32-bit trainer id and the play time
[decomp:include/global.h:327]. The low half is the TID printed on the trainer card; the high half is
the secret ID, which appears nowhere in the game and travels in no link message.

    (them) Mystery Gift -> Wonder Cards -> Friend, and wait on the search screen
    (you)  sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
               --buffer-script save-dump --dump-block sav2 --dump-size 64 \
               --dump-file dump.bin
    (them) join the host when it appears

    ./.venv/bin/python tools/dump_read.py dump.bin --block sav2

    dump.bin: 64 bytes from sav2 + 0x0
      playerName    'PLAYER'
      gender        boy
      trainerId     0xE5BBDF65  TID 57189  SID 58811
      playTime      148h 12m 30s

The TID is the check: it must match the number on the console's own trainer card. A dump that
disagrees is a bad read, whatever else it says.

## The party: PIDs, IVs and natures

SaveBlock1 0x34 is `playerPartyCount`, then `playerParty[6]` at 0x38, 100 bytes each
[decomp:include/global.h:772]. Six slots is 604 bytes, inside the 1024-byte per-run limit.

    (you)  sudo -E ./.venv/bin/python -u bin/frlgmg_host.py \
               --buffer-script save-dump --dump-block sav1 --dump-offset 0x34 \
               --dump-size 608 --dump-file party.bin

    ./.venv/bin/python tools/dump_read.py party.bin --block sav1 --offset 0x34 \
        --tid 57189 --sid 58811

    party.bin: 608 bytes from sav1 + 0x34
      playerPartyCount 5
      slot 1: ARCANINE  Lv72 nick='ARCANIN' OT='PLAYER' PID=0x30353ACA Lonely  IVs=[18,17,20,31,2,10] checksum ok
      slot 2: LUGIA     Lv77 nick='LUGIA'   OT='PLAYER' PID=0x91F854FF Relaxed IVs=[21,9,11,31,28,21] checksum ok

IVs read HP, ATK, DEF, SPE, SPA, SPD. Pass `--tid`/`--sid` to fill in the shiny column; without them
that column is left blank rather than guessed. Every stored mon carries a checksum over its
substructs, so `checksum ok` on every slot means the dump is a real party and not a stale buffer.

Party mons are stored exactly as a `.pk3`/`.ek3` stores them, which is why `frlgsim.mon` decodes
them unchanged: the 48 bytes at offset 0x20 are XORed with `PID ^ OTID`, and the four substructs
inside are ordered by `PID % 24`.

## Two things that will bite

**The party the game plays with is not the party in the save block.** `SavePlayerParty` copies
`gPlayerParty` into `gSaveBlock1Ptr->playerParty` when the console saves
[decomp:src/load_save.c:160], so SaveBlock1 holds the party as of the last save. For the live one,
dump `gPlayerParty` by address instead - 0x02024280 on both measured cartridges, with
`gPlayerPartyCount` at 0x02024025 (`frlgsim/rom_map.py`):

    --buffer-script memory-dump --dump-address 0x02024280 --dump-size 600

**Save block addresses move.** `SetSaveBlocksPointers` re-rolls them by a multiple of 4 in 0..124 on
every battle and every load [decomp:src/load_save.c:75]. Never carry an absolute save address from
one run to the next; `save-dump` takes the pointers fresh every call, which is why it is the one to
reach for.

## What else is in there

The same dump reaches money at SaveBlock1 0x0290, XORed with `SaveBlock2.encryptionKey` at 0xF20;
the bag; and the flags and vars. `memory-dump` takes an absolute address instead of a save block and
so reaches IWRAM, including `gRngValue` - see [the random number generator](rng.md), which uses that
to predict what the console will generate next.
