"""Protocol 0x84, `nn::pia::transport::ReliableBroadcastProtocol` - the version-4 bulk channel.

NOT protocol 0x80. `reliable4.py` carries the warning at length: `BroadcastReliableProtocol` is
0x80 and is the ack window, and the similarly named `ReliableBroadcastProtocol` is this. Confusing
them took two sessions of reading.

This is where a Sword sends its 3456-byte trade snapshot, and every field below is read off our own
console's own messages rather than from any other implementation:

    11 000000 0000 ffff  00000d80 057c 0005 00000000     control, 20 bytes
    12 000000 0001 ffff  00000000 <1404 bytes>           fragment 0
    12 000000 0005 ffff  00000002 <157 bytes, deflated>  fragment 2

    0x00  u8    kind: 0x11 control, 0x12 data
    0x01  3     zero
    0x04  u16be sequence, ours, counting up across BOTH kinds on this port
    0x06  u16be the peer's sequence we have seen, 0xFFFF before any
    0x08        control: u32be total size, u16be chunk size, u16be 5, four zero bytes
                data:    u32be fragment index, then the fragment body

**THE BODY MAY BE DEFLATED AND THE HEADER NEVER IS.** Pia's message flag 0x10 - version 4's zlib
flag, the same one that hid protocol 0x80 for two sessions - says the bytes AFTER the twelve-byte
prefix are a zlib stream. Concatenating a compressed fragment raw loses 491 bytes of
the snapshot without noticing, which is why `swsh.trade_payload.reassemble` refuses a total it does
not recognise.

`kwsch/PokePiaSWSH` splits at the same twelve bytes and `andyjusa/nxldn-lab` builds the same eight
byte header; where they and our console differ is the CHUNK SIZE, 1244 against our console's 1404,
so that is a sender's choice and not a constant of the protocol.
"""
import struct
import zlib

PROTOCOL = 0x84
HEADER_SIZE = 8
PREFIX_SIZE = 12                      # header + the fragment index: never compressed
KIND_CONTROL = 0x11
KIND_DATA = 0x12
# THE THREE KINDS SESSION 58 AND 59 NEVER SAW, because nothing here ever acked this protocol and
# the console therefore never got past retransmitting. Read off `andyjusa/nxldn-lab`'s receiver.
KIND_ACK = 0x21                       # base index + a bitmask of what arrived out of order
KIND_DONE = 0x19                      # a transfer is complete
KIND_DONE_ACK = 0x28                  # and its answer
ACK_SIZE = HEADER_SIZE + 12
CONTROL_SIZE = 20
NO_PEER_SEQUENCE = 0xFFFF
CONTROL_UNKNOWN = 5                   # the halfword at 0x0E, 5 in every message we have seen
CHUNK_SIZE = 1404                     # what OUR console uses; nxldn-lab's sender picks 1244

# The console's own deflate settings, from nxldn-lab's sender. A window of 12 bits and level 5 are
# not arbitrary: an inflater accepts anything, but a 15-bit window from us would be a difference
# from what the console sends, and this project changes one thing at a time.
COMPRESS_LAST = "last"                # deflate only the final fragment, as our console does
COMPRESS_AUTO = "auto"                # deflate whenever it is smaller, as nxldn-lab's sender does

_WBITS = 12
_LEVEL = 5
_MEM_LEVEL = 4


def build_header(kind, sequence, peer_sequence=NO_PEER_SEQUENCE):
    return struct.pack(">B3xHH", kind, sequence & 0xFFFF, peer_sequence & 0xFFFF)


def build_control(sequence, total, chunk_size=CHUNK_SIZE, peer_sequence=NO_PEER_SEQUENCE):
    """-> the 20-byte control message that announces a transfer's size."""
    return (build_header(KIND_CONTROL, sequence, peer_sequence)
            + struct.pack(">IHH4x", total, chunk_size, CONTROL_UNKNOWN))


