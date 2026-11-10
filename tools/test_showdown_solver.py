#!/usr/bin/env python3
"""
test_showdown_solver.py — proves the showdown solve is legal and optimal.

discover_showdown.py claims something the classic scenario tool does not: that
the winning lineup in each simulated game is solved EXACTLY rather than
approximated. That claim is the reason its captain table can be trusted at all,
because a captain is named by a single point of score and a greedy fill would
quietly hand the slot to the wrong player.

So it is checked against a brute force written independently here, over every
(captain, five flex) pair, with no vectorisation and no pruning. If the fast
solver and the slow one disagree on the achievable total, the fast one is wrong.

It also checks the three DraftKings rules on every lineup the solver returns,
since an illegal lineup that scores well would look like a great scenario:
  - six distinct players
  - salary at most $50,000 with the captain costing 1.5x
  - at least one player from each team

Run: python tools/test_showdown_solver.py
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discover_showdown as ds  # noqa: E402

FAIL = []


def check(cond, msg):
    print(("   ok   " if cond else "   FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def brute_force(score, sal, is_a):
    """The best legal lineup, found the slow obvious way. Returns the total."""
    n = len(score)
    best = -1e18
    for cpt in range(n):
        budget = ds.CAP - round(sal[cpt] * ds.CPT_MULT)
        if budget < 0:
            continue
        rest = [i for i in range(n) if i != cpt]
        for flex in itertools.combinations(rest, ds.FLEX_SLOTS):
            if sum(sal[i] for i in flex) > budget:
                continue
            ids = (cpt,) + flex
            if len({is_a[i] for i in ids}) < 2:      # both sides required
                continue
            tot = score[cpt] * ds.CPT_MULT + sum(score[i] for i in flex)
            best = max(best, tot)
    return best


def synthetic(seed, n=14):
    """A small random game, so the brute force finishes quickly."""
    rng = np.random.default_rng(seed)
    score = rng.gamma(3.0, 4.0, size=n)
    # Salaries wide enough that the cap actually binds and a punt is sometimes
    # needed; a pool where any six fit would test nothing.
    sal = (rng.integers(5, 115, size=n) * 100).astype(np.int64)
    is_a = np.zeros(n, dtype=bool)
    is_a[: n // 2] = True
    return score, sal, is_a


def main():
    print("1. fast solve matches an independent brute force")
    agree = 0
    for seed in range(12):
        score, sal, is_a = synthetic(seed)
        n = len(score)
        combos = ds.combos_for(n)
        contains = np.zeros((n, len(combos)), dtype=bool)
        for j in range(n):
            contains[j] = (combos == j).any(axis=1)
        cpt, flex, tot = ds.solve_trial(score, sal, is_a,
                                        np.arange(n, dtype=np.int64),
                                        combos, contains)
        want = brute_force(score, sal, is_a)
        if cpt is None:
            check(want < -1e17, f"seed {seed}: both found no legal lineup")
            continue
        same = abs(tot - want) < 1e-9
        agree += same
        if not same:
            check(False, f"seed {seed}: fast {tot:.4f} vs brute {want:.4f}")
    check(agree == 12, f"all 12 random games agree exactly ({agree}/12)")

    print("\n2. the returned lineup obeys every DraftKings rule")
    bad_count = bad_cap = bad_teams = 0
    for seed in range(40):
        score, sal, is_a = synthetic(seed + 100)
        n = len(score)
        combos = ds.combos_for(n)
        contains = np.zeros((n, len(combos)), dtype=bool)
        for j in range(n):
            contains[j] = (combos == j).any(axis=1)
        cpt, flex, _ = ds.solve_trial(score, sal, is_a,
                                      np.arange(n, dtype=np.int64),
                                      combos, contains)
        if cpt is None:
            continue
        ids = [cpt] + [int(x) for x in flex]
        if len(set(ids)) != ds.ROSTER:
            bad_count += 1
        spend = round(sal[cpt] * ds.CPT_MULT) + sum(sal[i] for i in ids[1:])
        if spend > ds.CAP:
            bad_cap += 1
        if len({bool(is_a[i]) for i in ids}) < 2:
            bad_teams += 1
    check(bad_count == 0, f"six distinct players every time ({bad_count} bad)")
    check(bad_cap == 0, f"never over the $50,000 cap ({bad_cap} bad)")
    check(bad_teams == 0, f"both teams always represented ({bad_teams} bad)")

    print("\n3. the captain is never also used in a flex slot")
    # This is what `contains` exists to prevent, and it is the easiest thing to
    # get wrong while still producing a plausible-looking score.
    dupes = 0
    for seed in range(30):
        score, sal, is_a = synthetic(seed + 500)
        n = len(score)
        combos = ds.combos_for(n)
        contains = np.zeros((n, len(combos)), dtype=bool)
        for j in range(n):
            contains[j] = (combos == j).any(axis=1)
        cpt, flex, _ = ds.solve_trial(score, sal, is_a,
                                      np.arange(n, dtype=np.int64),
                                      combos, contains)
        if cpt is not None and cpt in [int(x) for x in flex]:
            dupes += 1
    check(dupes == 0, f"no captain duplicated into flex ({dupes} bad)")

    print("\n4. the reduced candidate path returns exactly `width` indices")
    # The first version deduplicated with np.unique and silently returned
    # fewer whenever a cheap player was also a top scorer, which showed up as
    # an out-of-bounds index into the combination table.
    rng = np.random.default_rng(7)
    sizes = set()
    for _ in range(50):
        n = int(rng.integers(12, 40))
        score = rng.gamma(3.0, 4.0, size=n)
        sal = (rng.integers(5, 115, size=n) * 100).astype(np.int64)
        width = min(ds.MAX_EXACT, ds.RED_SCORE + ds.RED_CHEAP, n)
        cand = ds.candidates(score, np.argsort(sal), width)
        sizes.add(len(cand) == width and len(set(cand.tolist())) == width
                  and cand.max() < n)
    check(sizes == {True}, "every reduced set is the right size and in range")

    print("\n5. a pool with one team only is rejected, not silently solved")
    score, sal, _ = synthetic(3)
    n = len(score)
    one = np.ones(n, dtype=bool)
    combos = ds.combos_for(n)
    contains = np.zeros((n, len(combos)), dtype=bool)
    for j in range(n):
        contains[j] = (combos == j).any(axis=1)
    cpt, _f, _t = ds.solve_trial(score, sal, one, np.arange(n, dtype=np.int64),
                                 combos, contains)
    check(cpt is None, "no lineup is returned when both sides cannot be filled")

    print()
    if FAIL:
        print(f"{len(FAIL)} CHECK(S) FAILED")
        for m in FAIL:
            print("   - " + m)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
