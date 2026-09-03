"""Deterministic child/parent simulation for RFU leader milestones 3.1-3.3."""

from frlgsim import gbaframe, ni, rfu, rfu_leader
from frlgsim.rfu_leader import CHILD_NI, PARENT_NI, UNI, RFULeader


def _child_t(slot, ts):
    return gbaframe.wrap_t(slot, ts)


def test_31_connect_accept_matches_native_completed_trade():
    # switch_complete_trade: child C=8084, host A owns b7f1 and echoes 8084.
    leader = RFULeader(host_session_id=b"\xb7\xf1")
    assert leader.receive(bytes.fromhex("574302008084")) == "connect"
    assert leader.state == CHILD_NI and leader.connect_id == b"\x80\x84"
    accept = leader.tick()
    assert accept == bytes.fromhex("57410600b7f180840000")
    assert gbaframe.parse_in(accept) == {
        "type": "A", "host_session_id": b"\xb7\xf1", "connect_id": b"\x80\x84"
    }
    # A real Switch parent follows A with a 'G' link-state 0 (every joiner capture j19-j87).
    assert leader.tick() == bytes.fromhex("5747040000000000")
    # host_2.3 shows each retry C uses a new Reliable seq.  The leader must
    # not allocate another A; Reliable retransmits the original opening A.
    assert leader.receive(bytes.fromhex("574302008084")) == "connect_duplicate"
    assert leader.tick() is None


def test_default_parent_id_has_native_f1_high_byte():
    leader = RFULeader()
    assert len(leader.host_session_id) == 2
    assert leader.host_session_id[1] == 0xF1


def test_32_bidirectional_ni_is_ack_gated_and_recovers_identity():
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\xc5\xf1"))
    leader.tick()                                      # A
    assert leader.tick() == gbaframe.build_link_state(0)

    source = ni.build_game_data(5, 0x2288, "EMU")
    child = ni.NISender(source)
    ts = 1
    parent_acks = []
    saw_end = False
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        # Child NULL is not ACKed.  Leave the next tick for the parent's first
        # join-status NI frame instead of consuming it in this half-loop.
        child_llsf = rfu.parse_llsf_child(slot)
        if child_llsf["state"] == rfu.LCOM_NI_END:
            saw_end = True
            assert leader.state == CHILD_NI       # wait for terminal NULL
        out = None if child_llsf["state"] == rfu.LCOM_NULL else leader.tick()
        if out is not None:
            rec = gbaframe.parse_in(out)
            if rec.get("ni", {}).get("ack") == 1:
                parent_acks.append(rec["ni"])
    assert event in ("child_ni_complete", "child_ni")
    assert saw_end
    assert leader.state == PARENT_NI
    assert leader.child_game_data == source
    assert leader.child_trainer_id == 0x2288
    assert len(parent_acks) == 5                       # NULL is not ACKed

    # The child's NI is in: the real parent pushes 'G' link-state 1 before its own NI.
    assert leader.tick() == gbaframe.build_link_state(1)
    # Parent sends one status sub-frame, then waits until the child ACKs it.
    child_recv = ni.NIReceiver()
    seen_parent = []
    while leader.state != UNI:
        frame = leader.tick()
        assert frame is not None
        rec = gbaframe.parse_in(frame)
        seen_parent.append(rec["ni"])
        ack = child_recv.on_host_ni(rec["ni"])
        if ack is not None:
            repeat = leader.tick()                    # repeat every VBlank until ACK
            repeat_rec = gbaframe.parse_in(repeat)
            assert repeat_rec["ni"] == rec["ni"]
            assert repeat_rec["ts"] == rec["ts"] + 1
            assert leader.receive(_child_t(ack, ts)) == "parent_ni_ack"
            ts += 1
    assert [x["state"] for x in seen_parent] == [1, 1, 2, 3, 0]
    assert child_recv.status == ni.RFU_STATUS_JOIN_GROUP_OK
    assert child_recv.complete and leader.ni_complete


