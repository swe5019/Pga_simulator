#!/usr/bin/env python3
"""
build_matchups.py — how much each defense inflates or suppresses a stat.

Writes data/nfl_matchups.json: for every (defense, position, stat) it answers
"compared with what these players normally do, what happened against this
defense?" A multiplier of 1.14 means 14% more than expected.

WHY IT IS NOT JUST "YARDS ALLOWED"
A defense that happens to have faced three elite receiving backs will look
generous on running back targets, and a raw allowed total cannot tell that
apart from actually being soft. So the denominator is expected, not league
average: each player's own rate from his OTHER games. Facing good players
raises the bar rather than flattering the defense.

Then that is iterated. A player's "own rate from his other games" is itself
polluted by whoever he played in those games, so after a first pass of defense
multipliers, each expectation is divided by the multiplier of the defense that
game was against, and the whole thing is recomputed. Three passes is plenty;
the numbers stop moving.

Finally the result is shrunk toward 1.0 by sample size. Five games of football
against one position is a small number of player-games, and an unshrunk
multiplier off six carries would read as a finding rather than as noise.
"""
import datetime
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

POSITIONS = ("QB", "RB", "WR", "TE")

# The stats a prop can key off, computed from one weekly row.
def _sum(*keys):
    return lambda r: sum(r.get(k, 0) for k in keys)


STATS = {
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
    "Anytime TD": _sum("rtd", "utd"),
    "Rush + Rec TDs": _sum("rtd", "utd"),
}

ITERATIONS = 3
# Player-games of prior pulling the multiplier toward 1.0. A defense has played
# five games; without this, a position it has barely seen produces a confident
# looking number off almost nothing.
PRIOR_GAMES = 15
# Below this a player's season is too short to say what he "normally" does, so
# he contributes nothing to anyone's expectation.
MIN_PLAYER_GAMES = 2
# Guards against dividing by nothing. A ratio needs a denominator with real
# size in it: expected pass touchdowns for a wide receiver is approximately
# zero, and any actual at all then reads as a 40x matchup. Rushing yards can
# also come out negative for a receiver, which flips the sign of the whole
# thing. Combinations that cannot clear these are simply not published.
MIN_EXPECTED_TOTAL = 6.0
MIN_PLAYER_GAMES_SEEN = 6
# Even past those, a real defensive effect is not a tenfold one. Anything
# outside this band is a thin sample talking, so the published figure is capped
# and the raw value is kept alongside it.
MULT_FLOOR, MULT_CEIL = 0.45, 2.2


