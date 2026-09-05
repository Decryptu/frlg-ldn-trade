---
title: The French Easy Chat vocabulary
parent: Inside the console
nav_order: 3
---

# The French Easy Chat vocabulary, read off the console

**Status: CLOSED.** All 1006 language-dependent Easy Chat words are read out of the console's own
ROM (bs16-bs36, eighteen hardware runs, every one first try). `frlgsim/easychat_french_words.py`
is the table; `easychat_french.french(id)` answers from it. Composing a phrase for a French
console is no longer a guess.

## What the problem was

An Easy Chat id is `(group << 9) | index` — a **slot**, not a word. `frlgsim/easychat_words.py` is
generated from the English decompilation, so it names what the ENGLISH ROM keeps in that slot.
Every localized ROM carries its own `gEasyChatGroup_*` tables, and nothing in the decomp can say
what the French one holds. Every phrase this project ever composed for a French console — mail, the
trainer card quote, the visiting trainer's lines, `--denied-message`, the questionnaire gate — went
out on the strength of the English table.

Three slots had been caught diverging before this work, one at a time, by putting an id somewhere
the console would render it and having the player read the screen: `EC_WORD_ENJOY` printed STRESSE
(mev02), `EC_WORD_DONE` printed FURAX (mev03), `SPEECH/12` printed LES (bs07). Eleven slots
established in two years, against 1006.

## How the table was found

**bs16 — a fingerprint, not a guess.** `sEasyChatGroups[]` is 22 entries of
`struct EasyChatGroup { const void *wordData; u16 numWords; u16 numEnabledWords; }`
[decomp:src/data/easy_chat/easy_chat_groups.h:26], 8 bytes each. Groups 8, 9 and 10 (Endings,
Feelings, Conditions) all hold 69 words with 69 enabled, so the word `0x00450045` appears **three
times, exactly 8 bytes apart**. One hit anywhere is a coincidence; three on that stride is the
table. `--buffer-script memory-scan --scan-word 0x00450045` over 0x08000000..0x08480000 returned
**exactly three hits and no false positives at all** in 4.5 MB, 288 frames, `never=[]` on all
thirteen blocks.

The range stopped at 0x08480000 by the decomp's LINK ORDER and never its addresses — the same
inference that named `random.o` for bs13. `src/easy_chat.o(.rodata)` is object #99 in
`ld_script.ld` and `src/mystery_gift_client.o(.rodata)` is #182, whose `sClientFuncs` was read off
the console at 0x0845DBD0 [rom_map.py], so the table is below it. It is, at **0x083E3700**.

**bs17 — the table, and the hypothesis that mattered.** All 22 entries read back with sane ROM
pointers and **counts identical to the English build's**. So the French ROM bins the same number of
words per group, an id is the same slot in both languages, and the two tables can be compared
index for index. That was an assumption until bs17; it is a measurement now.

The 22 word arrays and their text span 0x083DE2C8..0x083E3700 — 21560 bytes, contiguous, with each
group's strings sitting between its array and the next.

**bs18-bs36 — the words**, one group a run, with `--buffer-script string-gather` (see
`docs/buffer_script.md`). bs18 read EC_GROUP_FEELINGS and was self-verifying the moment it landed:
index 42 came back STRESSE and index 60 FURAX, which mev02 and mev03 had read off the console's own
screen by a completely different route. Nine more slots were confirmed the same way as the sweep
went on — SALUT, MERCI, JE SUIS LA, AMIS, POURQUOI, CONNEXION, AVEC, LES.

`tests/test_easychat_french.py` requires the render evidence and the ROM evidence to agree wherever
they overlap. Neither is worth much alone; that check is what makes either of them evidence.

**It caught one.** bs07 had recorded `TRAINER/11` as DRESSEURS. The ROM holds **DRESSEUR**,
singular, and no DRESSEURS exists anywhere in the 1006. bs07's gloss was written down from the
phrase on the console's screen, and a phrase read by eye is weaker than the table the game indexes.
The four questionnaire **ids** are untouched and the gate is unaffected — only the gloss was wrong.
The default phrase really renders `CONNEXION AVEC LES DRESSEUR`.

## What the table says

**How far the English table diverges depends entirely on the group, and the note it replaces
("mostly right and occasionally wrong") was true for some groups and badly wrong for others.**

`EC_GROUP_STATUS` is nearly exact, because its 109 words are Ability names with official French
translations: `stench`→PUANTEUR, `thick_fat`→ISOGRAISSE, `rain_dish`→CUVETTE, `drizzle`→CRACHIN,
`arena_trap`→PIEGE, `rock_head`→TETE DE ROC, `air_lock`→AIR LOCK (untranslated in French too).

`EC_GROUP_FEELINGS` is almost entirely re-binned. The English group is a grab-bag that includes
verbs — meet, play, eat, drink, see, hear, got, goes, go home — while the French one is **purely
emotional states from end to end**. Slot 13, English `disappoints`, holds RAVI: delighted, the
opposite. Slot 44, `eat`, holds HUMILIE. Slot 51, `drink`, holds HONTEUX.

