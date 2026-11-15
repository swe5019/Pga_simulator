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
Dividing gives measured game leverage, which is what the page's leverage column
is trying to predict. Both are shares of the same nine roster slots, so the
ratio is meaningful even though the capture is partial.

MATCHING THE UNITS, WHICH THE FIRST VERSION OF THIS DID NOT
The page names a scenario as a game AND a depth, "GB/NE x4", and its Field%
is the share of lineups whose PRIMARY stack is that exact pair. The first
version of this file compared a game's x2 row alone against that game's whole
ownership share, which are not the same quantity and cannot agree in level: a
game that the model expects to be stacked three and four deep has most of its
mass in rows that were being ignored. That produced a confident and wrong
conclusion, that the model never sees a crowded game. It does. Its projected
ownership by game correlates +0.81 with what the field really did on
8 November, with the same spread, and the sampler reproduces that intent at
+0.99.

So both sides are now put in SLOT SHARE, the share of the nine roster spots a
game supplies:

  model field  the archived projected ownership, summed by game. Used rather
               than the sampled field because the sampler was measured to
               reproduce it at +0.99 correlation, so it adds nothing but noise.
  model winner sum over depths of pWin(game, depth) * depth, normalised. This
               counts a game's slots in the winning lineups the simulation
               found. It UNDERCOUNTS, because a game contributing one lone
               player to a winner is never that winner's primary stack and so
               appears in no row at all. Treat it as a floor.
  real field   captured ownership, summed by game.
  real winner  the same sum inside the top 1%.

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
    ap.add_argument("--projection", required=True,
                    help="the archived ownership_history file the scenarios "
                         "were sampled from")
    args = ap.parse_args()

    with open(args.scenarios, encoding="utf-8") as f:
        sc = json.load(f)
    with open(args.board, encoding="utf-8") as f:
        board = json.load(f)
    actual = read_actual(args.actual)
    with open(args.projection, encoding="utf-8") as f:
        proj_own = {nrm(k): (v or {}).get("mme")
                    for k, v in json.load(f)["ownership"].items()}

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

    # The model's winner slot share: every depth row for a game, weighted by
    # how many slots that depth uses. Summing the x2 row alone threw away most
    # of the mass for any game the model expected to be stacked deeply.
    mwin = defaultdict(float)
    for r in sc["scenarios"]:
        name = r["scenario"]
        if " x" not in name:
            continue
        g, _, d = name.rpartition(" x")
        try:
            depth = int(d)
        except ValueError:
            continue
        mwin[g] += r["pWin"] * depth
    tmw = sum(mwin.values())

    # The model's field slot share: the archived projection it was sampled from.
    mfld = defaultdict(float)
    for k, v in proj_own.items():
        g = game.get(k)
        if g and v is not None:
            mfld[g] += v
    tmf = sum(mfld.values())

    rows = []
    for g in fld:
        f_share, t_share = 100 * fld[g] / tf, 100 * top[g] / tt
        pf = 100 * mfld[g] / tmf if tmf else None
        pw = 100 * mwin[g] / tmw if tmw else None
        rows.append({
            "game": g, "field": f_share, "top1": t_share,
            "actual_lev": t_share / f_share if f_share else None,
            "pred_field": pf, "pred_win": pw,
            "pred_lev": (pw / pf) if (pf and pw is not None) else None,
        })
    rows.sort(key=lambda r: -(r["actual_lev"] or 0))

    log("\n" + "=" * 88)
    log("MEASURED vs PREDICTED, by game — both as share of the nine roster slots")
    log("=" * 88)
    log(f"{'game':12}{'fld pred':>10}{'fld real':>10}"
        f"{'win pred':>10}{'win real':>10}{'lev pred':>10}{'lev REAL':>10}")
    for r in rows:
        pf = f"{r['pred_field']:.1f}%" if r['pred_field'] is not None else "—"
        pw = f"{r['pred_win']:.1f}%" if r['pred_win'] is not None else "—"
        pl = f"{r['pred_lev']:.2f}x" if r['pred_lev'] is not None else "—"
        log(f"{r['game']:12}{pf:>10}{r['field']:>9.1f}%{pw:>10}"
            f"{r['top1']:>9.1f}%{pl:>10}{r['actual_lev']:>9.2f}x")

    # Rank correlation between what it predicted and what happened.
    both = [(r["pred_lev"], r["actual_lev"]) for r in rows
            if r["pred_lev"] is not None and r["actual_lev"] is not None]
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
        log(f"\nrank correlation, predicted vs measured leverage: "
            f"{num / den if den else 0:+.2f}  (over {n} games)")
        log("   +1 would be a perfect ordering, 0 is noise, -1 is backwards.")
        import statistics as _st
        log(f"\nspread of the FIELD share, which is the crowding question:")
        log(f"   predicted stdev {_st.pstdev([r['pred_field'] for r in rows]):.2f}"
            f"   measured stdev {_st.pstdev([r['field'] for r in rows]):.2f}")
        log(f"   predicted max {max(r['pred_field'] for r in rows):.1f}%"
            f"   measured max {max(r['field'] for r in rows):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
