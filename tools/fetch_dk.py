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
import re
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


def _fmt_date(raw):
    """DK ISO/epoch start -> 'M/D/YY'. Falls back to today on parse failure."""
    s = str(raw or "")
    dt = None
    m = re.search(r"/Date\((\d+)", s)  # legacy "/Date(1719316800000)/"
    if m:
        dt = datetime.datetime.utcfromtimestamp(int(m.group(1)) / 1000)
    else:
        iso = s.replace("Z", "").split(".")[0]
        try:
            dt = datetime.datetime.fromisoformat(iso)
        except ValueError:
            dt = None
    dt = dt or datetime.datetime.utcnow()
    return f"{dt.month}/{dt.day}/{dt.strftime('%y')}"


def _derive_tourney(event, date_str):
    """'Travelers Championship' + '6/25/26' -> 'TRAVELERS_2026'."""
    yr = date_str.split("/")[-1]
    full_yr = ("20" + yr) if len(yr) == 2 else (yr or "")
    drop = {"the", "championship", "open", "invitational", "classic",
            "tournament", "of", "at", "presented", "by", "golf"}
    words = [w for w in re.sub(r"[^A-Za-z ]", " ", event or "").split()
             if w.lower() not in drop]
    base = "_".join(words).upper() if words else "EVENT"
    return f"{base}_{full_yr}" if full_yr else base


def auto_discover():
    """Pick the main open PGA slate automatically, with no contest id needed:
    the GOLF draft group backing the most open contests (the main slate always
    dominates), then read its event name + start date. Returns
    (draftGroupId, event, tournament_name, date) or None if nothing is posted."""
    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF",
                     optional=True) or {}
    groups = {}
    for c in lobby.get("Contests", []):
        dg = c.get("dg") or c.get("draftGroupId")
        if not dg:
            continue
        g = groups.setdefault(dg, {"count": 0, "entries": 0})
        g["count"] += 1
        g["entries"] += (c.get("m") or 0)
    if not groups:
        print("auto-discover: no open GOLF contests (DK hasn't posted a slate yet)")
        return None

    dg_meta = {d.get("DraftGroupId"): d for d in lobby.get("DraftGroups", [])}
    print("Open GOLF draft groups by contest volume:")
    for dg, g in sorted(groups.items(), key=lambda kv: -kv[1]["count"])[:6]:
        m = dg_meta.get(dg, {})
        print(f"  dg={dg} contests={g['count']} entries={g['entries']} "
              f"start={m.get('StartDate') or m.get('StartDateEst')}")

    # Main slate = most contests, tie-break on total entries.
    best = max(groups.items(), key=lambda kv: (kv[1]["count"], kv[1]["entries"]))[0]
    meta = dg_meta.get(best, {})
    start = meta.get("StartDate") or meta.get("StartDateEst")

    ddata = get_json(
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{best}/draftables?format=json",
        optional=True,
    )
    event = ""
    if ddata:
        comp = find_key(ddata, "competition") or {}
        event = comp.get("name") or comp.get("nameDisplay") or ""
        start = start or comp.get("startTime") or comp.get("startDate")
    date_str = _fmt_date(start)
    tourney = _derive_tourney(event, date_str)
    print(f"auto-discover picked dg={best} event={event!r} -> {tourney} {date_str}")
    return str(best), event, tourney, date_str


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


def probe_contest(cid):
    """Try several DK endpoints for a contest id and report which expose payouts."""
    candidates = [
        f"https://api.draftkings.com/contests/v1/contests/{cid}?format=json",
        f"https://api.draftkings.com/contests/v1/contests/{cid}",
        f"https://www.draftkings.com/contest/detailspop?contestId={cid}",
        f"https://api.draftkings.com/contests/v1/contests/{cid}/payouts?format=json",
    ]
    for url in candidates:
        data = get_json(url, optional=True)
        if data is None:
            continue
        pay = find_key(data, "payoutSummary") or find_key(data, "payoutDescriptions") \
            or find_key(data, "payouts") or find_key(data, "TotalPayouts")
        dg = find_key(data, "draftGroupId")
        keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
        print(f"OK {url}\n   top-keys={keys}\n   draftGroupId={dg} payouts_present={pay is not None}")
        if pay is not None:
            print("   payout sample:", json.dumps(pay)[:400])
    return 0


def probe_draftgroup_payouts(dg):
    """Find real open contests for a draft group in the lobby and probe payouts."""
    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF", optional=True) or {}
    matches = [c for c in lobby.get("Contests", []) if str(c.get("dg")) == str(dg)]
    print(f"{len(matches)} open contests for draft group {dg}")
    for c in matches[:4]:
        cid = c.get("id")
        print(f"--- contest {cid} | {c.get('n')} | fee={c.get('a')} | entries={c.get('m')} ---")
        data = get_json(f"https://api.draftkings.com/contests/v1/contests/{cid}?format=json", optional=True)
        if not data:
            continue
        pay = find_key(data, "payoutSummary") or find_key(data, "payoutDescriptions") \
            or find_key(data, "payouts")
        print("   payouts_present=", pay is not None, "| sample:", json.dumps(pay)[:300] if pay else "")
    return 0


