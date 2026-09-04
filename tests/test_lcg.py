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


# --- bs51: a Pokemon the console caught by itself, in the grass ----------------------------------
# The ASPICOT (Weedle, species 13, Lv7) the player caught on Route 24 between bs50 and bs51, read
# out of gPlayerParty at 0x02024280. This is the fixture that says the model here describes the
# console rather than the decomp's English build, and it is the run that CORRECTED the model.

BS51_WEEDLE_PID = 0xF7EBC01B
BS51_WEEDLE_IVS = (23, 3, 16, 17, 24, 7)        # hp, atk, def, speed, spatk, spdef
BS51_WEEDLE_STATE = 0x4125F87F                  # gRngValue before the four draws


def test_the_caught_weedle_is_certain_before_any_rng_claim_is_made():
    """The PID and IVs are not taken on trust: they predict the six stats the console printed on
    its own summary screen, which the player read back. Two different mechanisms, one answer."""
    # Weedle base stats [decomp gSpeciesInfo]: HP 40, ATK 35, DEF 30, SPEED 50, SPATK 20, SPDEF 20.
    level, base = 7, (40, 35, 30, 50, 20, 20)
    hp, atk, dfn, spe, spa, spd = BS51_WEEDLE_IVS[0], *BS51_WEEDLE_IVS[1:]
    assert (2 * base[0] + hp) * level // 100 + level + 10 == 24
    def stat(b, iv, mult):
        return int(((2 * b + iv) * level // 100 + 5) * mult)
    # nature 16 is MILD - DOUX on the console's French screen - which raises Sp.Atk and lowers Def.
    assert lcg.nature_of(BS51_WEEDLE_PID) == 16
    assert stat(base[1], atk, 1.0) == 10
    assert stat(base[2], dfn, 0.9) == 9
    assert stat(base[3], spe, 1.0) == 13
    assert stat(base[4], spa, 1.1) == 9
    assert stat(base[5], spd, 1.0) == 8


def test_the_caught_weedle_names_one_state_and_the_gap_is_one_not_zero():
    """The run that corrected the model. Assuming the IV draws follow the personality immediately
    finds NOTHING for this mon; searching the gap finds exactly one state, one draw later."""
    found = lcg.recover_wild_state(BS51_WEEDLE_PID, BS51_WEEDLE_IVS)
    assert len(found) == 1
    got = found[0]
    assert got["before"] == BS51_WEEDLE_STATE
    assert got["gap"] == 1, "one extra draw sits between the personality and the IVs"
    assert got["order"] == "low-half first"
    assert got["iv_order"] == "HP/ATK/DEF first"
    # And the model that was wrong stays wrong, so a regression cannot pass unnoticed.
    assert lcg.recover_wild_state(BS51_WEEDLE_PID, BS51_WEEDLE_IVS, max_gap=0) == []


def test_the_seed_we_set_in_bs50_is_not_where_the_weedle_came_from():
    """The title screen re-seeds on the way out of Mystery Gift [mystery_gift_menu.c:463 ->
    CB2_InitTitleScreen -> SeedRng(REG_TM1CNT_L), title_screen.c:735], so 0xC0DE cannot reach the
    grass. The distance says so rather than leaving it to argument."""
    assert lcg.distance(0xC0DE, BS51_WEEDLE_STATE) > 1 << 30
    assert lcg.distance(0xDF65, BS51_WEEDLE_STATE) > 1 << 30      # nor did RfuMain1 reseed


# --- every mon this console has generated, and the three layouts it used ------------------------
# Methods 1, 2 and 4, all observed on the same cartridge in one evening. Searching one gap finds
# only some of them, and finds them SILENTLY - the other two came back empty, which is why the
# recovery searches both gaps and reports which it used.
CONSOLE_MONS = {
    # name:            (personality, ivs, state before, gap, iv_gap)
    "bs51 Weedle":     (0xF7EBC01B, (23, 3, 16, 17, 24, 7), 0x4125F87F, 1, 0),   # Method 2
    "bs52 Caterpie":   (0x99FDAFC5, (12, 10, 25, 6, 27, 9), 0x7492D8B4, 0, 1),   # Method 4
    "bs52 Weedle #2":  (0xC41B8241, (13, 31, 9, 30, 25, 22), 0xCD376EA8, 0, 1),  # Method 4
    "bs54 Mankey":     (0x321FCD56, (6, 8, 20, 19, 11, 24), 0xB2F6D04C, 0, 1),   # Method 4
    "bs53 Ditto":      (0x026F38B2, (31, 23, 27, 18, 30, 30), 0x81F6816D, 0, 0), # Method 1
}


@pytest.mark.parametrize("name", sorted(CONSOLE_MONS))
def test_every_mon_the_console_made_recovers_to_one_state(name):
    personality, ivs, state, gap, iv_gap = CONSOLE_MONS[name]
    found = lcg.recover_wild_state(personality, ivs)
    assert len(found) == 1, f"{name} should name exactly one state"
    assert found[0]["before"] == state
    assert (found[0]["gap"], found[0]["iv_gap"]) == (gap, iv_gap)
    assert found[0]["order"] == "low-half first"


def test_the_scripted_battle_recovers_to_the_seed_we_actually_wrote():
    """mev07's Ditto is the only one whose state was not inferred but CHOSEN: the field script wrote
    it four commands earlier. It recovers to exactly that, with both gaps zero - so the scripted
    generation is plain Method 1, with none of the stray draws the walked encounters showed."""
    from frlgsim import wonder_card_events
    personality, ivs, state, gap, iv_gap = CONSOLE_MONS["bs53 Ditto"]
    assert state == wonder_card_events.RNG_DITTO_SEED
    assert (gap, iv_gap) == (0, 0)


def test_the_union_room_does_not_reseed_either():
    """ur01/bs54: a full Union Room session - LinkPlayer exchange, trainer cards, a greeting, 199
    seconds of RFU - then a Mankey caught on Route 22. If SVC4B_RESEED_RNG fired for the Union
    Room the state would descend from the console's own trainer id. It is 2.1 BILLION turns away.
    Mystery Gift (bs15) and the Union Room are both ruled out now."""
    assert lcg.distance(0xDF65, CONSOLE_MONS["bs54 Mankey"][2]) > 1 << 30
