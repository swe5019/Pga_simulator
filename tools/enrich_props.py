#!/usr/bin/env python3
"""
enrich_props.py — attach historical hit rates to each Underdog prop line.

Reads data/nfl_props.json (written by fetch_props.py) and the per season
nfl_<year>.json files, and writes data/nfl_props_full.json, which is the file
the page loads.

WHAT A HIT RATE IS HERE
No historical odds are needed, which is the thing that makes this cheap. "Under
in 3 of 4" just means: take this player's last four games, count how many had
fewer receptions than the line sitting in front of us today. So the question is
always asked against TODAY's line, which is what a bettor actually cares about.

  L1  this season
  L2  this season plus last
  L3  this season plus the two before

Each window reports hits, games and rate, and the three are blended 20/40/40
into one number, weighted toward the longer samples because four games of
football is mostly noise.

WHAT IT CANNOT DO YET
Longest Reception, Longest Rush and every 1Q/1H split need play by play
extraction that does not exist yet; those props come through with no history
rather than a guess. Kicking and defensive props are not in the stats pipeline
at all. The run prints exactly how many rows fell into each bucket.
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Underdog's stat name -> how to compute it from one player-week row.
# A row is the weekly record written by fetch_nfl.py.
def _sum(*keys):
    return lambda r: sum(r.get(k, 0) for k in keys)


STAT_FN = {
    "Receptions": _sum("rec"),
    "Receiving Yards": _sum("ry"),
    "Targets": _sum("tg"),
    "Rush Yards": _sum("ru"),
    "Rush Attempts": _sum("ca"),
    "Rush + Rec Yards": _sum("ru", "ry"),
    "Pass Yards": _sum("py"),
    "Pass Attempts": _sum("att"),
    "Completions": _sum("cmp"),
    "Pass TDs": _sum("ptd"),
    "Interceptions": _sum("int"),
    "Pass + Rush Yards": _sum("py", "ru"),
    "Fumbles Lost": _sum("fl"),
    "Rec TDs": _sum("rtd"),
    "Rush TDs": _sum("utd"),
    "Rush + Rec TDs": _sum("rtd", "utd"),
    "Anytime TD": _sum("rtd", "utd"),
}

# Blend weights across the three windows. Weighted away from this season on
# purpose: a four game sample swings wildly, and the longer windows are what
# stop one freak afternoon dominating the number.
BLEND = {"l1": 0.20, "l2": 0.40, "l3": 0.40}


def log(*a):
    print(*a, flush=True)


def nrm(s):
    """Name key. Must survive 'J.K. Dobbins' against 'J.K. Dobbins' and
    'Jaxon Smith-Njigba' against itself, plus the Jr/Sr/III disagreements
    between feeds."""
    s = (s or "").lower()
    s = re.sub(r"[.'`,]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z]+", "", s)


def load_seasons():
    """Newest first. Whatever seasons are on disk get used; L3 silently becomes
    a two season window until the 2024 backfill lands, and the games count in
    the output says so."""
    idx_path = os.path.join(DATA, "nfl_index.json")
    if not os.path.exists(idx_path):
        raise SystemExit("no nfl_index.json; run fetch_nfl.py first")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    out = {}
    for s in sorted(idx["seasons"], key=lambda s: -int(s["season"])):
        p = os.path.join(DATA, s["file"])
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            out[int(s["season"])] = json.load(f)
    return out, int(idx.get("current") or max(out))


def game_logs(seasons):
    """name key -> {season: [row, ...]} with rows newest first."""
    logs = defaultdict(lambda: defaultdict(list))
    for yr, doc in seasons.items():
        meta = {p["id"]: p for p in doc["players"]}
        for r in doc["rows"]:
            m = meta.get(r["i"])
            if not m:
                continue
            logs[nrm(m["n"])][yr].append(r)
    for k in logs:
        for yr in logs[k]:
            logs[k][yr].sort(key=lambda r: -r["w"])
    return logs


def hit_rate(rows, fn, line, side):
    """Count games clearing the line. Underdog lines carry a .5 so there are no
    pushes, but the comparison is written strictly either way."""
    hits = n = 0
    for r in rows:
        v = fn(r)
        n += 1
        if side == "over":
            hits += 1 if v > line else 0
        else:
            hits += 1 if v < line else 0
    return hits, n


def main():
    props_path = os.path.join(DATA, "nfl_props.json")
    if not os.path.exists(props_path):
        log("no nfl_props.json; run fetch_props.py first")
        return 1
    with open(props_path, encoding="utf-8") as f:
        doc = json.load(f)
    props = doc["props"]

    seasons, current = load_seasons()
    years = sorted(seasons, reverse=True)
    log(f"seasons available: {years} (current {current})")
    if len(years) < 3:
        log(f"   only {len(years)} seasons on disk, so L3 covers {len(years)}; "
            f"backfill earlier years to deepen it")
    logs = game_logs(seasons)
    log(f"game logs for {len(logs):,} players")

    w1 = [current]
    w2 = [y for y in (current, current - 1) if y in seasons]
    w3 = [y for y in (current, current - 1, current - 2) if y in seasons]

    counts = defaultdict(int)
    unmatched = set()
    for p in props:
        fn = STAT_FN.get(p["stat"])
        if fn is None:
            counts["stat not supported yet"] += 1
            continue
        key = nrm(p["player"])
        if key not in logs:
            counts["player not in stats data"] += 1
            unmatched.add(p["player"])
            continue

        line, side = p["line"], p["side"]
        out = {}
        for label, yrs in (("l1", w1), ("l2", w2), ("l3", w3)):
            rows = [r for y in yrs for r in logs[key].get(y, [])]
            h, n = hit_rate(rows, fn, line, side)
            out[label] = {"h": h, "n": n, "r": round(h / n, 4) if n else None}

        # Blend, using only the windows that actually have games so a player
        # with one season is not quietly scored as if he had three.
        num = den = 0.0
        for label, wgt in BLEND.items():
            if out[label]["r"] is not None and out[label]["n"] > 0:
                num += wgt * out[label]["r"]
                den += wgt
        blended = round(num / den, 4) if den else None

        p["hits"] = out
        p["histRate"] = blended
        # Edge on history alone: how far the blended rate clears the price.
        # Positive means history says this side wins more often than the price
        # demands. It is not a projection, it is a sanity check on one.
        if blended is not None and p.get("decimal"):
            p["histEdge"] = round((blended - 1.0 / p["decimal"]) * 100, 1)
        counts["enriched"] += 1

    log("\nrows:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        log(f"   {v:>6}  {k}")
    if unmatched:
        log(f"\n{len(unmatched)} unmatched player names, first 15:")
        for n in sorted(unmatched)[:15]:
            log(f"   {n}")

    doc["enrichedAt"] = doc.get("built")
    doc["seasons"] = years
    out_path = os.path.join(DATA, "nfl_props_full.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"\nwrote nfl_props_full.json ({os.path.getsize(out_path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
