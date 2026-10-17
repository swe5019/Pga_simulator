#!/usr/bin/env python3
"""
enrich_props.py — attach historical hit rates to each Underdog prop line.

Reads data/nfl_props.json (written by fetch_props.py) and the per season
nfl_<year>.json files, and writes data/nfl_props_full.json, which is the file
the page loads.

WHAT A HIT RATE IS HERE
No historical odds are needed, which is the thing that makes this cheap. "Under
in 3 of 4" just means: take this player's last four games, count how many had
fewer receptions than the line sitting in front of us today. So the question is
always asked against TODAY's line, which is what a bettor actually cares about.

  L1  this season
  L2  this season plus last
  L3  this season plus the two before

Each window reports hits, games and rate, and the three are blended 20/40/40
into one number, weighted toward the longer samples because four games of
football is mostly noise.

WHERE THE HARDER MARKETS COME FROM
A box score total cannot answer "longest reception" or "receptions in the first
quarter", so those read from nfl_pbp_<season>.json, which holds each player's
individual plays bucketed by period. Longest anything is the best single play;
a 1Q market sums the first bucket; a 1H market sums the first two.

A game whose play by play is missing is DROPPED from those windows rather than
counted as a zero. Counting it as zero is the dangerous failure: every week
would read "0 first quarter receptions" and the under would look like a lock.
A player who played but never touched the ball is a genuine zero, and is kept.

WHAT IT STILL CANNOT DO
Kicking and defensive props (field goals, tackles, sacks) are not in the stats
pipeline at all, so they come through with no history rather than a guess. The
run prints exactly how many rows fell into each bucket.
"""
import json
import math
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Underdog's stat name -> how to compute it from one player-week row.
# A row is the weekly record written by fetch_nfl.py.
def _sum(*keys):
    return lambda r: sum(r.get(k, 0) for k in keys)


# Period buckets, as written by fetch_nfl_pbp.py: 0 first quarter, 1 second
# quarter, 2 everything after half time.
Q1 = (0,)
H1 = (0, 1)
FULL = (0, 1, 2)


def _periods(r, idxs):
    """The requested buckets, or None when this game has no play by play.

    None is not zero. None means unknown, and an unknown game is dropped from
    the sample; zero means he was out there and did nothing, which is real
    evidence and is kept."""
    ps = r.get("_p")
    if ps is None:
        return None
    return [ps[k] for k in idxs if k < len(ps)]


def _count(idxs, *keys):
    """How many plays of these kinds happened in these buckets. Receptions is
    the length of the catch list, targets that plus the uncaught ones."""
    def fn(r):
        ps = _periods(r, idxs)
        if ps is None:
            return None
        n = 0
        for p in ps:
            for k in keys:
                v = p.get(k, 0)
                n += len(v) if isinstance(v, list) else v
        return n
    return fn


def _yards(idxs, *keys):
    """Total yardage. A plain int key is lateral yardage, which counts toward a
    total without being a play of its own."""
    def fn(r):
        ps = _periods(r, idxs)
        if ps is None:
            return None
        t = 0
        for p in ps:
            for k in keys:
                v = p.get(k, 0)
                t += sum(v) if isinstance(v, list) else v
        return t
    return fn


def _longest(key):
    """The best single play of the whole game.

    Laterals are excluded on purpose: a two yard catch that someone else ran
    eighty yards with is a two yard reception, which is how the NFL scores it
    and how the market settles it. A player with none of these plays has a
    longest of zero, which is a real outcome rather than a missing one."""
    def fn(r):
        ps = _periods(r, FULL)
        if ps is None:
            return None
        best = 0
        for p in ps:
            v = p.get(key)
            if v:
                best = max(best, max(v))
        return best
    return fn


def _scored(flag_key):
    """Was he the game's first, or last, touchdown scorer.

    Defensive and special teams scores are in the ordering, so a pick six
    opening the scoring correctly means no offensive player was first."""
    def fn(r):
        if r.get("_p") is None:
            return None
        return 1 if r.get(flag_key) else 0
    return fn


