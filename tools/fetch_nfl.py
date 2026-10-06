#!/usr/bin/env python3
"""
fetch_nfl.py — build data/nfl_stats.json from nflverse, and data/nfl_dk.json
from DraftKings.

WHY THE OUTPUT LOOKS THE WAY IT DOES
------------------------------------
The page lets you pick any week range, so this file must NOT ship pre-averaged
rates. A rate averaged over weeks is not the rate over the window: a receiver
with 2 targets on 10 routes one week and 8 on 30 the next has a TPRR of 0.25,
not the 0.23 you get by averaging 0.20 and 0.267. So every row here is RAW
COUNTS for one player in one week, plus the team denominators for that week in
a separate block. The browser sums counts across whatever window you select and
divides once, which is correct for any window.

The handful of genuine rate inputs that cannot be decomposed into counts (Next
Gen Stats separation, YAC over expected, time to throw, rush yards over
expected) ship as the rate plus the volume they were measured over, so the
browser can take a volume-weighted mean rather than a flat one.

SOURCES (all static files in GitHub releases — no API edge that can block a
runner, which is the whole reason this is not scraped):
  stats_player/stats_player_week_<season>.csv   season-long weekly box score
  snap_counts/snap_counts_<season>.csv          offensive snap share
  pbp/play_by_play_<season>.csv                 red zone / goal line / EPA / aDOT
  nextgen_stats/ngs_{passing,receiving,rushing}.csv.gz   NGS tracking rates
  pbp_participation/pbp_participation_<season>.csv       ROUTES (see below)

ROUTES ARE SEASON-CONDITIONAL. Routes run are not published anywhere free. They
are reconstructed here from participation data, which lists the 11 offensive
players on the field for each play: a skill player on the field for a dropback
is counted as having run a route. That is the standard reconstruction and it is
an approximation — a back who stays in to block is counted a route he did not
run, so RB TPRR reads slightly low. nflverse publishes participation per season
and the CURRENT season usually lags. When the file is missing, routes, TPRR and
YPRR are simply absent and the page hides those columns rather than showing
zeros. Nothing needs changing here when nflverse posts it; the next run picks
it up.
"""
import csv
import datetime
import gzip
import io
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
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
# Expected fantasy points come from ffverse, a different project to nflverse,
# but published the same way: static files on a GitHub release.
FFOPP = "https://github.com/ffverse/ffopportunity/releases/download/latest-data"

POSITIONS = ("QB", "RB", "WR", "TE")

# Fields kept in the output even when they are exactly zero. The Next Gen rates
# are here because dropping a zero removes that week's weight from a weighted
# mean (see the emit loop). The expected-points fields are here because a
# missing one marks the week as "not modelled" and drops it from the vs-expected
# average, so a genuine 0.00 must be distinguishable from an absent reading.
KEEP_ZERO = frozenset(("sep", "yacoe", "ttt", "iay", "ryoe", "xfp", "xrec"))

# Standard PPR, matching the scoring ffopportunity's expected-points model uses:
# 0.04 per passing yard, 4 per passing TD, -2 per interception, 0.1 per rushing
# or receiving yard, 6 per TD, 1 per reception, 2 per two-point conversion and
# -2 per fumble lost. Verified against their published actuals rather than
# assumed, because DraftKings uses -1 for interceptions and fumbles and mixing
# the two conventions would bias every vs-expected figure.
def ppr_points(r):
    return (0.04 * num(r.get("passing_yards")) + 4 * num(r.get("passing_tds"))
            - 2 * num(r.get("passing_interceptions"))
            + 0.1 * num(r.get("rushing_yards")) + 6 * num(r.get("rushing_tds"))
            + 0.1 * num(r.get("receiving_yards")) + 6 * num(r.get("receiving_tds"))
            + 1 * num(r.get("receptions"))
            + 6 * num(r.get("special_teams_tds"))
            + 2 * (num(r.get("passing_2pt_conversions"))
                   + num(r.get("rushing_2pt_conversions"))
                   + num(r.get("receiving_2pt_conversions")))
            - 2 * (num(r.get("sack_fumbles_lost"))
                   + num(r.get("rushing_fumbles_lost"))
                   + num(r.get("receiving_fumbles_lost"))))

