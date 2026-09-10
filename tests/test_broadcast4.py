"""Protocol 0x84's framing, against the three messages our own console sent.

Those three are the whole point: a builder that cannot reproduce a message the console sent is a
builder we have no reason to trust, and every earlier layer of this project was settled the same
way.
"""
import random
import zlib

import pytest

from pokeldn.ldn import broadcast4

# off the wire, headers only - the bodies are a player's data and stay out of the repository.
CONTROL = bytes.fromhex("110000000000ffff00000d80057c000500000000")
DATA_0 = bytes.fromhex("120000000001ffff00000000")
DATA_2 = bytes.fromhex("120000000005ffff00000002")
SEED = 71          # this test's fixture seed


def test_the_control_message_the_console_sent_is_rebuilt_byte_for_byte():
    built = broadcast4.build_control(sequence=0, total=3456, chunk_size=0x057C)
    assert built == CONTROL
    assert len(built) == broadcast4.CONTROL_SIZE == 20


def test_the_two_data_headers_the_console_sent_are_rebuilt_byte_for_byte():
    for header, sequence, index in ((DATA_0, 1, 0), (DATA_2, 5, 2)):
        payload, _ = broadcast4.build_fragment(sequence, index, b"", compress=False)
        assert payload == header, f"fragment {index}"


def test_parsing_the_console_messages_gives_back_what_they_say():
    control = broadcast4.parse(CONTROL)
    assert control["is_control"] and control["sequence"] == 0
    assert control["peer_sequence"] == broadcast4.NO_PEER_SEQUENCE == 0xFFFF
    assert (control["total"], control["chunk_size"], control["unknown"]) == (3456, 1404, 5)

    data = broadcast4.parse(DATA_2 + b"\xaa\xbb")
    assert data["is_data"] and data["sequence"] == 5 and data["index"] == 2
    assert data["body"] == b"\xaa\xbb"


def test_a_message_of_an_unknown_kind_is_refused_rather_than_read_as_data():
    with pytest.raises(ValueError, match="is none of control"):
        broadcast4.parse(b"\x13\x00\x00\x00\x00\x01\xff\xff")
    with pytest.raises(ValueError, match="at least 8"):
        broadcast4.parse(b"\x11\x00")
    with pytest.raises(ValueError, match="is 20 bytes"):
        broadcast4.parse(CONTROL[:12])


def test_the_body_deflates_and_the_twelve_byte_prefix_never_does():
    """PokePiaSWSH splits at twelve bytes and inflates the rest; so must anything we send."""
    body = bytes(1404)                                  # zeros compress, so this takes the branch
    payload, compressed = broadcast4.build_fragment(3, 1, body)
    assert compressed is True
    assert payload[:broadcast4.PREFIX_SIZE] == broadcast4.build_header(0x12, 3) + b"\x00\x00\x00\x01"
    assert zlib.decompress(payload[broadcast4.PREFIX_SIZE:]) == body


def test_a_body_that_does_not_shrink_is_sent_plain():
    """The console only sets the flag when compression paid, and so do we.

    The body has to be genuinely incompressible for this to mean anything - a repeating byte
    pattern deflates to nothing and takes the other branch, which is what a first version of this
    test did. Our console's own fragments 0 and 1 go out plain at 1404 bytes; they are party data
    and stay out of the repository, so this uses a deterministic pseudo-random blob instead.
    """
    body = random.Random(SEED).randbytes(400)
    assert len(zlib.compress(body)) > len(body), "the fixture must be incompressible"
    payload, compressed = broadcast4.build_fragment(1, 0, body)
    assert compressed is False
    assert payload[broadcast4.PREFIX_SIZE:] == body


def test_a_transfer_is_a_control_message_and_then_every_fragment_in_order():
    payload = bytes(range(256)) * 14                    # 3584 bytes, three chunks at 1404
    sender = broadcast4.Sender()
    messages = sender.transfer(payload, compress=False)
    assert len(messages) == 4
    control = broadcast4.parse(messages[0][0])
    assert control["is_control"] and control["total"] == len(payload)

    rebuilt = b""
    for n, (msg, _) in enumerate(messages[1:]):
        got = broadcast4.parse(msg)
        assert got["index"] == n
        rebuilt += got["body"]
    assert rebuilt == payload, "the fragments must put the payload back together"