def deflate(body):
    """-> (bytes, compressed?). Deflated only when that is actually smaller, as the console does."""
    c = zlib.compressobj(_LEVEL, zlib.DEFLATED, _WBITS, _MEM_LEVEL)
    packed = c.compress(bytes(body)) + c.flush(zlib.Z_SYNC_FLUSH) + c.flush(zlib.Z_FINISH)
    return (packed, True) if len(packed) < len(body) else (bytes(body), False)


def build_fragment(sequence, index, body, peer_sequence=NO_PEER_SEQUENCE, compress=True):
    """-> (payload, compressed?). The caller sets Pia's 0x10 message flag when compressed is True."""
    packed, done = deflate(body) if compress else (bytes(body), False)
    return (build_header(KIND_DATA, sequence, peer_sequence)
            + struct.pack(">I", index) + packed), done


def split(payload, chunk_size=CHUNK_SIZE):
    return [bytes(payload[i:i + chunk_size]) for i in range(0, len(payload), chunk_size)]


def parse(message):
    """-> dict. One 0x84 message, header split from body; a data body is NOT inflated here.

    Inflating belongs to the caller because only Pia's message flag says whether it should happen,
    and a body that merely looks like a zlib stream is not a reason to treat it as one.
    """
    if len(message) < HEADER_SIZE:
        raise ValueError(f"a 0x84 message is at least {HEADER_SIZE} bytes, got {len(message)}")
    kind = message[0]
    sequence, peer = struct.unpack_from(">HH", message, 4)
    out = {"kind": kind, "sequence": sequence, "peer_sequence": peer,
           "is_control": kind == KIND_CONTROL, "is_data": kind == KIND_DATA}
    if kind == KIND_CONTROL:
        if len(message) < CONTROL_SIZE:
            raise ValueError(f"a control message is {CONTROL_SIZE} bytes, got {len(message)}")
        total, chunk, unknown = struct.unpack_from(">IHH", message, 8)
        out.update(total=total, chunk_size=chunk, unknown=unknown)
    elif kind == KIND_DATA:
        if len(message) < PREFIX_SIZE:
            raise ValueError(f"a data message is at least {PREFIX_SIZE} bytes, got {len(message)}")
        out.update(index=struct.unpack_from(">I", message, 8)[0], body=message[PREFIX_SIZE:])
    elif kind == KIND_ACK:
        if len(message) < ACK_SIZE:
            raise ValueError(f"an ack is {ACK_SIZE} bytes, got {len(message)}")
        base, mask = struct.unpack_from(">IQ", message, 8)
        out.update(base=base, mask=mask)
    elif kind in (KIND_DONE, KIND_DONE_ACK):
        pass
    else:
        raise ValueError(f"kind {kind:#04x} is none of control ({KIND_CONTROL:#04x}), "
                         f"data ({KIND_DATA:#04x}), ack ({KIND_ACK:#04x}), done "
                         f"({KIND_DONE:#04x}) or done-ack ({KIND_DONE_ACK:#04x})")
    return out


def build_ack(sequence, base, mask=0, peer_sequence=NO_PEER_SEQUENCE):
    """-> the 0x21 ack: how far the transfer is contiguous, and a bitmask of what came early.

    `base` is the first index NOT yet received, so it is a count of the contiguous run from zero,
    and `mask` bit n is index `base + 1 + n`. A receiver that has 0 and 2 acks base 1, mask 1.
    """
    return (build_header(KIND_ACK, sequence, peer_sequence)
            + struct.pack(">IQ", base, mask))


def build_done(sequence, peer_sequence=NO_PEER_SEQUENCE):
    return build_header(KIND_DONE, sequence, peer_sequence)


def build_done_ack(sequence, peer_sequence=NO_PEER_SEQUENCE):
    return build_header(KIND_DONE_ACK, sequence, peer_sequence)


def ack_fields(indexes):
    """-> (base, mask) for a set of received fragment indexes."""
    received = set(indexes)
    base = 0
    while base in received:
        base += 1
    mask = 0
    for index in received:
        if index > base:
            mask |= 1 << (index - base - 1)
    return base, mask


