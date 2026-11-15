#!/usr/bin/env python3
"""
detect_pulled_markets.py — a book taking a player down is news, not silence.

WHAT HAPPENED ON 15 NOVEMBER
Justin Jefferson had twenty-five prop rows across fifteen markets at 12:21,
including receptions, receiving yards, targets and anytime touchdown. By 16:42
every one of those was gone and only derivatives were left: first-half
receptions, first-quarter touchdowns, fumbles lost, last touchdown scorer.

Minnesota had changed quarterback and Jordan Addison had been ruled out. The
books pulled his volume markets to reprice him. Our pipeline has no concept of
that, so it saw zero anchorable lines, fell back to a conservative role prior,
produced 12.55 points at $6,800, and the ownership model read that poor value
and called him 3.1% owned. The field, which had the news, owned him 40.0%.

The absence of a market was the loudest signal on the board and it was read as
no signal at all. Worse than no signal: because everything downstream divides
by ownership, a player the book had taken down came out looking like the best
leverage play on the slate.

WHAT THIS DOES
Compares the newest props snapshot against the one before it and reports
players whose ANCHORABLE markets have disappeared. Those are the volume
markets a projection can be built on; the derivative and novelty markets that
often remain are not a substitute, and a player left holding only those is
flagged more loudly than one who simply never had a market.

It reads the archive in data/props_history and writes nothing.

USAGE
  python tools/detect_pulled_markets.py [--min-salary 4000]
"""
import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "props_history")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402

# The markets a projection's volume can actually be anchored to. Everything
# else (first-half, first-quarter, fumbles, touchdown-scorer novelties) can sit
# on the board long after the real market has gone, which is exactly how a
# player with nine live rows can still have nothing to anchor to.
ANCHORABLE = {
    "receptions", "receiving yards", "targets", "anytime td",
    "rush attempts", "rushing yards", "longest reception", "longest rush",
    "pass attempts", "passing yards", "completions", "pass tds",
    "interceptions", "fantasy points", "rush + rec yards",
}


def log(*a):
    print(*a, flush=True)


def markets(path):
    """player -> anchorable markets, total rows, and his kickoff time."""
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rows = doc.get("props") or []
    anc = defaultdict(set)
    total = defaultdict(int)
    kick, team = {}, {}
    for r in rows:
        p = nrm(str(r.get("player") or ""))
        if not p:
            continue
        total[p] += 1
        if r.get("kickoff"):
            kick[p] = r["kickoff"]
        if r.get("team"):
            team[p] = r["team"]
        stat = (r.get("stat") or "").strip().lower()
        if stat in ANCHORABLE:
            anc[p].add(stat)
    return doc.get("built"), anc, total, kick, team


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-salary", type=int, default=4000)
    args = ap.parse_args()

    snaps = sorted(f for f in os.listdir(HIST) if f.endswith(".json"))
    if len(snaps) < 2:
        log("need at least two props snapshots to compare")
        return 0
    prev_p, cur_p = (os.path.join(HIST, s) for s in snaps[-2:])
    t_prev, a_prev, _, k_prev, tm_prev = markets(prev_p)
    t_cur, a_cur, n_cur, _, _ = markets(cur_p)
    log(f"comparing {os.path.basename(prev_p)} ({t_prev})")
    log(f"     with {os.path.basename(cur_p)} ({t_cur})")

    # Salaries come from the whole DraftKings pool, not from the live board.
    # The board follows whichever slate is next, so once the main slate locks
    # it moves on and every player from it reads as salary zero. That silently
    # filtered Jefferson, the one player this tool exists to catch, out of its
    # own report.
    sal, disp = {}, {}
    dkpath = os.path.join(DATA, "nfl_dk.json")
    if os.path.exists(dkpath):
        with open(dkpath, encoding="utf-8") as f:
            for sl in json.load(f).get("slates", []):
                for pl in sl.get("players", []):
                    k = nrm(pl["n"])
                    if pl.get("sal", 0) > sal.get(k, 0):
                        sal[k] = pl["sal"]
                        disp[k] = pl["n"]
    bpath = os.path.join(DATA, "nfl_slate_board.json")
    if os.path.exists(bpath):
        with open(bpath, encoding="utf-8") as f:
            for pl in json.load(f)["players"]:
                k = nrm(pl["player"])
                sal.setdefault(k, pl.get("sal") or 0)
                disp.setdefault(k, pl["player"])

    # Only games that had NOT kicked off by the newer snapshot. A book clears
    # every market the moment a game starts, so without this the report fills
    # with players whose games are simply under way and the handful that
    # matter are buried.
    gone, started = [], 0
    for p, before in a_prev.items():
        after = a_cur.get(p, set())
        if not before or after:
            continue
        ko = k_prev.get(p)
        if ko and t_cur and ko <= t_cur:
            started += 1
            continue
        gone.append((sal.get(p, 0), disp.get(p, p), len(before),
                     n_cur.get(p, 0), (ko or "?")[:16], tm_prev.get(p, "?")))
    gone.sort(reverse=True)
    gone = [g for g in gone if g[0] >= args.min_salary]

    if started:
        log(f"\n({started} more lost their markets to kickoff, which is normal "
            f"and is excluded)")
    if not gone:
        log("\nno player in an UNSTARTED game lost all of their anchorable "
            "markets between these two snapshots.")
        return 0

    log(f"\n{'=' * 74}")
    log("MARKETS PULLED — treat as pending news, NOT as low ownership")
    log("=" * 74)
    log(f"   {'player':24}{'tm':>4}{'salary':>8}{'had':>5}{'now':>5}"
        f"  {'kickoff':17}left")
    for sa, name, had, now, ko, tm in gone:
        left = "derivatives only" if now else "nothing"
        log(f"   {name[:23]:24}{tm:>4}{sa:>8}{had:>5}{now:>5}  {ko:17}{left}")

    # The cluster is the signal. One player losing his markets is a repricing;
    # six from one team inside the same window is a team-level event, and it
    # can be read straight off the book without any injury feed. On
    # 15 November every pulled player in an unstarted game was a Minnesota
    # Viking: the quarterback change, the receiver who was ruled out, and the
    # four team mates repriced around them.
    byteam = defaultdict(list)
    for _sa, name, _h, _n, _k, tm in gone:
        byteam[tm].append(name)
    clusters = {t: v for t, v in byteam.items() if len(v) >= 3 and t != "?"}
    for t, v in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        log(f"\n   CLUSTER: {len(v)} {t} players lost their markets together. "
            f"That is a team-level\n   event, not a repricing. "
            + ", ".join(v[:7]))
    log("\nA book removes a player's volume markets when it is about to "
        "reprice him,\nwhich usually means news. Their projections are role "
        "priors and their\nmodelled ownership is biased LOW, so they will look "
        "contrarian when they\nare the opposite. Check the news before using "
        "any of them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
