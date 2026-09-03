"""FRLG AgbRfu 14-byte command slot [ChildBuildSendCmd, link_rfu_2.c:944-962]. The rolling tag (childSendCmdId, 0..7) lives
in bits 5-7 of word0's low byte and advances on every NON-idle slot; the host hard-errors after >4 bad ids
[link_rfu_2.c:884-888]. Idle = 14 zero bytes and does NOT advance the tag.
"""

COMM_SLOT_LENGTH = 14
RFUCMD_MASK = 0xFF00
FRAG_INDEX_MASK = 0x1F

IDLE = 0x0000
SEND_BLOCK_INIT = 0x8800
SEND_BLOCK = 0x8900
SEND_HELD_KEYS = 0xBE00
READY_EXIT_STANDBY = 0x6600
READY_CLOSE_LINK = 0x5F00
SEND_BLOCK_REQ = 0xA100
SEND_PLAYER_IDS = 0x7700
SEND_PACKET = 0x2F00
DISCONNECT = 0xED00

RFUCMD_NAMES = {
    0x0000: "IDLE", 0x2F00: "SEND_PACKET", 0x5F00: "READY_CLOSE_LINK",
    0x6600: "READY_EXIT_STANDBY", 0x7700: "SEND_PLAYER_IDS", 0x7800: "SEND_PLAYER_IDS_NEW",
    0x8800: "SEND_BLOCK_INIT", 0x8900: "SEND_BLOCK", 0xA100: "SEND_BLOCK_REQ",
    0xBE00: "SEND_HELD_KEYS", 0xED00: "DISCONNECT", 0xEE00: "DISCONNECT_PARENT",
}

OWNER_FLAG = 0x80

# librfu LLSF command states [include/librfu.h:249-253].
LCOM_NULL, LCOM_NI_START, LCOM_NI, LCOM_NI_END, LCOM_UNI = 0, 1, 2, 3, 4
# CHILD LLSF [llsf_struct[MODE_CHILD], librfu_rfu.c:79-94]: a 2-byte LE word, state<<10 ack<<9 n<<7 phase<<5 | size.
CHILD_LLSF_STATE_SHIFT, CHILD_LLSF_ACK_SHIFT = 10, 9
CHILD_LLSF_N_SHIFT, CHILD_LLSF_PHASE_SHIFT = 7, 5
# PARENT LLSF [llsf_struct[MODE_PARENT], librfu_rfu.c:95-110]: 3 bytes LE, state<<14 bmSlot<<18 ack<<13 n<<11 phase<<9 | size&0x7f.
PARENT_LLSF_STATE_SHIFT = 14


def uni_slot(cmd14):
    """2-byte LLSF (LCOM_UNI<<10 | size) then the command [rfu_STC_UNI_constructLLSF, librfu_rfu.c:1872]."""
    cmd = bytes(cmd14)
    llsf = (LCOM_UNI << CHILD_LLSF_STATE_SHIFT) | len(cmd)
    return llsf.to_bytes(2, "little") + cmd


PARENT_LLSF_ACK_SHIFT, PARENT_LLSF_N_SHIFT = 13, 11
PARENT_LLSF_PHASE_SHIFT, PARENT_LLSF_BMSLOT_SHIFT = 9, 18
PARENT_FRAME_SIZE = 3
COMM_TABLE_LENGTH = 70


def _parent_llsf(state, size, *, ack=0, n=0, phase=0, bm_slot=1):
    frame = ((state & 0xF) << PARENT_LLSF_STATE_SHIFT) | ((ack & 1) << PARENT_LLSF_ACK_SHIFT) \
        | ((n & 3) << PARENT_LLSF_N_SHIFT) | ((phase & 3) << PARENT_LLSF_PHASE_SHIFT) \
        | ((bm_slot & 0xF) << PARENT_LLSF_BMSLOT_SHIFT) | (size & 0x7F)
    return (frame & 0xFFFFFF).to_bytes(PARENT_FRAME_SIZE, "little")