def test_the_sequence_counts_across_both_kinds_on_one_port():
    """control at 0, fragment 0 at 1. One counter, not one per kind."""
    sender = broadcast4.Sender()
    messages = sender.transfer(bytes(3456), compress=False)
    assert [broadcast4.parse(m)["sequence"] for m, _ in messages] == [0, 1, 2, 3]
    again = sender.transfer(bytes(10), compress=False)
    assert broadcast4.parse(again[0][0])["sequence"] == 4, "a second transfer continues the count"


def test_every_message_echoes_the_peer_sequence_we_last_saw():
    sender = broadcast4.Sender()
    assert broadcast4.parse(sender.transfer(b"x")[0][0])["peer_sequence"] == 0xFFFF
    sender.saw(0x0007)
    for msg, _ in sender.transfer(b"x" * 3000, compress=False):
        assert broadcast4.parse(msg)["peer_sequence"] == 7


def test_the_default_policy_matches_what_our_console_actually_did():
    """The console sends fragments 0 and 1 plain at 1404 bytes and deflates only the short last one.

    Fragment 1's own bytes compress to well under half, so "smaller wins" is demonstrably not the
    console's rule, and a sender that used it would differ from the console in a way no run has
    asked about. The fixture reproduces that shape: two full chunks that would compress, and a
    short tail.
    """
    payload = bytes(3456)                              # all zeros: every chunk would compress
    plain = broadcast4.Sender().transfer(payload)
    assert [c for _, c in plain] == [False, False, False, True], \
        "control plain, both full fragments plain, only the last deflated"

    auto = broadcast4.Sender().transfer(payload, compress=broadcast4.COMPRESS_AUTO)
    assert [c for _, c in auto] == [False, True, True, True], "the other policy compresses all"

    never = broadcast4.Sender().transfer(payload, compress=False)
    assert [c for _, c in never] == [False, False, False, False]


def test_the_receiver_acks_every_fragment_with_a_base_and_a_mask():
    """0x21, the kind nothing in this project had ever sent - which is why 0x84 repeats forever."""
    rx = broadcast4.Receiver()
    assert rx.feed(broadcast4.build_control(0, 3456, 1404)) == []
    assert rx.total == 3456 and rx.chunk_size == 1404

    # fragment 0 arrives: contiguous through 0, so base 1 and nothing early
    ack = broadcast4.parse(rx.feed(broadcast4.build_fragment(1, 0, b"a" * 1404,
                                                             compress=False)[0])[0])
    assert ack["kind"] == broadcast4.KIND_ACK and (ack["base"], ack["mask"]) == (1, 0)

    # fragment 2 arrives before 1: base stays 1 and bit 0 of the mask says "2 is here"
    ack = broadcast4.parse(rx.feed(broadcast4.build_fragment(2, 2, b"c" * 648,
                                                             compress=False)[0])[0])
    assert (ack["base"], ack["mask"]) == (1, 1)
    assert rx.complete() is False

    # and the hole fills
    ack = broadcast4.parse(rx.feed(broadcast4.build_fragment(3, 1, b"b" * 1404,
                                                             compress=False)[0])[0])
    assert (ack["base"], ack["mask"]) == (3, 0)
    assert rx.complete() is True
    assert rx.payload() == b"a" * 1404 + b"b" * 1404 + b"c" * 648


def test_an_ack_echoes_the_peer_sequence_of_the_fragment_it_answers():
    rx = broadcast4.Receiver()
    rx.feed(broadcast4.build_fragment(0x1234, 0, b"x", compress=False)[0])
    ack = broadcast4.parse(rx.feed(broadcast4.build_fragment(0x1235, 1, b"y",
                                                             compress=False)[0])[0])
    assert ack["peer_sequence"] == 0x1235


def test_a_done_message_is_answered_and_an_ack_is_not():
    rx = broadcast4.Receiver()
    reply = rx.feed(broadcast4.build_done(7))
    assert broadcast4.parse(reply[0])["kind"] == broadcast4.KIND_DONE_ACK
    assert rx.feed(broadcast4.build_ack(8, 3, 0)) == [], "their ack needs no answer of ours"


def test_ack_fields_says_what_a_receiver_holds():
    assert broadcast4.ack_fields(set()) == (0, 0)
    assert broadcast4.ack_fields({0}) == (1, 0)
    assert broadcast4.ack_fields({0, 2}) == (1, 1)          # base 1, and index 2 is bit 0
    assert broadcast4.ack_fields({1}) == (0, 1)             # nothing contiguous, index 1 is bit 0
    assert broadcast4.ack_fields({0, 1, 2}) == (3, 0)
