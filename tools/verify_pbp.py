#!/usr/bin/env python3
"""
verify_pbp.py — check the play by play reconstruction against the box score.

WHY
fetch_nfl_pbp.py rebuilds every statistic from individual plays. That is a
reconstruction, and a reconstruction can be wrong in ways that look completely
plausible: counting penalty-wiped plays, counting two point conversions as
receptions, attributing a sack as a pass attempt, putting overtime in the wrong
period. Every one of those produces numbers that are close enough to pass a
glance and wrong enough to mis-price a prop.

So the plays are summed back up to game totals and compared, player by player
and week by week, against the weekly box score in nfl_<season>.json, which came
from a different nflverse file built by a different process. Where they
disagree, one of them is wrong and the run says so rather than shipping it.

This does NOT import fetch_nfl_pbp. It reads the written files, which is the
point: a bug shared between a builder and its checker is invisible.

WHAT THE GATE IS, AND WHY IT IS NOT "ZERO MISMATCHES"
The two nflverse products do not always agree with each other. A stat
correction lands in one before the other, so a handful of games have yardage
reattributed in the box score that the play by play still shows the old way.
Those are upstream and nothing here can fix them. Demanding a perfect match
would therefore mean a permanently red check that everyone learns to ignore,
which is worse than no check.

So the gate is on the two things that actually separate a bug from feed noise:

  RATE       a real attribution bug is broad. Missing the lateral columns put
             60 values out (0.128%); genuine revision noise is a tenth of that.
  DIRECTION  a real bug is one-sided, because it always drops or always adds
             the same kind of play. Revision noise goes both ways.

A stat with five or more mismatches all pointing the same way fails even if the
rate looks small, because that is the signature of a systematically mishandled
play type. Both numbers are printed either way, so a slow drift is visible
before it trips anything.
"""
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Fail above this share of values disagreeing. Set from measurement, not taste:
# the lateral bug that this check caught sat at 0.128%, and the residual
# upstream disagreement sits at 0.019%, so anything approaching a tenth of a
# percent is a bug rather than noise.
MAX_RATE = 0.05
# A stat with this many disagreements all pointing one way fails regardless of
# the rate.
MIN_ONE_SIDED = 5

# box score key -> how to get the same number out of the period buckets
CHECKS = {
    "rec": lambda p: sum(len(x.get("ry", [])) for x in p),
    # Lateral yards count toward the yardage total but are not a reception,
    # which is exactly how the official box score treats them.
    "ry":  lambda p: sum(sum(x.get("ry", [])) + x.get("lry", 0) for x in p),
    "tg":  lambda p: sum(len(x.get("ry", [])) + x.get("inc", 0) for x in p),
    "ca":  lambda p: sum(len(x.get("uy", [])) for x in p),
    "ru":  lambda p: sum(sum(x.get("uy", [])) + x.get("luy", 0) for x in p),
    "cmp": lambda p: sum(len(x.get("py", [])) for x in p),
    "py":  lambda p: sum(sum(x.get("py", [])) for x in p),
    "att": lambda p: sum(len(x.get("py", [])) + x.get("pinc", 0) for x in p),
    "rtd": lambda p: sum(x.get("rtd", 0) for x in p),
    "utd": lambda p: sum(x.get("utd", 0) for x in p),
    "ptd": lambda p: sum(x.get("ptd", 0) for x in p),
    "int": lambda p: sum(x.get("int", 0) for x in p),
    "sk":  lambda p: sum(x.get("sk", 0) for x in p),
}


def log(*a):
    print(*a, flush=True)


