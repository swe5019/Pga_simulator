#!/usr/bin/env python3
"""Checks on the kicker model.

The accuracy claim this model can actually support is that it is UNBIASED over
the kickers on file. It cannot support a skill claim: actual kicker scores
carry about 2.3 points of irreducible noise against 1.1 of real spread between
kickers, so a perfect model would average 1.83 points of error and a flat
league average 2.03, and nine observations have a standard error of 0.85. The
bias test below is therefore the real one, and there is deliberately no test
asserting that the model beats a flat average.
"""
import collections
import csv
import datetime
import glob
import json
import os
import statistics
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DATA = os.path.join(os.path.dirname(HERE), "data")

import kicker_model as K      # noqa: E402

MAX_BIAS = 0.60               # points, over the captured kickers
fails = []


def ok(cond, msg):
    print(f"   {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        fails.append(msg)


def two_sided(line, over_dec, under_dec):
    return {"over": {"line": line, "decimal": over_dec},
            "under": {"line": line, "decimal": under_dec}}


print("a Poisson mean is recovered from an over/under line")
# A fair coin on "2 or more" means P(X>=2)=0.5, which for a Poisson is lam~1.68
lam = K.lam_from_line(0.5, 1.5)
ok(1.4 < lam < 2.0, f"a 50/50 line at 1.5 implies a mean of {lam:.2f}")
ok(K.lam_from_line(0.9, 1.5) > K.lam_from_line(0.3, 1.5),
   "a longer price on the over implies a higher mean")
ok(K.lam_from_line(None, 1.5) is None and K.lam_from_line(0.5, None) is None,
   "a missing price or line returns nothing rather than guessing")

print("\nde-vigging removes the hold")
p = K._fair(1.90, 1.90)
ok(abs(p - 0.5) < 1e-9, f"two equal prices de-vig to exactly {p:.3f}")
p = K._fair(1.50, 2.50)
ok(0.6 < p < 0.68, f"a 1.50 favourite de-vigs to {p:.3f}, not the raw 0.667")

print("\nthe kicking points market is the anchor, not the components")
m = {"Kicking Points": two_sided(7.5, 1.90, 1.90),
     "FG Made": two_sided(1.5, 1.90, 1.90),
     "XP Made": two_sided(2.5, 1.90, 1.90)}
fg, xp, src = K.expectations(m)
ok(src == "kicking points", f"source is {src!r}")
total = K.FG_BASE * fg + xp
ok(abs(total - K.lam_from_line(0.5, 7.5)) < 0.1,
   f"3*FG + XP reproduces the kicking points mean ({total:.2f})")
# Breaking a component must not move the total.
m2 = dict(m, **{"FG Made": two_sided(4.5, 1.90, 1.90)})
fg2, xp2, _ = K.expectations(m2)
ok(abs((K.FG_BASE * fg2 + xp2) - total) < 0.1,
   "a badly wrong FG line cannot move the total, only the split")

print("\na kicker with no markets gets nothing, not a guess")
pts, src = K.projected_points({})
ok(pts is None, f"no market returns {pts!r} with source {src!r}")
ok(K.sample_points(np.random.default_rng(1), {}, 100) is None,
   "sampling an unpriced kicker returns nothing so a caller can drop him")

print("\nsampling matches the stated expectation and is not negative")
rng = np.random.default_rng(11)
s = K.sample_points(rng, m, 40000)
exp, _ = K.projected_points(m)
ok(abs(s.mean() - exp) < 0.05,
   f"sampled mean {s.mean():.3f} matches the projection {exp:.3f}")
ok(s.min() >= 0, f"no negative scores (min {s.min():.2f})")
ok(np.percentile(s, 90) > exp,
   f"the distribution has upside: p90 {np.percentile(s, 90):.1f} "
   f"above the mean {exp:.1f}")

print("\nUNBIASED over every kicker captured so far")
obs = []
for f in sorted(glob.glob(os.path.join(DATA, "nfl_showdown_own_2026-*.csv"))):
    date = "2026-11-" + os.path.basename(f)[-6:-4]
    for r in csv.DictReader(l for l in open(f, encoding="utf-8")
                            if not l.startswith("#")):
        if r.get("pos") == "K" and r["slot"] == "FLEX":
            obs.append((date, r["player"], float(r["points"])))

snaps = sorted(glob.glob(os.path.join(DATA, "props_history", "props_*.json")))


def markets_for(name, before):
    best = None
    for f in snaps:
        t = datetime.datetime.strptime(os.path.basename(f)[6:21],
                                       "%Y-%m-%d_%H%M")
        if t <= before and (best is None or t > best[0]):
            best = (t, f)
    if not best:
        return {}
    doc = json.load(open(best[1], encoding="utf-8"))
    rows = doc.get("props") if isinstance(doc, dict) else doc
    out = collections.defaultdict(dict)
    for r in rows or []:
        if r.get("player") == name and r.get("stat") in (
                "FG Made", "XP Made", "Kicking Points"):
            out[r["stat"]][r.get("side", "")] = {
                "line": r.get("line"), "decimal": r.get("decimal")}
    return dict(out)


pairs = []
for date, name, actual in obs:
    when = datetime.datetime.strptime(date, "%Y-%m-%d") \
        + datetime.timedelta(hours=12)
    pts, _src = K.projected_points(markets_for(name, when))
    if pts is not None:
        pairs.append((pts, actual))

if len(pairs) < 5:
    print(f"   SKIP only {len(pairs)} kickers could be priced from the "
          f"archive; nothing to test")
else:
    bias = statistics.mean(p - a for p, a in pairs)
    ok(abs(bias) <= MAX_BIAS,
       f"{len(pairs)} kickers: projected {statistics.mean(p for p, _ in pairs):.2f} "
       f"against actual {statistics.mean(a for _, a in pairs):.2f}, "
       f"bias {bias:+.2f} (must stay within {MAX_BIAS})")
    mae = statistics.mean(abs(p - a) for p, a in pairs)
    print(f"   note mean error is {mae:.2f}, which is NOT a pass/fail: a "
          f"perfect model would average about 1.83 on this noise")

print()
if fails:
    print(f"{len(fails)} check(s) FAILED")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("all checks passed")
