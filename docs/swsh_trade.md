---
title: The Link Trade
parent: Sword and Shield
nav_order: 3
---

# Trading with a retail Sword and Shield

A retail Sword has completed a trade with pokeldn: it accepted a Pokemon, gave one of its own, wrote
its save and returned the player to the overworld, with no error and no penalty.

This page covers the trade from the snapshot exchange to the save. The message framing, the content
registration and the PK8 format are on [The sync framework](swsh_protocol.md).

## The sequence

    1  the console broadcasts its 3456-byte snapshot on protocol 0x84, port 0
    2  the client acknowledges the fragments (0x21) and the transfer (0x19 / 0x28)
    3  the client sends its own snapshot on 0x84, PORT 1, and reports it complete
    4  the trade screen opens on the console
    5  the console sends the 40030 RPC pair on 0x7C PORT 1, several times a second
    6  the client answers the pair and sends `imReady` on the trade holder (20030)
    7  the console offers a Pokemon on 20030; the client offers one back on 10050
    8  the player accepts; the console sends MIGRATION_START on protocol 0x18 port 1
    9  the confirmation ladder runs on content 40
    10 the console writes its save

Transport rules for steps 1-3:

- The two directions do not share a Pia port. The console sends its snapshot on port 0 and
  acknowledges the peer's on port 1; a snapshot sent on port 0 is never acknowledged.
- A receiver that never answers 0x84 never sees the console's other message kinds. The console
  retransmits one snapshot indefinitely (19142 messages in one run; 13 once the fragments were
  acknowledged). `pokeldn/ldn/broadcast4.py` implements all four kinds.

## The trade RPC

When the trade screen opens the console sends message id 40030 as a pair, several times a second, on
0x7C port 1. The ping, the block messages and the Pokemon offer arrive on port 0. An answer sent on
port 0 goes to a window the console does not read there.

    id 40030 = 40000 + 30
      1  offset      30            - the same 30 the id is built from
      2  base        10000, and 20000 in the other member of the pair
      3  station id  THE SENDER'S, byte-identical to the host_constant our own seat record holds
      4  clock       a counter that advances between messages
      5  bytes(4)    00000000 for the 10000 member, 000018fc for the 20000 one

The base and the offset travel as separate fields and 20000 + 30 is assembled on the wire.
`0x006d44e0` opens with `strh w1, [x0, #0xac]`, overwriting the `0xfc18` its constructor put there;
`0xfc18` is the `000018fc` one member of the pair carries in field 5.

Field 3 is a station id; both of the console's own messages rebuild byte for byte from the parsed
fields. `pokeldn/swsh/trade.py`.

The Pokemon offer is 20030, `PokemonTradeDataHolder{pokemon{serializePokemonParam}}` holding a
344-byte party-form PK8. 40030 is the envelope that precedes it.

`3e4e000012020801` is message 20030 carrying `imReady{isReady:true}`. The console never sends those
bytes; published clients wait for them before offering. With them sent, the console displays the
offered Pokemon and asks the player to confirm.

Send each answer once. A sender on a timer that re-derives an answer to a message already answered
produced 859 copies of one Pokemon offer over 259 seconds where the console had asked once; the
window advances a sequence only once the last is acked, so those collapse to roughly forty delivered
duplicates. The game processed the offer while being flooded. `--answer-once` answers each payload
once.