def main():
    idx_path = os.path.join(DATA, "nfl_index.json")
    if not os.path.exists(idx_path):
        raise SystemExit("no nfl_index.json; run fetch_nfl.py first")
    with open(idx_path, encoding="utf-8") as f:
        idx = json.load(f)

    worst = defaultdict(list)
    signed = defaultdict(list)   # stat -> [plays minus box, ...]
    tot_checked = tot_bad = 0
    seasons_done = 0

    for s in sorted(idx["seasons"], key=lambda s: -int(s["season"])):
        season = int(s["season"])
        box_path = os.path.join(DATA, s["file"])
        pbp_path = os.path.join(DATA, f"nfl_pbp_{season}.json")
        if not os.path.exists(box_path) or not os.path.exists(pbp_path):
            log(f"{season}: missing a file, skipping "
                f"(box {os.path.exists(box_path)}, pbp {os.path.exists(pbp_path)})")
            continue

        with open(box_path, encoding="utf-8") as f:
            box = json.load(f)
        with open(pbp_path, encoding="utf-8") as f:
            pbp = json.load(f)

        # (pid, week) -> list of the periods present
        built = {}
        for r in pbp["logs"]:
            built[(r["i"], r["w"])] = [r[k] for k in ("p0", "p1", "p2") if k in r]

        names = {p["id"]: p["n"] for p in box["players"]}
        checked = bad = 0
        bad_by_stat = defaultdict(int)
        missing_week = 0

        for r in box["rows"]:
            key = (r["i"], r["w"])
            periods = built.get(key)
            if periods is None:
                # A player with snaps but no touch has no plays to reconstruct,
                # which is correct, not a mismatch. Only flag it when the box
                # score says he actually did something.
                if any(r.get(k) for k in CHECKS):
                    missing_week += 1
                continue
            for stat, fn in CHECKS.items():
                want = r.get(stat)
                if want is None:
                    # The box score omits a stat the player had none of, and
                    # the reconstruction must then also produce none of it.
                    got = fn(periods)
                    if got:
                        bad += 1
                        bad_by_stat[stat] += 1
                        signed[stat].append(got)
                        worst[stat].append((abs(got), season, names.get(r["i"], r["i"]),
                                            r["w"], 0, got))
                    continue
                checked += 1
                got = fn(periods)
                if abs(got - want) > 1e-6:
                    bad += 1
                    bad_by_stat[stat] += 1
                    signed[stat].append(got - want)
                    worst[stat].append((abs(got - want), season,
                                        names.get(r["i"], r["i"]), r["w"], want, got))

        tot_checked += checked
        tot_bad += bad
        seasons_done += 1
        pct = (100.0 * bad / checked) if checked else 0.0
        log(f"{season}: {checked:,} values checked, {bad:,} mismatched ({pct:.2f}%)"
            + (f", {missing_week} player-weeks absent from the pbp file"
               if missing_week else ""))
        if bad_by_stat:
            for stat, n in sorted(bad_by_stat.items(), key=lambda kv: -kv[1]):
                log(f"      {stat:>4}: {n}")

    if not seasons_done:
        log("nothing verified")
        return 1

    log(f"\ntotal: {tot_checked:,} values, {tot_bad:,} mismatched "
        f"({100.0 * tot_bad / tot_checked if tot_checked else 0:.3f}%)")

    if worst:
        log("\nlargest disagreements per stat:")
        for stat in sorted(worst, key=lambda s: -max(x[0] for x in worst[s])):
            rows = sorted(worst[stat], reverse=True)[:4]
            log(f"   {stat}:")
            for d, season, name, wk, want, got in rows:
                log(f"      {season} wk{wk:<2} {name:<24} box {want:>6}  "
                    f"plays {got:>6}  off by {d:g}")

    rate = (100.0 * tot_bad / tot_checked) if tot_checked else 0.0
    fails = []

    # Breadth. A mishandled play type shows up across many players at once.
    if rate > MAX_RATE:
        fails.append(f"{rate:.3f}% of values disagree, over the {MAX_RATE}% "
                     f"ceiling. That is broad enough to be an attribution bug, "
                     f"not stat corrections.")

    # Direction. This is the sharper test: a bug that drops a kind of play
    # always drops it, so every disagreement points the same way.
    log("\ndirection of disagreement (plays minus box):")
    for stat, ds in sorted(signed.items(), key=lambda kv: -len(kv[1])):
        up = sum(1 for d in ds if d > 0)
        down = sum(1 for d in ds if d < 0)
        verdict = "both ways, consistent with stat corrections"
        if len(ds) >= MIN_ONE_SIDED and (up == 0 or down == 0):
            verdict = "ALL ONE WAY, which is what a real bug looks like"
            fails.append(f"{stat}: {len(ds)} disagreements all in the same "
                         f"direction ({'plays high' if up else 'plays low'}).")
        log(f"   {stat:>4}: {len(ds):>3} total, {up} plays high, {down} plays low"
            f"   {verdict}")

    if fails:
        log("\nFAIL:")
        for f in fails:
            log(f"   {f}")
        return 1
    log(f"\nOK: {rate:.3f}% disagree, in both directions, which is the "
        f"upstream disagreement between nflverse's play by play and its box "
        f"score rather than a fault in the reconstruction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
