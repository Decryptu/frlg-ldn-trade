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

WHAT THIS PROJECT HAS MEASURED, from sw70's own capture (`scratchpad/sw_app_payloads.py`): id 97
with all three of its fields, and id 60000 with `result{}` on 0x7C and `imReady{isReady:true}` on
0x80. Those five payloads and no others. Everything past the trade snapshot is in `SYNC_ANSWERS`
and is NOT ours - see its comment.
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
POKEMON_TRADE = 20030                 # MEASURED at sw76: the console offered its own Pokemon here
                                      # (session 59 first wrote 40030, which is the RPC envelope)

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
    """`result{}` on the block holder - what the console asks for on 0x7C. Measured, sw70."""
    return message(BLOCK, field(RESULT, b""))


def im_ready(ready=True):
    """`imReady{isReady:true}` - what the console asks for on 0x80. Measured, sw68 and sw70."""
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


# --- the trade RPC envelope, MEASURED at sw75 -------------------------------------------------

# sw75 is where the trade screen opened and the console started talking, and these are its own
# bytes. Message id 40030 carries ONE nested field whose five members decode without a guess:
#
#     id 40030          = 40000 + 30, and field 1 below is that same 30
#       1  offset       30
#       2  base         10000 in one member of the pair, 20000 in the other
#       3  station id   THE SENDER'S, and it is byte-identical to the `host_constant` our own
#                       seat record holds - which is what turns a 6-byte find-and-replace into a
#                       field we can simply write
#       4  clock        a counter that advances between messages
#       5  bytes(4)     00000000 for the 10000 member, 000018fc for the 20000 one
#
# **AND THIS IS WHERE 20030 COMES FROM.** `swsh_msgid.py` found that the high ids are a base plus
# an offset and that no literal 20030 exists anywhere in the image. It does not need to: the base
# and the offset travel as separate fields of this envelope, and 20000 + 30 is assembled from them.
# The deduction session 59 wrote down is now a measurement, and its mechanism is on the wire.
RPC_ENVELOPE_BASE = 40000             # the envelope's own id is this plus the same offset
RPC_ENVELOPE = 40030                  # the only one the console has ever sent us: offset 30
RPC_OFFSET, RPC_BASE, RPC_STATION, RPC_CLOCK, RPC_BODY = 1, 2, 3, 4, 5
RPC_BASES = (10000, 20000)            # the pair the console sends, and the pair it expects back

# THE OFFSET IS THE PROCEDURE, and the envelope's id carries it twice - once as `40000 + offset`
# and once as field 1. 30 is the offer, the only one measured from our own console. 50 and 40 are
# `andyjusa/nxldn-lab`'s selection and confirmation, and what makes them more than borrowed
# constants is the dispatcher at main.bin `0x013b2c00`: a message id is banded and INDEXED, and an
# id in 40001..60000 indexes its container at `id - 40001`. So 40050 and 40040 are legal ids in
# the same band as the 40030 the console does send, at indexes 49 and 39.
OFFER_OFFSET = 30                     # MEASURED, sw75-sw83
SELECTION_OFFSET = 50                 # nxldn-lab's, structurally consistent, NOT measured here
CONFIRMATION_OFFSET = 40              # the same

# WHICH CONTENT IS WHICH, and it reframes what this project has been sending. `main` ships three
# trade holders and the registry has three trade contents, so they pair off - and each pairing is
# forced by something on the wire rather than chosen:
#
#   content 30  BoxSyncStateDataHolder   1 boxSendPokemon, 2 boxSyncStateCommand
#               MEASURED. `3e4e000012020801` is a FIELD 2 on 20030 and only this holder has one.
#   content 50  PokemonTradeDataHolder   1 Pokemon{1 serializePokemonParam}
#               nxldn-lab's `decode_rpc_pokemon_offer` pulls a 344-byte PK8 out of FIELD 5 of a
#               40050 envelope, so content 50 is the one that carries a Pokemon.
#   content 40  SyncSaveDataHolder       1 syncCommand{int32 data}
#               what is left, and a save sync is what a finished trade would run.
#
# **SO 20030 IS THE BOX EXCHANGE - SHOWING EACH OTHER A POKEMON - AND NOT THE TRADE.** Everything
# sw75 onward has done is content 30. The transfer itself is content 50, which this project has
# never spoken with a Pokemon in it, and the save sync is content 40. That is what the console
# runs out of after the accept.
CONTENT_HOLDERS = {OFFER_OFFSET: "BoxSyncStateDataHolder",
                   SELECTION_OFFSET: "PokemonTradeDataHolder",
                   CONFIRMATION_OFFSET: "SyncSaveDataHolder"}