Readers must not raise. At the confirmation prompt the console sends a three-byte message (a mesh
message, see [host migration](#host-migration)); a reader that raised on it killed the receive task,
transmission stopped mid-trade, and the player saw `la communication avec l'autre joueur a été
interrompue`. Every reader in `pokeldn/swsh/trade.py` returns `None` instead.

## Host migration

Once the player accepts, the console sends twelve bytes on protocol 0x18 port 1 and never speaks on
the application layer again:

    0f 00 00 03 00 01 00 01   44 00 01
    ^ version 4's reliable header, sequence 1     ^ the mesh message

`44` is the mesh protocol's MIGRATION_START, `[0x44, host index 0, new host index 1]`, matching the
join response's `stations=2 host_index=0 our_index=1`: the console names the client as the next host
of its mesh. The answer is `[0x48, our own station index]`, two bytes. Mesh protocol port 1 is the
reliable port, so the mesh message rides inside the reliable window. Both handlers are on
[The Pia layer](pia.md#host-migration).

The console sends it once and never retransmits; one transport ack satisfies it. Pia's RTTI names
the operation `nn::pia::mesh::LeaveWithHostMigrationJob`.

## The box state machine

Everything from the trade screen to the offer runs on content 30, the box exchange.

Commands are 1..6. `onBoxSyncStateCommand` is `0x010ce180`, vtable slot 1 of the 0x50-byte wrapper
at `session+0x120` (vtable group `0x2625808`):

1. `if (sender == our own station) return`: it ignores its own echo, `[[0x2616a30]]+0xf0`.
2. `w8 = msg->data`, then `if ((w8 - 1) > 5) return`. 0, 7, 8 and anything higher are dropped
   silently.
3. A six-entry jump table at `0x2067bec`, one case per command, each notifying every listener with
   the command value unchanged. Wire command *N* becomes event *N*.

Field 1 of the same holder, `boxSendPokemon`, goes to vtable slot 0, `0x010ce080`, and notifies with
event 0. The receive dispatcher takes 0..6; the sender emits 1..5; 0 is the Pokemon.

The commands come in toggle pairs. The listener `0x00c8d900` keeps one flag byte per event in an
array at `+0x218`, `[owner + 0x218 + code] = 1`, and before setting the new flag it clears another:

    code 2 clears the flag for code 1        (+0x219)
    code 5 clears the flag for code 4        (+0x21c)

1 offers and 2 withdraws the offer; 4 confirms and 5 withdraws the confirmation. Measured: 1 then 2
made the console begin leaving four seconds later (a cancelled offer); 4, 5 and 6 into the
post-accept window retracted the 4 about a second after it landed.

The sender is `0x010cda70(content, command)`, reached through five one-line wrappers `0x010cde90` ..
`0x010cded0`, commands 1 to 5 in address order. The scene drives them from a six-way jump table at
`0x00a96d10` keyed on its own action field `+0x78`:

    action 1  ->  command 3
    action 2  ->  the Pokemon (0x010ca430), then command 1
    action 3  ->  command 2
    action 4  ->  command 5
    action 5  ->  command 4
    action 6  ->  0x010ca640, which stores our Pokemon and sets the trade state to 1

Two gates sit in front of the send and both fail silently:

    [content+0x48] holds a pending command; a DIFFERENT one arriving sets the error byte
                   [content+0x4d] and sends nothing at all
    [content+0x4c] is the channel-ready bool, set by 0x010ce040 on a zero result code; while it is
                   clear the command is parked in +0x48 and never goes out

Command 3 is an opener. The session's per-frame update `0x010c9bb0` does this before it switches on
the trade state:

    if ([session+0x418]) { if (![session+0x419]) send command 3; [session+0x418] = 0; }

`+0x418` is set to 1 by the setup at `0x010c9280` and `+0x419` to `0x00dceea0() & 1`, which walks the
player list. Exactly one of the two sides emits command 3 on its first frame after the trade session
is built; a role bit decides which. `--box-open` sends box commands at the 0x84 snapshot ack, before
either side offers anything.

None of the four published clients names a command value; they encode the holder only.

## The trade state machine

`[session+0x140]`, table at `0x2067b68`, seven live entries and a range of 1..10:

    1  0x010c9c78  -> 0x010ca0a0: start content 50 and send our Pokemon. true -> 2, false -> 9
    2  wait        5  wait        7  wait
    3  0x010c9f60  the Pokemon exchange - 0x010d54b0 on content 50 - then state 4, or 9 on error
    4  0x010c9c9c  0x01109320 decides; false goes to state 6
    6  0x010c9f84  -> 0x010ca1ac: install four delegates and START CONTENT 40
    8  0x010c9fa8  content 40's teardown - 0x010dac90 - then state 9
    9  0x010c9ef4  terminal: [+0x144] set means failure, and the listeners are told event 8
    10 0x010ca838

`[session+0x140]` also gates the box callback: `0x010ca800` drops every event unless the state is 0,
so once an error is recorded the session stops listening.

State 2 is left by a delegate the state-1 branch installs at `session+0x2e0`, `0x010cc380`: it takes
the object it is handed, stores it at `session+0x70` (the partner's Pokemon), builds a 0x60-byte
record from it (`0x010f5cc0`) and writes `[session+0x140] = 3`. The partner's Pokemon arriving
through content 50's own receive event moves the console out of state 2.

State 8 is content 40's teardown. `0x010c9fa8` calls `0x010dac90(content40, session+0x170,
session+0x210)`, which walks the listener vectors at `[content+0x20]+0x60` and `[content+0x28]+0x60`,
removes those two, and tail-calls `0x010daac0`, the release. The state after it is 9.

State 1 is where an abort originates. `0x010ca0a0` calls `0x010d5440`, content 50's send, which opens
with `bl 0x010d4d90` and does nothing if that returns false. `0x010d4d90` is content 50's own init,
the twin of content 40's `0x010da470`; it registers with `mov w2, #0x32`. On false the caller takes
`[session+0x144] = 1` and state 9: error, listeners told event 8, the interrupted-communication
message.

## The confirmation ladder

Content 40 runs the last phase as a barrier: one rung per command received.

### The phase-to-state map

The machine's state is `delegate+0x5c`. Every store to that offset in the 30/40/50 band is the init
(0), four inside the machine `0x010dae70`, and `0x010dbf40`. The dispatch is `state - 1` into a
14-entry table at `0x2067ed0`; states 2, 4, 7 and 9 (the four the sends leave the machine in) take
the table's shared default `0x010db38c`, the function's epilogue. The machine leaves an idle state
only through `0x010dbf40`.

`0x010dbf40` takes a u16, drops out with the state untouched if it is above 4, and otherwise indexes
a 5-entry table at `0x2067f4c`:

    phase 0  -> state 1             -> send(0), announcing phase 1     0x010db308
    phase 1  -> state 3             -> send(1), announcing phase 2     0x010db0b0
    phase 2  -> state 5 -> 6 or 8   -> send(2), announcing phase 3     0x010db0dc / 0x010db104
    phase 3  -> state 10 or 11 -> 12 -> send(3), announcing phase 4    0x010db16c
    phase 4  -> state 13 -> 14      -> 0x010db970 tears the holders down and writes the sentinel
                                       0xfc18 to content+0x84. Nothing more is sent.

The two ways of reaching a send of 2 are the two roles: `[delegate+0x58]`, set in the init from
`0x110e620(...) & 1`, picks state 7 (send at once) or state 9 (send after a countdown
`[delegate+0x60]`, seeded from an xorshift to a random 2..302).

`0x010dbf40` is slot 0 of a second interface. The vtable group at `0x257fe90` is a
multiple-inheritance group: a primary vtable at `0x257fea0` whose slot 0 is the SyncCommand receive
handler `0x010dbc90` and whose slot 3 is `0x010dbf40`, then an offset-to-top of −8 at `0x257fec8` and
a secondary vtable at `0x257fed8` whose slot 0 is `0x010dbfd0`, the same code against `+0x50`/`+0x54`
instead of `+0x58`/`+0x5c` (the thunk for a `this` adjusted by 8). The init installs both halves:

    0x010da6bc   add x9, x19, #8       ->  [content+0x2c0] = delegate + 8     the second interface
    0x010da6d0   str x19, [x8, #0x168] ->  the 10040 holder's listener        the first

### The pump

`0x010db3e0`, called by content 40's per-frame tick before it runs the machine, is a 17-state machine
on `[content+0x80]`. Its shared tail:

    w1 = [content+0x17c]                    the content's PHASE
    if (w1 == [content+0x84]) skip          already committed to it
    else if (w1 == [content+0x86]) { 0x010de310(content, w1); B->slot7(w1); }
    w1 = [content+0x17c]
    if (w1 == [content+0x84]) done
    else if (w1 == [content+0x86]) { 0x010de310(content, w1); B->slot0(w1); }   <- the state setter

`0x010de310(content, phase)` writes `[content+0x84] = phase` and drops the content's pending body:
`+0x84` is the phase the content has committed to. `+0x86` is written in exactly one place in the
band, `0x010dbab0`, with the `flag` argument, which is `data + 1` at all five send sites: `+0x86` is
the phase the console announced when it sent its last command. The ladder climbs when the content's
phase reaches it.

The console's opening move is the pump's: the registrar leaves `[content+0x80] = 1` and pump state 1
(`0x010db418`, table `0x2067f08`) calls the state setter with the phase unconditionally, outside the
`+0x84`/`+0x86` gate. Phase 0 -> state 1 -> command 0, announcing 1.

### The phase is the element's field

Nothing between `0x010c0000` and `0x010e0000` stores to `content+0x17c`. The registrar builds the
40040 element at `content+0xd0` (`0x010daa4c add x21, x19, #0xd0`, then `0x006d4ff0` to add the
sub-element and `0x006d44e0(element, w20)` to mint it), and `0x006d44e0` opens with
`str wzr,[x0,#0xa8]; strh w1,[x0,#0xac]`. `0xd0 + 0xac` is `0x17c`: the phase is `element+0xac`,
starting at the registrar's `w1`, which content 40's init passes as `wzr`.

The element advances it in one place, `0x006d4ca0`, with the mesh's permission:

    w0  = 0x006d3260([element+0xf0])        read the shared value; 0xfc18 when there is none
    if (w0 == [element+0xac]) done
    if (0x006d3980([element+0xf0], w0)) {   publish it as our own, and only if that succeeds
        [element+0xac] = w0                 the phase moves
        [element+0xa0]->vtable[0]()         and the content is told
    }

### The step body

The four-byte body on the confirmation content's elementId 20000 has two halves with two publishers;
neither touches the other's half:

    0x006d3980(channel, v)   w8 = [sub+0x8a]; body = <u16 v><u16 w8>     writes the LOW half
                             called from the element's update with the value it just read
    0x006d3690(channel, v)   w8 = [sub+0x88]; body = <u16 w8><u16 v>     writes the HIGH half
                             called from content 40's pump, state 4, with [content+0x86]

Both resolve the sub-element by finding the station's own id (`[[0x2616a30]]+0xf0`) in the channel's
`{ownerId, entry}` table and taking `[entry+0x60] - 0x50`, and both hand the result to `0x006d3860`,
which is `0x010dbe20` one layer down. The pump reaches the channel as `[content+0x1c0]` and the
element's update as `[element+0xf0]`; `0xd0 + 0xf0` is `0x1c0`, the same object by two routes.

The low u16 is the phase and the high u16 is what the sender last announced. An observed ladder:

    000018fc   phase 0, announced 0xfc18   the sub-element's birth sentinel
    00000100   phase 0, announced 1        the cue - the console had already sent command 0
    01000100   phase 1, announced 1        the phase caught up, so the content committed
    01000200   phase 1, announced 2        it ran state 3, which sends command 1
    02000200   phase 2, announced 2        the phase caught up again
    02000300   phase 2, announced 3        it committed and sent command 2
    04000400   phase 4                     the teardown rung

`swsh_trade.parse_sync_step` decodes one; `swsh_trade.SYNC_LADDER` and `sync_announced_phase` carry
the mapping.

### The command

`SyncSaveDataHolder{syncCommand{data:N}}` on 10040, reliable port 0. The handler `0x010dbc90`
resolves the sender with `0x006b5850` and drops on `0xfd`; keeps the int32 from `[arg1+0x14]`;
indexes the subscriber slots at `+0x38` by the station index; hands the int32 to the relay
`0x010dbe20` and to the subscriber's vtable `+0x18`; and then, unconditionally:

    0x010dbdf8  ldr  x8, [x20, #0x18]
    0x010dbdfc  ldr  x0, [x8, #0x2a0]
    0x010dbe00  mov  w2, #1          <- the value recorded for this station is a CONSTANT
    0x010dbe04  mov  x1, x19         <- keyed by the sender
    0x010dbe08  bl   #0x6a24a0

The console files `1` against a station whatever number was sent. The int32 goes only to the relay:
an elementId-1 body of `00000000` appears right after a `syncCommand{data:0}`, the echo of the value.
The only thing that moves the content's state is `0x010dbf40`, whose sole caller is the pump, which
passes the content's own phase. A rung advances because a command arrives, not because of which of
0..3 it carries.

Measured with the command count as the only variable: one command bought two rungs (to `01000200`);
four commands bought four (to `02000300`). The queue must not run dry: the trigger pops on any
four-byte body not seen before, and the first such body is the birth sentinel `000018fc`, so the
first command is spent on something that is not a rung. `--confirm-commands 0,1,2,3,0,1,2,3,0,1,2,3`
is the working line.

`answer_rpc` copies the body it was handed, so an answer that echoes a step carries the console's own
two u16s back and moves neither half. `--confirm-phase N` writes the low half and keeps the high one.

### Shapes the confirmation content also sends

Alongside the pair, the console sends 40040 envelopes with no ownerId and bodies that are not four
bytes:

    elementId 20000, no owner, 2 bytes   0000   then   0100
    elementId 1,     no owner, 4 bytes   00000000        after a syncCommand{data:0}
    no elementId,    no owner, 4 bytes   00000000  then  01000000

The two-byte ones are dropped by `0x006d6490`'s `cmp x2,#4` and belong to the two-byte sub-element
kind, whose owning element field is unknown.

## The record we offer

The Pokemon offered on 20030 is a party record out of the 0x84 snapshot the client sends, selected
by `--offer-slot`. The edit is applied to the slot inside the snapshot, so the party the console is
shown and the Pokemon it is offered are the same record. `party_matches_trainer` holds after it: the
identity rewrite runs first and the offer flags do not touch the trainer ids.

`pokeldn.swsh.pokemon.build_from` rewrites the checksum, reshuffles the four blocks under the new
encryption constant, and keeps every byte no flag names. The 0x158 party form carries ribbons,
memories, met data and handler records that nothing here reads.

    --offer-slot 1 --offer-nickname PKCAMP --offer-ivs 31,31,31,31,31,31

| flag | effect |
|---|---|
| `--offer-nickname`, `--offer-ot` | 26-byte UTF-16 fields; at most 12 characters. A nickname sets the nicknamed flag; without it the console draws the species name |
| `--offer-species` | the species word alone; ability, moves, party stats, experience and met data stay the template's |
| `--offer-ability ID`, `--offer-moves A,B,C,D` | the two fields; PP and relearn moves stay |
| `--offer-level N` | the level byte at 0x148 |
| `--offer-experience N` | the experience word at 0x10 |
| `--offer-ivs` | the six IVs |
| `--offer-file FILE` | a `.pk8` from disk in any of its four shapes (stored or party, encrypted or PKHeX's decrypted export, told apart by whether the header checksum matches the raw body). Its OT name and ids are moved to the snapshot's trainer |
| `--offer-file-as-is` | keeps the file's OT |
| `--save-offer FILE` | writes the built record before the radio is touched |

Measured on a French Sword 1.3.2, one variable per run:

| record sent | result on the console |
|---|---|
| slot-1 Gengar template, nickname `PKCAMP`, six IVs of 31 | accepted, saved; summary read the nickname, level 100, `Potentiel exceptionnel`. Unnamed fields came through as the template's: female, ball 9, held item 281 (Boue Noire), met level 59, language 3, version 44 |
| the same with the species word set to 93 (Haunter), ability 130 (Cursed Body, which Haunter lacks), the Gengar's moves 164, 247, 482, 411 and stats | drawn as a Haunter named PKCAMP, saved, then trade-evolved to Gengar. Neither ability nor moves are checked against the species |
| the same with the species word set to 25 (Pikachu) | accepted. Summary: level 100, HP 211, Atk 131, Def 116, SpA 199, SpD 137, Spe 306: Pikachu's level-100 stats from the record's IVs (31, 31, 19, 6, 31, 31 in HP, Atk, Def, Spe, SpA, SpD order), EVs (0, 0, 0, 252, 252, 6), Timid nature and the hyper-training byte 0x24 at 0x126 (Def and Spe read as IV 31). The twelve stat bytes at 0x14A (the Gengar's 261/149/156/350/359/187) were discarded. Ability Cursed Body, item Black Sludge, moves Substitute, Shadow Ball, Sludge Wave, Focus Blast kept as sent |
| the Pikachu with the level byte at 0x148 set to 50 and experience left at 1059860 | drawn and received at level 100. The level comes from the experience word at 0x10; the party tail (level and stats) is discarded on receipt and rebuilt from the stored record |
| a PKHeX party-form export of a level-18 Flapple, OT moved to the snapshot's trainer (PkCamp, 12345/54321) | drawn as a level-18 Flapple, traded; summary read OT PkCamp, ID 993401 (`(54321 << 16 \| 12345) mod 1000000`, the six-digit Gen 7+ form), 9564 experience |
| the same file with its own OT kept (Gurvan, 56909/48474, the receiving player's own ids) under a MyStatus that says PkCamp | accepted and traded. Summary: OT Gurvan, ID 848973, met line as the player's own catch: level 18 on 26/11/2019 on Route 5 (the record's met date, level and location 40). The game does not compare the offered record's OT ids with the partner's MyStatus |
| the Flapple with the PID high half set to `low ^ TID ^ SID` against 12345/54321 (gender and nature bytes untouched; they are stored separately in Gen 8) | drawn shiny on the offer screen; shiny star on the summary after the trade |
| the Flapple file with the species word set to 152 (absent from the game) | climbed the whole ladder, landed in the PC. Offer screen: Pikachu's model, name Pomdrapi (the record's name field, nicknamed flag clear). Box icon a black Poke Ball, level 21: 9564 experience is level 21 on Medium Fast (21^3 = 9261, 22^3 = 10648), level 18 on Erratic, level 23 on Medium Slow. Traded back: level 21, stats 33/6/8/8/8/10 = base stats of zero at level 21 with the file's IVs (14, 7, 18, 17, 21, 24) and Adamant nature (HP `floor(14 * 21 / 100) + 31`, the rest `floor(IV * 21 / 100) + 5` with nature). The species entry for 152 is empty: zero base stats, growth group 0. Every other byte came back unchanged except current HP at 0x8A (55 to 33) and the handler block: name Gurvan at 0xA8, gender at 0xC2, language 3 at 0xC3, friendship 0 at 0xC8, two memory bytes at 0xCB-0xCC |

Unmeasured: which model and name the game draws for other absent species, and whether the name
shown came from the record's name field or from a failed species-name lookup.

A record the console offers can be one an earlier run gave it. One 20030 offer carried the client's
own trainer ids, `PkCamp` as the original trainer and the slot-1 template's nickname and IVs, with
`CurrentHandler` 1 and `HandlingTrainerName` the console's player.

    ./.venv/bin/python scratchpad/sw_offer_check.py SNAPSHOT --offer-slot 1 --offer-nickname PKCAMP

builds the record offline, reads it back through `offered_pokemon`, and prints the party and the
identity consistency.

## The penalty, and ending a run cleanly

A trade that times out with the link still alive is reported by the game as a failed trade and
costs the console about an hour's lockout (measured by the player across two runs). The alert is
`msg_ui_live_comm_app_alert_00`, line 331 of `/bin/message/French/common/live_comm.dat`; the text
names no duration and the label does not appear in 1.3.2's `main.bin`.

A trade whose link disappears is reported as a plain communication error, `2-ALZAA-0016`, and a new
local search is available at once.

`bin/swsh_connect.py --abort-on-stall SECONDS` drops the link once the confirmation ladder has
produced its first step and SECONDS pass with no new body on it. The trigger keys on bodies not seen
before: the console repeats the step it is parked on.

The abort stands down at phase 4. Phase 4 is the teardown rung and its state sends nothing, so a
finished ladder is silent like a stalled one. `stall_abort()` takes `final_phase_seen`; a ladder that
has reached `LADDER_FINAL_PHASE` is done, and the run holds for the save, the summary and the
migration.

Never change the console's clock or any system setting to clear an in-game gate. BDSP detects a
clock change and locks time-based features for a day.

## Verifying a completed trade

A Pokemon the console received in a trade comes back with `CurrentHandler` 1 at 0xC4 and the
receiving player's name in `HandlingTrainerName` at 0xA8, over an original trainer that is still the
sender's.

With `--offer-echo` (the console's own record handed back) a completed trade and a returned Pokemon
look identical: the player receives the Applin they offered. Offering slot 1 of the advertised party
makes the species the proof: a player who offers an Applin and receives an Ectoplasma has seen the
transfer.
