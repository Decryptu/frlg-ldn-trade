"""Sword/Shield's application messages: the id, the protobuf body, and the sync conversation.

The five payloads this project has actually measured are asserted against their captured bytes.
Everything past them is `SYNC_ANSWERS`, which is another project's reading - the tests hold its
SHAPE, so a run that measures the real thing changes one table and these still say what they mean.
"""
import pytest

from pokeldn.swsh import pokemon, trade
from pokeldn import gen8


def test_the_five_payloads_this_project_measured_are_built_exactly():
    """sw70's capture, via scratchpad/sw_app_payloads.py: these five and no others."""
    assert trade.sync(trade.SYNC_PING, trade.PING).hex() == "610000000a00"
    assert trade.sync(trade.SYNC_PING, trade.PING_REPLY).hex() == "610000001200"
    assert trade.sync(trade.SYNC_PING, trade.PING_SYNCED).hex() == "610000001a00"
    assert trade.result().hex() == "60ea00000a00"
    assert trade.im_ready().hex() == "60ea000012020801"


def test_a_message_is_a_little_endian_id_and_a_body():
    assert trade.message(97, b"\x0a\x00") == bytes.fromhex("610000000a00")
    assert trade.parse(bytes.fromhex("610000000a00")) == (97, b"\x0a\x00")
    assert trade.parse(trade.im_ready()) == (60000, bytes.fromhex("12020801"))
    with pytest.raises(ValueError, match="message id"):
        trade.parse(b"\x61\x00\x00")


def test_im_ready_carries_a_bool_and_can_say_no():
    assert trade.im_ready(False).hex() == "60ea000012020800"
    assert trade.parse(trade.im_ready(False))[0] == trade.BLOCK


def test_varints_and_fields_follow_the_protobuf_wire_format():
    assert trade.varint(0) == b"\x00"
    assert trade.varint(1) == b"\x01"
    assert trade.varint(127) == b"\x7f"
    assert trade.varint(128) == b"\x80\x01"
    assert trade.varint(300) == b"\xac\x02"
    assert trade.field(1, b"") == b"\x0a\x00"
    assert trade.field(2, b"\xff") == b"\x12\x01\xff"
    assert trade.field_varint(1, 1) == b"\x08\x01"
    with pytest.raises(ValueError):
        trade.varint(-1)


def test_a_trade_message_wraps_a_pk8_in_two_nested_fields():
    """PokemonTradeDataHolder{pokemon{serializePokemonParam}} - the game's own schema."""
    plain = bytearray(bytes(range(256)) * 2)[:gen8.SIZE_PARTY]
    plain[0x04:0x06] = b"\x00\x00"
    pk8 = pokemon.encrypt(bytes(plain))

    msg = trade.pokemon_trade(pk8)
    mid, body = trade.parse(msg)
    assert mid == trade.POKEMON_TRADE
    # field 1, length-delimited, holding field 1, length-delimited, holding the PK8
    assert body[0] == 0x0A and body[3] == 0x0A
    assert body.endswith(pk8)
    assert len(msg) > len(pk8)
    # and it round trips through the reader, so what we would send is a Pokemon
    assert pokemon.read(body[-len(pk8):])["species"] == pokemon.read(pk8)["species"]


def test_a_trade_message_refuses_anything_that_is_not_a_pk8():
    with pytest.raises(ValueError, match="not a PK8"):
        trade.pokemon_trade(b"\x00" * 100)


def test_the_sync_answers_are_keyed_and_valued_by_whole_payloads():
    for received, replies in trade.SYNC_ANSWERS.items():
        mid, _ = trade.parse(received)
        assert mid in trade.SYNC_IDS, f"{mid} answers a holder that is not a sync holder"
        assert replies, "an entry with no reply should not be an entry"
        for reply in replies:
            trade.parse(reply)                       # every reply is a well-formed message


def test_the_ping_answer_is_the_one_the_hardware_confirmed():
    """sw64: answering the ping walks the game forward; sw62: sending pingReply first stops it."""
    replies = trade.answers_for(bytes.fromhex("610000000a00"))
    assert [r.hex() for r in replies] == ["610000001200", "610000000a00"]
    assert trade.answers_for(bytes.fromhex("610000001a00"))[1] == trade.result()


def test_a_payload_with_no_rule_answers_nothing_and_is_reported():
    unknown = trade.sync(999, trade.PING)
    assert trade.answers_for(unknown) == ()
    assert trade.unanswered([unknown, bytes.fromhex("610000000a00")]) == [unknown]
    assert trade.unanswered([bytes.fromhex("610000000a00")]) == []


# the four distinct payloads sw70's console sent on 0x7C, in the order it first sent them
SW70_ON_7C = ["610000000a00", "610000001200", "610000001a00", "60ea00000a00"]


def test_the_answer_policy_never_falls_silent_where_the_mirror_spoke():
    """sw68 and sw70 reached the snapshot by echoing. A table that answered less would lose that."""
    for hexed in SW70_ON_7C:
        said = bytes.fromhex(hexed)
        payload, queue = trade.next_answer(said)
        assert payload, f"nothing to say to {hexed}"
        if not trade.answers_for(said):
            assert payload == said, "with no rule the policy must still mirror"
            assert queue == []


