#!/usr/bin/env python3
"""
verify_population.py — is the right SET of players on the board.

WHY THIS EXISTS, STATED PLAINLY
Everything else that checks this pipeline verifies arithmetic. The play by
play is reconciled against the box score, the simulation's probabilities are
walked forward against real outcomes, the anchors are compared with the
market, the ownership is made to sum to the number of roster slots. All of it
passes, continuously, and all of it was passing while:

  Christian McCaffrey was silently dropped from the projections because a
  rest day read as an injury, while the market had forty one lines on him.

  Joe Mixon was projected for Houston off a 2024 roster, along with Philip
  Rivers, who is retired. 268 of 671 players were ghosts.

  Nineteen players whose betting lines had been pulled were projected anyway.

  Jayden Reed was projected for eight points and picked into optimizer
  lineups while on season ending injured reserve.

Not one of those was a wrong number. Every figure attached to Philip Rivers
was correctly computed from correctly verified data about a player who is not
on the team. Arithmetic checks are structurally blind to this, and every one
of these was found by a person reading the page, which is not a control.

So this checks membership rather than values, and it asks two questions:

  IS THE BOARD INTERNALLY COHERENT   every team fielding a quarterback, nobody
                                     projected who is not on a roster, nobody
                                     projected who stopped playing a month ago,
                                     and nobody the market prices heavily left
                                     out without a reason.

  DID IT CHANGE WITHOUT EXPLANATION  against the previous build, because a
                                     swing in who is on the board should stop
                                     the deploy, not reach the page and wait to
                                     be noticed. "Without explanation" is the
                                     load-bearing part: the prop feed re-prices
                                     every game week, so players arriving with
                                     lines and leaving without them is the
                                     market moving, not a rule changing. Only
                                     movement the market contradicts fails.

It exits non-zero on a failure, and runs before the commit step, so a bad
population leaves the previous good data live rather than replacing it.
"""
import datetime
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402

# A team fielding fewer than this at a position is missing somebody real.
MIN_PER_TEAM = {"QB": 1, "RB": 1, "WR": 2, "TE": 1}
# More than this at a position on one team means ghosts are piling up.
MAX_PER_TEAM = {"QB": 4, "RB": 7, "WR": 11, "TE": 7}
# A player carrying at least this many betting lines is one the market is
# actively pricing. Leaving him out needs a reason, and "no reason" is a bug.
PRICED_HEAVILY = 4
# Only these are projected at all. The props feed also prices linebackers for
# tackles and kickers for field goals, and flagging those as missing would
# bury the one case this check exists for under a hundred and sixty seven
# defensive players who were never meant to be here.
PROJECTED_POSITIONS = ("QB", "RB", "WR", "TE")
# How far the projected population may move between builds before the deploy
# stops. Lines move daily and a few players come and go; a third of the board
# does not.
MAX_CHURN_PCT = 18.0
# Below this the population is too small to be a real slate.
MIN_PLAYERS = 120


def log(*a):
    print(*a, flush=True)


