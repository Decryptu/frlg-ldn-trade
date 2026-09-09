---
title: The confirmation ladder
parent: The trade
grand_parent: Sword and Shield
nav_order: 3
---

# The last phase, rung by rung, and the trade that completed

## The confirmation content takes a command, not a Pokemon

Session 64, read out of Shield 1.3.2's `main`, no association spent. The walk is content 50's, run
again one content along - and it is the same seven steps, so only the last two are new here.

**CONTENT 40 IS BUILT EXACTLY LIKE CONTENT 50, AND THE REGISTRAR SAYS SO.** `0x010da7d0` registers
its three holders off `[content+0x372]` in the same order and with the same flags as `0x010d5150`:
10040 through the builder `0x010dd910` into `content+0x2a8` with flag 1, 20040 through `0x010d85f0`
into `content+0x2b0` with flag 0, 30040 through `0x010d0980` into `content+0x2b8` with flag 0. The
builders differ per content, which is what makes the holders different types - content 50's
10000-base builder is `0x010d7fc0` and content 30's is `0x010d0310`.

**AND THE SAME TWO HOLDERS ARE LIVE, THE SAME ONE DEAD.** Every `str Xt,[Xn,#0x168]` between
`0x010c0000` and `0x010e0000` is an install or a teardown, and the three contents line up one for
one:

    content 30   0x010ccc94  0x010ccca4  0x010ccf7c        installs
    content 40   0x010da6d0  0x010da9bc                    installs, and 0x010dab10 clears
    content 50   0x010d50ac  0x010d533c                    installs, and 0x010d5660 clears

`0x010da6d0` is inside content 40's init `0x010da470` and writes the DELEGATE - the object the init
belongs to - into the 10040 holder; `0x010da9bc` is in the registrar and writes `content+0x68` into
the 30040 holder. **Nothing ever writes the 20040 holder's `+0x168`, so 20040 is inert by
construction**, exactly as 20050 is. A run addressed at it would be void rather than negative.

**THE HOLDER'S VTABLE SLOT 8 IS THE PARSE, AND THE TWO CONTENTS ARE STRUCTURALLY IDENTICAL.**
`0x010dd910` finishes by storing `[0x2625b00] + 0x10` at the object and the id at `+0x160`, so the
10040 holder's vtable is `0x2580148`; slot 8 is `0x010ddb20`. The same arithmetic on content 50's
group `0x257fc30` gives `0x010d81d0`, which is what session 63 measured - the method checks itself
before it is used on the new content.

**AND `0x010ddb20` IS `0x010d81d0` INSTRUCTION FOR INSTRUCTION** down to the register allocation:
`ldr x8,[x0,#0x168]; cbz` out, construct a 0x28-byte protobuf (`0x010df480`), `ParseFromArray`
(`0x0070c180`), read the oneof case at `[msg+0x24]`, and call the listener's slot 0 with the
submessage and the transport's sender pointer.

**THE MESSAGE IS NOT A POKEMON.** Content 40's `MergePartialFromCodedStream` is `0x010df6d0` and it
accepts **tag 0x0a and nothing else**, `operator new(0x20)` for the submessage; the submessage's own
parser `0x010debc0` accepts **tag 0x08 and nothing else** and stores the varint at `+0x14`. One
length-delimited field over one varint. The game's own descriptors say the same thing from the other
side, both in `net_contents.trade.common.sync_save.protocol_buffers`:

    sync_save_data_holder.proto   SyncSaveDataHolder { 1 SyncCommand syncCommand }
    sync_command.proto            SyncCommand        { 1 int32       data       }

So the message content 40's receive event can be fed is
`SyncSaveDataHolder{syncCommand{data:<int32>}}` on **10040**, and `swsh_trade.sync_command` builds
it. It is the same `holder{command{data}}` shape as content 30's `BoxSyncStateDataHolder`, which is
the shape that reached the player in the offer phase.

**THE HANDLER HAS CONTENT 50's GATE, AND THE SAME TWO-SLOT LIMIT.** The delegate's vtable is
`[0x2625a68]+0x10` and its slot 0 is `0x010dbc90`:

    w0 = 0x006b5850(senderPointer)     Pia: the mesh's station index; -3 (0xfd) on failure
    if (w0 == 0xfd) { [delegate+0x64] = 1; return; }        nothing parsed, nothing answered
    w8 = [SyncCommand + 0x14]                               the int32, and that is all it keeps
    subscriber = [delegate + 0x38 + index*8]
    if (subscriber == null || its refcount is 0) return     also silent