def main():
    if os.environ.get("DK_PROBE_DG", "").strip():
        return probe_draftgroup_payouts(os.environ["DK_PROBE_DG"].strip())
    if os.environ.get("DK_PROBE_CONTEST", "").strip():
        return probe_contest(os.environ["DK_PROBE_CONTEST"].strip())
    if os.environ.get("DK_LIST", "").strip():
        list_groups()
        return 0
    contest = os.environ.get("DK_CONTEST_ID", "").strip()
    tourney = os.environ.get("DK_TOURNAMENT", "").strip()
    date = os.environ.get("DK_DATE", "").strip()
    out = os.environ.get("DK_OUT", "data/dk_salaries.csv").strip()
    dg_override = os.environ.get("DK_DRAFTGROUP_ID", "").strip()
    auto = os.environ.get("DK_AUTO", "").strip()

    # Fully automatic mode: discover the current main PGA slate (no contest id,
    # no tournament name needed). Used by the schedule trigger so salaries land
    # on their own as soon as DK posts the next event.
    if auto and not (dg_override or contest):
        disc = auto_discover()
        if not disc:
            print("Nothing to fetch yet — exiting cleanly.")
            return 0
        dg_override, event_auto, tourney_auto, date_auto = disc
        tourney = tourney or tourney_auto
        date = date or date_auto

    # Keyword to find the slate in the lobby, e.g. "TRAVELERS_2026" -> "travelers".
    keyword = os.environ.get("DK_FIND", "").strip() or (tourney.split("_")[0] if tourney else "")
    if not (tourney and date):
        raise SystemExit("DK_TOURNAMENT and DK_DATE are required (or set DK_AUTO=1)")

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
        # DK upload files use the "Name (ID)" format; the draftableId is that ID
        # (matches the DKSalaries "Name + ID" column).
        dk_id = p.get("draftableId") or p.get("playerDkId") or p.get("playerId")
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

    # Real DK contests + exact payout tables for this draft group (for Contest Sim).
    contests = build_contests(dg, tourney, event)
    cpath = os.path.join(os.path.dirname(out), "dk_contests.json")
    with open(cpath, "w") as fh:
        json.dump(contests, fh, indent=1)
    print(f"Wrote {cpath}: {len(contests['contests'])} contests with exact payouts")
    return 0


def extract_tiers(detail):
    """Pull a rank-by-rank payout table [{min,max,value}] from a DK contest detail."""
    found = []

    def walk(o):
        if isinstance(o, list):
            if o and isinstance(o[0], dict) and "minPosition" in o[0]:
                found.append(o)
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)

    walk(detail)
    if not found:
        return []
    arr = max(found, key=len)
    tiers = []
    for t in arr:
        mn = t.get("minPosition")
        mx = t.get("maxPosition", mn)
        val = None
        pd = t.get("payoutDescriptions")
        if isinstance(pd, list) and pd:
            val = pd[0].get("value")
        if val is None:
            cash = (t.get("tierPayoutDescriptions") or {}).get("Cash")
            if cash:
                try:
                    val = float(str(cash).replace("$", "").replace(",", ""))
                except ValueError:
                    val = None
        if mn is not None and val is not None:
            tiers.append({"min": int(mn), "max": int(mx), "value": float(val)})
    return tiers


def build_contests(dg, tourney, event):
    """Discover real open contests for a draft group and capture exact payout tiers.
    Picks a spread of contest sizes/fees (deduped), up to a sane cap."""
    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF", optional=True) or {}
    matches = [c for c in lobby.get("Contests", []) if str(c.get("dg")) == str(dg)]
    seen = set()
    picks = []
    for c in sorted(matches, key=lambda c: -(c.get("m") or 0)):  # biggest fields first
        key = (c.get("a"), c.get("m"))
        if key in seen:
            continue
        seen.add(key)
        picks.append(c)
        if len(picks) >= 14:
            break

    out = []
    for c in picks:
        cid = c.get("id")
        detail = get_json(f"https://api.draftkings.com/contests/v1/contests/{cid}?format=json", optional=True)
        if not detail:
            continue
        tiers = extract_tiers(detail)
        if not tiers:
            continue
        pool = sum(t["value"] * (t["max"] - t["min"] + 1) for t in tiers)
        out.append({
            "id": str(cid),
            "name": c.get("n"),
            "fee": c.get("a"),
            "entries": c.get("m"),
            "paidSpots": max(t["max"] for t in tiers),
            "prizePool": round(pool, 2),
            "tiers": tiers,
        })
    out.sort(key=lambda x: -(x["entries"] or 0))
    return {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tournament": tourney,
        "event": event,
        "draftGroupId": str(dg),
        "contests": out,
    }


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
