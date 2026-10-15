#!/usr/bin/env python3
"""
fetch_nfl_pbp.py — per player, per game, the individual plays, bucketed by
period. Writes data/nfl_pbp_<season>.json.

WHY THIS FILE EXISTS
The weekly box score (what fetch_nfl.py builds) gives totals for a game. A
total cannot answer three whole families of prop:

  Longest Reception / Rush / Completion   needs the single best play
  1Q and 1H splits                        needs to know WHEN each play happened
  a simulation of any of the above        needs the shape of the distribution,
                                          not just its mean

All three come from the same place, so they are extracted once, together.

THE SHAPE, AND WHY
Per player-week there are three period buckets: first quarter, second quarter,
and everything after half time. From those three:

  1Q market        bucket 0
  1H market        buckets 0 + 1
  full game        all three
  longest anything max across all three
  simulation       the per-play lists ARE the empirical distribution

Storing the plays rather than pre-aggregating is what makes one file serve all
of it. A pre-aggregated 1Q total could not produce a longest, and neither could
produce a distribution.

Each bucket holds lists of yardage, one entry per play, plus counts of the
plays that produced no yardage line of their own:

  ry  [int]  yards on each CATCH          inc   targets not caught
  uy  [int]  yards on each CARRY
  py  [int]  yards on each COMPLETION     pinc  attempts not completed
  lry int    receiving yards taken on a lateral, which carry NO reception
  luy int    rushing yards taken on a lateral, which carry NO carry
  rtd utd ptd int sk                      counts

Receptions is therefore len(ry), targets len(ry) + inc, receiving yards
sum(ry) + lry, and longest reception max(ry). Lateral yards are kept apart
because they count toward a yardage total but are not a reception and cannot be
a longest reception. Nothing is stored twice.

WHAT IS DELIBERATELY EXCLUDED, so this matches the official box score
  season_type != REG     preseason and playoffs are a different population
  play_type == no_play   a penalty wiped the play; no stats were recorded
  two_point_attempt      conversions are counted separately by the NFL and are
                         NOT receptions or rushing yards, so including them
                         would overstate every total by the odd two yards

Verified against the box score by verify_pbp.py, which is the only reason to
trust any of it. Run that after this.
"""
import csv
import datetime
import gzip
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "text/csv, application/json, */*",
}
RETRY_CODES = (403, 429, 500, 502, 503, 504)

# Only the columns actually used. The pbp file carries 372 of them and holding
# all of them for 50,000 rows is a needless few hundred MB of memory.
COLS = (
    "season_type", "week", "qtr", "game_id", "play_type", "two_point_attempt",
    "posteam", "defteam", "complete_pass", "pass_attempt", "rush_attempt",
    "sack", "interception", "passer_player_id", "rusher_player_id",
    "receiver_player_id", "passing_yards", "rushing_yards", "receiving_yards",
    "pass_touchdown", "rush_touchdown", "touchdown", "td_player_id",
    # Laterals. A catch followed by a lateral is ONE reception to the man who
    # caught it, and the yards after the lateral belong to the man who took it.
    # Ignoring these columns loses whole touchdowns: in 2026 week 3 Purdy threw
    # two yards to Evans who lateralled to Samuel for eighty and the score.
    "lateral_receiver_player_id", "lateral_receiving_yards",
    "lateral_rusher_player_id", "lateral_rushing_yards",
)


def log(*a):
    print(*a, flush=True)


def fetch(url, attempts=4, optional=False):
    for k in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if optional:
                    log(f"   not published: {url.rsplit('/', 1)[-1]}")
                    return None
                raise
            if e.code in RETRY_CODES and k < attempts - 1:
                time.sleep(3 * (2 ** k))
                continue
            if optional:
                log(f"   HTTP {e.code}: {url.rsplit('/', 1)[-1]}")
                return None
            raise
        except Exception as e:  # noqa: BLE001
            if k < attempts - 1:
                time.sleep(3 * (2 ** k))
                continue
            if optional:
                log(f"   error: {e}")
                return None
            raise
    return None


def num(v, d=0.0):
    try:
        if v is None or v == "" or v == "NA":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def i(v, d=0):
    return int(round(num(v, d)))


