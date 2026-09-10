"""Sword/Shield's application layer: the protobuf messages that ride the reliable windows.

A message is a four-byte little-endian message id and a protobuf body. The ids come from two
different places in `main` and it is worth knowing which, because it decides what is measured and
what is inferred (`scratchpad/swsh_msgid.py`):

  - **the low ids are a registration table** - 838 records at 0x01BBFFA0, ids 1..880. 97, 110, 120
    and 130 are all in it.
  - **the high ids are computed, base + offset.** 40030 and its neighbours appear NOWHERE in the
    image - not as a word, not as a MOVZ immediate - while 20000, 40000 and 60000 do, and the code
    around them adds a register: `mov w9, #0x4e20; add w27, w22, w9`.

The message SHAPES are the game's own, out of the `FileDescriptorProto`s `main` ships
(`scratchpad/swsh_proto.py` reads all 78). Nothing here is a guess about a wire format:

    gflnet.p2p.sync.ping.pb.SyncPingDataHolder   1 ping, 2 pingReply, 3 pingSynced
    gflnet.p2p.block.pb.BlockDataHolder          1 result{isBlocking}, 2 imReady{isReady}
    net_contents.trade.common.pokemon_trade.protocol_buffers
        Pokemon                 1 bytes serializePokemonParam
        PokemonTradeDataHolder  1 Pokemon pokemon

Measured on this console (`scratchpad/sw_app_payloads.py`): id 97 with all three of its fields,
and id 60000 with `result{}` on 0x7C and `imReady{isReady:true}` on 0x80. Those five payloads and
no others. Everything past the trade snapshot is in `SYNC_ANSWERS` and is borrowed; see its comment.
"""
import struct

# --- protobuf, only the two wire types these messages use -------------------------------------

WIRE_VARINT = 0
WIRE_BYTES = 2


def varint(value):
    if value < 0:
        raise ValueError("only non-negative varints appear in these messages")
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(number, payload):
    """A length-delimited field: `bytes` or a nested message."""
    return varint((number << 3) | WIRE_BYTES) + varint(len(payload)) + bytes(payload)


def field_varint(number, value):
    return varint((number << 3) | WIRE_VARINT) + varint(value)


# --- messages ----------------------------------------------------------------------------------

SYNC_PING = 97                        # gflnet.p2p.sync.ping.pb.SyncPingDataHolder
BLOCK = 60000                         # gflnet.p2p.block.pb.BlockDataHolder
POKEMON_TRADE = 20030                 # measured: the console offers its own Pokemon here.
                                      # 40030 is the RPC envelope, not this

PING, PING_REPLY, PING_SYNCED = 1, 2, 3           # SyncPingDataHolder's three fields
RESULT, IM_READY = 1, 2                           # BlockDataHolder's two

# The other holders that answer to the same three-field shape. All four ids are registered in the
# low table, which is what makes them ids rather than byte strings.
SYNC_IDS = (SYNC_PING, 110, 120, 130)


def message(message_id, body=b""):
    """-> the four-byte little-endian id and its protobuf body, which is the whole wire format."""
    return struct.pack("<I", message_id) + bytes(body)


def parse(payload):
    """-> (message_id, body). Raises on anything too short to carry an id."""
    if len(payload) < 4:
        raise ValueError(f"{len(payload)} bytes cannot carry a message id")
    return struct.unpack_from("<I", payload, 0)[0], payload[4:]


def sync(message_id, which):
    """-> an empty one of the three sync fields, e.g. `610000000a00` for ping."""
    return message(message_id, field(which, b""))


def result():
    """`result{}` on the block holder, what the console asks for on 0x7C. Measured."""
    return message(BLOCK, field(RESULT, b""))


def im_ready(ready=True):
    """`imReady{isReady:true}`, what the console asks for on 0x80. Measured."""
    return message(BLOCK, field(IM_READY, field_varint(1, 1 if ready else 0)))


