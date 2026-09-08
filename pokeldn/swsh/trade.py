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
POKEMON_TRADE = 40030                 # DEDUCED, not confirmed - see SYNC_ANSWERS

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


def next_answer(said, queue=()):
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
    if queue:
        return queue[0], queue[1:]
    return said, []


def unanswered(payloads):
    """-> the distinct payloads a run saw that nothing here answers. The next run's shopping list."""
    return sorted({bytes(p) for p in payloads if not answers_for(p)})
