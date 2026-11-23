#!/usr/bin/env python3
"""Regression test for the NFL ownership model's calibration.

The model is a softmax and its temperature was a guess until three contests'
actual exposures existed to fit it against. This test pins the result so the
temperature cannot drift back, and so that a change to the appeal weights that
quietly wrecks calibration fails here instead of on a Sunday.

It scores the shipped model over archived slate boards against the transcribed
exposures. Boards live in data/boards/ and are the model's own inputs as they
stood before lock, so this measures the model and nothing else.

If this fails after a deliberate improvement, re-fit, update THRESHOLDS with
the new measured values, and say so in the commit.
"""
import copy
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(os.path.dirname(HERE), "data")

import build_nfl_slate as B          # noqa: E402
from enrich_props import nrm         # noqa: E402

# Measured on 270 players over three contests with the shipped temperatures.
# A little slack so a harmless change does not fail, but not enough to hide
# the over-dispersion this was built to catch: unfixed, pooled error was 3.97.
SLATES = {"2026-11-08": 3.04, "2026-11-15": 2.95, "2026-11-22": 3.87}
POOLED = 3.25
SLACK = 0.35

fails = []


def ok(cond, msg):
    print(f"   {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        fails.append(msg)


def load(date):
    bp = os.path.join(DATA, "boards", f"board_{date}.json")
    ap = os.path.join(DATA, f"nfl_actual_own_{date}.csv")
    if not (os.path.exists(bp) and os.path.exists(ap)):
        return None, None
    board = json.load(open(bp, encoding="utf-8"))
    act = {nrm(r["player"]): float(r["all"]) for r in csv.DictReader(
        l for l in open(ap, encoding="utf-8") if not l.startswith("#"))}
    return board, act


def score(board, act):
    players = copy.deepcopy(board["players"])
    B.ownership(players, board.get("scoring", "dk"))
    pairs = []
    for p in players:
        n = nrm(p["player"])
        own = (p.get("own") or {}).get("mme")
        if n in act and own is not None:
            pairs.append((act[n], own))
    return pairs


print("the model reproduces its measured error on each archived contest")
allp = []
missing = []
for date, target in sorted(SLATES.items()):
    board, act = load(date)
    if board is None:
        missing.append(date)
        continue
    pairs = score(board, act)
    mae = statistics.mean(abs(a - m) for a, m in pairs)
    allp += pairs
    ok(abs(mae - target) <= SLACK,
       f"{date}: {len(pairs)} players, mean error {mae:.2f} "
       f"(expected {target:.2f} +/- {SLACK})")

if missing:
    print(f"\n   SKIPPED {len(missing)} slate(s) with no archived board: "
          f"{', '.join(missing)}")

if allp:
    pooled = statistics.mean(abs(a - m) for a, m in allp)
    ok(abs(pooled - POOLED) <= SLACK,
       f"pooled over {len(allp)} players: {pooled:.2f} "
       f"(expected {POOLED:.2f} +/- {SLACK})")

    print("\nthe model is not over-dispersed: what it calls chalk must not be "
          "wildly over-stated")
    hi = [(a, m) for a, m in allp if m >= 25]
    if hi:
        bias = statistics.mean(m - a for a, m in hi)
        ok(bias <= 12.0,
           f"players modelled at 25%+ (n={len(hi)}) are over-predicted by "
           f"{bias:+.1f} points on average, which must stay under 12 "
           f"(it was +18.5 before the temperature was fitted)")
    lo = [(a, m) for a, m in allp if m < 8]
    if lo:
        bias = statistics.mean(m - a for a, m in lo)
        ok(abs(bias) <= 3.0,
           f"players modelled under 8% (n={len(lo)}) are off by {bias:+.1f} "
           f"points on average, which must stay within 3")

    print("\nit beats the trivial alternative by a wide margin")
    mu = statistics.mean(a for a, _ in allp)
    base = statistics.mean(abs(a - mu) for a, _ in allp)
    ok(pooled < 0.75 * base,
       f"mean error {pooled:.2f} against {base:.2f} for predicting the "
       f"average, a {100 * (1 - pooled / base):.0f}% reduction")

print("\nthe temperatures are the fitted ones and keep their ordering")
t = {k: v["temp"] for k, v in B.CONTESTS.items()}
ok(t["se"] < t["hs"] < t["mme"],
   f"single entry {t['se']} is sharper than high stakes {t['hs']} is sharper "
   f"than mass multi entry {t['mme']}")
ok(abs(t["hs"] - 1.40) < 1e-9,
   f"the high stakes temperature is the fitted 1.40, not {t['hs']}")

print()
if not allp:
    print("no archived board found; nothing was measured")
    sys.exit(1)
if fails:
    print(f"{len(fails)} check(s) FAILED")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("all checks passed")
