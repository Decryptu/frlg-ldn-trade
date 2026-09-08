"""The launcher's own send path, offline - the exact function a hardware run will call.

`tests/test_pia4.py` proves the framing against the console's own packets; this proves that
`swsh_connect.wrap` puts a Local Protocol ack inside it correctly, so the run spends its association
on a question rather than on a typo. There is no capture of one of our version-4 packets yet, so
this is a self-consistency check with the receiver's derivation on the other side of it.
"""

import struct

import swsh_connect

from pokeldn.ldn import (local_protocol as lp, mesh_protocol as mesh, pia4, reliable5,
                        rtt_protocol as rtt, station_protocol as stp)
from pokeldn.swsh.session import packet_iv, session_keys

APP_DATA = bytes.fromhex("0330112400000000051800008b718ac6")     # sw01's own advertisement
OUR_MAC = bytes.fromhex("7e5f4c3b2a19")


class _Net:
    application_data = APP_DATA


def _read_back(packet, mac=OUR_MAC):
    """Everything the console does with a packet of ours, in its order."""
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, mac, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    assert plain is not None, "the tag did not verify"
    header, body = pia4.parse_messages(plain)[0]
    return h, pia4.parse_message_header(header), body


def _ack(station=0, nonce8=b"\x01" * 8, seq=7):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8,
                             lp.build_ack(seq), lp.PROTOCOL, station)


def test_the_ack_the_run_sends_reads_back_as_an_ack():
    h, fields, body = _read_back(_ack())
    assert h.version == 4 and h.encrypted and len(h.tag) == pia4.TAG_SIZE
    assert fields["protocol"] == lp.PROTOCOL and fields["flags"] == pia4.MESSAGE_FLAGS
    assert fields["source"] == stp.ldn_constant_id(OUR_MAC)
    assert lp.parse_ack(body) == 7


def test_the_station_byte_reaches_the_header_and_the_iv_together():
    """The sweep only reads if the two move as one; a header saying 1 and an IV built on 0 would
    fail the tag and look exactly like the console ignoring us."""
    for station in (0, 1, 2):
        h, _, body = _read_back(_ack(station=station))
        assert h.station == station
        assert lp.parse_ack(body) == 7


def test_the_packet_is_padded_the_way_the_console_pads_its_own():
    """0xFF to a multiple of sixteen, which is what sw01's 160-byte ciphertext measures."""
    packet = _ack()
    assert (len(packet) - pia4.HEADER_SIZE) % 16 == 0
    keys = session_keys(_Net())
    h = pia4.PiaHeader4.parse(packet)
    plain = pia4.decrypt_payload(keys.session_key, packet_iv(keys, OUR_MAC, h.nonce8, h.station),
                                 pia4.ciphertext(packet), h.tag)
    used = pia4.MESSAGE_HEADER_SIZE + 0x14                       # the ack is twenty bytes
    assert set(plain[used:]) <= {0xFF}


def _join(ack_id=0x11223344, station=0, nonce8=b"\x02" * 8, port=0):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8,
                             mesh.build_join_request(ack_id), mesh.PROTOCOL, station, port=port)


def test_the_join_request_the_run_sends_is_what_0x017c1700_checks():
    """Sword's type-1 handler reads byte [1] and the last four bytes, and nothing else."""
    h, fields, body = _read_back(_join())
    assert fields["protocol"] == mesh.PROTOCOL == 0x18
    assert body == bytes([mesh.JOIN_REQUEST, 0xFD]) + struct.pack(">I", 0x11223344)
    assert mesh.read_ack_id(body) == 0x11223344


def test_the_join_travels_on_the_unreliable_port_by_default():
    # `--join-port` exists because the update mesh uses the reliable one and the join does not;
    # the default has to be the port the request is actually sent on.
    args = swsh_connect.build_parser().parse_args([])
    assert args.join_port == mesh.PORT_UNRELIABLE == 0
    assert args.join_station_index == mesh.STATION_INDEX_INVALID == 0xFD
    _, fields, _ = _read_back(_join(port=args.join_port))
    assert fields["port"] == 0


def test_joining_is_off_unless_it_is_asked_for():
    # An unasked-for join would change two things at once on a run bought for the handshake.
    assert swsh_connect.build_parser().parse_args([]).join is False
    assert swsh_connect.build_parser().parse_args(["--join"]).join is True


# --------------------------------------------------------------------------- answering sw29
# The two protocols the console left unanswered. Both send paths are checked as BYTES, decrypted
# back through the console's own derivation, because that is what a run will actually put on the air.

SW29_RTT = bytes.fromhex("000000000000000000000e7840e6df87")


def _data(payload, protocol, station=0, nonce8=b"\x03" * 8, destination=1, flags=0x01):
    keys = session_keys(_Net())
    return swsh_connect.wrap(keys, OUR_MAC, stp.ldn_constant_id(OUR_MAC), nonce8, payload,
                             protocol, station, message_flags=flags, destination=destination)


def test_the_rtt_answer_is_sixteen_bytes_and_echoes_what_we_do_not_read():
    h, fields, body = _read_back(_data(rtt.response_for_v4(SW29_RTT), rtt.PROTOCOL))
    assert fields["protocol"] == rtt.PROTOCOL == 0x58
    assert len(body) == rtt.SIZE_V4 == 16
    assert body[0] == rtt.RESPONSE and body[1:] == SW29_RTT[1:]
    assert rtt.parse_v4(body)["timestamp"] == rtt.parse_v4(SW29_RTT)["timestamp"]


