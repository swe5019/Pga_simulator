#!/usr/bin/env python3
"""
flex_ownership.py — how crowded each NON-captain showdown slot is, before lock.

IS THIS JUST THE CAPTAIN MODEL AGAIN? No. They are two separate markets and
the field behaves differently in each, which the five captured contests show
plainly. Taking the 45 players who appear in BOTH markets on the same slate,
the ratio of flex ownership to captain ownership runs from 1.4 to 32.0, with a
median of 4.4. If one were a rescaling of the other that ratio would be
roughly constant. It is not:

    Derrick Henry   $10,000   flex 47.6%   captain 33.3%   ratio  1.4
    Tyler Bass      $ 4,600   flex 32.6%   captain  2.0%   ratio 16.3
    Cameron Dicker  $ 5,400   flex 28.0%   captain  1.4%   ratio 20.0

The field captains expensive skill players and fills the flex with everybody
else. Measured as a power law on salary, captain ownership has an exponent
near 3.3 while flex ownership sits between 0.70 and 1.45 by slate. The captain
market is steep and winner-take-most; the flex market is nearly flat.

The second difference is the quarterback. Averaged across the five contests a
flexed quarterback is owned 50.8%, against 16% to 23% for every other position
at comparable money. Almost everybody rosters the quarterback somewhere, and
almost nobody captains him.

THE MODEL

    flex ownership  proportional to  (salary/1000) ** EXPONENT  x  POS[position]

normalised so the whole pool sums to 500%, which is what flex ownership sums
to across a showdown slate (captain ownership sums to 100%).

VALIDATION
98 flex observations over five contests, holding each slate out in turn:

    spread evenly (baseline)                  MAE 12.15
    salary alone                              MAE  7.25
    salary with one quarterback multiplier    MAE  6.75
    salary with all six positions             MAE  6.31   <- shipped

Using salary relative to the slate's most expensive player instead of absolute
dollars scores 6.31 as well, so the simpler absolute form is kept.

THAT 6.31 IS MEASURED IN AN EASIER SETTING THAN PRODUCTION, and the honest
number is worse. It is fitted and scored over the captured rows only, which
are by construction the players the field actually rostered. Production runs
the model over the WHOLE DraftKings pool, backup quarterbacks included, and
they absorb ownership that then goes missing from everyone else. Scoring the
full pool and then comparing only the players the capture lists, over the
three contests where both the pool and a pre-kickoff props snapshot could be
recovered:

    no guard                                  MAE 10.20
    with the no-markets guard                 MAE  7.21
    with the guard, holding each slate out    MAE  7.48   <- the real number

Quote 7.5 points, not 6.3. The exponent survives the move: 1.46 scores 7.21
against a best-in-setting 1.52 at 7.14, which is noise, so it is left alone.

THIS IS A COARSE MODEL AND THE NUMBER TO REMEMBER IS SEVEN AND A HALF POINTS.
Flex ownership averages about 22%, so that is roughly a third of the typical
value. It is half the error of assuming everyone is
equally owned, and it is enough to separate a 50% player from a 15% one, but
it will not tell you that someone is 18% rather than 24%. Read it in bands,
not as a figure.

KNOWN BIAS: it cannot push low enough. Pooled over the held-out slates, the
players who finished under 10% owned averaged 6.4% actual against 9.7%
modelled, while the 40%-and-up group came in at 50.4% actual against 46.0%
modelled. The curve is too flat at both ends. If you are hunting for a genuine
sub-5% flex play this model will not find it for you.

WHAT THIS IS NOT FOR
The same prohibition as the captain model: do NOT divide a win rate by this to
manufacture a leverage column. The model is monotone in salary within a
position, so the ratio collapses toward "win rate per dollar", which promotes
cheap players who mostly do not win. Dividing by the CAPTAIN model ranked the
actual winning captain 12th of 21 and 20th of 23 on the two contests where it
could be checked, against 1st and 10th for the raw win rate. There is no
reason to expect this one to behave better, and with six points of error it
has more room to behave worse.

WHAT IT IS FOR
Telling you how much of the field you share a lineup with. Every one of the
five winning lineups scored so far was chalk-heavy, 149.6% to 175.0% of summed
ownership with 1 to 32 duplicates, so this is not a tool for avoiding popular
players. It is a tool for knowing the bill before you pay it.
"""

# (salary/1000) ** EXPONENT. Fitted jointly with the position multipliers on
# all five contests by coordinate descent. The exponent and the multipliers
# trade off against each other, so neither is meaningful on its own.
EXPONENT = 1.46

