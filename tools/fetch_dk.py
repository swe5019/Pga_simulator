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


def get_json(url, optional=False):
    print(f"GET {url}")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        print(f"  -> HTTP {e.code} {body}")
        if optional:
            return None
        raise


def resolve_draft_group(contest, keyword=""):
    """Find the draftGroupId via: explicit contest id, then a keyword name match
    in the public GOLF lobby (salaries live at the draft-group level)."""
    if contest:
        cdata = get_json(
            f"https://api.draftkings.com/contests/v1/contests/{contest}?format=json",
            optional=True,
        )
        dg = find_key(cdata, "draftGroupId") if cdata else None
        if dg:
            return dg

    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF", optional=True)
    if not lobby:
        return None
    contests = lobby.get("Contests", [])

    if contest:
        for c in contests:
            if str(c.get("id")) == str(contest):
                return c.get("dg") or c.get("draftGroupId")
        print(f"  contest {contest} not found among {len(contests)} open GOLF contests")

    if not keyword:
        return None

    # Group open contests by draft group, keep those whose name matches the keyword.
    kw = keyword.lower()
    groups = {}
    for c in contests:
        name = (c.get("n") or "")
        dg = c.get("dg") or c.get("draftGroupId")
        if dg and kw in name.lower():
            g = groups.setdefault(dg, {"example": name, "start": c.get("sdstring") or c.get("sd"), "count": 0})
            g["count"] += 1

    if not groups:
        print(f"  no open GOLF contests matched '{keyword}'")
        return None
    print(f"Draft groups matching '{keyword}':")
    for dg, g in sorted(groups.items(), key=lambda kv: -kv[1]["count"]):
        print(f"  dg={dg}  start={g['start']}  contests={g['count']}  e.g. {g['example']}")
    if len(groups) == 1:
        return next(iter(groups))
    # Pick the draft group backing the most contests (usually the main slate).
    best = max(groups.items(), key=lambda kv: kv[1]["count"])[0]
    print(f"Multiple matches — choosing the most-used draft group: {best}")
    return best


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


def list_groups():
    """Print the open GOLF draft groups (id + start) and the event name read
    from each group's first draftable, so we can identify the right slate."""
    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF", optional=True) or {}
    dgs = lobby.get("DraftGroups", [])
    print(f"{len(dgs)} GOLF draft groups open:")
    for d in sorted(dgs, key=lambda x: str(x.get("StartDate") or x.get("StartDateEst") or "")):
        dg = d.get("DraftGroupId")
        start = d.get("StartDate") or d.get("StartDateEst")
        suffix = d.get("ContestStartTimeSuffix") or ""
        gt = d.get("GameTypeId")
        event = ""
        dd = get_json(
            f"https://api.draftkings.com/draftgroups/v1/draftgroups/{dg}/draftables?format=json",
            optional=True,
        )
        if dd:
            comp = find_key(dd, "competition") or {}
            event = comp.get("name") or comp.get("nameDisplay") or ""
        print(f"  dg={dg} start={start}{suffix} gameType={gt} event={event!r}")


def main():
    if os.environ.get("DK_LIST", "").strip():
        list_groups()
        return 0
    contest = os.environ.get("DK_CONTEST_ID", "").strip()
    tourney = os.environ.get("DK_TOURNAMENT", "").strip()
    date = os.environ.get("DK_DATE", "").strip()
    out = os.environ.get("DK_OUT", "data/dk_salaries.csv").strip()
    dg_override = os.environ.get("DK_DRAFTGROUP_ID", "").strip()
    # Keyword to find the slate in the lobby, e.g. "TRAVELERS_2026" -> "travelers".
    keyword = os.environ.get("DK_FIND", "").strip() or tourney.split("_")[0]
    if not (tourney and date):
        raise SystemExit("DK_TOURNAMENT and DK_DATE are required")

    if dg_override:
        dg = dg_override
    else:
        dg = resolve_draft_group(contest, keyword)
    if not dg:
        raise SystemExit("Could not resolve a draft group (try DK_DRAFTGROUP_ID).")
    print(f"Using draftGroupId {dg}")

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
