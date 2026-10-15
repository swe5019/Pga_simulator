#!/usr/bin/env python3
"""
fetch_nfl_injuries.py — who is not playing this week. Writes data/nfl_injuries.json.

WHY THIS IS THE MOST VALUABLE FEED ON THE SITE
Everything else here is built from games already played, which makes the whole
pipeline blind to the one thing that moves a prop line most: somebody ahead of
a player being ruled out. The market knows within minutes. This model did not
know at all, so it kept projecting a backup's workload against a starter's line
and reporting the biggest edge on the board for it.

WHAT THE SOURCE ACTUALLY GIVES
nflverse publishes the weekly injury report, and it carries two separate
columns that say different things:

  report_status     the official game designation: Out, Doubtful, Questionable.
                    Authoritative, but filed late in the week. Early on it is
                    blank for nearly everybody.
  practice_status   whether he practised: "Did Not Participate In Practice",
                    "Limited Participation In Practice", "Full Participation".
                    Available from Wednesday.

So early in the week the only signal is practice, and a starter who has not
practised at all is the single most useful fact available. Both are kept, and
each player carries WHICH of the two the conclusion rests on, so the page can
say "ruled out" when that is true and "has not practised" when that is all
anybody knows. Treating a Wednesday non-practice as a ruling would be
overclaiming; ignoring it would throw away the only early warning there is.

WHAT IS DELIBERATELY NOT DECIDED HERE
This file does not touch roles or projections. It records who is unavailable
and how confident that is. What to do about it belongs with the code that
knows about roles, and keeping the two apart means a wrong call about a
player's status cannot quietly become a wrong projection with no trace.
"""
import datetime
import io
import json
import os
import sys
import urllib.error
import urllib.request
import csv
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "text/csv, */*",
}

POSITIONS = ("QB", "RB", "WR", "TE")

# Official designations, worst first. Doubtful is treated as out because it
# means about a one in four chance of playing and nobody builds around that.
OUT_STATUS = ("Out", "Doubtful")
# Practice language that means he did not practise at all.
DNP = "did not participate"
LIMITED = "limited"


def log(*a):
    print(*a, flush=True)


def fetch(url, optional=False):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if optional:
            log(f"   HTTP {e.code} for {url.rsplit('/', 1)[-1]}")
            return None
        raise
    except Exception as e:  # noqa: BLE001
        if optional:
            log(f"   error: {e}")
            return None
        raise


def classify(report, practice):
    """Is he unavailable, how sure is that, and what is it based on.

    Returns (status, confidence, basis) where status is "out", "doubt" or
    "ok". The basis matters as much as the status: "Out" on the official
    report is a fact, while a Wednesday non-practice is a hint, and a page
    that presents them the same way is lying to its reader."""
    rep = (report or "").strip()
    pra = (practice or "").strip().lower()
    if rep in OUT_STATUS:
        return "out", "ruled", f"officially {rep.lower()}"
    if rep == "Questionable":
        # Questionable plus no practice all week is a different animal from
        # questionable after full practice.
        if DNP in pra:
            return "doubt", "strong", "questionable and has not practised"
        return "doubt", "weak", "questionable"
    if DNP in pra:
        return "doubt", "strong", "has not practised this week"
    if LIMITED in pra:
        return "doubt", "weak", "limited in practice"
    return "ok", "", ""


def main():
    season = int(sys.argv[1]) if len(sys.argv) > 1 else None
    if season is None:
        idx_path = os.path.join(DATA, "nfl_index.json")
        if not os.path.exists(idx_path):
            raise SystemExit("no nfl_index.json; run fetch_nfl.py first")
        with open(idx_path, encoding="utf-8") as f:
            season = int(json.load(f)["current"])

    log(f"injury report for {season}")
    blob = fetch(f"{NFLVERSE}/injuries/injuries_{season}.csv", optional=True)
    if blob is None:
        log("   not published; leaving the existing file alone")
        return 1
    rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8", "replace"))))
    rows = [r for r in rows if (r.get("season_type") or "REG") == "REG"]
    if not rows:
        log("   no regular season rows")
        return 1

    weeks = sorted({int(r["week"]) for r in rows if r.get("week")})
    week = weeks[-1]
    log(f"   weeks published: {weeks}, using week {week}")

    out = []
    counts = defaultdict(int)
    for r in rows:
        if int(r.get("week") or 0) != week:
            continue
        pos = (r.get("position") or "").upper()
        status, conf, basis = classify(r.get("report_status"),
                                       r.get("practice_status"))
        if status == "ok":
            continue
        out.append({
            "id": r.get("gsis_id") or "",
            "n": r.get("full_name") or "",
            "t": r.get("team") or "",
            "p": pos,
            "status": status,
            "conf": conf,
            "basis": basis,
            "injury": (r.get("report_primary_injury")
                       or r.get("practice_primary_injury") or ""),
        })
        counts[f"{status}/{conf}"] += 1

    skill = [p for p in out if p["p"] in POSITIONS]
    log(f"   {len(out)} players carrying something, {len(skill)} of them at "
        f"{'/'.join(POSITIONS)}")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        log(f"      {v:>4}  {k}")

    ruled = [p for p in skill if p["conf"] == "ruled"]
    strong = [p for p in skill if p["conf"] == "strong"]
    if ruled:
        log(f"\n   ruled out or doubtful:")
        for p in sorted(ruled, key=lambda x: (x["t"], x["p"])):
            log(f"      {p['t']:<4} {p['p']:<3} {p['n']:<24} {p['basis']}"
                + (f" ({p['injury']})" if p["injury"] else ""))
    if strong:
        log(f"\n   has not practised (no official ruling yet):")
        for p in sorted(strong, key=lambda x: (x["t"], x["p"]))[:25]:
            log(f"      {p['t']:<4} {p['p']:<3} {p['n']:<24} {p['basis']}"
                + (f" ({p['injury']})" if p["injury"] else ""))

    payload = {
        "built": datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": season,
        "week": week,
        "count": len(out),
        "players": out,
    }
    path = os.path.join(DATA, "nfl_injuries.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"\nwrote nfl_injuries.json ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
