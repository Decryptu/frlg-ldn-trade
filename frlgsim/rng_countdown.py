"""When to press A, and how far off the last press was.

Everything this needs was settled on hardware and none of it rests on a clock:

- `gRngValue` can be READ in the overworld (mev08, `gSpecialVar_0x8000` = 0x020370B4 [bs57]).
- The state advances **exactly 2 turns per frame** (mev09 1202/600, mev10 6002/3000, both `2N+2`).
- The offset between the reading and the generation is **zero**, and the mon is the next four
  draws (mev11/bs58: PID, nature, shininess and all six IVs predicted from a state the console
  chose for itself).

So the states a press can land on are `advance(S, 2k)` for whole frames k, and the mon each one
would produce is computable. This module walks that list and says which k are shiny.

THE MISS IS THE MEASUREMENT. The script prints the state it generated from, so a press that missed
reports exactly which state it hit - `press_error` turns two readings into a signed frame count.
No catching, no Poke Ball, no stopwatch: aim, read, correct, repeat, at a few seconds an attempt.
"""

from . import lcg

SHINY_ODDS = 8
FPS = 59.7275                   # for turning frames into a spoken countdown, and nothing else
TURNS_PER_FRAME = 2             # MEASURED, mev09 and mev10; not assumed


def _mon_from(state, tid, sid):
    """-> the mon `setwildbattle` would build from `state`: the next four draws, in order."""
    (d1, d2, d3, d4), _end = lcg.draws(state, 4)
    personality = d1 | (d2 << 16)               # low half first, at this call site [bs58]
    ivs = (d3 & 31, (d3 >> 5) & 31, (d3 >> 10) & 31,
           d4 & 31, (d4 >> 5) & 31, (d4 >> 10) & 31)
    shiny_value = tid ^ sid ^ (personality >> 16) ^ (personality & 0xFFFF)
    return {"state": state, "personality": personality, "ivs": ivs, "iv_total": sum(ivs),
            "nature": personality % 25, "shiny_value": shiny_value,
            "shiny": shiny_value < SHINY_ODDS}


def scan(state, tid, sid, frames=20000, want=None):
    """-> every frame within `frames` whose press would produce a shiny.

    `want(mon) -> bool` narrows it further - a nature, an IV floor - at no extra cost, because the
    whole mon is computed anyway.
    """
    out, current = [], int(state)
    for k in range(int(frames) + 1):
        mon = _mon_from(current, tid, sid)
        if mon["shiny"] and (want is None or want(mon)):
            out.append({**mon, "frames": k, "turns": k * TURNS_PER_FRAME,
                        "seconds": k / FPS})
        current = lcg.advance(current, TURNS_PER_FRAME)
    return out


def press_error(target, actual):
    """-> how far a press missed, signed, in turns and frames.

    Positive means LATE - the console had already moved past the target when the script read it.
    `lcg.distance` only ever answers forwards, so a distance past the halfway mark is read as a
    negative one; a miss of a few frames is unambiguous, a miss of a billion turns is not a miss
    but a different seed.
    """
    turns = lcg.distance(int(target), int(actual))
    if turns > lcg.STATES // 2:
        turns -= lcg.STATES
    return {"turns": turns, "frames": turns / TURNS_PER_FRAME,
            "on_target": turns == 0,
            "usable": abs(turns) < 10 ** 6}


def describe(state, tid, sid, frames=20000, limit=5):
    natures = ("Hardy Lonely Brave Adamant Naughty Bold Docile Relaxed Impish Lax Timid Hasty "
               "Serious Jolly Naive Modest Mild Quiet Bashful Rash Calm Gentle Sassy Careful "
               "Quirky").split()
    hits = scan(state, tid, sid, frames)
    lines = [f"from 0x{int(state):08X}, TID {tid} / SID {sid}",
             f"scanning {frames:,} frames ahead ({frames / FPS:,.0f} s at 59.7275 Hz)",
             f"{len(hits)} shiny frame(s); ~1 in {SHINY_ODDS and 65536 // SHINY_ODDS:,} presses"]
    if not hits:
        lines.append("  none in range - scan further ahead")
    for hit in hits[:limit]:
        lines.append(
            f"  +{hit['frames']:>6,} frames  ({hit['seconds']:>6.1f} s)  "
            f"PID 0x{hit['personality']:08X}  {natures[hit['nature']]:<8} "
            f"IVs {'/'.join(str(v) for v in hit['ivs'])}  (total {hit['iv_total']})")
    if len(hits) > limit:
        lines.append(f"  ... and {len(hits) - limit} more")
    lines.append("PRESS A SO THAT THE SCRIPT READS ON THAT FRAME. A miss costs one A press: read"
                 " the BEFORE it prints and pass both to press_error.")
    return lines


def main(argv=None):
    import argparse
    from . import rng_script
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("low", type=lambda v: int(v, 0), help="RNG LO, as the NPC printed it")
    parser.add_argument("high", type=lambda v: int(v, 0), help="RNG HI, as the NPC printed it")
    parser.add_argument("--tid", type=int, default=57189)
    parser.add_argument("--sid", type=int, default=58811)
    parser.add_argument("--frames", type=int, default=20000)
    parser.add_argument("--aimed-at", type=lambda v: int(v, 0), default=None, metavar="STATE",
                        help="the state the last press was aiming at: report the miss instead")
    args = parser.parse_args(argv)
    state = rng_script.seed_from_printed(args.low, args.high)
    if args.aimed_at is not None:
        miss = press_error(args.aimed_at, state)
        print(f"aimed at 0x{args.aimed_at:08X}, read 0x{state:08X}")
        if not miss["usable"]:
            print("  that is not a miss, it is a different seed - the game reseeded in between")
        else:
            print(f"  {miss['turns']:+,} turns = {miss['frames']:+,.1f} frames "
                  + ("(ON TARGET)" if miss["on_target"] else
                     "(LATE: press sooner)" if miss["turns"] > 0 else "(EARLY: press later)"))
        return 0
    for line in describe(state, args.tid, args.sid, args.frames):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
