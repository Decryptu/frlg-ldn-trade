---
title: Sword and Shield
nav_order: 5
---

# Sword and Shield

The second **native** Switch title this project has read, and the first one whose Mystery Gift
menu has a local-wireless branch - the same shape of target as FireRed's Wonder Card, one
generation of hardware later.

Measured on a **Shield 1.3.2 EUR cartridge image** (`01008db008c2c000`, update NCA, SDK 7.7.0.0),
against a **French Sword 1.3.2** on the console. The two builds share their network code; where a
finding could differ between the pair it says so.

## What is under the game

Sword/Shield statically links the whole of Pia into `main` - 252 `nn::pia` classes and 2036 virtual
methods come straight out of the binary's own RTTI - and imports `nn::ldn` from nnSdk. So the stack
is the one this project already speaks: LDN underneath, Pia above it, and the game's own layer on
top of that.

Above Pia the game is **protocol buffers**, not hand-rolled structs: `main` carries the
`FileDescriptorProto` for every P2P message set it uses (`gflnet.p2p.framework.pb`,
`gflnet.p2p.block.pb`, `gflnet.p2p.sync.pb`, and one package per content - trade, battle, camp,
raid). A game that ships its own schema is a game whose messages do not have to be guessed.

## The LDN passphrase

    W3GoSMEn7RIIUQ89rzqBHGhGferRNb7K18ZBq2aNuj8Us9RO9Q9JYyGOZlLy8MYL

**64 bytes, used raw.** FACT, read out of the binary rather than a wiki: the game calls Pia's
`nn::pia::local::LdnCreateSessionSetting` passphrase setter with a literal length of `0x40` and a
rodata pointer, and the buffer at that pointer is the string above:

    0x006c3eb4  adrp x1, #0x203f000        ; the 64-byte literal
    0x006c3eb8  add  x1, x1, #0xf04
    0x006c3ec0  add  x0, sp, #0x10         ; the LdnCreateSessionSetting
    0x006c3ec4  mov  w2, #0x40             ; 64, not a NUL-terminated length
    0x006c3ec8  bl   #0x1790450

The binary holds **two identical copies** of it (`0x203ff04` and `0x203ff45`), which is what a
create path and a join path each carrying their own literal looks like.

It is **not** on the NintendoClients wiki's [LDN passphrases] page, which has no Sword/Shield row at
all. It is byte-for-byte the string that page gives for **Scarlet/Violet**, and differs from
**Legends: Arceus** in one character - `HGhG` here, `HGHG` there. A row that looks like a
transcription error in someone else's table is two real values.

[LDN passphrases]: https://github.com/kinnay/NintendoClientsWiki/blob/master/LDN-Passphrases.md

## The Pia game key

    p1frXqxmeCZWFv0X

