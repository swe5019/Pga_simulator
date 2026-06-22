#!/usr/bin/env python3
"""
fetch_dk.py — pull a DraftKings contest's golf player pool (names + salaries)
and write rows that match the master "Data" tab's leading columns:

    Tournament_Name, Date, Name, Salary

Env inputs:
    DK_CONTEST_ID   (required)  e.g. 5173013489
    DK_TOURNAMENT   (required)  e.g. TRAVELERS_2026
    DK_DATE         (required)  e.g. 6/25/26
    DK_OUT          (optional)  output CSV path (default data/dk_salaries.csv)

DraftKings exposes these without auth:
    contests/v1/contests/{id}                  -> draftGroupId
    draftgroups/v1/draftgroups/{dg}/draftables -> player pool
"""
import csv
import json
import os
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; birdie-dfs/1.0)"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def find_key(obj, key):
    """Depth-first search for the first value of `key` anywhere in nested JSON."""
    if isinstance(obj, dict):
        if key in obj and obj[key] not in (None, ""):
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key)
            if found is not None:
                return found
    return None


def main():
    contest = os.environ.get("DK_CONTEST_ID", "").strip()
    tourney = os.environ.get("DK_TOURNAMENT", "").strip()
    date = os.environ.get("DK_DATE", "").strip()
    out = os.environ.get("DK_OUT", "data/dk_salaries.csv").strip()
    if not (contest and tourney and date):
        raise SystemExit("DK_CONTEST_ID, DK_TOURNAMENT and DK_DATE are all required")

    cdata = get_json(f"https://api.draftkings.com/contests/v1/contests/{contest}?format=json")
    dg = find_key(cdata, "draftGroupId")
    if not dg:
        raise SystemExit(f"Could not find draftGroupId for contest {contest}")
    print(f"Contest {contest} -> draftGroupId {dg}")

    ddata = get_json(
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables?format=json"
    )
    draftables = ddata.get("draftables", [])

    seen = {}
    for p in draftables:
        name = (p.get("displayName") or "").strip()
        salary = p.get("salary")
        if not name or salary is None:
            continue
        if name not in seen:  # players can appear multiple times; keep first
            seen[name] = int(salary)

    if not seen:
        raise SystemExit("No players parsed from draftables — aborting.")

    rows = sorted(seen.items(), key=lambda kv: -kv[1])  # high salary first
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Tournament_Name", "Date", "Name", "Salary"])
        for name, salary in rows:
            w.writerow([tourney, date, name, salary])

    print(f"Wrote {out}: {len(rows)} golfers for {tourney} ({date})")
    print("Top 5:")
    for name, salary in rows[:5]:
        print(f"  {name}: {salary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
