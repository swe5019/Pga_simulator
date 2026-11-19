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
ownership correlates about +0.73 with the player's flex salary and more weakly
with his flex ownership, and the relationship is a power law: the log of
captain ownership against the log of salary correlates +0.78 to +0.88.

So the model is deliberately almost trivial:

    captain ownership  proportional to  salary ** EXPONENT,  normalised to 100%

VALIDATION
Forty five captains across five contests, holding each slate out in turn and
fitting the exponent on the other four:

    hold out  8 Nov   fit 3.23   MAE 3.80   against a 3.85 baseline
    hold out  9 Nov   fit 2.87   MAE 2.75   against 6.56
    hold out 13 Nov   fit 3.23   MAE 4.54   against 5.91
    hold out 15 Nov   fit 3.11   MAE 1.94   against 5.03
    hold out 16 Nov   fit 2.71   MAE 4.03   against 6.49
    pooled                       MAE 3.41   against 5.66

The baseline is spreading the captured ownership evenly over the captains.

Adding this project's own simulated captain win rate makes it WORSE out of
sample even though it looks better in sample. The field is not simulating, it
is reading the price, and a second parameter on this little data fits noise.

THE EXPONENT IS NOT WORTH TUNING FURTHER. Over all five slates, 3.11 gives a
weighted MAE of 3.314, 3.25 gives 3.319 and the shipped 3.3 gives 3.329. That
is a fortieth of a point between them, far inside the noise, so the shipped
value stays where it is and should be left alone until there is much more
data.

WHERE IT EARNS NOTHING, which is the real limitation
On 8 November the captain market was flat: the most owned captain took 20.9%
of what was captured, against 52.9% on 16 November. On that slate the model
scored 3.80 against a baseline of 3.85. It was no better than assuming every
captain is equally popular, because the field itself was close to that. The
model only pays when the field concentrates, and it cannot tell beforehand
which slate that will be.

A WEAKER CLAIM THAN I FIRST MADE. The per-slate exponent does rise with how
concentrated the captain market is, but on five slates the relationship rests
almost entirely on one extreme point:

    slate     top captain's share of captured market    best exponent
     8 Nov                20.9%                              1.83
    15 Nov                23.8%                              3.31
    13 Nov                27.4%                              1.43
     9 Nov                28.5%                              3.23
    16 Nov                52.9%                              9.95

Rank correlation +0.50 over five slates, which is not evidence of much. Four
of the five sit between 21% and 29% concentration and their exponents bounce
between 1.4 and 3.3 with no order to them. Drop the fifth and the pattern
disappears. Read this as "one runaway captain needs a much steeper curve",
not as a dial that tracks concentration smoothly.

A CONFOUND WORTH NAMING: 16 November is also the least complete capture, 63.0%
of the captain market against 84 to 87% for the other four. The rows that are
missing are the low-owned ones, and leaving them out makes any distribution
look more concentrated than it is, so some of that 9.95 is probably an artifact
of the capture rather than a fact about the slate. Expressing concentration as
a share of what was captured, as the table above does, controls for part of
this but not for the shape of the missing tail.

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

WHAT EVERY CONTEST SO FAR AGREES ON, which this model does not try to capture:
leverage goes to whoever captained the TOP SCORER, and being popular costs
nothing if you are also right.

     8 Nov  most owned D'Andre Swift   17.6%, scored  4.65, worst       0.00x
            top scorer Bucky Irving     9.7%, scored 42.75              4.81x
     9 Nov  most owned Josh Allen     24.7%, scored 20.79, third best   0.63x
            top scorer James Cook     13.0%, scored 29.55                4.91x
    13 Nov  most owned Jayden Daniels 23.3%, scored 34.14, second best   0.01x
            top scorer Isaiah Likely  14.3%, scored 46.05                5.08x
    15 Nov  most owned Ja'Marr Chase  20.1%, scored 55.65, best          3.39x
    16 Nov  most owned Derrick Henry  33.3%, scored 28.50, second best   0.78x
            top scorer Omarion Hampton 2.2%, scored 30.75               11.18x

Five for five: whoever captained the top scorer was paid, between 3.4x and
11.2x, and the most owned captain returned almost nothing every time he was
not that player. Being popular costs nothing if you are also right, which is
why "fade the chalk captain" stays withdrawn. The most owned captain has been
the top scorer once in five.
"""

# Across 45 captains and five contests (8, 9, 13, 15 and 16 November 2026) the
# all-slate optimum is 3.11, and the difference between 3.11, 3.25 and 3.3 is
# about a fortieth of a point of error. There is nothing to choose between
# them, so this is left alone. Revisit only on a much larger sample.
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
            f"100%, fitted on 45 captains over 5 contests: about 3.4 points of "
            f"mean error out of sample against 5.7 for spreading evenly. The "
            f"exponent varies 1.5 to 10 by slate, so read the ordering rather "
            f"than the level")
