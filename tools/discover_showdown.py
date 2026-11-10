#!/usr/bin/env python3
"""
discover_showdown.py — which captain and which shape win a single-game slate.

WHY THE CLASSIC TOOL CANNOT DO THIS
discover_scenarios.py describes a winning lineup by which game it stacked and
how deep. In a showdown every lineup is six players from one game by rule, so
that signature collapses to a single cell holding 100% of the win share against
100% of the field, with leverage of exactly 1.00. It would not be wrong, it
would be vacuous.

So the scenario has to be re-pointed at the decisions that actually differ
between two showdown lineups:

  1. CAPTAIN. The format's one real lever. The captain scores 1.5x and costs
     1.5x, so a leveraged captain compounds: 1.5x the points inside a small
     slice of the field. No classic roster slot has that property.
  2. TEAM SPLIT. How many of the six come from each side, which is the direct
     analogue of stack depth. 5-1 is a bet on one team running away with it,
     3-3 is a bet on a back and forth game.
  3. GAME SCRIPT. You only have one game, so you cannot condition on which
     game breaks. You condition on HOW it breaks, and report the winning shape
     inside each kind of break. This is the closest thing to the original
     intent: in classic, "which game" was only ever a proxy for "which game
     goes off".

WHY THIS FORMAT SUITS THE METHOD BETTER THAN CLASSIC
The pool is the game, about fifty priced players and fewer than thirty with a
real projection, against 586 on a main slate. Two consequences matter. The
classic field model's worst known flaw, that 280 of 586 players absorb all 900%
of the ownership and inflate pair frequencies about twofold, is largely an
artifact of pool size. And six slots out of a pool this small can be solved
EXACTLY, so unlike the classic tool there is no greedy heuristic between the
simulation and the answer: every captain is enumerated and every legal filling
of the other five slots is evaluated.

WHAT THIS DOES NOT DO
Stage one reports win rates only. Win rate is the measured half: it is the
share of simulated games whose best possible lineup had that shape, and nothing
about the field enters it. It deliberately does NOT report field share or
leverage, because a showdown field needs a CAPTAIN ownership model (captain
ownership sums to 100% and flex to 500%, two different distributions) and no
such model exists here yet, nor any measured showdown contest to fit one
against. Shipping a leverage column off unvalidated priors is exactly how the
classic field column ended up needing a warning box, and a lineup's payoff
depends on the field, so an unvalidated denominator is worse than an absent one.

USAGE
  python tools/discover_showdown.py [--trials 1500] [--dg 156013] [--top 14]
"""
import argparse
import datetime
import itertools
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from enrich_props import nrm  # noqa: E402

# DraftKings showdown captain mode.
CAP = 50_000
ROSTER = 6                 # one captain plus five flex
FLEX_SLOTS = ROSTER - 1
CPT_MULT = 1.5             # applies to BOTH the score and the salary
SEED = 20261109

# Above this many projectable players the full enumeration of five-player
# fillings gets expensive, so the candidate set is reduced per trial. A real
# showdown pool is about 25 once the unprojectable deep roster is dropped, so
# this is set above that and the solve is normally exact.
MAX_EXACT = 30
# When reduction is needed: the best scorers, plus the cheapest, because the
# salary cap means an optimal showdown lineup routinely needs a punt and
# ranking candidates by score alone would never offer one.
RED_SCORE = 20
RED_CHEAP = 10


def log(*a):
    print(*a, flush=True)


