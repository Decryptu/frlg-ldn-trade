"""Union Room chat [src/union_room_chat.c]. The console asks with SEND_PACKET 0x45
(ACTIVITY_CHAT | IN_UNION_ROOM); once the parent ACCEPTs, both members SendBlock a 0x28-byte JOIN
[ChatEntryRoutine_Join, union_room_chat.c:429] and then one block per line typed. The child leaves
with LEAVE and waits for the parent to drop the link [union_room_chat.c:657]."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from frlgsim import charmap, mon, rfu, trade, uroom_chat  # noqa: E402
from frlgsim.host_trade import H_UROOM_CHAT, H_UROOM_PROMPT, HostTradeEngine  # noqa: E402


def _mon(marker):
    return mon.Mon(bytes([marker & 0xFF]) + b"\x00" * 99)


def _engine(**kw):
    kw.setdefault("union_room", True)
    h = HostTradeEngine([_mon(1)], **kw)
    h._words.clear()
    h._begin_card_exchange()
    h._words.clear()
    h._blocks.clear()
    h._expected = "card"
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    assert h.state == H_UROOM_PROMPT
    return h


def _packet_slot(*words):
    slot = bytearray(rfu.serialize(rfu.send_packet_words(list(words))))
    slot[0] |= 0x60
    return bytes(slot)


def _queued_packets(h):
    return [w[1] for w in h._words if w[0] == rfu.SEND_PACKET]


def _labels(h):
    return [label for _, label in h._blocks]


# --- the block itself -------------------------------------------------------------------------

def test_join_block_has_the_decomp_layout():
    """PrepareSendBuffer_Join: [0] command, [1..8] name, [1 + PLAYER_NAME_LENGTH + 1] mpid."""
    b = uroom_chat.build(uroom_chat.JOIN, "PkCamp", multiplayer_id=0)
    assert len(b) == uroom_chat.BLOCK_SIZE == 0x28
    assert b[0] == uroom_chat.JOIN == 2
    assert b[1:1 + 6] == charmap.encode("PkCamp")
    assert b[1 + uroom_chat.NAME_FIELD - 1] == charmap.EOS   # the name field is EOS-terminated
    assert b[uroom_chat.PAYLOAD_OFF] == 0


def test_chat_block_carries_the_text_after_the_name_field():
    b = uroom_chat.build(uroom_chat.CHAT, "PkCamp", text="HELLO")
    assert b[0] == uroom_chat.CHAT == 1
    assert b[uroom_chat.PAYLOAD_OFF:uroom_chat.PAYLOAD_OFF + 5] == charmap.encode("HELLO")
    assert uroom_chat.parse(b) == {"cmd": uroom_chat.CHAT, "name": "PkCamp",
                                   "multiplayer_id": None, "text": "HELLO"}
    assert uroom_chat.describe(uroom_chat.parse(b)) == "PkCamp: HELLO"


@pytest.mark.parametrize("cmd", [uroom_chat.JOIN, uroom_chat.LEAVE,
                                 uroom_chat.DROP, uroom_chat.DISBAND])
def test_non_chat_blocks_round_trip_with_their_multiplayer_id(cmd):
    msg = uroom_chat.parse(uroom_chat.build(cmd, "SWITCH", multiplayer_id=1))
    assert msg == {"cmd": cmd, "name": "SWITCH", "multiplayer_id": 1, "text": ""}
    assert uroom_chat.describe(msg) == f"[{uroom_chat.NAMES[cmd]}] SWITCH"


def test_a_full_length_line_still_fits_the_block():
    """messageEntryBuffer is 2 * MESSAGE_BUFFER_NCHAR + 1 = 31 bytes, exactly the block's tail."""
    assert uroom_chat.TEXT_FIELD == 31
    text = "A" * (uroom_chat.TEXT_FIELD - 1)
    assert uroom_chat.parse(uroom_chat.build(uroom_chat.CHAT, "PkCamp", text=text))["text"] == text


@pytest.mark.parametrize("bad", ["", "A" * 31, "hello あ"])
def test_unsendable_lines_are_rejected_before_a_run(bad):
    with pytest.raises(ValueError):
        uroom_chat.check_text(bad)


def test_a_bad_chat_message_fails_at_engine_construction():
    with pytest.raises(ValueError):
        HostTradeEngine([_mon(1)], union_room=True, union_room_chat=True,
                        chat_messages=["A" * 40])


# --- the engine -------------------------------------------------------------------------------

def test_chat_is_declined_unless_it_is_asked_for():
    h = _engine()
    h.feed_child_slot(_packet_slot(0x45))
    assert _queued_packets(h) == [0x52] * HostTradeEngine.UR_PACKET_REPEAT
    assert h.state == H_UROOM_PROMPT


