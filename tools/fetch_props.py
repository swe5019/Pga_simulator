#!/usr/bin/env python3
"""
fetch_props.py — pull Underdog NFL player prop lines into data/nfl_props.json.

ENDPOINT CHOICE, because it was not obvious and cost several probes:
  /v1/over_under_lines          7,633 lines in one call. This is the one.
  /v2/pickem_search/...         200, but a featured subset: 100 lines, 4 teams,
                                and it ignores page/per_page/limit entirely.
  /beta/v3..v6/over_under_lines 426 upgrade_required on every client-version
                                and client-type header tried.
  PrizePicks                    403 behind a DataDome captcha.

WHAT COMES OUT
One row per prop per side, flattened so the page can render it without knowing
anything about Underdog's object graph:

  player, pos, team, opp, kickoff, stat, line, side, american, decimal,
  multiplier, line_id, option_id

Both sides of a line are kept. Underdog prices higher and lower separately and
the payout multipliers are often asymmetric, so which side carries the value is
exactly the question the tool exists to answer.

HISTORY IS KEPT ON PURPOSE. Every run also writes a dated snapshot under
data/props_history/. DraftKings cut this project off from exact contest payouts
with no warning; if Underdog does the same, that archive is the difference
between losing new lines and losing everything.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "props_history")

URL = "https://api.underdogfantasy.com/v1/over_under_lines"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://underdogfantasy.com",
    "Referer": "https://underdogfantasy.com/",
}

# Underdog's own wording, mapped to short keys the page and the model use. Any
# stat not listed here still comes through with its raw name; the map exists to
# give the common ones stable keys, not to filter.
STAT_KEYS = {
    "Receptions": "rec", "Receiving Yards": "recyd", "Targets": "tgt",
    "Rush Yards": "ruyd", "Rush Attempts": "ratt",
    "Rush + Rec Yards": "scrim", "Pass Yards": "payd", "Pass Attempts": "patt",
    "Completions": "cmp", "Pass TDs": "ptd", "Interceptions": "int",
    "Anytime TD": "atd", "First TD Scorer": "ftd",
    "Longest Reception": "lngrec", "Longest Rush": "lngrush",
    "Pass + Rush Yards": "paydru", "Fumbles Lost": "fl",
    "Kicking Points": "kpts", "FG Made": "fgm", "XP Made": "xpm",
    "Tackles + Assists": "tkl",
}


def log(*a):
    print(*a, flush=True)


def get(url, attempts=4):
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            # 426 and 403 are policy, not load. Retrying will not change them.
            if e.code in (403, 426, 401):
                break
            time.sleep(3 * (2 ** i))
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(3 * (2 ** i))
    raise SystemExit(f"could not reach Underdog: {last}")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Underdog's team codes against nflverse's, which is the spine every statistic
# here joins onto. Only the Rams actually differ today, and that one cost 175
# prop sides their matchup adjustment: the opponent came through as LAR, the
# defensive multipliers were keyed LA, the lookup missed, and the column simply
# read blank rather than complaining. The rest are listed because other feeds
# spell them these ways and a silent join failure is the one bug this cannot
# detect on its own.
TEAM_ALIAS = {
    "LAR": "LA",    # nflverse keeps the Rams as LA
    "JAC": "JAX",
    "WSH": "WAS", "WFT": "WAS",
    "LVR": "LV", "OAK": "LV",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "SD": "LAC", "SDG": "LAC",
    "STL": "LA",
}


def nfl_team(code):
    """Underdog's abbreviation in nflverse's spelling."""
    c = (code or "").strip().upper()
    return TEAM_ALIAS.get(c, c)


def team_abbrs(games):
    """Underdog's /v1 response carries no teams array, but every game has
    abbreviated_title "HOU @ JAX" alongside home_team_id and away_team_id, so
    the id to abbreviation map falls out of the fixtures themselves."""
    out = {}
    for g in games:
        title = (g.get("abbreviated_title") or "").strip()
        m = re.match(r"^([A-Z]{2,4})\s*@\s*([A-Z]{2,4})$", title)
        if not m:
            continue
        away, home = nfl_team(m.group(1)), nfl_team(m.group(2))
        if g.get("away_team_id"):
            out[g["away_team_id"]] = away
        if g.get("home_team_id"):
            out[g["home_team_id"]] = home
    return out


def stat_of(line):
    """Underdog nests the stat under over_under.appearance_stat, but the option
    subheader ("Higher 0.5 Anytime TD") carries it too. Try the structured path
    first and fall back to the text, so a schema tweak degrades rather than
    drops the row."""
    ou = line.get("over_under") or {}
    ap = ou.get("appearance_stat") or {}
    name = (ap.get("display_stat") or ap.get("stat") or ou.get("title") or "").strip()
    if name:
        return name, ap.get("appearance_id")
    for o in line.get("options") or []:
        sub = (o.get("selection_subheader") or "").strip()
        m = re.match(r"^(?:Higher|Lower)\s+[\d.]+\s+(.*)$", sub)
        if m:
            return m.group(1).strip(), ap.get("appearance_id")
    return "", ap.get("appearance_id")


def build():
    log("fetching Underdog over/under lines…")
    t0 = time.time()
    doc = get(URL)
    lines = doc.get("over_under_lines") or []
    players = {p["id"]: p for p in (doc.get("players") or []) if p.get("id")}
    apps = {a["id"]: a for a in (doc.get("appearances") or []) if a.get("id")}
    games = (doc.get("games") or []) + (doc.get("solo_games") or [])
    gmap = {g["id"]: g for g in games if g.get("id")}
    abbr = team_abbrs(games)
    log(f"   {len(lines):,} lines, {len(players):,} players, {len(apps):,} appearances, "
        f"{len(games):,} games, {len(abbr)} team abbreviations  ({time.time() - t0:.1f}s)")

    rows = []
    skipped = defaultdict(int)
    for ln in lines:
        if ln.get("status") not in (None, "active"):
            skipped["line not active"] += 1
            continue
        stat_name, app_id = stat_of(ln)
        app = apps.get(app_id) if app_id else None
        if app is None:
            skipped["no appearance"] += 1
            continue
        pl = players.get(app.get("player_id"))
        if pl is None:
            skipped["no player"] += 1
            continue
        if (pl.get("sport_id") or "").upper() != "NFL":
            skipped["not NFL"] += 1
            continue

        line_val = num(ln.get("stat_value"))
        if line_val is None:
            skipped["no line value"] += 1
            continue

        tm = abbr.get(app.get("team_id"), "")
        g = gmap.get(app.get("match_id")) or {}
        home, away = abbr.get(g.get("home_team_id"), ""), abbr.get(g.get("away_team_id"), "")
        opp = away if tm == home else (home if tm == away else "")

        name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
        base = {
            "player": name,
            "pos": pl.get("position_name") or "",
            "team": tm,
            "opp": opp,
            "kickoff": g.get("scheduled_at") or "",
            "stat": stat_name,
            "key": STAT_KEYS.get(stat_name, ""),
            "line": line_val,
            "line_id": ln.get("id"),
        }
        for o in ln.get("options") or []:
            if o.get("status") not in (None, "active"):
                continue
            choice = (o.get("choice") or "").lower()
            if choice not in ("higher", "lower"):
                continue
            rows.append({
                **base,
                "side": "over" if choice == "higher" else "under",
                "american": o.get("american_price") or "",
                "decimal": num(o.get("decimal_price")),
                # payout_multiplier is what Underdog shows as 1.00x or 1.26x and
                # is what the break-even calculation actually keys off.
                "mult": num(o.get("payout_multiplier")),
                "option_id": o.get("id"),
            })

    if skipped:
        log("   skipped: " + ", ".join(f"{v} {k}" for k, v in
                                       sorted(skipped.items(), key=lambda kv: -kv[1])))
    return rows, doc


def main():
    rows, _ = build()
    if not rows:
        log("no NFL prop rows built; leaving the existing file alone")
        return 1

    stats = defaultdict(int)
    for r in rows:
        stats[r["stat"]] += 1
    players = len({r["player"] for r in rows})
    games = len({(r["team"], r["opp"]) for r in rows if r["team"] and r["opp"]})
    log(f"\n{len(rows):,} NFL prop sides · {players} players · ~{games // 2} games")
    log("stat types:")
    for s, n in sorted(stats.items(), key=lambda kv: -kv[1]):
        log(f"   {n:>5}  {s}")

    missing_team = sum(1 for r in rows if not r["team"])
    missing_opp = sum(1 for r in rows if not r["opp"])
    if missing_team or missing_opp:
        log(f"\nWARNING: {missing_team} rows without a team, {missing_opp} without "
            f"an opponent. The team map is derived from fixture titles, so a game "
            f"with an unusual title breaks it.")

    built = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"built": built, "source": "underdog", "count": len(rows), "props": rows}

    os.makedirs(HIST, exist_ok=True)
    out = os.path.join(DATA, "nfl_props.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"\nwrote nfl_props.json ({os.path.getsize(out) // 1024} KB)")

    # Dated snapshot. Lines move all week and the closing number is a different
    # thing from Tuesday's; keeping both is what makes any later honesty check
    # on the model possible at all.
    snap = os.path.join(HIST, f"props_{built[:10]}_{built[11:13]}{built[14:16]}.json")
    with open(snap, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"wrote {os.path.relpath(snap, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