RPC_POKEMON_FIELD = 5                 # where a PK8 rides inside the envelope's inner message

# THE TWO BODIES ARE THE CONSOLE'S OWN. Its 40030 pair carries `00000000` against base 10000 and
# `000018fc` against base 20000, and nxldn-lab's 40050 pair carries exactly the same two - so the
# pair's shape is the envelope's, not the procedure's, and building a 40050 is writing one field.
RPC_PAIR_BODIES = (b"\x00\x00\x00\x00", bytes.fromhex("000018fc"))


def build_rpc(offset, base, station_id, clock, body=b"\x00\x00\x00\x00", envelope=None):
    """-> one member of a trade RPC pair, as the console builds its own.

    `envelope` defaults to `40000 + offset`, which is what makes the offer envelope 40030 and the
    selection one 40050; pass it only to reproduce bytes that disagree with that rule.
    """
    inner = (field_varint(RPC_OFFSET, offset) + field_varint(RPC_BASE, base)
             + field_varint(RPC_STATION, station_id) + field_varint(RPC_CLOCK, clock)
             + field(RPC_BODY, body))
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
    if got is None or got[0] != RPC_ENVELOPE:
        return None
    _, body = got
    outer = _read_fields(body)
    if not isinstance(outer.get(1), bytes):
        return None
    inner = _read_fields(outer[1])
    return {"offset": inner.get(RPC_OFFSET), "base": inner.get(RPC_BASE),
            "station_id": inner.get(RPC_STATION), "clock": inner.get(RPC_CLOCK),
            "body": inner.get(RPC_BODY, b"")}


def answer_rpc(payload, station_id, clock_delta=5):
    """-> the same RPC with OUR station id and the clock advanced, or None if it is not one.

    THE STATION ID IS THE WHOLE POINT AND IT IS NOT A PATCH. `nxldn-lab` replaces six bytes it
    found by searching for a known identity, because it works from a capture; sw75 says those six
    bytes are the high half of a varint-encoded station constant id, so the field is written rather
    than hunted for. Ours is the constant id the mesh already gave us.

    `clock_delta` is nxldn-lab's 5 and is NOT measured. It is the one number here that is still
    somebody else's, and the run that answers an RPC is what tests it.
    """
    got = parse_rpc(payload)
    if got is None or got["clock"] is None:
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
# THE MEASUREMENT THAT SETTLES THE REST COSTS NO EXTRA ASSOCIATION: answer the whole set on the next
# run and log every id the console sends after the snapshot. Until a run does that, treat an entry
# below as a hypothesis about what comes next, and NOT as a description of our console.
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
# Session 60, and it reframes the whole trade. Two holders in `main`'s own schema have the SAME
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
# WHAT THAT EXPLAINS. sw90 offered the console its own Pokemon back, byte for byte out of its own
# save, and it aborted at the same place - so the record was never the problem. Between its offer
# and the teardown it sends nothing but acks: it is not waiting to be told something in a message
# it names, it is waiting for the state machine to move, and `data` is what moves it.
BOX_SEND_POKEMON, BOX_SYNC_STATE_COMMAND = 1, 2

