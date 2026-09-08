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

## The trade screen opens, and what it took

FACT, sw72-sw79, one variable per run. After the console sends its snapshot it waits, and what it
waits for is not another sync message - sw71 answered the whole sync set and the console said
nothing new at all. It is waiting for **its own transfer to be acknowledged and ours to arrive**.

    sw72   send our snapshot, nothing else        no change: the same five payloads
    sw73   ACK the console's 0x84 fragments       19142 messages -> 13, and it sent 0x19, DONE
    sw74   put ours on Pia PORT 1                 its ack base walks 0 -> 1 -> 2 -> 3
    sw75   tell it OUR transfer is complete       THE TRADE SCREEN OPENS
    sw76   answer the trade RPC                   it offers the Pokemon the player picked
    sw79   offer one back                         our offer is acknowledged

**NOTHING IN THIS PROJECT HAD EVER ACKED 0x84 AND THAT IS WHY IT REPEATED.** The protocol has more
kinds than the two sessions 58 and 59 saw, because a receiver that never answers never sees them:
0x21 is an ack carrying a contiguous BASE and a bitmask of what arrived early, 0x19 says a transfer
is complete and 0x28 answers it. `pokeldn/ldn/broadcast4.py`.

**AND THE TWO DIRECTIONS DO NOT SHARE A PIA PORT.** The console sends its snapshot on port 0 and
acks ours on port 1; ours went out on port 0 for a whole run and was never acknowledged. On port 1
its ack base walked to 3 and then repeated 3 four hundred and twenty-seven times - it had the whole
thing and was waiting for the 0x19 we had not learned to send.

**THE PLAYER SEES OUR INVENTED TRAINER.** The snapshot we send is the console's own with the
identity moved in MyStatus, the trainer card and every party record at once
(`swsh.trade_payload.rewrite`, 57 bytes of 3456), and the trade screen names that trainer as the
partner.

## The trade RPC, and where 20030 really comes from

FACT, sw75 and sw76. When the trade screen opens the console sends **message id 40030** as a PAIR,
several times a second, and it decodes without a guess:

    id 40030 = 40000 + 30
      1  offset      30            - the same 30 the id is built from
      2  base        10000, and 20000 in the other member of the pair
      3  station id  THE SENDER'S, byte-identical to the host_constant our own seat record holds
      4  clock       a counter that advances between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

**THIS IS WHERE THE HIGH IDS COME FROM, AND IT SETTLES THE OPEN QUESTION ABOVE.** `swsh_msgid.py`
found that no literal 20030 or 40030 exists anywhere in `main`, only the bases 10000/20000/40000
and code that adds a register to them. The envelope shows why: **the base and the offset travel as
separate fields**, and 20000 + 30 is assembled from them on the wire. A deduction became a
measurement, and its mechanism is visible rather than inferred.

Because field 3 is a station id and we know our own, answering is WRITING a field. `nxldn-lab`
reaches the same bytes by searching a capture for six known bytes and replacing them - that works
because these ids end in zeros, so a varint of one differs from a varint of another only in its
high bytes. Both of the console's own messages rebuild byte for byte from the parsed fields, which
is what makes the reader trustworthy. `pokeldn/swsh/trade.py`.

**AND THEN IT OFFERS A POKEMON, ON 20030.** `PokemonTradeDataHolder{pokemon{serializePokemonParam}}`
holding a **344-byte party-form PK8**, and it decoded to the Pokemon the player had picked on
screen a moment earlier - species 841, `Pomdrapi`, level 18, their own trainer name and ids, met at
level 18. Rebuilding that message from the record it carried gives the console's bytes back
exactly. So the trade message is 20030; **40030 is the envelope that precedes it**, and an earlier
reading of another client's prefixes that called 40030 the trade message was wrong.

## The game shows the player our Pokemon, and asks them to confirm

FACT, sw80-sw83. Two things stood between an acknowledged offer and a trade the player can see.

**THE TRADE RPC IS ON A DIFFERENT PIA PORT FROM EVERYTHING ELSE.** The console sends 19145 of its
40030 pair on **0x7C port 1**, while the ping, the block messages and the Pokemon offer all arrive
on port 0. Every RPC answer this project had sent went out on port 0 - a window the console does
not read them on - so the runs that "answered the RPC" had said nothing the game could hear.
Answered on port 1, with its own reliable window and its own sequence, the console acknowledged one
for the first time.