# csv's default field cap is 128KB; participation rows carry 22 player ids plus
# names in single fields and blow straight through it.
csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))

UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "text/csv, application/json, */*",
}
RETRY_CODES = (403, 429, 500, 502, 503, 504)


def log(*a):
    print(*a, flush=True)


def fetch(url, attempts=4, optional=False):
    """Return raw bytes, or None when optional and unavailable."""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if optional:
                    log(f"   not published: {url.rsplit('/', 1)[-1]}")
                    return None
                raise
            if e.code in RETRY_CODES and i < attempts - 1:
                time.sleep(3 * (2 ** i))
                continue
            if optional:
                log(f"   HTTP {e.code}: {url.rsplit('/', 1)[-1]}")
                return None
            raise
        except Exception as e:  # noqa: BLE001
            if i < attempts - 1:
                time.sleep(3 * (2 ** i))
                continue
            if optional:
                log(f"   error on {url.rsplit('/', 1)[-1]}: {e}")
                return None
            raise
    return None


def rows(url, optional=False):
    """Stream a nflverse csv (plain or .gz) as dicts."""
    blob = fetch(url, optional=optional)
    if blob is None:
        return []
    if url.endswith(".gz"):
        blob = gzip.decompress(blob)
    return list(csv.DictReader(io.StringIO(blob.decode("utf-8", "replace"))))


def num(v, d=0.0):
    try:
        if v is None or v == "" or v == "NA":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def i(v, d=0):
    return int(round(num(v, d)))


def r2(v):
    return round(float(v), 2)


def nrm(s):
    """Name key for joining feeds that do not share an id.

    Must survive 'A.J. Brown' vs 'AJ Brown' and 'Marvin Harrison Jr.' vs
    'Marvin Harrison'. Suffixes go because PFR and NGS disagree about them.
    """
    s = (s or "").lower()
    s = re.sub(r"[.'`,]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z]+", "", s)