def test_chat_request_is_accepted_and_its_standby_echoed():
    h = _engine(union_room_chat=True)
    h.feed_child_slot(_packet_slot(0x45))
    assert _queued_packets(h) == [0x51] * HostTradeEngine.UR_PACKET_REPEAT
    assert h.state == H_UROOM_CHAT and h._expected == "uroom_chat"
    # UR_STATE_START_ACTIVITY_LINK calls SetLinkStandbyCallback before the fade [union_room.c:3096].
    h._words.clear()
    h.feed_child_slot(rfu.serialize(rfu.exit_standby_words(1)))
    assert h._words and all(w[0] == rfu.READY_EXIT_STANDBY for w in h._words)
    assert h.state == H_UROOM_CHAT


def test_the_consoles_join_is_answered_with_ours():
    h = _engine(union_room_chat=True)
    h.feed_child_slot(_packet_slot(0x45))
    h._blocks.clear()
    h._after_child_block(trade.COUNT_RIBBON,
                         uroom_chat.build(uroom_chat.JOIN, "SWITCH", multiplayer_id=1))
    assert _labels(h) == ["host:chat_join"]
    sent = uroom_chat.parse(h._blocks[0][0])
    assert sent["cmd"] == uroom_chat.JOIN and sent["multiplayer_id"] == 0
    assert h.chat_received[-1]["name"] == "SWITCH"
    # Members keep sending blocks unprompted, so the expectation must not be cleared.
    assert h._expected == "uroom_chat"


def test_a_second_join_does_not_send_ours_twice():
    h = _engine(union_room_chat=True)
    h.feed_child_slot(_packet_slot(0x45))
    for _ in range(2):
        h._after_child_block(trade.COUNT_RIBBON,
                             uroom_chat.build(uroom_chat.JOIN, "SWITCH", multiplayer_id=1))
    assert _labels(h).count("host:chat_join") == 1


def test_typed_lines_are_recorded():
    h = _engine(union_room_chat=True)
    h.feed_child_slot(_packet_slot(0x45))
    h._after_child_block(trade.COUNT_RIBBON,
                         uroom_chat.build(uroom_chat.CHAT, "SWITCH", text="SALUT"))
    assert h.chat_received[-1]["text"] == "SALUT"
    assert ("uroom_chat_recv", uroom_chat.CHAT, "SWITCH") in h.trace


def test_queued_lines_go_out_one_at_a_time_after_the_gap():
    h = _engine(union_room_chat=True, chat_messages=["HELLO", "BYE"])
    h.feed_child_slot(_packet_slot(0x45))
    h._after_child_block(trade.COUNT_RIBBON,
                         uroom_chat.build(uroom_chat.JOIN, "SWITCH", multiplayer_id=1))
    h._blocks.clear()                      # our JOIN has drained
    gap = h.timing.chat_message_gap_frames
    for _ in range(gap):
        h._tick_chat_outbox()
    assert _labels(h) == []                # still inside the gap after our JOIN
    h._tick_chat_outbox()
    assert [uroom_chat.parse(b)["text"] for b, _ in h._blocks] == ["HELLO"]
    h._blocks.clear()
    for _ in range(gap):
        h._tick_chat_outbox()
    assert _labels(h) == []
    h._tick_chat_outbox()
    assert [uroom_chat.parse(b)["text"] for b, _ in h._blocks] == ["BYE"]
    # Drained: the chat stays open, nothing more is queued.
    h._blocks.clear()
    for _ in range(3 * gap):
        h._tick_chat_outbox()
    assert _labels(h) == [] and h._chat_send_wait is None


def test_an_in_flight_block_defers_the_next_line():
    h = _engine(union_room_chat=True, chat_messages=["HELLO"])
    h.feed_child_slot(_packet_slot(0x45))
    h._after_child_block(trade.COUNT_RIBBON,
                         uroom_chat.build(uroom_chat.JOIN, "SWITCH", multiplayer_id=1))
    for _ in range(3 * h.timing.chat_message_gap_frames):
        h._tick_chat_outbox()              # our JOIN is still queued
    assert _labels(h) == ["host:chat_join"]


@pytest.mark.parametrize("cmd", [uroom_chat.LEAVE, uroom_chat.DROP, uroom_chat.DISBAND])
def test_the_console_leaving_the_chat_closes_the_link(cmd):
    h = _engine(union_room_chat=True)
    h.feed_child_slot(_packet_slot(0x45))
    assert not h.done
    h._after_child_block(trade.COUNT_RIBBON,
                         uroom_chat.build(cmd, "SWITCH", multiplayer_id=1))
    assert h.done