Content 50 memcpys 0x158 bytes at the same point and reads its subscriber from `+0x30 + index*8`.
Content 40's init writes `+0x38` and `+0x40` and no others, so **any station index above 1 reads
zeroed memory and returns**, which is the identical limit session 63 found on content 50.

**AND THE FOUR COMMANDS ARE THE CONSOLE'S OWN.** `0x010db840(delegate, data, flag)` builds the
SyncCommand, stores `data` at `+0x14` and hands it to `0x010dbab0`; its only caller is content 40's
state machine `0x010dae70`, which dispatches on `[delegate+0x5c]` through a 14-entry jump table at
`0x2067ed0`. Five send sites, four values:

    state 1   -> send(0)  -> state 2       0x010db308
    state 3   -> send(1)  -> state 4       0x010db0b0
    state 6   -> send(2)  -> state 7       0x010db0dc
    state 8   -> send(2)  -> state 9       0x010db104, behind a countdown at [delegate+0x60]
    state 12  -> send(3)  -> state 0       0x010db16c, and the machine is done

The `flag` argument is always `data + 1` and never reaches the message. States 2, 4, 7 and 9 are the
table's do-nothing entries, so **each send parks the machine and something else has to move it on** -
which is what makes 0, 1, 2, 3 a handshake rather than a burst.

**THE SUB-ELEMENT SEND IS THE FOUR-BYTE 40040 BODY.** `0x010dbe20` asks Pia for its own id
(`0x01766740`), gives up if it is -1, copies the int32 to `[x+0x88]` and hands the transport
`(body, 4, thatId, [x+0x62], [x+0x68])` - the same shape as content 50's `0x010d6000` with 4 bytes
where the Pokemon goes. That is the layer the 40040 pair rides on.

### What sx51b did with the cue, and what it did not

sx51b's last unanswered message is a 40040/20000 member whose four-byte body ends `0100` - the same
shape that, on 40050, was the cue to send our Pokemon. Its own log says what happened to it: line
367 fired the selection cue and spent `offer_status_answered`, which is one latch for the whole run,
and line 443 then answered the 40040 body through the generic `--rpc-bodies` branch. **So the status
was answered on port 1 and nothing was ever sent on port 0.** The selection phase needed both.

`bin/swsh_connect.py --confirm-command N` is that missing half: on the confirmation envelope's cue
it sends `SyncSaveDataHolder{syncCommand{data:N}}` on 10040 reliable port 0 and answers the status
on port 1, with its own latch so the two cues cannot swallow each other.

## The confirmation content answers, and it climbs

Session 64, sx52e and sx53, on a retail Sword. **This is the first time anything of ours has
reached content 40's receive event**, and the two runs separate cleanly.

**sx52e, `--confirm-command 0`.** The console ran the ladder and then stopped:

    elementId 10000 + 20000   00000000 / 000018fc   the pair, answered
    elementId None            00000000
    elementId 20000           00000100             THE CUE -> we send syncCommand{data:0} on 10040
    elementId 1               00000000             the echo
    elementId 10000           8324462b             a hash
                                                   ... and then 124 s of silence

**THE ECHO AND THE HASH ARE THE SIGNATURE THAT THE RECORD LANDED.** On content 50 those two only
ever appeared once our PK8 genuinely reached the receive event - never for a shape that was merely
acknowledged at the transport. Their appearance here says the syncCommand passed `0x006b5850`'s
station-index gate and `0x010dbc90` ran. Six shapes were tried on content 50 before one did this.

**sx53, one variable added: `--confirm-final-delta 9`.** The move `--selection-final-delta` makes on
40050 - re-arm the pair after the hash and send both members again at a larger clock - and content
40 kept going instead of stalling:

    8324462b   hash        01000100   step      7a0ea399   hash
    944c70ea   hash        01000200   step

Five re-arms, and the console's own elementId-20000 body walked `00000100` -> `01000100` ->
`01000200`. Read as `<u16 a><u16 b>` little-endian that is (0,1) -> (1,1) -> (1,2): two counters,
one of which advances per step. **The phase is not a single exchange, it is a ladder**, and it moves
only while the pair is re-armed under it.

