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
import math
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

# Shrinkage, in games. A player's own hit rate is pulled toward the price with
# this much weight, so a five game record barely moves off the market and a
# forty game one nearly stands on its own.
PRIOR_GAMES = 12
# Under this many games in the widest window, history is flagged as thin.
MIN_GAMES = 8
# How many recent games define "his role now".
ROLE_GAMES = 3
# Snap share distance at which a past game counts about a third. 0.22 means a
# 60% snap starter still gets partial credit for his 40% games and almost none
# for his 15% ones.
ROLE_SCALE = 0.22


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
    """name key -> {season: [row, ...]}, newest first, each row tagged with the
    share of his team's offensive snaps he played that week.

    Snap share is what makes a historical game comparable or not. A back who
    took 23% of the snaps is a different player from the same man taking 60%,
    and counting both as one record is how a backup's quiet games get read as
    evidence about a starter."""
    logs = defaultdict(lambda: defaultdict(list))
    for yr, doc in seasons.items():
        meta = {p["id"]: p for p in doc["players"]}
        for r in doc["rows"]:
            m = meta.get(r["i"])
            if not m:
                continue
            t = doc["teams"].get(f"{r['t']}|{r['w']}") or {}
            tsn = t.get("sn") or 0
            r["_snap"] = (r.get("sn", 0) / tsn) if tsn else None
            logs[nrm(m["n"])][yr].append(r)
    for k in logs:
        for yr in logs[k]:
            logs[k][yr].sort(key=lambda r: -r["w"])
    return logs


def current_role(logs_for_player, current_season):
    """His role now, as mean snap share over the most recent games played.

    Taken from this season only. Last year's role is exactly the thing we are
    trying not to be fooled by."""
    rows = logs_for_player.get(current_season, [])
    snaps = [r["_snap"] for r in rows[:ROLE_GAMES] if r.get("_snap") is not None]
    return sum(snaps) / len(snaps) if snaps else None


def role_weight(snap, role_now):
    """How much a past game counts, by how close its role was to today's.

    A game at the same snap share counts fully, one 22 points away counts about
    a third, one 45 points away barely at all. Gaussian rather than a cutoff so
    the weight falls away smoothly instead of flipping at an arbitrary line.
    With no snap data, or no known current role, the game counts fully: better
    to fall back to a plain hit rate than to invent a weight."""
    if snap is None or role_now is None:
        return 1.0
    return math.exp(-(((snap - role_now) / ROLE_SCALE) ** 2))


def hit_rate(rows, fn, line, side, role_now=None):
    """Games clearing the line, counted twice over.

    Raw: the plain count, which is what a reader expects to see as "3 of 4".
    Weighted: the same games weighted by how close each one's role was to his
    role today, which is what should actually be leaned on.

    Returns (hits, n, weighted_rate, effective_n). Effective n is Kish's
    formula, the number of equally weighted games the weighted sample is worth,
    and it is what shrinkage keys off: thirty backup games are not thirty games
    of evidence about a starter.

    Underdog lines carry a .5 so there are no pushes, but the comparison is
    written strictly either way."""
    hits = n = 0
    wsum = w2sum = whit = 0.0
    for r in rows:
        v = fn(r)
        ok = (v > line) if side == "over" else (v < line)
        n += 1
        hits += 1 if ok else 0
        w = role_weight(r.get("_snap"), role_now)
        wsum += w
        w2sum += w * w
        whit += w if ok else 0.0
    wrate = (whit / wsum) if wsum > 0 else None
    eff = (wsum * wsum / w2sum) if w2sum > 0 else 0.0
    return hits, n, wrate, eff


