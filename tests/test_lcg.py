"""The RNG as arithmetic: exact distances, the seed behind a state, and a caught Pokemon read back.

Every test here is offline arithmetic, but the shapes are the ones a hardware run has to answer in:
a state read off the console (bs15's own samples are used as a fixture), and a Pokemon the console
built by itself in the grass.
"""
import random

import pytest

from frlgsim import buffer_script, lcg


def test_constants_agree_with_the_payload_builder():
    # Two readings of the same decomp line [include/random.h:18-19]; they must not drift apart.
    assert (lcg.RAND_MULT, lcg.RAND_ADD) == (buffer_script.RAND_MULT, buffer_script.RAND_ADD)
    assert lcg.step(0x12345678) == buffer_script.rand_step(0x12345678)


def test_unstep_inverts_step_everywhere():
    for value in (0, 1, 0xDF65, 0xFFFFFFFF, 0x3C22BA3A):
        assert lcg.unstep(lcg.step(value)) == value
        assert lcg.step(lcg.unstep(value)) == value


def test_advance_matches_stepping_one_at_a_time():
    value = 0xB8C0
    walked = value
    for _ in range(500):
        walked = lcg.step(walked)
    assert lcg.advance(value, 500) == walked
    assert lcg.advance(walked, -500) == value
    assert lcg.advance(value, 0) == value


def test_draw_returns_the_top_half_only():
    got, after = lcg.draw(0)
    assert after == lcg.step(0)
    assert got == after >> 16
    assert lcg.draws(0, 3)[0] == [lcg.draw(0)[0]] + [lcg.draw(lcg.step(0))[0]] + \
        [lcg.draw(lcg.step(lcg.step(0)))[0]]


@pytest.mark.parametrize("n", [0, 1, 2, 96, 34962, 1 << 20, (1 << 32) - 1])
def test_distance_is_exact_at_any_range(n):
    start = 0xDF65
    assert lcg.distance(start, lcg.advance(start, n)) == n


def test_distance_between_unrelated_states_is_huge_and_that_is_the_point():
    # bs15's first sample against the trainer id the Switch-only RfuMain1 hook would have seeded
    # with [decomp:src/link_rfu_2.c:2116]. A reseed did not happen: the answer is not small.
    assert lcg.distance(0xDF65, 0x3C22BA3A) > 1 << 30


def test_predecessors_finds_a_planted_seed_at_the_right_distance():
    seed = 0x1234
    state = lcg.advance(seed, 4321)
    steps, found = lcg.predecessors(state, limit=1 << 16)[0]
    assert (steps, found) == (4321, seed)


def test_predecessors_reports_nothing_when_the_seed_is_out_of_reach():
    assert lcg.predecessors(lcg.advance(0x1234, 5000), limit=100) == []


def test_seconds_uses_the_measured_rate():
    # bs15 measured two turns a frame at the Mystery Gift link menu, on all 95 gaps.
    assert lcg.seconds(2 * 60, per_frame=2, fps=60) == pytest.approx(1.0)


def _build_wild_mon(state):
    """The draws GenerateWildMon makes, from a state - the model a recovery is checked against."""
    nature, state = lcg.draw(state)
    nature %= lcg.NUM_NATURES
    while True:
        before = state
        low, state = lcg.draw(state)
        high, state = lcg.draw(state)
        personality = low | (high << 16)
        if lcg.nature_of(personality) == nature:
            break
    first, state = lcg.draw(state)
    second, state = lcg.draw(state)
    ivs = (first & 31, (first >> 5) & 31, (first >> 10) & 31,
           second & 31, (second >> 5) & 31, (second >> 10) & 31)
    return {"before": before, "personality": personality, "ivs": ivs, "nature": nature}


def test_a_caught_pokemon_names_exactly_one_rng_state():
    rolls = random.Random(30)
    for _ in range(12):
        planted = lcg.advance(rolls.randrange(1 << 16), rolls.randrange(1 << 20))
        mon = _build_wild_mon(planted)
        found = lcg.recover_wild_state(mon["personality"], mon["ivs"])
        assert len(found) == 1, "the two IV draws are 30 bits of check; one state should survive"
        assert found[0]["before"] == mon["before"]
        assert found[0]["order"] == "low-half first"


def test_the_recovered_state_is_a_measured_distance_from_the_seed():
    seed = 0xB8C0
    mon = _build_wild_mon(lcg.advance(seed, 5000))
    found = lcg.recover_wild_state(mon["personality"], mon["ivs"])[0]
    # The rejection loop makes it 5000 PLUS the pairs it threw away, never less.
    assert 5000 < lcg.distance(seed, found["before"]) < 5000 + 2 * 25 * 20


def test_the_nature_draw_is_there_at_an_even_offset():
    mon = _build_wild_mon(lcg.advance(0x0691, 777))
    offset = lcg.nature_draw_before(mon["before"], mon["nature"])
    assert offset is not None and offset % 2 == 0


def test_iv_word_refuses_an_impossible_iv():
    assert lcg.iv_word(31, 0, 1) == 31 | (1 << 10)
    with pytest.raises(ValueError):
        lcg.iv_word(32, 0, 0)


def test_bs15_samples_hold_the_recurrence_and_two_turns_a_frame():
    # The console's own bytes, kept as the fixture that says the arithmetic here describes it.
    trace = buffer_script.read_rng_trace(open("scratchpad/bs15_dump.bin", "rb").read()) \
        if __import__("os").path.exists("scratchpad/bs15_dump.bin") else None
    if trace is None:
        pytest.skip("bs15_dump.bin is not in this checkout")
    assert all(after == lcg.step(before) for before, after in trace["samples"])
    gaps = {lcg.distance(trace["samples"][i - 1][1], trace["samples"][i][0])
            for i in range(1, trace["taken"])}
    assert gaps == {2}, "the game turned the RNG exactly twice a frame at that menu"