# --------------------------------------------------------------------------
# nflverse
# --------------------------------------------------------------------------
def build_stats(season):
    out_players = {}   # id -> meta
    weeks = defaultdict(dict)   # (id, week) -> counting stats
    team = defaultdict(lambda: defaultdict(float))  # (team, week) -> denominators
    opp = {}           # (team, week) -> opponent

    def pw(pid, wk):
        return weeks[(pid, wk)]

    # ---- weekly box score: the spine. Everything else joins onto these ids.
    log("1. weekly player stats")
    spw = rows(f"{NFLVERSE}/stats_player/stats_player_week_{season}.csv")
    if not spw:
        log(f"   no weekly stats for {season} — nothing to build")
        return None
    for r in spw:
        if r.get("season_type") != "REG":
            continue
        pos = (r.get("position") or "").upper()
        if pos not in POSITIONS:
            continue
        pid, wk = r.get("player_id"), i(r.get("week"))
        if not pid or not wk:
            continue
        tm = (r.get("team") or "").upper()
        out_players.setdefault(pid, {
            "id": pid,
            "n": r.get("player_display_name") or r.get("player_name") or "",
            "p": pos,
            "t": tm,
        })
        out_players[pid]["t"] = tm   # last team seen wins, so trades follow
        d = pw(pid, wk)
        d["tm"] = tm
        d["tg"] = i(r.get("targets"))
        d["rec"] = i(r.get("receptions"))
        d["ry"] = i(r.get("receiving_yards"))
        d["ay"] = i(r.get("receiving_air_yards"))
        d["ca"] = i(r.get("carries"))
        d["ru"] = i(r.get("rushing_yards"))
        d["att"] = i(r.get("attempts"))
        d["cmp"] = i(r.get("completions"))
        d["py"] = i(r.get("passing_yards"))
        d["sk"] = i(r.get("sacks_suffered"))
        d["pay"] = i(r.get("passing_air_yards"))
        # Touchdowns are kept apart rather than summed. A combined figure cannot
        # be taken back apart, and the standard box score wants to know whether
        # a back scored on the ground or through the air.
        d["rtd"] = i(r.get("receiving_tds"))
        d["utd"] = i(r.get("rushing_tds"))
        d["ptd"] = i(r.get("passing_tds"))
        d["int"] = i(r.get("passing_interceptions"))
        d["fl"] = (i(r.get("sack_fumbles_lost")) + i(r.get("rushing_fumbles_lost"))
                   + i(r.get("receiving_fumbles_lost")))
        # EPA and CPOE arrive per-game already summed over the player's plays,
        # so they stay sums here and are divided by window volume in the page.
        d["pepa"] = num(r.get("passing_epa"))
        d["repa"] = num(r.get("receiving_epa"))
        d["ruepa"] = num(r.get("rushing_epa"))
        # cpoe is a per-attempt mean in this feed; store the weighted numerator.
        d["cpoeN"] = num(r.get("passing_cpoe")) * d["att"]
        # Actual points come from the box score, not from the expected-points
        # feed's own actuals. The two disagree on about 2% of player-weeks over
        # touchdown attribution, and the box score is the official record. It
        # also keeps the Half PPR column on screen exactly equal to the vs
        # expected column plus expected, which is what a reader will assume.
        d["fp"] = round(ppr_points(r), 2)
        o = (r.get("opponent_team") or "").upper()
        if tm and wk and o:
            opp[(tm, wk)] = o
    log(f"   {len(out_players)} skill players, {len(weeks)} player-weeks")

    # ---- team denominators from play by play. Targets, air yards and carries
    # must come from the same source as the player numbers or the shares will
    # not sum to 100%, so both sides are counted off pbp here.
    log("2. play by play (team shares, red zone, goal line)")
    qb_ids = {pid for pid, m in out_players.items() if m["p"] == "QB"}
    pbp = rows(f"{NFLVERSE}/pbp/play_by_play_{season}.csv")
    dropbacks = set()
    for r in pbp:
        if r.get("season_type") != "REG":
            continue
        wk, pt = i(r.get("week")), (r.get("posteam") or "").upper()
        if not wk or not pt:
            continue
        t = team[(pt, wk)]
        y100 = num(r.get("yardline_100"), 999)
        # play_type is the gate for everything counted here. pass_attempt and
        # rush_attempt are also set on plays wiped out by penalty, which
        # play_type marks 'no_play'; counting those put team pace 20% high.
        ptype = (r.get("play_type") or "").lower()
        is_pass = ptype == "pass"
        is_rush = ptype == "run" and i(r.get("qb_scramble")) != 1
        if i(r.get("qb_dropback")) == 1:
            t["db"] += 1
            # Remembered so participation can count routes against the real
            # dropback set rather than guessing from its own columns.
            dropbacks.add((r.get("game_id") or "", str(i(r.get("play_id")))))
        if ptype in ("pass", "run"):
            t["plays"] += 1
        rid = r.get("receiver_player_id") or ""
        if is_pass and rid:
            t["tg"] += 1
            t["ay"] += num(r.get("air_yards"))
            d = weeks.get((rid, wk))
            if d is not None and y100 <= 20:
                d["rz"] = d.get("rz", 0) + 1
        uid = r.get("rusher_player_id") or ""
        if is_rush and uid:
            t["ca"] += 1
            d = weeks.get((uid, wk))
            if d is not None:
                if y100 <= 20:
                    d["rzc"] = d.get("rzc", 0) + 1
                if y100 <= 5:
                    d["glc"] = d.get("glc", 0) + 1
        # QB rushing is the single biggest DFS separator at the position and is
        # not isolated in the box score, so count scrambles + designed runs.
        # The test is the player's POSITION, not whether he threw a pass that
        # week: gating on attempts scored a zero for any quarterback who ran but
        # did not throw, which is exactly the mobile-QB game worth seeing.
        if uid and uid in qb_ids and (is_rush or i(r.get("qb_scramble")) == 1):
            d = weeks.get((uid, wk))
            if d is not None:
                d["qra"] = d.get("qra", 0) + 1
    log(f"   {len(pbp)} plays, {len(team)} team-weeks")

    # ---- snap share. snap_counts carries no gsis id, so join on name+team.
    log("3. snap counts")
    by_name = defaultdict(list)
    for pid, m in out_players.items():
        by_name[nrm(m["n"])].append(pid)
    snaps = rows(f"{NFLVERSE}/snap_counts/snap_counts_{season}.csv")
    hit = miss = 0
    # Team snaps are recovered from snaps/pct, but offense_pct is rounded to two
    # decimals, so the error in that division is brutal for bit-part players: a
    # lineman with 1 snap at "0.01" implies 100 team snaps when the truth is 66.
    # Taking the max across players therefore picks the single worst estimate
    # every time. Keep the estimate from the player with the MOST snaps, where
    # the rounding is proportionally smallest, and floor it at the largest snap
    # count seen, since a team ran at least as many snaps as its busiest player.
    best = {}   # (tm, wk) -> (snaps of the player used, implied team snaps)
    most = defaultdict(int)
    for r in snaps:
        if r.get("game_type") != "REG":
            continue
        wk = i(r.get("week"))
        pct = num(r.get("offense_pct"))
        sn = i(r.get("offense_snaps"))
        tm = (r.get("team") or "").upper()
        if not wk or sn <= 0 or not tm:
            continue
        # Every offensive player counts toward the denominator, linemen
        # included; only the numerator needs a skill-player match.
        most[(tm, wk)] = max(most[(tm, wk)], sn)
        if pct > 0 and sn > best.get((tm, wk), (0, 0))[0]:
            best[(tm, wk)] = (sn, round(sn / pct))

        cands = by_name.get(nrm(r.get("player")), [])
        pid = None
        for c in cands:
            if weeks.get((c, wk), {}).get("tm") == tm:
                pid = c
                break
        if pid is None and len(cands) == 1:
            pid = cands[0]
        if pid is None:
            miss += 1
            continue
        hit += 1
        weeks[(pid, wk)]["sn"] = sn

    for key, top in most.items():
        team[key]["sn"] = max(top, best.get(key, (0, 0))[1])
    log(f"   matched {hit} snap rows, {miss} unmatched, "
        f"{len(most)} team-week denominators")

    # ---- Next Gen Stats: rates that have no count decomposition.
    # These must distinguish "measured as zero" from "not measured". num()
    # returns 0.0 for a blank, which would turn an absent reading into a real
    # one and drag a weighted mean toward zero, so parse strictly here.
    def opt(v):
        if v is None or v == "" or v == "NA":
            return None
        try:
            return round(float(v), 3)
        except (TypeError, ValueError):
            return None

    def put(d, k, v):
        if v is not None:
            d[k] = v

    log("4. next gen stats")
    ngs_hit = 0
    for kind, url in (("rec", "ngs_receiving.csv.gz"),
                      ("pass", "ngs_passing.csv.gz"),
                      ("rush", "ngs_rushing.csv.gz")):
        for r in rows(f"{NFLVERSE}/nextgen_stats/{url}", optional=True):
            if i(r.get("season")) != season or r.get("season_type") != "REG":
                continue
            wk = i(r.get("week"))
            pid = r.get("player_gsis_id")
            if not wk or not pid or (pid, wk) not in weeks:
                continue
            d = weeks[(pid, wk)]
            if kind == "rec":
                put(d, "sep", opt(r.get("avg_separation")))
                put(d, "yacoe", opt(r.get("avg_yac_above_expectation")))
            elif kind == "pass":
                put(d, "ttt", opt(r.get("avg_time_to_throw")))
                put(d, "iay", opt(r.get("avg_intended_air_yards")))
            else:
                put(d, "ryoe", opt(r.get("rush_yards_over_expected_per_att")))
            ngs_hit += 1
    log(f"   {ngs_hit} ngs values attached")

    # ---- expected fantasy points, from ffopportunity (ffverse, not nflverse).
    # Their model prices each target and carry by its depth and field position,
    # which is what makes "he is not scoring but the role is there" a readable
    # number rather than a hunch. Optional: if the release is unavailable the
    # vs-expected column simply does not render.
    log("5. expected fantasy points")
    has_exp = False
    ep = rows(f"{FFOPP}/ep_weekly_{season}.csv", optional=True)
    ep_hit = 0
    for r in ep:
        wk, pid = i(r.get("week")), r.get("player_id")
        if not wk or not pid or (pid, wk) not in weeks:
            continue
        xfp = opt(r.get("total_fantasy_points_exp"))
        xrec = opt(r.get("receptions_exp"))
        if xfp is None:
            continue
        d = weeks[(pid, wk)]
        d["xfp"] = round(xfp, 2)
        # Receptions are worth a full point in their model, so half PPR is
        # recovered exactly by taking half a point back off both sides. No
        # second model is needed, and nothing is approximated.
        d["xrec"] = round(xrec, 2) if xrec is not None else 0.0
        ep_hit += 1
    has_exp = ep_hit > 0
    log(f"   {ep_hit} expected-point weeks attached"
        if has_exp else f"   no expected points for {season} — that column will be hidden")

    # ---- routes, from participation. Optional by design (see module docstring).
    log("6. participation (routes)")
    has_routes = False
    part = rows(f"{NFLVERSE}/pbp_participation/pbp_participation_{season}.csv",
                optional=True)
    if part:
        pressure_db = defaultdict(int)
        matched = 0
        for r in part:
            gid = r.get("nflverse_game_id") or ""
            bits = gid.split("_")
            if len(bits) < 2 or not bits[1].isdigit():
                continue
            wk = int(bits[1])
            # The denominator is the dropback set taken from play by play, NOT
            # anything in this file. was_pressure reads "FALSE" on run plays
            # rather than being blank, so testing it for emptiness counts every
            # snap of the game and inflates routes by well over 2x.
            # This file names the column play_id; nflverse_play_id is the FTN
            # charting file's spelling and is absent here.
            if (gid, str(i(r.get("play_id")))) not in dropbacks:
                continue
            matched += 1
            for pid in (r.get("offense_players") or "").split(";"):
                d = weeks.get((pid, wk))
                if d is not None and d.get("tm"):
                    d["rt"] = d.get("rt", 0) + 1
            if str(r.get("was_pressure")).strip().upper() == "TRUE":
                pressure_db[(r.get("possession_team") or "").upper(), wk] += 1
        for (tm, wk), n in pressure_db.items():
            team[(tm, wk)]["prs"] = n
        log(f"   {matched} of {len(part)} participation rows were dropbacks")
        has_routes = any("rt" in d for d in weeks.values())
        log(f"   routes reconstructed for {sum(1 for d in weeks.values() if 'rt' in d)} player-weeks")
    else:
        log(f"   participation not published for {season} — "
            f"Routes / TPRR / YPRR will be hidden on the page")

    # ---- emit
    wk_list = sorted({wk for (_, wk) in weeks})
    out_rows = []
    for (pid, wk), d in weeks.items():
        if not d.get("tm"):
            continue
        # Drop player-weeks with no involvement at all; they are inactives and
        # would only dilute the window averages.
        if not any(d.get(k) for k in ("sn", "tg", "ca", "att")):
            continue
        row = {"i": pid, "w": wk, "t": d["tm"], "o": opp.get((d["tm"], wk), "")}
        for k, v in d.items():
            if k == "tm":
                continue
            # Zeros are dropped to keep the file small, which is safe for counts
            # because the page reads a missing count as zero. It is NOT safe for
            # the Next Gen rates: dropping one removes that week's WEIGHT from
            # the weighted mean, so a genuine 0.00 reading silently deletes the
            # whole game. Jonathan Taylor's week 2 RYOE of 0.0035 did exactly
            # that and moved his season figure by a third.
            if not v and k not in KEEP_ZERO:
                continue
            row[k] = r2(v) if isinstance(v, float) and k not in KEEP_ZERO else v
        out_rows.append(row)

    out_teams = {}
    for (tm, wk), t in team.items():
        out_teams[f"{tm}|{wk}"] = {k: (r2(v) if isinstance(v, float) else v)
                                   for k, v in t.items() if v}

    return {
        "built": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": season,
        "weeks": wk_list,
        "hasRoutes": has_routes,
        "hasExp": has_exp,
        "players": sorted(out_players.values(), key=lambda m: m["n"]),
        "rows": out_rows,
        "teams": out_teams,
    }


