#!/usr/bin/env python3
"""
build_structured_lineup.py — build to the structure, not to the projection.

WHY THIS IS NOT THE OPTIMIZER
The optimizer maximises points under a salary cap, which is what every other
optimizer on the slate also does, so it lands on the lineups everybody else
lands on. This builds to the three structural rules that have actually been
measured against real contests, and only then maximises inside them:

  FOUR DEEP IN ONE GAME. The best entry in a simulated field is four or more
  deep in a single game 40.5% of the time, against 10.2% for the unconstrained
  optimum (compare_winner_shapes.py). Both real winners on record were four
  deep: CIN/TEN on 1 November, GB/NE on 8 November.

  TOTAL OWNERSHIP NEAR 100%. The 8 November winner totalled 90.6%. Lineups
  ranked by raw projection average 141.3%. The cap costs about 4.5 projected
  points, roughly 3%, which is the cheapest differentiation available.

  CHEAP CORRELATION. Take the unowned piece of the stacked game rather than
  the obvious bring-back. Darren Waller was 0.7% owned at $3,300 for 23.00
  points and 6.86x measured winner leverage on 8 November.

The objective inside those constraints is CEILING, not mean. A tournament pays
the top of the distribution and the mean is what the field is already pricing.

WHAT IT DOES NOT DO
It does not pick the game for you on any claim of skill. The leverage ordering
scored -0.01 against 8 November, so the game is enumerated rather than ranked:
every game is tried as the stack and the results are reported per game, for you
to choose on your own read.

USAGE
  python tools/build_structured_lineup.py [--own-cap 110] [--stack 4] [--top 5]
"""
import argparse
import json
import os
import random
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

CAP = 50_000
MAX_PER_TEAM = 8
SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
FLEX_OK = ("RB", "WR", "TE")


def log(*a):
    print(*a, flush=True)


def game_of(p):
    return "/".join(sorted((p["team"], p.get("opp") or "?")))


def load_pool():
    with open(os.path.join(DATA, "nfl_slate_board.json"), encoding="utf-8") as f:
        board = json.load(f)
    pool = []
    for p in board["players"]:
        own = (p.get("own") or {}).get("mme")
        if p.get("proj") is None or own is None or not p.get("sal"):
            continue
        if not p.get("opp"):
            continue
        pool.append({
            "player": p["player"], "pos": p["pos"], "team": p["team"],
            "opp": p["opp"], "sal": p["sal"], "own": own,
            "proj": p["proj"], "ceil": p.get("ceil") or p["proj"],
            "game": game_of(p),
        })
    return board, pool


# A defence and the offence it is playing against want opposite things. A
# lineup holding both is betting against itself, and an optimiser that only
# sees means will build one happily, because nothing in a mean says two players
# cannot both do well. The 8 November winner had Kansas City's defence beside
# Kenneth Walker, a Kansas City running back, which is the right version: same
# side, and they rise together when the team leads and runs the ball.
MAX_OPPOSING_SKILL_WITH_DST = 1

# Two running backs from the same team share one pool of carries, so they are
# negatively correlated and cannot both go off. A builder that only reads means
# will happily take a whole backfield, because nothing in a mean forbids it.
MAX_RB_PER_TEAM = 1


def legal(ids, pool, own_cap):
    if len(set(ids)) != len(SLOTS):
        return False
    sel = [pool[i] for i in ids]
    if sum(p["sal"] for p in sel) > CAP:
        return False
    if sum(p["own"] for p in sel) > own_cap:
        return False
    t = defaultdict(int)
    for p in sel:
        t[p["team"]] += 1
    if max(t.values()) > MAX_PER_TEAM:
        return False
    rb = defaultdict(int)
    for p in sel:
        if p["pos"] == "RB":
            rb[p["team"]] += 1
    if rb and max(rb.values()) > MAX_RB_PER_TEAM:
        return False
    for d in sel:
        if d["pos"] != "DST":
            continue
        against = sum(1 for p in sel
                      if p["pos"] != "DST" and p["team"] == d["opp"])
        if against > MAX_OPPOSING_SKILL_WITH_DST:
            return False
    return True