**AND THEN `imReady` ON THE TRADE HOLDER.** `3e4e000012020801` is message 20030 carrying
`imReady{isReady:true}` - the same shape that released the trade snapshot, one holder further
along. The console has never sent those bytes to us; the published client waits for them before it
offers, which is what suggested it was our turn to say them. With them sent, **the console
displayed our Pokemon and asked the player to confirm the trade**, and the player accepted.

**THE RUN THEN CRASHED, AND THE CONSOLE WAS RIGHT ABOUT WHOSE FAULT IT WAS.** At the confirmation
prompt the console sends a **three-byte** message; the reader raised on it, the receive task died,
and we stopped transmitting mid-trade. The player saw `la communication avec l'autre joueur a été
interrompue`, which is exactly what had happened - we were the one who left. **A reader on a live
run must not raise**, and every reader in `pokeldn/swsh/trade.py` now returns None instead.

## Where it stops, and it is not the application layer at all

With that fixed the run is clean and the console shows our Pokemon, takes the player's accept, and
then sends **nothing on the application layer for the remaining five minutes**. Session 59 read
that as a trade phase we do not speak, and looked to `andyjusa/nxldn-lab`'s selection RPCs on 40050
(`729c`) and confirmation stages on 40040 (`689c`) for what comes next.

**IT IS NOT WAITING ON THE APPLICATION LAYER. ITS LAST WORD IS TWO LAYERS DOWN.** Session 60,
FACT, from our own captures. Once the player accepts, the console sends twelve bytes on protocol
**0x18 port 1** and never speaks again:

    0f 00 00 03 00 01 00 01   44 00 01
    ^ version 4's reliable header, sequence 1     ^ the mesh message

**sw81 and sw83 both carry it, byte-identical, and no other run in this project has one** - and
those two are the only runs where the player pressed accept. `44` is the mesh protocol's
MIGRATION_START, `[0x44, host index 0, new host index 1]`, and sw83's own join response said
`stations=2 host_index=0 our_index=1`. **The console is naming us as the next host of its mesh.**
The answer is `[0x48, 1]`, two bytes; `docs/pia.md` "Host migration" carries both handlers and both
index getters, because that is Pia and true of any title.

This also names the three bytes that ended sw81. Session 59 recorded "the console sends a
THREE-BYTE message at the confirmation prompt and `trade.parse` raised" and hardened every
application reader against short buffers, which was right and is still right - but the three bytes
were never an application payload. Mesh protocol port 1 IS the reliable port, so the reliable
window is the transport and a mesh message rides inside it.

Our own offer, a Pokemon out of the party our snapshot advertised, is acknowledged by the reliable
window throughout.

## And we were shouting: 859 offers where the console sent one

FACT, sw83's own jsonl (`scratchpad/sw_tx_tally.py`). Every message the console sent it sent once
or a handful of times. Of ours:

    3e4e00000adb...   the Pokemon offer         859 times over 259 seconds
    5e9c00000a1a...   the trade RPC answer     1024 times over 309 seconds
    60ea000012020801  imReady on 0x80          1045 times over 315 seconds
    everything that moved the game on          EXACTLY ONCE

The window only advances a sequence once the last is acked, so those collapse to roughly forty and
fifty *delivered* duplicates rather than nine hundred - still forty copies of "here is my Pokemon"
to a console that asked once.

The cause is not a policy anyone chose. `said_by_proto` in `bin/swsh_connect.py` holds the last
payload the console put on a protocol and never clears, and the senders run on a 0.3 s timer, so
each tick re-derives an answer to a message already answered. It was harmless while the answer was
a ping echo, which is every phase that worked; it became an offer at t=23.8.

**This is a defect, not a hypothesis about the stall.** The game processed our offer while being
flooded - it showed the Pokemon to the player and took the accept - so the repetition did not stop
this trade. `--answer-once` answers each payload the console sends once, which is what the console
does, what every published client does, and what makes the next run legible.

## Where a message id comes from, and which ones are ours

FACT, off `main` (`scratchpad/swsh_msgid.py`). A P2P message is four bytes of little-endian id and a
protobuf body, and the ids come from two different places - which decides what is measured and what
is inferred.

