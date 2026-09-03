"""Union Room 'do something' prompt: after the cards the console talks in SEND_PACKETs
[union_room.c:2928, :2955] and the parent answers with ACCEPT / DECLINE packets
[UR_STATE_HANDLE_ACTIVITY_REQUEST, union_room.c:3151]. Seen on hardware in u06: the console sent
SEND_PACKET 0x48 (ACTIVITY_CARD | IN_UNION_ROOM) and waited on us."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from frlgsim import mon, rfu, trade  # noqa: E402
from frlgsim.host_trade import H_ENTRY_CARD, H_UROOM_PROMPT, HostTradeEngine  # noqa: E402


def _mon(marker):
    return mon.Mon(bytes([marker & 0xFF]) + b"\x00" * 99)


def _engine(union_room=True):
    h = HostTradeEngine([_mon(1)], union_room=union_room)
    h._words.clear()
    h._begin_card_exchange()
    h._words.clear()
    h._blocks.clear()
    h._expected = "card"
    return h


def _packet_slot(*words):
    # The child stamps its rolling tag in word0's low byte; parse_slot masks it off.
    slot = bytearray(rfu.serialize(rfu.send_packet_words(list(words))))
    slot[0] |= 0x60
    return bytes(slot)


def _queued_packets(h):
    return [w[1] for w in h._words if w[0] == rfu.SEND_PACKET]


def test_send_packet_round_trips_through_rfu():
    words = rfu.send_packet_words([0x51])
    assert words == [rfu.SEND_PACKET, 0x51, 0, 0, 0, 0, 0]
    rec = rfu.parse_slot(_packet_slot(0x48))
    assert rec["op"] == rfu.SEND_PACKET and rec["packet"] == [0x48, 0, 0, 0, 0, 0]


def test_card_block_moves_a_union_room_host_to_the_prompt():
    h = _engine()
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(range(100)))
    assert h.state == H_UROOM_PROMPT and h._expected is None
    assert h.child_card == bytes(range(100))


def test_card_block_keeps_the_trade_centre_path_without_the_option():
    h = _engine(union_room=False)
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    assert h.state == H_ENTRY_CARD and h._expected == "warp1"


def test_greetings_request_is_accepted_and_the_standby_echoed():
    h = _engine()
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    h.feed_child_slot(_packet_slot(0x48))
    assert _queued_packets(h) == [0x51] * HostTradeEngine.UR_PACKET_REPEAT
    assert h.uroom_requests == [(0x48, 0, 0, 0, 0, 0)]
    # Reliable dedups retransmits; the same packet in the very next frame must not answer twice.
    h.feed_child_slot(_packet_slot(0x48))
    assert len(_queued_packets(h)) == HostTradeEngine.UR_PACKET_REPEAT
    # But a second Salut chosen later is a new request (u08: the console hung on our silence).
    for _ in range(30):
        h.feed_child_slot(rfu.idle_slot())
    h.feed_child_slot(_packet_slot(0x48))
    assert len(_queued_packets(h)) == 2 * HostTradeEngine.UR_PACKET_REPEAT
    # Both sides SetLinkStandbyCallback after the card message [union_room.c:2995].
    h._words.clear()
    h.feed_child_slot(rfu.serialize(rfu.exit_standby_words(1)))
    assert [w[0] for w in h._words] and all(w[0] == rfu.READY_EXIT_STANDBY for w in h._words)
    assert h.state == H_UROOM_PROMPT


def test_battle_and_chat_are_declined_exit_is_silent():
    h = _engine()
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    h.feed_child_slot(_packet_slot(0x41))
    h.feed_child_slot(_packet_slot(0x45))
    assert _queued_packets(h) == [0x52] * (2 * HostTradeEngine.UR_PACKET_REPEAT)
    h._words.clear()
    h.feed_child_slot(_packet_slot(0x40))
    assert _queued_packets(h) == []


def test_trade_request_is_accepted_with_its_species_and_level():
    h = _engine()
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    h.feed_child_slot(_packet_slot(0x44, 25, 30))
    assert _queued_packets(h) == [0x51] * HostTradeEngine.UR_PACKET_REPEAT
    assert h.uroom_requests[-1][:3] == (0x44, 25, 30)


def test_packets_are_ignored_outside_the_union_room():
    h = _engine(union_room=False)
    h.feed_child_slot(_packet_slot(0x48))
    assert _queued_packets(h) == []


def test_exit_at_the_prompt_answers_the_close_link_handshake():
    """u10: after Retour the console sent READY_CLOSE_LINK and waited; WaitAllReadyToCloseLink
    [link_rfu_2.c:1471] needs the parent's READY_CLOSE_LINK before the child disconnects itself."""
    from frlgsim.host_trade import H_CLOSE
    h = _engine()
    h._after_child_block(trade.COUNT_TRAINER_CARD, bytes(100))
    h.feed_child_slot(_packet_slot(0x40))
    h._words.clear()
    h.feed_child_slot(rfu.serialize(rfu.close_link_words(2)))
    assert h.state == H_CLOSE
    assert [w[0] for w in h._words] and all(w[0] == rfu.READY_CLOSE_LINK for w in h._words)
    assert h.close_confirmed


def test_close_link_outside_the_room_prompt_is_still_ignored():
    h = _engine(union_room=False)
    h.feed_child_slot(rfu.serialize(rfu.close_link_words(2)))
    assert h.state == H_ENTRY_CARD and not h._words
