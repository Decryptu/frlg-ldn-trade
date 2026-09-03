"""Leader/parent side of the emulator RFU protocol (the inner payload of Pia Reliable protocol 10).
receive(inner) once per unique in-order Reliable payload, tick(words) once per VBlank (at most one
frame out). The Reliable layer MUST deduplicate retransmitted DATA before calling receive()."""

from collections import deque
import secrets

from . import gbaframe, ni, rfu


WAIT_CONNECT = "WAIT_CONNECT"
CHILD_NI = "CHILD_NI"
PARENT_NI = "PARENT_NI"
KEEPALIVE = "KEEPALIVE"
UNI = "UNI"
DISCONNECTED = "DISCONNECTED"


def _control_frame(frame):
    """Child frame envelope: 57 type len(u16 LE) body."""
    frame = bytes(frame)
    if len(frame) < 4 or frame[0] != gbaframe.GBA_MARKER:
        return None
    size = int.from_bytes(frame[2:4], "little")
    if len(frame) < 4 + size:
        return None
    return frame[1], frame[4:4 + size]


def _parent_ni_fields(slot):
    value = int.from_bytes(slot[:3], "little")
    return ((value >> rfu.PARENT_LLSF_STATE_SHIFT) & 0xF,
            (value >> rfu.PARENT_LLSF_N_SHIFT) & 3,
            (value >> rfu.PARENT_LLSF_PHASE_SHIFT) & 3)


# The console emits slots slightly faster than this host echoes them; a lagging echo makes its
# SendLastBlock re-send fragments we already hold and its retry loop ends in an RFU error.
ECHO_MAX = 2


def _normalize_child_cmd(slot):
    cmd = bytearray(bytes(slot)[:rfu.COMM_SLOT_LENGTH].ljust(
        rfu.COMM_SLOT_LENGTH, b"\x00"))
    cmd[0] &= rfu.FRAG_INDEX_MASK
    return bytes(cmd)