**WHERE IT STOPS, AND WHAT IS NOT MEASURED.** sx53 ended at `01000200` with one command sent all
run. Content 40's own machine sends 0, 1, 2 and 3 and parks after each (`0x010dae70`), so the
reading that fits is that each step wants the NEXT command - but **nothing has measured that**, and
"the console climbed two steps after one command" is equally consistent with it climbing on its own
and stopping somewhere else. `--confirm-commands 0,1,2,3` sends the sequence and **has never been on
the air**: the console entered a trade penalty before the run went out.

**AND THE TRIGGER HAD TO CHANGE WITH THE MEASUREMENT.** `--confirm-command` fires on a body ending
`0100`, which is the cue and the first step and NOT `01000200`, the step sx53 finished on. Any
four-byte body on the confirmation content's elementId 20000 is a step, and that is what
`--confirm-commands` keys on.

## The ladder is a barrier, and every rung needs a command

Session 65, read out of Shield 1.3.2's `main`, no association spent. sx53 left one question: whether
each step of the confirmation ladder wants the NEXT command, or whether the console was climbing on
its own. The state field answers it, because it has only three writers.

**THE MACHINE'S STATE IS `delegate+0x5c`, AND EVERY WRITE TO IT IN THE MODULE IS ONE OF THREE
THINGS.** `scratchpad/swsh_offset_writes.py 0x5c 4 0x010c0000 0x010e0000` - every `str Wt,[Xn,#0x5c]`
in content 30, 40 and 50's band:

    0x010da724   in the init 0x010da470       state = 0
    0x010daed8   in the machine 0x010dae70    the machine's own transitions
    0x010daf0c   in the machine
    0x010db180   in the machine
    0x010db388   in the machine, the shared tail every case branches to
    0x010dbfb0   in 0x010dbf40               THE ONE THAT IS NOT THE MACHINE

(`arm64_xref.function_start` attributes the last one to `0x010dbe20`, because it walks back through
the `udf` padding at `0x010dbf38`; the prologue at `0x010dbf40` is where the function starts.)

**AND THE PARKED STATES REALLY ARE PARKED.** The dispatch is `state - 1` into a 14-entry table at
`0x2067ed0`, and states 2, 4, 7 and 9 - the four the sends leave the machine in - all take the
table's shared default `0x010db38c`, which is the function's epilogue. They do nothing and they
change nothing. **So the machine leaves an idle state only when `0x010dbf40` is called.**

**`0x010dbf40` IS A PHASE-TO-STATE MAP, AND ITS FIVE ENTRIES ARE THE LADDER.** It takes a u16, drops
out with the state untouched if it is above 4, and otherwise indexes a 5-entry table at `0x2067f4c`:

    phase 0  -> state 1             -> send(0), announcing phase 1     0x010db308
    phase 1  -> state 3             -> send(1), announcing phase 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8   -> send(2), announcing phase 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing phase 4    0x010db16c
    phase 4  -> state 13 -> 14      -> `0x010db970` tears the holders down and writes the
                                       sentinel `0xfc18` to `content+0x84`. Nothing more is sent.

The two ways of reaching a send of 2 are the two roles: `[delegate+0x58]`, set in the init from
`0x110e620(...) & 1`, picks state 7 (send at once) or state 9 (send after a countdown
`[delegate+0x60]`, seeded in the init from an xorshift to a random 2..302).

