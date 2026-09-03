"""The Union Room battle: the link buffer codec, struct BattlePokemon, and the non-master
controller. Every constant here is a decomp citation; see docs/joiner_protocol_notes.md."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import battle_link as bl, battle_mon, charmap, mon as monmod, uroom_battle as ub  # noqa: E402


def _mon():
    """A real party mon, so the serialiser is exercised against genuine substructs."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scratchpad", "TREECKO.pk3")
    if not os.path.exists(path):
        pytest.skip("scratchpad/TREECKO.pk3 is not in this checkout")
    return monmod.Mon.from_file(path)


# --- the link buffer record -------------------------------------------------------------------

def test_the_stored_size_always_adds_a_whole_word():
    """`alignedSize = size - size % 4 + 4` [battle_controllers.c:417], so an exact multiple of four
    still grows: a 4-byte payload is stored as 8."""
    assert bl.aligned_size(1) == 4
    assert bl.aligned_size(3) == 4
    assert bl.aligned_size(4) == 8
    assert bl.aligned_size(5) == 8
    assert bl.aligned_size(88) == 92


def test_a_record_round_trips_with_its_header_fields():
    rec = bl.parse(bl.build(bl.BUFFER_A, 1, bytes([bl.CHOOSEACTION, 7, 0, 0]),
                            attacker=1, target=0, absent_flags=2, effect_battler=3))
    assert rec["buffer_id"] == bl.BUFFER_A
    assert rec["active_battler"] == 1
    assert rec["attacker"] == 1 and rec["target"] == 0
    assert rec["absent_flags"] == 2 and rec["effect_battler"] == 3
    assert rec["cmd"] == bl.CHOOSEACTION
    assert rec["size"] == 8 and len(rec["payload"]) == 8
    assert rec["payload"][:4] == bytes([bl.CHOOSEACTION, 7, 0, 0])


def test_a_truncated_record_is_rejected_rather_than_read_short():
    with pytest.raises(ValueError):
        bl.parse(b"\x00" * 4)
    with pytest.raises(ValueError):
        bl.parse(bl.build(bl.BUFFER_A, 1, b"\x01\x02\x03\x04")[:-2])


def test_the_ack_names_the_battler_and_carries_our_player_id():
    """It clears gBitTable[active_battler] << (id * 4) [battle_controllers.c:590], and the reference
    sends it at size 4, so 16 bytes on the wire."""
    rec = bl.parse(bl.ack(1, 0))
    assert rec["buffer_id"] == bl.EXEC_CLEAR
    assert rec["active_battler"] == 1
    assert rec["payload"][0] == 0
    assert len(bl.ack(1, 0)) == 16


def test_the_controller_enum_matches_the_decomp():
    """[include/battle_controllers.h:138]. The tail is what a mis-numbered enum would break first."""
    assert bl.GETMONDATA == 0
    assert bl.CHOOSEACTION == 18 and bl.CHOOSEMOVE == 20
    assert bl.LINKSTANDBYMSG == 53 and bl.ENDLINKBATTLE == 55 and bl.TERMINATOR_NOP == 56
    assert len(bl.NAMES) == 57


def test_reply_payloads_match_their_emitters():
    two = bl.parse(bl.two_return_values(1, bl.B_ACTION_RUN, 0x1234))
    assert two["payload"][:4] == bytes([bl.TWORETURNVALUES, bl.B_ACTION_RUN, 0x34, 0x12])
    one = bl.parse(bl.one_return_value(1, 0x0102))
    assert one["payload"][:3] == bytes([bl.ONERETURNVALUE, 0x02, 0x01])
    chosen = bl.parse(bl.chosen_mon_return_value(1, 3, b"\x04\x05\x06"))
    assert chosen["payload"][:5] == bytes([bl.CHOSENMONRETURNVALUE, 3, 4, 5, 6])
    xfer = bl.parse(bl.data_transfer(1, b"ABCDE"))
    assert xfer["payload"][:4] == bytes([bl.DATATRANSFER, bl.DATATRANSFER, 5, 0])
    assert xfer["payload"][4:9] == b"ABCDE"


# --- struct BattlePokemon ---------------------------------------------------------------------

def test_battle_pokemon_is_the_struct_size():
    assert battle_mon.SIZE == 0x58
    assert len(battle_mon.from_mon(_mon())) == 0x58


