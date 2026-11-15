#!/usr/bin/env python3
"""
compare_winner_shapes.py — is the tool measuring the wrong winner?

THE QUESTION
discover_scenarios.py reports, for each trial, the shape of the lineup that
would have WON that trial, where "won" means the best lineup that could legally
be built. That is the global optimum over the whole player pool.

But a tournament is not won by the global optimum. It is won by the best of
147,058 lineups that people actually built, and those people stack. The two
objects come apart whenever the field is concentrated: the best entry drawn
from a stack-heavy population should itself be more stacked than the
unconstrained optimum, because the deep-stack lineups are the ones being
sampled in bulk.

That matters because the evidence points that way. Both real winners available
went FOUR DEEP in one game: Cincinnati/Tennessee on 1 November, Green Bay/New
England on 8 November. The model puts all four-deep shapes at roughly five
percent of simulated wins, and on 8 November it ranked GB/NE four deep 23rd of
42 at 0.7x, calling it a bad bet, the week it won. Two for two against a five
percent rate is about a one-in-four-hundred coincidence. Thin, but pointed.

WHAT THIS MEASURES
For the same trials and the same simulation, two winners side by side:

  A. the GLOBAL OPTIMUM, which is what the tool reports today
  B. the BEST ENTRY IN A SIMULATED FIELD built at projected ownership with the
     stacking behaviour real entries show, which is what a contest actually
     pays

and compares their shape distributions. If B is systematically deeper stacked
than A, the tool is answering a slightly different question from the one the
contest asks, and the fix is to change what it scores rather than how well it
scores it.

This is a diagnostic. It writes nothing and changes no behaviour.

USAGE
  python tools/compare_winner_shapes.py [--trials 1200] [--field 6000]
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_contest as bc            # noqa: E402
import discover_scenarios as ds       # noqa: E402


def log(*a):
    print(*a, flush=True)


def depth_of(ids, pool):
    """How many of the nine come from the single most-used game."""
    g = Counter(ds.game_of(pool[i]) for i in ids)
    top = g.most_common(1)[0]
    return top[1], top[0]


def summarise(name, depths, shapes, n):
    log(f"\n{name}")
    log(f"   {'deepest game':16}{'share of wins':>16}")
    for d in sorted(depths):
        bar = "#" * int(round(60 * depths[d] / max(n, 1)))
        log(f"   {('x' + str(d)):16}{100 * depths[d] / max(n, 1):>14.1f}%  {bar}")
    log(f"   mean depth {sum(d * c for d, c in depths.items()) / max(n, 1):.2f}")
    log("   most common shapes: "
        + ", ".join(f"{s} ({100 * c / max(n, 1):.0f}%)"
                    for s, c in shapes.most_common(5)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1200)
    ap.add_argument("--field", type=int, default=6000)
    args = ap.parse_args()

    import json
    with open(os.path.join(DATA, "nfl_slate_board.json"), encoding="utf-8") as f:
        board = json.load(f)
    log(f"slate: {board.get('slate', {}).get('name', '?')}")
    log(f"simulating at {args.trials:,} trials")
    import build_projections as bp
    sims, _ = bp.player_scores(args.trials, "dk")
    pool = bc.build_pool(board, sims)
    log(f"{len(pool)} players in the pool")

    scores = np.vstack([p["fp"] for p in pool])
    sal = np.array([p["sal"] for p in pool])
    teams = [p["team"] for p in pool]
    idx_by_pos = defaultdict(list)
    for i, p in enumerate(pool):
        idx_by_pos[p["pos"]].append(i)
    idx_by_pos = {k: np.asarray(v) for k, v in idx_by_pos.items()}
    meta = (idx_by_pos, sal, teams)

    rng = np.random.default_rng(bc.SEED)

    # B's population, built once: ownership-weighted and stacked the way real
    # entries are, which is the whole point of the comparison.
    log(f"\nbuilding a field of {args.field:,} lineups at projected ownership")
    field, attempts = bc.sample_field(rng, pool, args.field)
    log(f"   {len(field):,} legal lineups from {attempts:,} attempts")
    fidx = np.array([sorted(ids) for ids in field], dtype=np.int32)

    fld_depth, fld_shape = Counter(), Counter()
    opt_depth, opt_shape = Counter(), Counter()
    agree_game = 0
    n = 0
    log(f"\nsolving both winners in each of {args.trials:,} trials")
    for t in range(scores.shape[1]):
        sc = scores[:, t]

        # A. the global optimum, exactly as discover_scenarios reports it
        ids, _tot = ds.solve_trial(sc, meta, rng)
        if not ids:
            continue

        # B. the best entry in the field, on this same realised slate
        totals = sc[fidx].sum(axis=1)
        best = fidx[int(np.argmax(totals))]

        n += 1
        da, ga = depth_of(ids, pool)
        db, gb = depth_of(best, pool)
        opt_depth[da] += 1
        fld_depth[db] += 1
        opt_shape[ds.shape_of(ds.signature(ids, pool)[1])] += 1
        fld_shape[ds.shape_of(ds.signature(list(best), pool)[1])] += 1
        if ga == gb:
            agree_game += 1
        if n % 300 == 0:
            log(f"   {n:,} trials")

    if not n:
        log("no trials solved")
        return 1

    log(f"\n{n:,} trials compared")
    summarise("A. GLOBAL OPTIMUM — what the tool reports today",
              opt_depth, opt_shape, n)
    summarise("B. BEST ENTRY IN THE FIELD — what the contest actually pays",
              fld_depth, fld_shape, n)

    log(f"\nthe two agree on WHICH game to stack in "
        f"{100 * agree_game / n:.1f}% of trials")

    deep_a = sum(c for d, c in opt_depth.items() if d >= 4)
    deep_b = sum(c for d, c in fld_depth.items() if d >= 4)
    log(f"\nfour deep or more:")
    log(f"   global optimum      {100 * deep_a / n:>5.1f}% of wins")
    log(f"   best field entry    {100 * deep_b / n:>5.1f}% of wins")
    log(f"   observed, 2 of 2 real winners were four deep "
        f"(CIN/TEN 1 Nov, GB/NE 8 Nov)")
    if deep_b > deep_a:
        log(f"\n   The field's best entry is deeper stacked than the global "
            f"optimum,\n   by {100 * (deep_b - deep_a) / n:.1f} points of win "
            f"share. The hypothesis survives: the\n   tool is scoring a winner "
            f"the contest never pays.")
    else:
        log(f"\n   The field's best entry is NOT deeper stacked than the "
            f"global optimum.\n   The hypothesis is wrong, and the two real "
            f"four-deep winners need\n   another explanation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
