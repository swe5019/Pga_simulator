#!/usr/bin/env python3
"""Checks on the flex ownership model, run in CI alongside the solver tests.

These are not accuracy tests. Accuracy is measured by holding slates out and
is recorded in the module docstring. These check the arithmetic identities and
the invariants a page would otherwise violate silently.
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex_ownership import flex_ownership, TOTAL, MIN_REPORTABLE, POS  # noqa: E402
from captain_ownership import captain_ownership                        # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data")
fails = []


def ok(cond, msg):
    print(f"   {'ok  ' if cond else 'FAIL'} {msg}")
    if not cond:
        fails.append(msg)


def slates():
    for f in sorted(glob.glob(os.path.join(DATA,
                                           "nfl_showdown_own_2026-*.csv"))):
        rows = [r for r in csv.DictReader(
            l for l in open(f, encoding="utf-8") if not l.startswith("#"))]
        yield os.path.basename(f), rows


print("flex ownership sums to 500%, which is what five flex slots means")
pool = [{"player": "A", "sal": 10000, "pos": "QB"},
        {"player": "B", "sal": 7000, "pos": "RB"},
        {"player": "C", "sal": 4000, "pos": "DST"},
        {"player": "D", "sal": 3000, "pos": "K"},
        {"player": "E", "sal": 6000, "pos": "WR"},
        {"player": "F", "sal": 5000, "pos": "TE"},
        {"player": "G", "sal": 4500, "pos": "WR"}]
own = flex_ownership(pool)
ok(abs(sum(own.values()) - TOTAL) < 1e-6,
   f"a seven-man pool sums to {sum(own.values()):.4f}, expected {TOTAL}")

print("\nno single player can exceed 100%, because a slot is either his or not")
# A pool this lopsided is not realistic, but the identity must hold anyway.
big = flex_ownership([{"player": "A", "sal": 12000, "pos": "QB"},
                      {"player": "B", "sal": 200, "pos": "WR"}])
ok(max(big.values()) <= 100.0 + 1e-9,
   f"most owned is {max(big.values()):.1f}%, which must not exceed 100%")

print("\na pool too short to fill five slots sums to what it can, not to 500%")
short = flex_ownership([{"player": "A", "sal": 9000, "pos": "QB"},
                        {"player": "B", "sal": 3000, "pos": "WR"}])
ok(abs(sum(short.values()) - 200.0) < 1e-6,
   f"two players sum to {sum(short.values()):.1f}%, which is all two can hold")

print("\nthe cap redistributes rather than discarding, so the total survives")
lop = flex_ownership([{"player": "A", "sal": 20000, "pos": "QB"}]
                     + [{"player": f"p{i}", "sal": 3000, "pos": "WR"}
                        for i in range(8)])
ok(abs(sum(lop.values()) - TOTAL) < 1e-6,
   f"after capping, the pool still sums to {sum(lop.values()):.4f}")
ok(lop["A"] <= 100.0 + 1e-9, "the capped player sits at or under 100%")

print("\nthe captain multiplier cancels, so captain prices give the same answer")
a = flex_ownership(pool)
b = flex_ownership([{**p, "sal": p["sal"] * 1.5} for p in pool])
ok(all(abs(a[k] - b[k]) < 1e-9 for k in a),
   "scaling every salary by 1.5 leaves the shares unchanged")

print("\nan unknown position is treated as a wide receiver, never dropped")
u = flex_ownership([{"player": "A", "sal": 5000, "pos": "LS"},
                    {"player": "B", "sal": 5000, "pos": "WR"}])
ok(len(u) == 2 and abs(u["A"] - u["B"]) < 1e-9,
   "an unrecognised position keeps the player at the neutral multiplier")
ok(len(flex_ownership([{"player": "A", "sal": 5000}])) == 1,
   "a missing position key does not raise")

print("\ndegenerate input returns nothing rather than dividing by zero")
ok(flex_ownership([]) == {}, "an empty pool returns an empty mapping")
ok(flex_ownership([{"player": "A", "sal": 0, "pos": "WR"}]) == {},
   "a pool with no priced player returns an empty mapping")

print("\nthe two markets are distinct, which is the reason this module exists")
mixed = [{"player": "rich", "sal": 10000, "pos": "RB"},
         {"player": "kicker", "sal": 4600, "pos": "K"}]
f = flex_ownership(mixed)
c = captain_ownership([{"player": p["player"], "sal": p["sal"]} for p in mixed])
ratio_rich = f["rich"] / c["rich"]
ratio_kick = f["kicker"] / c["kicker"]
ok(ratio_kick > 2 * ratio_rich,
   f"a cheap kicker is relatively far more flexed than captained "
   f"({ratio_kick:.1f}x against {ratio_rich:.1f}x), as the captures show")

print("\nevery capture file carries a position for every row")
for name, rows in slates():
    bad = [r["player"] for r in rows if not r.get("pos")]
    ok(not bad, f"{name}: all {len(rows)} rows have a position")

print("\ncaptured totals are consistent with the two markets' identities")
for name, rows in slates():
    fl = sum(float(r["all"]) for r in rows if r["slot"] == "FLEX")
    cp = sum(float(r["all"]) for r in rows if r["slot"] == "CPT")
    ok(0 < fl <= TOTAL + 1e-9,
       f"{name}: flex capture {fl:.1f}% is positive and at most {TOTAL:.0f}%")
    ok(0 < cp <= 100.0 + 1e-9,
       f"{name}: captain capture {cp:.1f}% is positive and at most 100%")

print("\nthe reported floor is respected")
tiny = flex_ownership([{"player": "A", "sal": 12000, "pos": "QB"}]
                      + [{"player": f"p{i}", "sal": 200, "pos": "WR"}
                         for i in range(60)])
ok(min(tiny.values()) >= MIN_REPORTABLE - 1e-9,
   f"the smallest reported share is {min(tiny.values()):.2f}%, "
   f"at or above the {MIN_REPORTABLE}% floor")

print("\nthe no-markets guard, which is the thing most likely to misfire")
guarded = [{"player": "starter", "sal": 10000, "pos": "QB", "anchors": 7},
           {"player": "backup", "sal": 6000, "pos": "QB", "anchors": 0},
           {"player": "wr", "sal": 8000, "pos": "WR", "anchors": 4},
           {"player": "te", "sal": 5000, "pos": "TE", "anchors": 3},
           {"player": "rb", "sal": 7000, "pos": "RB", "anchors": 5},
           {"player": "dst", "sal": 4000, "pos": "DST", "anchors": 0}]
g = flex_ownership(guarded)
ok(g["backup"] <= MIN_REPORTABLE + 1e-9,
   f"a quarterback with no prop markets drops to {g['backup']:.2f}%")
ok(g["dst"] > 5.0,
   f"a DEFENCE with no prop markets is NOT excluded, at {g['dst']:.1f}%: "
   f"defences never carry player props, and two of six in the sample were "
   f"rostered at 19.3% and 11.1%")
ok(abs(sum(g.values()) - (TOTAL + MIN_REPORTABLE)) < 1e-6,
   "the excluded player keeps his floor and the rest still sum to 500%")
ok(set(g) == {p["player"] for p in guarded},
   "an excluded player is still returned, so no caller loses a row silently")

print("\nthe guard is off unless the caller supplies the evidence")
blind = flex_ownership([{k: v for k, v in p.items() if k != "anchors"}
                        for p in guarded])
ok(blind["backup"] > 5.0,
   f"without anchors the same backup is modelled at {blind['backup']:.1f}%, "
   f"because a model that cannot see the evidence must not act on it")

print("\nthe captain model applies the same guard")
cg = captain_ownership(guarded)
ok(cg["backup"] <= 1.0,
   f"a quarterback with no prop markets is captained at {cg['backup']:.2f}%")
ok(cg["dst"] > 0.5, f"a defence is still captainable, at {cg['dst']:.1f}%")

print("\nposition multipliers are ordered the way the captures are")
ok(POS["K"] > POS["WR"] and POS["QB"] > POS["RB"],
   "kickers are lifted above receivers and quarterbacks above running backs")

print()
if fails:
    print(f"{len(fails)} check(s) FAILED")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("all checks passed")