def parent_uni_slot(recv_cmds, bm_slot=1):
    """The 70-byte gRecvCmds table in a PARENT UNI sub-frame [rfu_UNI_setSendData(acceptSlot, gRfu.recvCmds, 70)];
    broadcast every frame while linked.
    """
    payload = bytes(recv_cmds).ljust(COMM_TABLE_LENGTH, b"\x00")[:COMM_TABLE_LENGTH]
    return _parent_llsf(LCOM_UNI, len(payload), bm_slot=bm_slot) + payload


def parent_ni_llsf(state, n, phase, ack, size, bm_slot=1):
    return _parent_llsf(state, size, ack=ack, n=n, phase=phase, bm_slot=bm_slot)


def pack_recv_cmds(rows):
    """Row 0 = the parent's own gSendCmd, row 1 = the child; rows 2-4 zero for a 2-player link [ReadAllPlayerRecvCmds,
    link_rfu_2.c:743].
    """
    out = bytearray(COMM_TABLE_LENGTH)
    for i, row in enumerate(rows[:5]):
        r = bytes(row)[:COMM_SLOT_LENGTH]
        out[i * COMM_SLOT_LENGTH:i * COMM_SLOT_LENGTH + len(r)] = r
    return bytes(out)


def child_ni_llsf(state, n, phase, ack, size):
    """[rfu_STC_NI_constructLLSF, librfu_rfu.c:1843]"""
    frame = ((state & 0xF) << CHILD_LLSF_STATE_SHIFT) | ((ack & 1) << CHILD_LLSF_ACK_SHIFT) \
        | ((n & 3) << CHILD_LLSF_N_SHIFT) | ((phase & 3) << CHILD_LLSF_PHASE_SHIFT) | (size & 0x1F)
    return frame.to_bytes(2, "little")


def parse_llsf_child(slot):
    f = int.from_bytes(slot[0:2], "little")
    return {"state": (f >> CHILD_LLSF_STATE_SHIFT) & 0xF, "ack": (f >> CHILD_LLSF_ACK_SHIFT) & 1,
            "n": (f >> CHILD_LLSF_N_SHIFT) & 3, "phase": (f >> CHILD_LLSF_PHASE_SHIFT) & 3,
            "size": f & 0x1F}


def _words_to_slot(words):
    w = list(words) + [0] * (7 - len(words))
    return b"".join((x & 0xFFFF).to_bytes(2, "little") for x in w[:7])


def idle_slot():
    return b"\x00" * COMM_SLOT_LENGTH


def serialize(words):
    """WITHOUT a rolling tag (the PARENT path / test harness); the child uses SlotBuilder, which adds the tag."""
    return _words_to_slot(words)


def init_words(count, owner=1):
    return [SEND_BLOCK_INIT, count & 0xFFFF, (owner | OWNER_FLAG) & 0xFFFF, 0, 0, 0, 0]


def send_block_words(index, chunk12):
    c = bytes(chunk12[:12]).ljust(12, b"\x00")
    return [SEND_BLOCK | (index & FRAG_INDEX_MASK)] + \
        [int.from_bytes(c[i:i + 2], "little") for i in range(0, 12, 2)]


def held_keys_words(keycode=0):
    return [SEND_HELD_KEYS, keycode & 0xFFFF, 0, 0, 0, 0, 0]


BLOCK_REQ_SIZE_NONE = 0


def send_player_ids_words(link_player_idx=(1, 0, 0, 0), player_count=2):
    """[RfuPrepareSendBuffer, link_rfu_2.c:1298-1305]: w1=playerCount, then linkPlayerIdx[0..3] as bytes from w2. A single
    child in RFU slot 0 gets [1,0,0,0], so it reads mpId=1.
    """
    idx = list(link_player_idx)[:4] + [0] * (4 - len(link_player_idx))
    w2 = (idx[0] & 0xFF) | ((idx[1] & 0xFF) << 8)
    w3 = (idx[2] & 0xFF) | ((idx[3] & 0xFF) << 8)
    return [SEND_PLAYER_IDS, player_count & 0xFFFF, w2, w3, 0, 0, 0]