def main():
    props_path = os.path.join(DATA, "nfl_props.json")
    if not os.path.exists(props_path):
        log("no nfl_props.json; run fetch_props.py first")
        return 1
    with open(props_path, encoding="utf-8") as f:
        doc = json.load(f)
    props = doc["props"]

    # Matchup multipliers, if they have been built. Optional: a missing file
    # costs the matchup column and nothing else.
    mpath = os.path.join(DATA, "nfl_matchups.json")
    matchups = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            matchups = json.load(f).get("matchups") or {}
        log(f"{len(matchups):,} matchup combinations loaded")
    else:
        log("no nfl_matchups.json; matchup column will be empty")

    # The market's genuine opinion, with the house edge taken out. Both
    # break-evens on a line sum to about 105%, and that extra 5% is Underdog's
    # cut, not a belief about the player. Shrinking toward the priced number
    # therefore drags both sides upward and produces a pair of probabilities
    # that cannot both be true. So shrink toward the DE-VIGGED split, which is
    # what the market actually thinks, while still measuring edge against the
    # real price, which is what has to be beaten.
    sides = defaultdict(dict)
    for p0 in props:
        if p0.get("decimal") and p0.get("line_id"):
            sides[p0["line_id"]][p0["side"]] = 1.0 / p0["decimal"]
    fair = {}
    for lid, v in sides.items():
        tot = sum(v.values())
        if tot > 0:
            for side, imp in v.items():
                # One-sided lines cannot be de-vigged, so they keep their price.
                fair[(lid, side)] = (imp / tot) if len(v) > 1 else imp

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
        role_now = current_role(logs[key], current)
        out = {}
        eff3 = 0.0
        for label, yrs in (("l1", w1), ("l2", w2), ("l3", w3)):
            rows = [r for y in yrs for r in logs[key].get(y, [])]
            h, n, wrate, eff = hit_rate(rows, fn, line, side, role_now)
            out[label] = {
                "h": h, "n": n,
                "r": round(h / n, 4) if n else None,      # plain, for display
                "w": round(wrate, 4) if wrate is not None else None,  # role weighted
            }
            if label == "l3":
                eff3 = eff

        # Blend, using only the windows that actually have games so a player
        # with one season is not quietly scored as if he had three.
        num = den = rnum = rden = 0.0
        for label, wgt in BLEND.items():
            if out[label]["n"] > 0 and out[label]["w"] is not None:
                num += wgt * out[label]["w"]
                den += wgt
            if out[label]["r"] is not None and out[label]["n"] > 0:
                rnum += wgt * out[label]["r"]
                rden += wgt
        blended = round(num / den, 4) if den else None     # role weighted
        raw = round(rnum / rden, 4) if rden else None      # plain

        # The evidence count is the EFFECTIVE number of games, not the raw one.
        # Two different ways a raw count lies: a rookie has the same five games
        # in all three windows, and a player who just took over a starting job
        # has thirty games of a backup's workload being compared against a line
        # priced for a starter. Both read as deep history and neither is.
        n3 = out["l3"]["n"]
        eff_n = eff3
        be = (1.0 / p["decimal"]) if p.get("decimal") else None
        # What to pull toward: the de-vigged market view, falling back to the
        # raw price when the other side is missing.
        prior = fair.get((p.get("line_id"), p["side"]), be)

        # So shrink toward the price. With little evidence the honest default is
        # that the market is right, and the pull fades as games accumulate: five
        # games barely move off the line, forty are nearly all their own. This
        # degrades smoothly, unlike a cutoff that flips at an arbitrary game.
        shrunk = blended
        if blended is not None and prior is not None and eff_n > 0:
            shrunk = round((eff_n * blended + PRIOR_GAMES * prior) / (eff_n + PRIOR_GAMES), 4)

        p["hits"] = out
        p["histRaw"] = raw          # plain count, what actually happened
        p["histRate"] = shrunk      # role weighted and shrunk, what to lean on
        p["histN"] = n3             # games played
        p["histEff"] = round(eff_n, 1)   # games worth of comparable evidence
        if role_now is not None:
            p["roleNow"] = round(role_now * 100, 1)
            # Average role across the games his history is built from. When this
            # sits far below roleNow he has just moved into a bigger job and the
            # raw hit rate is describing somebody else's workload.
            rows3 = [r for y in w3 for r in logs[key].get(y, [])]
            snaps = [r["_snap"] for r in rows3 if r.get("_snap") is not None]
            if snaps:
                p["roleHist"] = round(sum(snaps) / len(snaps) * 100, 1)
                p["roleShift"] = round(p["roleNow"] - p["roleHist"], 1)
        # Below this there is not enough history to mean anything, which is the
        # normal state for a rookie. The page marks these rather than hiding
        # them: "no history" is useful information, a confident wrong number
        # is not.
        p["thin"] = eff_n < MIN_GAMES
        if shrunk is not None and be is not None:
            # Edge is still measured against the PRICE, not the fair value. The
            # vig is real money and has to be cleared.
            p["histEdge"] = round((shrunk - be) * 100, 1)
            p["fairBE"] = round(prior * 100, 1) if prior is not None else None
        # How this defense has treated this position in this stat. Attached to
        # both sides of a line unchanged: the multiplier describes the defense,
        # and which side of the number that helps is for the reader to judge.
        mk = f"{p.get('opp', '')}|{p.get('pos', '')}|{p['stat']}"
        mm = matchups.get(mk)
        if mm:
            p["mu"] = mm["mult"]
            p["muRaw"] = mm["raw"]
            p["muN"] = mm["n"]
            p["muGames"] = mm["games"]

        counts["enriched"] += 1
        if p["thin"]:
            counts["  of those, thin history (rookie or little played)"] += 1

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