**IT IS SLOT 0 OF THE DELEGATE'S SECOND INTERFACE, NOT SOMETHING THE MACHINE CAN CALL.** The vtable
group at `0x257fe90` is a multiple-inheritance group: a primary vtable at `0x257fea0` whose slot 0 is
the SyncCommand receive handler `0x010dbc90` and whose slot 3 is `0x010dbf40`, then an offset-to-top
of **-8** at `0x257fec8` and a secondary vtable at `0x257fed8` whose slot 0 is `0x010dbfd0` - the
same code again against `+0x50`/`+0x54` instead of `+0x58`/`+0x5c`, which is the thunk for a `this`
adjusted by 8. The init installs both halves:

    0x010da6bc   add x9, x19, #8       ->  [content+0x2c0] = delegate + 8     the second interface
    0x010da6d0   str x19, [x8, #0x168] ->  the 10040 holder's listener        the first

**AND THE ONLY CALLER OF THAT SLOT IS CONTENT 40's PUMP.** `0x010db3e0` - the function content 40's
per-frame tick calls before it runs the machine, a 17-state machine of its own on `[content+0x80]` -
reads `[content+0x2c0]` at eight sites, and the ones that matter are its shared tail:

    w1 = [content+0x17c]                    the content's PHASE
    if (w1 == [content+0x84]) skip          already committed to it
    else if (w1 == [content+0x86]) { 0x010de310(content, w1); B->slot7(w1); }
    w1 = [content+0x17c]
    if (w1 == [content+0x84]) done
    else if (w1 == [content+0x86]) { 0x010de310(content, w1); B->slot0(w1); }   <- the state setter

`0x010de310(content, phase)` writes `[content+0x84] = phase` and drops the content's pending body,
so `+0x84` is the phase the content has COMMITTED to. `+0x86` is written in exactly one place in the
band - `0x010dbab0`, the send that `0x010db840` hands the built SyncCommand to - and the value it
writes is the `flag` argument, which is `data + 1` at all five send sites (`0x010db308` is
`w1 = wzr, w2 = #1`, and the other four follow). **So `+0x86` is the phase the console ANNOUNCED
when it sent its last command, and the ladder climbs when the content's phase reaches it.**

**WHICH MAKES THE CONFIRMATION PHASE A BARRIER, ONE RUNG PER COMMAND.** The console sends command
N, records N+1 as the phase it is waiting for, and parks. When the phase reaches N+1 the pump
commits the content to it and hands N+1 to the state setter, which puts the machine in the state
that sends N+1. Command 3 announces phase 4, and phase 4's rung is the teardown.

**AND THE RECEIVE SIDE FEEDS THE BARRIER RATHER THAN THE MACHINE.** `0x010dbc90` never touches
`+0x5c`. It resolves the sender to a station index, keeps the int32, hands it to `0x010dbe20` to go
back out as a four-byte body, and then calls `0x006a24a0([content+0x2a0], &sender, 1)` - which looks
the sender up in a map at `+0x1c0` and sets that station's byte to 1. A per-station flag, set when
our command lands. `0x010de310` calls `0x006a2760` on the same object when it commits.

**AND `content+0x17c` IS NOT A FIELD OF THE CONTENT AT ALL - IT IS THE ELEMENT'S.** Nothing in
`0x010c0000`-`0x010e0000` stores to `+0x17c` at any width, which is what sent this walk one layer
down. The registrar builds the 40040 element at **`content+0xd0`** (`0x010daa4c add x21, x19, #0xd0`,
then `0x006d4ff0` to add the sub-element and `0x006d44e0(element, w20)` to mint it), and
`0x006d44e0` opens with `str wzr,[x0,#0xa8]; strh w1,[x0,#0xac]`. **`0xd0 + 0xac` is `0x17c`**: the
phase is `element+0xac`, and it starts at the registrar's own `w1`, which content 40's init passes as
`wzr` - zero. `+0x84` is set to the same value in the same breath, which is why the pump's first
comparison is equal and quiet.

**THE ELEMENT ADVANCES IT IN ONE PLACE, AND ONLY WITH THE MESH'S PERMISSION.** In the element's
update, at `0x006d4ca0`:

    w0  = 0x006d3260([element+0xf0])        read the shared value; 0xfc18 when there is none
    if (w0 == [element+0xac]) done
    if (0x006d3980([element+0xf0], w0)) {   publish it as our own, and only if that succeeds
        [element+0xac] = w0                 THE PHASE MOVES
        [element+0xa0]->vtable[0]()         and the content is told
    }

`0x006d3980` walks a table of `{ownerId, entry}` pairs at `[obj+8]..[obj+0x10]` for **our own id**
(`[[0x2616a30]]+0xf0`, the same id content 30's echo check compares against), takes the sub-element
`[entry+0x60] - 0x50`, and sends. There is a matching pair above it for a u32 at `element+0xa8`.

**AND THAT SEND IS WHERE THE FOUR-BYTE BODY IS BUILT, SO THE STEP BODIES ARE READ RATHER THAN
GUESSED.** `0x006d3980` finishes with:

    w8 = [sub+0x8a]                         the high half of the body it already has
    stack = <u16 newValue><u16 w8>          a new LOW half, the high half carried over
    0x006d3860(sub, &stack)                 which is 0x010dbe20 one layer down: [sub+0x88] = the
                                            four bytes, then the transport with len 4

and `0x006d3260` reads the value back out of the same four bytes - `[[obj+0x38]+0x60]+0x38` is
`sub+0x88` under the same `+0x60`-holds-`sub+0x50` convention the publish uses, gated on the byte at
`sub+0x61`. **So the low u16 of a step body is the phase and the high u16 is what the sender last
announced**, and sx52e and sx53's three bodies read straight off:

    00000100   phase 0, announced 1    the cue - the console had already sent command 0
    01000100   phase 1, announced 1    our command let the phase catch up, so it committed
    01000200   phase 1, announced 2    and ran state 3, which sends command 1 announcing phase 2

**WHICH IS sx53 EXPLAINED WITH NOTHING ADDED.** One command, two steps, and then a stop - because
phase 2 needs a second command. `swsh_trade.parse_sync_step` decodes a step body and
`bin/swsh_connect.py` prints the decode beside the trigger.

**AND THE CONSOLE'S OPENING MOVE IS THE PUMP'S, NOT THE MACHINE'S.** The registrar leaves
`[content+0x80] = 1`, and pump state 1 (`0x010db418`, the 17-entry table at `0x2067f08`) sets the
pump to 2 and then calls the state setter with the phase **unconditionally**, outside the
`+0x84`/`+0x86` gate. Phase 0 -> state 1 -> send command 0, announcing 1. That is the cue.

**WHAT IS STILL NOT MEASURED.** How a partner's command reaches `sub+0x88`. The receive handler
`0x010dbc90` does not write it: it keeps the int32, relays it through `0x010dbe20`, and sets the
sender's byte in the map at `[content+0x2a0]+0x1c0`. That our command is what lets the shared value
move is a DEDUCTION from that flag and from every run so far, and `--confirm-commands 0,1,2,3` is
what settles it.

`swsh_trade.SYNC_LADDER`, `sync_announced_phase` and `parse_sync_step` carry the mapping and the
wire shape, with tests driven by the three measured bodies.

## The step body is two u16s with two publishers, and we have only ever echoed it

Still session 65, and it finishes the layer under the ladder. The four-byte body is not one value: it
has two halves, each with its own publisher, and neither publisher touches the other's half.

**THE RECEIVE HANDLER IS FOUR INSTRUCTIONS.** The 40000-family router `0x006d59f0` matches a `Data`
on (elementId, ownerId) against the element's sub-elements - 0x90 bytes each, `[sub+0x62]` the
elementId and `[sub+0x68]` the ownerId - and tail-calls slot 9 of the sub-element's own vtable. For
this channel that is `0x006d6490`:

    if (len != 4) return                    a two-byte body is dropped here, silently
    [sub+0x88] = the four bytes
    [sub+0x78] = the clock
    strh 0x0100 -> [sub+0x60]               which sets the READY byte at sub+0x61

and `sub+0x61` is exactly the byte `0x006d3260` gates on before it returns the value. **So a
four-byte `Data` whose (elementId, ownerId) matches a registered sub-element is the only thing
besides a station's own publish that can change what the phase is read from.**

**AND THE TWO HALVES HAVE TWO PUBLISHERS.**

    0x006d3980(channel, v)   w8 = [sub+0x8a]; body = <u16 v><u16 w8>     writes the LOW half
                             called from the element's update with the value it just read
    0x006d3690(channel, v)   w8 = [sub+0x88]; body = <u16 w8><u16 v>     writes the HIGH half
                             called from content 40's pump, state 4, with `[content+0x86]`

Both resolve the sub-element by finding **our own id** (`[[0x2616a30]]+0xf0`) in the channel's
`{ownerId, entry}` table and taking `[entry+0x60] - 0x50`, and both hand the result to `0x006d3860`,
which is `0x010dbe20` one layer down. **The pump reaches the channel as `[content+0x1c0]` and the
element's update as `[element+0xf0]`, and `0xd0 + 0xf0` is `0x1c0`** - the same object by two routes,
which is what checked this walk.

**AND THE SUB-ELEMENT IS BORN WITH BOTH HALVES SET TO THE SENTINEL.** Its constructor `0x006d6160`
does `mov w8, #0xfc18; movk w8, #0xfc18, lsl #16; str w8, [sub+0x88]` - `0xfc18fc18` - and the next
instruction pair records the object's size as **0x90**, the router's stride. `0xfc18` is the same
value `0x006d3260` returns when there is nothing to read and `0x010db970` writes to `content+0x84`
on teardown.

**WHICH MAKES sx53's OWN CAPTURE READ END TO END, AND IT CONFIRMS THE LAYOUT FROM THE WIRE.** Every
four-byte body on the confirmation content's elementId 20000, in order, decoded off
`scratchpad/sx53_2.out`:

    000018fc   phase 0, announced 0xfc18   the phase minted to 0 by the registrar; the high half is
                                           still the birth sentinel, nothing announced yet
    00000100   phase 0, announced 1        the cue: it had sent command 0
    01000100   phase 1, announced 1        the phase caught up, so the content committed
    01000200   phase 1, announced 2        and ran state 3, which sends command 1

**The high half starting at the constructor's own sentinel and then walking 1, 2 is the wire
agreeing with the image on both publishers at once**, and it is why the halves are no longer a
reading of a hexdump.

**AND THE CORRECTION THIS TURNS UP.** `answer_rpc` copies the body it was handed, so **every step
this project has ever sent carried the console's own two u16s back to it under our ownerId.** We
have never written a value into either half. Answering a value with itself cannot move it, whichever
sub-element the channel reads from - so the one send that has never been made is a step whose low
half is ours. `bin/swsh_connect.py --confirm-phase N` is that send, and `swsh_trade.sync_step` builds
the body.

**AND FOUR SHAPES THE CAPTURE CARRIES THAT WERE NEVER CATALOGUED.** Alongside the pair, the console
sends 40040 envelopes with **no ownerId at all** and bodies that are not four bytes:

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after our syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000

The two-byte ones cannot reach this channel - `0x006d6490` drops anything but four - so they belong
to a handler that has not been walked. The elementId-1 four-byte body is the echo `0x010dbe20`
produces from our syncCommand's int32, which is why it carried our own `0`.

## The hash is a quorum, and the third sub-element kind takes two bytes

Session 65, finishing the two shapes the confirmation content sends that had never been walked: the
four bytes on elementId 10000 and the two-byte bodies in the capture.

**THERE ARE THREE SUB-ELEMENT KINDS AND THEY DIFFER BY BODY LENGTH.** Slot 9 of each kind's vtable
is the receive handler, and all three are the same five instructions with one constant changed:

    0x006d5f20   cmp x2,#4    ldr  w8,[x1]   str  w8,[sub+0x88]      a 32-bit value
    0x006d6490   cmp x2,#4    ldr  w8,[x1]   str  w8,[sub+0x88]      the phase pair
    0x006d69f0   cmp x2,#2    ldrh w8,[x1]   strh w8,[sub+0x88]      A 16-BIT VALUE

each followed by `[sub+0x78] = clock` and `strh 0x0100 -> [sub+0x60]`, which sets the ready byte at
`sub+0x61`. **So the two-byte bodies in sx53's capture are a registered shape, not noise** - there is
a whole channel kind whose values are 16 bits, and the four-byte handlers drop its traffic at their
own `cmp`. Which element field carries it is not yet known: the confirmation element's update only
touches `+0xd0`, `+0xf0` and `+0x110`, and those three are accounted for.

**AND SLOT 7 - THE VALUE THE FRAMEWORK HASHES - IS THE CLOCK, NOT THE BODY.** All three kinds:
`ldr x0,[x0,#0x78]; ret`. `+0x78` is where the receive handler puts the clock and where a send puts
Pia's own id.

**WHICH MAKES THE elementId-10000 FOUR BYTES A QUORUM CHECKSUM.** `0x006d7b40` builds
`element+0xa8` over the sub-elements of the channel at `element+0x110`:

    h = 0
    for sub in subs:
        if (!sub[+0x61]) { h = 0; break }        ANY station not ready -> the hash is ZERO
        h = crc32(le32(h + sub->slot7()))        and slot 7 is the clock

**That is why the hash was `00000000` for the whole run and then suddenly was not.** It is not a
value being computed late - it is a quorum: the hash stays zero until EVERY station's sub-element
has taken a body. A non-zero hash on this channel is the console telling us our own sub-element went
ready, which is a positive acknowledgement this project has been reading as decoration.

**AND `0x0065de30` IS A STANDARD CRC-32.** Its table is generated by `0x0065e110` from the
non-reflected polynomial `0x04C11DB7` (with `<<1`, `<<2`, `<<3` precomputed as `0x09823B6E`,
`0x130476DC`, `0x2608EDB8`), bit-reversing both the index and the value - which is the ordinary
`0xEDB88320` reflected table. Init `0xFFFFFFFF`, `mvn` at the end: `zlib.crc32`, exactly. The
CRC-16 generator two functions along (`0x0065df04`, poly `0x8005`) belongs to a different table and
is easy to mistake for it.

**A MEASURED NEGATIVE, SO THAT NOBODY SPENDS THE SEARCH TWICE.** CRC-32 over a fixed four bytes is
affine over GF(2), so one round inverts exactly and a two-station search only has to scan the first
clock. `scratchpad/swsh_hash_search.py` does that. Run against all four measured hashes -
`8324462b`, `944c70ea`, `7a0ea399` (sx53) and `b22d6f50` (sx52e) - across every clock in the runs'
window, **it finds nothing**. So either the channel's list carries more than the two stations, or the
value hashed is not the envelope clock this project can see. The formula is read; the inputs are not.

## The ladder climbs one rung per command, and the queue ran out before it did

**sx54 IS THE FURTHEST THIS PROJECT HAS BEEN.** `--confirm-commands 0,1,2,3` went out for the first
time - the run had been built in session 64 and blocked by a trade penalty ever since - and the
console's confirmation step body walked **two rungs past where sx53 died**.

FACT, every four-byte body the console put on the confirmation content's elementId 20000, in order,
decoded as `<u16 phase><u16 announced>` (`scratchpad/sx54_4.out`):

    000018fc   phase 0, announced 0xfc18   the sub-element's birth sentinel
    00000100   phase 0, announced 1        the cue - it had sent its command 0
    01000100   phase 1, announced 1        the phase caught up
    01000200   phase 1, announced 2        it committed and sent command 1   <- sx53 STOPPED HERE
    02000200   phase 2, announced 2        the phase caught up again
    02000300   phase 2, announced 3        it committed and sent command 2   <- sx54

sx53 sent ONE command and the ladder stopped at `01000200`. sx54 sent four and it reached
`02000300`. **That is the answer to session 64's open question: the rungs are not climbed on the
console's own initiative, they are paid for.**

**AND THE RUN RAN OUT OF COMMANDS ONE RUNG EARLY, FOR A REASON THE LOG NAMES.** The queue pops on
any four-byte body the confirmation content has not sent before, and the FIRST such body is
`000018fc` - the sub-element's constructor value (`0x006d6160`), not a rung at all. So command 0 was
spent on the sentinel and only three commands ever landed on a step. The queue was empty when
`02000200` arrived, the console climbed once more on the credit it already had, and then nothing.

**THE VALUE IS INERT, AND THE HANDLER'S LAST INSTRUCTION SAYS SO.** `0x010dbc90` end to end:
resolve the sender with `0x006b5850` and drop on `0xfd` (setting `[this+0x64] = 1`); keep our int32
from `[arg1+0x14]` on the stack; index the subscriber slots at `+0x38` by the station index, which
is the two-slot limit content 50 has; hand the int32 to the relay `0x010dbe20` and to the
subscriber's vtable `+0x18`; and then, unconditionally,

    0x010dbdf8  ldr  x8, [x20, #0x18]
    0x010dbdfc  ldr  x0, [x8, #0x2a0]
    0x010dbe00  mov  w2, #1          <- the value recorded for this station is a CONSTANT
    0x010dbe04  mov  x1, x19         <- keyed by the sender
    0x010dbe08  bl   #0x6a24a0

**What the console files against our station is `1`, not the number we sent.** Our int32 goes only to
the relay - which is why the capture carries an elementId-1 body of `00000000` right after a
`syncCommand{data:0}`, the echo of the value itself. And the only thing that moves the content's
state is `0x010dbf40`, whose sole caller is the pump `0x010db3e0`, which passes `[content+0x17c]`,
the content's OWN phase. **So what advances a rung is that a command ARRIVES, not which of 0..3 it
carries** - and the next run needs a queue that does not run dry, not a better guess at the values.

## A stalled ladder costs the player an hour, so the run ends itself now

**TWO RUNS IN A ROW ENDED WITH THE CONSOLE UNDER A TRADE PENALTY** - sx53 and sx54, the only two
runs that have ever reached the confirmation content. FACT: after sx54's last step body the run held
for **200 more seconds of pure acks**, the game sat on `communication en cours... veuillez
patienter`, and it then raised `msg_ui_live_comm_app_alert_00` - an error that names the TRADE as
failed and closes the game. The penalty followed. Roughly an hour, measured by the player across
both.

DEDUCTION: a trade that times out with the link still alive is a failed trade, and a trade whose
link disappears is a lost connection. They are different failures for the game to report, and only
the first has been observed to cost a penalty. **HYPOTHESIS, and the next run tests it**: whatever
the game charges for a dropped link is charged to a peer that does not exist.

`bin/swsh_connect.py --abort-on-stall SECONDS` is the move. Once the confirmation ladder has
produced its first step, the run ends the moment SECONDS pass with no NEW body on it - all
transmission stops and the link goes away well before the game's own timeout. Nothing is given up:
the tail it discards is the 200 seconds of acks. The trigger keys on bodies not seen before, because
the console REPEATS the step it is parked on and a stall is the absence of movement, not of traffic.

## A retail Sword and Shield completed a trade with us

**sx56. THE TRADE COMPLETED.** The console took our Pokemon, gave us its own, wrote its save and
returned the player to the overworld - no crash, no error, no penalty. This is the first completed
trade between this project and a retail Sword/Shield, and it took four sessions of confirmation
content to reach.

FACT, from `scratchpad/sx56_*.out` and the player at the screen:

    we offered      species  94  Ectoplasma  level 100, from slot 1 of the party we advertised
    it offered      species 840  Applin      level 100, OT 'Gurvan' (56909/48474)
    the ladder      000018fc ... 04000400 at t=38.44, the teardown rung
    the console     handed the player a Gengar, held a long save screen, then the overworld
    afterwards      the player could open a new local search immediately

**THE SPECIES IS THE PROOF, AND IT HAD TO BE.** sx55 completed the same climb with `--offer-echo`,
which hands the console its own record back byte for byte - so the player received the Applin they
had just offered and there was no way to tell a completed trade from a returned one. sx56 dropped
the echo for `--offer-slot 1`. **A player who offers an Applin and receives an Ectoplasma has
measured the transfer**, and no reading of the capture is needed to see it.

**WHAT MADE THE DIFFERENCE, IN ORDER.** The queue that does not run dry
(`--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3`), because every rung is paid for with a command and
the sentinel eats the first one. And the abort standing down at phase 4, because the finished
ladder goes quiet exactly like a stalled one - see below.

## The penalty is the failed trade, and a dropped link is not one

**MEASURED, AND IT CHANGES THE RUN BUDGET.** sx53 and sx54 both held the link alive and acking
until the game's own timeout declared the TRADE failed, and both cost the player about an hour's
lockout. sx55 dropped the link instead: the console raised **2-ALZAA-0016**, a plain communication
error, and **the player was able to start a new local search at once**. Same phase of the same
flow, two failure paths, one penalty between them.

So `--abort-on-stall SECONDS` does what it was built for. **The hypothesis in the session before
this one is now a measurement.**

**AND ITS FIRST VERSION DROPPED THE LINK ON A TRADE THAT HAD SUCCEEDED.** sx55 climbed the WHOLE
ladder to `04000400`, ran the trade, handed the player our Pokemon - and then stopped producing
steps, because **phase 4 is the teardown rung and its state sends nothing** (`0x010dbf40`: phase 4
-> state 13 -> 14). Fifteen seconds later the abort could not tell the finish from a stall and cut
the link under a game that was mid-save: 2-ALZAA-0016 at the worst possible moment. `stall_abort()`
takes `final_phase_seen` now, and a ladder that has reached `LADDER_FINAL_PHASE` is done - the run
holds for whatever the game does next, which is the save, the summary and the migration.