class RFULeader:
    """``bm_slot=1`` seats the child in RFU slot zero / multiplayer id 1."""

    def __init__(self, host_session_id=None, *, bm_slot=1,
                 join_status=ni.RFU_STATUS_JOIN_GROUP_OK, start_ts=1,
                 skip_parent_ni=False, keepalive_frames=0):
        if host_session_id is None:
            # Native leaders use parent-id high byte 0xf1 with a varying low byte; beacon and A store it LE.
            host_session_id = secrets.token_bytes(1) + b"\xf1"
        self.host_session_id = bytes(host_session_id)[:2].ljust(2, b"\x00")
        self.bm_slot = bm_slot & 0xF
        self.join_status = join_status & 0xFF
        # Union Room: the child sets only a UNI receive buffer at LMAN_MSG_CHILD_NAME_SEND_COMPLETED
        # [link_rfu_2.c:2526] and goes straight to UNI, so it never mirrors a parent NI body (u03, u04).
        self.skip_parent_ni = bool(skip_parent_ni)
        # skip_parent_ni only: re-present the first parent NI_START subframe for this many VBlanks
        # before the first UNI frame. The room child mirrors NI_STARTs without a game receive buffer
        # [librfu_rfu.c:2202] and 'D's after five unanswered parent frames; the pending receive then
        # blocks its own UNI send until its 480-frame NI fail counter releases it (u06, u12).
        self.keepalive_frames = max(0, int(keepalive_frames))
        self._keepalive_left = 0
        self._keepalive_slot = None
        self.ts = start_ts & 0xFFFFFFFF
        self.state = WAIT_CONNECT
        self.connect_id = None
        self.child_cmd = rfu.idle_slot()
        # Native RFU reflects every child command into row one; keeping only the newest loses block
        # fragments and the console retries until it disconnects.
        self._echo_queue = deque()
        self._echo_cmd = rfu.idle_slot()
        self.echo_backlog_peak = 0
        self.echo_dropped = 0
        self.child_game_data = None
        self.k_acks = 0
        self.uni_in = 0
        self.uni_out = 0

        self._pending = deque()
        self._child_ni = None
        self._parent_ni = None
        self._parent_waiting = None
        self._parent_current_slot = None
        self._seen_child_ni = set()

    @property
    def connected(self):
        return self.connect_id is not None and self.state != DISCONNECTED

    @property
    def ni_complete(self):
        return self.state == UNI

    @property
    def child_trainer_id(self):
        return None if self._child_ni is None else self._child_ni.trainer_id

    @property
    def child_uname(self):
        return None if self._child_ni is None else self._child_ni.uname

    def _wrap_parent_t(self, slot):
        frame = gbaframe.wrap_t_parent(slot, self.ts)
        self.ts = (self.ts + 1) & 0xFFFFFFFF
        return frame

    def receive(self, inner):
        """Output is queued for tick() to keep one parent frame per VBlank; returns an event name or None."""
        ctl = _control_frame(inner)
        if ctl is None:
            return None
        typ, body = ctl

        if typ == gbaframe.TYPE_C:
            if len(body) < 2:
                return None
            cid = bytes(body[:2])
            if self.connect_id is None:
                self.connect_id = cid
                self.state = CHILD_NI
                self._child_ni = ni.ParentNIReceiver(self.bm_slot)
                self._pending.append(gbaframe.build_accept(self.host_session_id, cid))
                self._pending.append(gbaframe.build_link_state(0))
                return "connect"
            if cid == self.connect_id and self.state != DISCONNECTED:
                # The child sends C as a new Reliable frame every VBlank until it sees A; A is one
                # stream-opening frame whose retransmits belong to Reliable, so never allocate a fresh A per C.
                return "connect_duplicate"
            return "connect_rejected"

        if typ == gbaframe.TYPE_D:
            self.state = DISCONNECTED
            self._pending.clear()
            return "disconnect"

        if typ == gbaframe.TYPE_K:
            self.k_acks += 1
            return "k_ack"

        if typ != gbaframe.TYPE_T or not self.connected:
            return None

        rec = gbaframe.parse_out(inner)
        if rec is None or rec.get("llsf") is None:
            return None
        llsf = rec["llsf"]

        if llsf["ack"] == 1:
            got = (llsf["state"], llsf["n"], llsf["phase"])
            if self.state == PARENT_NI and got == self._parent_waiting:
                self._parent_waiting = None
                self._parent_current_slot = None
                return "parent_ni_ack"
            return "ni_ack_ignored"

        if llsf["state"] != rfu.LCOM_UNI:
            if self.state not in (CHILD_NI, PARENT_NI):
                return "ni_out_of_phase"
            slot = rec["slot"]
            key = (llsf["state"], llsf["n"], llsf["phase"], bytes(slot[2:]))
            if key in self._seen_child_ni:
                # If a layer failed to deduplicate, ACK again but never append the payload twice.
                if llsf["state"] in (rfu.LCOM_NI_START, rfu.LCOM_NI, rfu.LCOM_NI_END):
                    ack = ni.parent_recv_ack_slot(llsf["state"], llsf["n"],
                                                  llsf["phase"], self.bm_slot)
                    self._pending.append(self._wrap_parent_t(ack))
                return "child_ni_duplicate"
            self._seen_child_ni.add(key)
            ack = self._child_ni.on_child_ni(ni.decode_child_ni_slot(slot))
            if ack is not None:
                self._pending.append(self._wrap_parent_t(ack))
            # Handover to the parent NI sender happens on the child's unacknowledged terminal NULL,
            # not on NI_END (native order: END -> NULL -> parent NI).
            if (llsf["state"] == rfu.LCOM_NULL
                    and self._child_ni.complete and self.state == CHILD_NI):
                self.child_game_data = self._child_ni.game_data
                self._pending.append(gbaframe.build_link_state(1))
                if self.skip_parent_ni:
                    if self.keepalive_frames:
                        self._keepalive_slot = ni.ParentNISender(
                            self.join_status, self.bm_slot).next_slot()
                        self._keepalive_left = self.keepalive_frames
                        self.state = KEEPALIVE
                        return "child_ni_complete_keepalive"
                    self.state = UNI
                    return "child_ni_complete_no_parent_ni"
                self._parent_ni = ni.ParentNISender(self.join_status, self.bm_slot)
                self.state = PARENT_NI
                return "child_ni_complete"
            return "child_ni"

        # Native RfuMain2_Parent strips childSendCmdId bits before publishing via gRecvCmds; both the
        # activity and the row-one echo must see that normalized form.
        if self.state != UNI or rec.get("cmd") is None:
            return "uni_early"
        self.child_cmd = _normalize_child_cmd(rec["cmd"])
        self._echo_queue.append(self.child_cmd)
        self.echo_backlog_peak = max(self.echo_backlog_peak, len(self._echo_queue))
        while len(self._echo_queue) > ECHO_MAX:
            self._echo_queue.popleft()
            self.echo_dropped += 1
        self.uni_in += 1
        return "uni"

    def tick(self, parent_words=None):
        """Queued A/NI ACKs first; parent NI is stop-and-wait on the child's mirrored ACK; in UNI a T
        goes out every call, even with both rows idle. None before C arrives."""
        if self._pending:
            return self._pending.popleft()

        if self.state == KEEPALIVE:
            if self._keepalive_left > 0:
                self._keepalive_left -= 1
                return self._wrap_parent_t(self._keepalive_slot)
            self.state = UNI

        if self.state == PARENT_NI:
            # The native leader re-presents the current NI subframe every VBlank until the child mirrors it
            # with ack=1; a delivered poll can still be missed by the child's RFU callback.
            if self._parent_waiting is not None:
                return self._wrap_parent_t(self._parent_current_slot)

            slot = self._parent_ni.next_slot()
            if slot is not None:
                fields = _parent_ni_fields(slot)
                frame = self._wrap_parent_t(slot)
                if fields[0] == rfu.LCOM_NULL:
                    # The terminal NULL is not ACKed by the child.
                    self.state = UNI
                else:
                    self._parent_waiting = fields
                    self._parent_current_slot = slot
                return frame

        if self.state == UNI:
            if parent_words is None:
                parent_cmd = rfu.idle_slot()
            elif isinstance(parent_words, (bytes, bytearray)):
                parent_cmd = bytes(parent_words)[:rfu.COMM_SLOT_LENGTH].ljust(
                    rfu.COMM_SLOT_LENGTH, b"\x00")
            else:
                parent_cmd = rfu.serialize(parent_words)
            if self._echo_queue:
                self._echo_cmd = self._echo_queue.popleft()
            table = rfu.pack_recv_cmds([parent_cmd, self._echo_cmd])
            self.uni_out += 1
            return self._wrap_parent_t(rfu.parent_uni_slot(table, self.bm_slot))
        return None

    def disconnect_frame(self):
        if self.connect_id is None:
            return None
        self.state = DISCONNECTED
        self._pending.clear()
        return gbaframe.build_disconnect(self.connect_id)

    def on_ldn_leave(self):
        """A LeaveEvent is below Pia/RFU: no peer remains to receive D. Graceful shutdown uses disconnect_frame()."""
        self.state = DISCONNECTED
        self._pending.clear()
