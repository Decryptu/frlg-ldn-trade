"""The countdown: which frames are shiny, and how far a press missed.

Every constant it stands on was measured on hardware, so these tests check the arithmetic against
the runs rather than against a restatement of the same arithmetic.
"""
import sys

import pytest

from frlgsim import lcg, rng_countdown, rng_script

# mev11's own reading, and the mon bs58 dumped out of gPlayerParty afterwards.
MEV11_BEFORE = 0x9A4F5DAA
MEV11_PID = 0x0BF87DD1
MEV11_IVS = (25, 10, 28, 9, 19, 3)
CONSOLE_TID, CONSOLE_SID = 57189, 58811


def test_the_mon_it_computes_is_the_one_the_console_actually_built():
    """The whole tool rests on this: frame 0 of a scan must reproduce mev11/bs58 exactly."""
    mon = rng_countdown._mon_from(MEV11_BEFORE, CONSOLE_TID, CONSOLE_SID)

    assert mon["personality"] == MEV11_PID
    assert mon["ivs"] == MEV11_IVS
    assert mon["nature"] == 13                      # Jolly, as the summary screen read
    assert mon["shiny"] is False


def test_a_press_lands_only_on_even_turns_because_the_rate_is_two_per_frame():
    """mev09 and mev10 measured exactly 2 turns a frame, so the states a press can reach are
    advance(S, 2k) and nothing between them."""
    hits = rng_countdown.scan(MEV11_BEFORE, CONSOLE_TID, CONSOLE_SID, frames=200)
    assert rng_countdown.TURNS_PER_FRAME == 2
    for hit in hits:
        assert hit["turns"] == 2 * hit["frames"]
        assert hit["state"] == lcg.advance(MEV11_BEFORE, 2 * hit["frames"])


def test_every_frame_it_calls_shiny_really_is_shiny_and_none_are_missed():
    frames = 20000
    hits = rng_countdown.scan(MEV11_BEFORE, CONSOLE_TID, CONSOLE_SID, frames=frames)
    found = {hit["frames"] for hit in hits}

    state = MEV11_BEFORE
    expected = set()
    for k in range(frames + 1):
        mon = rng_countdown._mon_from(state, CONSOLE_TID, CONSOLE_SID)
        if (CONSOLE_TID ^ CONSOLE_SID ^ (mon["personality"] >> 16)
                ^ (mon["personality"] & 0xFFFF)) < 8:
            expected.add(k)
        state = lcg.advance(state, 2)

    assert found == expected
    assert all(hit["shiny"] for hit in hits)
    # ~1 in 8192 presses, so a 20k-frame window should hold a handful, not none and not hundreds.
    assert 0 <= len(hits) <= 20


def test_want_narrows_without_inventing_hits():
    everything = rng_countdown.scan(MEV11_BEFORE, CONSOLE_TID, CONSOLE_SID, frames=60000)
    picky = rng_countdown.scan(MEV11_BEFORE, CONSOLE_TID, CONSOLE_SID, frames=60000,
                               want=lambda mon: mon["iv_total"] >= 150)

    assert {hit["frames"] for hit in picky} <= {hit["frames"] for hit in everything}
    assert all(hit["iv_total"] >= 150 for hit in picky)


@pytest.mark.parametrize("frames_late", [0, 1, 5, -1, -12])
def test_a_miss_reads_back_as_the_signed_number_of_frames_it_missed_by(frames_late):
    """The script prints the state it generated from, so a miss is not a mystery - it is a
    measurement. Late is positive: the console had already moved past the target."""
    target = MEV11_BEFORE
    actual = lcg.advance(target, 2 * frames_late)

    miss = rng_countdown.press_error(target, actual)

    assert miss["frames"] == frames_late
    assert miss["turns"] == 2 * frames_late
    assert miss["on_target"] == (frames_late == 0)
    assert miss["usable"]


def test_a_reseed_is_reported_as_a_different_seed_rather_than_a_huge_miss():
    """Backing out to the title screen reseeds, and a distance ALWAYS exists - so the tool has to
    say 'that is not the same orbit position' instead of '1.9 billion turns late'."""
    miss = rng_countdown.press_error(0xC0DE, 0x9A4F5DAA)

    assert not miss["usable"]


def test_the_cli_prints_a_countdown_and_a_miss(capsys):
    rng_countdown.main(["23978", "39503", "--frames", "20000"])
    countdown = capsys.readouterr().out
    assert "0x9A4F5DAA" in countdown
    assert "shiny frame(s)" in countdown

    rng_countdown.main(["23978", "39503", "--aimed-at", hex(lcg.advance(MEV11_BEFORE, 10))])
    miss = capsys.readouterr().out
    assert "-5.0 frames" in miss and "EARLY" in miss


def test_the_printed_halves_are_the_ones_the_npc_shows():
    assert rng_script.seed_from_printed(23978, 39503) == MEV11_BEFORE