STAT_FN = {
    "Receptions": _sum("rec"),
    "Receiving Yards": _sum("ry"),
    "Targets": _sum("tg"),
    "Rush Yards": _sum("ru"),
    "Rush Attempts": _sum("ca"),
    "Rush + Rec Yards": _sum("ru", "ry"),
    "Pass Yards": _sum("py"),
    "Pass Attempts": _sum("att"),
    "Completions": _sum("cmp"),
    "Pass TDs": _sum("ptd"),
    "Interceptions": _sum("int"),
    "Pass + Rush Yards": _sum("py", "ru"),
    "Fumbles Lost": _sum("fl"),
    "Rec TDs": _sum("rtd"),
    "Rush TDs": _sum("utd"),
    "Rush + Rec TDs": _sum("rtd", "utd"),
    "Anytime TD": _sum("rtd", "utd"),
    # Already in the box score, just not previously mapped to Underdog's name
    # for them.
    "INTs Thrown": _sum("int"),
    "Fantasy Points": _sum("fp"),

    # ---- from the play by play
    "Longest Reception": _longest("ry"),
    "Longest Rush": _longest("uy"),
    "Longest Completion": _longest("py"),

    "1Q Receptions": _count(Q1, "ry"),
    "1H Receptions": _count(H1, "ry"),
    "1Q Targets": _count(Q1, "ry", "inc"),
    "1H Targets": _count(H1, "ry", "inc"),
    "1Q Rec Yards": _yards(Q1, "ry", "lry"),
    "1H Rec Yards": _yards(H1, "ry", "lry"),
    "1Q Rush Yards": _yards(Q1, "uy", "luy"),
    "1H Rush Yards": _yards(H1, "uy", "luy"),
    "1Q Rush Attempts": _count(Q1, "uy"),
    "1H Rush Attempts": _count(H1, "uy"),
    "1Q Pass Yards": _yards(Q1, "py"),
    "1H Pass Yards": _yards(H1, "py"),
    "1Q Completions": _count(Q1, "py"),
    "1H Completions": _count(H1, "py"),
    "1Q Pass Attempts": _count(Q1, "py", "pinc"),
    "1H Pass Attempts": _count(H1, "py", "pinc"),
    "1Q Pass TDs": _count(Q1, "ptd"),
    "1H Pass TDs": _count(H1, "ptd"),
    "1Q Rush + Rec TDs": _count(Q1, "rtd", "utd"),
    "1H Rush + Rec TDs": _count(H1, "rtd", "utd"),
    "1Q Rush + Rec Yards": _yards(Q1, "uy", "luy", "ry", "lry"),
    "1H Rush + Rec Yards": _yards(H1, "uy", "luy", "ry", "lry"),

    "First TD Scorer": _scored("_ftd"),
    "Last TD Scorer": _scored("_ltd"),
}

# Which defensive multiplier a market is adjusted by. A derived market has no
# multiplier of its own, because there is no "longest reception allowed" or
# "first quarter receiving yards allowed" to measure without slicing the sample
# until it means nothing. So each borrows its parent's: how a defense treats
# receiving yards is the best available read on how it treats the longest one
# and on the first quarter of one.
#
# This lives here and is imported by the simulation, so the multiplier shown in
# the column is always the multiplier the simulation applied. Two copies of
# this map would drift and the page would quietly contradict itself.
MATCHUP_STAT = {
    "Longest Reception": "Receiving Yards",
    "Longest Rush": "Rush Yards",
    "Longest Completion": "Pass Yards",
    "1Q Rec Yards": "Receiving Yards", "1H Rec Yards": "Receiving Yards",
    "1Q Receptions": "Receptions", "1H Receptions": "Receptions",
    "1Q Targets": "Targets", "1H Targets": "Targets",
    "1Q Rush Yards": "Rush Yards", "1H Rush Yards": "Rush Yards",
    "1Q Rush Attempts": "Rush Attempts", "1H Rush Attempts": "Rush Attempts",
    "1Q Pass Yards": "Pass Yards", "1H Pass Yards": "Pass Yards",
    "1Q Completions": "Completions", "1H Completions": "Completions",
    "1Q Pass Attempts": "Pass Attempts", "1H Pass Attempts": "Pass Attempts",
    "1Q Pass TDs": "Pass TDs", "1H Pass TDs": "Pass TDs",
    "1Q Rush + Rec TDs": "Anytime TD", "1H Rush + Rec TDs": "Anytime TD",
    "1Q Rush + Rec Yards": "Rush + Rec Yards",
    "1H Rush + Rec Yards": "Rush + Rec Yards",
}