def pokemon_trade(pk8):
    """-> PokemonTradeDataHolder{pokemon{serializePokemonParam: <the PK8>}}.

    The PK8 goes in ENCRYPTED, as it travels: the 0x84 snapshot carries encrypted party records and
    `serializePokemonParam` is the same serialised form. 0x158 is the party form, which is what
    Sword sends and therefore what it is expected to receive; `pokeldn.swsh.pokemon.build_from`
    makes one out of a record the console itself sent.
    """
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(POKEMON_TRADE, field(1, field(1, pk8)))


# --- the trade RPC envelope, measured -----------------------------------------------------------

# The console's own bytes when the trade screen opens. Message id 40030 carries one nested field
# whose five members decode without a guess:
#
#     id 40030          = 40000 + 30, and field 1 below is that same 30
#       1  syncId       30            the game's own names: this envelope is
#       2  elementId    10000 / 20000 `gflnet.p2p.sync.pb.Data`, and the schema is in
#       3  ownerId      the sender's  `scratchpad/swsh_schema.txt` at data.proto
#       4  clock        a counter that advances between messages
#       5  body         00000000 / 000018fc here; a 344-byte PK8 in the console's own 40050
#
# `ownerId` is byte-identical to the `host_constant` our own seat record holds, so it is a field to
# write rather than a six-byte find-and-replace. The receiving side resolves it to a station index
# before it looks at a body (`0x010d5e40`, docs/swsh_protocol.md).
#
# This is also where 20030 comes from: the high ids are a base plus an offset and no literal 20030
# exists in the image. The base and the offset travel as separate fields of this envelope, and
# 20000 + 30 is assembled from them on the wire.
RPC_ENVELOPE_BASE = 40000             # the envelope's own id is this plus the same offset
RPC_ENVELOPE = 40030                  # the only one the console has ever sent us: offset 30
RPC_PREFIX = struct.pack("<I", RPC_ENVELOPE)      # its four-byte header, for recognising a member
                                      # of the pair on the wire before parsing it
RPC_OFFSET, RPC_BASE, RPC_STATION, RPC_CLOCK, RPC_BODY = 1, 2, 3, 4, 5
RPC_BASES = (10000, 20000)            # the pair the console sends, and the pair it expects back

# The offset is the procedure, and the envelope's id carries it twice: as `40000 + offset` and as
# field 1. The dispatcher at main.bin `0x013b2c00` bands and indexes a message id, and an id in
# 40001..60000 indexes its container at `id - 40001`, so 40050 and 40040 are legal ids in the same
# band as the 40030 the console sends, at indexes 49 and 39.
OFFER_OFFSET = 30                     # measured on this console
SELECTION_OFFSET = 50                 # nxldn-lab's, structurally consistent, not measured here
CONFIRMATION_OFFSET = 40              # the same

# `main` ships three trade holders and the registry has three trade contents, so they pair off.
# Each pairing is forced by something on the wire:
#
#   content 30  BoxSyncStateDataHolder   1 boxSendPokemon, 2 boxSyncStateCommand
#               Measured: `3e4e000012020801` is a field 2 on 20030 and only this holder has one.
#   content 50  PokemonTradeDataHolder   1 Pokemon{1 serializePokemonParam}
#               nxldn-lab's `decode_rpc_pokemon_offer` pulls a 344-byte PK8 out of field 5 of a
#               40050 envelope, so content 50 is the one that carries a Pokemon.
#   content 40  SyncSaveDataHolder       1 syncCommand{int32 data}
#               what is left, and a save sync is what a finished trade would run.
#
# So 20030 is the box exchange, showing each other a Pokemon, and not the trade. The transfer
# itself is content 50 and the save sync is content 40.
CONTENT_HOLDERS = {OFFER_OFFSET: "BoxSyncStateDataHolder",
                   SELECTION_OFFSET: "PokemonTradeDataHolder",
                   CONFIRMATION_OFFSET: "SyncSaveDataHolder"}
RPC_POKEMON_FIELD = 5                 # where a PK8 rides inside the envelope's inner message

# The two bodies are the console's own: its 40030 pair carries `00000000` against base 10000 and
# `000018fc` against base 20000, and the 40050 pair carries the same two. The pair's shape belongs
# to the envelope, not to the procedure.
RPC_PAIR_BODIES = (b"\x00\x00\x00\x00", bytes.fromhex("000018fc"))


