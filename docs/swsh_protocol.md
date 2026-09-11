---
title: The sync framework
parent: Sword and Shield
nav_order: 2
---

# Messages, contents and routing

Above Pia, Sword and Shield run a publish/subscribe framework. An application message is four bytes
of little-endian id, a discriminator byte, a zero byte, and a protobuf body. This page covers where
an id comes from, how a message reaches a handler, and the party payload the game sends over it.

## Where a message id comes from

Low ids are a registration table: 838 records of 24 bytes at `0x01BBFFA0`,
`{u64 handler slot, u32 0x402, u32 id, u64 0}`, ids 1..880. The slot pointers step by eight through
an array of identical thunks; the table is id -> handler. Ids 97 (the ping holder), 110, 120 and 130
are in it.

High ids are computed, base plus offset. 20030, 40030, 40040 and 40050 appear nowhere in the image
(neither as an aligned word nor as a MOVZ/MOVK/MOVN immediate); 20000, 40000 and 60000 do, with code
adding a register:

    mov w9, #0x4e20          ; 20000
    add w27, w22, w9         ; id = 20000 + w22

    ldrh w8, [x19, #0x372]
    mov w9, #0x4e20
    add w8, w8, w9           ; id = 20000 + a halfword out of the object

60000 is base + 0, a MOVZ at 41 sites. `scratchpad/swsh_msgid.py` reads both families.

The 40000 family is minted one layer further down and encodes 40000 as a MOVN of -0x63c0:

    ldrb w20, [x0, #0x28]          the content offset, 30 / 40 / 50
    mov  w9, #-0x63c0              a MOVN: w9 = 0xffff9c40
    add  w24, w20, w9
    strh w24, [x20, #0x160]        0x9c5e / 0x9c68 / 0x9c72 = 40030 / 40040 / 40050

40030, 40040 and 40050 are ids this image registers. Whether the trade flow over them is the one
`andyjusa/nxldn-lab` records is a separate question.

## Contents and holders

Each content registers a family of three holders. The registrars are `0x010ccd90` for content 30,
`0x010da7d0` for 40 and `0x010d5150` for 50; each reads the content's offset from the halfword at
`[content+0x372]`:

    ldrh w8, [x19, #0x372] ; mov w9, #0x2710 ; add w8, w8, w9    id = 10000 + offset  -> 0x010dd910
    ldrh w8, [x19, #0x372] ; mov w9, #0x4e20 ; add w8, w8, w9    id = 20000 + offset  -> 0x010d85f0
    ldrh w8, [x19, #0x372] ; mov w9, #0x7530 ; add w8, w8, w9    id = 30000 + offset  -> 0x010d0980

each handed to `0x006daeb0(manager, &holder, flag)` with flag 1, 0 and 0 in that order.

Only a holder with a listener installed delivers anything. `0x010d81d0` (content 50's 10000-base
parse) opens `ldr x8,[x0,#0x168]; cbz x8, out`: no listener, silent return. Installs and teardowns
in the 30/40/50 band:

    content 30   0x010ccc94  0x010ccca4  0x010ccf7c        installs
    content 40   0x010da6d0  0x010da9bc                    installs, and 0x010dab10 clears
    content 50   0x010d50ac  0x010d533c                    installs, and 0x010d5660 clears

Nothing writes the 20000-base holder's `+0x168` in content 40 or 50, so 20040 and 20050 are inert.
A message addressed at either is dropped.

### The three trade contents

One function, `0x010c9280`, constructs all three and stores them in the trade session object:

    +0x120   content 30, the box exchange       ctor 0x010cca10, registers offset 30 at 0x010ce4f0
    +0x148   content 40, SyncSaveDataHolder     ctor 0x010da3f0
    +0x2b0   content 50, PokemonTradeDataHolder ctor 0x010d4d40
    +0x60    an event source, listeners in a vector at its own +0x60
    +0x68    our Pokemon        +0x70  theirs
    +0x140   the trade state, 1..10            +0x144  the error code
    +0x418   send-command-3-on-the-first-frame  +0x419  the role bit that suppresses it

It also writes four function pointers into `+0x90..+0xa8` and the session pointer into `+0xb0`: a
delegate whose invoke thunk is `0x010cc250`, tail-calling `0x010ca800`, the session's box callback,
as `(session, code, payload)`.

A content's holders are registered by its init, which runs from a trade state; the constructors set
two vtables, keep their arguments and zero their fields:

    state 1   content 50 starts: 10050, 20050, 30050 registered, 40050 minted   init 0x010d4d90
    state 6   content 40 starts: 10040, 20040, 30040 registered, 40040 minted   init 0x010da470

No 40040 exists until the trade has passed states 1 to 4. State 6 is downstream of the Pokemon
exchange (state 3) and of the state-4 decision at `0x01109320`.

## The routing path

From the radio to a content's receive event:

    0x006a9a20   the sync pump, called from the trade session update
    0x006db3b0   the poll: for every registered entry, take its byte at +8 and drain both streams
    0x006a8490   stream A for that byte: mesh port [pia+0xd0+kind*4] on Pia PROTOCOL 0x7C
    0x006a84f0   stream B for that byte: mesh port [pia+0xd8+kind*4] on Pia PROTOCOL 0x80
    0x006db9c0   drain one stream: slot 0x78 fills (sender*, length) and the buffer at manager+0xf0
    0x006db620   the dispatch: match the entry, then call the holder's vtable slot 8
    0x010d81d0   content 50's 10000-base holder: parse the body, then call the listener's slot 0
    0x010d5e40   the listener: resolve the sender to a station index, memcpy 0x158, invoke it

### The application header

A payload is `struct.pack("<HBB", id, discriminator, 0)` then the body: id 97 with the body `0a00`
assembles to `61 00 00 00 0a 00`, the ping the console repeats. `0x006db840` builds a message at
`manager+0x240f0`:

    manager+0x240f0   u16   the message id            strh w3
    manager+0x240f2   u8    a discriminator           from manager+0x480f0
    manager+0x240f3   u8    zero                      strb wzr
    manager+0x240f4   ...   the body

and `0x006db620` takes it apart the same way. The discriminator is a generation counter,
`[content+0x370] = ([content+0x370] + 1) mod 255` (`0x008b6670`), pushed into `[manager+0x480f0]`.
Every content's registrar sets it to zero on its way out (`0x010d53a0`). All 107 application
payloads in one whole run carried zero there, on every id.

### Reading the registrations live

The poll walks the manager's entry array, so the ids a running scene accepts can be listed from
memory without sending anything:

    manager = read_u64(read_u64(main + 0x02616750))     0x006a9a70, the poll's caller
    count   = read_u64(manager + 0xD8)                  0x006db3dc
    array   = read_u64(manager + 0xD0)                  0x006db3e0
    entry i = array + i * 0x10                          the shift at 0x006db3e4
    id      = read_u16(holder + 0x160)

### The three dispatch gates

A registration entry is 16 bytes: the holder, then a byte at +8 and a byte at +9.
`0x006daeb0(manager, &holder, flag)` passes `w2 = 0` and `w3 = flag`, so +8 is always 0 and +9 is
the flag: 1 for the 10000+offset holder and 0 for the others. The gates:

    id == holder->slot7()          slot 7 returns [holder+0x160], the id
    entry[8] == the drain's kind   both 0
    entry[9] ? header[2] == [manager+0x480f0] : no check

The 10000-base holder is the only one whose discriminator byte is validated.

### Kind is the Pia port

The 40000-family holder registers with `0x006daf40(manager, &holder, 1, 0)` (`w2 = 1`); every
content holder registers with `w2 = 0`. `w2` is `entry[8]`, the drain's kind, and `0x006a8490` /
`0x006a84f0` turn a kind into a mesh port. Port 0 carries the content holders (20030, 10050, the
pings); port 1 carries the framework's 40000-family envelopes.

### The sender is a transport pointer

`0x006db9c0` reads the sender out of the stream (`[sp+0x28]`, filled by the stream's own slot 0x78)
and passes it as `x2`; `0x006db620` forwards it as `x3`; `0x010d81d0` forwards it as `x2` to
`0x010d5e40`, which hands it to `0x006b5850`, Pia's `mesh->GetStationIndex`, `-3` (0xfd) on
failure. The loopback path passes `[[0x2616a30]]+0xf0`, the station's own record.

`Data.ownerId` is not on the 10050 path; varying it changes nothing there.

## The `Data` envelope

`scratchpad/swsh_schema.txt`, `data.proto`, package `gflnet.p2p.sync.pb`:

    1  uint32  syncId        the content offset       30 / 40 / 50
    2  uint32  elementId     the base                 10000 / 20000
    3  uint64  ownerId       the sender
    4  uint64  clock
    5  bytes   body          four bytes in a pair; a 344-byte PK8 in a 40050

The 40000 holder's listener is `element+0x18` and its slot 0 is `0x006d59f0`, eleven instructions of
routing:

    [Data+0x14] == [listener+0x10]        field 1, syncId, against the element's own offset
    walk [listener+0x28] .. [+0x30]       the element's sub-elements, 0x90 bytes each
      [Data+0x18] == [sub+0x62]           field 2, elementId, against the sub-element's u16 id
      [Data+0x20] == [sub+0x68]           field 3, ownerId,   against the sub-element's u64 owner
    sub->vtable at 0x48, called with (sub, body, len, [Data+0x28])   the body and the CLOCK
    otherwise: ret

A `Data` whose (elementId, ownerId) matches no registered sub-element is dropped silently.

### Sub-element kinds

Slot 9 of each kind's vtable is its receive handler; all three are the same five instructions with one
constant changed:

    0x006d5f20   cmp x2,#4    ldr  w8,[x1]   str  w8,[sub+0x88]      a 32-bit value
    0x006d6490   cmp x2,#4    ldr  w8,[x1]   str  w8,[sub+0x88]      the phase pair
    0x006d69f0   cmp x2,#2    ldrh w8,[x1]   strh w8,[sub+0x88]      a 16-bit value

each followed by `[sub+0x78] = clock` and `strh 0x0100 -> [sub+0x60]`, which sets the ready byte at
`sub+0x61`. Slot 7, the value the framework hashes, is `ldr x0,[x0,#0x78]; ret`: the clock.

A sub-element is born with `0xfc18fc18` at `+0x88` (`0x006d6160`) and records its size as 0x90, the
router's stride.

### The quorum hash

The four bytes the framework sends on elementId 10000 are a checksum over the channel's sub-elements,
built by `0x006d7b40` at `element+0xa8`:

    h = 0
    for sub in subs:
        if (!sub[+0x61]) { h = 0; break }        any station not ready -> the hash is ZERO
        h = crc32(le32(h + sub->slot7()))        slot 7 is the clock

The hash is zero until every station's sub-element has taken a body; a non-zero hash is the console
reporting that the peer's sub-element went ready. `0x0065de30` is a standard `zlib.crc32` (table
generated from the non-reflected polynomial `0x04C11DB7` with index and value bit-reversed, the
ordinary `0xEDB88320` table; init `0xFFFFFFFF`, `mvn` at the end). The CRC-16 generator two
functions along (`0x0065df04`, poly `0x8005`) belongs to a different table.

## The party payload on protocol 0x84

Protocol 0x84 is `nn::pia::transport::ReliableBroadcastProtocol`. It carries the trade snapshot:
3456 bytes in three fragments, repeated until acknowledged.

The third fragment is compressed (Pia message flag 0x10, version 4's zlib flag). Concatenated raw
the three fragments give 1404 + 1404 + 157 = 2965; inflated, the third is 648 bytes and the total is
3456. `pokeldn/swsh/trade_payload.py` refuses any reassembly that is not 3456 bytes.

The layout, verified field for field against pokeldn's own capture and matching
`kwsch/PokePiaSWSH` and `lincoln-lm/swsh-lan-client`:

    0x000  six PK8 records, party form, 0x158 each          -> 0x810
    0x810  u32   party count
    0x814  MyStatus, 272 bytes      TID/SID at 0xA0, trainer name at 0xB0
    0x924  TrainerCard, 456 bytes   trainer name at 0x00, start date at 0x170
    0xAEC  660 bytes not named by any published client       -> 0xD80 = 3456

MyStatus and TrainerCard are PKHeX save blocks (`Saves/Substructures/Gen8/SWSH/`). The date at
`0x924 + 0x170` is the date the save was started.

The party is the first 0x810: six PK8 records at a 0x158 stride. Empty slots are zero-filled; an
empty slot is an encryption constant of zero. The count at 0x810 agrees.

`pokeldn/swsh/trade_payload.rewrite` moves the identity in MyStatus, the trainer card and every party
record at once (57 bytes of 3456), and the trade screen names that trainer as the partner.
`scratchpad/sw84_read.py <payload.bin>` is the viewer.

## The PK8

The Gen-8 entity format is shared with BDSP and lives in `pokeldn/gen8.py`; in PKHeX, `PK8` and `PB8`
are both `G8PKM` and neither overrides a shared offset. `pokeldn/swsh/pokemon.py` is the Sword view
and sends the party form, 0x158; a BDSP trade sends the 0x148 stored form.

    0x00  u32  encryption constant, in the clear. Seeds the cipher and the block order
    0x06  u16  checksum, in the clear, over the decrypted body ONLY
    0x08       four 80-byte blocks, LCG-encrypted and permuted by (EC >> 13) & 31
    0x148      the party stats, LCG-encrypted with the stream RESTARTED, and never permuted

Two properties of that format cause silent misreads:

- The party stats restart the LCG. `PokeCrypto.Decrypt8` calls `CryptArray` twice, both seeded from
  the encryption constant. A tail decrypted with the continued stream produces plausible garbage such
  as a level of 110.
- `BLOCK_ORDER[sv]` is applied, not inverted: it names the block that becomes block *i*. Sixteen of
  the 32 `sv` values (ten of the 24 distinct orderings) are their own inverse, so a wrong direction
  reads perfectly for those and garbles the rest. The checksum is a sum of 16-bit words and does not
  change under block permutation. The table is 32 entries long; PKHeX's `PokeCrypto.BlockPosition`
  writes entries 24-31 as duplicates of 0-7.

Independent checks that a party has decoded correctly: the nicknames decode
as species names in the console's own language; the species numbers match those names; the levels
come out of the party-stat tail, which is outside the four shuffled blocks; the experience agrees
with each level on its own growth curve; the hyper-training byte at 0x126 agrees bit for bit with the
IV word at 0x8C; and MyStatus's trainer ids match the ids inside every PK8, from a different block of
the payload.

`pokeldn/swsh/pokemon.py` `build_from` edits a record the console sent and re-encrypts it; every
byte outside the named fields stays a byte from a real save.

## The trade message

`pokemon_trade.proto`, package `net_contents.trade.common.pokemon_trade.protocol_buffers`:

    Pokemon                  { 1 bytes   serializePokemonParam }
    PokemonTradeDataHolder   { 1 Pokemon pokemon }

129 bytes of descriptor, one message, one field. Content 50's holder parse `0x010d81d0` constructs a
0x28-byte protobuf (`0x010d9c90`), calls `ParseFromArray` (`0x0070c180`) and passes `[msg+0x18]` to
the listener; its `MergePartialFromCodedStream` (`0x010d9ee0`) accepts tag 0x0a and nothing else.
The listener reads `[Pokemon+0x18]` as a libc++ `std::string` (byte 0 bit 0 selects the heap pointer
at +0x10) and memcpys 0x158 out of it.

A Pokemon offer is `PokemonTradeDataHolder{pokemon{serializePokemonParam: <344-byte PK8>}}` on
10050. `pokeldn/swsh/trade.py` `pokemon_offer` builds it.

### The receive handler's two silent drops

`0x010d5e40`:

    w0 = 0x006b5850(senderPointer)      Pia: mesh->GetStationIndex; -3 (0xfd) on failure
    if (w0 == 0xfd) { [content+0x1a4] = 1; return; }          nothing parsed, nothing answered
    memcpy(stack, body, 0x158)                                0x158 = 344 = the party-form PK8
    subscriber = [content + 0x30 + index*8]                   one slot per station index
    if (subscriber == null || its refcount is 0) return       also silent
    ... invoke it, then call content 50's own send 0x010d6000 on it

Content 50's init writes exactly two subscriber slots, `+0x30` and `+0x38`; any station index above
1 reads zeroed memory and returns. Content 40's handler `0x010dbc90` has the identical gate at
`+0x38`/`+0x40`.

Diagnostic: receiving a Pokemon on the 10000-base holder makes the console put its own on the same
holder immediately. A run in which the console never sends a 10050 is a run in which the offer never
reached `0x010d5e40`.

Content 30's equivalent slot (`0x010ce080`) does not resolve a station index; it compares the sender
against the station's own id (`[[0x2616a30]]+0xf0`) and returns if they are equal. A sender id that
is merely not-ours passes content 30 and fails content 50: an offer with no owner reaches the player
in the box phase and is swallowed in the selection phase.

### Content 40's message

`sync_save_data_holder.proto` and `sync_command.proto`, both in
`net_contents.trade.common.sync_save.protocol_buffers`:

    SyncSaveDataHolder { 1 SyncCommand syncCommand }
    SyncCommand        { 1 int32       data       }

Content 40's holder parse `0x010ddb20` is `0x010d81d0` instruction for instruction. Its
`MergePartialFromCodedStream` `0x010df6d0` accepts tag 0x0a and nothing else, over a submessage
parser `0x010debc0` that accepts tag 0x08 and nothing else: one length-delimited field carrying one
varint. `swsh_trade.sync_command` builds it.
