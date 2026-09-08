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

## Pia here is version 4, and it decrypts

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

So neither `pia_connect.py` nor `pia5.py` parses this header as it stands. **But the header is the
whole difference.** Underneath it, version 4 is 5.27's LDN family exactly - same session key, same
IV, same message framing - which is why `pokeldn/ldn/pia4.py` is fifty lines rather than a second
stack. See "What the console says" below, and `docs/pia.md` "The version-4 header".

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

**A seat was taken on 2026-09-07 (sw01).** The passphrase read out of the binary associates with a
retail Sword on the first reading tried, `raw`, 64 bytes. Association is about one in two, the same
coin flip BDSP has - a `ConnectionError: Connect failed with status code 1` is a retry, not a
finding - and the console's advertisement disappears within a minute or so of the seat being
released, so the player has to re-open the trade screen between runs.

The seat is an LDN seat and the console's screen does not react to it. What reacts is the air: from
the moment we associate, the console broadcasts Pia to `169.254.x.255:12345` about ten times a
second, and the derivation below reads it.

## What the console says

`pokeldn.swsh.session_keys` turns the advertisement into the keys, and it is BDSP's derivation with
one difference - **no version substitution**, because the game key here is a literal:

    session key   = ldn_session_key(GAME_KEY, application_data[12:16] little-endian)
    IV            = crc32(application_data[0:4] || the sender's MAC)[0:3] || source id || nonce
    tag           = sixteen bytes, checked in full

FACT, sw01: **484 of 484 packets authenticated**, source id 0 on every one. The session parameter
and the network id both move per session - a run against the wrong session's advertisement fails on
every packet, which is exactly what happened here for an hour before the two were matched up.

The payload is 5.27's presence-flagged message framing plus one field: a **24-byte** message header
rather than 16, body `size` bytes big-endian at offset 2, padded to a multiple of four, 0xFF to the
end of the packet. That arithmetic accounts for every payload in the capture exactly.

What it is saying, ten times a second, is a station announcement that already contains us:

    a9fe0e01 3039 ... 00      169.254.14.1:12345   station 0, the console
    a9fe0e02 3039 ... 01      169.254.14.2:12345   station 1, the seat we took

so the console has put our station in its own mesh table before anything of ours has spoken Pia.
`pokeldn.ldn.pia4` parses and builds the header; `tests/test_pia4.py` holds two of the packets as a
golden vector, and a sixteen-byte tag makes them impossible to satisfy by accident.

## Answering it, and the console going quiet

FACT, sw02/sw03 (session 56). The console's announcement is **Pia's Local Protocol, protocol 0x24,
the same one BDSP speaks** - `pokeldn.ldn.local_protocol` reads Sword's field for field with no
change: version 1, message type 0x11, 0x30 fixed bytes, eight nine-byte seats, then the
host-migration byte. Seat 0 is the console at ranking 0 and seat 1 is us at ranking 1, and
`allow_participating` is true. Sword's Pia agrees with BDSP's on the protocol numbers too, read off
the `GetProtocolId` vfuncs rather than the wire: `0x017c8460` returns 0x14 (MeshStationProtocol) and
`0x017c4280` returns 0x18 (MeshProtocol).

A host repeats that update session until every station acknowledges it, so the 0x21 ack is the
cheapest possible first packet out: the pass signal is the rebroadcast STOPPING, and it needs
nothing on the console's screen and nothing above Pia.

    sw02   ack seq 2, the sequence the console sent    44 update sessions, then its last one
                                                       13 ms after our first ack, then SILENCE
                                                       for the remaining 26 s
    sw03   ack seq 3, a sequence it never sent         261 update sessions, 148 acks, never stopped

One run would have proved nothing - a console that stops advertising on its own looks identical.
The control is what makes sw02 a measurement: the two runs differ in one field of one message, and
that field is inside the encrypted payload, so the console decrypted our packet, walked the message
header, dispatched on protocol 0x24 and compared the sequence id. `bin/swsh_connect.py`,
`--seq-delta` is the control.

The station byte at header 0x05 and the IV's source-id byte were both 0, mirroring the console's
own; `--station-sweep` walks other readings if one is ever needed. What we send is built by
`pia4.build_message` / `pia4.build_packet`, and `tests/test_pia4.py` checks it against the console's
own bytes: given the console's values it reproduces the console's 24-byte header exactly.

## The game layer, and the first application data

FACT, sw52 and the binary. Every layer beneath the game is closed in both directions - LDN
association, Local Protocol 0x24, the station handshake 0x14, the mesh join 0x18, RTT 0x58, the
reliable window 0x7C and the broadcast reliable window 0x80. Over 120 seconds the console sent
**455 application messages carrying one distinct payload**, six bytes, sequence ids 1..233:

    61 00 00 00 0a 00

That is a heartbeat, and the game is waiting for something we have never sent. **Nothing of ours
has ever been application data on either window**, and both of them are waiting for our sequence 1:

- **0x80 says so out loud.** Its ack asks for ack id 1 in every filled slot, once a second, in sw29
  and sw52 alike - 256 messages, never moving. A window that has received nothing.
- **0x7C says so by its silence.** The console has never sent us an ack on 0x7C, not one in 2092
  messages, because that protocol only answers application data and we had only ever acked.

`bin/swsh_connect.py --send-data HEX` is the first application data of the project, on either
protocol (`--send-protocol`), retransmitting until it is acknowledged the way a window does. What
it builds is `reliable4.build_data_message`, and the offline proof is that it reproduces the
console's own sequence 1 byte for byte. `docs/pia.md` "Version 4's reliable header" has the five
checks the receive path applies in silence; `scratchpad/sw_validate_msg.py` runs the exact bytes we
are about to send through all five before an association is spent on them.

**THE PASS SIGNAL IS DIFFERENT ON EACH PROTOCOL AND NEITHER NEEDS THE GAME TO AGREE WITH US.** On
0x80 the ack id moves off 1 for the first time; on 0x7C the console sends an ack at all. Either
says the console decrypted our packet, walked the message, found itself in the destination list and
accepted a sequence into its window - and a game that then keeps sending the same six bytes is a
finding about the game rather than the transport.

## Answering it: five steps, and the game hands over its party

FACT, sw68 and sw70, with sw69 as the control. Answer the heartbeat and the game walks its own
state machine, and **none of the message ids below is guessed**: `main` ships a `FileDescriptorProto`
for every P2P message set and `scratchpad/swsh_proto.py` extracts all 78 of them. The six bytes the
console repeated for 2092 messages are a four-byte little-endian message id and a protobuf body:

    61 00 00 00  = message 97     gflnet.p2p.sync.ping.pb.SyncPingDataHolder
        0a 00        field 1  ping {}
        12 00        field 2  pingReply {}
        1a 00        field 3  pingSynced {}
    60 ea 00 00  = message 60000  gflnet.p2p.block.pb.BlockDataHolder
        0a 00        field 1  result {}          Result { bool isBlocking }
        12 02 08 01  field 2  imReady { isReady: true }

It was pinging us. The five steps, all reproduced twice:

    1  answer the ping continuously   --send-data 610000000a00 --send-mirror --send-count N
    2  ack EVERY reliable window      0x7C, 0x18 port 1, 0x80 - one unacked window kills the mesh
    3  answer `result{}` on 0x7C      the mirror must be PER PROTOCOL
    4  answer imReady on 0x80         --send2-data 60ea000012020801
    5  the console sends its party on 0x84

**ONE MESSAGE IS NOT A STREAM.** sw61 sent a single message, saw `pingReply` once and watched the
game fall back to pinging; sw64 sent 400, all acked, and the game stayed in the new state. And the
bytes matter in the other direction too: sw62 sent `pingReply` FIRST, before the console had asked
for it, and the heartbeat stopped after ten messages with nothing else all run.

**STEP 3 IS NAMED BY A CONTROL RUN, WHICH IS THE ONLY REASON IT IS IN THE LIST.** sw69 did
everything sw68 did and got no 0x84 at all. The one difference was what we answered on 0x7C: the
mirror kept a single "what it last said" across all protocols, so once the console spoke on 0x80
the 0x7C mirror echoed `imReady` back on 0x7C instead of `result{}`. Made per protocol, sw70
answered `result{}` again and the transfer came back.

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

## Open questions

- ANSWERED, sw68/sw70, and it is the point of the project's next step. **What the game says once
  it is answered**: it walks ping -> pingReply -> pingSynced, asks for `result{}` on 0x7C and
  `imReady` on 0x80, and then sends its own party on 0x84. See the two sections above.
- **Sending a party back.** Nothing of ours has ever been on 0x84. `pokemon_trade.proto` (package
  `net_contents.trade.common.pokemon_trade.protocol_buffers`) is `Pokemon { bytes
  serializePokemonParam }` and `PokemonTradeDataHolder { Pokemon pokemon }`, so a trade message is a
  serialised PK8 inside one protobuf field. `pokeldn/swsh/pokemon.py` builds and encrypts one;
  `build_from` edits a record the console itself sent, so every byte we have never read stays a real
  byte from a real save. What is NOT known is which message id carries it, and on which protocol.
- **The trailer of the 0x84 payload.** Six 24-byte records at 0xA00 and a raw-deflate stream at
  0xAF9 that carries the trainer name a third time. Nothing in the schemas has been matched to
  either yet, and the nine bytes that move between runs are all inside the deflate.
- **The two unnamed header fields**, the byte at 0x05 and the halfword at 0x06. What writes them is
  `0x017beb74`/`0x017beb78`; what they mean is a deduction until a capture agrees.
- ANSWERED, sw01. **What seeds the session key** is the advertisement's session parameter, twelve
  bytes in, little-endian - BDSP's offset exactly. The code at `0x0179bff0` -> `0x01774f40` computes
  a seed a different way (AES-GCM over the session's own two 64-bit values, keyed by them), so
  reading that path is what to do if a session ever turns up whose key this does not derive; for a
  console hosting a local trade, the advertisement is enough.
- ANSWERED, sw01. **The local communication id** is `0x0100ABF008968000` and the version is 4, scene
  60001, app version 7, read off the advertisement. That id is **Sword's**, and the binary this
  project reads is Shield - the first place the pair are known to differ.
- **What `StateReceiveLocal` actually sends**, and whether the console hosts or scans on that
  screen. A scan answers the second half in one run.
- **Sword against Shield.** Everything read off the binary is Shield's; the console is Sword. The
  passphrase, the game key and the Pia version are now measured to hold across the pair - they
  associated and decrypted - and the local communication id is measured NOT to. Mystery Gift's
  states are still Shield-only readings.
- ANSWERED, session 56, offline. **The message header's presence bits.** Bit 0x10 owns the extra
  eight-byte field and bits 0x20/0x40 own nothing, read off the size arithmetic the library inlines
  at eighteen sites (`docs/pia.md` "Which presence bit owns which field"). No second message shape
  was needed - the capture could not have separated them, and the code states it outright.
- ANSWERED, sw02/sw03. **What protocol 0x24 is**: Pia's Local Protocol, BDSP's numbering exactly,
  and the console acts on what we send it there.
- ANSWERED, sw20/sw21/sw24. **The Mesh Station Protocol (0x14) request.** Version 4 puts a flag
  byte at [3] and every field after it moves; clearing it is what got a request answered, and the
  console then completed the handshake and accepted us as a station. `docs/pia.md` "The version-4
  Mesh Station Protocol" and `pokeldn/ldn/station4.py`. The loop at `0x0185c5c0` reads a 32-entry
  table of `{u8, u16be, u64be, u64be}` = 19 bytes each and is a station table, not the request.
- ANSWERED, session 57, offline. **The Mesh Protocol (0x18) join.** Its dispatcher is `0x017c0c80`
  off `MeshProtocol::vfunc9`, its message table is BDSP's without 0x22 and 0x23, its join-request
  handler (`0x017c1700`) checks the same six bytes we already send, and its join-response parser
  (`0x017b4830`) has the same sixteen-byte header over **64-byte** entries with the index at 0x3E.
  `docs/pia.md` "The version-4 Mesh Protocol". SENT AND ANSWERED at sw29: one request, one
  acceptance, `our_index` 1, and the console then opened seven protocols at us.