# Blend weights across the three windows. Weighted away from this season on
# purpose: a four game sample swings wildly, and the longer windows are what
# stop one freak afternoon dominating the number.
BLEND = {"l1": 0.20, "l2": 0.40, "l3": 0.40}

# Shrinkage, in games. A player's own hit rate is pulled toward the price with
# this much weight, so a five game record barely moves off the market and a
# forty game one nearly stands on its own.
PRIOR_GAMES = 12
# Under this many games in the widest window, history is flagged as thin.
MIN_GAMES = 8
# How many recent games define "his role now".
ROLE_GAMES = 3
# Snap share distance at which a past game counts about a third. 0.22 means a
# 60% snap starter still gets partial credit for his 40% games and almost none
# for his 15% ones.
ROLE_SCALE = 0.22


def log(*a):
    print(*a, flush=True)


def nrm(s):
    """Name key. Must survive 'J.K. Dobbins' against 'J.K. Dobbins' and
    'Jaxon Smith-Njigba' against itself, plus the Jr/Sr/III disagreements
    between feeds."""
    s = (s or "").lower()
    s = re.sub(r"[.'`,]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z]+", "", s)


def load_seasons():
    """Newest first. Whatever seasons are on disk get used; L3 silently becomes
    a two season window until the 2024 backfill lands, and the games count in
    the output says so."""
    idx_path = os.path.join(DATA, "nfl_index.json")
    if not os.path.exists(idx_path):
        raise SystemExit("no nfl_index.json; run fetch_nfl.py first")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)
    out = {}
    for s in sorted(idx["seasons"], key=lambda s: -int(s["season"])):
        p = os.path.join(DATA, s["file"])
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            out[int(s["season"])] = json.load(f)
    return out, int(idx.get("current") or max(out))


