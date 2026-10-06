#!/usr/bin/env python3
"""
verify_nfl.py — recompute every NFL column from the raw nflverse files and
compare it against data/nfl_<season>.json.

This exists because a wrong number here looks exactly like a right one. Snap
share shipped 17% low for a week and read as entirely plausible: DK Metcalf at
82% when he had not been below 95% all season. Nothing caught it but a user.

Two rules keep this honest:
  1. It does NOT import fetch_nfl. It re-derives everything from the source
     CSVs, so a bug in the fetcher cannot reproduce itself in the check.
  2. It replicates the BROWSER's aggregation, not the fetcher's, because what
     the page shows is what matters. If the two ever disagree, that is the bug.

Exit code is non-zero on any mismatch, so the workflow can refuse to commit.

Usage:  python tools/verify_nfl.py [season]
"""
import collections
import csv
import gzip
import io
import json
import os
import sys
import urllib.request

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
FFOPP = "https://github.com/ffverse/ffopportunity/releases/download/latest-data"
UA = {"User-Agent": "slatesims-verify"}

# Per-metric tolerance. Most are compared at 1% relative, but a few need an
# absolute floor because they sit near zero and a relative test is meaningless.
TOL = {"g": 0, "snap": 0.6, "cpoe": 0.05, "epa": 0.005, "ryoe": 0.02,
       "yacoe": 0.02, "sep": 0.02, "ttt": 0.02, "iay": 0.02,
       "ppr": 0.02, "hppr": 0.02, "fpoe": 0.03}
# Columns the page only renders for certain positions.
ONLY = {"cmp_c": ("QB",), "att_c": ("QB",), "py_c": ("QB",), "ptd_c": ("QB",),
        "int_c": ("QB",), "sk_c": ("QB",), "cmppct": ("QB",),
        "rush": ("QB",), "dbpg": ("QB",), "ypg": ("QB",), "cpoe": ("QB",),
        "epa": ("QB",), "adot_qb": ("QB",), "ttt": ("QB",), "iay": ("QB",),
        "ryoe": ("RB", "QB"), "carsh": ("RB", "QB"), "ypc": ("RB", "QB"),
        "rzc": ("RB", "QB"), "glc": ("RB", "QB")}


def log(*a):
    print(*a, flush=True)


def fetch_rows(url, optional=False):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r:
            blob = r.read()
    except Exception as e:  # noqa: BLE001
        if optional:
            log(f"   (skipping {url.rsplit('/', 1)[-1]}: {e})")
            return []
        raise
    if url.endswith(".gz"):
        blob = gzip.decompress(blob)
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8", "replace"))))


def f(v, d=0.0):
    try:
        return float(v) if v not in (None, "", "NA") else d
    except (TypeError, ValueError):
        return d


def I(v):
    return int(round(f(v)))


def ppr(r):
    """Standard PPR off the box score. Written out again rather than imported,
    so a change to the fetcher's scoring cannot silently pass this check."""
    return (0.04 * f(r["passing_yards"]) + 4 * f(r["passing_tds"])
            - 2 * f(r["passing_interceptions"])
            + 0.1 * f(r["rushing_yards"]) + 6 * f(r["rushing_tds"])
            + 0.1 * f(r["receiving_yards"]) + 6 * f(r["receiving_tds"])
            + 1 * f(r["receptions"]) + 6 * f(r["special_teams_tds"])
            + 2 * (f(r["passing_2pt_conversions"]) + f(r["rushing_2pt_conversions"])
                   + f(r["receiving_2pt_conversions"]))
            - 2 * (f(r["sack_fumbles_lost"]) + f(r["rushing_fumbles_lost"])
                   + f(r["receiving_fumbles_lost"])))