def test_our_data_messages_carry_the_bitmap_bit_for_the_console():
    # the console sends 2 to us at station index 1; the bit for station 0 is 1
    _, fields, _ = _read_back(_data(rtt.response_for_v4(SW29_RTT), rtt.PROTOCOL))
    assert fields["destination"] == 1
    assert swsh_connect.build_parser().parse_args([]).data_destination == 1


def test_replaying_sw29s_own_stream_acks_it_through_sequence_twenty():
    """The 1637 messages sw29 received are 20 sequence ids. One ack per advance, never a re-ack."""
    seen, acks, through = set(), [], 0
    for seq in [1] + list(range(2, 21)) * 8:          # the retransmit train, in arrival order
        seen.add(seq)
        nxt = reliable5.contiguous_through(seen, through)
        if nxt != through:
            through = nxt
            acks.append(reliable5.build_ack_message(through + 1, lowest_pending=1))
    assert through == 20
    assert len(acks) == 20                            # one per advance, not one per message
    last = reliable5.parse(acks[-1])
    assert last["is_ack"] and last["sequence_id"] == reliable5.ACK_SEQUENCE == 0xFFFF
    entry = reliable5.parse_ack_payload(last["payload"])["entries"][0]
    assert entry["ack_id"] == 21 and entry["field_0x50"] == 20
    assert entry["mask"] == b"\0" * 16                # a contiguous run leaves nothing in the mask


def test_a_gap_stops_the_run_rather_than_being_skipped():
    assert reliable5.contiguous_through({1, 2, 4, 5}) == 2
    assert reliable5.contiguous_through({2, 3}) == 0   # nothing contiguous from the start
    assert reliable5.contiguous_through({2, 3}, start=1) == 3


def test_the_data_shaped_selection_offer_is_off_unless_it_is_asked_for():
    """sx14 died of `args.box_open.split(",")` with the flag absent, inside the receiver. Every
    flag combination this branch reads is proven here before a run carries it.
    """
    args = swsh_connect.build_parser().parse_args([])
    assert args.selection_offer is False and args.selection_offer_data is False
    on = swsh_connect.build_parser().parse_args(["--selection-offer", "--selection-offer-data"])
    assert on.selection_offer is True and on.selection_offer_data is True


def test_neither_answer_happens_unless_it_is_asked_for():
    args = swsh_connect.build_parser().parse_args([])
    assert args.answer_rtt is False and args.ack_reliable is False


# --- The post-offer queue, session 60 ----------------------------------------------------------
#
# sw95 died in the middle of a trade because this queue held two different kinds of thing: built
# payloads for --open-content and plain ints for --box-commands, drained through a builder that
# assumed ints. The second entry raised, the nursery went down, and the player saw the console
# report the communication as interrupted seconds after our Pokemon reached their screen.

from pokeldn.swsh import trade as swsh_trade                          # noqa: E402


def drain(queue):
    """What the launcher's drain branch does: pop a payload and send it, nothing else."""
    return queue.pop(0)


def test_both_flags_seed_the_queue_with_payloads_and_nothing_else():
    opens = [swsh_trade.open_content(int(c)) for c in "40,50".split(",")]
    boxes = [swsh_trade.box_sync_state(int(c)) for c in "1,2,4".split(",")]
    for queue in (opens, boxes):
        assert all(isinstance(p, bytes) for p in queue)
        while queue:
            payload = drain(queue)
            assert isinstance(payload, bytes) and len(payload) >= 4
            swsh_trade.parse(payload)                 # a real message, id and body


def test_the_openers_and_the_commands_are_different_ids():
    assert swsh_trade.parse(swsh_trade.open_content(40))[0] == 10040
    assert swsh_trade.parse(swsh_trade.box_sync_state(4))[0] == swsh_trade.POKEMON_TRADE


def test_a_spaced_queue_drains_every_entry_and_not_just_the_first():
    """sx02's bug, as a model of the two loops rather than a re-read of the code.

    The drain has to sit where a payload is CHOSEN - a loop that runs every period - and not
    where a queued payload is ACKNOWLEDGED. In the ack branch the first "not yet" leaves nothing
    pending, so nothing is queued, so no queued payload is ever acked again and the drain never
    runs a second time: one command in 46 seconds where eight were meant to span the accept.
    """
    def run(drain_in_ack, ticks=200, period=5.0, tick=0.3):
        # The first entry is seeded directly when our own offer is acknowledged, which is why
        # sx02 sent command 1 and then nothing: the seeding worked and the DRAIN did not.
        queue, sent, now = [2, 3, 4], [], 0.0
        pending, box_next = 1, period
        for _ in range(ticks):
            if not drain_in_ack and pending is None and queue and now >= box_next:
                pending, box_next = queue.pop(0), now + period
            if pending is not None:
                sent.append((now, pending))
                acked = pending
                pending = None
                if drain_in_ack and queue and now >= box_next:
                    pending, box_next = queue.pop(0), now + period
                del acked
            now += tick
        return sent

    assert [p for _, p in run(drain_in_ack=False)] == [1, 2, 3, 4]
    assert [p for _, p in run(drain_in_ack=True)] == [1]          # the shape sx02 shipped

    spaced = run(drain_in_ack=False)
    gaps = [round(b[0] - a[0], 1) for a, b in zip(spaced, spaced[1:])]
    assert all(g >= 5.0 for g in gaps), gaps