def load_pbp(years):
    """season -> {(pid, week): record}. A season with no file is absent from
    the result, which is what makes its games drop out of the split and longest
    markets instead of reading as zeros."""
    out = {}
    for y in years:
        p = os.path.join(DATA, f"nfl_pbp_{y}.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        out[y] = {(r["i"], r["w"]): r for r in doc["logs"]}
    return out


def game_logs(seasons, pbp):
    """name key -> {season: [row, ...]}, newest first, each row tagged with the
    share of his team's offensive snaps he played that week.

    Snap share is what makes a historical game comparable or not. A back who
    took 23% of the snaps is a different player from the same man taking 60%,
    and counting both as one record is how a backup's quiet games get read as
    evidence about a starter."""
    logs = defaultdict(lambda: defaultdict(list))
    for yr, doc in seasons.items():
        meta = {p["id"]: p for p in doc["players"]}
        plays = pbp.get(yr)
        for r in doc["rows"]:
            m = meta.get(r["i"])
            if not m:
                continue
            t = doc["teams"].get(f"{r['t']}|{r['w']}") or {}
            tsn = t.get("sn") or 0
            r["_snap"] = (r.get("sn", 0) / tsn) if tsn else None
            r["_yr"] = yr
            if plays is not None:
                # Within a season that HAS play by play, a player with no
                # record simply never touched the ball, so his splits and
                # longests are genuinely zero. Three empty buckets say that.
                rec = plays.get((r["i"], r["w"]))
                if rec:
                    r["_p"] = [rec.get(f"p{k}") or {} for k in (0, 1, 2)]
                    r["_ftd"] = rec.get("ftd", 0)
                    r["_ltd"] = rec.get("ltd", 0)
                else:
                    r["_p"] = [{}, {}, {}]
                    r["_ftd"] = r["_ltd"] = 0
            logs[nrm(m["n"])][yr].append(r)
    for k in logs:
        for yr in logs[k]:
            logs[k][yr].sort(key=lambda r: -r["w"])
    return logs


def initial_last(name):
    """First initial plus surname, which survives a first name being written
    two ways. "Joshua Palmer" and "Josh Palmer" both reduce to jpalmer."""
    t = re.sub(r"[.'`,]", "", name or "").strip()
    t = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", t, flags=re.I).strip()
    bits = [b for b in t.split() if b]
    if len(bits) < 2:
        return nrm(name)
    return re.sub(r"[^a-z]+", "", (bits[0][:1] + bits[-1]).lower())


def resolve_names(props, logs, logs_display, meta_pos):
    """Join the market's spelling of a name to the stats' spelling.

    The two feeds do not share an id, so everything keys off the name, and a
    name can be written two ways. The market priced "Joshua Palmer" while the
    statistics call him "Josh Palmer", and the two never met: four betting
    lines simply failed to anchor his projection and nothing anywhere said so.
    The population check found it, which is the entire reason that check
    exists.

    The fallback is deliberately narrow. Matching on surname alone would
    cheerfully merge two different players, so a candidate must share the
    first initial AND the surname AND the position, and must be the only one
    who does. Anything ambiguous is left unmatched, because a wrong join is
    far worse than a missing one: it would attach one player's betting lines
    to another player's history."""
    # A log key is already normalised with the spaces gone, so the first
    # initial cannot be recovered from it. The display names come in
    # separately for exactly that reason.
    by_il = defaultdict(list)
    for key, disp in logs_display.items():
        by_il[initial_last(disp)].append(key)

    fixed = {}
    for p in props:
        k = nrm(p["player"])
        if k in logs:
            continue
        cands = [c for c in by_il.get(initial_last(p["player"]), [])
                 if meta_pos.get(c) == p.get("pos")]
        # An identity mapping is not an alias. Those arise for a player who
        # is on a roster but has no game log, and reporting them as resolved
        # names would bury the real ones.
        if len(cands) == 1 and cands[0] != k:
            fixed[k] = cands[0]
    return fixed


def load_injuries():
    """Who is unavailable this week, as written by fetch_nfl_injuries.py.

    Optional: with no file, everything falls back to the old behaviour of
    reading a role purely from games played."""
    path = os.path.join(DATA, "nfl_injuries.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def snap_table(seasons):
    """Two lookups that together answer "was this teammate available then".

    snaps   (season, team, week) -> {player id: share of team snaps}
    roster  (season, team) -> {player id} that appeared for them at all

    The roster half is not optional, and leaving it out was a real bug. A
    teammate missing from one week's snap data has two completely different
    explanations: he was hurt, or he was playing for somebody else that year.
    Reading the second as the first told the model that Woody Marks had
    seventeen games without David Montgomery, when in fact they were only
    teammates for five, and the "role without him" it computed was really his
    role on a different team in a different season."""
    snaps = defaultdict(dict)
    roster = defaultdict(set)
    for yr, doc in seasons.items():
        for r in doc["rows"]:
            roster[(yr, r["t"])].add(r["i"])
            t = doc["teams"].get(f"{r['t']}|{r['w']}") or {}
            tsn = t.get("sn") or 0
            if tsn:
                snaps[(yr, r["t"], r["w"])][r["i"]] = r.get("sn", 0) / tsn
    return snaps, roster


# A teammate counts as absent from a past game at or below this share of the
# team's snaps. Not zero, because a starter who got hurt early still appears
# with a handful of snaps, and that game is exactly the one worth learning
# from.
ABSENT_SHARE = 0.25
# A context role resting on fewer than this many games is kept but marked, so
# it shrinks toward the market instead of standing on its own.
CTX_THIN = 3
# The measured role increase, in points of snap share, below which the
# difference is treated as noise and nothing is changed.
MIN_ROLE_GAIN = 8.0
# A teammate going out only matters if he was doing something. This is his
# minimum mean snap share across the season to be worth reacting to.
MIN_TEAMMATE_ROLE = 0.20
# The player himself needs a real role for any of this to mean anything.
MIN_OWN_ROLE = 0.05


def build_role_context(logs, seasons, current, injuries, meta_pos, meta_team):
    """The role each player should be weighted against THIS week, given who is
    out, plus enough detail for the page to explain itself.

    THE PROBLEM. A role read from games played is an average of the job he had,
    not the job he is about to have. When the man ahead of him is out, that
    average is wrong in the one direction that matters, and wrong while looking
    perfectly well evidenced: a back whose starter got hurt late last week
    reads 55% of snaps, because that averages two games as the backup with the
    one game he finished as the starter.

    IT DOES NOT GUESS WHO IS AHEAD OF WHOM, and the first attempt at this did,
    which was wrong twice over. Deciding by recent snap share is corrupted by
    the very injury being reacted to: the starter's average is dragged below
    the backup's by the game he got hurt in, so the code concluded the backup
    was the senior man and did nothing. And snap share is the wrong yardstick
    for a running back anyway, since the lead back takes the carries while the
    other plays passing downs, so neither is "ahead" on snaps.

    SO IT MEASURES THE DIFFERENCE INSTEAD. Split his games by whether that
    teammate was on the field, and compare his role in each. If he plays
    materially more without the man, that is the effect, measured on him
    specifically, with no assumption about depth charts. If he does not,
    nothing changes. This is self correcting in a way a seniority test cannot
    be, and it catches cases a depth chart would miss.

    WHAT IT REFUSES TO DO. If he has never played without that teammate there
    is nothing to learn from and no honest number to produce, so it says so and
    the page leans on the market. A context built on one or two games is kept
    but marked thin, which makes it shrink toward the market rather than stand
    alone. A player who is himself out gets no boost from anybody, because his
    own status is the dominant fact about him."""
    if not injuries:
        return {}
    snaps, roster = snap_table(seasons)

    # Who is unavailable, by team and position. Only designations worth acting
    # on: an official ruling, or a player who has not practised at all.
    unavailable = defaultdict(list)
    himself = {}
    for pl in injuries.get("players", []):
        if pl.get("conf") not in ("ruled", "strong"):
            continue
        if not pl.get("id") or not pl.get("t"):
            continue
        unavailable[(pl["t"], pl["p"])].append(pl)
        himself[nrm(pl["n"])] = pl
    if not unavailable:
        return {}

    def season_share(key):
        """His mean snap share across this season, which is a steadier read on
        the size of his job than the last few games."""
        rows = logs.get(key, {}).get(current, [])
        vals = [r["_snap"] for r in rows if r.get("_snap") is not None]
        return (sum(vals) / len(vals)) if vals else None

    out = {}
    for key, byyear in logs.items():
        pos, team = meta_pos.get(key), meta_team.get(key)
        if not pos or not team:
            continue
        mine = season_share(key)
        if mine is None or mine < MIN_OWN_ROLE:
            continue

        # His own availability comes first. A player who has not practised is
        # not a man about to be handed more work.
        own = himself.get(key)
        if own is not None:
            out[key] = {"selfOut": True, "selfBasis": own["basis"],
                        "selfInjury": own.get("injury") or "",
                        "role": None, "unknown": False, "ctxN": 0,
                        "roleBefore": round(mine * 100, 1),
                        "outAhead": "", "outBasis": ""}
            continue

        gains = []
        for pl in unavailable[(team, pos)]:
            tkey = nrm(pl["n"])
            if tkey == key:
                continue
            theirs = season_share(tkey)
            if theirs is None or theirs < MIN_TEAMMATE_ROLE:
                continue
            tid = pl["id"]
            with_him, without_him = [], []
            for yr, rows in byyear.items():
                for r in rows:
                    if r.get("_snap") is None:
                        continue
                    # Only games they were actually teammates for. Otherwise
                    # "without him" quietly becomes "before he joined", which
                    # is a different player's situation entirely.
                    if tid not in roster.get((yr, r["t"]), ()):
                        continue
                    tbl = snaps.get((yr, r["t"], r["w"])) or {}
                    share = tbl.get(tid)
                    if share is None or share <= ABSENT_SHARE:
                        without_him.append(r["_snap"])
                    else:
                        with_him.append(r["_snap"])
            if not without_him or not with_him:
                # Either never played without him, which is unmeasurable, or
                # never played with him, which means he is not the constraint.
                if not without_him:
                    gains.append((None, pl, 0, None, None))
                continue
            a = sum(without_him) / len(without_him)
            b = sum(with_him) / len(with_him)
            gains.append(((a - b) * 100, pl, len(without_him), a, b))

        measured = [g for g in gains if g[0] is not None]
        if not measured:
            unmeasurable = [g for g in gains if g[0] is None]
            if unmeasurable:
                pl = unmeasurable[0][1]
                out[key] = {
                    "outAhead": pl["n"], "outBasis": f"{pl['n']} {pl['basis']}",
                    "roleBefore": round(mine * 100, 1), "ctxN": 0,
                    "role": None, "unknown": True}
            continue

        # The teammate whose absence moves him most.
        gain, pl, n, a, b = max(measured, key=lambda g: g[0])
        if gain < MIN_ROLE_GAIN:
            continue
        out[key] = {
            "outAhead": pl["n"],
            "outBasis": f"{pl['n']} {pl['basis']}"
                        + (f" ({pl['injury']})" if pl.get("injury") else ""),
            "roleBefore": round(b * 100, 1),
            "role": a,
            "roleCtx": round(a * 100, 1),
            "roleGain": round(gain, 1),
            "ctxN": n,
            "thin": n < CTX_THIN,
        }
    return out


def current_role(logs_for_player, current_season):
    """His role now, as mean snap share over the most recent games played.

    Taken from this season only. Last year's role is exactly the thing we are
    trying not to be fooled by."""
    rows = logs_for_player.get(current_season, [])
    snaps = [r["_snap"] for r in rows[:ROLE_GAMES] if r.get("_snap") is not None]
    return sum(snaps) / len(snaps) if snaps else None


def role_weight(snap, role_now):
    """How much a past game counts, by how close its role was to today's.

    A game at the same snap share counts fully, one 22 points away counts about
    a third, one 45 points away barely at all. Gaussian rather than a cutoff so
    the weight falls away smoothly instead of flipping at an arbitrary line.
    With no snap data, or no known current role, the game counts fully: better
    to fall back to a plain hit rate than to invent a weight."""
    if snap is None or role_now is None:
        return 1.0
    return math.exp(-(((snap - role_now) / ROLE_SCALE) ** 2))


def hit_rate(rows, fn, line, side, role_now=None):
    """Games clearing the line, counted twice over.

    Raw: the plain count, which is what a reader expects to see as "3 of 4".
    Weighted: the same games weighted by how close each one's role was to his
    role today, which is what should actually be leaned on.

    Returns (hits, n, weighted_rate, effective_n). Effective n is Kish's
    formula, the number of equally weighted games the weighted sample is worth,
    and it is what shrinkage keys off: thirty backup games are not thirty games
    of evidence about a starter.

    Underdog lines carry a .5 so there are no pushes, but the comparison is
    written strictly either way."""
    hits = n = 0
    wsum = w2sum = whit = 0.0
    for r in rows:
        v = fn(r)
        if v is None:
            # This game cannot answer the question. Dropping it is the only
            # honest option: counted as a zero it would read as evidence for
            # the under, and counted as a hit it would read as evidence for the
            # over.
            continue
        ok = (v > line) if side == "over" else (v < line)
        n += 1
        hits += 1 if ok else 0
        w = role_weight(r.get("_snap"), role_now)
        wsum += w
        w2sum += w * w
        whit += w if ok else 0.0
    wrate = (whit / wsum) if wsum > 0 else None
    eff = (wsum * wsum / w2sum) if w2sum > 0 else 0.0
    return hits, n, wrate, eff


def main():
    props_path = os.path.join(DATA, "nfl_props.json")
    if not os.path.exists(props_path):
        log("no nfl_props.json; run fetch_props.py first")
        return 1
    with open(props_path, encoding="utf-8") as f:
        doc = json.load(f)
    props = doc["props"]

    # Matchup multipliers, if they have been built. Optional: a missing file
    # costs the matchup column and nothing else.
    mpath = os.path.join(DATA, "nfl_matchups.json")
    matchups = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            matchups = json.load(f).get("matchups") or {}
        log(f"{len(matchups):,} matchup combinations loaded")
    else:
        log("no nfl_matchups.json; matchup column will be empty")

    # The market's genuine opinion, with the house edge taken out. Both
    # break-evens on a line sum to about 105%, and that extra 5% is Underdog's
    # cut, not a belief about the player. Shrinking toward the priced number
    # therefore drags both sides upward and produces a pair of probabilities
    # that cannot both be true. So shrink toward the DE-VIGGED split, which is
    # what the market actually thinks, while still measuring edge against the
    # real price, which is what has to be beaten.
    sides = defaultdict(dict)
    for p0 in props:
        if p0.get("decimal") and p0.get("line_id"):
            sides[p0["line_id"]][p0["side"]] = 1.0 / p0["decimal"]
    fair = {}
    for lid, v in sides.items():
        tot = sum(v.values())
        if tot > 0:
            for side, imp in v.items():
                # One-sided lines cannot be de-vigged, so they keep their price.
                fair[(lid, side)] = (imp / tot) if len(v) > 1 else imp

    seasons, current = load_seasons()
    years = sorted(seasons, reverse=True)
    log(f"seasons available: {years} (current {current})")
    if len(years) < 3:
        log(f"   only {len(years)} seasons on disk, so L3 covers {len(years)}; "
            f"backfill earlier years to deepen it")
    pbp = load_pbp(sorted(seasons, reverse=True))
    if pbp:
        log(f"play by play for seasons {sorted(pbp, reverse=True)} "
            f"({sum(len(v) for v in pbp.values()):,} player-weeks)")
    else:
        log("no nfl_pbp_<season>.json files; the longest and 1Q/1H markets "
            "will come through with no history. Run fetch_nfl_pbp.py.")
    logs = game_logs(seasons, pbp)
    log(f"game logs for {len(logs):,} players")

    meta_pos, meta_team = {}, {}
    for yr in sorted(seasons, reverse=True):
        for pl in seasons[yr]["players"]:
            meta_pos.setdefault(nrm(pl["n"]), pl["p"])
            meta_team.setdefault(nrm(pl["n"]), pl["t"])
    # One spelling of each name before anything joins on it.
    logs_display = {}
    for yr in sorted(seasons, reverse=True):
        for pl in seasons[yr]["players"]:
            logs_display.setdefault(nrm(pl["n"]), pl["n"])
    aliases = resolve_names(props, logs, logs_display, meta_pos)
    if aliases:
        log(f"name aliases resolved between the market and the stats: "
            + ", ".join(f"{k} -> {v}" for k, v in list(aliases.items())[:5]))
        for p in props:
            k = nrm(p["player"])
            if k in aliases:
                p["skey"] = aliases[k]

    injuries = load_injuries()
    role_ctx = build_role_context(logs, seasons, current, injuries,
                                  meta_pos, meta_team)
    if injuries:
        known = sum(1 for v in role_ctx.values() if v.get("role") is not None)
        log(f"injury report week {injuries.get('week')}: "
            f"{len(role_ctx)} players have somebody ahead of them out, "
            f"{known} of whom have games without that man to measure")
    else:
        log("no nfl_injuries.json; roles are read purely from games played. "
            "Run fetch_nfl_injuries.py to make this injury aware.")

    w1 = [current]
    w2 = [y for y in (current, current - 1) if y in seasons]
    w3 = [y for y in (current, current - 1, current - 2) if y in seasons]

    counts = defaultdict(int)
    unmatched = set()
    for p in props:
        fn = STAT_FN.get(p["stat"])
        if fn is None:
            counts["stat not supported yet"] += 1
            continue
        key = p.get("skey") or nrm(p["player"])
        if key not in logs:
            counts["player not in stats data"] += 1
            unmatched.add(p["player"])
            continue

        line, side = p["line"], p["side"]
        # Injury-aware when somebody ahead of him is out and he has games
        # without that man to learn from; otherwise the plain recent role.
        ctx = role_ctx.get(key)
        role_now = current_role(logs[key], current)
        if ctx and ctx.get("role") is not None:
            role_now = ctx["role"]
        out = {}
        eff3 = 0.0
        for label, yrs in (("l1", w1), ("l2", w2), ("l3", w3)):
            rows = [r for y in yrs for r in logs[key].get(y, [])]
            h, n, wrate, eff = hit_rate(rows, fn, line, side, role_now)
            out[label] = {
                "h": h, "n": n,
                "r": round(h / n, 4) if n else None,      # plain, for display
                "w": round(wrate, 4) if wrate is not None else None,  # role weighted
            }
            if label == "l3":
                eff3 = eff

        # Blend, using only the windows that actually have games so a player
        # with one season is not quietly scored as if he had three.
        num = den = rnum = rden = 0.0
        for label, wgt in BLEND.items():
            if out[label]["n"] > 0 and out[label]["w"] is not None:
                num += wgt * out[label]["w"]
                den += wgt
            if out[label]["r"] is not None and out[label]["n"] > 0:
                rnum += wgt * out[label]["r"]
                rden += wgt
        blended = round(num / den, 4) if den else None     # role weighted
        raw = round(rnum / rden, 4) if rden else None      # plain

        # The evidence count is the EFFECTIVE number of games, not the raw one.
        # Two different ways a raw count lies: a rookie has the same five games
        # in all three windows, and a player who just took over a starting job
        # has thirty games of a backup's workload being compared against a line
        # priced for a starter. Both read as deep history and neither is.
        n3 = out["l3"]["n"]
        eff_n = eff3
        be = (1.0 / p["decimal"]) if p.get("decimal") else None
        # What to pull toward: the de-vigged market view, falling back to the
        # raw price when the other side is missing.
        prior = fair.get((p.get("line_id"), p["side"]), be)

        # So shrink toward the price. With little evidence the honest default is
        # that the market is right, and the pull fades as games accumulate: five
        # games barely move off the line, forty are nearly all their own. This
        # degrades smoothly, unlike a cutoff that flips at an arbitrary game.
        shrunk = blended
        if blended is not None and prior is not None and eff_n > 0:
            shrunk = round((eff_n * blended + PRIOR_GAMES * prior) / (eff_n + PRIOR_GAMES), 4)

        p["hits"] = out
        p["histRaw"] = raw          # plain count, what actually happened
        p["histRate"] = shrunk      # role weighted and shrunk, what to lean on
        p["histN"] = n3             # games played
        p["histEff"] = round(eff_n, 1)   # games worth of comparable evidence
        if role_now is not None:
            p["roleNow"] = round(role_now * 100, 1)
            # Average role across the games his history is built from. When this
            # sits far below roleNow he has just moved into a bigger job and the
            # raw hit rate is describing somebody else's workload.
            rows3 = [r for y in w3 for r in logs[key].get(y, [])]
            snaps = [r["_snap"] for r in rows3 if r.get("_snap") is not None]
            if snaps:
                p["roleHist"] = round(sum(snaps) / len(snaps) * 100, 1)
                p["roleShift"] = round(p["roleNow"] - p["roleHist"], 1)
        # Below this there is not enough history to mean anything, which is the
        # normal state for a rookie. The page marks these rather than hiding
        # them: "no history" is useful information, a confident wrong number
        # is not.
        p["thin"] = eff_n < MIN_GAMES
        if ctx and ctx.get("selfOut"):
            # He is the one carrying the injury. The page says so and shows no
            # edge, because whether he plays at all is the open question.
            p["selfOut"] = True
            p["selfBasis"] = ctx["selfBasis"]
            p["selfInjury"] = ctx["selfInjury"]
            p["thin"] = True
        elif ctx:
            p["outAhead"] = ctx["outAhead"]
            p["outBasis"] = ctx["outBasis"]
            p["roleBefore"] = ctx["roleBefore"]
            if ctx.get("role") is not None:
                p["roleCtx"] = ctx["roleCtx"]
                p["roleCtxN"] = ctx["ctxN"]
                p["roleGain"] = ctx.get("roleGain")
                if ctx.get("thin"):
                    # One or two games is a hint about his new job, not a
                    # measurement of it.
                    p["thin"] = True
            else:
                # He has never played without the man who is out, so there is
                # no honest role to use and the market is the better guide.
                p["roleUnknown"] = True
                p["thin"] = True
        if shrunk is not None and be is not None:
            # Edge is still measured against the PRICE, not the fair value. The
            # vig is real money and has to be cleared.
            p["histEdge"] = round((shrunk - be) * 100, 1)
            p["fairBE"] = round(prior * 100, 1) if prior is not None else None
        # How this defense has treated this position in this stat. Attached to
        # both sides of a line unchanged: the multiplier describes the defense,
        # and which side of the number that helps is for the reader to judge.
        # Derived markets borrow their parent's, per MATCHUP_STAT.
        mstat = MATCHUP_STAT.get(p["stat"], p["stat"])
        mm = matchups.get(f"{p.get('opp', '')}|{p.get('pos', '')}|{mstat}")
        if mm:
            p["mu"] = mm["mult"]
            # Say so when the multiplier is the parent market's rather than
            # this one's, so the tooltip is not read as a measurement of
            # something that was never measured.
            if mstat != p["stat"]:
                p["muFrom"] = mstat
            p["muRaw"] = mm["raw"]
            p["muN"] = mm["n"]
            p["muGames"] = mm["games"]

        counts["enriched"] += 1
        if p["thin"]:
            counts["  of those, thin history (rookie or little played)"] += 1

    log("\nrows:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        log(f"   {v:>6}  {k}")
    if unmatched:
        log(f"\n{len(unmatched)} unmatched player names, first 15:")
        for n in sorted(unmatched)[:15]:
            log(f"   {n}")

    doc["enrichedAt"] = doc.get("built")
    doc["seasons"] = years
    out_path = os.path.join(DATA, "nfl_props_full.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"\nwrote nfl_props_full.json ({os.path.getsize(out_path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