def test_33_uni_continuously_reflects_child_and_carries_parent_row():
    leader = _complete_ni_handshake()
    child_cmd = rfu.SlotBuilder().build(rfu.held_keys_words(0x1234))
    assert leader.receive(_child_t(rfu.uni_slot(child_cmd), 100)) == "uni"

    parent_cmd = rfu.serialize(rfu.send_player_ids_words())
    first = gbaframe.parse_in(leader.tick(parent_cmd))
    second = gbaframe.parse_in(leader.tick())
    assert first["ts"] + 1 == second["ts"]
    assert first["llsf_state"] == second["llsf_state"] == rfu.LCOM_UNI
    rows1, rows2 = dict(first["slots"]), dict(second["slots"])
    assert rows1[0] == parent_cmd and rows1[1] == child_cmd
    assert rows2[0] == rfu.idle_slot() and rows2[1] == child_cmd
    assert leader.uni_in == 1 and leader.uni_out == 2


def test_tagged_child_command_is_normalized_for_activity_and_echo():
    """The parent clears the child's rolling tag before publishing it."""
    leader = _complete_ni_handshake()
    builder = rfu.SlotBuilder()
    builder.build(rfu.held_keys_words(0x0001))
    tagged = builder.build(rfu.held_keys_words(0x1234))
    expected = rfu.serialize(rfu.held_keys_words(0x1234))
    assert tagged != expected and tagged[0] & ~rfu.FRAG_INDEX_MASK

    assert leader.receive(_child_t(rfu.uni_slot(tagged), 100)) == "uni"
    assert leader.child_cmd == expected

    frame = gbaframe.parse_in(leader.tick())
    assert dict(frame["slots"])[1] == expected


def test_duplicate_child_ni_is_reacked_without_corrupting_reassembly():
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.tick()                                      # A
    leader.tick()                                      # G 0
    slot = ni.NISender(ni.build_game_data(5, 0x2288, "EMU")).next_slot()
    frame = _child_t(slot, 1)
    assert leader.receive(frame) == "child_ni"
    ack1 = leader.tick()
    assert leader.receive(frame) == "child_ni_duplicate"
    ack2 = leader.tick()
    assert gbaframe.parse_in(ack1)["ni"] == gbaframe.parse_in(ack2)["ni"]


def test_link_state_frames_mirror_the_real_parent():
    """The real Switch parent sends 'G' link-state frames: 0 shortly after A, 1 once it holds the child's NI."""
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    assert gbaframe.parse_in(leader.tick())["type"] == "A"
    g0 = leader.tick()
    assert g0 == bytes.fromhex("5747040000000000")
    assert gbaframe.parse_in(g0) == {"type": gbaframe.TYPE_G}
    assert leader.tick() is None
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()                             # parent ACK
    assert event == "child_ni_complete"
    assert leader.tick() == bytes.fromhex("5747040001000000")
    assert gbaframe.parse_in(leader.tick())["ni"]["state"] == rfu.LCOM_NI_START


def test_union_room_leader_skips_the_parent_join_status_ni():
    """Union Room: the child reaches RFUSTATE_UR_PLAYER_EXCHANGE and goes straight to UNI via
    rfu_UNI_setSendData + Task_PlayerExchange [src/link_rfu_2.c:533], so it never waits for the
    parent's join-status NI. On hardware (u03, u04) the console mirrored both our NI_STARTs, then
    stopped mirroring the NI body and disconnected 80ms later.

    With skip_parent_ni the leader still sends the 'G' link-state 1 frame, then goes straight to
    UNI instead of presenting an NI. UNTESTED on hardware."""
    leader = RFULeader(skip_parent_ni=True)
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    assert gbaframe.parse_in(leader.tick())["type"] == "A"
    leader.tick()                                      # G link-state 0
    assert leader.tick() is None
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()
    assert event == "child_ni_complete_no_parent_ni"
    # The 'G' link-state 1 frame is still sent: it is not part of the NI.
    assert leader.tick() == bytes.fromhex("5747040001000000")
    # Next frame is UNI, not an NI_START.
    parsed = gbaframe.parse_in(leader.tick())
    assert parsed.get("ni") is None, parsed
    assert leader.state == "UNI"


def test_default_leader_still_sends_the_parent_ni():
    """Guards the trade centre path, which is hardware-proven and must not change."""
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.tick()
    leader.tick()
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()
    assert event == "child_ni_complete"
    assert leader.tick() == bytes.fromhex("5747040001000000")
    assert gbaframe.parse_in(leader.tick())["ni"]["state"] == rfu.LCOM_NI_START


