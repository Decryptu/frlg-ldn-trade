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

The wiki's Pokemon Sword/Shield row, and the same 16 bytes it gives for Legends: Arceus and for
Scarlet/Violet. Not yet verified against the binary - see the open questions.

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

UNKNOWN: what `StateReceiveLocal` actually speaks. It has not been read past its name, and nothing
here says whether the local branch reaches the same Pia session the rest of Y-Comm uses or opens one
of its own.

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

## Open questions

- **The Pia version band.** `docs/pia.md` splits at 6.32; BDSP is 5.27-5.45. Sword/Shield's SDK is
  7.7.0.0, older than BDSP's, but no version constant has been read yet and the version byte in the
  header decides which of `pia_connect.py` / `pia5.py` applies.
- **The local communication id and version.** Held at the Pia object's +0xB8 and +0xC0, filled at
  runtime from an object in `.bss` rather than a literal. Reachable from a scan of the console's own
  advertisement without reading any more code.
- **The game key**, taken from the wiki and not yet verified against the binary.
- **Sword against Shield.** Everything above is read off Shield. The passphrase and the Mystery Gift
  states are game code, not per-version data, so they should be identical; association against the
  console is what proves it.
