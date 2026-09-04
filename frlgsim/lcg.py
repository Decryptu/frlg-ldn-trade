"""The game's random number generator as arithmetic: where a state came from, and how far.

`Random` is a full-period affine map on 32 bits [decomp:include/random.h:18]

    gRngValue = gRngValue * 1103515245 + 24691          ISO_RANDOMIZE1
    return gRngValue >> 16                              only the TOP HALF is ever returned

and bs13-bs15 measured all three parts of that on the console: the address (0x03004220), the
function (0x080486B0) and the console's own consumption at the Mystery Gift menu, EXACTLY TWICE a
frame on all 95 gaps. This module is the arithmetic that turns those readings into statements.

WHY IT IS NOT `lcg_distance`. buffer_script.lcg_distance walks the orbit one step at a time and
gives up after a limit, so it can only ever answer about the near neighbourhood - which is all a
frame-to-frame gap needs. Every question worth asking about an ENCOUNTER is about a distance of
thousands to millions, and "not found within the limit" cannot be told apart from "not on the
orbit". `distance` here is exact and always answers, in ~2**17 operations instead of up to 2**32,
because the map is affine: composing it with itself is multiplication of (a, c) pairs, so
baby-step/giant-step applies. There is no such thing as "not on the orbit" - the map is a
PERMUTATION of all 2**32 states, so a distance always exists, and that is exactly why a distance
is only evidence when it is SMALL. A random pair of states sits ~2**31 apart; a pair that is
40000 apart is 100000:1 against by chance, and THAT is the argument a run has to make.

WHAT A 16-BIT STATE MEANS. `SeedRng` takes a u16 and assigns it whole [decomp:src/random.c:15], so
every seeding in the game leaves gRngValue below 0x10000. In ordinary play there is exactly one:
`SeedRngAndSetTrainerId` on the title screen [decomp:src/title_screen.c:735], seeding from the
hardware timer REG_TM1CNT_L and then handing off to the main menu. Mystery Gift, the overworld and
an encounter all run downstream of it with NOTHING reseeding in between - the only other call sites
are two unused debug screens [link.c:318, link_rfu_2.c:2670] and the Switch-only RfuMain1 hook
[link_rfu_2.c:2116], which `predecessors` is how we test for. So walking a state BACKWARD to the
first value under 0x10000 recovers the seed the console booted with, and the number of steps is
how much the game consumed getting from the title screen to wherever we read it.
"""

RAND_MULT = 1103515245                  # 0x41C64E6D [decomp:include/random.h:18]
RAND_ADD = 24691                        # ISO_RANDOMIZE1's addend [:19]
MASK = 0xFFFFFFFF
STATES = 1 << 32
SEED_LIMIT = 1 << 16                    # SeedRng takes a u16 [decomp:src/random.c:15]

_INV_MULT = pow(RAND_MULT, -1, STATES)  # RAND_MULT is odd, so it is invertible mod 2**32


def step(value):
    """One turn of the LCG: the state after a single Random() call."""
    return (value * RAND_MULT + RAND_ADD) & MASK


def unstep(value):
    """The state BEFORE a single Random() call - the map is a permutation, so this always exists."""
    return ((value - RAND_ADD) * _INV_MULT) & MASK


def draw(value):
    """(the u16 Random() returns, the state it leaves) from the state before the call."""
    value = step(value)
    return value >> 16, value


def draws(value, count):
    """(the `count` u16s Random() returns, the state it leaves) from the state before the first."""
    out = []
    for _ in range(int(count)):
        got, value = draw(value)
        out.append(got)
    return out, value


# --- composing the map with itself ---------------------------------------------------------------
# f(x) = a*x + c is closed under composition, so f**n is one (a, c) pair reachable by squaring
# rather than by n applications. Everything below rests on that.

def _compose(first, second):
    """The pair for `first` then `second`."""
    fa, fc = first
    sa, sc = second
    return ((sa * fa) & MASK, (sa * fc + sc) & MASK)


def _power(pair, n):
    result = (1, 0)
    while n:
        if n & 1:
            result = _compose(result, pair)
        pair = _compose(pair, pair)
        n >>= 1
    return result


