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
from captain_ownership import captain_ownership, describe as cpt_own_note  # noqa: E402
from flex_ownership import (flex_ownership, is_rostered,  # noqa: E402
                            describe as flex_own_note)
import kicker_model as kick  # noqa: E402

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


def _start_of(s):
    try:
        return datetime.datetime.strptime(
            s.get("start") or "", "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def load_slates(dg=None, want=2):
    """The showdown slates to solve, from the archived DK draft groups.

    Returns (slates, status), SOONEST FIRST. Status separates "nothing to solve
    right now", which is the ordinary state midweek before DraftKings posts the
    weekend, from "something is broken". The scheduled job must not fail on the
    former, and must not pass silently on the latter.

    Two things this gets right that solving a single slate did not.

    Upcoming games only. Ranking by entry count alone silently solved a game
    that had already been played, because run on a Monday, Sunday night's
    showdown still carries the most entries in the archive.

    And the biggest upcoming showdown is not the next one. A Sunday posts a
    dozen single-game slates, and on 15 November the largest was Monday night's
    LAC/BAL at 639,260 entries while Sunday night's PIT/CIN at 491,902 locked
    thirteen hours earlier. Picking the largest meant the Sunday game, the one
    actually in front of the player, was never solved. So the `want` largest
    are taken, then ORDERED BY KICKOFF, which puts the game you have to decide
    first at the top without dropping the bigger one later in the week.

    The small slates are deliberately not solved. The same Sunday carried seven
    showdowns between 8,400 and 40,000 entries against two near half a million;
    they are a different product, and solving all twelve would spend the runtime
    on games nobody is entering.
    """
    path = os.path.join(DATA, "nfl_dk.json")
    if not os.path.exists(path):
        log("no data/nfl_dk.json; run tools/fetch_nfl.py first")
        return [], "error"
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    sd = [s for s in doc.get("slates", []) if s.get("kind") == "showdown"]
    if not sd:
        log("no showdown slates in data/nfl_dk.json; nothing to solve")
        return [], "empty"

    if dg:
        hit = [s for s in sd if str(s["dg"]) == str(dg)]
        if not hit:
            log(f"dg {dg} is not a showdown slate in the archive. Available:")
            for s in sorted(sd, key=lambda x: x.get("start") or ""):
                log(f"   dg={s['dg']:<8} {s['entries']:>8,} entries  "
                    f"starts {s.get('start','?')}  {s['name']}")
            return [], "error"
        chosen = hit[:1]
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
        upcoming = [s for s in sd
                    if (_start_of(s) or now) > now and _start_of(s)]
        if not upcoming:
            log("no showdown in the archive has a future start time; every one "
                "of these has already locked. Refresh data/nfl_dk.json, or pass "
                "--dg to solve a past game deliberately:")
            for s in sorted(sd, key=lambda x: x.get("start") or ""):
                log(f"   dg={s['dg']:<8} {s['entries']:>8,} entries  "
                    f"starts {s.get('start','?')}  {s['name']}")
            return [], "empty"
        if len(upcoming) < len(sd):
            log(f"{len(sd) - len(upcoming)} showdown slate(s) ignored as "
                f"already started")
        biggest = sorted(upcoming, key=lambda s: -(s.get("entries") or 0))
        chosen = sorted(biggest[:max(1, want)], key=lambda s: _start_of(s))
        skipped = biggest[max(1, want):]
        if skipped:
            log(f"{len(skipped)} smaller upcoming showdown(s) not solved "
                f"(largest of them {max(x.get('entries') or 0 for x in skipped):,} "
                f"entries); pass --dg to solve one")

    for s in chosen:
        s["_built"] = doc.get("built")
    log(f"solving {len(chosen)} showdown slate(s), soonest first:")
    for s in chosen:
        log(f"   dg={s['dg']:<8} {s['entries']:>8,} entries  "
            f"starts {s.get('start','?')}  {s['name']}")
    return chosen, "ok"


def anchor_counts():
    """How many de-vigged prop markets back each player's projection.

    The ownership models use this to tell a priced-up starter from a backup
    quarterback carrying the showdown minimum: the field does not roster a
    player the book will not price, 23 times out of 23 in the sample behind
    flex_ownership.is_rostered. Keyed by the same normalised name the
    simulation uses. An empty mapping disables the guard rather than excluding
    everyone, which is the safe direction to fail.
    """
    path = os.path.join(DATA, "nfl_projections.json")
    if not os.path.exists(path):
        log("no data/nfl_projections.json; ownership guards are OFF and "
            "backup quarterbacks will collect modelled ownership")
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return {nrm(p["player"]): len(p.get("anchors") or [])
            for p in doc.get("players", [])}


def kicker_markets():
    """Every kicker's de-viggable lines, keyed by normalised name.

    Kickers are not in the joint simulation because no kicker history has ever
    been ingested, so their scores come from their own markets instead. See
    kicker_model.py. Leaving them out entirely was worse: on 19 November the
    slate's kicker was in 100% of the top 1% of entries and this project could
    not see the slot at all.
    """
    path = os.path.join(DATA, "nfl_props.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("props") if isinstance(doc, dict) else doc
    out = defaultdict(lambda: defaultdict(dict))
    for r in rows or []:
        if r.get("pos") == "K" and r.get("stat") in (
                "FG Made", "XP Made", "Kicking Points"):
            out[nrm(r["player"])][r["stat"]][r.get("side", "")] = {
                "line": r.get("line"), "decimal": r.get("decimal")}
    return {k: dict(v) for k, v in out.items()}


def build_pool(slate, sims, anchors=None, kickers=None, trials=None):
    """Join the showdown's priced players onto the correlated simulation.

    The DK rows carry their own team code, so a defence is keyed straight to
    `dst_<TEAM>` rather than matched on DraftKings' nickname for it ("Bears"),
    which never had to be a name-matching problem at all.

    Kickers are joined from their OWN markets rather than from the simulation,
    because no kicker history exists to simulate from. They are therefore
    uncorrelated with everything else in the pool, which is wrong and is
    stated in the log rather than hidden: a kicker's points come from drives
    that stall, so he is positively correlated with his offence getting the
    ball and negatively with it reaching the end zone.
    """
    anchors = {} if anchors is None else anchors
    kickers = {} if kickers is None else kickers
    rng_k = np.random.default_rng(90210)
    teams = sorted({p["tm"] for p in slate["players"] if p["tm"]})
    if len(teams) != 2:
        log(f"expected two teams, found {teams}")
        return None, None
    other = {teams[0]: teams[1], teams[1]: teams[0]}

    pool, missing, n_kick = [], [], 0
    for p in slate["players"]:
        key = f"dst_{p['tm']}" if p["pos"] == "DST" else nrm(p["n"])
        fp = sims.get(key)
        if fp is None and p["pos"] == "K" and trials:
            fp = kick.sample_points(rng_k, kickers.get(key, {}), trials)
            if fp is not None:
                n_kick += 1
        if fp is None:
            missing.append(p)
            continue
        pool.append({
            "key": key, "name": p["n"], "pos": p["pos"], "team": p["tm"],
            "opp": other.get(p["tm"]), "sal": int(p["sal"]), "fp": np.asarray(fp),
            "anchors": anchors.get(key),
        })

    log(f"\npool: {len(pool)} of {len(slate['players'])} priced players have a "
        f"simulated score")
    if n_kick:
        log(f"   {n_kick} of those are kickers priced from their own markets "
            f"({kick.describe()}); they are UNCORRELATED with the rest of the "
            f"pool, which understates both their upside in a field-goal game "
            f"and their downside in a shootout")
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
                why = ("kicker, and the book posts no lines for him, which "
                       "usually means he is not playing" if m["pos"] == "K"
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


def solve_slate(slate, sims, args, anchors=None, kickers=None):
    """Everything for ONE showdown slate. Returns its result dict, or None.

    Separated from main so the joint simulation, which is the expensive part
    and is league-wide rather than slate-specific, is drawn once and reused
    across every slate solved in a run.
    """
    log("\n" + "#" * 76)
    log(f"# {slate['name']}  (dg={slate['dg']}, {slate['entries']:,} entries, "
        f"starts {slate.get('start','?')})")
    log("#" * 76)

    pool, teams = build_pool(slate, sims, anchors, kickers,
                             trials=len(next(iter(sims.values()))) if sims else None)
    if not pool or len(pool) < ROSTER:
        log("not enough projectable players to fill a lineup")
        return None
    team_a = teams[0]
    if not any(p["team"] == teams[1] for p in pool):
        log(f"every projectable player is on {team_a}; "
            f"DraftKings requires both sides")
        return None

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
    flex_wins = Counter()
    own_sums = []
    solved = 0
    illegal = 0

    # Both ownership models depend only on price and position, so they are
    # built once here and are available inside the solve loop. Captain and
    # flex are SEPARATE markets, summing to 100% and 500%: on the five
    # captured contests the ratio between a player's two shares ran from 1.4
    # to 32, so neither can be derived from the other.
    own_in = [{"player": p["name"], "sal": p["sal"], "pos": p["pos"],
               "anchors": p.get("anchors")} for p in pool]
    cpt_own = captain_ownership(own_in)
    flex_own = flex_ownership(own_in)
    skipped = [p for p in pool if not is_rostered(
        {"pos": p["pos"], "anchors": p.get("anchors")})]
    if skipped:
        log(f"\n{len(skipped)} priced player(s) carry no prop markets and are "
            f"treated as unrostered by the field:")
        for p in sorted(skipped, key=lambda q: -q["sal"]):
            log(f"   {p['pos']:4} {p['name']:24} ${p['sal']:<7} {p['team']}")

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
            flex_wins[pool[i]["name"]] += 1
        # What this winning lineup would have cost in field share, in the units
        # FantasyLabs reports and the five scored winners were measured in:
        # the captain's captain-market share plus each flex player's flex
        # share. Those five came in between 149.6% and 175.0%, so a solved
        # winner landing in that band is evidence the simulation is finding
        # the same kind of lineup the contests actually paid.
        own_sums.append(cpt_own.get(c["name"], 0.0)
                        + sum(flex_own.get(pool[i]["name"], 0.0)
                              for i in ids[1:]))
        if solved % 500 == 0:
            log(f"   {solved:,} solved")

    if not solved:
        log("no trial produced a legal lineup")
        return None
    log(f"   {solved:,} games produced a legal winner")
    if illegal:
        log(f"   WARNING: {illegal:,} solved lineups broke a roster rule "
            f"and were discarded; the solver has a bug")

    meta = {p["name"]: p for p in pool}
    # Both ownership models are reported BESIDE the win rates and never
    # divided into them: tested on both measured contests, win rate over
    # modelled captain ownership ranked the actual winning captain 12th of 21
    # and 20th of 23, against 1st and 10th for the raw win rate. The models
    # are monotone in salary, so the ratio is close to win rate per dollar and
    # simply promotes cheap players.
    if own_sums:
        own_sums.sort()
        mid = own_sums[len(own_sums) // 2]
        lo = own_sums[int(0.1 * len(own_sums))]
        hi = own_sums[int(0.9 * len(own_sums))]
        log(f"\nfield share of the solved winners: median {mid:.0f}%, "
            f"10th to 90th percentile {lo:.0f}% to {hi:.0f}%")
        log("   the five scored contests were won at 149.6%, 151.3%, 166.1%, "
            "169.6% and 175.0%")

    log("\n" + "=" * 76)
    log("CAPTAINS — share of simulated games whose best lineup captained him")
    log("=" * 76)
    log(f"   {cpt_own_note()}")
    log(f"{'captain':24}{'pos':5}{'team':6}{'salary':>8}{'cpt cost':>10}"
        f"{'wins%':>8}{'field%':>8}")
    for name, w in cpt_wins.most_common(args.top):
        p = meta[name]
        log(f"{name[:23]:24}{p['pos']:5}{p['team']:6}${p['sal']:>7,}"
            f"${int(round(p['sal']*CPT_MULT)):>9,}{100*w/solved:>7.1f}%"
            f"{cpt_own.get(name, 0):>7.1f}%")
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

    return {
        "slate": {"dg": slate["dg"], "name": slate["name"],
                  "entries": slate.get("entries"), "start": slate.get("start"),
                  "teams": teams},
        "trials": solved,
        "exactSolve": bool(exact),
        "poolSize": n,
        "priced": len(slate["players"]),
        "captains": [
            {"player": nm, "pos": meta[nm]["pos"], "team": meta[nm]["team"],
             "sal": meta[nm]["sal"],
             "cptSal": int(round(meta[nm]["sal"] * CPT_MULT)),
             "wins": w, "pWin": w / solved,
             "cptOwn": round(cpt_own.get(nm, 0.0), 2),
             "flexOwn": round(flex_own.get(nm, 0.0), 2),
             "partners": dict(partners[nm].most_common(5))}
            for nm, w in cpt_wins.most_common()
        ],
        # The flex slot's own version of the captain table: how often a winning
        # lineup carried the player in a NON-captain slot, beside how much of
        # the field is expected to. Five slots, so pFlex is out of five and
        # flexOwn sums to 500% across the pool, not 100%.
        "flex": [
            {"player": p["name"], "pos": p["pos"], "team": p["team"],
             "sal": p["sal"],
             "wins": flex_wins.get(p["name"], 0),
             "pFlex": flex_wins.get(p["name"], 0) / solved,
             "flexOwn": round(flex_own.get(p["name"], 0.0), 2),
             "cptOwn": round(cpt_own.get(p["name"], 0.0), 2)}
            for p in sorted(pool, key=lambda q: -flex_wins.get(q["name"], 0))
        ],
        "ownSum": ({"p10": round(own_sums[int(0.1 * len(own_sums))], 1),
                    "median": round(own_sums[len(own_sums) // 2], 1),
                    "p90": round(own_sums[int(0.9 * len(own_sums))], 1),
                    "scoredWinners": [149.6, 151.3, 166.1, 169.6, 175.0]}
                   if own_sums else None),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--dg", default="", help="solve this showdown draft group "
                                             "only, ignoring the usual choice")
    ap.add_argument("--slates", type=int, default=2,
                    help="how many of the biggest upcoming showdowns to solve; "
                         "they are reported soonest first")
    ap.add_argument("--top", type=int, default=14)
    ap.add_argument("--out", default="nfl_showdown_scenarios.json")
    args = ap.parse_args()

    slates, status = load_slates(args.dg, args.slates)
    if not slates:
        # "empty" is a normal midweek state, so the scheduled job must not go
        # red for it. Only a genuine problem returns non-zero.
        return 0 if status == "empty" else 1
    log(f"draft groups archived {slates[0].get('_built')}")

    # Drawn once for the whole run: the simulation is league-wide, so solving a
    # second showdown costs only its own solve, not another twenty seconds of
    # correlated sampling.
    log(f"\nregenerating the joint simulation at {args.trials:,} trials")
    import build_projections as bp
    sims, _res = bp.player_scores(args.trials, "dk")
    anchors = anchor_counts()
    kickers = kicker_markets()
    log(f"kicker markets found for {len(kickers)} kicker(s)")

    results = []
    for slate in slates:
        r = solve_slate(slate, sims, args, anchors, kickers)
        if r:
            results.append(r)
    if not results:
        log("\nno showdown slate could be solved")
        return 1

    out = {
        "built": datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage": 1,
        # Named so a page cannot render an absent denominator as if it were a
        # measurement. BOTH SLOT MARKETS ARE NOW MODELLED: captain ownership
        # summing to 100% and flex ownership to 500%.
        #
        # hasFieldModel stays FALSE on purpose, and does not mean "no
        # ownership". It means there is no model of whole LINEUPS. Summing the
        # two marginals gives a lineup's field share, which is what the
        # contests report and what ownSum carries, but it does NOT give the
        # probability that anyone built that exact six, because entries are
        # not assembled by drawing six independent players: stacking makes the
        # slots strongly dependent. Duplicate counts and true lineup-level
        # leverage need a model of how entries are constructed, and this is
        # not one.
        "hasFieldModel": False,
        "hasCaptainOwnership": True,
        "hasFlexOwnership": True,
        "captainOwnershipNote": cpt_own_note(),
        "flexOwnershipNote": flex_own_note(),
        # Soonest first, so index 0 is the game that has to be decided next.
        "slates": results,
    }
    path = os.path.join(DATA, args.out)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    log(f"\nwrote {path} ({len(results)} slate(s), soonest first: "
        + ", ".join(r["slate"]["name"] for r in results) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