def build_rpc(offset, base, station_id, clock, body=b"\x00\x00\x00\x00", envelope=None):
    """-> one member of a trade RPC pair, as the console builds its own.

    `envelope` defaults to `40000 + offset`, which is what makes the offer envelope 40030 and the
    selection one 40050; pass it only to reproduce bytes that disagree with that rule.
    """
    inner = field_varint(RPC_OFFSET, offset)
    if base is not None:                      # the console's own Pokemon-carrying 40050 has
        inner += field_varint(RPC_BASE, base)  # neither of these two, only fields 1, 4 and 5
    if station_id is not None:
        inner += field_varint(RPC_STATION, station_id)
    inner += field_varint(RPC_CLOCK, clock) + field(RPC_BODY, body)
    if envelope is None:
        envelope = RPC_ENVELOPE_BASE + offset
    return message(envelope, field(1, inner))


def build_rpc_pokemon(offset, base, station_id, clock, pk8):
    """-> an RPC envelope carrying a PK8 in field 5, the shape the console uses on content 50.

    `nxldn-lab`'s `decode_rpc_pokemon_offer` reads exactly this: walk the envelope's inner message
    and take field 5 when it is 344 bytes. So field 5 is not always the four-byte body the 40030
    pair carries - it is a variable-length slot, and on content 50 it holds the Pokemon.
    """
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return build_rpc(offset, base, station_id, clock, pk8)


def mirror_pokemon_offer(offset, clock, pk8):
    """-> a Pokemon-carrying envelope with the console's OWN field set: syncId, clock, body.

    The console's selection offer decodes to fields 1, 4 and 5 only, with no `elementId` and no
    `ownerId`, where `build_rpc_pokemon` writes all five. All five with our own ownerId is
    acknowledged on every sequence and moves nothing.

    The identity is not the reason: the ownerId sent was the id the console addressed a reliable
    ack to in the same run, so it knows us by that value. The field set is what is left to vary.
    """
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return build_rpc(offset, None, None, clock, pk8)


def build_rpc_pair(offset, station_id, clock, bodies=RPC_PAIR_BODIES):
    """-> the two members of an RPC pair, base 10000 then base 20000, in the order it sends them.

    THIS IS HOW A PHASE IS OPENED. The console opens the offer phase with its 40030 pair and we
    answer it; nothing here has ever opened one. `nxldn-lab`'s client sends a 40050 pair unprompted
    to start the selection phase, and its two messages differ from the console's 40030 pair in one
    field - the offset - plus the station id, which is ours.
    """
    return tuple(build_rpc(offset, base, station_id, clock, body)
                 for base, body in zip(RPC_BASES, bodies))


def parse_rpc(payload):
    """-> the five members of a trade RPC, or None if this is not one."""
    got = _maybe_parse(payload)
    # Any envelope in the band, not just 40030: past the offer phase the console sends 40050
    # pairs. The envelope's id is 40000 + the same offset its field 1 carries, so the band is the
    # test and the offset is read from the message.
    if got is None or not (RPC_ENVELOPE_BASE < got[0] <= RPC_ENVELOPE_BASE + 1000):
        return None
    _, body = got
    outer = _read_fields(body)
    if not isinstance(outer.get(1), bytes):
        return None
    inner = _read_fields(outer[1])
    return {"envelope": got[0], "offset": inner.get(RPC_OFFSET), "base": inner.get(RPC_BASE),
            "station_id": inner.get(RPC_STATION), "clock": inner.get(RPC_CLOCK),
            "body": inner.get(RPC_BODY, b"")}


def answer_rpc(payload, station_id, clock_delta=5):
    """-> the same RPC with OUR station id and the clock advanced, or None if it is not one.

    The six bytes `nxldn-lab` patches by searching for a known identity are the high half of a
    varint-encoded station constant id, so the field is written rather than hunted for. Ours is the
    constant id the mesh gave us.

    `clock_delta` is nxldn-lab's 5 and is not measured here.
    """
    got = parse_rpc(payload)
    # Every field or nothing. The console's Pokemon rides a 40050 envelope with no base field at
    # all, and its echo of ours carries base 1, so a rebuild would call `varint(None)`. A reader
    # must not raise on a live run: "I cannot answer this" is a None.
    if got is None or any(got[k] is None for k in ("offset", "base", "clock")):
        return None
    return build_rpc(got["offset"], got["base"], station_id, got["clock"] + clock_delta,
                     got["body"])