# --------------------------------------------------------------------------
# DraftKings
# --------------------------------------------------------------------------
def dk_json(url, optional=True):
    blob = fetch(url, attempts=3, optional=optional)
    if blob is None:
        return None
    try:
        return json.loads(blob.decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        log(f"   unparseable json from {url[:70]}: {e}")
        return None


# In-game ("2H", "4Q") and simulated ("Madden Stream") slates share the lobby
# with real ones and sometimes outdraw them.
NOVELTY_RE = re.compile(r"\b([1-4]Q|[12]H|Madden|Simulated|Stream|Tiers|Solo)\b", re.I)


def dk_team(p):
    """The player's own team abbreviation.

    DK gives the fixture's home and away abbreviations on every player plus the
    player's team id, so picking one requires comparing ids. Reaching straight
    for htabbr stamps the home team on both rosters.
    """
    tid = p.get("tid")
    for id_key, ab_key in (("htid", "htabbr"), ("atid", "atabbr")):
        if tid is not None and p.get(id_key) is not None and str(p.get(id_key)) == str(tid):
            return (p.get(ab_key) or "").upper()
    return (p.get("tsa") or p.get("ta") or p.get("teamAbbreviation") or "").upper()


def parse_dk_date(s):
    if not s:
        return None
    s = str(s)
    if s.startswith("/Date("):
        try:
            ms = int(re.split(r"[-+]", s[6:-2])[0])
            return datetime.datetime.utcfromtimestamp(ms / 1000)
        except Exception:  # noqa: BLE001
            return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "").split(".")[0])
    except Exception:  # noqa: BLE001
        return None


