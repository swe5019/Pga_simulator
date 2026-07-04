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
import io
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


def parse_standings_ownership(text):
    """Parse a DraftKings 'contest standings' CSV -> {player_name: %drafted}.
    The export interleaves entry columns (left) with a player/ownership block
    (right): columns include 'Player', 'Roster Position', '%Drafted', 'FPTS'."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {}, {}
    header = [h.strip().lower() for h in rows[0]]
    try:
        pi = header.index("player")
        oi = header.index("%drafted")
    except ValueError:
        return {}, {}
    fi = header.index("fpts") if "fpts" in header else None
    own, fpts = {}, {}
    for row in rows[1:]:
        if len(row) <= max(pi, oi):
            continue
        name = (row[pi] or "").strip()
        if not name:
            continue
        val = (row[oi] or "").replace("%", "").strip()
        try:
            own[name] = round(float(val), 2)
        except ValueError:
            continue
        if fi is not None and len(row) > fi:
            try:
                fpts[name] = round(float(row[fi]), 1)
            except ValueError:
                pass
    return own, fpts


def find_results_contest():
    """Resolve the completed contest id to pull ownership from: explicit id, or a
    keyword matched against data/dk_contests.json (e.g. 'Caddie')."""
    cid = os.environ.get("DK_RESULTS_CONTEST", "").strip()
    if cid:
        return cid
    kw = os.environ.get("DK_RESULTS_FIND", "").strip().lower()
    try:
        with open(os.path.join("data", "dk_contests.json")) as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    contests = doc.get("contests", [])
    if kw:
        for c in contests:
            if kw in str(c.get("name", "")).lower():
                return str(c.get("id"))
    # Otherwise the biggest-field contest we know about.
    if contests:
        return str(max(contests, key=lambda c: c.get("entries") or 0).get("id"))
    return None


def fetch_ownership():
    """Pull real post-contest ownership from a completed DK contest's standings
    CSV (needs DK_COOKIE — your logged-in session). Writes/merges
    data/actual_ownership.json so the history archive can score models vs reality."""
    cid = find_results_contest()
    if not cid:
        raise SystemExit("No results contest id (set DK_RESULTS_CONTEST or DK_RESULTS_FIND).")
    cookie = os.environ.get("DK_COOKIE", "").strip()
    if not cookie:
        raise SystemExit("DK_COOKIE secret required to export contest standings "
                         "(your logged-in DraftKings session cookie).")
    tourney = os.environ.get("DK_TOURNAMENT", "").strip()
    if not tourney:
        disc = auto_discover()
        tourney = disc[2] if disc else "UNKNOWN"

    url = f"https://www.draftkings.com/contest/exportfullstandingscsv/{cid}"
    print(f"GET {url} (authenticated)")
    req = urllib.request.Request(url, headers={**UA, "Cookie": cookie})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode("utf-8", "replace")
    if "<html" in text[:200].lower():
        raise SystemExit("Got an HTML page, not a CSV — cookie likely expired or "
                         "you didn't enter this contest.")
    own, fpts = parse_standings_ownership(text)
    if not own:
        raise SystemExit("No ownership parsed — standings CSV format unexpected.")

    path = os.path.join("data", "actual_ownership.json")
    doc = {}
    if os.path.exists(path):
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except ValueError:
            doc = {}
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    doc.setdefault("tournaments", {})
    doc["tournaments"][tourney] = {
        "contestId": str(cid), "updatedUtc": now,
        "count": len(own), "ownership": own, "fpts": fpts or None,
    }
    doc["updatedUtc"] = now
    os.makedirs("data", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1)
    top = sorted(own.items(), key=lambda kv: -kv[1])[:5]
    print(f"Pulled ownership for {len(own)} players from contest {cid} -> {tourney}")
    print("  top owned:", ", ".join(f"{n} {v}%" for n, v in top))
    return 0


def auto_discover():
    """Pick the main open 4-day Classic PGA slate automatically, with no contest
    id needed: the GOLF draft group backing the most open Classic contests, then
    read its event name + start date. Returns (draftGroupId, event,
    tournament_name, date) or None if nothing is posted.

    Excludes "Showdown"-branded contests: DK posts a new Showdown slate (smaller
    field, single-round scoring) every day once the main Classic contests lock at
    Thursday tee time, and those out-open the original Classic contests by entry
    count for the rest of the week. Ranking by raw open-contest volume would drift
    onto that day's Showdown draft group instead of the Classic one — this app's
    roster rules (6 golfers / $50K cap, full-tournament scoring) only match the
    Classic format.
    """
    lobby = get_json("https://www.draftkings.com/lobby/getcontests?sport=GOLF",
                     optional=True) or {}
    classic_groups = {}
    showdown_groups = {}
    for c in lobby.get("Contests", []):
        name_lower = (c.get("n") or "").lower()
        dg = c.get("dg") or c.get("draftGroupId")
        if not dg:
            continue
        # Identify showdown/captain's-mode contests by common DK naming patterns.
        is_sd = any(kw in name_lower for kw in ("showdown", "captain", "single game", "sgp"))
        if is_sd:
            g = showdown_groups.setdefault(dg, {"count": 0, "entries": 0, "example": c.get("n", "")})
        else:
            g = classic_groups.setdefault(dg, {"count": 0, "entries": 0})
        g["count"] += 1
        g["entries"] += (c.get("m") or 0)

    if not classic_groups:
        print("auto-discover: no open non-Showdown GOLF contests (DK hasn't posted "
              "the Classic slate yet, or only Showdown contests are open this week)")
        return None, _pick_showdown_dg(showdown_groups, lobby)

    dg_meta = {d.get("DraftGroupId"): d for d in lobby.get("DraftGroups", [])}
    print("Open GOLF draft groups by contest volume:")
    for dg, g in sorted(classic_groups.items(), key=lambda kv: -kv[1]["count"])[:6]:
        m = dg_meta.get(dg, {})
        print(f"  dg={dg} contests={g['count']} entries={g['entries']} "
              f"start={m.get('StartDate') or m.get('StartDateEst')}")

    # Main slate = most contests, tie-break on total entries.
    best = max(classic_groups.items(), key=lambda kv: (kv[1]["count"], kv[1]["entries"]))[0]
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
    return (str(best), event, tourney, date_str), _pick_showdown_dg(showdown_groups, lobby)


def _pick_showdown_dg(showdown_groups, lobby):
    """Return (dg, event, tourney, date) for the most-used showdown draft group, or None."""
    if not showdown_groups:
        return None
    best_dg = max(showdown_groups.items(), key=lambda kv: (kv[1]["count"], kv[1]["entries"]))[0]
    dg_meta = {d.get("DraftGroupId"): d for d in lobby.get("DraftGroups", [])}
    meta = dg_meta.get(best_dg, {})
    start = meta.get("StartDate") or meta.get("StartDateEst")
    ddata = get_json(
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{best_dg}/draftables?format=json",
        optional=True,
    )
    event = ""
    if ddata:
        comp = find_key(ddata, "competition") or {}
        event = comp.get("name") or comp.get("nameDisplay") or ""
        start = start or comp.get("startTime") or comp.get("startDate")
    date_str = _fmt_date(start)
    tourney = _derive_tourney(event, date_str)
    print(f"auto-discover showdown dg={best_dg} event={event!r} -> {tourney} {date_str}")
    return str(best_dg), event, tourney, date_str


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
    # Pull real post-contest ownership from a completed contest's standings CSV.
    if (os.environ.get("DK_RESULTS_CONTEST", "").strip()
            or os.environ.get("DK_RESULTS_FIND", "").strip()):
        return fetch_ownership()
    contest = os.environ.get("DK_CONTEST_ID", "").strip()
    tourney = os.environ.get("DK_TOURNAMENT", "").strip()
    date = os.environ.get("DK_DATE", "").strip()
    out = os.environ.get("DK_OUT", "data/dk_salaries.csv").strip()
    dg_override = os.environ.get("DK_DRAFTGROUP_ID", "").strip()
    auto = os.environ.get("DK_AUTO", "").strip()

    # Fully automatic mode: discover the current main PGA slate (no contest id,
    # no tournament name needed). Used by the schedule trigger so salaries land
    # on their own as soon as DK posts the next event.
    showdown_disc = None
    if auto and not (dg_override or contest):
        classic_disc, showdown_disc = auto_discover()
        if not classic_disc:
            print("Nothing to fetch yet — exiting cleanly.")
            return 0
        dg_override, event_auto, tourney_auto, date_auto = classic_disc
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

    # Detect showdown by duplicate player names (CPT+FLEX = same name appears twice).
    raw_names = [p.get("displayName", "").strip() for p in draftables if p.get("displayName")]
    is_showdown = len(raw_names) > len(set(raw_names)) or len(set(raw_names)) < 80

    # Rich JSON for the live app to overlay onto the master slate (salary + status).
    doc = {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tournament": tourney,
        "date": date,
        "event": event,
        "draftGroupId": str(dg),
        "isShowdown": is_showdown,
        "count": len(rows),
        "players": [{"name": n, "salary": v["salary"], "status": v["status"],
                     "out": v["out"], "dkId": v["dkId"]}
                    for n, v in rows],
    }
    # If this slate is actually showdown (mis-identified as classic), write it to
    # dk_showdown.json and leave dk.json untouched to preserve the classic slate.
    if is_showdown:
        json_path = os.path.join(os.path.dirname(out), "dk_showdown.json")
        print(f"Detected showdown slate (unique players: {len(set(raw_names))}) — "
              f"writing to dk_showdown.json instead of dk.json")
    else:
        json_path = os.path.join(os.path.dirname(out), "dk.json")
        with open(out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Tournament_Name", "Date", "Name", "Salary"])
            for name, v in rows:
                w.writerow([tourney, date, name, v["salary"]])

    with open(json_path, "w") as fh:
        json.dump(doc, fh, indent=1)

    print(f"Wrote {json_path}: {len(rows)} golfers for {tourney} ({date}, event {event!r})")

    # Fetch the showdown slate too if we discovered one (auto mode only).
    if showdown_disc:
        _fetch_and_write_showdown(showdown_disc, os.path.dirname(out))

    # Real DK contests + exact payout tables for this draft group (for Contest Sim).
    if not is_showdown:
        contests = build_contests(dg, tourney, event)
        cpath = os.path.join(os.path.dirname(out), "dk_contests.json")
        with open(cpath, "w") as fh:
            json.dump(contests, fh, indent=1)
        print(f"Wrote {cpath}: {len(contests['contests'])} contests with exact payouts")
    return 0


def _fetch_and_write_showdown(disc, data_dir):
    """Fetch a showdown draft group and write dk_showdown.json."""
    sd_dg, sd_event, sd_tourney, sd_date = disc
    print(f"\n--- Fetching showdown slate dg={sd_dg} ---")
    ddata = get_json(
        f"https://api.draftkings.com/draftgroups/v1/draftgroups/{sd_dg}/draftables?format=json",
        optional=True,
    )
    if not ddata:
        print("  showdown draftables fetch failed — skipping dk_showdown.json")
        return
    draftables = ddata.get("draftables", [])
    event = (find_key(ddata, "competition") or {}).get("name", "") or sd_event

    players = {}
    for p in draftables:
        name = (p.get("displayName") or "").strip()
        salary = p.get("salary")
        if not name or salary is None or name in players:
            continue
        status, is_out = player_status(p)
        dk_id = p.get("draftableId") or p.get("playerDkId") or p.get("playerId")
        players[name] = {"salary": int(salary), "status": status, "out": is_out, "dkId": dk_id}

    if not players:
        print("  no showdown players parsed — skipping dk_showdown.json")
        return

    rows = sorted(players.items(), key=lambda kv: -kv[1]["salary"])
    doc = {
        "updatedUtc": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "tournament": sd_tourney,
        "date": sd_date,
        "event": event,
        "draftGroupId": str(sd_dg),
        "isShowdown": True,
        "count": len(rows),
        "players": [{"name": n, "salary": v["salary"], "status": v["status"],
                     "out": v["out"], "dkId": v["dkId"]}
                    for n, v in rows],
    }
    path = os.path.join(data_dir, "dk_showdown.json")
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"  Wrote {path}: {len(rows)} showdown players for {sd_tourney}")


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
