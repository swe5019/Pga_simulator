#!/usr/bin/env python3
"""
build_projections.py — market anchored fantasy point projections, as
distributions rather than single numbers. Writes data/nfl_projections.json.

THE DESIGN DECISION THIS RESTS ON
The betting market is the most accurate public forecast of NFL player volume
that exists, and the backtest in backtest_sim.py is what settled it: the
simulation's skill on quarterback passing volume is under 2%, essentially
nothing, because volume is decided by game script and the model has neither the
spread nor the total. Building a projection that ignores the market and then
claiming accuracy would be backwards.

So the props set the location and the play by play sets the shape:

  FROM THE PROPS        the expected value of every stat a line exists for,
                        recovered by de-vigging the price and inverting it
  FROM THE PLAY BY PLAY the distribution around it, the long tail, the
                        correlation between team mates, and every player the
                        market has not posted a line on

A line only becomes an expected value once you assume a shape, which is why
these two halves are not alternatives. A line of 4.5 receptions priced at a
fair 52% over implies a different mean depending on how spread out the player's
receptions are, and that spread comes from his own plays.

WHY DISTRIBUTIONS AND NOT NUMBERS
Point estimate accuracy on fantasy points is mostly a measure of how lucky you
got on touchdowns. A projection of 12.4 is not meaningfully better than 11.9
and nobody can honestly tell them apart. A correctly calibrated 90th percentile
is a different matter: it is checkable, it is what a tournament lineup actually
needs, and being right about it is a defensible claim.

CORRELATION, WHICH IS THE PART NOBODY PUBLISHES
Teammates are not independent. Measured across three seasons of half PPR:

  quarterback and his WR2        +0.37        quarterback and WR1      +0.33
  quarterback and his TE1        +0.30        quarterback and WR3      +0.19
  the two running backs          -0.12        WR1 and WR2              +0.08
  quarterback and the OTHER      +0.16        the two lead backs       -0.08
  quarterback

Those are induced with a Gaussian copula, which reorders each player's own
simulated trials to match the target correlation while leaving his marginal
distribution exactly as it was. So the projection for one player is unchanged
by who he is correlated with, and a stack can be priced honestly.

Opposing team correlations were measured only on the top two at each position.
Including deeper players produced figures like a quarterback at -0.59 against
an opposing third tight end, which is a selection effect from who appears in
what kind of game rather than anything real, and using it would have been
actively harmful.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

from enrich_props import (
    FULL, build_role_context, current_role, game_logs, load_injuries,
    load_pbp, load_seasons, nrm,
)
from simulate_props import (
    MIN_GAMES, PRIOR_GAMES, PRIOR_RATE, draw_counts, fit, flat_pool,
    position_baselines, role_prior, shrink,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

TRIALS = 10_000
SEED = 20261016

# Scoring. Half PPR is the default because it is what most DFS and most home
# leagues use; the other two come off identical trials so they stay consistent
# with each other.
SCORING = {
    "half": {"rec": 0.5, "ry": 0.1, "uy": 0.1, "py": 0.04, "td": 6.0,
             "ptd": 4.0, "int": -2.0, "fl": -2.0},
    "ppr": {"rec": 1.0, "ry": 0.1, "uy": 0.1, "py": 0.04, "td": 6.0,
            "ptd": 4.0, "int": -2.0, "fl": -2.0},
    # DraftKings: full PPR, minus one for an interception rather than two, and
    # a three point bonus at 100 rushing or receiving yards and 300 passing.
    "dk": {"rec": 1.0, "ry": 0.1, "uy": 0.1, "py": 0.04, "td": 6.0,
           "ptd": 4.0, "int": -1.0, "fl": -1.0, "bonus": True},
}

# Measured same team correlations, by position and depth rank. Anything not
# listed falls back to a small shared game effect rather than to zero, because
# every player in a game shares the pace and the weather.
SAME_TEAM = {
    ("QB1", "WR1"): 0.33, ("QB1", "WR2"): 0.37, ("QB1", "WR3"): 0.19,
    ("QB1", "TE1"): 0.30, ("QB1", "TE2"): 0.16, ("QB1", "RB1"): 0.10,
    ("QB1", "RB2"): 0.05, ("QB1", "QB2"): -0.48,
    ("WR1", "WR2"): 0.08, ("WR1", "WR3"): 0.06, ("WR2", "WR3"): 0.06,
    ("WR1", "TE1"): 0.05, ("WR2", "TE1"): 0.05,
    ("RB1", "RB2"): -0.12, ("RB1", "RB3"): -0.12, ("RB2", "RB3"): -0.10,
    ("RB1", "WR1"): 0.03, ("RB1", "TE1"): 0.03,
}
SAME_DEFAULT = 0.04
# Opposing team: a shootout lifts both sides, but weakly. Running backs are
# the exception, since only one team can control the clock.
OPP_PASS = 0.12
OPP_QB_QB = 0.16
OPP_RB_RB = -0.08
OPP_DEFAULT = 0.06


def log(*a):
    print(*a, flush=True)


def pos_rank(pos, rank):
    return f"{pos}{min(rank, 3)}"


def pair_corr(a, b, same_team):
    """Target correlation between two players in the same game."""
    ka, kb = a, b
    if same_team:
        key = (ka, kb) if (ka, kb) in SAME_TEAM else (kb, ka)
        return SAME_TEAM.get(key, SAME_DEFAULT)
    if ka.startswith("QB") and kb.startswith("QB"):
        return OPP_QB_QB
    if ka.startswith("RB") and kb.startswith("RB"):
        return OPP_RB_RB
    if ka.startswith("QB") or kb.startswith("QB"):
        return OPP_PASS
    return OPP_DEFAULT


# --------------------------------------------------------------------------
# One player, one complete stat line per trial
# --------------------------------------------------------------------------
# ANCHORING HAS TO BE SEQUENTIAL, and getting this wrong is the single easiest
# way to produce nonsense that still looks like a projection. The first version
# solved every scale against the same unanchored sample and then applied them
# all at once, so a back whose carries were scaled 3.3x and whose rushing yards
# were ALSO scaled 3.0x came out at 305 rushing yards against a line of 69.5.
# A yardage line already includes the volume, so its scale has to be solved
# AFTER the volume is anchored, against what the volume anchoring produced.
#
# The order is therefore: how many plays, then how often they convert, then how
# far each one goes, then how often they score. Each stage is solved against
# the distribution the previous stages actually generated.


def solve_rate(rng, volume, line, q, lo=0.0, hi=1.0):
    """The per-opportunity rate the market implies, given the volume already
    anchored. Redrawn at each step rather than rescaled, for the same reason a
    count cannot be rescaled."""
    if line is None or q is None or not (0.02 < q < 0.98):
        return None
    if volume.max() <= 0:
        return None

    def tail(rate):
        return float((rng.binomial(volume, min(max(rate, 0.0), 1.0))
                      > line).mean())

    if tail(hi) < q:
        return None
    for _ in range(26):
        mid = 0.5 * (lo + hi)
        if tail(mid) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def solve_scale(sample, line, q, lo=0.2, hi=5.0):
    """The multiplier that makes a CONTINUOUS total agree with the market.

    Valid for yardage only. Scaling moves a yardage total's location while
    keeping its shape, and P(k*X > L) is P(X > L/k), which a sorted sample
    answers instantly, so this is a bisection costing nothing. Returns None
    when no rescaling of this shape can reach the market's probability, which
    means the line says nothing usable about the mean."""
    if sample.size == 0 or line is None or q is None:
        return None
    if not (0.02 < q < 0.98):
        return None
    srt = np.sort(sample)
    n = srt.size

    def over(k):
        return float(n - np.searchsorted(srt, line / k, side="right")) / n

    if over(lo) > q or over(hi) < q:
        return None
    for _ in range(40):
        mid = math.sqrt(lo * hi)
        if over(mid) < q:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def player_lines(rng, f, base, prior, market, eff_cap=None):
    """TRIALS complete stat lines, anchored to the market in stages.

    Shared draws are the whole point. Fantasy points need a player's
    receptions and his receiving yards to come from the SAME simulated game,
    so the yards are the sum of that trial's catches. Sampling each stat
    independently, which is what the props page does because it only ever
    answers one question at a time, would hand a player four receptions in one
    column and ninety yards in another with nothing tying them together."""
    eff = f["effGames"]
    if eff_cap is not None:
        eff = min(eff, eff_cap)
    used = []

    def model_vol(kind):
        own_m, own_v = f[kind]
        pm, pv = prior.get(kind, (own_m, own_v))
        m = shrink(own_m, eff, pm, PRIOR_GAMES)
        v = max(shrink(own_v, eff, pv, PRIOR_GAMES), m)
        return m, v

    def model_rate(kind):
        num, den = f[kind]
        own = (num / den) if den > 0 else None
        return shrink(own, den * eff if den else 0.0,
                      base.get(kind, 0.0), PRIOR_RATE)

    def prop(stat):
        p = market.get(stat)
        if not p or p.get("fairBE") is None:
            return None, None
        return p["line"], p["fairBE"] / 100.0

    # ---- stage one: how many plays
    def volume(kind, stat):
        """Solved against the DRAW PATH, not against a formula.

        Solving the mean analytically and then drawing was wrong in two ways
        that cancelled nothing: the participation factor multiplies the mean
        per trial afterwards, pulling the realised mean below the solved one,
        and rescaling the variance changes the shape the analytic solution
        assumed. Both showed up as the same signature, every role-change
        backup landing 20 to 45 points under the market on volume, all in the
        same direction. Bisecting on what is actually drawn cannot drift from
        what is actually drawn."""
        m, v = model_vol(kind)
        line, q = prop(stat)

        def draw(k):
            mm = m * k
            vv = max(v * k * k, mm)
            return draw_counts(rng, mm, vv, TRIALS, f.get("_parts"))

        if line is None or m <= 0:
            return draw(1.0), m
        lo, hi = 0.05, 10.0
        if float((draw(hi) > line).mean()) < q:
            return draw(1.0), m
        if float((draw(lo) > line).mean()) > q:
            return draw(1.0), m
        for _ in range(24):
            mid = math.sqrt(lo * hi)
            if float((draw(mid) > line).mean()) < q:
                lo = mid
            else:
                hi = mid
        k = math.sqrt(lo * hi)
        used.append({"stat": stat, "line": line, "fair": round(q * 100, 1),
                     "was": round(m, 2), "now": round(m * k, 2)})
        return draw(k), m * k

    tgt, tgt_m = volume("tgt", "Targets")
    car, car_m = volume("car", "Rush Attempts")
    patt, patt_m = volume("patt", "Pass Attempts")

    # ---- stage two: how often they convert, on the anchored volume
    def converted(volume_arr, num_kind, den_kind, stat, fallback):
        own = (f[num_kind][0] / f[den_kind][0]) if f[den_kind][0] > 0 else None
        pn = prior.get(num_kind, (0, 0))[0]
        pd = prior.get(den_kind, (0, 0))[0]
        pri = (pn / pd) if pd > 0 else fallback
        rate = shrink(own, f[den_kind][0] * eff, pri, PRIOR_RATE)
        rate = min(max(rate, 0.0), 1.0)
        line, q = prop(stat)
        if line is not None:
            got = solve_rate(rng, volume_arr, line, q)
            if got is not None:
                used.append({"stat": stat, "line": line,
                             "fair": round(q * 100, 1),
                             "was": round(rate, 3), "now": round(got, 3)})
                rate = got
        return rng.binomial(volume_arr, rate)

    rec = converted(tgt, "rec", "tgt", "Receptions", 0.62)
    cmp_ = converted(patt, "cmp", "patt", "Completions", 0.64)

    # ---- stage three: how far each play goes, on the anchored counts
    out = {"tgt": tgt, "rec": rec, "car": car, "patt": patt, "cmp": cmp_}

    def yards(count, kind, stat, want_longest=False):
        pool = flat_pool(rng, f, kind, base)
        if pool is None or count.max() <= 0:
            out[kind] = np.zeros(TRIALS)
            if want_longest:
                out["lrec"] = np.zeros(TRIALS)
            return
        k = int(count.max())
        idx = rng.integers(0, len(pool), size=(TRIALS, k))
        draws = pool[idx]
        mask = np.arange(k)[None, :] < count[:, None]
        total = (draws * mask).sum(axis=1)
        line, q = prop(stat)
        scale = 1.0
        if line is not None:
            got = solve_scale(total, line, q)
            if got is not None:
                used.append({"stat": stat, "line": line,
                             "fair": round(q * 100, 1),
                             "was": round(float(total.mean()), 1),
                             "now": round(float(total.mean()) * got, 1)})
                scale = got
        draws = draws * scale
        out[kind] = (draws * mask).sum(axis=1)
        if want_longest:
            lng = np.where(mask, draws, -np.inf).max(axis=1)
            out["lrec"] = np.where(np.isfinite(lng), lng, 0.0).clip(min=0.0)

    yards(rec, "ry", "Receiving Yards", want_longest=True)
    yards(car, "uy", "Rush Yards")
    yards(cmp_, "py", "Pass Yards")

    # ---- stage four: how often they score, on the anchored volumes
    def scored(volume_arr, kind, stat):
        rate = min(max(model_rate(kind), 0.0), 1.0)
        line, q = prop(stat)
        if line is not None:
            got = solve_rate(rng, volume_arr, line, q)
            if got is not None:
                used.append({"stat": stat, "line": line,
                             "fair": round(q * 100, 1),
                             "was": round(rate, 4), "now": round(got, 4)})
                rate = got
        return rng.binomial(volume_arr, rate)

    # An anytime touchdown line covers rushing and receiving together, so it
    # cannot anchor either rate on its own. It is solved against the combined
    # count and the shortfall is shared between the two in proportion to the
    # scoring each volume already implies.
    out["rtd"] = rng.binomial(rec, min(max(model_rate("rtd"), 0.0), 1.0))
    out["utd"] = rng.binomial(car, min(max(model_rate("utd"), 0.0), 1.0))
    line, q = prop("Anytime TD")
    if line is not None:
        base_rt = min(max(model_rate("rtd"), 0.0), 1.0)
        base_ut = min(max(model_rate("utd"), 0.0), 1.0)

        def tail(k):
            return float(((rng.binomial(rec, min(base_rt * k, 1.0))
                           + rng.binomial(car, min(base_ut * k, 1.0)))
                          > line).mean())

        lo, hi = 0.0, 12.0
        if tail(hi) >= q:
            for _ in range(24):
                mid = 0.5 * (lo + hi)
                if tail(mid) < q:
                    lo = mid
                else:
                    hi = mid
            k = 0.5 * (lo + hi)
            used.append({"stat": "Anytime TD", "line": line,
                         "fair": round(q * 100, 1),
                         "was": round(base_rt + base_ut, 4),
                         "now": round((base_rt + base_ut) * k, 4)})
            out["rtd"] = rng.binomial(rec, min(base_rt * k, 1.0))
            out["utd"] = rng.binomial(car, min(base_ut * k, 1.0))

    out["ptd"] = scored(cmp_, "ptd", "Pass TDs")
    out["int"] = scored(patt, "int", "INTs Thrown")
    return out, used


def fantasy(lines, system):
    s = SCORING[system]
    td = lines["rtd"] + lines["utd"]
    fp = (s["rec"] * lines["rec"] + s["ry"] * lines["ry"] + s["uy"] * lines["uy"]
          + s["py"] * lines["py"] + s["td"] * td + s["ptd"] * lines["ptd"]
          + s["int"] * lines["int"])
    if s.get("bonus"):
        fp = fp + 3.0 * (lines["ry"] >= 100) + 3.0 * (lines["uy"] >= 100) \
             + 3.0 * (lines["py"] >= 300)
    return fp


def main():
    seasons, current = load_seasons()
    pbp = load_pbp(sorted(seasons, reverse=True))
    if not pbp:
        log("no play by play on disk; run fetch_nfl_pbp.py first")
        return 1
    logs = game_logs(seasons, pbp)

    meta_pos, meta_team = {}, {}
    for yr in sorted(seasons, reverse=True):
        for pl in seasons[yr]["players"]:
            meta_pos.setdefault(nrm(pl["n"]), pl["p"])
            meta_team.setdefault(nrm(pl["n"]), pl["t"])

    injuries = load_injuries()
    role_ctx = build_role_context(logs, seasons, current, injuries,
                                  meta_pos, meta_team)

    ppath = os.path.join(DATA, "nfl_props_full.json")
    props_by_player = defaultdict(list)
    fixtures = {}
    if os.path.exists(ppath):
        with open(ppath, encoding="utf-8") as f:
            pdoc = json.load(f)
        for p in pdoc["props"]:
            props_by_player[nrm(p["player"])].append(p)
            if p.get("team") and p.get("opp"):
                fixtures[p["team"]] = p["opp"]
        log(f"{len(props_by_player):,} players carry props, "
            f"{len(fixtures)} teams in this slate")
    else:
        log("no nfl_props_full.json; projections will be model only")

    years = [y for y in (current, current - 1, current - 2) if y in seasons]
    bases = position_baselines(logs, meta_pos, seasons, FULL)
    rng = np.random.default_rng(SEED)

    # Season usage decides depth rank, which is what the correlation matrix is
    # keyed on. Taken from this season only, so last year's depth chart does
    # not describe this week's.
    usage = defaultdict(list)
    for key, byyear in logs.items():
        rows = byyear.get(current, [])
        tot = sum((r.get("tg", 0) + r.get("ca", 0) + r.get("att", 0))
                  for r in rows)
        if meta_team.get(key) and meta_pos.get(key):
            usage[(meta_team[key], meta_pos[key])].append((tot, key))
    depth = {}
    for (team, pos), lst in usage.items():
        for i, (_, key) in enumerate(sorted(lst, reverse=True)):
            depth[key] = i + 1

    built = []
    skipped = defaultdict(int)
    for key, byyear in logs.items():
        pos, team = meta_pos.get(key), meta_team.get(key)
        if not pos or not team or team not in fixtures:
            skipped["not in this slate"] += 1
            continue
        ctx = role_ctx.get(key)
        if ctx and ctx.get("selfOut"):
            skipped["on the injury report himself"] += 1
            continue
        role_now = (ctx["role"] if ctx and ctx.get("role") is not None
                    else current_role(byyear, current))
        hist = [r for y in years for r in byyear.get(y, [])]
        f = fit(hist, FULL, role_now)
        if f is None:
            skipped["no play by play history"] += 1
            continue
        prior = role_prior(bases.get(pos, {}), role_now)
        eff_cap = None
        if ctx and ctx.get("role") is not None and ctx.get("thin"):
            eff_cap = float(max(ctx["ctxN"], 1))

        market = {p["stat"]: p for p in props_by_player.get(key, [])
                  if p["side"] == "over"}
        lines, used = player_lines(rng, f, bases.get(pos, {}), prior,
                                   market, eff_cap)
        entry = {
            "key": key, "pos": pos, "team": team, "opp": fixtures[team],
            "rank": depth.get(key, 9),
            "effGames": round(f["effGames"], 1),
            "thin": (f["effGames"] < MIN_GAMES) or (eff_cap is not None),
            "anchors": used,
            "lines": lines,
        }
        if ctx:
            if ctx.get("role") is not None:
                entry["outAhead"] = ctx["outAhead"]
                entry["outBasis"] = ctx["outBasis"]
                entry["roleCtx"] = ctx["roleCtx"]
                entry["roleCtxN"] = ctx["ctxN"]
            elif ctx.get("unknown"):
                entry["outAhead"] = ctx["outAhead"]
                entry["outBasis"] = ctx["outBasis"]
                entry["roleUnknown"] = True
        built.append(entry)

    log(f"\n{len(built):,} players simulated")
    for k, v in sorted(skipped.items(), key=lambda kv: -kv[1]):
        log(f"   skipped {v:,}: {k}")
    anchored = sum(1 for e in built if e["anchors"])
    log(f"{anchored:,} of them anchored to at least one prop "
        f"({sum(len(e['anchors']) for e in built):,} anchors in total)")

    # ---- correlation, applied game by game
    by_game = defaultdict(list)
    for e in built:
        by_game[tuple(sorted((e["team"], e["opp"])))].append(e)
    log(f"\ninducing correlation across {len(by_game)} games")
    for gkey, players in by_game.items():
        apply_copula(rng, players)

    # Did it work. A copula that silently failed would leave every projection
    # correct on its own and every stack priced as though teammates were
    # strangers, which is exactly the error this whole layer exists to avoid,
    # and nothing else in the pipeline would notice.
    achieved = defaultdict(list)
    for players in by_game.values():
        for i in range(len(players)):
            for j in range(i + 1, len(players)):
                a, b = players[i], players[j]
                ka = pos_rank(a["pos"], a["rank"])
                kb = pos_rank(b["pos"], b["rank"])
                if a["rank"] > 3 or b["rank"] > 3:
                    continue
                same = a["team"] == b["team"]
                fa, fb = fantasy(a["lines"], "half"), fantasy(b["lines"], "half")
                if fa.std() < 1e-9 or fb.std() < 1e-9:
                    continue
                got = float(np.corrcoef(fa, fb)[0, 1])
                label = (f"{ka}/{kb}" if same else f"{ka}/opp {kb}")
                achieved[(label, pair_corr(ka, kb, same))].append(got)
    log("\nachieved correlation against target, half PPR:")
    log("%-18s %7s %8s %8s %8s" % ("pair", "n", "target", "achieved", "off by"))
    # The pairs a stack is actually built on come first, then whatever else
    # has enough samples. Sorting purely by frequency buried them under
    # third tight ends.
    KEY_PAIRS = ("QB1/WR1", "QB1/WR2", "QB1/TE1", "QB1/RB1", "WR1/WR2",
                 "RB1/RB2", "QB1/opp QB1", "WR1/opp WR1", "RB1/opp RB1")
    rows = [kv for kv in achieved.items() if kv[0][0] in KEY_PAIRS]
    rows.sort(key=lambda kv: KEY_PAIRS.index(kv[0][0]))
    worst = 0.0
    for (label, target), vals in rows:
        got = sum(vals) / len(vals)
        worst = max(worst, abs(got - target))
        log("%-18s %7d %+8.2f %+8.2f %+8.2f"
            % (label, len(vals), target, got, got - target))
    log(f"   worst miss among those: {worst:.2f}")

    # ---- stacks, computed while the joint sample still exists
    #
    # This is the one thing a projection sheet cannot give you after the fact.
    # Two players' medians tell you nothing about how often they go off in the
    # same game, and that is the entire question a tournament lineup asks. It
    # is measured here rather than inferred from a correlation, because what
    # matters is the joint upside and not the average co-movement.
    stacks = []
    disp = {}
    for yr in sorted(seasons, reverse=True):
        for pl in seasons[yr]["players"]:
            disp.setdefault(nrm(pl["n"]), pl["n"])
    for players in by_game.values():
        qbs = [p for p in players if p["pos"] == "QB" and p["rank"] == 1]
        for qb in qbs:
            fq = fantasy(qb["lines"], "half")
            hi_q = np.percentile(fq, 70)
            mates = [p for p in players
                     if p["team"] == qb["team"] and p["pos"] in ("WR", "TE", "RB")
                     and p["rank"] <= 3]
            # The bring back: an opposing pass catcher, which is the other half
            # of how these lineups are built.
            backs = [p for p in players
                     if p["team"] != qb["team"] and p["pos"] in ("WR", "TE")
                     and p["rank"] <= 2]
            for mate in sorted(mates + backs,
                               key=lambda p: -float(fantasy(p["lines"], "half").mean()))[:6]:
                fm = fantasy(mate["lines"], "half")
                hi_m = np.percentile(fm, 70)
                both = float(((fq >= hi_q) & (fm >= hi_m)).mean())
                # 0.09 is what independence would give, since each side is a
                # 30% event. Anything above it is the stack earning its place.
                stacks.append({
                    "qb": disp.get(qb["key"], qb["key"]),
                    "qbTeam": qb["team"],
                    "mate": disp.get(mate["key"], mate["key"]),
                    "matePos": mate["pos"],
                    "mateTeam": mate["team"],
                    "same": mate["team"] == qb["team"],
                    "corr": round(float(np.corrcoef(fq, fm)[0, 1]), 3),
                    "both": round(both, 3),
                    "lift": round(both / 0.09, 2),
                })
    log(f"\n{len(stacks):,} stack pairings priced")

    # ---- summarise
    name_of = {}
    for yr in sorted(seasons, reverse=True):
        for pl in seasons[yr]["players"]:
            name_of.setdefault(nrm(pl["n"]), pl["n"])
    out = []
    for e in built:
        rec = {
            "player": name_of.get(e["key"], e["key"]),
            "pos": e["pos"], "team": e["team"], "opp": e["opp"],
            "rank": e["rank"], "effGames": e["effGames"], "thin": e["thin"],
            "anchors": e["anchors"],
        }
        for k in ("outAhead", "outBasis", "roleCtx", "roleCtxN",
                  "roleUnknown"):
            if k in e:
                rec[k] = e[k]
        L = e["lines"]
        # DID THE ANCHORING ACTUALLY TAKE. The market said this stat clears
        # its line with probability q; the finished simulation has to agree.
        # Comparing the projected MEAN against the line looks like the obvious
        # check and is wrong: on a line of 4.5 receiving yards the median sits
        # at the line by construction while the mean sits far above it, because
        # the distribution is all zeros and occasional long gains. So the
        # probability is what gets checked, which is the thing that was
        # actually solved for.
        ANCHOR_ARRAY = {
            "Receiving Yards": "ry", "Rush Yards": "uy", "Pass Yards": "py",
            "Receptions": "rec", "Targets": "tgt", "Rush Attempts": "car",
            "Pass Attempts": "patt", "Completions": "cmp",
            "Pass TDs": "ptd", "INTs Thrown": "int",
            "Longest Reception": "lrec",
        }
        for a in e["anchors"]:
            arr = None
            if a["stat"] == "Anytime TD":
                arr = L["rtd"] + L["utd"]
            else:
                k = ANCHOR_ARRAY.get(a["stat"])
                arr = L.get(k) if k else None
            if arr is not None and a.get("line") is not None:
                a["got"] = round(float((arr > a["line"]).mean()) * 100, 1)
        for system in SCORING:
            fp = fantasy(L, system)
            q = np.percentile(fp, [10, 25, 50, 75, 90])
            rec[system] = {
                "mean": round(float(fp.mean()), 2),
                "p10": round(float(q[0]), 1), "p25": round(float(q[1]), 1),
                "med": round(float(q[2]), 1), "p75": round(float(q[3]), 1),
                "p90": round(float(q[4]), 1),
                "sd": round(float(fp.std()), 2),
                "p20": round(float((fp >= 20).mean()), 3),
            }
        rec["stats"] = {k: round(float(L[k].mean()), 2) for k in
                        ("tgt", "rec", "ry", "car", "uy", "patt", "cmp", "py",
                         "rtd", "utd", "ptd", "int")}
        rec["stats"]["lrec"] = round(float(L["lrec"].mean()), 1)
        out.append(rec)

    out.sort(key=lambda r: -r["half"]["mean"])
    payload = {
        "built": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": current,
        "trials": TRIALS,
        "count": len(out),
        "anchoredPlayers": anchored,
        "players": out,
        "stacks": stacks,
    }
    path = os.path.join(DATA, "nfl_projections.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    log(f"\nwrote nfl_projections.json ({os.path.getsize(path) // 1024} KB)")

    miss = [abs(a["got"] - a["fair"]) for r in out for a in r["anchors"]
            if a.get("got") is not None]
    if miss:
        miss.sort()
        n = len(miss)
        log(f"\nanchor fidelity: {n:,} anchors, the simulation's own "
            f"probability against the market's")
        log(f"   median miss {miss[n // 2]:.1f} points, "
            f"p90 {miss[int(0.9 * n)]:.1f}, worst {miss[-1]:.1f}")
        bad = [(a["got"] - a["fair"], a["stat"], r["player"], a["line"])
               for r in out for a in r["anchors"]
               if a.get("got") is not None and abs(a["got"] - a["fair"]) > 8]
        if bad:
            bad.sort(key=lambda x: -abs(x[0]))
            log(f"   {len(bad)} anchors off by more than 8 points:")
            for d, stat, who, line in bad[:8]:
                log(f"      {stat:<18} {who[:22]:<22} line {line:<6} "
                    f"off {d:+.1f}")

    best = sorted(stacks, key=lambda s2: -s2["lift"])[:8]
    if best:
        log("\nstacks where both sides go off together most often")
        log("   (0.09 is what independence would give; higher is the stack working)")
        for s2 in best:
            log("   %-20s + %-20s %-4s corr %+.2f  both %.3f  lift %.2fx%s"
                % (s2["qb"][:20], s2["mate"][:20], s2["matePos"],
                   s2["corr"], s2["both"], s2["lift"],
                   "" if s2["same"] else "  (bring back)"))

    log("\ntop 15 by half PPR median:")
    log("%-24s %-4s %-4s %6s %6s %6s %6s  %s"
        % ("player", "pos", "opp", "p25", "med", "p75", "p90", "anchors"))
    for r in out[:15]:
        h = r["half"]
        log("%-24s %-4s %-4s %6.1f %6.1f %6.1f %6.1f  %d"
            % (r["player"][:24], r["pos"], r["opp"], h["p25"], h["med"],
               h["p75"], h["p90"], len(r["anchors"])))
    return 0


def apply_copula(rng, players):
    """Reorder each player's trials so teammates move together.

    A Gaussian copula: draw correlated normals, rank them, and permute each
    player's own trials into that rank order. His marginal distribution is
    untouched, every trial remains a complete and internally consistent stat
    line, and the joint behaviour becomes what was measured. That is why this
    cannot distort a projection: it only decides which of his own simulated
    games lands in the same trial as which of his team mate's."""
    n = len(players)
    if n < 2:
        return
    keys = [pos_rank(p["pos"], p["rank"]) for p in players]
    C = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            same = players[i]["team"] == players[j]["team"]
            c = pair_corr(keys[i], keys[j], same)
            C[i, j] = C[j, i] = c
    # A matrix built from pairwise rules need not be positive definite, and
    # drawing from one that is not fails outright. Clipping the eigenvalues is
    # the standard repair and moves the targets only slightly.
    w, V = np.linalg.eigh(C)
    if w.min() < 1e-6:
        w = np.clip(w, 1e-6, None)
        C = V @ np.diag(w) @ V.T
        d = np.sqrt(np.diag(C))
        C = C / np.outer(d, d)
    try:
        Lc = np.linalg.cholesky(C)
    except np.linalg.LinAlgError:
        return
    T = len(players[0]["lines"]["rec"])
    Z = (rng.standard_normal((T, n)) @ Lc.T)
    for j, p in enumerate(players):
        order = np.argsort(np.argsort(Z[:, j]))
        fp = fantasy(p["lines"], "half")
        src = np.argsort(fp)          # his own trials, worst to best
        perm = src[order]
        for k, v in p["lines"].items():
            p["lines"][k] = v[perm]


if __name__ == "__main__":
    sys.exit(main())