def send_block_req_words(reqtype=BLOCK_REQ_SIZE_NONE):
    """[link_rfu_2.c:1294-1296]: w1=blockRequestType; NONE(0) makes both sides block-send their LinkPlayerBlock
    (link_rfu_2.c:1172).
    """
    return [SEND_BLOCK_REQ, reqtype & 0xFFFF, 0, 0, 0, 0, 0]


def send_packet_words(packet):
    """RFUCMD_SEND_PACKET with up to six u16 words of gRfu.packet [Rfu_SendPacket, link_rfu_2.c:1324]."""
    packet = [int(w) & 0xFFFF for w in packet][:6]
    return [SEND_PACKET] + packet + [0] * (6 - len(packet))


def exit_standby_words(count):
    """w1 = resendExitStandbyCount [link_rfu_2.c:1307-1310]; the child's reply MUST equal the round the host is currently
    broadcasting or the host's recv gate ignores it (link_rfu_2.c:1178-1180).
    """
    return [READY_EXIT_STANDBY, count & 0xFFFF, 0, 0, 0, 0, 0]


def close_link_words(count):
    """w1 continues the standby round counter; the host accepts any count (link_rfu_2.c:1175-1176)."""
    return [READY_CLOSE_LINK, count & 0xFFFF, 0, 0, 0, 0, 0]


class SlotBuilder:
    def __init__(self):
        self.tag = 0

    def build(self, words):
        """Idle (word0==0) emits 14 zeros and leaves the tag untouched."""
        if (words[0] & 0xFFFF) == 0:
            return idle_slot()
        w = list(words)
        w[0] = (w[0] | (self.tag << 5)) & 0xFFFF
        slot = _words_to_slot(w)
        self.tag = (self.tag + 1) & 7
        return slot


def parse_slot(slot):
    """Reflected child blocks may carry the child tag, so it is stripped for the index (real indices < 32). None for an
    empty/short slot.
    """
    if len(slot) < 2:
        return None
    if slot[:COMM_SLOT_LENGTH] == b"\x00" * min(len(slot), COMM_SLOT_LENGTH):
        return None
    word0 = int.from_bytes(slot[0:2], "little")
    op = word0 & RFUCMD_MASK
    rec = {"word0": word0, "op": op, "name": RFUCMD_NAMES.get(op, f"0x{op:04x}"),
           "low": word0 & 0xFF}
    if op == SEND_BLOCK_INIT:
        rec["count"] = int.from_bytes(slot[2:4], "little")
        owner_raw = slot[4]
        rec["owner_raw"] = owner_raw
        rec["peer"] = owner_raw & 0x7F
    elif op == SEND_BLOCK:
        rec["index"] = word0 & FRAG_INDEX_MASK
        rec["frag"] = bytes(slot[2:14]).ljust(12, b"\x00")
    elif op == SEND_BLOCK_REQ:
        # The BLOCK_REQ_* selector is word1 (gSendCmd[1] = blockRequestType, link_rfu_2.c:1296), not word0's low byte.
        rec["reqtype"] = int.from_bytes(slot[2:4], "little")
    elif op == SEND_HELD_KEYS:
        rec["keycode"] = int.from_bytes(slot[2:4], "little")
    elif op in (READY_EXIT_STANDBY, READY_CLOSE_LINK):
        # word1 = resendExitStandbyCount, the round the host advertises [link_rfu_2.c:1309].
        rec["count"] = int.from_bytes(slot[2:4], "little")
    elif op == SEND_PACKET:
        # gRfu.packet[0..5] in words 1..6 [Rfu_SendPacket, link_rfu_2.c:1324]. The Union Room puts
        # activity | IN_UNION_ROOM in packet[0]; a trade request adds species and level.
        rec["packet"] = [int.from_bytes(slot[2 + 2 * i:4 + 2 * i], "little") for i in range(6)]
    return rec