def test_a_multi_payload_rule_goes_out_in_order_one_per_sequence():
    said = bytes.fromhex("610000000a00")
    first, queue = trade.next_answer(said)
    assert first.hex() == "610000001200"                  # pingReply
    second, queue = trade.next_answer(said, queue)
    assert second.hex() == "610000000a00"                 # then ping
    assert queue == []
    # and once the queue is spent the policy is the mirror again
    third, queue = trade.next_answer(said, queue)
    assert third.hex() == "610000001200"


def test_the_policy_changes_exactly_two_things_against_sw70s_mirror():
    """CLAUDE.md rule 4 is one variable per run, so the size of the change is worth asserting.

    Precisely: the FIRST thing we say changes only for `ping`, where the mirror echoed ping and the
    rule answers pingReply. For `pingSynced` the first reply is still the echo and the rule adds a
    `result{}` behind it. The other two payloads sw70 saw are untouched.
    """
    first_differs = [h for h in SW70_ON_7C
                     if trade.next_answer(bytes.fromhex(h))[0] != bytes.fromhex(h)]
    assert first_differs == ["610000000a00"], "only the answer to ping changes what we say first"

    follow_ups = {h: trade.next_answer(bytes.fromhex(h))[1] for h in SW70_ON_7C}
    assert follow_ups["610000001a00"] == [trade.result()], "pingSynced gains a result{} behind it"
    assert follow_ups["610000000a00"] == [bytes.fromhex("610000000a00")]
    assert follow_ups["610000001200"] == [] and follow_ups["60ea00000a00"] == []


# sw75, off the wire: the two members of the trade RPC pair the console sent when the trade screen
# opened. The station id in them is the console's own, and our seat record holds the same number.
SW75_RPC_10000 = bytes.fromhex(
    "5e9c00000a19081e10904e188080a08a8fc4c8cdeb0120c0502a0400000000")
SW75_RPC_20000 = bytes.fromhex(
    "5e9c00000a1a081e10a09c01188080a08a8fc4c8cdeb0120c0502a04000018fc")
SW75_HOST_STATION = 16977200745185542144
OUR_STATION = 1317762632229847040


def test_the_consoles_own_rpcs_are_read_and_rebuilt_byte_for_byte():
    """The test that makes the reader trustworthy: build back what it took apart."""
    for raw, base, body in ((SW75_RPC_10000, 10000, "00000000"),
                            (SW75_RPC_20000, 20000, "000018fc")):
        got = trade.parse_rpc(raw)
        assert got["offset"] == 30, "40030 is 40000 + 30 and the message says so"
        assert got["base"] == base
        assert got["station_id"] == SW75_HOST_STATION, "field 3 is the SENDER's station id"
        assert got["clock"] == 10304
        assert got["body"].hex() == body
        assert trade.build_rpc(got["offset"], got["base"], got["station_id"],
                               got["clock"], got["body"]) == raw


def test_the_pair_carries_both_bases_and_the_same_clock():
    a, b = trade.parse_rpc(SW75_RPC_10000), trade.parse_rpc(SW75_RPC_20000)
    assert (a["base"], b["base"]) == trade.RPC_BASES == (10000, 20000)
    assert a["clock"] == b["clock"], "a pair shares its clock"
    assert a["station_id"] == b["station_id"]


def test_our_answer_carries_our_station_id_and_advances_the_clock():
    answer = trade.answer_rpc(SW75_RPC_10000, OUR_STATION, clock_delta=5)
    got = trade.parse_rpc(answer)
    assert got["station_id"] == OUR_STATION, "it must not be the console's own id"
    assert got["clock"] == 10304 + 5
    # everything else is the console's, unchanged
    assert (got["offset"], got["base"], got["body"]) == (30, 10000, b"\x00\x00\x00\x00")


def test_answering_something_that_is_not_an_rpc_gives_nothing():
    assert trade.answer_rpc(trade.im_ready(), OUR_STATION) is None
    assert trade.parse_rpc(bytes.fromhex("610000000a00")) is None
    assert trade.parse_rpc(trade.message(trade.RPC_ENVELOPE, b"\x08\x01")) is None


def test_the_policy_answers_a_trade_rpc_by_rebuilding_it_not_by_echoing_it():
    """Echoing an RPC would hand the console its own station id back - the one field that moves."""
    payload, queue = trade.next_answer(SW75_RPC_10000, station_id=OUR_STATION)
    assert payload != SW75_RPC_10000, "an echo is exactly what must not happen here"
    assert trade.parse_rpc(payload)["station_id"] == OUR_STATION
    assert queue == []
    # without a station id there is nothing to build with, so the policy falls back to the mirror
    assert trade.next_answer(SW75_RPC_10000)[0] == SW75_RPC_10000
    # and the sync table still wins where it has a rule
    assert trade.next_answer(bytes.fromhex("610000000a00"),
                             station_id=OUR_STATION)[0].hex() == "610000001200"
