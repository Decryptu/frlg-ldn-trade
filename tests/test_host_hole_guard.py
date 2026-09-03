"""The host stops emitting new Reliable frames while the console's cumulative ack is stuck behind a hole,
keeps retransmitting the hole, and resumes once the ack catches up (lg150: an unbounded backlog behind a
lost frame is released in one burst that overflows the console's 8-deep RFU queue)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from frlgsim import reliable
from frlgsim.host_session import HOST_OUTSTANDING_MAX, HostSession
from frlgsim.rfu_leader import UNI


class _Engine:
    disconnect_requested = False
    ticks = 0

    def tick(self):
        self.ticks += 1
        return [0] * 7

    def mark_disconnect_sent(self):
        pass


class _Rfu:
    state = UNI
    ni_complete = True

    def __init__(self):
        self.n = 0

    def tick(self, words):
        self.n += 1
        return b"\x57\x54" + self.n.to_bytes(2, "little")

    def on_ldn_leave(self):
        pass


def _session():
    session = HostSession(engine=_Engine())
    session.rfu = _Rfu()
    session.reliable.open(b"\x57\x41", 0)
    session.connect_ack_sent = True
    return session


def _ack(session, next_expected, now_ms):
    wire = reliable.build_reliable(session.reliable.start_seq, 0,
                                   reliable.build_bulk_ack(next_expected & 0xFFFF),
                                   reliable.FLAGSA_CTRL)
    session.reliable.receive(wire, now_ms)


def _new_data_seqs(emissions):
    return [e.seq for e in emissions if e.flagsA & 1 and not e.retransmitted]


def test_new_frames_stop_at_the_outstanding_cap_and_resume_after_the_ack():
    session = _session()
    seen = set()
    now = 0.0
    for _ in range(40):
        now += 16.7
        for seq in _new_data_seqs(session.tick(now)):
            seen.add(seq)
    # The opening frame plus the new frames never exceed the cap; the engine was held, not drained.
    assert len(seen) + 1 == HOST_OUTSTANDING_MAX
    assert session.console_backlogged
    assert session.activity.ticks == HOST_OUTSTANDING_MAX - 1
    # Retransmits of the hole keep flowing while held.
    now += 500
    held = session.tick(now)
    assert any(e.retransmitted for e in held)
    assert not _new_data_seqs(held)
    # The console catches up: everything sent is acked, new frames resume.
    _ack(session, session.reliable.link.out_seq, now)
    now += 16.7
    resumed = _new_data_seqs(session.tick(now))
    assert resumed and resumed[0] not in seen
    assert not session.console_backlogged


def test_partial_catch_up_releases_exactly_the_room_it_frees():
    session = _session()
    now = 0.0
    for _ in range(20):
        now += 16.7
        session.tick(now)
    assert session.console_backlogged
    # Ack two frames: the guard opens for two new frames, then closes again.
    _ack(session, session.reliable.start_seq + 2, now)
    new = []
    for _ in range(10):
        now += 16.7
        new += _new_data_seqs(session.tick(now))
    assert len(new) == 2
    assert session.console_backlogged