def _read_fields(data):
    """-> {field number: value} for a flat protobuf message. Varints and byte fields only."""
    out, i = {}, 0
    while i < len(data):
        tag, i = _varint(data, i)
        number, wire = tag >> 3, tag & 7
        if wire == WIRE_VARINT:
            out[number], i = _varint(data, i)
        elif wire == WIRE_BYTES:
            size, i = _varint(data, i)
            out[number], i = data[i:i + size], i + size
        else:
            break
    return out


def _varint(data, i):
    value = shift = 0
    while i < len(data):
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, i
        shift += 7
    raise ValueError("truncated varint")


# --- the sync conversation ---------------------------------------------------------------------

# **NOT OURS AND NOT YET MEASURED.** This project has only ever seen the console's ping and the two
# block messages, because every run so far stopped at the trade snapshot. The rest of this table is
# `andyjusa/nxldn-lab`'s `SwordInitialSync`, read off a console-to-console capture they took, and
# reproduced here as protocol data with its source named. Its ids ARE real - 110, 120 and 130 are
# in the low table - and its bytes for id 97 and id 60000 agree with ours exactly, which is the
# only part of it we can check.
#
# Entries below that this console has not sent are a hypothesis about what comes next, not a
# description of it. Answering the whole set and logging every id the console sends after the
# snapshot settles the rest.
#
#   received payload            ->   what to send back, in order
SYNC_ANSWERS = {
    sync(SYNC_PING, PING):            (sync(SYNC_PING, PING_REPLY), sync(SYNC_PING, PING)),
    sync(SYNC_PING, PING_SYNCED):     (sync(SYNC_PING, PING_SYNCED), result()),
    sync(110, PING):                  (sync(110, PING),),
    sync(110, PING_REPLY):            (sync(110, PING_REPLY), sync(110, PING_SYNCED)),
    sync(120, PING):                  (sync(120, PING),),
    sync(120, PING_REPLY):            (sync(120, PING_REPLY), sync(120, PING_SYNCED)),
    sync(130, PING):                  (sync(130, PING), sync(130, PING_REPLY)),
    sync(130, PING_SYNCED):           (sync(130, PING_SYNCED),),
}


def answers_for(payload):
    """-> the payloads to send back for one received payload, or () for one we have no rule for.

    An empty answer is not a failure: most of what the console sends has no reply, and a run that
    logs the unanswered ones is how this table stops being someone else's.
    """
    return SYNC_ANSWERS.get(bytes(payload), ())


# --- 20030 IS A BoxSyncStateDataHolder, AND ITS FIELD 2 IS A COMMAND ENUM --------------------
#
# Two holders in `main`'s own schema have the same
# wire shape, and this project picked the wrong one:
#
#     PokemonTradeDataHolder   1 Pokemon{1 bytes serializePokemonParam}
#     BoxSyncStateDataHolder   1 BoxSendPokemon{1 bytes serializePokemonParam}
#                              2 BoxSyncStateCommand{1 int32 data}
#
# The console's offer, `3e4e0000 0adb02 0ad802 <344 bytes>`, fits both - field 1 of a field 1 - so
# the offer alone could never tell them apart. **Field 2 can.** `3e4e000012020801` is
# `boxSyncStateCommand{data: 1}`, and `nxldn-lab`'s capture of a real console-to-console trade has
# the host sending `data: 4` as well. A holder with only one field cannot carry either, so 20030 is
# the BOX one and the trade runs over a COMMAND ENUM this project has been sending one guess of.
#
# Offering the console its own Pokemon back, byte for byte out of its own save, aborts in the same
# place, so the record is not what it is waiting for. Between its offer and the teardown it sends
# nothing but acks: it is waiting for the state machine to move, and `data` is what moves it.
BOX_SEND_POKEMON, BOX_SYNC_STATE_COMMAND = 1, 2