def fills_roster(sel):
    """Can these nine players be assigned to the nine DK slots?"""
    need = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DST": 1}
    have = defaultdict(int)
    for p in sel:
        have[p["pos"]] += 1
    flex = 0
    for pos, n in need.items():
        if have[pos] < n:
            return False
        if pos in FLEX_OK:
            flex += have[pos] - n
    return flex == 1 and have["QB"] == 1 and have["DST"] == 1


def build_for_game(pool, game, own_cap, stack, rng, iters):
    """Best lineup we can find that takes `stack` players from `game`."""
    # Skill players only. A defence in the stacked game is not a piece of that
    # game going off, it is a bet on the opposite, so counting it toward the
    # four produced "stacks" that were three skill players and a defence
    # rooting against two of them.
    inside = [i for i, p in enumerate(pool)
              if p["game"] == game and p["pos"] != "DST"]
    outside = [i for i, p in enumerate(pool)
               if p["game"] != game or p["pos"] == "DST"]
    if len(inside) < stack:
        return None
    best = None
    for _ in range(iters):
        # Weight toward ceiling per point of ownership, which is what pushes
        # the build onto the unowned pieces of the game rather than its chalk.
        def weight(i):
            p = pool[i]
            return (p["ceil"] / max(p["own"], 1.0)) * rng.uniform(0.6, 1.4)

        # A game stack is a QUARTERBACK and the players he throws to, plus
        # somebody from the other side. Without that it was choosing whichever
        # four players in the game had the best ceiling per point of ownership,
        # which came back as three running backs who cannot all be fed.
        qbs = [i for i in inside if pool[i]["pos"] == "QB"]
        if not qbs:
            continue
        qb = max(qbs, key=weight)
        mates = [i for i in inside
                 if pool[i]["team"] == pool[qb]["team"]
                 and pool[i]["pos"] in ("WR", "TE")]
        backs = [i for i in inside if pool[i]["team"] != pool[qb]["team"]
                 and pool[i]["pos"] in ("WR", "TE", "RB")]
        if len(mates) < 1 or not backs:
            continue
        mates.sort(key=weight, reverse=True)
        backs.sort(key=weight, reverse=True)
        # QB, then his receivers, then one bring-back from the other side.
        pick = [qb] + mates[:max(1, stack - 2)] + backs[:1]
        pick = list(dict.fromkeys(pick))[:stack]
        if len(pick) < stack:
            pick += [i for i in mates + backs if i not in pick][:stack - len(pick)]
        if len(pick) < stack:
            continue
        rest = sorted(outside, key=weight, reverse=True)
        sel = list(pick)
        for i in rest:
            if len(sel) == len(SLOTS):
                break
            trial = sel + [i]
            if len(trial) < len(SLOTS):
                # Keep the partial roster assignable: never take a second QB
                # or DST, and leave room for the ones still required.
                cnt = defaultdict(int)
                for j in trial:
                    cnt[pool[j]["pos"]] += 1
                if cnt["QB"] > 1 or cnt["DST"] > 1:
                    continue
                if cnt["RB"] > 3 or cnt["WR"] > 4 or cnt["TE"] > 2:
                    continue
                sel = trial
            else:
                sel = trial
        if len(sel) != len(SLOTS) or not fills_roster([pool[i] for i in sel]):
            continue
        # Repair: while illegal, drop the worst ceiling-per-dollar piece from
        # OUTSIDE the stack and try a cheaper or less owned replacement.
        for _ in range(60):
            if legal(sel, pool, own_cap):
                break
            swappable = [i for i in sel if i not in pick]
            if not swappable:
                break
            worst = min(swappable,
                        key=lambda i: pool[i]["ceil"] / max(pool[i]["sal"], 1))
            opts = [i for i in outside
                    if i not in sel and pool[i]["pos"] == pool[worst]["pos"]
                    and (pool[i]["sal"] < pool[worst]["sal"]
                         or pool[i]["own"] < pool[worst]["own"])]
            if not opts:
                break
            sel[sel.index(worst)] = max(opts, key=lambda i: pool[i]["ceil"])
        if not legal(sel, pool, own_cap) or not fills_roster([pool[i] for i in sel]):
            continue
        # Improve: any single swap that raises ceiling and stays legal.
        improved = True
        while improved:
            improved = False
            for s in list(sel):
                if s in pick:
                    continue
                for alt in outside:
                    if alt in sel or pool[alt]["pos"] != pool[s]["pos"]:
                        continue
                    if pool[alt]["ceil"] <= pool[s]["ceil"]:
                        continue
                    trial = [alt if x == s else x for x in sel]
                    if legal(trial, pool, own_cap) and fills_roster(
                            [pool[i] for i in trial]):
                        sel = trial
                        improved = True
                        break
                if improved:
                    break
        tot = sum(pool[i]["ceil"] for i in sel)
        if best is None or tot > best[0]:
            best = (tot, sorted(sel))
    return best


