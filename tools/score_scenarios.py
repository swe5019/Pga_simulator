#!/usr/bin/env python3
"""
score_scenarios.py — was the scenario page right?

Every number discover_scenarios.py publishes is a forecast, and until now none
of them had ever been scored. This takes an archived scenarios file and a
transcribed contest capture carrying top-1% ownership, and asks the only
question that matters: did the games it called leveraged actually show up in
the winning lineups?

HOW THE TRUTH IS MEASURED
A game's share of the field is the ownership of its players added up; its share
of the winners is the same sum taken inside the top 1% of lineups by score.
Dividing gives measured game leverage, which is the thing the page's leverage
column is trying to predict. Both are shares of the same nine roster slots, so
the ratio is meaningful even though the capture is partial.

WHAT THE PARTIAL CAPTURE DOES AND DOES NOT BREAK
FantasyLabs publishes no defence exposure, and the tail of each position is
missing, so the absolute shares here are NOT a game's true share of all nine
slots. They are its share of the players that were captured. The ratio survives
that much better than the levels do, because a player missing from the capture
is missing from both the numerator and the denominator. It is still a bias, and
it runs toward games whose captured players are a larger fraction of their real
ones, so treat the ORDERING as the result and the magnitudes as indicative.

USAGE
  python tools/score_scenarios.py --scenarios <file> --actual <csv> --board <file>
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402


def log(*a):
    print(*a, flush=True)


def read_actual(path):
    lines = [l for l in open(path, encoding="utf-8-sig")
             if not l.lstrip().startswith("#")]
    out = []
    for r in csv.DictReader(lines):
        try:
            out.append({"player": r["player"], "pos": r.get("pos", ""),
                        "all": float(r["all"]), "top1": float(r["top1"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", required=True)
    ap.add_argument("--actual", required=True)
    ap.add_argument("--board", required=True)
    args = ap.parse_args()

    with open(args.scenarios, encoding="utf-8") as f:
        sc = json.load(f)
    with open(args.board, encoding="utf-8") as f:
        board = json.load(f)
    actual = read_actual(args.actual)

    game = {}
    for p in board["players"]:
        if p.get("opp"):
            game[nrm(p["player"])] = "/".join(sorted((p["team"], p["opp"])))

    fld, top = defaultdict(float), defaultdict(float)
    matched, missed = 0, []
    for r in actual:
        g = game.get(nrm(r["player"]))
        if not g:
            missed.append(r["player"])
            continue
        matched += 1
        fld[g] += r["all"]
        top[g] += r["top1"]

    log(f"slate: {sc['slate']['name']}   scenarios built {sc['built']}")
    log(f"matched {matched} of {len(actual)} captured players to a game"
        + (f"; unmatched: {', '.join(missed[:5])}" if missed else ""))
    tf, tt = sum(fld.values()), sum(top.values())
    log(f"captured ownership: {tf:.0f}% of the field, {tt:.0f}% of the top 1%")
    log("(not 900% either side: no defence is published and the tails are cut)")

    # What the page said, at the two-deep grain, which is how it names a game.
    pred = {}
    for r in sc["scenarios"]:
        name = r["scenario"]
        if not name.endswith(" x2"):
            continue
        pred[name[:-3]] = r

    rows = []
    for g in fld:
        f_share, t_share = 100 * fld[g] / tf, 100 * top[g] / tt
        rows.append({
            "game": g, "field": f_share, "top1": t_share,
            "actual_lev": t_share / f_share if f_share else None,
            "pred": pred.get(g),
        })
    rows.sort(key=lambda r: -(r["actual_lev"] or 0))

    log("\n" + "=" * 86)
    log("MEASURED vs PREDICTED, by game")
    log("=" * 86)
    log(f"{'game':12}{'field%':>9}{'top1%':>9}{'ACTUAL':>9}"
        f"{'predicted':>11}{'page rank':>11}   verdict")
    ranked = [r for r in sc["scenarios"] if r["scenario"].endswith(" x2")]
    ranked.sort(key=lambda r: -r["leverage"])
    rank_of = {r["scenario"][:-3]: i + 1 for i, r in enumerate(ranked)}

    for r in rows:
        p = r["pred"]
        pl = f"{p['leverage']:.1f}x" if p else "—"
        rk = f"{rank_of.get(r['game'], '—')} of {len(ranked)}" if p else "—"
        a = r["actual_lev"]
        verdict = ""
        if p:
            if a >= 1.3 and p["leverage"] >= 2.0:
                verdict = "called it"
            elif a < 0.8 and p["leverage"] < 1.5:
                verdict = "correctly faded"
            elif a >= 1.3 and p["leverage"] < 1.5:
                verdict = "MISSED"
            elif a < 0.8 and p["leverage"] >= 2.0:
                verdict = "WRONG WAY"
        log(f"{r['game']:12}{r['field']:>8.1f}%{r['top1']:>8.1f}%"
            f"{a:>8.2f}x{pl:>11}{rk:>11}   {verdict}")

    # Rank correlation between what it predicted and what happened.
    both = [(r["pred"]["leverage"], r["actual_lev"])
            for r in rows if r["pred"] and r["actual_lev"] is not None]
    if len(both) > 2:
        def rank(v):
            s = sorted(range(len(v)), key=lambda i: v[i])
            out = [0] * len(v)
            for pos, i in enumerate(s):
                out[i] = pos
            return out
        rp, ra = rank([x for x, _ in both]), rank([y for _, y in both])
        n = len(both)
        mp, ma = sum(rp) / n, sum(ra) / n
        num = sum((rp[i] - mp) * (ra[i] - ma) for i in range(n))
        den = (sum((rp[i] - mp) ** 2 for i in range(n))
               * sum((ra[i] - ma) ** 2 for i in range(n))) ** .5
        log(f"\nrank correlation between predicted and measured leverage: "
            f"{num / den if den else 0:+.2f}  (over {n} games)")
        log("   +1 would be a perfect ordering, 0 is noise, -1 is backwards.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