def build_dk():
    """Salaries for the open NFL slates.

    api.draftkings.com 403s GitHub runners, so this uses www exclusively — the
    same host the golf fetcher fell back to. A failure here is not fatal: the
    page drops the salary and Edge columns and still shows every stat.
    """
    log("7. draftkings nfl slates")
    lobby = dk_json("https://www.draftkings.com/lobby/getcontests?sport=NFL")
    if not lobby:
        log("   lobby unreachable — skipping salaries")
        return None

    entries = defaultdict(int)
    for c in lobby.get("Contests") or []:
        dg = c.get("dg") or c.get("draftGroupId")
        if dg:
            entries[int(dg)] += c.get("m") or 0
    meta = {int(d.get("DraftGroupId")): d for d in (lobby.get("DraftGroups") or [])
            if d.get("DraftGroupId")}

    slates = []
    for dg in sorted(entries, key=lambda k: -entries[k])[:20]:
        m = meta.get(dg, {})
        suffix = (m.get("ContestStartTimeSuffix") or "").strip()
        # Quarter and half slates reprice mid-game and a Madden stream is not a
        # real game at all. Neither belongs next to season-long usage stats.
        if NOVELTY_RE.search(suffix):
            log(f"   dg={dg}: skipping novelty slate {suffix!r}")
            continue
        data = dk_json(f"https://www.draftkings.com/lineup/getavailableplayers?draftGroupId={dg}")
        if not data:
            continue
        pool = data.get("playerList") or data.get("players") or []
        players = []
        for p in pool:
            # fn/ln are the reliable name fields on this feed. "pn" is the
            # POSITION name here, not the player name — reading it as a name is
            # what silently collapsed the golf pool once already.
            name = (" ".join(x for x in (p.get("fn"), p.get("ln")) if x).strip()
                    or (p.get("displayName") or p.get("name") or "").strip())
            sal = p.get("s") or p.get("salary")
            pos = (p.get("pn") or p.get("position") or "").upper()
            if not name or not isinstance(sal, (int, float)):
                continue
            players.append({"n": name, "pos": pos, "sal": int(sal), "tm": dk_team(p)})
        if len(players) < 50:
            log(f"   dg={dg}: only {len(players)} players, ignoring")
            continue

        # Best-ball and snake draft pools come back through the same endpoint,
        # but their "salary" field is a draft rank: 1..N, one per player. No
        # salary-cap game on DK tops out under $4,000, so that separates them
        # without having to recognise every draft product by name.
        top = max(p["sal"] for p in players)
        if top < 4000:
            log(f"   dg={dg}: top 'salary' is {top} over {len(players)} players — "
                f"a draft pool, not a salary cap slate. Skipping.")
            continue

        teams = {p["tm"] for p in players if p["tm"]}
        # A showdown prices a captain at 1.5x, so its salaries are not
        # comparable with a classic slate's and must never be mixed in.
        kind = ("showdown" if len(teams) <= 2
                else "classic" if len(teams) >= 6 and len(players) >= 150
                else "small")
        start = parse_dk_date(m.get("StartDateEst") or m.get("StartDate"))
        day = start.strftime("%a %b %-d") if start else ""
        if kind == "classic":
            name = f"{day} Main · {len(teams) // 2} games" if day else f"Main · {len(teams) // 2} games"
        else:
            name = suffix or day or f"dg {dg}"
            if kind == "showdown":
                name = f"Showdown {name}"
        slates.append({
            "dg": dg, "name": name, "kind": kind,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ") if start else "",
            "entries": entries[dg], "teams": len(teams), "players": players,
        })
        log(f"   dg={dg} {kind:<9} {len(players):>4} players, {len(teams):>2} teams, "
            f"{entries[dg]} entries — {name}")

    if not slates:
        return None
    # Classic first regardless of entry count. A single-game showdown routinely
    # outdraws the main slate, and defaulting a season-long stats page to
    # captain-mode pricing for one game would be wrong every Sunday.
    rank = {"classic": 0, "small": 1, "showdown": 2}
    slates.sort(key=lambda s: (rank.get(s["kind"], 3), -s["entries"]))
    return {
        "built": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "slates": slates,
    }