def log(*a):
    print(*a, flush=True)


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    with open(os.path.join(DATA, "nfl_index.json"), encoding="utf-8") as f:
        idx = json.load(f)
    season = season or int(idx["current"])
    entry = next((s for s in idx["seasons"] if int(s["season"]) == season), None)
    if entry is None:
        log(f"season {season} not built yet")
        return 1
    with open(os.path.join(DATA, entry["file"]), encoding="utf-8") as f:
        doc = json.load(f)

    meta = {p["id"]: p for p in doc["players"]}
    # One record per player-game: who, what position, which defense, and the
    # row itself so any stat can be read off it later.
    games = []
    for r in doc["rows"]:
        m = meta.get(r["i"])
        if not m or m["p"] not in POSITIONS or not r.get("o"):
            continue
        games.append({"pid": r["i"], "pos": m["p"], "name": m["n"],
                      "tm": r["t"], "opp": r["o"], "wk": r["w"], "row": r})
    log(f"season {season}: {len(games):,} player-games across {len(POSITIONS)} positions")

    by_player = defaultdict(list)
    for g in games:
        by_player[g["pid"]].append(g)

    out = {}
    for stat, fn in STATS.items():
        # mult[defense] for this stat+position, starting neutral
        mult = defaultdict(lambda: 1.0)

        for it in range(ITERATIONS):
            num = defaultdict(float)   # (defense, pos) -> actual
            den = defaultdict(float)   # (defense, pos) -> expected
            cnt = defaultdict(int)
            for g in games:
                mine = by_player[g["pid"]]
                if len(mine) < MIN_PLAYER_GAMES:
                    continue
                others = [o for o in mine if o is not g]
                if not others:
                    continue
                # His own rate from his other games. On later passes each of
                # those games is divided by the multiplier of the defense it
                # was against, so a player is not credited with a big day just
                # for having drawn a soft schedule.
                tot = 0.0
                for o in others:
                    v = fn(o["row"])
                    adj = mult[(o["opp"], g["pos"])] if it else 1.0
                    # A nonsensical adjustment from an earlier pass must not be
                    # allowed to propagate into the next one.
                    if not (MULT_FLOOR <= adj <= MULT_CEIL):
                        adj = 1.0
                    tot += v / adj
                exp = tot / len(others)
                if exp <= 0:
                    continue
                key = (g["opp"], g["pos"])
                num[key] += fn(g["row"])
                den[key] += exp
                cnt[key] += 1
            new = {}
            for key, d in den.items():
                new[key] = (num[key] / d) if d > 0 else 1.0
            mult = defaultdict(lambda: 1.0, new)

        # Final pass: shrink toward 1.0 and keep the per-game breakdown that
        # makes the number checkable rather than something to take on trust.
        per_game = defaultdict(list)
        gnum = defaultdict(float)
        gden = defaultdict(float)
        for g in games:
            mine = by_player[g["pid"]]
            if len(mine) < MIN_PLAYER_GAMES:
                continue
            others = [o for o in mine if o is not g]
            if not others:
                continue
            tot = 0.0
            for o in others:
                adj = mult[(o["opp"], g["pos"])]
                if not (MULT_FLOOR <= adj <= MULT_CEIL):
                    adj = 1.0
                tot += fn(o["row"]) / adj
            exp = tot / len(others)
            if exp <= 0:
                continue
            k = (g["opp"], g["pos"], g["wk"])
            gnum[k] += fn(g["row"])
            gden[k] += exp
            per_game[k].append(g["name"])

        agg_n = defaultdict(float)
        agg_d = defaultdict(float)
        agg_c = defaultdict(int)
        rows = defaultdict(list)
        for (dfs, pos, wk), a in sorted(gnum.items(), key=lambda kv: -kv[0][2]):
            e = gden[(dfs, pos, wk)]
            agg_n[(dfs, pos)] += a
            agg_d[(dfs, pos)] += e
            agg_c[(dfs, pos)] += len(per_game[(dfs, pos, wk)])
            rows[(dfs, pos)].append({
                "wk": wk,
                "tm": next((g["tm"] for g in games
                            if g["opp"] == dfs and g["wk"] == wk), ""),
                "n": len(per_game[(dfs, pos, wk)]),
                "act": round(a, 1),
                "exp": round(e, 1),
            })

        for (dfs, pos), a in agg_n.items():
            e = agg_d[(dfs, pos)]
            n = agg_c[(dfs, pos)]
            # Not enough denominator, or not enough player-games, means there
            # is nothing here worth publishing for this position and stat.
            if e < MIN_EXPECTED_TOTAL or n < MIN_PLAYER_GAMES_SEEN:
                continue
            raw = a / e
            # Shrink toward neutral by player-games seen, then cap.
            shrunk = (n * raw + PRIOR_GAMES * 1.0) / (n + PRIOR_GAMES)
            shrunk = max(MULT_FLOOR, min(MULT_CEIL, shrunk))
            out[f"{dfs}|{pos}|{stat}"] = {
                "mult": round(shrunk, 3),
                "raw": round(raw, 3),
                "n": n,
                "act": round(a, 1),
                "exp": round(e, 1),
                "games": rows[(dfs, pos)],
            }

    built = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"built": built, "season": season, "iterations": ITERATIONS,
               "priorGames": PRIOR_GAMES, "count": len(out), "matchups": out}
    p = os.path.join(DATA, "nfl_matchups.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"\n{len(out):,} defense/position/stat combinations")
    log(f"wrote nfl_matchups.json ({os.path.getsize(p) // 1024} KB)")

    # A quick read on whether the numbers are sane: the extremes, and the
    # spread. Multipliers should mostly sit near 1 with a modest tail.
    vals = sorted(v["mult"] for v in out.values())
    n = len(vals)
    log(f"multiplier spread: min {vals[0]:.2f}  p10 {vals[n // 10]:.2f}  "
        f"median {vals[n // 2]:.2f}  p90 {vals[9 * n // 10]:.2f}  max {vals[-1]:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