**THE LOW IDS ARE A REGISTRATION TABLE.** 838 records of 24 bytes at `0x01BBFFA0`,
`{u64 handler slot, u32 0x402, u32 id, u64 0}`, ids 1..880. The slot pointers step by eight through
an array of identical thunks, so the table is id -> handler and nothing more. **97** (the ping
holder), **110**, **120** and **130** are all in it.

**THE HIGH IDS ARE COMPUTED, base plus offset**, which is why searching for one finds nothing.
20030, 40030, 40040 and 40050 appear NOWHERE in the image - not as an aligned word, not as a
MOVZ/MOVK/MOVN immediate - while 20000, 40000 and 60000 do, and the code around them adds a
register:

    mov w9, #0x4e20          ; 20000
    add w27, w22, w9         ; id = 20000 + w22

    ldrh w8, [x19, #0x372]
    mov w9, #0x4e20
    add w8, w8, w9           ; id = 20000 + a halfword out of the object

60000 is the one high id we have measured, and it is base + 0, a MOVZ at 41 sites.

**SO THE TRADE IDS ARE STRUCTURALLY CONSISTENT AND INDIVIDUALLY UNCONFIRMED.** `andyjusa/nxldn-lab`
names a trade flow over 20030/40030/40040/40050; the right bases exist and the offsets are small,
and that is a DEDUCTION, not a confirmation. An unaligned single occurrence of one of those values
in 40 MB is what four random bytes do, and counting it as evidence would make "the id is in the
binary" true of ids that are not.

## The box state machine, read out of the binary

Sixteen hardware runs swept box command values blind. This is the code that receives them, and it
settles what each one means without another association. Everything here is Shield 1.3.2's `main`,
addresses as `tools/switch/nso_read.py` writes them.

**THE TRADE SESSION IS ONE CLASS AND ITS SETUP IS `0x010c9280`.** One function constructs all three
trade contents in order and stores them in the session object:

    +0x120   content 30, the box exchange       ctor 0x010cca10, registers offset 30 at 0x010ce4f0
    +0x148   content 40, SyncSaveDataHolder     ctor 0x010da3f0
    +0x2b0   content 50, PokemonTradeDataHolder ctor 0x010d4d40
    +0x60    an event source, listeners in a vector at its own +0x60
    +0x68    our Pokemon        +0x70  theirs
    +0x140   the trade state, 1..9             +0x144  the error code
    +0x418   send-command-3-on-the-first-frame  +0x419  the role bit that suppresses it

It also writes four function pointers into `+0x90..+0xa8` and the session pointer into `+0xb0`.
That is a delegate, and it is the thing session 60 could not find: `0x010cc250` is its invoke
thunk and it tail-calls **`0x010ca800`**, the session's box callback, as `(session, code, payload)`.

**COMMANDS ARE 1..6 AND NOTHING ELSE.** `onBoxSyncStateCommand` is `0x010ce180`, vtable slot 1 of
the 0x50-byte wrapper at session+0x120 (vtable group `0x2625808`). It does three things:

1. `if (sender == our own station) return` - it ignores its own echo, `[[0x2616a30]]+0xf0`.
2. `w8 = msg->data`, then `if ((w8 - 1) > 5) return`. **0, 7, 8 and anything higher are dropped
   silently**, which is why sw91's sweep of 1..8 provoked nothing for half its values.
3. a six-entry jump table at `0x2067bec`, one case per command, each notifying every listener with
   the command value unchanged. The map is the identity: wire command N becomes event N.

Field 1 of the same holder - `boxSendPokemon` - goes to vtable slot 0, `0x010ce080`, and notifies
with event **0**. That is why the receive dispatcher takes 0..6 while the sender only ever emits
1..5: 0 is not a command, it is the Pokemon.

**AND THE COMMANDS COME IN TOGGLE PAIRS.** The listener is `0x00c8d900`. It keeps one flag byte per
event in an array at `+0x218`, `[owner + 0x218 + code] = 1` - and before it sets the new flag it
clears another:

    code 2 clears the flag for code 1        (+0x219)
    code 5 clears the flag for code 4        (+0x21c)

So the enum is not a list of unrelated pokes. **1 offers, 2 withdraws the offer; 4 confirms, 5
withdraws the confirmation.** Two facts measured on hardware fall out of that and stop being
mysteries: sx03 sent 1 then 2 and the console began leaving four seconds later - it was not a crash
and not a refusal, **we cancelled our own offer**; and sx07 put 4, 5 and 6 into the post-accept
window, where the 5 retracted the 4 about a second after it landed.

**THE SENDER IS `0x010cda70(content, command)`** and the game reaches it through five one-line
wrappers, `0x010cde90` .. `0x010cded0`, which are commands 1, 2, 3, 4 and 5 in address order. The
scene drives them from a six-way jump table at `0x00a96d10` keyed on its own action field `+0x78`:

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores our Pokemon and sets the trade state to 1

Two gates sit in front of the send, and both fail SILENTLY - the console looks identical on the air
whether it sent nothing or refused to:

    [content+0x48] holds a pending command; a DIFFERENT one arriving sets the error byte
                   [content+0x4d] and sends nothing at all
    [content+0x4c] is the channel-ready bool, set by 0x010ce040 on a zero result code; while it is
                   clear the command is parked in +0x48 and never goes out

**THERE IS AN OPENER AND WE HAVE NEVER SENT IT.** The session's per-frame update is `0x010c9bb0`,
and before it switches on the trade state it does this:

    if ([session+0x418]) { if (![session+0x419]) send command 3; [session+0x418] = 0; }

`+0x418` is set to 1 by the setup at `0x010c9280` and `+0x419` to `0x00dceea0() & 1`, which walks
the player list. So **exactly one of the two sides emits command 3 on its first frame after the
trade session is built, and which one is decided by a role bit.** Command 3 is the only value in
1..5 this project has never put on the air.

**THE TRADE STATE IS `[session+0x140]` and its table is at `0x2067b68`.** The table decodes to
seven live entries and **state 10 is one of them**, so the range is 1..10 rather than the 1..9 an
earlier reading of this page gave:

    1  0x010c9c78  -> 0x010ca0a0: start content 50 and send our Pokemon. true -> 2, false -> 9
    2  wait        5  wait        7  wait
    3  0x010c9f60  the Pokemon exchange - 0x010d54b0 on content 50 - then state 4, or 9 on error
    4  0x010c9c9c  the big one; 0x01109320 decides, and false goes to state 6
    6  0x010c9f84  -> 0x010ca1ac: install four delegates and START CONTENT 40
    8  0x010c9fa8  content 40's TEARDOWN - 0x010dac90 - then state 9
    9  0x010c9ef4  terminal: [+0x144] set means failure, and the listeners are told event 8
    10 0x010ca838

`[session+0x140]` also gates the whole box callback: `0x010ca800` drops every event unless the
state is 0, so once an error is recorded the session stops listening.

**STATE 2 DOES NOT LEAVE ITSELF, AND THAT IS THE WHOLE POINT.** Nothing in the update writes state
3. The write is in a delegate the state-1 branch installs at `session+0x2e0`, and the delegate is
`0x010cc380`: it takes the object it is handed, stores it at `session+0x70` (`0x766390`, and +0x70
is where the docs above put the PARTNER's Pokemon), builds a 0x60-byte record from it
(`0x010f5cc0`) and writes `[session+0x140] = 3`. **What moves the console out of state 2 is our
Pokemon arriving through content 50's own receive event - not a ping, not a confirmation, not a box
command.**

**AND STATE 8 IS NOT THE SAVE SYNC.** `0x010c9fa8` calls `0x010dac90(content40, session+0x170,
session+0x210)`, which walks the listener vectors at `[content+0x20]+0x60` and `[content+0x28]+0x60`,
removes those two, and tail-calls `0x010daac0` - the release, which drops the holder at +0x18 and
both event sources. It is content 40's teardown, and the state after it is 9.

None of this is in `nxldn-lab`, `PokePiaSWSH`, `swsh-lan-client` or `PSD` - all four encode the
holder and none of them names a command value. The wire format was published; the state machine
behind it was not.

**WHAT THE AIR SAYS BACK, sx09 and sx10.** Two runs tested the reading and both are one-variable
steps from the last:

    sx09  command 4 alone, sent on MIGRATION_START     acked; console still left 5 s later
    sx10  command 3 before the offer command, late     console left 3.5 s later, player still
                                                       picking, and the screen said the partner
                                                       had cancelled rather than the usual
                                                       communication error

sx09 is a clean negative for "4 is the confirmation the console is waiting for". sx10 is NOT a
result about command 3's meaning: `--box-commands` fires after our offer is acknowledged, and the
game emits its own 3 ten seconds earlier, on the first frame after the trade session exists. The
order was wrong, so the run measures the order and not the value. `--box-open` sends box commands
at the 0x84 snapshot ack instead, which is before either side offers anything.

**AND STATE 1 IS WHERE THE ABORT LIVES.** `0x010ca0a0` calls `0x010d5440`, content 50's send, which
opens with `bl 0x010d4d90` and **does nothing whatever if that returns false**. `0x010d4d90` is not
a gate on a send: it is content 50's own INIT, the twin of content 40's `0x010da470`, and it
registers with `mov w2, #0x32` - fifty. The caller then
takes the false branch to `[session+0x144] = 1`, which is state 9, error, listeners told event 8 -
the interrupted-communication message. The console has never put a 40050 on the air, so it has
never completed state 1: the accept runs, content 50 declines to send, and the session errors out
without a byte on the application layer. Every run since sw83 has that shape.

## A content is three holders, and 40000+offset is minted in the framework

Session 62, read out of Shield 1.3.2's `main` with no association spent. The three trade contents
are not three message ids; each one is a small family, and the family is built the same way for all
three.

**EVERY CONTENT REGISTERS THREE HOLDERS.** The registrar is one function per content -
`0x010ccd90` for 30, `0x010da7d0` for 40, `0x010d5150` for 50 - and each of them does the same
three things, reading the content's own offset from the halfword at `[content+0x372]`:

    ldrh w8, [x19, #0x372] ; mov w9, #0x2710 ; add w8, w8, w9    id = 10000 + offset  -> 0x010dd910
    ldrh w8, [x19, #0x372] ; mov w9, #0x4e20 ; add w8, w8, w9    id = 20000 + offset  -> 0x010d85f0
    ldrh w8, [x19, #0x372] ; mov w9, #0x7530 ; add w8, w8, w9    id = 30000 + offset  -> 0x010d0980

each handed to `0x006daeb0(manager, &holder, flag)` with flag 1, 0 and 0 in that order. **The
30000 family - 30030, 30040, 30050 - exists in every content this project has spoken to, and we
have never seen one on the air or sent one.**

**AND THE 40000 FAMILY IS MINTED ONE LAYER DOWN, WHICH IS WHY THE SEARCH FOR IT FAILED.** The base
class those holders hang off is constructed by `0x006d3f80`, which stores the content offset as a
BYTE at `[base+0x28]` (30, 40 or 50) and the constant `0xfc18` as a halfword at `[base+0xac]`. The
framework's start call `0x006d44e0` then reads that byte back and builds the id:

    ldrb w20, [x0, #0x28]          the content offset, 30 / 40 / 50
    mov  w9, #-0x63c0              a MOVN: w9 = 0xffff9c40
    add  w24, w20, w9
    strh w24, [x20, #0x160]        the low 16 bits: 0x9c5e / 0x9c68 / 0x9c72 = 40030 / 40040 / 40050

**40030, 40040 and 40050 are therefore measured in the image and no longer borrowed from
`nxldn-lab`.** `swsh_msgid.py` reported that no 40000 exists in `main` because it looked for a MOVZ
of 40000; the constant is a **MOVN of -0x63c0**, and 40000 never appears as a literal at all. Any
future id hunt has to accept that encoding.

`0x006d44e0` also opens with `strh w1, [x0, #0xac]`, overwriting the `0xfc18` the constructor put
there with its caller's argument - and `0xfc18` is exactly the `000018fc` that one member of the
observed 40030 pair carries in field 5, where the other carries `00000000`. That the constant and
both writes exist is FACT; that this field is where the pair's two values come from is a DEDUCTION.

## When each content starts, and why a 40040 cannot come early

**CONTENT 40 IS NOT BUILT WITH THE TRADE SESSION.** `0x010c9280` runs its small constructor
`0x010da3f0`, which does nothing but set two vtables, keep its arguments and zero its fields. The
init that registers 10040/20040/30040 and makes `0x006d44e0` mint 40040 is `0x010da470`, reached
only through `0x010dabc0` - and `0x010dabc0`'s only caller inside the session update is at
`0x010ca288`, in the **state 6** branch (`0x010c9f84` -> `0x010ca1ac`). Content 50's init
`0x010d4d90` is likewise reached only from state 1.

    state 1   content 50 starts: 10050, 20050, 30050 registered, 40050 minted
    state 6   content 40 starts: 10040, 20040, 30040 registered, 40040 minted

**SO NO 40040 OF ANY KIND CAN EXIST UNTIL THE TRADE HAS PASSED STATES 1, 2, 3 AND 4.** State 6 is
downstream of the Pokemon exchange (state 3) and of the state-4 decision at `0x01109320`, where the
game allocates a 0x90-byte record (`0x783c20`) and hands it `session+0x68` and `session+0x70` - our
Pokemon and theirs. Content 40 is `SyncSaveDataHolder`, and it is started after the swap has been
decided, not before it.

Three hardware runs were spent on the other reading: sx28 pinged content 40's 10000-base holder,
sx31 sent the sync-120 ping, sx32 was launched to send a 40040 RPC pair. **The console was never
going to answer any of them, because the object that would answer had not been constructed.** The
same is true of the confirmation stages `nxldn-lab` records on 40040: they are real, and they
belong after the exchange rather than before it.

What that leaves is state 2, and state 2 wants one thing - the partner's Pokemon delivered through
content 50's receive event, which is what `0x010cc380` turns into `[session+0x140] = 3`.

**AND THE RECEIVE HANDLER DISPATCHES ON THE SENDER'S STATION INDEX, WITH A SILENT DROP IF IT CANNOT
RESOLVE ONE.** Content 50's wrapper vtable is the group at GOT `0x2625988`, and slot 0 -
`0x010d5e40`, the same position content 30 puts `boxSendPokemon` in - reads like this:

    w0 = 0x006b5850(senderStationId)      Pia: mesh->GetStationIndex(&index, id); -3 (0xfd) on failure
    if (w0 == 0xfd) { [content+0x1a4] = 1; return; }          NOTHING is parsed, nothing is answered
    memcpy(stack, body, 0x158)                                0x158 = 344 = the party-form PK8
    subscriber = [content + 0x30 + index*8]                   one slot per station index
    if (subscriber == null || its refcount is 0) return       also silent
    ... invoke it

`0x006b5850` is a two-line wrapper on the mesh's own station-index lookup (`0x01862af0`), and its
failure value is `-3`. **So a Pokemon that arrives from a station the console's mesh cannot name is
dropped without a byte of complaint**, which is the shape of every run since the selection phase
started working: the console acks our offer at the transport, echoes the record, answers with a
hash, and never advances its trade state.

**AND THE ENVELOPE HAS THE GAME'S OWN NAMES FOR ITS FIELDS.** `scratchpad/swsh_schema.txt`,
`data.proto`, package `gflnet.p2p.sync.pb` - the message this project has been calling the trade
RPC envelope is `Data`, and its five fields are named in the binary:

    1  uint32  syncId        what we called the offset      30 / 40 / 50
    2  uint32  elementId     what we called the base        10000 / 20000
    3  uint64  ownerId       what we called the station id  THE SENDER'S
    4  uint64  clock
    5  bytes   body          four bytes in the pair; a 344-byte PK8 in the console's own 40050

**`ownerId` is the sender, by the game's own naming, and the receive handler above resolves a
sender to a station index or drops.** That the two are the same value is a DEDUCTION and not yet a
measurement - the handler's third argument is a station id, and `Data.ownerId` is the only station
id in the message - but it is the reading that predicts what we see, and it is cheap to act on.

**THE SEND SIDE SAYS THE SAME THING FROM THE OTHER END.** Content 50's own send is `0x010d6000`:
it asks Pia for its own id (`0x01766740`, which returns -1 while the session state is 3 and
`[session+0x158]` otherwise), **gives up entirely if that is -1**, copies the 344-byte PK8 into
`[content+0x88]`, and hands the transport `(body, 0x158, thatId, [content+0x62], [content+0x68])`.
The id travels with the Pokemon by construction; the console stamps its own on every offer.

**AND IT EXPLAINS AN ASYMMETRY THIS PROJECT HAS MEASURED.** Content 30's slot 0, `0x010ce080`,
does not resolve an index at all - it compares the sender against our own id
(`[[0x2616a30]]+0xf0`) and returns if they are equal, which is the echo check. **A sender id that
is merely not-ours passes content 30 and fails content 50.** The offer phase worked; the selection
phase does not; and that is the difference between the two handlers.

So what to build next is a `Data` on 40050 carrying our own `ownerId` and the 344-byte PK8 in
`body`, rather than `PokemonTradeDataHolder{pokemon{...}}` on 10050 with no owner in it at all -
which is what `pokemon_offer` has been sending. It is buildable and provable offline.

**THAT PARAGRAPH IS WRONG AND THE SECTION BELOW IS THE MEASUREMENT THAT RETIRES IT.** The sender
`0x010d5e40` resolves is not a field of the message at all: it is a pointer the transport hands
down. Session 63 walked the dispatch instead of guessing at it.

## The whole path from the radio to content 50's receive event

Session 63, read out of Shield 1.3.2's `main`, no association spent. Every step below is a function
in the image and the argument registers are named where they are set.

    0x006a9a20   the sync pump, called from the trade session update (0x01108ed0, 0x011092f0)
    0x006db3b0   the poll: for every registered entry, take its byte at +8 and drain both streams
    0x006a8490   stream A for that byte: mesh port [pia+0xd0+kind*4] on Pia PROTOCOL 0x7C
    0x006a84f0   stream B for that byte: mesh port [pia+0xd8+kind*4] on Pia PROTOCOL 0x80
    0x006db9c0   drain one stream: slot 0x78 fills (sender*, length) and the buffer at manager+0xf0
    0x006db620   the dispatch: match the entry, then call the holder's vtable slot 8
    0x010d81d0   content 50's 10000-base holder: parse the body, then call the listener's slot 0
    0x010d5e40   the listener: resolve the sender to a station index, memcpy 0x158, invoke it

**THE APPLICATION HEADER IS FOUR BYTES AND THE THIRD ONE IS NOT PADDING.** `0x006db840` builds a
message at `manager+0x240f0`:

    manager+0x240f0   u16   the message id            strh w3
    manager+0x240f2   u8    a discriminator           from manager+0x480f0
    manager+0x240f3   u8    zero                      strb wzr
    manager+0x240f4   ...   the body

and `0x006db620` takes it apart the same way - `ldrh w24,[x2]` is the id, `ldrb w9,[x2,#2]` is the
discriminator, `add x23,x2,#4` is the body and `sub w9,w3,#4` its length. This project has been
sending `<u16 id><u16 0000>` since session 56 and byte 2 has always been zero.

**THE DISPATCH HAS THREE GATES, AND ONLY ONE HOLDER IN THREE IS SUBJECT TO THE THIRD.** A
registration entry is 16 bytes: the holder, then a byte at +8 and a byte at +9. `0x006daeb0(manager,
&holder, flag)` passes `w2 = 0` and `w3 = flag`, and `0x006db358` / `0x006db35c` store them in that
order, so **+8 is always 0 and +9 is the flag** - and the flag is 1 for the 10000+offset holder and
0 for the 20000 and 30000 ones (`0x010d5150`, three calls). The gates:

    id == holder->slot7()          slot 7 is the getter that returns [holder+0x160], the id
    entry[8] == the drain's kind   both 0
    entry[9] ? header[2] == [manager+0x480f0] : no check

**So the 10000-base holder is the only one whose header byte 2 is validated**, and each content's
registrar sets `[manager+0x480f0]` to zero on its way out (`0x010d53a0`: `mov w1,wzr; bl 0x6db470`).
Our zero passes. The check exists; it is not what is stopping us.

**THE SENDER IS A POINTER FROM THE TRANSPORT, NOT A FIELD OF THE MESSAGE.** `0x006db9c0` reads it
out of the stream (`[sp+0x28]`, filled by the stream's own slot 0x78) and passes it as `x2`;
`0x006db620` forwards it as `x3`; `0x010d81d0` forwards it as `x2` to `0x010d5e40`, which hands it
straight to `0x006b5850`. The loopback path shows what kind of thing it is: `0x006db8e8` passes
`[[0x2616a30]]+0xf0`, our own station record - the same address content 30's echo check compares
against. **`Data.ownerId` has nothing to do with the 10050 path**, and sx36, sx37 and sx45's
ownerId variations were varying a field this handler never reads.

**AND THE MESSAGE TYPE IS NOW READ RATHER THAN INFERRED.** `0x010d81d0` constructs a 0x28-byte
protobuf (`0x010d9c90`), calls `ParseFromArray` (`0x0070c180`, the usual Clear / slot 0x58 /
IsInitialized triple) and then passes `[msg+0x18]` to the listener. Its
`MergePartialFromCodedStream` is `0x010d9ee0` and it accepts **tag 0x0a and nothing else**: field 1,
wire type 2, `operator new(0x28)` for the submessage, `[msg+0x24] = 1` for the oneof case and
`[msg+0x18]` for the pointer. The submessage's own default instance is registered by `0x010d8ed0`,
whose descriptor is the string at `0x1bdb460`:

    pokemon_trade.proto   net_contents.trade.common.pokemon_trade.protocol_buffers
      Pokemon
        1  bytes  serializePokemonParam

129 bytes, no NUL, ending in `proto3` - one message, one field. The listener reads
`[Pokemon+0x18]` as a libc++ `std::string` (byte 0 bit 0 selects the heap pointer at +0x10) and
memcpys `0x158` out of it.

**SO `PokemonTradeDataHolder{pokemon{serializePokemonParam: <344-byte PK8>}}` ON 10050 IS EXACTLY
RIGHT, AND IT IS WHAT `pokemon_offer` HAS BEEN BUILDING SINCE SESSION 61.** The shape was never the
problem. sx34 sent the correct message.

**AND TWO OF THE THREE HOLDERS CANNOT DELIVER A POKEMON AT ALL.** `0x010d81d0` opens with
`ldr x8,[x0,#0x168]; cbz x8, out` - no listener, silent return, nothing parsed. Only three stores to
a `+0x168` exist in content 50's code:

    0x010d50ac   content+0x2a8, the 10000-base holder -> the delegate at session+0x2b0,
                 whose slot 0 is 0x010d5e40. Installed by the init that state 1 runs.
    0x010d533c   content+0x2b8, the 30000-base holder -> content+0x68, a different listener
    0x010d5660   the teardown, clearing the first one

**`content+0x2b0` - the 20000-base holder - is registered and never given a listener.** 20050 is
inert by construction, so sx39 was void rather than a negative, and 30050 (sx45) reaches a handler
that is not the Pokemon receive.

**WHAT IS LEFT IS INSIDE `0x010d5e40` AND IT IS TWO SILENT RETURNS.** With the id right, the header
right, the type right and the listener installed, a correct 10050 that changes nothing can only be
dying at `0x006b5850` returning `0xfd` - the mesh cannot name the sending station - or at
`[delegate + 0x30 + index*8]` being null. Content 50's init writes exactly two of those slots,
`+0x30` and `+0x38` (`0x010d5034`, `0x010d5080`, both built by `0x010d7960` off a counter at
`content+0x100`), so **any station index above 1 reads zeroed memory and returns**. That is the next
read.



## What this project has measured, and what it has borrowed

FACT, sw70's own capture (`scratchpad/sw_app_payloads.py` walks it): the console sent **five
distinct application payloads and no others** across the whole run -

    0x7C  id 97     0a00        ping            x20
    0x7C  id 97     1200        pingReply        x2
    0x7C  id 97     1a00        pingSynced       x3
    0x7C  id 60000  0a00        result{}         x2
    0x80  id 60000  12020801    imReady{true}    x2

Those five are ours. **Everything past the trade snapshot is not.** `pokeldn/swsh/trade.py` carries
`SYNC_ANSWERS`, a table of what to answer for the other sync holders, and it is `nxldn-lab`'s
reading of a console-to-console capture, reproduced with its source named. Its ids are real and its
bytes for 97 and 60000 agree with ours exactly, which is the only part of it we can check.

**THE MEASUREMENT THAT MAKES IT OURS COSTS NO EXTRA ASSOCIATION.** `bin/swsh_connect.py
--sync-answers` answers the table where it has a rule and keeps sw68/sw70's proven per-protocol
echo everywhere else, and it PRINTS every distinct payload it has no rule for. The console names
its own ids; the run is what asks it to.

Against sw70 that changes exactly two things: the first thing we say to `ping` becomes `pingReply`
rather than an echo, and `pingSynced` gains a `result{}` behind it. Nothing else about the run
moves, which is what one variable means here.

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
