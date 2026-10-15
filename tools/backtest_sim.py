#!/usr/bin/env python3
"""
backtest_sim.py — is the simulation's probability actually worth the name?

WHY THIS HAS TO EXIST
A hit rate cannot really be wrong. It is a count of what happened, and a reader
can check it by hand. A simulated probability is a claim about the future, and
it is perfectly possible to build one that looks authoritative, sits beside a
market price, and is systematically miles off. Published next to a break-even
number, that is worse than showing nothing, because it invites a bet.

So the model is run forward through seasons it was not fitted on, and its
probabilities are compared with what actually happened.

HOW IT WORKS
Strictly walk forward. For each player-week in the test seasons, the model is
fitted on that player's games BEFORE that week only, and the position priors
come only from seasons before the test season. Nothing from the week being
predicted, or after it, is in scope. Then a grid of thresholds around the
simulated median stands in for the lines a book would have offered, and for
each one the predicted probability is recorded against whether it actually
cleared.

WHAT IS MEASURED
  RELIABILITY  bucket by predicted probability, then compare with how often it
               really happened. This is the test that matters: if everything
               the model calls 70% comes in 55% of the time, the edge column is
               a liability.
  BRIER        mean squared error of the probabilities, against the base rate
               as a baseline. Lower is better; worse than the base rate means
               the model is adding noise.
  PIT          where the actual outcome fell in the predicted distribution.
               Flat is right. Piled up at the ends means the distribution is
               too narrow, which is the classic way a simulation lies: the
               means look fine and the tails are far too thin, so the longest
               and anytime markets are badly priced while the yardage ones
               look healthy.

WHAT IS NOT COVERED
The matchup multipliers are not applied, because reconstructing what they would
have said in week 7 of 2025 means rebuilding them from only the games before
it, which this does not do. So this tests the player model, which is the part
carrying nearly all of the weight, and not the defensive adjustment.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

from enrich_props import (
    FULL, H1, Q1, current_role, game_logs, load_pbp, load_seasons, nrm,
)
from simulate_props import (
    LONGEST, YARDS, COUNT, fit, game_values, position_baselines, role_prior,
    simulate,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Fewer draws than the live run: this is many thousands of simulations rather
# than one, and the aggregate does not need per-line precision.
TRIALS = 4_000
# A player needs this much comparable history before his week is predicted at
# all, matching the point at which the live page stops flagging a row as thin.
MIN_EFF = 4.0
# Fail if any reliability bucket is off by this much. Set from what has been
# achieved rather than from what sounds tolerable: the over-confident version
# of this model sat at 3.9 points and the corrected one at 0.8, so three points
# is comfortably clear of the noise and would have caught the bug.
MAX_GAP = 0.03

# Which markets are worth testing for which position. Without this the test
# fills up with "will this receiver throw for 200 yards", which every model
# gets right and which flatters the reliability curve into meaninglessness.
BY_POS = {
    "QB": ("Pass Yards", "Completions", "Pass Attempts", "Pass TDs",
           "Longest Completion", "Rush Yards", "Anytime TD"),
    "RB": ("Rush Yards", "Rush Attempts", "Longest Rush", "Receptions",
           "Receiving Yards", "Targets", "Longest Reception", "Anytime TD"),
    "WR": ("Receptions", "Receiving Yards", "Targets", "Longest Reception",
           "Anytime TD"),
    "TE": ("Receptions", "Receiving Yards", "Targets", "Longest Reception",
           "Anytime TD"),
}

# Market -> how to read the realised value out of one game's buckets.
ACTUAL = {
    "Receptions":       lambda g: g["rec"],
    "Targets":          lambda g: g["tgt"],
    "Rush Attempts":    lambda g: g["car"],
    "Completions":      lambda g: g["cmp"],
    "Pass Attempts":    lambda g: g["patt"],
    "Receiving Yards":  lambda g: sum(g["_ry"]),
    "Rush Yards":       lambda g: sum(g["_uy"]),
    "Pass Yards":       lambda g: sum(g["_py"]),
    "Longest Reception": lambda g: max(g["_ry"]) if g["_ry"] else 0,
    "Longest Rush":     lambda g: max(g["_uy"]) if g["_uy"] else 0,
    "Longest Completion": lambda g: max(g["_py"]) if g["_py"] else 0,
    "Anytime TD":       lambda g: g["rtd"] + g["utd"],
    "Pass TDs":         lambda g: g["ptd"],
}

# Thresholds are placed around the simulated median, as half-integers, which is
# how the lines a book posts are actually shaped.
OFFSETS = {
    "count": (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5),
    "yards": (-25.5, -15.5, -5.5, 4.5, 14.5, 24.5),
    "td": (0.5, 1.5),
}


def log(*a):
    print(*a, flush=True)


def kind_of(stat):
    if stat in ("Anytime TD", "Pass TDs"):
        return "td"
    if "Yards" in stat or stat.startswith("Longest"):
        return "yards"
    return "count"


def main():
    seasons, current = load_seasons()
    pbp = load_pbp(sorted(seasons, reverse=True))
    if not pbp:
        log("no play by play on disk; nothing to backtest")
        return 1
    logs = game_logs(seasons, pbp)

    meta = {}
    for yr in sorted(seasons, reverse=True):
        for p in seasons[yr]["players"]:
            meta.setdefault(nrm(p["n"]), p["p"])

    years = sorted(seasons)
    test_years = [y for y in years if any(x < y for x in years)]
    if not test_years:
        log("need at least two seasons on disk to walk forward")
        return 1
    log(f"seasons on disk {years}; testing {test_years}, "
        f"each fitted only on what came before it")

    rng = np.random.default_rng(7)
    records = []          # (stat, predicted P(over), did it clear)
    pit = defaultdict(list)
    skipped = defaultdict(int)

    for test_year in test_years:
        # Position priors from earlier seasons only, so nothing from the season
        # under test informs its own predictions.
        past = {y: seasons[y] for y in years if y < test_year}
        past_logs = game_logs(past, {y: pbp[y] for y in past if y in pbp})
        base_all = position_baselines(past_logs, meta, past, FULL)
        log(f"\n{test_year}: priors from {sorted(past)}")

        weeks = sorted({r["w"] for rows in logs.values()
                        for r in rows.get(test_year, [])})
        for wk in weeks:
            for key, byyear in logs.items():
                pos = meta.get(key)
                if not pos or pos not in base_all:
                    continue
                this = [r for r in byyear.get(test_year, []) if r["w"] == wk]
                if not this:
                    continue
                actual_g = game_values(this[0], FULL)
                if actual_g is None:
                    continue

                # Everything before this week, and nothing else.
                hist = [r for y in years if y < test_year
                        for r in byyear.get(y, [])]
                hist += [r for r in byyear.get(test_year, []) if r["w"] < wk]
                if not hist:
                    skipped["no prior games"] += 1
                    continue

                role_now = current_role({test_year: sorted(
                    [r for r in byyear.get(test_year, []) if r["w"] < wk],
                    key=lambda r: -r["w"])}, test_year)
                f = fit(hist, FULL, role_now)
                if f is None or f["effGames"] < MIN_EFF:
                    skipped["too little comparable history"] += 1
                    continue
                prior = role_prior(base_all[pos], role_now)

                for stat in BY_POS.get(pos, ()):
                    read = ACTUAL[stat]
                    sample = simulate(rng, stat, None, f,
                                      base_all[pos], 1.0, prior)
                    if sample is None:
                        continue
                    # A market nobody would post on this player at all.
                    if float(sample.mean()) <= 0.4:
                        continue
                    a = read(actual_g)
                    med = float(np.median(sample))
                    k = kind_of(stat)
                    for off in OFFSETS[k]:
                        line = (math.floor(med) + 0.5 + off if k != "td"
                                else off)
                        if line <= 0:
                            continue
                        p_over = float((sample > line).mean())
                        # Nothing is learned from a threshold the model treats
                        # as settled, and they would swamp the buckets.
                        if p_over < 0.02 or p_over > 0.98:
                            continue
                        records.append((stat, p_over, 1 if a > line else 0))
                    pit[stat].append(float((sample < a).mean()
                                           + 0.5 * (sample == a).mean()))

    if not records:
        log("\nnothing was predicted; check that the seasons overlap")
        return 1

    log(f"\n{len(records):,} threshold predictions over "
        f"{sum(len(v) for v in pit.values()):,} player-weeks")
    for k, v in sorted(skipped.items(), key=lambda kv: -kv[1]):
        log(f"   skipped {v:,}: {k}")

    # ---- reliability
    log("\nRELIABILITY — does a 70% call come in 70% of the time?")
    log(f"{'predicted':>14}  {'n':>7}  {'said':>7}  {'happened':>9}  {'gap':>7}")
    edges = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    worst = 0.0
    for lo, hi in zip(edges, edges[1:]):
        sel = [r for r in records if lo <= r[1] < hi]
        if len(sel) < 30:
            continue
        said = sum(r[1] for r in sel) / len(sel)
        happened = sum(r[2] for r in sel) / len(sel)
        worst = max(worst, abs(said - happened))
        log(f"{lo:>6.0%}-{hi:<6.0%}  {len(sel):>7,}  {said:>6.1%}  "
            f"{happened:>8.1%}  {happened - said:>+6.1%}")

    # ---- Brier, against the base rate
    n = len(records)
    brier = sum((r[1] - r[2]) ** 2 for r in records) / n
    rate = sum(r[2] for r in records) / n
    base = sum((rate - r[2]) ** 2 for r in records) / n
    log(f"\nBRIER  model {brier:.4f}   always-say-the-base-rate {base:.4f}   "
        f"skill {100 * (1 - brier / base):+.1f}%")
    log(f"   (skill above zero means the probabilities carry real information; "
        f"below zero means they are worse than a constant)")

    # ---- per market
    log("\nBY MARKET")
    log(f"{'market':>20}  {'n':>7}  {'said':>7}  {'happened':>9}  {'brier':>7}  "
        f"{'skill':>7}")
    for stat in sorted({r[0] for r in records}):
        sel = [r for r in records if r[0] == stat]
        if len(sel) < 100:
            continue
        said = sum(r[1] for r in sel) / len(sel)
        hap = sum(r[2] for r in sel) / len(sel)
        b = sum((r[1] - r[2]) ** 2 for r in sel) / len(sel)
        bb = sum((hap - r[2]) ** 2 for r in sel) / len(sel)
        sk = (100 * (1 - b / bb)) if bb > 0 else 0.0
        log(f"{stat:>20}  {len(sel):>7,}  {said:>6.1%}  {hap:>8.1%}  "
            f"{b:>7.4f}  {sk:>+6.1f}%")

    # ---- PIT, the tail test
    log("\nSHAPE — where the real outcome fell in the predicted distribution")
    log("   a flat spread is right. Weight piled at both ends means the")
    log("   distribution is too narrow and the tails are underpriced.")
    log(f"{'market':>20}  {'n':>6}  " + "  ".join(f"{int(q * 100):>3}%"
                                                  for q in (.1, .3, .5, .7, .9))
        + "   ends")
    for stat in sorted(pit):
        v = pit[stat]
        if len(v) < 200:
            continue
        a = np.asarray(v)
        qs = [float((a < q).mean()) for q in (.1, .3, .5, .7, .9)]
        ends = float(((a < 0.1) | (a > 0.9)).mean())
        log(f"{stat:>20}  {len(v):>6,}  "
            + "  ".join(f"{q:>4.2f}" for q in qs)
            + f"   {ends:.0%} vs 20% ideal")

    log("\n(ideal row reads 0.10 0.30 0.50 0.70 0.90 with 20% in the ends)")
    log(f"\nworst reliability gap: {worst:.1%}  (gate {MAX_GAP:.0%})")
    if worst >= MAX_GAP:
        log("FAIL: the probabilities do not come in at the rate they claim.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