def flag(v):
    """pbp booleans arrive as 1/0, but also as TRUE/FALSE in some columns and
    as an empty string on plays where the concept does not apply. Anything that
    is not positively true is false."""
    s = str(v).strip().upper()
    return s in ("1", "1.0", "TRUE", "T", "YES")


def bucket(qtr):
    """Period index: 0 first quarter, 1 second quarter, 2 after half time.

    Overtime lands in bucket 2 with the second half. No prop is written on
    "second half" alone, so the only thing bucket 2 does is complete the
    full-game total, and overtime counts toward a full-game total."""
    return 0 if qtr == 1 else (1 if qtr == 2 else 2)


def new_period():
    return {"ry": [], "uy": [], "py": [], "inc": 0, "pinc": 0, "lry": 0,
            "luy": 0, "rtd": 0, "utd": 0, "ptd": 0, "int": 0, "sk": 0}


def build(season):
    log(f"\n=== {season} play by play")
    blob = fetch(f"{NFLVERSE}/pbp/play_by_play_{season}.csv", optional=True)
    if blob is None:
        return None
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    log(f"   {len(blob) // (1024 * 1024)} MB")

    rd = csv.DictReader(io.StringIO(blob.decode("utf-8", "replace")))
    missing = [c for c in COLS if c not in (rd.fieldnames or [])]
    if missing:
        raise SystemExit(f"pbp {season} is missing columns: {missing}")

    # (pid, week) -> [period, period, period]
    logs = defaultdict(lambda: [new_period(), new_period(), new_period()])
    weeks = set()
    # Game-level TD order, for the first and last scorer props.
    tds = defaultdict(list)   # game_id -> [pid, ...] in play order
    gid_week = {}             # game_id -> week
    teams = {}                # (pid, week) -> team, for sanity reporting
    kept = skipped = 0

    for row in rd:
        if row.get("season_type") != "REG":
            continue
        pt = row.get("play_type") or ""
        # A penalty-wiped play recorded no statistics. Including it is the
        # classic way a reconstruction drifts above the box score.
        if pt == "no_play":
            skipped += 1
            continue
        if flag(row.get("two_point_attempt")):
            skipped += 1
            continue

        wk = i(row.get("week"))
        if not wk:
            continue
        b = bucket(i(row.get("qtr")))
        gid = row.get("game_id") or ""
        posteam = row.get("posteam") or ""
        if gid:
            gid_week[gid] = wk

        # Touchdown order, for first/last scorer. Taken from td_player_id so
        # that a defensive or special teams score is attributed to whoever
        # actually scored it: those count for "first touchdown scorer" and
        # leaving them out would overstate every offensive player's rate.
        scorer = row.get("td_player_id") or ""
        if flag(row.get("touchdown")) and scorer:
            tds[gid].append(scorer)

        lat_rec = row.get("lateral_receiver_player_id") or ""
        lat_ru = row.get("lateral_rusher_player_id") or ""
        did = False

        # ---- passing side
        if pt == "pass" or flag(row.get("pass_attempt")):
            qb = row.get("passer_player_id") or ""
            rec = row.get("receiver_player_id") or ""
            sack = flag(row.get("sack"))
            comp = flag(row.get("complete_pass"))
            if qb:
                p = logs[(qb, wk)][b]
                if sack:
                    # A sack is not a pass attempt in the box score. It is
                    # counted on its own so the simulation can price the risk
                    # of one without inflating attempts.
                    p["sk"] += 1
                elif comp:
                    p["py"].append(i(row.get("passing_yards")))
                    if flag(row.get("pass_touchdown")):
                        # The passer is credited the passing touchdown however
                        # the ball reached the end zone, including by lateral.
                        p["ptd"] += 1
                else:
                    p["pinc"] += 1
                    if flag(row.get("interception")):
                        p["int"] += 1
                teams[(qb, wk)] = posteam
                did = True
            if rec and not sack:
                p = logs[(rec, wk)][b]
                if comp:
                    p["ry"].append(i(row.get("receiving_yards")))
                    # Credited to whoever actually crossed the line, which on a
                    # lateral is not the man who caught it.
                    if flag(row.get("pass_touchdown")) and (
                            scorer == rec or not scorer):
                        p["rtd"] += 1
                else:
                    # An incomplete pass is still a target, which is what the
                    # Targets market and the simulation's volume both key off.
                    p["inc"] += 1
                teams[(rec, wk)] = posteam
                did = True
            if lat_rec and comp and not sack:
                p = logs[(lat_rec, wk)][b]
                p["lry"] += i(row.get("lateral_receiving_yards"))
                if flag(row.get("pass_touchdown")) and scorer == lat_rec:
                    p["rtd"] += 1
                teams[(lat_rec, wk)] = posteam
                did = True

        # ---- rushing side
        if pt == "run" or flag(row.get("rush_attempt")):
            ru = row.get("rusher_player_id") or ""
            if ru:
                p = logs[(ru, wk)][b]
                p["uy"].append(i(row.get("rushing_yards")))
                if flag(row.get("rush_touchdown")) and (
                        scorer == ru or not scorer):
                    p["utd"] += 1
                teams[(ru, wk)] = posteam
                did = True
            if lat_ru:
                p = logs[(lat_ru, wk)][b]
                p["luy"] += i(row.get("lateral_rushing_yards"))
                if flag(row.get("rush_touchdown")) and scorer == lat_ru:
                    p["utd"] += 1
                teams[(lat_ru, wk)] = posteam
                did = True

        if did:
            kept += 1
            weeks.add(wk)

    log(f"   {kept:,} plays with a statistic, {skipped:,} skipped "
        f"(penalties and two point conversions)")

    # First and last touchdown of each game, flattened to a per player-week
    # flag because that is how every other statistic here is keyed.
    #
    # Defensive and special teams scores are included in the ordering. That is
    # deliberate: when a pick six opens the scoring, no offensive player was
    # the first scorer, and pretending otherwise would lift every receiver's
    # rate on a market that is already a long shot.
    ftd = set()
    ltd = set()
    for gid, seq in tds.items():
        wk = gid_week.get(gid)
        if wk is None or not seq:
            continue
        ftd.add((seq[0], wk))
        ltd.add((seq[-1], wk))
    log(f"   {len(tds):,} games with touchdowns scored")

    # Flatten, dropping empty periods so the file is not three quarters of
    # zeros. An absent period means the player recorded nothing in it.
    out = []
    for (pid, wk), periods in logs.items():
        rec = {"i": pid, "w": wk}
        any_play = False
        for k, p in enumerate(periods):
            trimmed = {kk: vv for kk, vv in p.items() if vv not in (0, [], None)}
            if trimmed:
                rec[f"p{k}"] = trimmed
                any_play = True
        if (pid, wk) in ftd:
            rec["ftd"] = 1
        if (pid, wk) in ltd:
            rec["ltd"] = 1
        if any_play:
            out.append(rec)
    out.sort(key=lambda r: (r["i"], r["w"]))

    return {
        "built": datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": season,
        "weeks": sorted(weeks),
        "players": len({r["i"] for r in out}),
        "logs": out,
    }


def main():
    argv = sys.argv[1:]
    if argv:
        seasons = [int(a) for a in argv]
    else:
        idx_path = os.path.join(DATA, "nfl_index.json")
        if not os.path.exists(idx_path):
            raise SystemExit("no nfl_index.json; run fetch_nfl.py first")
        with open(idx_path, encoding="utf-8") as f:
            idx = json.load(f)
        seasons = sorted((int(s["season"]) for s in idx["seasons"]), reverse=True)

    log(f"seasons: {seasons}")
    wrote = 0
    for s in seasons:
        doc = build(s)
        if doc is None:
            log(f"   {s}: no play by play published, skipping")
            continue
        path = os.path.join(DATA, f"nfl_pbp_{s}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, separators=(",", ":"))
        log(f"   wrote nfl_pbp_{s}.json: {len(doc['logs']):,} player-weeks, "
            f"{doc['players']:,} players, {os.path.getsize(path) // 1024} KB")
        wrote += 1

    if not wrote:
        log("\nnothing written")
        return 1
    log(f"\n{wrote} season file(s) written. Run verify_pbp.py next.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