def write(name, payload):
    path = os.path.join(DATA, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"   wrote {name} ({os.path.getsize(path) // 1024} KB)")


def current_season():
    now = datetime.date.today()
    # The NFL season is named for the year it starts, so Jan-Jul belongs to the
    # previous year's season, not the current calendar year.
    return now.year if now.month >= 8 else now.year - 1


def update_index(season, stats):
    """Keep data/nfl_index.json in step with whatever season files exist.

    The page reads this to fill the season dropdown. Writing it from here rather
    than hardcoding a list in the JS means a season archived once keeps showing
    up without anyone editing the front end.
    """
    path = os.path.join(DATA, "nfl_index.json")
    idx = {"seasons": [], "current": current_season()}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:  # noqa: BLE001
            pass
    seasons = {int(s["season"]): s for s in idx.get("seasons", [])}
    seasons[season] = {
        "season": season,
        "file": f"nfl_{season}.json",
        "weeks": stats["weeks"],
        "hasRoutes": stats["hasRoutes"],
        "hasExp": stats.get("hasExp", False),
        "built": stats["built"],
    }
    idx["seasons"] = sorted(seasons.values(), key=lambda s: -s["season"])
    idx["current"] = current_season()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(idx, f, separators=(",", ":"))
    log(f"   index now lists seasons {[s['season'] for s in idx['seasons']]}")


def main():
    # NFL_SEASON takes one year or a comma list, so a single manual run can
    # backfill the archive seasons that still carry participation data.
    raw = (os.environ.get("NFL_SEASON") or "").strip()
    seasons = [int(x) for x in re.split(r"[,\s]+", raw) if x.strip().isdigit()] \
        if raw else [current_season()]

    built_any = False
    for season in seasons:
        log(f"=== season {season} ===")
        stats = build_stats(season)
        if not stats:
            log(f"nothing built for {season}")
            continue
        write(f"nfl_{season}.json", stats)
        update_index(season, stats)
        built_any = True

    # Salaries describe the slate that is open right now, so they are fetched
    # once regardless of how many seasons were built.
    try:
        dk = build_dk()
    except Exception as e:  # noqa: BLE001
        log(f"   dk fetch failed: {e}")
        dk = None
    if dk:
        write("nfl_dk.json", dk)
    else:
        log("no dk salaries — leaving data/nfl_dk.json alone")

    return 0 if built_any else 1


if __name__ == "__main__":
    sys.exit(main())