def test_battle_pokemon_carries_the_fields_copy_player_mon_data_writes():
    m = _mon()
    d = m.decode()
    b = battle_mon.from_mon(m)
    raw = m.party_bytes()
    assert int.from_bytes(b[0x00:0x02], "little") == d["species"]
    assert list(int.from_bytes(b[0x0C + i * 2:0x0E + i * 2], "little") for i in range(4)) == d["moves"]
    assert b[0x2A] == d["level"]
    assert int.from_bytes(b[0x28:0x2A], "little") == int.from_bytes(raw[86:88], "little")   # hp
    assert int.from_bytes(b[0x2C:0x2E], "little") == int.from_bytes(raw[88:90], "little")   # maxHP
    assert int.from_bytes(b[0x02:0x04], "little") == int.from_bytes(raw[90:92], "little")   # attack
    assert charmap.decode(b[0x30:0x3B]) == d["nickname"]
    assert charmap.decode(b[0x3C:0x44]) == d["otName"]
    assert int.from_bytes(b[0x48:0x4C], "little") == d["pid"]
    assert int.from_bytes(b[0x54:0x58], "little") == d["otid"]


def test_the_fields_the_game_leaves_as_stack_garbage_are_zero():
    """CopyPlayerMonData never writes statStages, ability, type1, type2, unknown or status2
    [battle_controller_player.c:1519]; the receiver recomputes them from the species."""
    b = battle_mon.from_mon(_mon())
    assert b[0x18:0x24] == bytes(12)        # statStages[8], ability, type1, type2, unknown
    assert b[0x50:0x54] == bytes(4)         # status2


# --- the entry blocks -------------------------------------------------------------------------

def test_the_selection_block_is_32_bytes_of_one_meaningful_byte():
    assert len(ub.accept_block()) == ub.ACCEPT_BLOCK_SIZE == 0x20
    assert ub.accept_block()[0] == 0x51 and ub.accept_block()[1:] == bytes(0x1F)
    assert ub.accept_block(False)[0] == 0x52
    assert ub.read_accept_block(ub.accept_block()) is True
    assert ub.read_accept_block(ub.accept_block(False)) is False
    with pytest.raises(ValueError):
        ub.read_accept_block(b"\x40")


def test_we_advertise_a_version_that_makes_the_console_master():
    """LinkBattleComputeBattleTypeFlags [battle_main.c:886]: the console at multiplayer id 1 elects
    itself master only for a signature below 0x201 that is not 0x100."""
    assert ub.VERSION_NON_MASTER < ub.VERSION_FIRERED
    assert ub.VERSION_NON_MASTER != 0x100
    h = ub.battler_header()
    assert len(h) == ub.HEADER_SIZE == 31
    assert h[0] | (h[1] << 8) == ub.VERSION_NON_MASTER
    assert h[2:] == bytes(29)               # healthy party, and no enigma berry


def test_the_party_goes_out_as_the_same_three_blocks_the_trade_uses():
    blocks = ub.party_blocks([_mon(), _mon()])
    assert [len(b) for b in blocks] == [200, 200, 200]
    assert blocks[1] == bytes(200) and blocks[2] == bytes(200)
    with pytest.raises(ValueError):
        ub.party_blocks([_mon()] * 3)


# --- the controller ---------------------------------------------------------------------------

def _controller(**kw):
    return ub.BattleController([_mon(), _mon()], **kw)


def test_every_command_is_acked_for_both_battlers():
    """The master waits on gBattleControllerExecFlags == 0 [battle_util.c:185], so a command for the
    console's own battler needs our ack just as much as one for ours."""
    c = _controller()
    for battler in (bl.MASTER_BATTLER, bl.OUR_BATTLER):
        out = c.feed(bl.build(bl.BUFFER_A, battler, bytes([bl.INTROSLIDE, 0, 0, 0])))
        assert len(out) == 1
        rec = bl.parse(out[0])
        assert rec["buffer_id"] == bl.EXEC_CLEAR and rec["active_battler"] == battler


def test_a_reply_goes_out_before_its_ack():
    c = _controller()
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.CHOOSEACTION, 0, 0, 0])))
    assert [bl.parse(b)["buffer_id"] for b in out] == [bl.BUFFER_B, bl.EXEC_CLEAR]