# Position multipliers, relative to a wide receiver at 1.00. These are six
# parameters fitted on five slates: the ORDERING is the signal and the second
# decimal place is not. The cheap positions are lifted because a showdown
# roster needs salary relief somewhere, and kickers and defences are where the
# field takes it.
POS = {
    "QB": 1.30,
    "RB": 0.90,
    "WR": 1.00,
    "TE": 1.30,
    "K": 1.50,
    "DST": 1.30,
}

# Flex ownership sums to 500% across a showdown slate: five non-captain slots,
# each of which is 100% spoken for.
TOTAL = 500.0

# Below this the model cannot tell one player from another, given six points
# of error, so it reports a floor rather than a number that invites division.
MIN_REPORTABLE = 0.5


def is_rostered(p):
    """Will the field put this player in a lineup at all?

    THE FIELD DOES NOT ROSTER A PLAYER THE BOOK WILL NOT PRICE. Over the three
    contests where the full DraftKings pool and a pre-kickoff props snapshot
    could both be recovered, of the players priced at $4,000 or more:

        with prop markets      43 players, 93.0% owned enough to be listed
        with no prop markets   23 players,  0.0%

    Not one of the 23. They were backup quarterbacks priced at the showdown
    minimum, ruled-out starters, and two kickers. The salary curve on its own
    had them at 17.5% each.

    DEFENCES ARE EXEMPT, because they never carry player props by
    construction, so absence of markets says nothing about them. Two of the
    six defences in that sample were rostered at 19.3% and 11.1%.

    `anchors` is the count of de-vigged volume markets behind the player's
    projection, which data/nfl_projections.json already carries. When the
    caller does not supply it, nothing is excluded: a model that cannot see
    the evidence must not act as though it has.
    """
    if p.get("pos") == "DST":
        return True
    a = p.get("anchors")
    if a is None:
        return True
    return a > 0


def flex_ownership(players, exponent=EXPONENT, pos_mult=None, total=TOTAL):
    """players: [{'player': name, 'sal': flex salary, 'pos': position,
                  'anchors': how many prop markets back his projection}]
    -> {name: percent of entries rostering him in a flex slot}.

    `sal` is the FLEX salary, not the captain price. A player not matched to a
    position is treated as a wide receiver, the neutral multiplier, rather than
    dropped: a missing position should cost accuracy, not remove a player from
    the field's roster entirely.

    `anchors` is optional and omitting it only loses the guard described in
    is_rostered. A player the guard excludes is still RETURNED, at the floor,
    rather than dropped, so a caller cannot silently lose a row.
    """
    mult = POS if pos_mult is None else pos_mult
    pool = [p for p in players if (p.get("sal") or 0) > 0]
    if not pool:
        return {}
    weights = {}
    unrostered = {}
    for p in pool:
        if not is_rostered(p):
            unrostered[p["player"]] = MIN_REPORTABLE
            continue
        w = (float(p["sal"]) / 1000.0) ** exponent
        weights[p["player"]] = w * mult.get(p.get("pos"), 1.0)
    if sum(weights.values()) <= 0:
        return dict(unrostered)

    # A player occupies at most one flex slot per lineup, so he cannot be in
    # more than 100% of entries however the weights fall. A raw normalisation
    # has no such ceiling and will happily hand a short pool 499%. Cap at 100
    # and share the remainder among whoever is still under it, repeating
    # because redistributing can push the next player over in turn. This is
    # the same water-filling the real field performs by construction.
    cap, out, free = 100.0, {}, dict(weights)
    budget = min(total, 100.0 * len(weights))   # a pool of 4 cannot reach 500
    for _ in range(len(weights) + 1):
        denom = sum(free.values())
        if not free or denom <= 0:
            break
        over = {n for n, w in free.items() if budget * w / denom > cap}
        if not over:
            for n, w in free.items():
                out[n] = budget * w / denom
            break
        for n in over:
            out[n] = cap
            free.pop(n)
        budget -= cap * len(over)
    out = {n: max(v, MIN_REPORTABLE) for n, v in out.items()}
    out.update(unrostered)
    return out


def describe():
    return (f"flex ownership modelled as (salary/1000)^{EXPONENT} times a "
            f"position multiplier, normalised to 500%, fitted on 98 players "
            f"over 5 contests: about 7.5 points of mean error out of sample "
            f"against a full slate pool, which is roughly a third of a typical "
            f"flex ownership, so read it in bands rather than as a figure. "
            f"Players the book posts no markets for are treated as unrostered: "
            f"23 of 23 such players went unrostered in the sample")
