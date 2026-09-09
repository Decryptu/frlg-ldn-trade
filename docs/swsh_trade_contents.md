---
title: The content framework
parent: The trade
grand_parent: Sword and Shield
nav_order: 2
---

# Contents, holders, and how a message reaches a handler

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

## The 40000 family is routed on (elementId, ownerId), and kind is the port

Still session 63, and it finishes the layer above. `0x006d44e0` builds the 40030/40040/40050 holder
the same way the content holders are built - id at `+0x160`, listener at `+0x168` - but it registers
it with `0x006daf40(manager, &holder, 1, 0)`, **`w2 = 1`**, where every content holder registers with
`w2 = 0`. `w2` is `entry[8]`, the drain's kind, and `0x006a8490` / `0x006a84f0` turn a kind into a
mesh port: `[pia+0xd0+kind*4]` on Pia 0x7C and `[pia+0xd8+kind*4]` on 0x80.

**So "port 0" and "port 1" are kind 0 and kind 1, and they are not two windows of one thing: port 0
carries the CONTENT holders (20030, 10050, the pings) and port 1 carries the framework's own
40000-family envelopes.** That is exactly what every capture shows, and it is now read rather than
observed.

**AND THE ENVELOPE IS ROUTED ON A PAIR OF KEYS.** The 40000 holder's listener is `element+0x18` and
its slot 0 is `0x006d59f0`, which is eleven instructions of routing:

    [Data+0x14] == [listener+0x10]        field 1, syncId, against the element's own offset 30/40/50
    walk [listener+0x28] .. [+0x30]       the element's sub-elements, 0x90 bytes each
      [Data+0x18] == [sub+0x62]           field 2, elementId, against the sub-element's u16 id
      [Data+0x20] == [sub+0x68]           field 3, ownerId,   against the sub-element's u64 owner
    sub->vtable at 0x48, called with (sub, body, len, [Data+0x28])   field 5 and field 4:
                                          the body and the CLOCK
    otherwise: ret                        NOTHING, silently

**A `Data` whose (elementId, ownerId) is not a registered sub-element is dropped without a byte of
complaint**, and the sub-element that does own the pair is handed the body **and the clock**.
Content 50's own send confirms the layout from the other end: `0x010d6000` passes
`[x+0x62]` and `[x+0x68]` to the transport alongside the Pokemon, so a sub-element sends with the
same id and owner it is addressed by.

## What nxldn-lab does in the selection phase and this project does not

`scratchpad/nxldn-lab` is replay-with-substitution off a console-to-console capture, so it is a map
rather than a derivation - but the map records two moves that have no counterpart here, and both are
about the clock and the pair the section above says the console routes on.

**IT OPENS THE SELECTION PHASE ITSELF.** On `820000001a00` - id 130, `pingSynced` - its client sends
two 40050 `Data`s on port 1, elementId 10000 and 20000, its own `ownerId`, and the console's own two
four-byte bodies. Our own captures carry that payload every run: `sx45r1_6` has it at t=31.30,
**0.3 s before the console's own 40050 burst at t=31.60**, and this project has only ever echoed it.

**AND IT ANSWERS THE PAIR TWICE, THE SECOND TIME AT CLOCK + 2.** The console's selection burst is
the same three messages sent three times with the clock advanced by 2 each time - `sx45r1_6`:
`0x1cb4`, `0x1cb6`, `0x1cb8`. Every answer this project has sent carries ONE clock and is then
retransmitted unchanged until it is acked, so our state has never moved while the console's did.

`bin/swsh_connect.py --selection-start` and `--rpc-pair-advance 2` are those two moves, each behind
its own flag so a run changes one of them.

**AND ONE HYPOTHESIS DIED CHEAPLY.** nxldn-lab sends every application message on Pia **0x7C**, and
`--send-protocol`'s default is 0x80 - but `scratchpad/launcher_logs/sx45r1_6_launcher.log` shows
every run since session 61 passes `--send-protocol 0x7c` already. The offer's protocol is not the
difference, and no run needs to be spent finding that out.

**WHAT IS LEFT IS INSIDE `0x010d5e40` AND IT IS TWO SILENT RETURNS.** With the id right, the header
right, the type right and the listener installed, a correct 10050 that changes nothing can only be
dying at `0x006b5850` returning `0xfd` - the mesh cannot name the sending station - or at
`[delegate + 0x30 + index*8]` being null. Content 50's init writes exactly two of those slots,
`+0x30` and `+0x38` (`0x010d5034`, `0x010d5080`, both built by `0x010d7960` off a counter at
`content+0x100`), so **any station index above 1 reads zeroed memory and returns**. That is the next
read.

## The console must answer a Pokemon with a Pokemon, and it never has

Session 63, sx46 / sx47 / sx48b, three runs and three clean negatives - and one of them settles
where the message is lost.

**THE HANDLER SENDS BACK.** `0x010d5e40` does not merely record what arrives. Having resolved the
sender and copied the 0x158 bytes out, it calls `0x010d6000` - **content 50's own send** - on the
subscriber it just found, and then `0x006a24a0(content+0x2a0, sender, 1)`. Receiving a Pokemon on
the 10000-base holder makes the console put its own on the same holder immediately.

**IT NEVER DOES.** Every application id the console sends across a whole run, counted out of
`sx48b_1_pia.jsonl`: 97, 110, 130, 20030, 40030, 40050, 60000. **No 10050, ever, in any run.** So
our offer is not being answered-and-ignored: it is not reaching `0x010d5e40` at all. That is a
measurement, not a reading.

**AND THREE MORE THINGS ARE DEAD.**

- **The clock.** `--rpc-pair-advance 2` (sx46) sent the 40050 pair and then the pair again one state
  later, the way the console's own burst advances. Acked, inert.
- **Opening the phase ourselves.** `--selection-start` (sx47) put our own 40050 pair on port 1 the
  moment the console said id 130 `pingSynced`, ahead of its burst, the way `nxldn-lab` does. Acked,
  inert.
- **The record.** `--offer-echo` (sx48b) handed back the console's own Pomdrapi, byte for byte, out
  of its own save. Acked, inert. **So it is not our PK8** - not the encryption, not the checksum,
  not legality, not the slot.

**AND THE DISCRIMINATOR IS RULED OUT BY MEASUREMENT TOO.** `0x008b6670` shows what the header's
third byte is: a generation counter, `[content+0x370] = ([content+0x370] + 1) mod 255`, pushed into
`[manager+0x480f0]` and stamped into every outgoing message by `0x006db840`. If it ever advanced,
our fixed zero would fail the one gate that applies to the 10000-base holder and nothing else. It
does not advance: **every one of the 107 application payloads the console sent in sx48b carries zero
in byte 2**, on every id. Our zero is the right value.

So the id matches, the kind matches, the discriminator matches, the listener is installed by content
50's init, our station index is 1 and init writes that subscriber slot - and the message still does
not arrive. What is left is to stop deducing and probe it: **a bare `ping` on 10050**
(`422700000a00`, `--open-content 50`) parses as an empty holder, takes `0x010d81d0`'s
default-instance branch, and still reaches the listener - so if the holder is being fed at all, the
console must answer it with a 10050 of its own. Against the same probe on 20030, which we know is
delivered because the box exchange works, that separates "the 10000-base holder is not being fed"
from "nothing of ours reaches the sync manager".