def nrm(s):
    import re
    s = (s or "").lower()
    s = re.sub(r"[.'`,]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z]+", "", s)


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if season is None:
        import datetime
        now = datetime.date.today()
        season = now.year if now.month >= 8 else now.year - 1

    path = os.path.join(ROOT, "data", f"nfl_{season}.json")
    if not os.path.exists(path):
        log(f"no {path} to verify")
        return 0
    with open(path, encoding="utf-8") as fh:
        app = json.load(fh)
    log(f"verifying {os.path.basename(path)} — {len(app['rows'])} player-weeks")

    log("fetching sources independently...")
    spw = [r for r in fetch_rows(f"{NFLVERSE}/stats_player/stats_player_week_{season}.csv")
           if r.get("season_type") == "REG"]
    pbp = [r for r in fetch_rows(f"{NFLVERSE}/pbp/play_by_play_{season}.csv")
           if r.get("season_type") == "REG"]
    snaps = [r for r in fetch_rows(f"{NFLVERSE}/snap_counts/snap_counts_{season}.csv")
             if r.get("game_type") == "REG"]
    ep = {(r["player_id"], I(r.get("week"))): r
          for r in fetch_rows(f"{FFOPP}/ep_weekly_{season}.csv", optional=True)}
    ngs = {}
    for kind, fn in (("rec", "ngs_receiving"), ("pass", "ngs_passing"), ("rush", "ngs_rushing")):
        ngs[kind] = [r for r in fetch_rows(f"{NFLVERSE}/nextgen_stats/{fn}.csv.gz", optional=True)
                     if I(r.get("season")) == season and r.get("season_type") == "REG"]

    box = {(r["player_id"], I(r["week"])): r for r in spw}

    # team denominators, straight off pbp
    tt = collections.defaultdict(lambda: collections.defaultdict(float))
    rz = collections.Counter(); rzc = collections.Counter(); glc = collections.Counter()
    qra = collections.Counter()
    for r in pbp:
        wk, pt = I(r["week"]), r.get("posteam") or ""
        ptype = (r.get("play_type") or "").lower()
        y = f(r.get("yardline_100"), 999)
        if pt:
            k = (pt, wk)
            if ptype == "pass" and r.get("receiver_player_id"):
                tt[k]["tg"] += 1
                tt[k]["ay"] += f(r.get("air_yards"))
            if ptype == "run" and r.get("rusher_player_id") and r.get("qb_scramble") != "1":
                tt[k]["ca"] += 1
            if ptype in ("pass", "run"):
                tt[k]["plays"] += 1
        if ptype == "pass" and r.get("receiver_player_id") and y <= 20:
            rz[(r["receiver_player_id"], wk)] += 1
        if ptype == "run" and r.get("rusher_player_id") and r.get("qb_scramble") != "1":
            if y <= 20:
                rzc[(r["rusher_player_id"], wk)] += 1
            if y <= 5:
                glc[(r["rusher_player_id"], wk)] += 1
        if r.get("rusher_player_id") and (ptype == "run" or r.get("qb_scramble") == "1"):
            qra[(r["rusher_player_id"], wk)] += 1

    # team snaps, from the busiest player (smallest rounding error on offense_pct)
    best, most = {}, collections.defaultdict(int)
    snapidx = {}
    for r in snaps:
        wk, tm = I(r["week"]), (r.get("team") or "").upper()
        sn, pct = I(r.get("offense_snaps")), f(r.get("offense_pct"))
        if sn <= 0 or not tm:
            continue
        snapidx[(nrm(r.get("player")), wk, tm)] = sn
        most[(tm, wk)] = max(most[(tm, wk)], sn)
        if pct > 0 and sn > best.get((tm, wk), (0, 0))[0]:
            best[(tm, wk)] = (sn, round(sn / pct))
    teamsnap = {k: max(v, best.get(k, (0, 0))[1]) for k, v in most.items()}

    meta = {p["id"]: p for p in app["players"]}
    arows = collections.defaultdict(dict)
    for r in app["rows"]:
        arows[r["i"]][r["w"]] = r
    name = {p["id"]: p["n"] for p in app["players"]}

    def snapof(pid, w):
        b = box.get((pid, w))
        return snapidx.get((nrm(name.get(pid, "")), w, (b or {}).get("team", "")), 0)

    def app_agg(pid, lo, hi):
        """Mirror of agg() in assets/js/nfl.js."""
        rs = [r for w, r in arows[pid].items() if lo <= w <= hi]
        if not rs:
            return None
        S = lambda k: sum(r.get(k, 0) for r in rs)  # noqa: E731
        T = lambda k: sum(app["teams"].get(f"{r['t']}|{r['w']}", {}).get(k, 0) for r in rs)  # noqa: E731
        g, tg, ay, att, sk = len(rs), S("tg"), S("ay"), S("att"), S("sk")

        def wm(key, wkey):
            n = d = 0.0
            for r in rs:
                if r.get(key) is None or not r.get(wkey):
                    continue
                n += r[key] * r[wkey]
                d += r[wkey]
            return n / d if d else None

        def fpoe_of(rr):
            a = x = 0.0
            c = 0
            for r in rr:
                if r.get("xfp") is None:
                    continue
                a += r.get("fp", 0) - 0.5 * r.get("rec", 0)
                x += r["xfp"] - 0.5 * r.get("xrec", 0)
                c += 1
            return (a - x) / c if c else None
        tgtsh = tg / T("tg") if T("tg") else None
        airsh = ay / T("ay") if T("ay") else None
        return {
            "g": g,
            "snap": S("sn") / T("sn") * 100 if T("sn") else None,
            "tgtsh": tgtsh * 100 if tgtsh is not None else None,
            "airsh": airsh * 100 if airsh is not None else None,
            "adot_rec": ay / tg if tg else None,
            "adot_qb": S("pay") / att if att else None,
            "wopr": 1.5 * tgtsh + 0.7 * airsh if None not in (tgtsh, airsh) else None,
            "rz": S("rz") / g, "rzc": S("rzc") / g, "glc": S("glc") / g,
            "carsh": S("ca") / T("ca") * 100 if T("ca") else None,
            "ypc": S("ru") / S("ca") if S("ca") else None,
            "tgpg": tg / g, "dbpg": (att + sk) / g, "ypg": S("py") / g,
            "cpoe": S("cpoeN") / att if att else None,
            "epa": S("pepa") / (att + sk) if (att + sk) else None,
            "rush": S("qra") / g,
            "sep": wm("sep", "tg"), "yacoe": wm("yacoe", "rec"),
            "ttt": wm("ttt", "att"), "iay": wm("iay", "att"), "ryoe": wm("ryoe", "ca"),
            "tg_c": S("tg"), "rec_c": S("rec"), "ry_c": S("ry"), "rtd_c": S("rtd"),
            "ca_c": S("ca"), "ru_c": S("ru"), "utd_c": S("utd"), "cmp_c": S("cmp"),
            "att_c": S("att"), "py_c": S("py"), "ptd_c": S("ptd"), "int_c": S("int"),
            "sk_c": S("sk"), "fl_c": S("fl"),
            "td_c": S("rtd") + S("utd") + S("ptd"),
            "ypr": S("ry") / S("rec") if S("rec") else None,
            "catch": S("rec") / S("tg") * 100 if S("tg") else None,
            "cmppct": S("cmp") / S("att") * 100 if S("att") else None,
            "ppr": S("fp") / g,
            "hppr": (S("fp") - 0.5 * S("rec")) / g,
            "fpoe": fpoe_of(rs),
        }

    def tfpoe(pid, wks):
        """Actual half PPR minus expected half PPR, over only the weeks the
        model priced. Expected receptions are worth a full point in their
        scoring, so half PPR comes off both sides exactly."""
        a = x = 0.0
        c = 0
        for w in wks:
            e = ep.get((pid, w))
            if not e or e.get("total_fantasy_points_exp") in (None, "", "NA"):
                continue
            b = box[(pid, w)]
            a += ppr(b) - 0.5 * f(b["receptions"])
            x += round(f(e["total_fantasy_points_exp"]), 2) - 0.5 * round(f(e["receptions_exp"]), 2)
            c += 1
        return (a - x) / c if c else None

    def truth(pid, lo, hi):
        wks = [w for w in range(lo, hi + 1) if (pid, w) in box]
        wks = [w for w in wks
               if I(box[(pid, w)]["targets"]) or I(box[(pid, w)]["carries"])
               or I(box[(pid, w)]["attempts"]) or snapof(pid, w)]
        if not wks:
            return None
        g = len(wks)
        B = lambda k: sum(f(box[(pid, w)][k]) for w in wks)  # noqa: E731
        tms = [(box[(pid, w)]["team"], w) for w in wks]
        TT = lambda k: sum(tt[t].get(k, 0) for t in tms)  # noqa: E731
        tg, ay, att, sk = B("targets"), B("receiving_air_yards"), B("attempts"), B("sacks_suffered")
        sd = sum(teamsnap.get(t, 0) for t in tms)
        tgtsh = tg / TT("tg") if TT("tg") else None
        airsh = ay / TT("ay") if TT("ay") else None

        def ngwm(kind, key, wkey):
            n = d = 0.0
            for r in ngs[kind]:
                if r.get("player_gsis_id") != pid:
                    continue
                w = I(r.get("week"))
                if w not in wks or r.get(key) in (None, "", "NA"):
                    continue
                wt = f(box[(pid, w)][wkey])
                if wt > 0:
                    n += round(f(r[key]), 3) * wt
                    d += wt
            return n / d if d else None
        return {
            "g": g,
            "snap": sum(snapof(pid, w) for w in wks) / sd * 100 if sd else None,
            "tgtsh": tgtsh * 100 if tgtsh is not None else None,
            "airsh": airsh * 100 if airsh is not None else None,
            "adot_rec": ay / tg if tg else None,
            "adot_qb": B("passing_air_yards") / att if att else None,
            "wopr": 1.5 * tgtsh + 0.7 * airsh if None not in (tgtsh, airsh) else None,
            "rz": sum(rz[(pid, w)] for w in wks) / g,
            "rzc": sum(rzc[(pid, w)] for w in wks) / g,
            "glc": sum(glc[(pid, w)] for w in wks) / g,
            "carsh": B("carries") / TT("ca") * 100 if TT("ca") else None,
            "ypc": B("rushing_yards") / B("carries") if B("carries") else None,
            "tgpg": tg / g, "dbpg": (att + sk) / g, "ypg": B("passing_yards") / g,
            "cpoe": sum(f(box[(pid, w)]["passing_cpoe"]) * f(box[(pid, w)]["attempts"])
                        for w in wks) / att if att else None,
            "epa": B("passing_epa") / (att + sk) if (att + sk) else None,
            "rush": sum(qra[(pid, w)] for w in wks) / g,
            "sep": ngwm("rec", "avg_separation", "targets"),
            "yacoe": ngwm("rec", "avg_yac_above_expectation", "receptions"),
            "ttt": ngwm("pass", "avg_time_to_throw", "attempts"),
            "iay": ngwm("pass", "avg_intended_air_yards", "attempts"),
            "ryoe": ngwm("rush", "rush_yards_over_expected_per_att", "carries"),
            "tg_c": B("targets"), "rec_c": B("receptions"), "ry_c": B("receiving_yards"),
            "rtd_c": B("receiving_tds"), "ca_c": B("carries"), "ru_c": B("rushing_yards"),
            "utd_c": B("rushing_tds"), "cmp_c": B("completions"), "att_c": B("attempts"),
            "py_c": B("passing_yards"), "ptd_c": B("passing_tds"),
            "int_c": B("passing_interceptions"), "sk_c": B("sacks_suffered"),
            "fl_c": (B("sack_fumbles_lost") + B("rushing_fumbles_lost")
                     + B("receiving_fumbles_lost")),
            "td_c": B("receiving_tds") + B("rushing_tds") + B("passing_tds"),
            "ypr": B("receiving_yards") / B("receptions") if B("receptions") else None,
            "catch": B("receptions") / B("targets") * 100 if B("targets") else None,
            "cmppct": B("completions") / B("attempts") * 100 if B("attempts") else None,
            "ppr": sum(ppr(box[(pid, w)]) for w in wks) / g,
            "hppr": sum(ppr(box[(pid, w)]) - 0.5 * f(box[(pid, w)]["receptions"])
                        for w in wks) / g,
            "fpoe": tfpoe(pid, wks),
        }

    fields = ["g", "snap", "tgtsh", "airsh", "adot_rec", "adot_qb", "wopr", "rz",
              "rzc", "glc", "carsh", "ypc", "tgpg", "dbpg", "ypg", "cpoe", "epa",
              "rush", "sep", "yacoe", "ttt", "iay", "ryoe", "ppr", "hppr", "fpoe",
              "tg_c", "rec_c", "ry_c", "rtd_c", "ca_c", "ru_c", "utd_c", "cmp_c",
              "att_c", "py_c", "ptd_c", "int_c", "sk_c", "fl_c", "td_c",
              "ypr", "catch", "cmppct"]
    weeks = app["weeks"]
    lo, hi = weeks[0], weeks[-1]
    # Full season, a trailing window, and a single week: the three shapes the
    # page offers, since a bug can hide in one and not the others.
    windows = [(lo, hi, "full season"), (max(lo, hi - 2), hi, "last 3"), (hi, hi, "latest week")]

    failures = 0
    for a_lo, a_hi, label in windows:
        bad = collections.Counter(); seen = collections.Counter(); ex = {}
        for pid, m in meta.items():
            a, t = app_agg(pid, a_lo, a_hi), truth(pid, a_lo, a_hi)
            if not a or not t:
                continue
            for k in fields:
                if k in ONLY and m["p"] not in ONLY[k]:
                    continue
                av, tv = a.get(k), t.get(k)
                if av is None and tv is None:
                    continue
                if av is None or tv is None:
                    if (av or 0) or (tv or 0):
                        bad[k] += 1
                        ex.setdefault(k, []).append((m["n"], av, tv))
                    continue
                seen[k] += 1
                if abs(av - tv) > TOL.get(k, max(0.02, abs(tv) * 0.01)):
                    bad[k] += 1
                    ex.setdefault(k, []).append((m["n"], round(av, 3), round(tv, 3)))
        n_bad = sum(bad.values())
        failures += n_bad
        log(f"\n  {label} (weeks {a_lo}-{a_hi}): {sum(seen.values())} values checked, {n_bad} mismatched")
        for k in fields:
            if bad[k]:
                log(f"    FAIL {k:<10} {bad[k]} of {seen[k]}")
                for e in ex[k][:3]:
                    log(f"           {e[0]:<24} app={e[1]}  source={e[2]}")

    if failures:
        log(f"\n{failures} mismatches — data/nfl_{season}.json does NOT match its sources")
        return 1
    log(f"\nall columns match the sources for {season}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