def show(pool, ids, label):
    sel = sorted((pool[i] for i in ids),
                 key=lambda p: (SLOTS.index(p["pos"]) if p["pos"] in SLOTS else 7))
    g = defaultdict(int)
    for p in sel:
        g[p["game"]] += 1
    log(f"\n{label}")
    log(f"   {'pos':5}{'player':22}{'team':6}{'game':11}{'sal':>7}{'own':>7}"
        f"{'proj':>7}{'ceil':>7}")
    for p in sel:
        log(f"   {p['pos']:5}{p['player'][:21]:22}{p['team']:6}{p['game']:11}"
            f"{p['sal']:>7}{p['own']:>6.1f}%{p['proj']:>7.1f}{p['ceil']:>7.1f}")
    log(f"   {'':5}{'TOTAL':22}{'':6}{'':11}"
        f"{sum(p['sal'] for p in sel):>7}{sum(p['own'] for p in sel):>6.1f}%"
        f"{sum(p['proj'] for p in sel):>7.1f}{sum(p['ceil'] for p in sel):>7.1f}")
    shape = "-".join(str(c) for _, c in
                     sorted(g.items(), key=lambda kv: -kv[1]) if c >= 2)
    log(f"   stack: {shape or 'none'}   "
        + ", ".join(f"{k} x{v}" for k, v in
                    sorted(g.items(), key=lambda kv: -kv[1]) if v >= 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--own-cap", type=float, default=110.0)
    ap.add_argument("--stack", type=int, default=4)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--iters", type=int, default=600)
    ap.add_argument("--seed", type=int, default=20261115)
    ap.add_argument("--avoid", default="",
                    help="comma separated players to leave out, for building a "
                         "PORTFOLIO rather than one lineup. Each build is solved "
                         "independently, so they converge on the same best value "
                         "plays and end up sharing them; if the same two players "
                         "are in every lineup and both bust, every lineup dies "
                         "together, which is the one risk entering several "
                         "lineups is supposed to remove.")
    args = ap.parse_args()

    board, pool = load_pool()
    avoid = {a.strip().lower() for a in args.avoid.split(",") if a.strip()}
    if avoid:
        before = len(pool)
        pool = [p for p in pool
                if not any(a in p["player"].lower() for a in avoid)]
        log(f"avoiding {len(avoid)} player(s): {before - len(pool)} removed")
    log(f"slate: {board['slate']['name']}   built {board['built']}")
    log(f"{len(pool)} players with a projection, an ownership and an opponent")
    log(f"structure: {args.stack} deep in one game, "
        f"total ownership at most {args.own_cap:.0f}%, maximising CEILING")

    rng = random.Random(args.seed)
    games = sorted({p["game"] for p in pool})
    out = []
    for g in games:
        r = build_for_game(pool, g, args.own_cap, args.stack, rng, args.iters)
        if r:
            out.append((r[0], g, r[1]))
    if not out:
        log("\nnothing legal at this ownership cap; raise --own-cap")
        return 1
    out.sort(reverse=True)

    log("\n" + "=" * 78)
    log(f"BEST BUILD PER STACKED GAME, by ceiling")
    log("=" * 78)
    log(f"   {'game':12}{'ceiling':>9}{'proj':>8}{'own':>8}{'salary':>9}")
    for tot, g, ids in out:
        sel = [pool[i] for i in ids]
        log(f"   {g:12}{tot:>9.1f}{sum(p['proj'] for p in sel):>8.1f}"
            f"{sum(p['own'] for p in sel):>7.1f}%{sum(p['sal'] for p in sel):>9,}")

    for tot, g, ids in out[:args.top]:
        show(pool, ids, f"STACK {g}  —  ceiling {tot:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
