#!/usr/bin/env python3
"""
ingest_actual_ownership.py — what the field ACTUALLY owned, and how wrong we were.

WHY THIS EXISTS
Every leverage number this project computes is a ratio with projected ownership
in the denominator, and that denominator had never once been checked against
reality. When it finally was, on a single screenshot of one position, the model
turned out to be 10x high on its two highest-conviction calls:

  Malik Willis    projected 18.8%   actual  1.8%
  Tanner McKee    projected 25.2%   actual under 1.8%

Both were the top value plays by points per dollar, and the model assumed the
field would hammer them. It didn't. Worse, ownership is normalised to exactly
900%, so over-projecting those two by forty combined points pushed everyone
else down: nearly every other quarterback came in under. The normalisation
makes a single bad call contagious across the whole position.

So this takes actual post-contest ownership, joins it to the projection that
was archived before lock, and says plainly how far off it was and in which
direction.

INPUT
A CSV with a header, one row per player. Only `player` and `all` are required:

  pos,player,team,salary,points,all,top20,top10,top1
  QB,Joe Burrow,CIN,7000,45.48,8.5,35.4,55.6,96.9

`all` is ownership across the whole field. `top20`/`top10`/`top1` are ownership
within the top N% of lineups by score, which is the far more interesting
number: Burrow was 8.5% of the field and 96.9% of the top 1%. That ratio is
what a leverage model is really trying to predict, and having it as a column
means the model can finally be scored against it.

THE COMPLETENESS CHECK
A DraftKings classic lineup is nine slots, so ownership summing across every
player in the contest is exactly 900%: 100 at quarterback, 100 at defence, and
700 shared by the running backs, receivers and tight ends through the three
base slots plus the flex. That is an arithmetic identity, not an estimate, so
it doubles as a check on the input itself. If this data was read off a
scrolling screen and a position sums to 60 instead of 100, rows were missed,
and the calibration would silently be computed against a partial field. The
check runs first and says which position is short.

USAGE
  python tools/ingest_actual_ownership.py <csv> [--slate "Sun Nov 1 Main · 13 games"]
"""
import argparse
import csv
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "ownership_history")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402

# Roster slots per position in a DK classic lineup. RB/WR/TE share the flex, so
# they are checked as one pooled total rather than three separate ones.
SLOTS_EXACT = {"QB": 1.0, "DST": 1.0}
SLOTS_POOLED = {"RB", "WR", "TE"}
POOLED_SLOTS = 7.0
# How far a position's total may sit from its slot count before the input is
# treated as incomplete. Generous, because a contest's tail of sub-0.1% players
# is long and rounding on each one accumulates.
SUM_TOLERANCE_PCT = 12.0


def log(*a):
    print(*a, flush=True)


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        r = { (k or "").strip().lower(): (v or "").strip() for k, v in r.items() }
        name = r.get("player") or r.get("name")
        if not name:
            continue

        def num(key):
            v = (r.get(key) or "").replace("%", "").replace("$", "").replace(",", "")
            try:
                return float(v)
            except ValueError:
                return None

        out.append({
            "player": name,
            "pos": (r.get("pos") or r.get("position") or "").upper(),
            "team": (r.get("team") or "").upper(),
            "salary": num("salary"),
            "points": num("points") if "points" in r else num("fpts"),
            "all": num("all") if "all" in r else num("%drafted"),
            "top20": num("top20"), "top10": num("top10"), "top1": num("top1"),
        })
    return [r for r in out if r["all"] is not None]


def check_completeness(rows):
    """Ownership must sum to the number of roster slots. Report what is short."""
    tot = {}
    for r in rows:
        tot[r["pos"]] = tot.get(r["pos"], 0.0) + r["all"]
    log("\ncompleteness — ownership has to sum to the roster slots:")
    ok = True
    for pos, slots in SLOTS_EXACT.items():
        got = tot.get(pos, 0.0)
        want = slots * 100
        short = abs(got - want) > SUM_TOLERANCE_PCT
        ok &= not short
        log(f"   {pos:4} {got:7.1f}% of {want:5.0f}%  "
            f"{'SHORT — rows are missing' if short else 'ok'}")
    pooled = sum(tot.get(p, 0.0) for p in SLOTS_POOLED)
    want = POOLED_SLOTS * 100
    short = abs(pooled - want) > SUM_TOLERANCE_PCT
    ok &= not short
    log(f"   {'RB/WR/TE':8} {pooled:6.1f}% of {want:5.0f}%  (three base slots plus flex)  "
        f"{'SHORT — rows are missing' if short else 'ok'}")
    for p in sorted(SLOTS_POOLED):
        log(f"       {p:3} {tot.get(p, 0.0):7.1f}%  ({sum(1 for r in rows if r['pos'] == p)} players)")
    if not ok:
        log("\n   A short total means the capture stopped before the tail. The "
            "calibration below is still computed, but on a partial field: the "
            "players that are missing are the low-owned ones, which is exactly "
            "where the model's over-projections live.")
    return ok


