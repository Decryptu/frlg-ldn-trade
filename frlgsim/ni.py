"""librfu NI (acknowledged) sender/receiver machines [src/librfu_rfu.c rfu_STC_NI_constructLLSF:1808,
rfu_STC_setSendData_org:1423]. The child delivers its 26-byte RfuGameData over NI (rfu_NI_CreateConnectionAllSlots:
dataType=1, dataSize=26) before any UNI traffic; for payloadSize 12 the emitted sequence is NI_START n=1 sz=7 (header),
NI n=1 ph=0/1/2 (12, 12, 2 bytes), NI_END n=0, NULL n=1.
"""

from . import rfu, charmap, linkplayer

SLOT_STATE_SEND_START = "SEND_START"
SLOT_STATE_SENDING = "SENDING"
SLOT_STATE_SEND_LAST = "SEND_LAST"
SLOT_STATE_SEND_NULL = "SEND_NULL"
SLOT_STATE_DONE = "DONE"

WINDOW_COUNT = 4
CHILD_FRAME_SIZE = 2
RFU_SERIAL_GAME = 0x0002
RFU_STATUS_JOIN_GROUP_OK = 5             # host accepted our join [include/link_rfu.h:40]; any other status = reject
NI_HEADER_SIZE = 7                       # dataType(1) + payloadSize(2) + dataSize(4)

ACTIVITY_TRADE = 0x04
ACTIVITY_WONDER_CARD = 21


def build_game_data(version_low, trainer_id, ot_name, *, language=linkplayer.LANGUAGE_ENGLISH,
                    activity=ACTIVITY_TRADE, started=True, partner_info=b"\x00\x00\x00\x00"):
    """The 26-byte NI src (serialNo + gname[15] + uname[9]) built from our identity; gname[0:13] is a packed RfuGameData
    [link_rfu.h:81-93]. `version_low` = gGameVersion (4 FireRed, 5 LeafGreen).
    """
    compat = (language & 0xF) | ((version_low & 0xF) << 10)
    rgd = bytearray(13)
    rgd[0:2] = (compat & 0xFFFF).to_bytes(2, "little")
    rgd[2:4] = (trainer_id & 0xFFFF).to_bytes(2, "little")     # compatibility.playerTrainerId[2]
    rgd[4:8] = bytes(partner_info[:4]).ljust(4, b"\x00")       # partnerInfo[RFU_CHILD_MAX]
    rgd[8:10] = (0).to_bytes(2, "little")                      # tradeSpecies:10 | tradeType:6
    rgd[10] = (activity & 0x7F) | ((1 if started else 0) << 7) # activity:7 | startedActivity:1
    rgd[11] = 0                                                # playerGender:1 | tradeLevel:7
    rgd[12] = 0                                                # padding
    gname = bytes(rgd).ljust(15, b"\x00")                      # gname[RFU_GAME_NAME_LENGTH + 2] = 15
    uname = charmap.encode(ot_name, width=9, pad=0x00)         # uname[RFU_USER_NAME_LENGTH + 1] = 9
    src = RFU_SERIAL_GAME.to_bytes(2, "little") + gname + uname
    assert len(src) == 26, len(src)
    return bytes(src)


def _ni_header(data_type, payload_size, data_size):
    """dataType(u8) + payloadSize(u16 LE) + dataSize(u32 LE): struct NIComm from .dataType."""
    return (bytes([data_type & 0xFF])
            + (payload_size & 0xFFFF).to_bytes(2, "little")
            + (data_size & 0xFFFFFFFF).to_bytes(4, "little"))


def _ni_send_sequence(src, data_type, payload_size):
    """Single pass of the librfu NI sender -> [(state, n, phase, size, payload)], LLSF-agnostic. The 7-byte header is
    chunked over NI_STARTs in payload_size units (parent payloadSize 5 needs two), then src is windowed over WINDOW_COUNT phases.
    """
    src = bytes(src)
    data_size = len(src)
    header = _ni_header(data_type, payload_size, data_size)
    seq = []
    # SEND_START: the header goes out in payload_size units; remainSize starts at 7 and drops by payload_size per ack [receive_Sender:2132].
    n0, off, remain = 1, 0, NI_HEADER_SIZE
    while True:
        size = min(remain, payload_size)
        seq.append((rfu.LCOM_NI_START, n0, 0, size, header[off:off + size]))
        n0 = (n0 + 1) & 3
        off += payload_size
        remain -= payload_size
        if remain <= 0:
            break
    # SENDING: phase round-robin, skipping phases past the end of src [constructLLSF:1818]; n resets to 1 per phase.
    now = [payload_size * i for i in range(WINDOW_COUNT)]
    n = [1] * WINDOW_COUNT
    phase, remain = 0, data_size
    while remain > 0:
        while now[phase] >= data_size:
            phase = (phase + 1) % WINDOW_COUNT
        o = now[phase]
        size = min(payload_size, data_size - o)
        seq.append((rfu.LCOM_NI, n[phase], phase, size, src[o:o + size]))
        now[phase] += payload_size << 2            # SENDING stride [receive_Sender:2131]
        n[phase] = (n[phase] + 1) & 3
        phase = (phase + 1) % WINDOW_COUNT
        remain -= payload_size
    seq.append((rfu.LCOM_NI_END, 0, 0, 0, b""))
    seq.append((rfu.LCOM_NULL, 1, 0, 0, b""))
    return seq