def test_the_consoles_own_battler_gets_no_reply_from_us():
    """Hypothesis 2 in the write-up: it answers its own GETMONDATA locally from gEnemyParty
    [battle_controller_link_opponent.c:444], so ours would be a duplicate."""
    c = _controller()
    out = c.feed(bl.build(bl.BUFFER_A, bl.MASTER_BATTLER, bytes([bl.GETMONDATA, 0, 0, 0])))
    assert [bl.parse(b)["buffer_id"] for b in out] == [bl.EXEC_CLEAR]


def test_get_mon_data_answers_the_active_mon_when_the_mask_is_zero():
    c = _controller()
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER,
                          bytes([bl.GETMONDATA, bl.REQUEST_ALL_BATTLE, 0, 0])))
    rec = bl.parse(out[0])
    assert rec["payload"][:2] == bytes([bl.DATATRANSFER, bl.DATATRANSFER])
    assert int.from_bytes(rec["payload"][2:4], "little") == battle_mon.SIZE
    assert rec["payload"][4:4 + battle_mon.SIZE] == battle_mon.from_mon(_mon())


def test_get_mon_data_concatenates_the_mons_a_bitmask_asks_for():
    c = _controller()
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER,
                          bytes([bl.GETMONDATA, bl.REQUEST_ALL_BATTLE, 0b11, 0])))
    rec = bl.parse(out[0])
    assert int.from_bytes(rec["payload"][2:4], "little") == battle_mon.SIZE * 2


def test_an_unimplemented_get_mon_data_request_fails_loudly():
    """Only REQUEST_ALL_BATTLE is sent at battle start; a different id means the battle went
    somewhere this controller has not read, and silence would look like a protocol stall."""
    c = _controller()
    with pytest.raises(ValueError):
        c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.GETMONDATA, 1, 0, 0])))


def test_the_first_action_is_run_which_forfeits_a_link_battle():
    """Link battles skip the "can't run from a trainer" branch [battle_main.c:3239] and a running
    battler takes top turn order [:3548]."""
    c = _controller()
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.CHOOSEACTION, 0, 0, 0])))
    assert bl.parse(out[0])["payload"][:2] == bytes([bl.TWORETURNVALUES, bl.B_ACTION_RUN])


def test_forfeit_can_be_turned_off_to_fight_instead():
    c = _controller(forfeit=False)
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.CHOOSEACTION, 0, 0, 0])))
    assert bl.parse(out[0])["payload"][1] == bl.B_ACTION_USE_MOVE
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.CHOOSEMOVE, 0, 0, 0])))
    p = bl.parse(out[0])["payload"]
    assert p[1] == bl.RET_CHOSEN_MOVE
    assert (p[2] | (p[3] << 8)) == (0 | (bl.MASTER_BATTLER << 8))


def test_end_link_battle_records_the_outcome_and_finishes():
    c = _controller()
    assert not c.done
    out = c.feed(bl.build(bl.BUFFER_A, bl.OUR_BATTLER, bytes([bl.ENDLINKBATTLE, 7, 0, 0])))
    assert c.done and c.outcome == 7
    assert bl.parse(out[-1])["buffer_id"] == bl.EXEC_CLEAR


def test_replies_and_acks_from_the_console_owe_nothing():
    c = _controller()
    assert c.feed(bl.two_return_values(bl.MASTER_BATTLER, 0, 0)) == []
    assert c.feed(bl.ack(bl.MASTER_BATTLER, 1)) == []


# --- the engine, end to end -------------------------------------------------------------------

def _engine(**kw):
    """A HostTradeEngine parked at the Union Room's "do something" prompt, as the chat tests do."""
    from frlgsim import rfu, trade
    from frlgsim.host_trade import H_UROOM_PROMPT, HostTradeEngine
    kw.setdefault("union_room", True)
    kw.setdefault("union_room_battle", True)
    h = HostTradeEngine([_mon(), _mon()], **kw)
    h._words.clear()
    h._begin_card_exchange()
    h._words.clear()
    h._blocks.clear()
    h._expected = "card"
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    assert h.state == H_UROOM_PROMPT
    h._blocks.clear()
    return h


def _packet_slot(*words):
    from frlgsim import rfu
    slot = bytearray(rfu.serialize(rfu.send_packet_words(list(words))))
    slot[0] |= 0x60
    return bytes(slot)


def _queued_packets(h):
    from frlgsim import rfu
    return [w[1] for w in h._words if w[0] == rfu.SEND_PACKET]


