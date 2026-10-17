#!/usr/bin/env python3
"""
build_contest.py — simulate a tournament field against the slate sim. Writes
data/nfl_contest.json.

WHAT THIS ANSWERS THAT NOTHING ELSE HERE DOES
Every other number on this site asks how a player will do. A tournament does
not pay for that. It pays for finishing above sixty thousand other lineups, so
what matters is how a player's outcomes line up against what everybody ELSE
rostered. A 25 point game from a player half the field owns moves you nowhere;
the same 25 from a player nobody has wins the thing.

That cannot be read off a projection, or off ownership, or off both side by
side. It needs an actual field of lineups, scored against the same correlated
slate simulations the projections came from, which is what this does:

  1. Build a field of lineups by sampling players at their projected
     ownership, under the real DraftKings roster and salary rules, so the
     field looks like a field rather than a list of optimal teams.
  2. Score every one of those lineups in every simulated slate.
  3. For each player, compare how often lineups containing him win against
     how often a lineup wins at all.

The last number is the point. A ratio of 2.0 means a lineup with him in it is
twice as likely to win as a random entry, and that already contains his
projection, his ceiling, his correlation with his team mates, and how many
other people are on him. It is the leverage number the slate board
approximates with boom rate minus ownership, done properly.

WHY THE CORRELATION MATTERS MORE HERE THAN ANYWHERE ELSE
Lineups are not independent draws. A quarterback and his receiver go off in
the same trial, and a field full of that stack either all wins together or all
loses together. Scoring a field against uncorrelated player simulations would
badly understate how often a stack takes down a tournament, which is precisely
the question being asked.

HONESTY ABOUT THE FIELD
It is built from projected ownership, which is a model with no NFL training
data behind it yet. Everything here inherits that uncertainty. What does not
depend on it is the relative shape: who is leveraged against the field the
model describes. When real ownership arrives, this sharpens without any of it
being rewritten.
"""
import datetime
import json
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

FIELD = 4_000          # lineups in the simulated tournament
TRIALS = 4_000         # simulated slates each lineup is scored in
SEED = 20261017
CAP = 50_000
# Real entrants spend nearly all of the cap. Sampling purely at ownership
# produced an average lineup of 46,931, which is a field of people leaving
# three thousand dollars unspent, and a field that weak makes every lineup
# look likelier to win than it is.
MIN_SALARY = 47_500
# Below this share of the field a win rate is measuring the handful of lineups
# a player happened to land in, not the player. Those are reported separately
# rather than sorted to the bottom as though zero meant something.
MIN_FIELD_PCT = 1.0
# DraftKings classic: one quarterback, two backs, three receivers, a tight
# end, a flex of those three, and a defense.
SLOTS = ("QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST")
FLEX_OK = ("RB", "WR", "TE")
MAX_PER_TEAM = 8       # DraftKings caps a lineup at eight from one side
# A tournament pays the top fifth, steeply. Only the shape matters here.
PAYOUT_TOP = 0.20


def log(*a):
    print(*a, flush=True)


def sample_field(rng, pool, n_lineups):
    """A field of lineups, drawn at projected ownership under the real rules.

    Sampling at ownership rather than optimising is the whole point: a real
    tournament field is mostly ordinary lineups built around popular players,
    not sixty thousand copies of the optimal one, and measuring leverage
    against a field of optimal lineups would answer a question nobody is in."""
    by_pos = defaultdict(list)
    for i, p in enumerate(pool):
        by_pos[p["pos"]].append(i)
    flex_idx = [i for pos in FLEX_OK for i in by_pos.get(pos, [])]

    def weights(idxs):
        w = np.array([max(pool[i]["own"], 0.01) for i in idxs], dtype=np.float64)
        return w / w.sum()

    wts = {pos: weights(idxs) for pos, idxs in by_pos.items() if idxs}
    flex_w = weights(flex_idx) if flex_idx else None
    need = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DST": 1}
    for pos in need:
        if pos not in by_pos or len(by_pos[pos]) < need[pos]:
            raise SystemExit(f"not enough {pos} on the slate to build a lineup")

    out = []
    attempts = 0
    while len(out) < n_lineups and attempts < n_lineups * 60:
        attempts += 1
        picked = []
        ok = True
        for pos, k in need.items():
            idxs = by_pos[pos]
            take = rng.choice(idxs, size=k, replace=False, p=wts[pos])
            picked.extend(int(x) for x in take)
        if flex_idx:
            for _ in range(8):
                f = int(rng.choice(flex_idx, p=flex_w))
                if f not in picked:
                    picked.append(f)
                    break
            else:
                ok = False
        if not ok or len(picked) != len(SLOTS):
            continue
        sal = sum(pool[i]["sal"] for i in picked)
        if sal > CAP or sal < MIN_SALARY:
            continue
        teams = defaultdict(int)
        for i in picked:
            teams[pool[i]["team"]] += 1
        if max(teams.values()) > MAX_PER_TEAM:
            continue
        out.append(sorted(picked))
    return np.array(out, dtype=np.int32), attempts


