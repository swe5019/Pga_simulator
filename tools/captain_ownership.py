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

VALIDATION
Twenty six captains across three slates, holding each slate out in turn and
fitting the exponent on the other two:

    hold out 13 Nov   fit 3.45   MAE 4.62   against a 5.91 baseline
    hold out 15 Nov   fit 3.50   MAE 2.00   against 5.03
    hold out 16 Nov   fit 2.70   MAE 4.04   against 6.49
    pooled                       MAE 3.61   against about 5.8

Adding this project's own simulated captain win rate makes it WORSE out of
sample even though it looks better in sample. The field is not simulating, it
is reading the price, and a second parameter on this little data fits noise.

THE EXPONENT IS THE WEAK POINT, and more data made that clearer rather than
better. Fitted per slate it comes out 1.45, 3.30 and 7.95. That five-fold
range is not noise in the fit: it is the exponent absorbing how CONCENTRATED
each captain market happened to be. On 16 November one captain took a third of
the market and the curve has to be steep; on 13 November the top nine captains
ran 23.3% down to 2.9% and it has to be shallow. Salary says nothing about
which of those a slate will be, so a single fixed exponent is a compromise
between slates that genuinely disagree.

The honest out of sample error therefore ROSE from 3.27 on two slates to 3.61
on three. The two-slate figure was luck, not skill, and this is the better
estimate.

WHAT THIS IS NOT FOR
Do NOT divide a captain's win rate by this to make a leverage column. That was
the intended use and it fails: on the two contests where this project had
archived a prediction beforehand, it ranked the winning captain 12th of 21 and
20th of 23, against 1st and 10th for the raw win rate on its own. (The
13 November contest predates the showdown tool's first live run, so it cannot
be scored this way.)
Because the model is monotone in salary, the ratio is close to "win rate per
dollar", which promotes cheap players who mostly do not win. The model's job is
to say how crowded a choice is, not to pick one.

KNOWN FAILURE
It under-predicts a dominant captain. Henry came through at 18.5% modelled
against 33.3% actual. When one captain is obvious to everybody the real field
concentrates harder than a salary curve can, and nothing available before lock
says which slate that will be.

WHAT THE THREE CONTESTS DO AGREE ON, which this model does not try to capture:
leverage goes to whoever captained the TOP SCORER, and being popular costs
nothing if you are also right.

    13 Nov  most owned Jayden Daniels 23.3%, scored 34.14, second best   0.01x
            top scorer Isaiah Likely  14.3%, scored 46.05                5.08x
    15 Nov  most owned Ja'Marr Chase  20.1%, scored 55.65, best          3.39x
    16 Nov  most owned Derrick Henry  33.3%, scored 28.50, second best   0.78x
            top scorer Omarion Hampton 2.2%, scored 30.75               11.18x

Three for three: the most owned captain is only punished when he is not the
best one. "Fade the chalk captain" remains wrong.
"""

# Best single value across 26 captains and three contests (13, 15 and 16
# November 2026). The slates individually want 1.45, 3.30 and 7.95, so this is
# a compromise and not a measurement. Refit it as contests accumulate, and do
# not read precision into the third significant figure.
EXPONENT = 3.3

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
            f"100%, fitted on 26 captains over 3 contests: about 3.6 points of "
            f"mean error out of sample against 5.8 for spreading evenly. The "
            f"exponent varies 1.5 to 8.0 by slate, so read the ordering rather "
            f"than the level")