def _invert(pair):
    a, c = pair
    inverse = pow(a, -1, STATES)
    return (inverse, (-inverse * c) & MASK)


_STEP = (RAND_MULT, RAND_ADD)


def advance(value, n):
    """The state `n` turns after `value`. `n` may be negative, and is taken modulo the period."""
    a, c = _power(_STEP, int(n) % STATES)
    return (a * (value & MASK) + c) & MASK


_GIANT = 1 << 16                        # 2**16 baby steps and at most 2**16 giant steps


def distance(start, target):
    """How many turns of the LCG take `start` to `target`. Exact, and always an answer.

    0 <= distance < 2**32. The map is a permutation of every 32-bit state, so this NEVER fails and
    a large answer is not an error - it is the finding that the two states are unrelated.
    """
    start, target = start & MASK, target & MASK
    seen = {}
    value = start
    for baby in range(_GIANT):          # f**baby(start) for every baby step, first wins
        if value not in seen:
            seen[value] = baby
        value = step(value)
    back = _invert(_power(_STEP, _GIANT))
    value = target
    for giant in range(_GIANT):
        baby = seen.get(value)
        if baby is not None:
            return giant * _GIANT + baby
        value = (back[0] * value + back[1]) & MASK
    raise AssertionError("the LCG is a permutation of 2**32 states; a distance always exists")


# --- reading a state backwards to the seed it came from ------------------------------------------

def predecessors(value, limit=1 << 20, count=1):
    """[(steps, seed), ...]: states under 0x10000 within `limit` turns BEFORE `value`.

    A state below 0x10000 is what SeedRng leaves [decomp:src/random.c:15], so the first entry is
    the candidate for the seed the console is running on and `steps` is what the game consumed
    since. Values arrive at random, so one turns up every ~65536 steps BY CHANCE: a candidate is
    only evidence when its `steps` matches an independently measured elapsed time.
    """
    found = []
    current = value & MASK
    for steps in range(1, int(limit) + 1):
        current = unstep(current)
        if current < SEED_LIMIT:
            found.append((steps, current))
            if len(found) >= int(count):
                break
    return found


def seconds(turns, per_frame=2, fps=59.7275):
    """`turns` of the LCG as wall-clock seconds, at a measured consumption rate.

    bs15 measured per_frame = 2 at the Mystery Gift link menu, on all 95 gaps. It is NOT a
    constant of the game - it is what that ONE screen consumes - so any use of it outside a menu
    is a hypothesis that the run has to check, not an assumption it may make.
    """
    return turns / float(per_frame) / float(fps)


# --- the four draws a wild Pokemon is made of ----------------------------------------------------
# GenerateWildMon calls CreateMonWithNature(&gEnemyParty[0], species, level, USE_RANDOM_IVS,
# Random() % NUM_NATURES) [decomp:src/wild_encounter.c:233], and CreateMonWithNature ROLLS THE
# PERSONALITY UNTIL IT MATCHES that nature [decomp:src/pokemon.c]:
#
#     do { personality = Random32(); } while (nature != GetNatureFromPersonality(personality));
#     CreateMon(mon, species, level, fixedIV, TRUE, personality, OT_ID_PLAYER_ID, 0);
#
# so the accepted personality is TWO CONSECUTIVE draws, and because hasFixedPersonality is TRUE and
# the OT is the player, CreateBoxMon [decomp:src/pokemon.c] draws nothing more until the IVs, which
# are the very next two [MAX_IV_MASK, five bits each, three per draw]. Four consecutive draws:
#
#     d1, d2  the personality      d3  HP / ATK / DEF        d4  SPEED / SPATK / SPDEF
#
# THAT IS WHY A CAUGHT POKEMON IS A READING OF gRngValue. The 32 bits of the personality alone
# would leave 2**16 candidate states (only the top half of each state is ever returned, so the low
# half of the first is unconstrained); the IVs are 30 more bits over the two draws that FOLLOW, and
# checking them against each candidate leaves one. Nothing in the payload is involved - the console
# built this on its own, in the grass, long after our code stopped running.
#
# THE ORDER OF THE PERSONALITY'S TWO HALVES IS NOT ASSUMED. Random32() is
# `(Random() | (Random() << 16))` [decomp:include/random.h:15] and C does not order the operands of
# `|`, so which half is drawn first is the COMPILER's choice in the French build - unknown until a
# console answers. Both are tried and the IVs decide, so the answer reports which one held.

