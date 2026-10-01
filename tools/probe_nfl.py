#!/usr/bin/env python3
"""
probe_nfl.py — read-only check of what DraftKings exposes for NFL.

Writes nothing. Answers two questions:
  1. Which NFL draft groups are open, and which is the Thu-Mon full-week slate
     versus the Sun-Mon main slate (DK distinguishes them only by start time).
  2. Whether the www player endpoint returns salaries for them, the same way it
     does for golf now that api.draftkings.com 403s this runner.
"""
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.draftkings.com/",
    "Origin": "https://www.draftkings.com",
}


def get(url, attempts=3):
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"   HTTP {e.code} on {url[:90]}")
            if e.code in (403, 429, 500, 502, 503, 504) and i < attempts - 1:
                time.sleep(3 * (2 ** i))
                continue
            return None
        except Exception as e:  # noqa: BLE001
            print(f"   error: {e}")
            if i < attempts - 1:
                time.sleep(3)
                continue
            return None
    return None


def parse_start(s):
    """DK sends /Date(1234567890000)/ or an ISO string depending on endpoint."""
    if not s:
        return None
    if isinstance(s, str) and s.startswith("/Date("):
        try:
            return datetime.datetime.utcfromtimestamp(int(s[6:-2].split("-")[0].split("+")[0]) / 1000)
        except Exception:  # noqa: BLE001
            return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "").split(".")[0])
    except Exception:  # noqa: BLE001
        return None


def main():
    print("=" * 78)
    print("1. NFL LOBBY")
    print("=" * 78)
    lobby = get("https://www.draftkings.com/lobby/getcontests?sport=NFL")
    if not lobby:
        print("lobby unreachable — NFL is blocked the same way the api host is.")
        return 1
    contests = lobby.get("Contests", [])
    print(f"open NFL contests visible: {len(contests)}")

    groups = {}
    for c in contests:
        dg = c.get("dg") or c.get("draftGroupId")
        if not dg:
            continue
        g = groups.setdefault(dg, {"n": 0, "entries": 0, "names": [], "start": c.get("sd")})
        g["n"] += 1
        g["entries"] += c.get("m") or 0
        if len(g["names"]) < 2:
            g["names"].append(c.get("n") or "")

    # DK also publishes a draft-group index with start times and slate labels.
    meta = get("https://www.draftkings.com/lobby/getcontests?sport=NFL") or {}
    dgmeta = {str(d.get("DraftGroupId")): d for d in (meta.get("DraftGroups") or [])}
    print(f"draft groups in lobby: {len(groups)}\n")

    rows = sorted(groups.items(), key=lambda kv: -kv[1]["entries"])
    print(f"{'dg':<9}{'contests':>9}{'entries':>10}  {'start (UTC)':<20}{'tag':<12}example")
    print("-" * 110)
    for dg, g in rows[:14]:
        m = dgmeta.get(str(dg), {})
        start = parse_start(m.get("StartDateEst") or m.get("StartDate") or g.get("start"))
        tag = (m.get("ContestStartTimeSuffix") or m.get("DraftGroupTag") or "").strip()
        sd = start.strftime("%a %Y-%m-%d %H:%M") if start else "?"
        print(f"{dg:<9}{g['n']:>9}{g['entries']:>10}  {sd:<20}{tag:<12}{g['names'][0][:44]}")

    print()
    print("=" * 78)
    print("2. SALARIES PER DRAFT GROUP (www player endpoint)")
    print("=" * 78)
    for dg, g in rows[:6]:
        data = get(f"https://www.draftkings.com/lineup/getavailableplayers?draftGroupId={dg}")
        if not data:
            print(f"\ndg={dg}: NO DATA")
            continue
        players = data.get("playerList") or data.get("players") or []
        if not players:
            print(f"\ndg={dg}: endpoint answered but returned no players "
                  f"(top-level keys: {sorted(str(k) for k in data)[:10]})")
            continue
        pos = {}
        sal = []
        for p in players:
            pos[p.get("pn") or p.get("position") or "?"] = pos.get(p.get("pn") or "?", 0) + 1
            s = p.get("s") or p.get("salary")
            if isinstance(s, (int, float)):
                sal.append(s)
        m = dgmeta.get(str(dg), {})
        start = parse_start(m.get("StartDateEst") or m.get("StartDate"))
        print(f"\ndg={dg}  players={len(players)}  start={start}  "
              f"salary {min(sal) if sal else '?'}–{max(sal) if sal else '?'}")
        print(f"   positions: {dict(sorted(pos.items(), key=lambda kv: -kv[1]))}")
        for p in players[:4]:
            nm = " ".join(x for x in (p.get("fn"), p.get("ln")) if x)
            print(f"      {nm:<24} {p.get('pn'):<4} ${p.get('s')}  team={p.get('htabbr')}/{p.get('atabbr')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