def main():
    cpath = os.path.join(DATA, "nfl_slate_board.json")
    if not os.path.exists(cpath):
        log("no nfl_slate_board.json; run build_nfl_slate.py first")
        return 1
    with open(cpath, encoding="utf-8") as f:
        board = json.load(f)

    # The per trial scores live only inside the projection build, so the joint
    # simulation is regenerated here rather than a ten thousand by four hundred
    # matrix being carried around in a JSON file nobody else needs.
    log("regenerating the joint slate simulation for the contest")
    import build_projections as bp
    bp.TRIALS = TRIALS
    # Everyone on the board, with their salary and projected ownership.
    want = {}
    for p in board["players"]:
        if p.get("proj") is None or not p.get("sal"):
            continue
        own = (p.get("own") or {}).get("mme")
        if own is None:
            continue
        want[nrm(p["player"])] = p

    sims, _res = bp.player_scores(TRIALS, "dk")
    log(f"{len(sims)} players simulated at {TRIALS:,} trials")

    # Defenses are keyed by team in the simulation and by name on the board.
    alias = {}
    for p in board["players"]:
        if p.get("pos") == "DST":
            alias[f"dst_{p['team']}"] = nrm(p["player"])

    pool = []
    for key, entry in sims.items():
        b = want.get(alias.get(key, key))
        if not b:
            continue
        pool.append({
            "key": key, "name": b["player"], "pos": b["pos"],
            "team": b["team"], "opp": b.get("opp"),
            "sal": b["sal"], "own": (b.get("own") or {}).get("mme", 1.0),
            "fp": entry,
        })
    log(f"{len(pool)} of them are on the DraftKings slate with a salary "
        f"and an ownership")
    have = defaultdict(int)
    for p in pool:
        have[p["pos"]] += 1
    log("   " + ", ".join(f"{v} {k}" for k, v in sorted(have.items())))

    rng = np.random.default_rng(SEED)
    log(f"\nbuilding a field of {FIELD:,} lineups at projected ownership")
    field, attempts = sample_field(rng, pool, FIELD)
    log(f"   {len(field):,} legal lineups from {attempts:,} attempts")
    if len(field) < FIELD * 0.5:
        log("   WARNING: a lot of draws were rejected, usually the salary cap")

    scores = np.vstack([p["fp"] for p in pool])        # players x trials
    sal = np.array([p["sal"] for p in pool])
    log(f"   average lineup salary {sal[field].sum(axis=1).mean():,.0f} "
        f"of a {CAP:,} cap")

    # Score every lineup in every trial, in blocks so the matrix never has to
    # exist all at once.
    n_lu = len(field)
    wins = np.zeros(n_lu, dtype=np.float64)
    cash = np.zeros(n_lu, dtype=np.float64)
    block = 500
    for t0 in range(0, TRIALS, block):
        t1 = min(t0 + block, TRIALS)
        tot = scores[:, t0:t1][field].sum(axis=1)      # lineups x block
        best = tot.argmax(axis=0)
        np.add.at(wins, best, 1.0)
        cut = np.quantile(tot, 1.0 - PAYOUT_TOP, axis=0)
        cash += (tot >= cut).sum(axis=1)
    wins /= TRIALS
    cash /= TRIALS

    # Per player: how a lineup containing him fares against the field average.
    base_win = 1.0 / n_lu
    base_cash = PAYOUT_TOP
    rows = []
    for i, p in enumerate(pool):
        mask = (field == i).any(axis=1)
        n = int(mask.sum())
        if n == 0:
            continue
        w = float(wins[mask].sum() / n)
        c = float(cash[mask].mean())
        pct = 100.0 * n / n_lu
        rows.append({
            "thinField": pct < MIN_FIELD_PCT,
            "player": p["name"], "pos": p["pos"], "team": p["team"],
            "opp": p["opp"], "sal": p["sal"],
            "own": round(p["own"], 1),
            "fieldPct": round(100.0 * n / n_lu, 1),
            "winRate": round(w / base_win, 2) if base_win else None,
            "cashRate": round(c / base_cash, 2) if base_cash else None,
            "proj": round(float(p["fp"].mean()), 1),
        })
    rows.sort(key=lambda r: (r["thinField"], -(r["winRate"] or 0)))
    # Built AFTER the sort. Taking the slice first printed the list in
    # whatever order the pool happened to be in, which put a 0.53 at the top
    # of a table headed "most leveraged".
    solid = [r for r in rows if not r["thinField"]]

    # The lineups that actually won, so the shape of a winner is visible
    # rather than described.
    top = np.argsort(-wins)[:25]
    winners = []
    for li in top:
        if wins[li] <= 0:
            continue
        ids = field[li]
        winners.append({
            "win": round(float(wins[li]) * 100, 2),
            "sal": int(sal[ids].sum()),
            "players": [{"n": pool[i]["name"], "pos": pool[i]["pos"],
                         "tm": pool[i]["team"], "sal": pool[i]["sal"]}
                        for i in ids],
        })

    built = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "built": built,
        "slate": board.get("slate"),
        "field": n_lu, "trials": TRIALS,
        "payoutTop": PAYOUT_TOP,
        "ownershipCalibrated": False,
        "players": rows,
        "winners": winners,
    }
    out = os.path.join(DATA, "nfl_contest.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"\nwrote nfl_contest.json ({os.path.getsize(out) // 1024} KB)")

    log("\nmost leveraged against the field "
        "(win rate of lineups with him, against a random lineup):")
    log("%-24s %-4s %6s %7s %8s %8s" %
        ("player", "pos", "$", "own%", "in field", "win x"))
    for r in solid[:14]:
        log("%-24s %-4s %6d %7.1f %7.1f%% %8.2f"
            % (r["player"][:24], r["pos"], r["sal"], r["own"],
               r["fieldPct"], r["winRate"]))
    log(f"\n({len(rows) - len(solid)} players appear in under "
        f"{MIN_FIELD_PCT}% of the field, where a win rate measures the sample "
        f"rather than the player, and are reported but not ranked)")
    log("\nleast leveraged, the chalk that does not pay for itself:")
    for r in sorted(solid, key=lambda r: r["winRate"] or 0)[:8]:
        log("%-24s %-4s %6d %7.1f %7.1f%% %8.2f"
            % (r["player"][:24], r["pos"], r["sal"], r["own"],
               r["fieldPct"], r["winRate"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
