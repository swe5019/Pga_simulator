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
import datetime
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
    event = (find_key(ddata, "competition") or {}).get("name", "")

    players = {}  # name -> {salary, status, out, dkId}
    for p in draftables:
        name = (p.get("displayName") or "").strip()
        salary = p.get("salary")
        if not name or salary is None or name in players:
            continue
        status, is_out = player_status(p)
        # DK upload files use the "Name (ID)" format; this is that ID.
        dk_id = p.get("playerDkId") or p.get("playerId") or p.get("draftableId")
        players[name] = {"salary": int(salary), "status": status, "out": is_out,
                         "dkId": dk_id}

    if not players:
        raise SystemExit("No players parsed from draftables — aborting.")

    rows = sorted(players.items(), key=lambda kv: -kv[1]["salary"])  # high salary first

    # Debug: show what status-ish fields DK exposes, plus any flagged-out players.
    sample = draftables[0] if draftables else {}
    print("Sample draftable status fields:",
          {k: sample.get(k) for k in ("status", "newsStatus", "isDisabled", "draftAlerts",
                                      "playerGameAttributes")})
    print("Sample draftable id fields:",
          {k: sample.get(k) for k in ("playerDkId", "playerId", "draftableId")})
    outs = [n for n, v in rows if v["out"]]
    print(f"Flagged OUT/WD ({len(outs)}): {outs}")

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Tournament_Name", "Date", "Name", "Salary"])
        for name, v in rows:
            w.writerow([tourney, date, name, v["salary"]])

    # Rich JSON for the live app to overlay onto the master slate (salary + status).
    doc = {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tournament": tourney,
        "date": date,
        "event": event,
        "draftGroupId": str(dg),
        "count": len(rows),
        "players": [{"name": n, "salary": v["salary"], "status": v["status"],
                     "out": v["out"], "dkId": v["dkId"]}
                    for n, v in rows],
    }
    json_path = os.path.join(os.path.dirname(out), "dk.json")
    with open(json_path, "w") as fh:
        json.dump(doc, fh, indent=1)

    print(f"Wrote {out} and {json_path}: {len(rows)} golfers for {tourney} ({date}, event {event!r})")
    return 0


def player_status(p):
    """Derive (status_string, is_out) for a DK draftable, defensively across schema.
    Returns ('', False) for an active player; never raises."""
    if p.get("isDisabled") is True:
        return ("OUT", True)
    raw = (p.get("status") or "").strip()
    if raw and raw.lower() not in ("none", "active", "available"):
        up = raw.upper()
        return (up, up in ("O", "OUT", "WD", "W/D", "DISABLED"))
    news = (p.get("newsStatus") or "").strip()
    if news and news.lower() in ("out", "wd"):
        return (news.upper(), True)
    # draftAlerts / playerGameAttributes sometimes carry WD/Out wording.
    blob = json.dumps(p.get("draftAlerts") or p.get("playerGameAttributes") or "").lower()
    if '"wd"' in blob or "withdraw" in blob or '"out"' in blob:
        return ("OUT", True)
    return ("", False)


if __name__ == "__main__":
    sys.exit(main())