def load_slate(dg=None):
    """The showdown slate to solve, from the archived DK draft groups.

    Returns (slate, status). Status separates "nothing to solve right now",
    which is the ordinary state midweek before DraftKings posts the weekend,
    from "something is broken". The scheduled job must not fail on the former,
    and must not pass silently on the latter.
    """
    path = os.path.join(DATA, "nfl_dk.json")
    if not os.path.exists(path):
        log("no data/nfl_dk.json; run tools/fetch_nfl.py first")
        return None, "error"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    sd = [s for s in doc.get("slates", []) if s.get("kind") == "showdown"]
    if not sd:
        log("no showdown slates in data/nfl_dk.json; nothing to solve")
        return None, "empty"
    if dg:
        hit = [s for s in sd if str(s["dg"]) == str(dg)]
        if not hit:
            log(f"dg {dg} is not a showdown slate in the archive. Available:")
            for s in sd:
                log(f"   dg={s['dg']:<8} {s['entries']:>8,} entries  {s['name']}")
            return None, "error"
        slate = hit[0]
    else:
        # Upcoming games only, THEN by entry count. Ranking by entries alone
        # silently solved a game that had already been played: run on a Monday,
        # Sunday night's showdown still carries the most entries in the archive
        # and would win the comparison every time.
        now = datetime.datetime.now(datetime.timezone.utc)
        upcoming = []
        for s in sd:
            try:
                st = datetime.datetime.strptime(
                    s.get("start") or "", "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=datetime.timezone.utc)
            except ValueError:
                continue
            if st > now:
                upcoming.append(s)
        if not upcoming:
            log("no showdown in the archive has a future start time; every one "
                "of these has already locked. Refresh data/nfl_dk.json, or pass "
                "--dg to solve a past game deliberately:")
            for s in sorted(sd, key=lambda x: x.get("start") or ""):
                log(f"   dg={s['dg']:<8} {s['entries']:>8,} entries  "
                    f"starts {s.get('start','?')}  {s['name']}")
            return None, "empty"
        slate = max(upcoming, key=lambda s: s.get("entries") or 0)
        if len(upcoming) < len(sd):
            log(f"{len(sd) - len(upcoming)} showdown slate(s) ignored as "
                f"already started")
    slate["_built"] = doc.get("built")
    return slate, "ok"


def build_pool(slate, sims):
    """Join the showdown's priced players onto the correlated simulation.

    The DK rows carry their own team code, so a defence is keyed straight to
    `dst_<TEAM>` rather than matched on DraftKings' nickname for it ("Bears"),
    which never had to be a name-matching problem at all.
    """
    teams = sorted({p["tm"] for p in slate["players"] if p["tm"]})
    if len(teams) != 2:
        log(f"expected two teams, found {teams}")
        return None, None
    other = {teams[0]: teams[1], teams[1]: teams[0]}

    pool, missing = [], []
    for p in slate["players"]:
        key = f"dst_{p['tm']}" if p["pos"] == "DST" else nrm(p["n"])
        fp = sims.get(key)
        if fp is None:
            missing.append(p)
            continue
        pool.append({
            "key": key, "name": p["n"], "pos": p["pos"], "team": p["tm"],
            "opp": other.get(p["tm"]), "sal": int(p["sal"]), "fp": np.asarray(fp),
        })

    log(f"\npool: {len(pool)} of {len(slate['players'])} priced players have a "
        f"simulated score")
    if missing:
        by_pos = Counter(m["pos"] for m in missing)
        log(f"   excluded {len(missing)}: {dict(by_pos)}")
        # Said out loud rather than dropped silently. A priced-up starter with
        # no projection is a data problem worth seeing; a $200 fourth-string
        # running back is not.
        notable = sorted([m for m in missing if m["sal"] >= 4000],
                         key=lambda m: -m["sal"])
        if notable:
            log("   of those, priced at $4,000 or more, so worth checking:")
            for m in notable:
                why = ("no kicker model exists" if m["pos"] == "K"
                       else "not in the projection build")
                log(f"      {m['pos']:4} {m['n']:24} ${m['sal']:<7} {m['tm']}  ({why})")
    return pool, teams


def combos_for(n):
    """Every way to fill the five flex slots from n candidates."""
    return np.array(list(itertools.combinations(range(n), FLEX_SLOTS)),
                    dtype=np.int32)


def candidates(score, cheap_order, width):
    """Exactly `width` distinct player indices: best scorers first, then the
    cheapest to make a punt reachable.

    It must return exactly `width`, because the combination table is built once
    for that size and indexes into this list. Deduplicating with np.unique
    returned fewer whenever a cheap player was also a top scorer, and the
    shortfall surfaced as an out-of-bounds index rather than a bad answer.
    """
    picked, seen = [], set()
    n_score = min(RED_SCORE, width)
    for i in itertools.chain(np.argsort(-score)[:n_score], cheap_order):
        i = int(i)
        if i in seen:
            continue
        seen.add(i)
        picked.append(i)
        if len(picked) == width:
            break
    return np.array(sorted(picked), dtype=np.int64)


def solve_trial(score, sal, is_a, cand, combos, contains):
    """The best legal showdown lineup for ONE realised game, solved exactly.

    Every candidate is tried as captain. For a fixed captain the remaining
    problem is to pick five others maximising score under the leftover cap, and
    because the combination list is enumerated once and scored as a vector, the
    best filling is found rather than approximated. The captain dimension is
    the one that names the scenario, so it is the one that must not be left to
    a heuristic.

    Returns (captain_index, flex_indices, total) in POOL indices.
    """
    cs, csal, ca = score[cand], sal[cand], is_a[cand]
    # Computed once per trial: these do not depend on who captains.
    combo_score = cs[combos].sum(axis=1)
    combo_sal = csal[combos].sum(axis=1)
    combo_a = ca[combos].sum(axis=1)
    order = np.argsort(-combo_score)
    s_score = combo_score[order]
    s_sal = combo_sal[order]
    s_a = combo_a[order]

    best = (None, None, -1e18)
    for c in range(len(cand)):
        budget = CAP - int(round(csal[c] * CPT_MULT))
        if budget < 0:
            continue
        # DraftKings requires at least one player from each side. The captain
        # covers his own team, so the five flex must supply the other.
        if ca[c]:
            ok = s_a < FLEX_SLOTS          # captain is team A: need a B
        else:
            ok = s_a > 0                   # captain is team B: need an A
        valid = ok & (s_sal <= budget) & ~contains[c][order]
        k = int(np.argmax(valid))
        if not valid[k]:
            continue
        tot = cs[c] * CPT_MULT + s_score[k]
        if tot > best[2]:
            best = (int(cand[c]), cand[combos[order[k]]], float(tot))
    return best


def script_of(total, margin, t_lo, t_hi, m_hi):
    """How the game broke, in terms the simulation itself defines.

    Thresholds are terciles of this game's own simulated distribution rather
    than absolute point totals, so the buckets mean the same thing in a 38
    point game and a 56 point game. What is bucketed is combined offensive
    FANTASY output and the gap between the two sides, which is a proxy for the
    game script and not a predicted scoreline.
    """
    if margin >= m_hi:
        return "blowout (one side runs away)"
    if total >= t_hi:
        return "shootout (both sides produce)"
    if total <= t_lo:
        return "grind (neither side produces)"
    return "ordinary (nothing extreme)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--dg", default="", help="showdown draft group to solve")
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("--out", default="nfl_showdown_scenarios.json")
    args = ap.parse_args()

    slate, status = load_slate(args.dg)
    if not slate:
        # "empty" is a normal midweek state, so the scheduled job must not go
        # red for it. Only a genuine problem returns non-zero.
        return 0 if status == "empty" else 1
    log(f"slate: {slate['name']}  (dg={slate['dg']}, "
        f"{slate['entries']:,} entries, starts {slate.get('start','?')})")
    log(f"draft groups archived {slate.get('_built')}")

    log(f"\nregenerating the joint simulation at {args.trials:,} trials")
    import build_projections as bp
    sims, _res = bp.player_scores(args.trials, "dk")

    pool, teams = build_pool(slate, sims)
    if not pool or len(pool) < ROSTER:
        log("not enough projectable players to fill a lineup")
        return 1
    team_a = teams[0]
    if not any(p["team"] == teams[1] for p in pool):
        log(f"every projectable player is on {team_a}; "
            f"DraftKings requires both sides")
        return 1

    scores = np.vstack([p["fp"] for p in pool])        # players x trials
    sal = np.array([p["sal"] for p in pool], dtype=np.int64)
    is_a = np.array([p["team"] == team_a for p in pool])
    n, n_trials = scores.shape
    log(f"   {n} players x {n_trials:,} trials, "
        f"{int(is_a.sum())} {team_a} / {int((~is_a).sum())} {teams[1]}")

    exact = n <= MAX_EXACT
    width = n if exact else min(MAX_EXACT, RED_SCORE + RED_CHEAP, n)
    combos = combos_for(width)
    # contains[j] marks the combinations that already use candidate j, so a
    # captain is never also counted in his own flex.
    contains = np.zeros((width, len(combos)), dtype=bool)
    for j in range(width):
        contains[j] = (combos == j).any(axis=1)
    log(f"   solve: {'EXACT over all ' if exact else 'reduced to '}{width} "
        f"candidates, {len(combos):,} fillings per captain"
        f"{'' if exact else f' (pool is larger than {MAX_EXACT})'}")

    # Game script buckets, from the simulation's own spread.
    off = np.array([p["pos"] != "DST" for p in pool])
    fp_a = scores[off & is_a].sum(axis=0)
    fp_b = scores[off & ~is_a].sum(axis=0)
    tot_fp, marg_fp = fp_a + fp_b, np.abs(fp_a - fp_b)
    t_lo, t_hi = np.percentile(tot_fp, [33.3, 66.7])
    m_hi = np.percentile(marg_fp, 66.7)
    log(f"   script terciles: total {t_lo:.0f}/{t_hi:.0f} fantasy points, "
        f"margin {m_hi:.0f}")

    cheap_order = np.argsort(sal)
    all_idx = np.arange(n, dtype=np.int64)
    cpt_wins = Counter()
    shape_wins = Counter()
    script_wins = Counter()
    script_shape = defaultdict(Counter)
    cpt_by_script = defaultdict(Counter)
    split_wins = Counter()
    partners = defaultdict(Counter)
    solved = 0
    illegal = 0

    log(f"\nsolving the winning lineup in each of {n_trials:,} simulated games")
    for t in range(n_trials):
        sc = scores[:, t]
        cand = all_idx if exact else candidates(sc, cheap_order, width)
        cpt, flex, _tot = solve_trial(sc, sal, is_a, cand, combos, contains)
        if cpt is None:
            continue
        solved += 1

        ids = [cpt] + [int(x) for x in flex]
        # Cheap insurance on live data. The solver is proven against a brute
        # force in test_showdown_solver.py, but that runs on synthetic pools,
        # and an illegal lineup here would score well and look like a great
        # scenario rather than like a bug.
        spend = int(round(sal[cpt] * CPT_MULT)) + int(sal[ids[1:]].sum())
        if (len(set(ids)) != ROSTER or spend > CAP
                or len({is_a[i] for i in ids}) < 2):
            illegal += 1
            continue
        c = pool[cpt]
        same = sum(1 for i in ids if pool[i]["team"] == c["team"])
        split = f"{same}-{ROSTER - same}"
        shape = f"CPT {c['pos']} · {split} {c['team']}"
        scr = script_of(tot_fp[t], marg_fp[t], t_lo, t_hi, m_hi)

        cpt_wins[c["name"]] += 1
        shape_wins[shape] += 1
        split_wins[split] += 1
        script_wins[scr] += 1
        script_shape[scr][shape] += 1
        cpt_by_script[scr][c["name"]] += 1
        for i in ids[1:]:
            partners[c["name"]][pool[i]["name"]] += 1
        if solved % 500 == 0:
            log(f"   {solved:,} solved")

    if not solved:
        log("no trial produced a legal lineup")
        return 1
    log(f"   {solved:,} games produced a legal winner")
    if illegal:
        log(f"   WARNING: {illegal:,} solved lineups broke a roster rule "
            f"and were discarded; the solver has a bug")

    meta = {p["name"]: p for p in pool}

    log("\n" + "=" * 76)
    log("CAPTAINS — share of simulated games whose best lineup captained him")
    log("=" * 76)
    log(f"{'captain':24}{'pos':5}{'team':6}{'salary':>8}{'cpt cost':>10}{'wins%':>8}")
    for name, w in cpt_wins.most_common(args.top):
        p = meta[name]
        log(f"{name[:23]:24}{p['pos']:5}{p['team']:6}${p['sal']:>7,}"
            f"${int(round(p['sal']*CPT_MULT)):>9,}{100*w/solved:>7.1f}%")
        mates = ", ".join(f"{m} ({100*c/w:.0f}%)"
                          for m, c in partners[name].most_common(4))
        log(f"   most often with: {mates}")

    log("\n" + "=" * 76)
    log("SHAPES — captain position and how the six split across the two sides")
    log("=" * 76)
    log(f"{'shape':34}{'wins%':>8}")
    for shape, w in shape_wins.most_common(12):
        log(f"{shape[:33]:34}{100*w/solved:>7.1f}%")

    log("\nteam split alone, ignoring who captained "
        "(first number is the captain's own side):")
    for split, w in sorted(split_wins.items(), key=lambda kv: -kv[1]):
        log(f"   {split:8}{100*w/solved:>7.1f}%")

    log("\n" + "=" * 76)
    log("GAME SCRIPT — how the game broke, and what won when it did")
    log("=" * 76)
    for scr, w in script_wins.most_common():
        log(f"\n{scr}   ({100*w/solved:.1f}% of games)")
        for shape, c in script_shape[scr].most_common(3):
            log(f"   {shape[:38]:40}{100*c/w:>6.1f}% of those")
        top = ", ".join(f"{nm} ({100*c/w:.0f}%)"
                        for nm, c in cpt_by_script[scr].most_common(3))
        log(f"   usual captain: {top}")

    out = {
        "built": datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slate": {"dg": slate["dg"], "name": slate["name"],
                  "entries": slate.get("entries"), "start": slate.get("start"),
                  "teams": teams},
        "trials": solved,
        "exactSolve": bool(exact),
        "poolSize": n,
        "priced": len(slate["players"]),
        "stage": 1,
        # Named so the page cannot accidentally render an absent denominator as
        # if it were a measurement. Stage two adds captain ownership.
        "hasFieldModel": False,
        "captains": [
            {"player": nm, "pos": meta[nm]["pos"], "team": meta[nm]["team"],
             "sal": meta[nm]["sal"],
             "cptSal": int(round(meta[nm]["sal"] * CPT_MULT)),
             "wins": w, "pWin": w / solved,
             "partners": dict(partners[nm].most_common(5))}
            for nm, w in cpt_wins.most_common()
        ],
        "shapes": [{"shape": s, "wins": w, "pWin": w / solved}
                   for s, w in shape_wins.most_common()],
        "splits": [{"split": s, "wins": w, "pWin": w / solved}
                   for s, w in sorted(split_wins.items(), key=lambda kv: -kv[1])],
        "scripts": [
            {"script": s, "wins": w, "pWin": w / solved,
             "shapes": [{"shape": sh, "pWithin": c / w}
                        for sh, c in script_shape[s].most_common(5)],
             "captains": [{"player": nm, "pWithin": c / w}
                          for nm, c in cpt_by_script[s].most_common(5)]}
            for s, w in script_wins.most_common()
        ],
    }
    path = os.path.join(DATA, args.out)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    log(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