The mechanism is visible in `EC_GROUP_SPEECH`: `but`→MAIS, `however`→CEPENDANT, `how`→COMMENT and
`the`→LE all line up, but French needs three forms of the article where English needs one, so LES
and L' took the neighbouring slots that English spends on `case` and `miss`. The localization kept
each group's theme and **displaced its neighbours** wherever the target language needed a different
number of words for a concept. Where a group is a list of proper nouns it barely moved; where it is
ordinary vocabulary it moved a lot.

There is no shortcut and no way to tell by looking at an id. Use the table.

## Using it

```python
from frlgsim import easychat, easychat_french
easychat_french.french(easychat.WORDS["enjoy"])     # 'STRESSE', not 'enjoy'
easychat_french.render(ids)                          # the line as the console will print it
easychat_french.check(ids, strict=True)              # raises on anything unread
```

`check` no longer flags real words — all 1006 are read — so what it still catches is an id that is
not a word at all, such as an index past the end of its group.

**The 807 slots that needed no reading.** `EC_GROUP_POKEMON`, `POKEMON_2`, `MOVE_1` and `MOVE_2`
print from `gSpeciesNames` / `gMoveNames` indexed by species number and move id
[decomp:src/easy_chat.c:155], so the console prints its own localized name and the slot means the
same thing in every language. `easychat.species_word(55)` and `easychat.move_word(177)` build them
and `easychat.is_language_safe` recognises them. mev03 proved it on hardware: the player typed
AKWAKWAK and the console stored POKEMON/55, SPECIES_GOLDUCK.

## The runs

| run | group | words | bytes | note |
|---|---|---|---|---|
| bs16 | `memory-scan 0x00450045` | — | — | 3 hits, no false positives; table at 0x083E3700 |
| bs17 | `sEasyChatGroups` | — | 1024 | 22 entries, counts identical to English |
| bs18 | FEELINGS | 69 | 558 | STRESSE at 42, FURAX at 60 |
| bs19 | SPEECH | 60 | 488 | LES at 12 |
| bs20 | TRAINER | 26 | 201 | CONNEXION at 9; **DRESSEUR** at 11 corrects bs07 |
| bs21 | ENDINGS | 69 | 422 | AVEC at 48 |
| bs22 | GREETINGS | 42 | 345 | SALUT, MERCI, JE SUIS LA |
| bs23 | PEOPLE | 75 | 459 | AMIS at 51 |
| bs24 | MISC | 42 | 303 | POURQUOI at 37 |
| bs25 | CONDITIONS | 69 | — | |
| bs26 | ACTIONS | 78 | — | |
| bs27 | BATTLE | 63 | — | |
| bs28 | VOICES | 63 | — | |
| bs29 | LIFESTYLE | 45 | — | |
| bs30 | HOBBIES | 54 | — | |
| bs31 | TIME | 45 | — | |
| bs32 | ADJECTIVES | 36 | — | |
| bs33 | EVENTS | 28 | — | |
| bs34 | TRENDY_SAYING | 33 | — | |
| bs35 | STATUS 0..82 | 83 | 760 | the budget stopped it, as designed |
| bs36 | STATUS 83..108 | 26 | — | resumed from the address bs35 reported |

Eighteen runs, all first try. bs35/bs36 are the proof that the payload's refusal to truncate works
on hardware: it stopped **before** the word that would not fit, said where to resume, and bs36
picked up at index 83 with no word lost or repeated.

## Reproducing or extending

    ./scratchpad/ec_sweep.sh bs37 GREETINGS 0x083DF5C0 42        # chain runs without prompting
    ./.venv/bin/python scratchpad/ec_words.py --group 4 --tag bs37 scratchpad/bs37_dump.bin
    ./.venv/bin/python scratchpad/ec_words.py --report

`scratchpad/ec_locate.py` finds the table in a scan answer and checks a dump of it against the
decomp's counts. The addresses of all 22 word arrays are in `scratchpad/ec_words.py`.

**A LeafGreen console does NOT need the whole thing again — that claim stood here and was wrong.**
Every address on this page was read off French FireRed (BPRF, software version 0x0A) and none of
them is valid on LeafGreen, which is what the claim got right. What it got wrong is the conclusion:
the whole Easy Chat region is a single uniform shift of **−0x1C4**, so every address here maps to
its LeafGreen counterpart by subtraction, and the vocabulary itself is identical. lg169 read
LeafGreen's group table — 22 entries, every count equal to the ones here — and lg170 then read
group 1 with `string-gather` and got 26/26 words back in the same slots: CE SERA TOI, JE T'AI EU,
ECHANGER, SAPHIR … ARGENT. So `easychat_french` answers for both consoles and the eighteen runs do
not have to be repeated. See [LeafGreen](leafgreen.md); use `rom_map.leafgreen_guess`, which knows
the region deltas and refuses the ranges where none has been measured.