# --- opening a content ---------------------------------------------------------------------------
#
# A content registered at offset N gets four ids: its registrar builds holders for 10000+N, 20000+N
# and 30000+N (the third has never been on the air here), and the framework's own start call mints
# 40000+N. `382700000a00` on port 0 is id 10040, the `ping` field of content 40's holder, sent
# unprompted as an opener the way the 40050 pair is.
#
# This console never sends 10040, 10050, 40040 or 40050, and never a box command, so every phase
# after the offer has to be opened from here. A 40050 pair opened properly, acknowledged ten seconds
# before the teardown, is ignored; 10040 is the other opener in the borrowed capture.
CONTENT_BASE_LOW = 10000              # the fourth id a content gets, and the one their client opens


def open_content(offset, which=PING):
    """-> `ping` on content `offset`'s 10000-base holder: `382700000a00` for offset 40."""
    return message(CONTENT_BASE_LOW + offset, field(which, b""))


def pokemon_offer(offset, pk8):
    """-> PokemonTradeDataHolder on content `offset`'s 10000-base holder: id 10050 for offset 50.

    Measured from the console's side: once the selection phase's pair is answered it offers its
    Pokemon as a 344-byte PK8 in field 5 of a 40050 envelope, then a status whose body ends `0100`.
    The answer to that status is our own Pokemon here (`4227` little-endian is 10050) on reliable
    port 0, not on the 20030 holder the offer phase uses. The offer phase and the selection phase
    each carry a Pokemon, on different messages and different windows.

    **AND SESSION 63 CONFIRMED THE SHAPE OUT OF THE BINARY.** Content 50's 10000-base holder parses
    its body with `0x010d9ee0`, which accepts tag 0x0a and nothing else, and the submessage's
    descriptor at `0x1bdb460` is `Pokemon { 1 bytes serializePokemonParam }`. This is the one
    message content 50's receive event can be fed. `docs/swsh.md`, "The whole path from the radio
    to content 50's receive event".
    """
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(CONTENT_BASE_LOW + offset, field(1, field(1, pk8)))


def pokemon_offer_high(offset, pk8):
    """-> PokemonTradeDataHolder on content `offset`'s 20000-base holder: id 20050 for offset 50.

    THE ONE SHAPE LEFT, and the symmetry says it. In the BOX phase the console sends its RPC pair
    on 40030 and its Pokemon on **20030** - the 20000-base holder of the same content - and that is
    the exchange that reaches the player. In the selection phase it sends its pair on 40050 and its
    own Pokemon on 40050, the sync layer's own envelope.

    Inert by construction. `0x010d81d0` returns silently when `[holder+0x168]` is null, and content
    50 installs a listener on its 10000-base holder (`0x010d50ac`) and its 30000-base one
    (`0x010d533c`) but never on the 20000-base one, so a message addressed here reaches nothing.

    A five-field Data on 40050 and the console's own three-field one, byte-identical in shape and
    length, are both acknowledged on every sequence and move nothing.
    """
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return message(RPC_BASES[1] + offset, field(1, field(1, pk8)))


# --- content 40, the confirmation ----------------------------------------------------------------

SYNC_SAVE_COMMAND = 1                 # SyncSaveDataHolder's only field
SYNC_COMMAND_DATA = 1                 # SyncCommand's only field

# The four the console itself sends, out of content 40's state machine `0x010dae70`, the only
# caller of the send `0x010db840(delegate, data, flag)`. Each send parks the machine in an idle
# state, so the four are a handshake: the partner's own command moves it on. The flag argument is
# always `data + 1` and is not part of the message.
SYNC_COMMANDS = {0: "0x010db308, out of state 1  -> state 2",
                 1: "0x010db0b0, out of state 3  -> state 4",
                 2: "0x010db0dc / 0x010db104, states 6 and 8 -> states 7 and 9",
                 3: "0x010db16c, out of state 12 -> state 0, and the machine is done"}

