#!/usr/bin/env python3
"""
discover_scenarios.py — the ways this slate can pay, and who is already there.

THE PROBLEM THIS EXISTS FOR
Everyone has projections now, and everyone has roughly the same ones. A tool
that ranks players by mean, or by ceiling, or by ceiling over ownership, is
computing a first-order statistic that every other tool computes the same way,
so the lineups it builds are the lineups the field builds. Positive expected
value against a field using the same inputs is not an edge.

What is not competed away is the JOINT structure. Two lineups sharing no
players can be the same bet, and two sharing six players can be different bets,
because what a lineup really wagers on is a state of the world: which games go
nuclear and which die. The 1st of November is the cleanest demonstration of
this available. Measured from the Millionaire's own standings, the top 1% of
147,058 entries drew 51.4% of its roster slots from a single game, Cincinnati
against Tennessee, while the whole field drew 12.6% from it. The two games the
field was heaviest on, Arizona/Dallas and Baltimore/Buffalo, returned 0.29x and
0.21x. Nobody could have read that off a player projection, because it is not a
fact about players.

HOW THIS FINDS IT
The projection build already simulates the slate ten thousand times with
teammates correlated through a copula, and then throws the joint structure away
by averaging it into a mean and a set of percentiles. This keeps it.

  1. For every trial, solve for the lineup that would have WON that trial.
     Not the best lineup on average: the best lineup in that particular world.
  2. Describe each winner by where its points came from, as a game-exposure
     signature, rather than by which players it used.
  3. Group them. Each group is a coherent way the slate can pay, and the share
     of trials it wins is how often it pays.
  4. Build the field at projected ownership and describe it the same way, so
     the two are comparable.
  5. Rank by P(scenario wins) / P(field is in it).

A game only needs a fat enough right tail to appear here. It does not need a
high mean, which is exactly why a mean-ranked board cannot see it: on the 1st
of November, Cincinnati/Tennessee was 6th of 13 by projected total.

WHAT IT DOES NOT DO
It does not claim to know which scenario will happen. It says which ones pay
when they happen and how crowded each one already is, which is the part that is
knowable in advance and the part the field is not pricing.

USAGE
  python tools/discover_scenarios.py [--trials 2000] [--field 4000] [--top 20]
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_contest as bc  # noqa: E402

# A game contributing fewer than this many players is not a stack, it is a
# coincidence, so it is not part of what names the scenario.
MIN_STACK = 2
# Restarts of the local search per trial. The solve only has to be good enough
# to land on the right SHAPE; a point or two of score left behind does not move
# a lineup into a different scenario.
RESTARTS = 3
# How many of the trial's top scorers at each position the solver may use.
# A player outside this is not in an optimal lineup for that trial.
TOPK = {"QB": 8, "RB": 16, "WR": 22, "TE": 12, "DST": 6}


def log(*a):
    print(*a, flush=True)


def game_of(p):
    """Both sides of one game, as a stable name."""
    o = p.get("opp") or "?"
    return "/".join(sorted((p["team"], o)))


def solve_trial(scores, pool_meta, rng):
    """The best legal lineup for ONE realised slate.

    An exact solve is a multi-dimensional knapsack and would have to run once
    per trial, so this prunes to each position's top scorers in this trial and
    then does greedy plus swap improvement from several starts. The objective
    is only to identify which shape wins, and shapes are robust to the last
    point of score.
    """
    idx_by_pos, sal, teams = pool_meta
    cand = {}
    for pos, idxs in idx_by_pos.items():
        k = TOPK.get(pos, 12)
        arr = np.asarray(idxs)
        if len(arr) > k:
            arr = arr[np.argsort(-scores[arr])[:k]]
        cand[pos] = arr

    need = [("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1), ("DST", 1)]
    flex_pool = np.concatenate([cand[p] for p in bc.FLEX_OK if len(cand.get(p, []))])

    best, best_score = None, -1e9
    for _ in range(RESTARTS):
        picked = []
        # Seed greedily on value per dollar with a little noise, so the restarts
        # explore different corners instead of returning the same lineup.
        for pos, k in need:
            arr = cand[pos]
            w = scores[arr] / np.maximum(sal[arr], 1)
            w = w * rng.uniform(0.85, 1.15, size=len(arr))
            picked.extend(int(x) for x in arr[np.argsort(-w)[:k]])
        remaining = [int(x) for x in flex_pool if x not in picked]
        if not remaining:
            continue
        picked.append(max(remaining, key=lambda i: scores[i]))

        def legal(ids):
            if sum(sal[i] for i in ids) > bc.CAP:
                return False
            t = Counter(teams[i] for i in ids)
            return max(t.values()) <= bc.MAX_PER_TEAM

        # Repair: drop the worst value until it fits under the cap.
        while not legal(picked):
            worst = min(picked, key=lambda i: scores[i] / max(sal[i], 1))
            pos = None
            for ps, idxs in idx_by_pos.items():
                if worst in idxs:
                    pos = ps
                    break
            repl = [int(x) for x in cand.get(pos, []) if x not in picked
                    and sal[x] < sal[worst]]
            if not repl:
                break
            picked[picked.index(worst)] = max(repl, key=lambda i: scores[i])

        if not legal(picked):
            continue

        # Local search: try replacing each slot with any candidate of a
        # compatible position, keep the first improvement, repeat.
        improved = True
        while improved:
            improved = False
            for s in range(len(picked)):
                cur = picked[s]
                pos = None
                for ps, idxs in idx_by_pos.items():
                    if cur in idxs:
                        pos = ps
                        break
                opts = cand.get(pos, [])
                for alt in opts:
                    alt = int(alt)
                    if alt in picked or scores[alt] <= scores[cur]:
                        continue
                    trial = list(picked)
                    trial[s] = alt
                    if legal(trial):
                        picked = trial
                        improved = True
                        break
                if improved:
                    break
        tot = sum(scores[i] for i in picked)
        if tot > best_score:
            best, best_score = sorted(picked), tot
    return best, best_score


def signature(ids, pool):
    """Describe a lineup by where its points can come from, not by its players.

    Two lineups with the same signature are the same bet even when they share
    no names, which is the distinction player-level leverage cannot draw.

    The scenario is the PRIMARY stack alone — one game and how deep into it the
    lineup goes — and not the full pairing of first and second stack. Naming
    the pair looked more descriptive and was unusable: thirteen games give
    hundreds of ordered pairs, so every cell held a handful of trials, every
    scenario reported about one percent, and the leverage column was noise
    dressed as a number. One game by depth is forty or so cells, which the
    trials can actually populate, and it is also the decision being made.
    The companion game is reported underneath as a breakdown.
    """
    g = Counter(game_of(pool[i]) for i in ids)
    stacks = sorted(((c, k) for k, c in g.items() if c >= MIN_STACK), reverse=True)
    if not stacks:
        return "spread (no game with two players)", (), None
    top_c, top_k = stacks[0]
    parts = tuple((k, c) for c, k in stacks[:2])
    companion = stacks[1][1] if len(stacks) > 1 else None
    return f"{top_k} x{top_c}", parts, companion


def shape_of(parts):
    """The abstract form, with the game names removed: '4-2', '3', 'spread'."""
    if not parts:
        return "spread"
    return "-".join(str(c) for _, c in parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=2000)
    ap.add_argument("--field", type=int, default=4000)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--calibrate", type=float, default=0.0,
                    help="compress projected ownership by this exponent before "
                         "sampling the field (0 = off; 0.71 was fitted on the "
                         "1 November Millionaire)")
    args = ap.parse_args()

    bpath = os.path.join(DATA, "nfl_slate_board.json")
    if not os.path.exists(bpath):
        log("no nfl_slate_board.json; run build_nfl_slate.py first")
        return 1
    with open(bpath, encoding="utf-8") as f:
        board = json.load(f)

    log(f"slate: {board.get('slate', {}).get('name', '?')}")
    log(f"regenerating the joint simulation at {args.trials:,} trials")
    import build_projections as bp
    sims, _ = bp.player_scores(args.trials, "dk")
    pool = bc.build_pool(board, sims)
    log(f"{len(pool)} players in the playable pool")

    # The field is sampled at PROJECTED ownership, so every error in that
    # projection lands in the denominator of every leverage number here. On
    # 1 November the projection was badly over-dispersed, and the simulated
    # field inherited it whole: it put 37.3% of itself in Miami/New England,
    # which really drew 10.7%, because the model had Malik Willis at 18.8%
    # when the field had him at 1.8%. Compressing the projection toward the
    # middle before sampling is the cheapest available correction.
    if args.calibrate:
        slots = {"QB": 100.0, "DST": 100.0}
        pooled = {"RB", "WR", "TE"}
        raw = {}
        for pl in pool:
            raw[id(pl)] = max(pl["own"], 0.01) ** args.calibrate
        for group, target in list(slots.items()) + [("_flex", 700.0)]:
            members = [pl for pl in pool
                       if (pl["pos"] in pooled if group == "_flex"
                           else pl["pos"] == group)]
            tot = sum(raw[id(pl)] for pl in members)
            if tot <= 0:
                continue
            for pl in members:
                pl["own"] = raw[id(pl)] * target / tot
        log(f"   ownership compressed by ^{args.calibrate} and renormalised "
            f"to the roster slots")

    scores = np.vstack([p["fp"] for p in pool])          # players x trials
    sal = np.array([p["sal"] for p in pool])
    teams = [p["team"] for p in pool]
    idx_by_pos = defaultdict(list)
    for i, p in enumerate(pool):
        idx_by_pos[p["pos"]].append(i)
    idx_by_pos = {k: np.asarray(v) for k, v in idx_by_pos.items()}
    meta = (idx_by_pos, sal, teams)

    # ---- 1-3. what wins, trial by trial
    rng = np.random.default_rng(bc.SEED)
    n = scores.shape[1]
    log(f"\nsolving the winning lineup in each of {n:,} simulated slates")
    win_sig = Counter()
    win_shape = Counter()
    sig_players = defaultdict(Counter)
    sig_companion = defaultdict(Counter)
    solved = 0
    for t in range(n):
        ids, _tot = solve_trial(scores[:, t], meta, rng)
        if not ids:
            continue
        solved += 1
        name, parts, companion = signature(ids, pool)
        win_sig[name] += 1
        win_shape[shape_of(parts)] += 1
        if companion:
            sig_companion[name][companion] += 1
        # Only the players from the stacked game. Counting all nine mixed the
        # bet in with the filler, so the census listed names from games the
        # scenario is not about.
        stack_game = name.rsplit(" x", 1)[0]
        for i in ids:
            if game_of(pool[i]) == stack_game:
                sig_players[name][pool[i]["name"]] += 1
        if solved % 500 == 0:
            log(f"   {solved:,} solved")
    log(f"   {solved:,} trials produced a legal winner")
    if not solved:
        log("no trials solved; the pool is probably too small")
        return 1

    # ---- 4. where the field already is
    log(f"\nbuilding a field of {args.field:,} lineups at projected ownership")
    field, attempts = bc.sample_field(rng, pool, args.field)
    log(f"   {len(field):,} legal lineups from {attempts:,} attempts")
    field_sig = Counter()
    field_shape = Counter()
    for ids in field:
        name, parts, _c = signature(ids, pool)
        field_sig[name] += 1
        field_shape[shape_of(parts)] += 1

    # ---- 5. leverage
    nf = max(len(field), 1)
    rows = []
    for name, wins in win_sig.items():
        pw = wins / solved
        pf = field_sig.get(name, 0) / nf
        # A scenario the sampled field never produced is not infinitely good,
        # it is merely rarer than one lineup in the sample, so it is floored
        # there rather than reported as a divide by zero.
        pf_eff = max(pf, 1.0 / nf)
        rows.append({"scenario": name, "pWin": pw, "field": pf,
                     "leverage": pw / pf_eff, "wins": wins})
    rows.sort(key=lambda r: -r["leverage"])

    log("\n" + "=" * 78)
    log("SCENARIOS BY LEVERAGE — how often it wins against how crowded it is")
    log("=" * 78)
    log(f"{'scenario':42}{'wins%':>8}{'field%':>8}{'lev':>8}")
    shown = [r for r in rows if r["wins"] >= max(3, solved * 0.004)][:args.top]
    for r in shown:
        log(f"{r['scenario'][:41]:42}{100*r['pWin']:>7.1f}%{100*r['field']:>7.1f}%"
            f"{r['leverage']:>8.1f}")
        top = ", ".join(f"{n} ({100*c/r['wins']:.0f}%)"
                        for n, c in sig_players[r["scenario"]].most_common(4))
        log(f"   from that game: {top}")
        comp = sig_companion[r["scenario"]].most_common(2)
        if comp:
            log("   paired with:    " + ", ".join(
                f"{k} ({100*v/r['wins']:.0f}%)" for k, v in comp))

    log("\nby abstract shape, ignoring which game it was:")
    log(f"{'shape':14}{'wins%':>8}{'field%':>8}{'lev':>8}")
    for shape, wins in win_shape.most_common(8):
        pw = wins / solved
        pf = max(field_shape.get(shape, 0) / nf, 1.0 / nf)
        log(f"{shape:14}{100*pw:>7.1f}%{100*field_shape.get(shape,0)/nf:>7.1f}%"
            f"{pw/pf:>8.1f}")

    out = {
        "built": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slate": board.get("slate"),
        "trials": solved, "field": int(len(field)),
        "scenarios": [
            {**r, "players": [n for n, _ in sig_players[r["scenario"]].most_common(9)],
             "companions": dict(sig_companion[r["scenario"]].most_common(3))}
            for r in rows if r["wins"] >= 2
        ],
        "shapes": [{"shape": s, "wins": w, "pWin": w / solved,
                    "field": field_shape.get(s, 0) / nf}
                   for s, w in win_shape.most_common()],
    }
    path = os.path.join(DATA, "nfl_scenarios.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    log(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
