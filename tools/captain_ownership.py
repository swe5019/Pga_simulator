#!/usr/bin/env python3
"""
captain_ownership.py — how crowded each captain choice is, before lock.

WHY THIS EXISTS
A showdown lineup is six players from one game, and the only slot where the
field really concentrates is the captain. Captain ownership sums to 100% across
the slate, so one popular choice swallows an enormous share of it: on
16 November Derrick Henry was captained by 33.3% of 642,122 entries. A third of
the field made the same decision, and when he finished second among captains by
2.25 points, all of them lost together. Nothing in this project could see that
coming, because the showdown page reported which captain WINS and never how
many people were already there.

WHAT THE FIELD ACTUALLY DOES
It captains by price. Measured across the two contests available, captain
ownership correlates +0.73 with the player's flex salary and only +0.62 with
his flex ownership, and the relationship is a power law: the log of captain
ownership against the log of salary correlates +0.78 to +0.88.

So the model is deliberately almost trivial:

    captain ownership  proportional to  salary ** EXPONENT,  normalised to 100%

VALIDATION, and why nothing more elaborate is used
Seventeen captains across two slates. Fitting on one slate and scoring the
other, which is the only honest test available:

    salary only              3.67 and 2.87   mean 3.27 points of error
    simulated win rate only  3.90 and 3.61   mean 3.76
    salary times win rate    3.90 and 5.53   mean 4.72
    spreading evenly         6.49 and 5.03   mean 5.76

Adding this project's own simulated captain win rate makes it WORSE out of
sample, even though it looks better in sample. The field is not simulating. It
is reading the price, and a second parameter fitted on seventeen points is
fitting noise. The exponent itself is unstable, 3.3 when fitted on one slate
and 4.5 on the other, so the midpoint is used and should be refitted as
contests accumulate.

WHAT THIS IS NOT FOR
Do NOT divide a captain's win rate by this to make a leverage column. That was
the intended use and it fails: tested on both contests it ranked the winning
captain 12th of 21 and 20th of 23, against 1st and 10th for the raw win rate.
Because the model is monotone in salary, the ratio is close to "win rate per
dollar", which promotes cheap players who mostly do not win. The model's job is
to say how crowded a choice is, not to pick one.

KNOWN FAILURE
It under-predicts a dominant captain. Henry came through at 18.0% modelled
against 33.3% actual. When one captain is obvious to everybody the real field
concentrates harder than a salary curve can.
"""

# Fitted on 17 captains across the 15 and 16 November 2026 showdowns. The two
# slates independently want 3.3 and 4.5, so this is the midpoint and carries
# real uncertainty.
EXPONENT = 3.8

# Captain ownership below this is not meaningfully distinguishable from zero
# given about 3 points of error, so it is reported as a floor rather than a
# number that invites division.
MIN_REPORTABLE = 0.2


def captain_ownership(players, exponent=EXPONENT):
    """players: [{'player': name, 'sal': flex salary}] -> {name: percent}.

    `sal` is the FLEX salary. DraftKings prices the captain at 1.5x, but the
    multiplier is constant across the slate and so cancels in the normalisation;
    passing captain salaries instead gives the same answer.
    """
    pool = [p for p in players if (p.get("sal") or 0) > 0]
    if not pool:
        return {}
    weights = {p["player"]: float(p["sal"]) ** exponent for p in pool}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {n: max(100.0 * w / total, MIN_REPORTABLE)
            for n, w in weights.items()}


def describe():
    return (f"captain ownership modelled as salary^{EXPONENT} normalised to "
            f"100%, fitted on 17 captains over 2 contests, about 3.3 points of "
            f"mean error out of sample against 5.8 for spreading evenly")