# The ladder between them is `0x010dbf40`, the state setter, the only writer of the machine's state
# field `delegate+0x5c` outside the machine itself and its constructor. It
# takes a u16 0..4, puts the machine in the state that sends the NEXT command, and returns without
# touching anything when the value is above 4. Its only caller is content 40's pump `0x010db3e0`,
# which passes the content's own phase `+0x17c` once that phase has caught up with the `+0x86` the
# last send recorded - so the machine leaves each idle state only when the phase advances:
#
#     phase 0 -> state 1            sends command 0, announcing phase 1
#     phase 1 -> state 3            sends command 1, announcing phase 2
#     phase 2 -> state 5 -> 6 or 8  sends command 2, announcing phase 3
#     phase 3 -> state 10 or 11 -> 12   sends command 3, announcing phase 4
#     phase 4 -> state 13           tears the holders down; nothing more is sent
#
# The ladder therefore needs all four commands, in order, and the fourth ends it.
# `docs/swsh.md`, "The ladder is a barrier, and every rung needs a command".
SYNC_LADDER = {0: 1, 1: 3, 2: 5, 3: 10, 4: 13}


def sync_announced_phase(data):
    """-> the phase the console records when it sends command `data`, which is `data + 1`.

    `0x010dae70` calls the send `0x010db840(delegate, data, flag)` with `flag == data + 1` at all
    five of its send sites, and `0x010dbab0` - the send that message is handed to - writes that flag
    to `content+0x86`. The pump commits the content to a phase (`0x010de310` writes `+0x84`) and
    climbs the ladder when `+0x17c` reaches `+0x86`, so the phase a command announces is the rung
    that unlocks the command after it.
    """
    return data + 1


def sync_step(phase, announced):
    """-> the four-byte step body `<u16 phase><u16 announced>` a content's element publishes.

    The two halves have independent publishers and neither one touches the other: `0x006d3980`
    writes the low half and carries the high half over from `sub+0x8a`, and `0x006d3690` - called
    from the pump - writes the high half and carries the low half over from `sub+0x88`. Both hand
    the result to `0x006d3860`, which stores it at `sub+0x88` and sends four bytes.

    **THIS PROJECT HAS NEVER PUT A VALUE OF ITS OWN IN EITHER HALF.** `answer_rpc` copies the body
    it was given, so every step we have ever sent carries the console's own two u16s under our
    ownerId. `bin/swsh_connect.py --confirm-phase N` is the first send that does not.
    """
    return struct.pack("<HH", phase & 0xFFFF, announced & 0xFFFF)


def answer_rpc_with_phase(payload, station_id, phase, clock_delta=5):
    """-> `answer_rpc`'s reply with the step body's PHASE half replaced, or None.

    The console's receive handler for this channel is four instructions - `if (len != 4) return;
    [sub+0x88] = body; [sub+0x78] = clock; sub+0x61 = 1` - so a four-byte `Data` whose (elementId,
    ownerId) matches a registered sub-element is the only thing besides the console's own publish
    that can change the value the phase is read from. Every answer this project has sent echoed the
    console's own halves back, which cannot move a value that is already what it says.

    Returns None rather than raising when the payload is not a four-byte RPC: a reader on a live
    run must not raise.
    """
    got = parse_rpc(payload)
    if got is None or any(got[k] is None for k in ("offset", "base", "clock")):
        return None
    step = parse_sync_step(got["body"])
    if step is None:
        return None
    return build_rpc(got["offset"], got["base"], station_id, got["clock"] + clock_delta,
                     sync_step(phase, step[1]))


def parse_sync_step(body):
    """-> `(phase, announced)` out of a content's four-byte step body, or None if it is not four.

    The four-byte body is two u16s and both halves are named in the image. The sub-element keeps
    its body at `sub+0x88`, and the publish `0x006d3980` rebuilds it as
    `<u16 newValue><u16 sub+0x8a>`: a new low half and the high half carried over unchanged, handed
    to `0x006d3860`, which is `0x010dbe20` one layer down. The low half is what the element then
    adopts as its phase (`element+0xac`, which IS `content+0x17c`, the element sitting at
    `content+0xd0`), and `0x006d3260` reads it back out of that same four bytes.

    So the low half is the phase and the high half is the phase the sender has announced, which is
    `data + 1` for the last command it sent. Three observed bodies:

        00000100   phase 0, announced 1     the cue: it had sent command 0
        01000100   phase 1, announced 1     our command let the phase catch up
        01000200   phase 1, announced 2     it committed and sent command 1

    `docs/swsh.md`, "The ladder is a barrier, and every rung needs a command".
    """
    if body is None or len(body) != 4:
        return None
    return struct.unpack("<HH", bytes(body))