The wiki's Pokemon Sword/Shield row, and now **verified in the binary**: the literal is at
`0x01c3dc87`, referenced from three call sites, and the one at `0x006ca91c` shows how it is used -
sixteen ASCII bytes loaded with a single `ldp` into a `{u32 enabled = 1; u8 key[16]}` beside the
session setting, handed to Pia's session entry at `0x0183fd10`:

    0x006ca914  mov  w8, #1 ; str w8, [sp, #0x18]     crypto enabled
    0x006ca91c  adrp x8, #0x1c3d000 ; add x8, x8, #0xc87
    0x006ca924  ldp  x9, x8, [x8]                     the 16 bytes, raw ASCII
    0x006ca938  stur x9, [sp, #0x1c]                  -> the setting's key field
    0x006ca93c  bl   #0x183fd10                       create/join, with the setting

Unlike BDSP's, this one needed no metadata archaeology: a native title keeps its constants in
rodata where a cross-reference finds them.

## Where the passphrase goes

Pia's own LDN wrapper holds it. `nn::pia::local::LdnCreateNetworkJob`'s object keeps the passphrase
at **+0xC4** and its length at **+0x104**, and the job builds the `nn::ldn::SecurityConfig` from
them immediately before calling `nn::ldn::CreateNetwork`:

    0x01797280  add  x1, x19, #0xc4        ; the passphrase
    0x01797284  ldrb w2, [x19, #0x104]     ; its length
    0x01797284  bl   memcpy                ; -> SecurityConfig +4
    0x017972bc  bl   nn::ldn::CreateNetwork

The same object holds the `NetworkConfig`'s intent at **+0xB8** (the local communication id, a u64)
and **+0xC0**. `nn::pia::local::LdnBackgroundProcessJob` validates the length as **16..64** before
any of this runs, which is the same range `docs/ldn.md` records.

## Pia here is version 4, and we have never spoken it

`docs/pia.md` had two bands, 6.32+ (version byte 15/16) and 5.27-5.45 (version byte 9). Sword and
Shield are **neither**: their header carries **4**, and the header is a different shape.

    0x00  4  magic 0x32AB9864, big-endian
    0x04  1  0x80 (encrypted) | version (0x7F) = 4
    0x05  1  a station index
    0x06  2  big-endian halfword
    0x08  8  AES-GCM nonce
    0x10  16 AES-GCM tag, NOT truncated to 8 the way 5.27-5.45 truncates it
    0x20     ciphertext

Read out of the game's own deserializer (`0x01774730`, which requires more than 0x1f bytes and then
copies field by field), its initializer (`0x017748bc`, one 64-bit store of `0x00000004_32AB9864`)
and three validators that each check `(byte & 0x7f) == 4`. **BDSP's binary has the identical three
validators against 9**, which is what makes this a comparison rather than a guess - see
`docs/pia.md` "The version-4 header".

So neither `pia_connect.py` nor `pia5.py` applies as it stands, and a third module is what talking
to this console will need. The session-key derivation is a separate question: `nn::pia::local` and
`nn::pia::lan` are both present and named here, so the same class-name test that settled it for BDSP
settles it here.

## Mystery Gift has a local branch

FACT, from the game's own state names. The receive-method chooser is
`StateSelectReceiveDataBase` and it has five siblings, one per menu button
(`L_mystery_top_btn_00` .. `_04`):

| state | what it is |
|---|---|
| `StateSelectReceiveDataInternet` | over the network |
| `StateSelectReceiveDataSerial` | a serial code / password |
| **`StateSelectReceiveDataLocal`** | **local wireless** |
| `StateSelectReceiveDataFromBall` | the Poke Ball Plus |
| `StateSelectReceiveDataRankMatch` | ranked-battle rewards |

and the receive states themselves are `StateReceiveBase`, `StateReceiveInternet`,
`StateReceiveSerial`, **`StateReceiveLocal`** (`0x01004938`), `StateReceiveFromBall`,
`StateReceiveRankMatch`, plus `StateReceiveNews` and `StateReceiveComplete`.

The game also counts what it received by channel: the play-record keys are `fushigi_net`,
`fushigi_serial` and **`fushigi_p2p`**, sitting beside `yy_battle_single_p2p` / `_net` in the same
table. A record key per channel is a channel the game expects to use.

And the menu is not a developer leftover - it is a line the player reads, in their own language.
`/bin/message/French/common/mystery.dat` in the base game's RomFS, decoded, gives the whole receive
menu:

| line | text |
|---|---|
| 63 | `Via Internet` |
| 64 | `Via un code ou mot de passe` |
| **69** | **`Via communication sans fil locale`** |
| 65 | `Voir vos Cadeaux Mystère` |

with the top menu above it at 72-75 (`Recevoir un Cadeau Mystère`, the Wild Area news, the Poké Ball
Plus, the Battle Stadium rewards).

**DEDUCTION: on that screen the console SEARCHES, so a distributor hosts and we would be the host.**
Line 42 is `Communication sans fil locale activée.`, exactly parallel to line 39's
`Connexion à Internet activée.`; line 9 is `Recherche de cadeau en cours...` and line 11
`Aucun cadeau n'a été trouvé.` That is a receiver scanning, not one advertising - which means
`--scan-only` seeing nothing on that screen is the expected result and not a failure.

The archive is the Gen 6/7/8 message container and `scratchpad/gfl_text.py` reads it. Its key was
solved out of the file rather than looked up: every line ends in a `0x0000` terminator, so rotating
the last ciphertext halfword back by three per character gives that line's starting key, and the
values across lines came out an arithmetic sequence - `0x7C89 + line * 0x2983`, rotating left by 3
within a line.

UNKNOWN: what `StateReceiveLocal` actually speaks. **There is no static call path** from the
Mystery Gift app to the LDN session setup - checked over the whole app to depth 10 with a
function-level call graph. That is not evidence the branch is dead: the game reaches its network
layer through vtables and delegates, which a static walk cannot follow, and the same search finds no
path from the Union Room's own code either.

A first attempt at this DID report a path, and it was an artefact worth recording: the walker
bounded each function by "the first 0x1000 bytes after its entry", walked through the `ret` into the
next function's body, and stitched two unrelated bodies into one edge. Both of the hops it produced
turned out to be refcounted-pointer setters that call nothing. `scratchpad/swsh_reach.py` builds a
real function-level graph now.

So the cheap decisive test is the air, not more reading: open the Mystery Gift local-wireless screen
on the console and see whether it advertises a network or is scanning for one.

## Reading the cartridge

The XCI is 13.3 GB on a network share and **nothing is unpacked**. `tools/switch/xci_read.py` walks
the HFS0 partitions, decrypts each NCA header in place (AES-128-XTS under `header_key`, big-endian
sector tweak) and prints the title id, content type, key generation, each section's offset, its
counter and its section key:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --keys prod.keys --type Program

A cartridge NCA's rights id is all zeroes, so there is no ticket step at all: the body key is key
area slot 2 under `key_area_key_application_<generation>`, where the generation is
`max(crypto_type, crypto_type2) - 1`. The 1.3.2 update's exefs is section 0 of the update Program
NCA, an ordinary CTR PartitionFS - the BKTR patching only touches its RomFS - so `main` comes out
with one more flag:

    ./.venv/bin/python tools/switch/xci_read.py <the.xci> --nca 87e41bc8 --exefs 0 --extract main

Then `nso_read.py` decompresses it (text 0..0x1900fc0, rodata to 0x24da168) and `rtti_names.py`
names the middleware:

    ./.venv/bin/python tools/switch/rtti_names.py main.bin 0x1900fc0 --rodata 0x1901000:0x24da168

`tools/switch/nso_imports.py` is what makes an `nn::ldn` call findable: a call into nnSdk goes
through a GOT slot filled by a JUMP_SLOT relocation naming the symbol, so the slot is the thing to
cross-reference, and its one PLT stub is the thing to count callers of.

## A gift is a multiple of 0x2D0 bytes

FACT, and it is the game checking rather than us measuring. At `0x00ff22d8` the Mystery Gift code
divides a received length by **0x2D0** - as a reciprocal multiply, `umulh` then `lsr #7` - takes the
remainder with `msub`, and **branches to the error path if it is non-zero**:

    0x00ff22e4  umulh x8, x21, x8        ; x21 = the length
    0x00ff22e8  lsr   x28, x8, #7        ; x28 = length / 0x2d0, the record COUNT
    0x00ff22ec  mov   w8, #0x2d0
    0x00ff22f0  msub  x8, x28, x8, x21   ; the remainder
    0x00ff22f4  cbnz  x8, #0xff272c      ; not a whole number of records -> refuse

So a gift payload is *n* records of 0x2D0 bytes and nothing else will be accepted. The same app
allocates a 0x2D0 object at `0x00feba7c`, which is one record. 0x2D0 is the size PKHeX gives a Gen 8
Wonder Card, so the two agree - but the number here came out of the game's own length check, which
is the one that matters when we are the side building the payload.

## Taking a seat

`bin/swsh_join.py` scans, reports and associates. It carries the passphrase above and nothing else
game-specific, because nothing else is settled: the local communication id is filled at runtime, so
the first run is a scan that writes every advertisement it sees to `scratchpad/swsh_net_facts.json`
and names the ones this project already knows.

    sudo -E ./.venv/bin/python bin/swsh_join.py --scan-only

**Point it at a screen where the console HOSTS, not at the Mystery Gift one.** A Link Trade over
local communication puts the console on the air; the Mystery Gift local screen looks like a receiver
searching, and a searching station has no advertisement to read. The comm id is per application, so
the id read off any local-wireless feature is the id the gift path uses too.

`--pw-mode` defaults to `raw` rather than to BDSP's sweep of readings, because the length here is an
instruction (`mov w2, #0x40`) rather than the length of a wiki string. If raw fails, the reading is
what to doubt last.

Above LDN there is nothing to run: version 4 has no transport in this repository. `pokeldn.swsh`
holds the constants and the one derivation that IS shared with BDSP - the LDN session key, whose
copy at `0x017ab010` is instruction-for-instruction `pokeldn.ldn.pia5.ldn_session_key`: seed an
xorshift128 with the recurrence around `0x6C078965`, take four draws into consecutive words, and
AES-128-ECB them under the game key that Pia keeps at `LocalProtocol+0x4d4` (its setter is at
`0x017ab750`, and what it copies is exactly the `{u32 enabled; u8 key[16]}` the game built).

That settles which of the two families applies. `nn::pia::local` and `nn::pia::lan` are both present
and named in this binary, and it is the **local** one - the LDN row of `docs/pia.md`'s table - that
holds this code.

## Open questions

- **The two unnamed header fields**, the byte at 0x05 and the halfword at 0x06. What writes them is
  `0x017beb74`/`0x017beb78`; what they mean is a deduction until a capture agrees.
- **What seeds the session key.** The derivation is settled; its input is not. `0x0179bff0` ->
  `0x01774f40` caches a value computed from `LocalProtocol+0x80`, and whether that is the
  advertisement's session parameter the way BDSP's is has not been read.
- **The local communication id and version.** Held at the Pia object's +0xB8 and +0xC0, filled at
  runtime from an object in `.bss` rather than a literal. Reachable from a scan of the console's own
  advertisement without reading any more code.
- **What `StateReceiveLocal` actually sends**, and whether the console hosts or scans on that
  screen. A scan answers the second half in one run.
- **Sword against Shield.** Everything above is read off Shield. The passphrase, the game key, the
  Pia version and the Mystery Gift states are game code, not per-version data, so they should be
  identical; association against the console is what proves it.