def load_projection(slate):
    """The archived pre-lock projection for this slate."""
    best = None
    for fn in sorted(os.listdir(HIST)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(HIST, fn), encoding="utf-8") as f:
            d = json.load(f)
        if slate and d.get("slate") != slate:
            continue
        # The LAST build before lock is the one the field actually saw.
        if best is None or d.get("built", "") > best.get("built", ""):
            best = d
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--slate", default="", help="slate name to score against")
    ap.add_argument("--profile", default="mme", choices=("se", "hs", "mme"))
    args = ap.parse_args()

    rows = read_csv(args.csv)
    log(f"read {len(rows)} players from {args.csv}")
    check_completeness(rows)

    proj = load_projection(args.slate)
    if not proj:
        log(f"\nno archived projection matching slate {args.slate!r}; "
            f"writing actuals only.")
    else:
        log(f"\nscoring against {proj['slate']!r} built {proj['built']} "
            f"({len(proj['ownership'])} projected, {args.profile} profile)")
        pm = {nrm(k): (v or {}).get(args.profile) for k, v in proj["ownership"].items()}
        pairs = [(r, pm[nrm(r["player"])]) for r in rows
                 if nrm(r["player"]) in pm and pm[nrm(r["player"])] is not None]
        log(f"matched {len(pairs)} of {len(rows)} by name")
        if pairs:
            errs = [(r["all"] - p) for r, p in pairs]
            mae = sum(abs(e) for e in errs) / len(errs)
            bias = sum(errs) / len(errs)
            log(f"\n   mean absolute error {mae:5.2f} points of ownership")
            log(f"   mean signed error   {bias:+5.2f}  "
                f"({'model projects too LOW overall' if bias > 0 else 'model projects too HIGH overall'})")
            # Filtered, not just sorted. Taking the top eight of a sorted list
            # pads the over-projections with under-projections whenever there
            # are fewer than eight of them, and then prints each one as
            # "0.2x too high", which is the opposite of what happened.
            over = sorted((t for t in pairs if t[1] > t[0]["all"]),
                          key=lambda t: t[1] - t[0]["all"], reverse=True)[:8]
            under = sorted((t for t in pairs if t[0]["all"] > t[1]),
                           key=lambda t: t[0]["all"] - t[1], reverse=True)[:8]
            log(f"\n   worst OVER-projections ({len(over)} shown of "
                f"{sum(1 for t in pairs if t[1] > t[0]['all'])} — model said "
                f"chalk, field passed):")
            for r, pv in over:
                log(f"      {r['player']:22} proj {pv:5.1f}  actual {r['all']:5.1f}  "
                    f"({pv / max(r['all'], .01):5.1f}x too high)")
            log(f"\n   worst UNDER-projections ({len(under)} shown of "
                f"{sum(1 for t in pairs if t[0]['all'] > t[1])} — field piled "
                f"in, model missed):")
            for r, pv in under:
                log(f"      {r['player']:22} proj {pv:5.1f}  actual {r['all']:5.1f}  "
                    f"({r['all'] / max(pv, .01):5.1f}x too low)")

    # Winner leverage: ownership inside the top 1% against ownership overall.
    # This is the quantity the whole leverage idea is reaching for, and unlike
    # projected ownership it is measured rather than guessed.
    lev = [r for r in rows if r.get("top1") is not None and r["all"]]
    if lev:
        for r in lev:
            r["winnerLeverage"] = round(r["top1"] / r["all"], 2)
        lev.sort(key=lambda r: -r["winnerLeverage"])
        log("\nwinner leverage — share of the top 1% divided by share of the field:")
        for r in lev[:10]:
            log(f"   {r['player']:22} all {r['all']:5.1f}  top1% {r['top1']:5.1f}  "
                f"= {r['winnerLeverage']:6.2f}x   ({r['points'] if r['points'] is not None else '?'} pts)")
        # Only worth printing when the list is long enough that the tail is
        # not already on screen in the block above.
        if len(lev) > 16:
            log("\n   and the other end — owned by the field, absent from the winners:")
            for r in lev[-6:]:
                log(f"   {r['player']:22} all {r['all']:5.1f}  top1% {r['top1']:5.1f}  "
                    f"= {r['winnerLeverage']:6.2f}x   "
                    f"({r['points'] if r['points'] is not None else '?'} pts)")

    path = os.path.join(DATA, "nfl_actual_ownership.json")
    doc = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except ValueError:
            doc = {}
    doc.setdefault("slates", {})
    doc["slates"][args.slate or "unknown"] = {
        "capturedUtc": datetime.datetime.now(datetime.timezone.utc)
                       .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": os.path.basename(args.csv),
        "count": len(rows),
        "players": rows,
    }
    doc["updatedUtc"] = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"\nwrote {path} ({len(rows)} players)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