def sync_command(offset, data):
    """-> `SyncSaveDataHolder{syncCommand{data: <int32>}}` on content `offset`'s 10000-base holder.

    The confirmation content takes one int32, not a Pokemon. Content 40's 10000-base holder parses
    its body
    with `0x010df6d0`, which accepts tag 0x0a and nothing else; the submessage's own parser
    `0x010debc0` accepts tag 0x08 and nothing else and stores the varint at `+0x14`. The game's own
    descriptors agree, which is two independent readings of one shape:

        sync_save_data_holder.proto   SyncSaveDataHolder { 1 SyncCommand syncCommand }
        sync_command.proto            SyncCommand        { 1 int32       data       }

    Both are `net_contents.trade.common.sync_save.protocol_buffers`. `SYNC_COMMANDS` says which
    values the console's own machine sends. The walk is `docs/swsh.md`, "The confirmation content
    takes a command, not a Pokemon".

    It is the same `holder{command{data}}` shape as `box_sync_state`, one content along - and that
    one is the shape that reached the player in the offer phase.
    """
    if data < 0:
        raise ValueError(f"{data} is not one of the commands the machine sends: {sorted(SYNC_COMMANDS)}")
    return message(CONTENT_BASE_LOW + offset,
                   field(SYNC_SAVE_COMMAND, field_varint(SYNC_COMMAND_DATA, data)))


def parse_sync_command(payload):
    """-> the command int on a content's 10000-base holder, or None when the payload is not one.

    The mirror of `parse_box_command`, and it is what reads the console's own confirmation traffic
    back out of a capture. Any content's 10000-base id is accepted, not just 10040: the shape is
    the holder's, and which content sent it is the id the caller already has.
    """
    got = _maybe_parse(payload)
    if got is None or got[0] not in {CONTENT_BASE_LOW + o for o in CONTENT_HOLDERS}:
        return None
    inner = _read_fields(got[1]).get(SYNC_SAVE_COMMAND)
    if not isinstance(inner, bytes):
        return None
    value = _read_fields(inner).get(SYNC_COMMAND_DATA)
    return value if isinstance(value, int) else None


SELECTION_SWEEP_NOTE = """The selection-offer shapes that remain, swept together.

Every one of these is acknowledged at the transport and moves nothing: the holder on 10050, a
five-field Data on 40050 with our ownerId, the console's own three-field Data on 40050
(byte-identical in shape and length), the holder on 20050, and the 120 pingSynced the borrowed
trace calls the confirmation's opener (the console uses 97, 110 and 130 all run and never 120).

What is left comes from the binary rather than from another project's capture. Each content's
registrar builds THREE holders - 10000+off, 20000+off and 30000+off - and the 30000 family has
never been on the air here in either direction. And the pair's two members carry elementId 10000
and 20000, so if those are the two sides' slots, our Pokemon may belong on the one we have not
used.

This is deliberately NOT one variable. The player is the scarce resource and the remaining space is
two shapes; a run that moves anything at all is worth a bisect afterwards."""


def selection_sweep(offset, pk8):
    """-> the shapes left, in order: Data on elementId 10000, then the 30000-base holder."""
    pk8 = bytes(pk8)
    if len(pk8) not in (0x148, 0x158):
        raise ValueError(f"{len(pk8)} bytes is not a PK8 (0x148 stored or 0x158 party)")
    return (build_rpc(offset, RPC_BASES[0], None, 0, pk8),
            message(30000 + offset, field(1, field(1, pk8))))


def box_sync_state(command):
    """-> `BoxSyncStateDataHolder{boxSyncStateCommand{data: command}}` on the trade holder.

    `trade_ready()` is this with command 1 under an older name and an older reading.
    """
    return message(POKEMON_TRADE,
                   field(BOX_SYNC_STATE_COMMAND, field_varint(1, command)))