def test_ldn_leave_immediately_silences_queued_output():
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.on_ldn_leave()
    assert leader.tick() is None
    assert not leader.connected


def _complete_ni_handshake():
    leader = RFULeader()
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.tick()                                      # A
    leader.tick()                                      # G 0
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()                             # parent ACK
    assert leader.tick() == gbaframe.build_link_state(1)  # G 1 once the child NI is in
    child_recv = ni.NIReceiver()
    while leader.state != UNI:
        out = leader.tick()
        ack = child_recv.on_host_ni(gbaframe.parse_in(out)["ni"])
        if ack is not None:
            leader.receive(_child_t(ack, ts))
            ts += 1
    return leader


def test_every_child_command_is_echoed_even_when_they_arrive_in_a_burst(monkeypatch):
    """Row 1 reflects every child command rather than only the newest one, once the backlog bound is lifted."""
    monkeypatch.setattr(rfu_leader, "ECHO_MAX", 1000)
    leader = _complete_ni_handshake()
    builder = rfu.SlotBuilder()
    expected = [rfu.serialize(rfu.send_block_words(i, bytes([i]) * 12))
                for i in range(17)]
    sent = [builder.build(rfu.send_block_words(i, bytes([i]) * 12))
            for i in range(17)]
    assert any(raw != normalized for raw, normalized in zip(sent, expected))
    for ts, slot in enumerate(sent, 100):
        leader.receive(_child_t(rfu.uni_slot(slot), ts))

    echoed = []
    for _ in range(len(sent) + 4):
        record = gbaframe.parse_in(leader.tick(rfu.idle_slot()))
        row1 = dict(record["slots"]).get(1)
        if row1 is not None and row1 != rfu.idle_slot():
            echoed.append(row1)

    for slot in expected:
        assert slot in echoed, (
            f"fragment {rfu.parse_slot(slot)['index']} was never echoed back")
    assert echoed[-1] == expected[-1]


if __name__ == "__main__":
    for name, func in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"PASS {name}")


def test_union_room_keepalive_re_presents_an_ni_start_before_uni():
    """Probe for the 'D' that follows five unanswered parent frames (u03-u05): after the child's
    name NI the leader re-presents the first parent NI_START subframe, which the console mirrors
    even in the room (u03, u04), for keepalive_frames VBlanks, then goes to UNI. UNTESTED on hardware."""
    leader = RFULeader(skip_parent_ni=True, keepalive_frames=3)
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.tick()                                      # A
    leader.tick()                                      # G link-state 0
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()
    assert event == "child_ni_complete_keepalive"
    assert leader.tick() == bytes.fromhex("5747040001000000")
    reference = RFULeader()                            # the hardware-proven first parent NI_START
    first = ni.ParentNISender(reference.join_status, reference.bm_slot).next_slot()
    for _ in range(3):
        parsed = gbaframe.parse_in(leader.tick())
        assert parsed["ni"]["state"] == rfu.LCOM_NI_START, parsed
        assert parsed["ni"]["n"] == 1 and parsed["ni"]["ack"] == 0, parsed
        assert parsed["ni"]["size"] == 5 and parsed["ni"]["payload"] == first[-5:]
        assert leader.state == "KEEPALIVE"
    # A mirrored ack during the keepalive is accepted without changing state.
    assert leader.receive(_child_t(ni.recv_ack_slot(rfu.LCOM_NI_START, 1, 0), ts)) == "ni_ack_ignored"
    parsed = gbaframe.parse_in(leader.tick())
    assert parsed.get("ni") is None, parsed
    assert leader.state == "UNI"


def test_union_room_keepalive_zero_is_the_plain_skip():
    leader = RFULeader(skip_parent_ni=True, keepalive_frames=0)
    leader.receive(gbaframe.build_connect(b"\x67\x79"))
    leader.tick()
    leader.tick()
    child = ni.NISender(ni.build_game_data(5, 0x2288, "EMU"))
    ts = 1
    while not child.done:
        slot = child.next_slot()
        event = leader.receive(_child_t(slot, ts))
        ts += 1
        if rfu.parse_llsf_child(slot)["state"] != rfu.LCOM_NULL:
            leader.tick()
    assert event == "child_ni_complete_no_parent_ni"