def load(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    pr = load("nfl_projections.json")
    if pr is None:
        log("no nfl_projections.json to check")
        return 1
    props_doc = load("nfl_props_full.json")
    board = load("nfl_slate_board.json")
    box = load(f"nfl_{pr['season']}.json")
    if box is None:
        log(f"no nfl_{pr['season']}.json; cannot check rosters")
        return 1

    players = [p for p in pr["players"] if p["pos"] != "DST"]
    keys = {nrm(p["player"]) for p in players}
    fails, warns = [], []

    log(f"checking the population of {len(players)} projected players "
        f"(plus {pr['count'] - len(players)} defenses)")

    # ---- 1. is everybody on a current roster
    roster = {nrm(p["n"]) for p in box["players"]}
    priced = defaultdict(int)
    priced_pos = {}
    if props_doc:
        for p in props_doc["props"]:
            k = p.get("skey") or nrm(p["player"])
            priced[k] += 1
            if p.get("pos"):
                priced_pos[k] = p["pos"]
    ghosts = [p for p in players
              if nrm(p["player"]) not in roster and not priced.get(nrm(p["player"]))]
    if ghosts:
        fails.append(
            f"{len(ghosts)} projected players are on no current roster and "
            f"carry no betting lines, which is what a player from an old "
            f"season looks like: "
            + ", ".join(p["player"] for p in ghosts[:6]))

    # ---- 2. has anybody stopped playing
    latest = max((r["w"] for r in box["rows"]), default=0)
    last = defaultdict(int)
    meta = {p["id"]: nrm(p["n"]) for p in box["players"]}
    for r in box["rows"]:
        k = meta.get(r["i"])
        if k:
            last[k] = max(last[k], r["w"])
    stale = []
    for p in players:
        k = nrm(p["player"])
        if priced.get(k):
            continue
        gap = latest - last.get(k, 0)
        if latest and gap >= 2:
            stale.append((gap, p["player"]))
    if stale:
        stale.sort(reverse=True)
        fails.append(
            f"{len(stale)} projected players have not played in two or more "
            f"weeks and carry no betting lines, which is what injured reserve "
            f"looks like: "
            + ", ".join(f"{n} ({g} weeks)" for g, n in stale[:6]))

    # ---- 3. is anybody the market prices heavily missing
    #
    # This is the check that would have caught McCaffrey. The market pricing a
    # player is the strongest available statement that he is playing, so if he
    # is priced and not projected, the burden is on the pipeline to say why.
    missing = []
    for key, n in priced.items():
        if (n >= PRICED_HEAVILY and key not in keys
                and priced_pos.get(key) in PROJECTED_POSITIONS):
            missing.append((n, key))
    if missing:
        missing.sort(reverse=True)
        names = {nrm(p["player"]): p["player"] for p in props_doc["props"]}
        fails.append(
            f"{len(missing)} players carry {PRICED_HEAVILY} or more betting "
            f"lines but are not projected at all. The market pricing a player "
            f"is the strongest evidence he is playing: "
            + ", ".join(f"{names.get(k, k)} ({n} lines)" for n, k in missing[:6]))

    # ---- 4. does every team field a side
    by_team = defaultdict(lambda: defaultdict(int))
    for p in players:
        by_team[p["team"]][p["pos"]] += 1
    thin_teams, fat_teams = [], []
    for team, counts in sorted(by_team.items()):
        for pos, floor in MIN_PER_TEAM.items():
            if counts.get(pos, 0) < floor:
                thin_teams.append(f"{team} has {counts.get(pos, 0)} {pos}")
        for pos, ceil in MAX_PER_TEAM.items():
            if counts.get(pos, 0) > ceil:
                fat_teams.append(f"{team} has {counts.get(pos, 0)} {pos}")
    if thin_teams:
        fails.append(f"{len(thin_teams)} teams are missing a position "
                     f"entirely: " + "; ".join(thin_teams[:6]))
    if fat_teams:
        warns.append(f"{len(fat_teams)} teams carry more at a position than "
                     f"a real roster does: " + "; ".join(fat_teams[:6]))

    # ---- 5. is the board the right size at all
    if len(players) < MIN_PLAYERS:
        fails.append(f"only {len(players)} players projected, which is too "
                     f"few to be a real slate")

    # ---- 6. did it change without explanation
    base = load("population_baseline.json")
    now = sorted(p["player"] for p in players)
    if base is None:
        warns.append("no previous population recorded, so nothing to compare "
                     "against. One is being written now.")
        churn = None
    else:
        prev = set(base.get("players") or [])
        cur = set(now)
        added, dropped = cur - prev, prev - cur
        churn = 100.0 * (len(added) + len(dropped)) / max(len(prev), 1)
        log(f"\nagainst the previous build ({base.get('built', 'unknown')}): "
            f"{len(added)} added, {len(dropped)} dropped, {churn:.1f}% churn")
        # The names worth seeing are the ones that mattered, so the list is
        # ordered by what the market thinks of them rather than alphabetically.
        if added:
            top = sorted(added, key=lambda n: -priced.get(nrm(n), 0))[:8]
            log("   added:   " + ", ".join(
                f"{n} ({priced.get(nrm(n), 0)} lines)" for n in top))
        if dropped:
            top = sorted(dropped, key=lambda n: -priced.get(nrm(n), 0))[:8]
            log("   dropped: " + ", ".join(
                f"{n} ({priced.get(nrm(n), 0)} lines)" for n in top))
        # A dropped player the market still prices heavily is the McCaffrey
        # shape and is worth failing on by itself.
        bad_drops = [n for n in dropped if priced.get(nrm(n), 0) >= PRICED_HEAVILY]
        if bad_drops:
            fails.append(
                f"{len(bad_drops)} players were dropped since the last build "
                f"while the market still prices them: "
                + ", ".join(sorted(bad_drops)[:6]))

        # Raw churn counts movement the market fully explains, which made this
        # fail for a legitimate reason and then stay failed. Across a game week
        # the prop feed re-prices from scratch: a hundred players get lines for
        # the coming slate and last week's lose theirs. That is turnover of the
        # feed, not of the rule deciding who belongs, and it read as 53.5%.
        #
        # What deserves to stop a deploy is a player leaving WHILE THE MARKET
        # STILL PRICES HIM — the McCaffrey shape, measured across the whole
        # board rather than one name at a time. Players arriving are not judged
        # here: checks 1 and 2 already reject an arrival that is off the roster
        # or has stopped playing, and they do it absolutely rather than against
        # a baseline, so a wave of genuinely priced arrivals is allowed through
        # while a wave of ghosts is not.
        unexplained = [n for n in dropped if priced.get(nrm(n), 0)]
        unex_pct = 100.0 * len(unexplained) / max(len(prev), 1)
        log(f"   of those drops, {len(unexplained)} still carry lines "
            f"({unex_pct:.1f}% of the board); the rest lost their lines, "
            f"which is the market moving on")
        if unex_pct > MAX_CHURN_PCT:
            fails.append(
                f"{len(unexplained)} players ({unex_pct:.1f}% of the board, "
                f"over the {MAX_CHURN_PCT}% ceiling) were dropped while the "
                f"market still prices them. A swing this size means the rule "
                f"deciding who belongs has changed behaviour: "
                + ", ".join(sorted(unexplained)[:6]))
        elif churn > MAX_CHURN_PCT:
            warns.append(
                f"the projected population moved {churn:.1f}% since the last "
                f"build, which is a lot, but every player who left had already "
                f"lost his betting lines. That is what a new game week looks "
                f"like, so this is reported rather than failed.")

    # ---- 7. the slate board should show everyone DraftKings offers
    if board:
        shown = len(board["players"])
        projd = board.get("projected", 0)
        log(f"\nslate board: {shown} DraftKings players, {projd} with a "
            f"projection ({100.0 * projd / max(shown, 1):.0f}%)")
        no_reason = [p for p in board["players"]
                     if p.get("proj") is None and not p.get("why")]
        if no_reason:
            fails.append(f"{len(no_reason)} players on the slate board have "
                         f"no projection and no reason given for it")

    log("")
    for w in warns:
        log(f"WARN: {w}")
    for f in fails:
        log(f"FAIL: {f}")

    if not fails:
        log("OK: the board contains the players it should, every team fields "
            "a side, nobody the market prices is missing, and the population "
            "has not moved more than it should have.")

    # The baseline is written even on a failure, otherwise one bad build makes
    # every later run fail against a population nobody intends to return to.
    with open(os.path.join(DATA, "population_baseline.json"), "w",
              encoding="utf-8") as f:
        json.dump({
            "built": datetime.datetime.now(datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "season": pr["season"],
            "count": len(players),
            "players": now,
        }, f, separators=(",", ":"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