MAX_IV_MASK = 31                        # [decomp:include/constants/pokemon.h]
NUM_NATURES = 25


def iv_word(first, second, third):
    """The 15 bits of one IV draw: three stats, five bits each, low to high."""
    for value in (first, second, third):
        if not 0 <= value <= MAX_IV_MASK:
            raise ValueError(f"an IV is 0..{MAX_IV_MASK}, got {value}")
    return (first & 31) | ((second & 31) << 5) | ((third & 31) << 10)


def nature_of(personality):
    """GetNatureFromPersonality: the personality modulo the number of natures."""
    return (personality & MASK) % NUM_NATURES


def recover_wild_state(personality, ivs, max_gap=32):
    """[{...}]: the RNG states that would build this Pokemon, from its personality and IVs.

    `ivs` is (hp, atk, def, speed, spatk, spdef) as the mon stores them.

    THE GAP IS SEARCHED, NOT ASSUMED, AND THAT IS NOT A CONVENIENCE. bs51 caught a Weedle whose
    personality and IVs are certain - the six stats it produces match what the console printed on
    its own summary screen, 6/6, and the nature reads DOUX = MILD = 16 - and NO state builds it
    with the IV draws immediately after the personality. Exactly one does with ONE draw in
    between. That extra advance is in no line of CreateBoxMon [decomp:src/pokemon.c]; it comes
    from outside the generation, and it is the Gen 3 "Method 2" spread, MEASURED here rather than
    taken from lore. Since the game produces more than one such layout, assuming any single one
    turns a wrong model into a silent wrong answer - so the ANSWER decides the gap, the way bs38's
    needle was built to let the answer decide the stride.

    `before` is gRngValue as it stood immediately BEFORE the first personality draw; that is the
    state a distance is measured to. `gap` is how many draws sat between the personality and the
    IVs. In practice one candidate survives: the personality alone allows 2**16 states, and the
    two IV draws are 30 more bits of check, so over the whole search of
    2 orders x 2**16 states x (max_gap + 1) gaps x 2 IV orders a false positive is expected
    about once in 2**30 / (that count) - report the count when more than one comes back.
    """
    personality &= MASK
    if len(ivs) != 6:
        raise ValueError(f"six IVs, got {len(ivs)}")
    first_word = iv_word(ivs[0], ivs[1], ivs[2])
    second_word = iv_word(ivs[3], ivs[4], ivs[5])
    orders = (("low-half first", personality & 0xFFFF, personality >> 16),
              ("high-half first", personality >> 16, personality & 0xFFFF))
    iv_orders = (("HP/ATK/DEF first", first_word, second_word),
                 ("SPEED/SPATK/SPDEF first", second_word, first_word))
    found = []
    for order, first, second in orders:
        for low in range(1 << 16):
            state = (first << 16) | low
            after_personality = step(state)
            if after_personality >> 16 != second:
                continue
            walked = after_personality
            for gap in range(int(max_gap) + 1):
                one = step(walked)
                two = step(one)
                for iv_order, early, late in iv_orders:
                    if (one >> 16) & 0x7FFF == early and (two >> 16) & 0x7FFF == late:
                        found.append({"before": unstep(state), "after": two, "order": order,
                                      "iv_order": iv_order, "gap": gap,
                                      "nature": nature_of(personality)})
                walked = step(walked)
    return found


def nature_draw_before(state, nature, limit=4096):
    """How many turns before `state` the `Random() % NUM_NATURES` that chose `nature` was drawn.

    CreateMonWithNature rejects whole PAIRS of draws, so the nature draw sits an EVEN number of
    turns before the accepted personality; a hit at an odd offset is a coincidence and is not
    reported. This is a free extra check on a recovered state - the nature is read off the
    Pokemon, and the draw that chose it has to be there.
    """
    current = state & MASK
    for steps in range(1, int(limit) + 1):
        current = unstep(current)
        if steps % 2 == 0 and (step(current) >> 16) % NUM_NATURES == nature:
            return steps
    return None
