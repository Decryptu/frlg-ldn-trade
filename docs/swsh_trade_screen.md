---
title: The trade screen
parent: The trade
grand_parent: Sword and Shield
nav_order: 1
---

# What the player sees, and the machine behind it

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