# --- OPENING A CONTENT, WHICH IS WHAT `nxldn-lab`'s CLIENT DOES AND OURS NEVER HAS -------------
#
# A content registered at offset N gets FOUR ids - 10000+N, 20000+N, 40000+N and 60000+N - and this
# project has only ever spoken the 20000 and 40000 ones. Their client opens the confirmation phase
# by sending `382700000a00` on port 0, and that is id 10040: **10000 + 40**, the `ping` field of
# content 40's holder. It sends it unprompted, as an opener, exactly as it sends the 40050 pair.
#
# Our console never sends 10040, 10050, 40040 or 40050, and it never sends a box command either -
# so every phase after the offer is one nobody has opened. sw93 opened 40050 properly (acked, ten
# seconds before the teardown) and the console ignored it; 10040 is the other opener in their
# capture and the one this has never tried.
CONTENT_BASE_LOW = 10000              # the fourth id a content gets, and the one their client opens


def open_content(offset, which=PING):
    """-> `ping` on content `offset`'s 10000-base holder: `382700000a00` for offset 40."""
    return message(CONTENT_BASE_LOW + offset, field(which, b""))


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

    NOT MEASURED FROM OUR CONSOLE, and the reasoning is worth writing down. `nxldn-lab`'s client
    waits for exactly these bytes before it sends its own Pokemon, and then echoes them back. Ours
    never sends them: across sw76, sw79 and sw80 the only thing the console ever put on 20030 was
    the offer itself. So either it is waiting for this from us, or the roles in their capture are
    not ours.

    It is the same shape that unlocked the snapshot - `imReady` on the block holder - one holder
    further along, which is the reason to try it before anything more elaborate.
    """
    return message(POKEMON_TRADE, field(IM_READY, field_varint(1, 1 if ready else 0)))


def _maybe_parse(payload):
    """-> (id, body), or None for anything too short to be one.

    **A READER ON A LIVE RUN MUST NOT RAISE.** sw81 reached the confirmation prompt - the player
    saw our Pokemon and pressed accept - and then the console sent a THREE-BYTE message, this
    module raised, and the run died mid-trade. The console reported the communication as
    interrupted, which is exactly what had happened: we were the one who left.
    """
    payload = bytes(payload)
    if len(payload) < 4:
        return None
    return struct.unpack_from("<I", payload, 0)[0], payload[4:]


def offered_pokemon(payload):
    """-> the 0x158 PK8 inside a trade offer, or None when this is not one.

    sw76: the console sent `PokemonTradeDataHolder{pokemon{serializePokemonParam}}` on id 20030
    holding a 344-byte party-form record, and it decoded to the Pokemon the player had just picked
    on screen - `Pomdrapi`, level 18, their own trainer name and ids. Rebuilding that message from
    the record it carried gives the console's bytes back exactly, which is what says the framing is
    read and not merely guessed.
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

    THE MIRROR IS THE PROVEN POLICY AND THIS DOES NOT REPLACE IT. sw68 and sw70 reached the trade
    snapshot by echoing the console's own last payload back per protocol, and `SYNC_ANSWERS` has a
    rule for only some of what they saw - `pingReply` and `result{}` on 0x7C have none. A run that
    used the table alone would fall silent on those two and lose the path that works, so a rule
    REPLACES the echo where it exists and the echo stands everywhere else.

    A rule may be more than one payload; the queue carries the rest so they go out in order, one
    per sequence, because a window sends one message at a time.
    """
    queue = list(queue)
    if not queue:
        queue = list(answers_for(said))
    if not queue:
        # AN OFFER IS ANSWERED WITH AN OFFER. Echoing this one would hand the console back the very
        # Pokemon it just offered us, under its own trainer's name.
        queue = list(answers_for_offer(said, offer_pk8))
    if not queue and station_id is not None:
        # A TRADE RPC IS ANSWERED BY REBUILDING IT, not by echoing it. Mirroring one would send the
        # console its own station id back, which is the one field that has to change.
        queue = list(answers_for_rpc(said, station_id, clock_delta))
    if queue:
        return queue[0], queue[1:]
    return said, []


def unanswered(payloads):
    """-> the distinct payloads a run saw that nothing here answers. The next run's shopping list."""
    return sorted({bytes(p) for p in payloads if not answers_for(p)})