class Sender:
    """One port's outgoing side: the sequence counter, and the messages of one transfer.

    The console counts a single sequence across control and data alike: control at 0,
    fragment 0 at 1 and fragment 2 at 5 - so the counter lives here rather than in the caller, and
    the gaps are the retransmits it sends in between.
    """

    def __init__(self, chunk_size=CHUNK_SIZE):
        self.sequence = 0
        self.peer_sequence = NO_PEER_SEQUENCE
        self.chunk_size = chunk_size

    def _next(self):
        sequence, self.sequence = self.sequence, (self.sequence + 1) & 0xFFFF
        return sequence

    def saw(self, sequence):
        """Record the peer's sequence, which every message of ours then echoes back."""
        self.peer_sequence = sequence & 0xFFFF

    def transfer(self, payload, compress=COMPRESS_LAST):
        """-> [(payload, compressed?), ...]: the control message and then every fragment, in order.

        The default matches what the console does, which is not "compress when it helps". It
        sent fragments 0 and 1 plain at the full 1404 bytes and deflated only the short last one -
        and fragment 1's own bytes deflate to 776, so the console left half of it on the table by
        choice. Whatever its rule is, "smaller wins" is not it, and a sender that compressed a
        full-size fragment would differ from the console in a way no run had asked about.

        `COMPRESS_AUTO` is that other policy, kept because nxldn-lab's sender uses it and reaches a
        trade; `False` sends everything plain. One of these per run, never two.
        """
        chunks = split(payload, self.chunk_size)
        out = [(build_control(self._next(), len(payload), self.chunk_size, self.peer_sequence),
                False)]
        for index, chunk in enumerate(chunks):
            if compress == COMPRESS_LAST:
                allow = index == len(chunks) - 1
            else:
                allow = bool(compress)
            out.append(build_fragment(self._next(), index, chunk, self.peer_sequence, allow))
        return out


class Receiver:
    """The incoming side of one port: what has arrived, and the ack that says so.

    An unacknowledged 0x84 repeats: 15460 and 19142 messages of the same snapshot in two runs,
    because the console retransmits until a receiver
    tells it what it has. Every other window here behaves the same way and every one of them had to
    be answered before the layer above it would move - the mesh's own reliable window took the
    session down in four seconds when it is left unacked.
    """

    def __init__(self):
        self.indexes = set()
        self.total = None
        self.chunk_size = None
        self.sequence = 0
        self.peer_sequence = NO_PEER_SEQUENCE
        self.fragments = {}

    def _next(self):
        sequence, self.sequence = self.sequence, (self.sequence + 1) & 0xFFFF
        return sequence

    def feed(self, message, body=None):
        """-> the replies to send for one received 0x84 message, in order.

        `body` is the fragment already inflated when Pia's 0x10 flag was set; the caller owns that
        decision because only the flag decides it.
        """
        got = parse(message)
        self.peer_sequence = got["sequence"]
        if got["is_control"]:
            self.total, self.chunk_size = got["total"], got["chunk_size"]
            return []
        if got["kind"] == KIND_DATA:
            self.indexes.add(got["index"])
            self.fragments[got["index"]] = body if body is not None else got["body"]
            base, mask = ack_fields(self.indexes)
            return [build_ack(self._next(), base, mask, self.peer_sequence)]
        if got["kind"] == KIND_DONE:
            return [build_done_ack(self._next(), self.peer_sequence)]
        return []

    def complete(self):
        """-> True when every fragment the control message promised has arrived."""
        if self.total is None or self.chunk_size is None:
            return False
        expected = -(-self.total // self.chunk_size)
        return self.indexes >= set(range(expected))

    def payload(self):
        """-> the reassembled bytes, or None until the transfer is complete."""
        if not self.complete():
            return None
        return b"".join(self.fragments[i] for i in sorted(self.fragments))