def parse_box_command(payload):
    """-> the command int on the trade holder, or None when the payload is not one."""
    got = _maybe_parse(payload)
    if got is None or got[0] != POKEMON_TRADE:
        return None
    outer = _read_fields(got[1])
    inner = outer.get(BOX_SYNC_STATE_COMMAND)
    if not isinstance(inner, bytes):
        return None
    value = _read_fields(inner).get(1)
    return value if isinstance(value, int) else None


def trade_ready(ready=True):
    """`imReady{isReady:true}` on the TRADE holder, 20030 - the same shape as the block one.

    Not measured from this console: the only thing it ever puts on 20030 is the offer itself.
    `nxldn-lab`'s client waits for exactly these bytes before it sends its own Pokemon, then echoes
    them back, so either the console wants them from us or the roles in that capture are not ours.

    It is the same shape that releases the snapshot (`imReady` on the block holder) one holder
    further along.
    """
    return message(POKEMON_TRADE, field(IM_READY, field_varint(1, 1 if ready else 0)))


def _maybe_parse(payload):
    """-> (id, body), or None for anything too short to be one.

    A reader on a live run must not raise. At the confirmation prompt the console sends a
    three-byte message; raising on it kills the run mid-trade and the console reports the
    communication as interrupted.
    """
    payload = bytes(payload)
    if len(payload) < 4:
        return None
    return struct.unpack_from("<I", payload, 0)[0], payload[4:]


def offered_pokemon(payload):
    """-> the 0x158 PK8 inside a trade offer, or None when this is not one.

    The console sends `PokemonTradeDataHolder{pokemon{serializePokemonParam}}` on id 20030 holding
    a 344-byte party-form record, which decodes to the Pokemon the player picked on screen.
    Rebuilding that message from the record it carried gives the console's bytes back exactly.
    """
    got = _maybe_parse(payload)
    if got is None or got[0] != POKEMON_TRADE:
        return None
    _, body = got
    outer = _read_fields(body)
    if not isinstance(outer.get(1), bytes):
        return None
    inner = _read_fields(outer[1])
    pk8 = inner.get(1)
    return pk8 if isinstance(pk8, bytes) and len(pk8) in (0x148, 0x158) else None


def answers_for_offer(payload, our_pk8):
    """-> our own offer, as a one-tuple, when the console has just made one."""
    if our_pk8 is None or offered_pokemon(payload) is None:
        return ()
    return (pokemon_trade(our_pk8),)


def answers_for_rpc(payload, station_id, clock_delta=5):
    """-> the reply to a trade RPC as a one-tuple, or () when the payload is not one.

    Kept in the same shape as `answers_for` so a caller can treat both the same way.
    """
    answer = answer_rpc(payload, station_id, clock_delta)
    return (answer,) if answer is not None else ()


def next_answer(said, queue=(), station_id=None, clock_delta=5, offer_pk8=None):
    """-> (what to send now, the queue after it). The table where there is a rule, the mirror else.

    Echoing the console's own last payload back per protocol is what reaches the trade snapshot,
    and `SYNC_ANSWERS` has no rule for some of what that path carries (`pingReply` and `result{}`
    on 0x7C). The table alone would fall silent on those, so a rule replaces the echo where it
    exists and the echo stands everywhere else.

    A rule may be more than one payload; the queue carries the rest so they go out in order, one
    per sequence, because a window sends one message at a time.
    """
    queue = list(queue)
    if not queue:
        queue = list(answers_for(said))
    if not queue:
        # An offer is answered with an offer: echoing hands the console back the Pokemon it just
        # offered, under its own trainer's name.
        queue = list(answers_for_offer(said, offer_pk8))
    if not queue and station_id is not None:
        # A trade RPC is answered by rebuilding it: mirroring sends the console its own station id
        # back, which is the one field that has to change.
        queue = list(answers_for_rpc(said, station_id, clock_delta))
    if queue:
        return queue[0], queue[1:]
    return said, []


def unanswered(payloads):
    """-> the distinct payloads a run saw that nothing here answers. The next run's shopping list."""
    return sorted({bytes(p) for p in payloads if not answers_for(p)})