class NISender:
    def __init__(self, src, sub_frame_size=14, data_type=1):
        self.src = bytes(src)
        self.data_size = len(self.src)
        self.data_type = data_type & 0xFF
        self.payload_size = sub_frame_size - CHILD_FRAME_SIZE
        self.state = SLOT_STATE_SEND_START
        self.phase = 0
        self.n = [1] * WINDOW_COUNT
        self.remain = NI_HEADER_SIZE
        self.now = [0] * WINDOW_COUNT
        self._header = _ni_header(self.data_type, self.payload_size, self.data_size)
        self.null_slot = None
        self.emitted = []

    @property
    def done(self):
        return self.state == SLOT_STATE_DONE

    def _emit(self, state_lcom, n, phase, size, payload):
        slot = rfu.child_ni_llsf(state_lcom, n, phase, 0, size) + bytes(payload)
        # Every emitted sub-frame is retained: the host can lose one and re-ack its predecessor forever, so the orchestrator re-sends.
        self.emitted.append((state_lcom, n, phase, slot))
        return slot

    def resend_after(self, state_lcom, n, phase):
        """The sub-frame following the one the host last acked (state, n, phase), or None."""
        for i, (st, nn, ph, _slot) in enumerate(self.emitted):
            if (st, nn, ph) == (state_lcom, n, phase):
                if i + 1 < len(self.emitted):
                    return self.emitted[i + 1][3]
                return None
        return None

    def next_slot(self):
        if self.state == SLOT_STATE_SEND_START:
            size = min(self.remain, self.payload_size)
            slot = self._emit(rfu.LCOM_NI_START, self.n[0], 0, size, self._header[:size])
            self.state = SLOT_STATE_SENDING
            self.phase = 0
            for i in range(WINDOW_COUNT):
                self.n[i] = 1
                self.now[i] = self.payload_size * i
            self.remain = self.data_size
            return slot

        if self.state == SLOT_STATE_SENDING:
            while self.now[self.phase] >= self.data_size:
                self.phase = (self.phase + 1) % WINDOW_COUNT
            off = self.now[self.phase]
            size = min(self.payload_size, self.data_size - off)
            slot = self._emit(rfu.LCOM_NI, self.n[self.phase], self.phase, size,
                              self.src[off:off + size])
            self.remain -= size
            self.now[self.phase] += self.payload_size << 2
            self.phase = (self.phase + 1) % WINDOW_COUNT
            if self.remain <= 0:
                self.state = SLOT_STATE_SEND_LAST
                self.phase = 0
            return slot

        if self.state == SLOT_STATE_SEND_LAST:
            slot = self._emit(rfu.LCOM_NI_END, 0, 0, 0, b"")
            self.state = SLOT_STATE_SEND_NULL
            return slot

        if self.state == SLOT_STATE_SEND_NULL:
            slot = self._emit(rfu.LCOM_NULL, 1, 0, 0, b"")
            self.state = SLOT_STATE_DONE
            # retained so the orchestrator can re-emit it if the host never registers it
            self.null_slot = slot
            return slot

        return None


class ParentNISender:
    """PARENT NI sender for the 1-byte join status [SendRfuStatusToPartner -> rfu_NI_setSendData(1 << idx, 8, &status, 1),
    link_rfu_2.c:1747]: frameSize 3, subFrameSize 8 -> payloadSize 5 < the 7-byte header, so SEND_START emits two NI_STARTs.
    """

    STATUS_SUBFRAME_SIZE = 8

    def __init__(self, status=RFU_STATUS_JOIN_GROUP_OK, bm_slot=1, sub_frame_size=STATUS_SUBFRAME_SIZE):
        """RFU_STATUS_JOIN_GROUP_OK accepts the child; any other status rejects it."""
        self.status = status & 0xFF
        self.bm_slot = bm_slot
        payload_size = sub_frame_size - rfu.PARENT_FRAME_SIZE
        # dataType 0: the sending path of setSendData_org sets it [librfu_rfu.c:1477]
        self._seq = _ni_send_sequence(bytes([self.status]), data_type=0, payload_size=payload_size)
        self._i = 0

    @property
    def done(self):
        return self._i >= len(self._seq)

    def next_slot(self):
        if self.done:
            return None
        state, n, phase, size, payload = self._seq[self._i]
        self._i += 1
        return rfu.parent_ni_llsf(state, n, phase, 0, size, self.bm_slot) + bytes(payload)