def _sent(h):
    """The blocks queued for the console since the last clear, oldest first."""
    return [data for data, _ in h._blocks]


def test_a_battle_request_is_still_declined_unless_it_is_asked_for():
    from frlgsim.host_trade import HostTradeEngine
    h = _engine(union_room_battle=False)
    h.feed_child_slot(_packet_slot(0x41))
    assert _queued_packets(h) == [0x52] * HostTradeEngine.UR_PACKET_REPEAT


def test_the_whole_entry_sequence_runs_block_for_block():
    """SEND_PACKET 0x41 -> accept -> the 0x20 selection block -> the 31-byte header -> three
    200-byte party blocks -> the controller loop."""
    from frlgsim import trade
    from frlgsim.host_trade import H_UROOM_BATTLE, H_UROOM_BATTLE_LINK, HostTradeEngine
    h = _engine()
    h.feed_child_slot(_packet_slot(0x41))
    assert _queued_packets(h) == [0x51] * HostTradeEngine.UR_PACKET_REPEAT
    assert h.state == H_UROOM_BATTLE and h._expected == "battle_accept"

    h._blocks.clear()
    h._after_child_block(ub.COUNT_ACCEPT, ub.accept_block())
    assert _sent(h) == [ub.accept_block()]
    assert h._expected == "battle_header"

    h._blocks.clear()
    h._after_child_block(ub.COUNT_HEADER, ub.battler_header(ub.VERSION_FIRERED))
    assert _sent(h) == [ub.battler_header()]
    assert h._expected == "battle_party:0"

    ours = ub.party_blocks([_mon(), _mon()])
    for i in range(3):
        h._blocks.clear()
        h._after_child_block(trade.COUNT_PARTY, bytes(200))
        assert _sent(h) == [ours[i]]
    assert h.state == H_UROOM_BATTLE_LINK and h._expected == "battle_link"
    assert h.battle is not None


def test_the_selection_block_saying_decline_takes_us_back_to_the_prompt():
    from frlgsim.host_trade import H_UROOM_PROMPT
    h = _engine()
    h.feed_child_slot(_packet_slot(0x41))
    h._blocks.clear()
    h._after_child_block(ub.COUNT_ACCEPT, ub.accept_block(False))
    assert _sent(h) == [] and h.state == H_UROOM_PROMPT and h._expected is None


def _into_the_battle(**kw):
    from frlgsim import trade
    h = _engine(**kw)
    h.feed_child_slot(_packet_slot(0x41))
    h._after_child_block(ub.COUNT_ACCEPT, ub.accept_block())
    h._after_child_block(ub.COUNT_HEADER, ub.battler_header(ub.VERSION_FIRERED))
    for _ in range(3):
        h._after_child_block(trade.COUNT_PARTY, bytes(200))
    h._blocks.clear()
    return h


def test_the_controller_loop_acks_a_command_of_any_size():
    """Link buffer records have no fixed block count, so the size check that guards every other
    block must not apply here [PrepareBufferDataTransferLink, battle_controllers.c:412]."""
    h = _into_the_battle()
    h._after_child_block(99, bl.build(bl.BUFFER_A, bl.MASTER_BATTLER,
                                      bytes([bl.INTROSLIDE, 0, 0, 0])))
    assert [bl.parse(b)["buffer_id"] for b in _sent(h)] == [bl.EXEC_CLEAR]


def test_the_first_get_mon_data_is_answered_with_our_mon():
    h = _into_the_battle()
    h._after_child_block(99, bl.build(bl.BUFFER_A, bl.OUR_BATTLER,
                                      bytes([bl.GETMONDATA, bl.REQUEST_ALL_BATTLE, 0, 0])))
    out = [bl.parse(b) for b in _sent(h)]
    assert [r["buffer_id"] for r in out] == [bl.BUFFER_B, bl.EXEC_CLEAR]
    assert out[0]["payload"][4:4 + battle_mon.SIZE] == battle_mon.from_mon(_mon())


def test_the_battle_ends_and_stops_expecting_blocks():
    h = _into_the_battle()
    h._after_child_block(99, bl.build(bl.BUFFER_A, bl.OUR_BATTLER,
                                      bytes([bl.ENDLINKBATTLE, 3, 0, 0])))
    assert h.battle.done and h.battle.outcome == 3
    assert h._expected is None