def recv_ack_slot(state, n, phase):
    """CHILD recv-side ack of a host NI sub-frame: mirror (state, n, phase) with ack=1, size=0, no payload [rfu_STC_NI_receive].
    The child must ack every host NI sub-frame or the host faults the link.
    """
    return rfu.child_ni_llsf(state, n, phase, ack=1, size=0)


class NIReceiver:
    """Tracks the host's NI transfer; complete on its NI_END (or NULL) with ack=0. The host's terminal NULL is not acked."""

    def __init__(self):
        self.complete = False
        # The 1-byte join status from the host's LCOM_NI sub-frame; anything but RFU_STATUS_JOIN_GROUP_OK means it rejected us.
        self.status = None

    def on_host_ni(self, ni_rec):
        if ni_rec is None or ni_rec.get("ack") != 0:
            return None
        state = ni_rec["state"]
        if state == rfu.LCOM_NI and ni_rec.get("payload"):
            self.status = ni_rec["payload"][0]
        if state == rfu.LCOM_NULL:
            self.complete = True
            return None
        if state == rfu.LCOM_NI_END:
            self.complete = True
        if state in (rfu.LCOM_NI_START, rfu.LCOM_NI, rfu.LCOM_NI_END):
            return recv_ack_slot(state, ni_rec["n"], ni_rec["phase"])
        return None


def parent_recv_ack_slot(state, n, phase, bm_slot=1):
    return rfu.parent_ni_llsf(state, n, phase, 1, 0, bm_slot)


def decode_child_ni_slot(slot):
    llsf = rfu.parse_llsf_child(slot)
    return {"state": llsf["state"], "ack": llsf["ack"], "n": llsf["n"], "phase": llsf["phase"],
            "size": llsf["size"], "payload": bytes(slot[2:2 + llsf["size"]])}


class ParentNIReceiver:
    """Host-side NI receiver: acks the child's game-data sub-frames and reassembles the 26-byte RfuGameData by phase;
    the child's terminal NULL is not acked.
    """

    def __init__(self, bm_slot=1, payload_size=12):
        self.complete = False
        self.bm_slot = bm_slot
        self.payload_size = payload_size
        self.data_type = None
        self.data_size = None
        self.game_data = None
        self._hdr = bytearray()
        self._buf = bytearray()
        self._phase_count = [0] * WINDOW_COUNT

    def on_child_ni(self, ni_rec):
        if ni_rec is None or ni_rec.get("ack") != 0:
            return None
        state = ni_rec["state"]
        if state == rfu.LCOM_NI_START:
            self._hdr += ni_rec.get("payload", b"")
            if self.data_size is None and len(self._hdr) >= NI_HEADER_SIZE:
                self.data_type = self._hdr[0]
                self.payload_size = int.from_bytes(self._hdr[1:3], "little") or self.payload_size
                self.data_size = int.from_bytes(self._hdr[3:7], "little")
        elif state == rfu.LCOM_NI:
            phase = ni_rec["phase"] & 3
            off = phase * self.payload_size + self._phase_count[phase] * WINDOW_COUNT * self.payload_size
            payload = ni_rec.get("payload", b"")
            if off + len(payload) > len(self._buf):
                self._buf.extend(b"\x00" * (off + len(payload) - len(self._buf)))
            self._buf[off:off + len(payload)] = payload
            self._phase_count[phase] += 1
        elif state == rfu.LCOM_NULL:
            self.complete = True
            self._finalize()
            return None
        if state == rfu.LCOM_NI_END:
            self.complete = True
            self._finalize()
        if state in (rfu.LCOM_NI_START, rfu.LCOM_NI, rfu.LCOM_NI_END):
            return parent_recv_ack_slot(state, ni_rec["n"], ni_rec["phase"], self.bm_slot)
        return None

    def _finalize(self):
        if self.game_data is None:
            data = bytes(self._buf)
            if self.data_size is not None:
                data = data[:self.data_size]
            self.game_data = data

    @property
    def trainer_id(self):
        """game_data[4:6] LE = compatibility.playerTrainerId."""
        if not self.game_data or len(self.game_data) < 6:
            return None
        return int.from_bytes(self.game_data[4:6], "little")

    @property
    def uname(self):
        """game_data[17:26], game charset, 0-padded."""
        if not self.game_data or len(self.game_data) < 26:
            return None
        return bytes(self.game_data[17:26])
