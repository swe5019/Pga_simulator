#!/usr/bin/env python3
"""
simulate_props.py — simulate each prop at the play level and attach SIM%.

Reads data/nfl_props_full.json (written by enrich_props.py) and rewrites it
with a simulated probability on every line it can model.

WHY A SIMULATION WHEN THERE IS ALREADY A HIT RATE
A hit rate asks one question: how often has this player beaten THIS number.
It is honest and it is what a reader wants to see, but it is blunt in three
ways that cost money.

  It cannot tell neighbouring lines apart. A receiver with 20 games has at most
  21 possible hit rates. Receptions at 4.5 and at 5.5 can come back identical
  when they are plainly different bets.

  It throws away almost all the data. A player with 30 games has 30 data points
  for a hit rate and perhaps 200 individual plays. The 200 are what decide a
  longest reception, where the whole question is the tail: "has he ever broken
  one" is not answerable from game totals.

  It cannot recombine. A player whose target count has doubled but whose yards
  per catch is unchanged has no usable history against today's line, yet both
  of his inputs are perfectly well measured.

So this fits the pieces separately, volume and efficiency, and puts them back
together ten thousand times.

THE MODELS
Four, because four kinds of question are being asked.

  COUNTS     receptions, targets, attempts, completions
             Negative binomial on the count itself. Its mean AND variance come
             from his own games, which matters: a back who alternates 4 and 18
             carries is a different bet from one who takes 11 every week, and a
             model fixing variance to the mean (Poisson) would price them the
             same.

  YARDAGE    receiving, rushing, passing, and the combinations
             Two stages. Draw how many plays, then draw each play's yardage
             from his own plays. Summing beats fitting a curve to game totals
             because a 12 target game and a 4 target game are not two samples
             of one quantity.

  LONGEST    longest reception, rush, completion
             The same draws, taking the maximum instead of the sum. This is the
             market that most needs a simulation and least suits a hit rate.

  TOUCHDOWNS anytime, passing, the 1Q and 1H versions
             Per-opportunity scoring rate against simulated volume. Note that
             the matchup multiplier has to move the RATE here. Scaling the line
             would do nothing at all, because a 0.5 line asks only whether the
             count is zero and no multiplier changes that.

WHERE THE NUMBERS COME FROM, AND WHAT THEY ARE SHRUNK TOWARD
Every input is role weighted exactly as the hit rate is: a game at a different
snap share counts less, so a backup's workload is not read as evidence about a
starter. Each is then pulled toward the baseline for his POSITION, by how much
comparable evidence he has.

That prior is deliberately not the market. The hit rate already leans on the
price, and a simulation that did the same would agree with the market by
construction and be worth nothing. This one is free to disagree, which is the
entire point of showing both columns, and is also why a thin-history player's
SIM% should be read as little more than a positional average.

WHAT IS NOT SIMULATED
Fumbles lost, because fumbles are not attributed per play in what is
extracted. First and last touchdown scorer, because those depend on the
ordering of scores across a whole game rather than on one player's
distribution. Kicking and defensive props, which are not in the stats pipeline
at all. Those keep their hit rate and show no SIM%.
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

# Shared history loading, so the simulation and the hit rate cannot drift apart
# in how they read a game log or weight a role.
from enrich_props import (
    FULL, H1, MATCHUP_STAT, Q1, current_role, game_logs, load_pbp,
    load_seasons, nrm, role_weight,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Draws per line. 20,000 puts the sampling error on a probability near 50% at
# about 0.35 of a percentage point, which is well inside the error of the
# inputs and therefore not the thing worth spending time on.
TRIALS = 20_000
SEED = 20261015      # fixed, so a rerun on unchanged data gives the same page

# Shrinkage priors, in games or plays. Each is the amount of evidence at which
# a player's own figure and his position's baseline carry equal weight.
# SIM_PRIOR overrides it when sweeping this against out-of-sample bias.
PRIOR_GAMES = float(os.environ.get("SIM_PRIOR") or 6)   # per-game volume mean
PRIOR_PLAYS = 40     # for a per-play yardage distribution
PRIOR_RATE = 30      # for a per-opportunity rate, such as a touchdown
# Half-life in games for how fast old football stops counting. Role weighting
# answers "was this the same job"; this answers "was this the same player". A
# receiver's own yards per game come in at 0.82 of the previous season's and
# 0.92 the year after, so weighting his three-season-old self equally with his
# current self over-projects him, which showed up out of sample as every market
# reading 3 to 10 percent high. Set by sweeping it against out-of-sample bias,
# not by taste; SIM_HALFLIFE overrides it for that sweep.
HALF_LIFE = float(os.environ.get("SIM_HALFLIFE") or 22)
# Below this many effective games the simulation is reported but flagged, since
# it is then mostly describing the position rather than the player.
MIN_GAMES = 4
# Position plays are subsampled to this many before being mixed into a player's
# own pool. The pool only has to represent a shape, and a few thousand draws
# represent it just as well as ninety thousand.
POS_POOL = 3_000
# A player's weighted play pool is resampled once into this many flat draws,
# after which sampling is uniform integer indexing instead of a weighted draw.
# Weighted sampling costs a binary search per draw and dominated the runtime;
# this makes it a lookup. Four thousand draws leave the resampling error far
# below the error already in the inputs.
POOL_FLAT = 4_000


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------
# Market definitions
# --------------------------------------------------------------------------
# Each market says: which model, which quantity, which periods, and which
# matchup multiplier applies to it.
#
#   COUNT    (quantity, periods, multiplier stat)
#   YARDS    (quantity, periods, multiplier stat)
#   LONGEST  (quantity, multiplier stat)
#   TD       (quantity, periods, multiplier stat)
#
COUNT = {
    "Receptions":        ("rec", FULL, "Receptions"),
    "Targets":           ("tgt", FULL, "Targets"),
    "Rush Attempts":     ("car", FULL, "Rush Attempts"),
    "Pass Attempts":     ("patt", FULL, "Pass Attempts"),
    "Completions":       ("cmp", FULL, "Completions"),
    "1Q Receptions":     ("rec", Q1, "Receptions"),
    "1H Receptions":     ("rec", H1, "Receptions"),
    "1Q Targets":        ("tgt", Q1, "Targets"),
    "1H Targets":        ("tgt", H1, "Targets"),
    "1Q Rush Attempts":  ("car", Q1, "Rush Attempts"),
    "1H Rush Attempts":  ("car", H1, "Rush Attempts"),
    "1Q Pass Attempts":  ("patt", Q1, "Pass Attempts"),
    "1H Pass Attempts":  ("patt", H1, "Pass Attempts"),
    "1Q Completions":    ("cmp", Q1, "Completions"),
    "1H Completions":    ("cmp", H1, "Completions"),
}

YARDS = {
    "Receiving Yards":      (("ry",), FULL, "Receiving Yards"),
    "Rush Yards":           (("uy",), FULL, "Rush Yards"),
    "Pass Yards":           (("py",), FULL, "Pass Yards"),
    "Rush + Rec Yards":     (("uy", "ry"), FULL, "Rush + Rec Yards"),
    "Pass + Rush Yards":    (("py", "uy"), FULL, "Pass + Rush Yards"),
    "1Q Rec Yards":         (("ry",), Q1, "Receiving Yards"),
    "1H Rec Yards":         (("ry",), H1, "Receiving Yards"),
    "1Q Rush Yards":        (("uy",), Q1, "Rush Yards"),
    "1H Rush Yards":        (("uy",), H1, "Rush Yards"),
    "1Q Pass Yards":        (("py",), Q1, "Pass Yards"),
    "1H Pass Yards":        (("py",), H1, "Pass Yards"),
    "1Q Rush + Rec Yards":  (("uy", "ry"), Q1, "Rush + Rec Yards"),
    "1H Rush + Rec Yards":  (("uy", "ry"), H1, "Rush + Rec Yards"),
}

LONGEST = {
    "Longest Reception":  ("ry", "Receiving Yards"),
    "Longest Rush":       ("uy", "Rush Yards"),
    "Longest Completion": ("py", "Pass Yards"),
}

TD = {
    "Anytime TD":          (("rtd", "utd"), FULL, "Anytime TD"),
    "Pass TDs":            (("ptd",), FULL, "Pass TDs"),
    "INTs Thrown":         (("int",), FULL, None),
    "1Q Pass TDs":         (("ptd",), Q1, "Pass TDs"),
    "1H Pass TDs":         (("ptd",), H1, "Pass TDs"),
    "1Q Rush + Rec TDs":   (("rtd", "utd"), Q1, "Anytime TD"),
    "1H Rush + Rec TDs":   (("rtd", "utd"), H1, "Anytime TD"),
}

# Which volume each per-play yardage pool is counted out of, and which
# opportunity each scoring rate is measured against.
VOLUME_OF = {"ry": "rec", "uy": "car", "py": "cmp"}
RATE_OF = {"rtd": "rec", "utd": "car", "ptd": "cmp", "int": "patt"}


# --------------------------------------------------------------------------
# Per-game and per-play extraction
# --------------------------------------------------------------------------
def game_values(r, periods):
    """One game's counts and individual plays, for the requested periods.

    Returns None when the game has no play by play, which drops it from the
    fit rather than feeding it in as a row of zeros."""
    ps = r.get("_p")
    if ps is None:
        return None
    sel = [ps[k] for k in periods if k < len(ps)]
    ry = [y for p in sel for y in p.get("ry", [])]
    uy = [y for p in sel for y in p.get("uy", [])]
    py = [y for p in sel for y in p.get("py", [])]
    return {
        "rec": len(ry),
        "tgt": len(ry) + sum(p.get("inc", 0) for p in sel),
        "car": len(uy),
        "cmp": len(py),
        "patt": len(py) + sum(p.get("pinc", 0) for p in sel),
        "rtd": sum(p.get("rtd", 0) for p in sel),
        "utd": sum(p.get("utd", 0) for p in sel),
        "ptd": sum(p.get("ptd", 0) for p in sel),
        "int": sum(p.get("int", 0) for p in sel),
        # The individual plays. These are the whole reason this file exists.
        "_ry": ry, "_uy": uy, "_py": py,
    }


def fit(rows, periods, role_now):
    """Fit one player's volume, efficiency and scoring rates over a window.

    Every game is weighted by how close its snap share was to his role now,
    which is the same weighting the hit rate uses. Returns None when no game in
    the window has play by play."""
    # Newest first, by season then week, so "games ago" means the same thing
    # however the caller put the list together. The live run already supplies
    # them in order; the backtest does not, and silently fitting a decay to a
    # reversed list would have inverted it.
    ordered = sorted(rows, key=lambda r: (-(r.get("_yr") or 0), -r["w"]))
    games = []
    for k, r in enumerate(ordered):
        g = game_values(r, periods)
        if g is None:
            continue
        # Two independent reasons a past game counts less: it was a different
        # job, and it was a different player. Multiplied, not chosen between.
        w = role_weight(r.get("_snap"), role_now) * (0.5 ** (k / HALF_LIFE))
        games.append((g, w))
    if not games:
        return None

    wsum = sum(w for _, w in games)
    w2sum = sum(w * w for _, w in games)
    if wsum <= 0:
        return None
    eff_games = (wsum * wsum / w2sum) if w2sum else 0.0

    out = {"effGames": eff_games, "games": len(games), "roleNow": role_now}

    # HOW OFTEN HE DOES NOT GET A FULL GAME.
    #
    # Role weighting answers "was this the same job", and it answers it well,
    # but on its own it quietly asks the wrong question. A quarterback pulled
    # at half time played 50% of the snaps, which sits so far from his role
    # that the curve weights that game at about 0.006 — effectively deleting
    # it. So the fitted volume describes a full game, while the game being
    # predicted might be another half. Measured out of sample, that inflated
    # quarterback passing volume by 5% while his plain unweighted average was
    # unbiased, which is how it was found.
    #
    # So the role fit stays as it is, and the chance of a short game is put
    # back separately: the unconditional spread of how much of his own role he
    # actually played, which the simulation draws from per trial. Deliberately
    # NOT role weighted, because the whole point is to recover the games role
    # weighting set aside.
    # NORMALISED AGAINST WHAT THE FIT ALREADY ABSORBED, which is the part that
    # is easy to get wrong and was.
    #
    # The fitted mean is not the unconditional mean; it is the mean under the
    # role weights. So the correction is not E[part], it is the ratio
    # E[part] / E_weighted[part]: how much of a game he gets on average,
    # against how much of one the fit was already looking at.
    #
    # That ratio is what distinguishes the two positions. For a quarterback the
    # weights pile onto full games, so the weighted mean is about 1 and the
    # ratio bites. For a running back the snap share moves around smoothly, the
    # role curve is broad enough to keep most of it, the weighted and plain
    # means nearly agree, and the ratio is close to 1 so almost nothing
    # changes. Applying a raw E[part] instead corrected quarterbacks and
    # dragged running backs to 10% BELOW actual, which is how this was caught.
    parts, pw_num, pw_den = [], 0.0, 0.0
    for r in ordered:
        sn = r.get("_snap")
        if sn is None or not role_now:
            continue
        # Capped: a game above his recent role is ordinary variation, not
        # evidence he can play 125% of a game.
        pt = min(sn / role_now, 1.25)
        parts.append(pt)
        w = role_weight(sn, role_now)
        pw_num += pt * w
        pw_den += w
    if len(parts) >= 6 and pw_den > 0:
        pw = pw_num / pw_den
        arr = np.asarray(parts, dtype=np.float64) / max(pw, 1e-6)
        # A game cannot be worth more than a game and a quarter however the
        # normalisation lands.
        out["_parts"] = np.clip(arr, 0.0, 1.25)
    else:
        out["_parts"] = np.ones(1)

    # Volume: weighted mean and weighted variance of the per-game count. The
    # variance is carried because it is half the answer on a count market.
    for k in ("rec", "tgt", "car", "cmp", "patt"):
        m = sum(g[k] * w for g, w in games) / wsum
        v = sum(((g[k] - m) ** 2) * w for g, w in games) / wsum
        out[k] = (m, v)

    # Scoring: successes over opportunities, both weighted.
    for k, vol in RATE_OF.items():
        num = sum(g[k] * w for g, w in games) / wsum
        den = sum(g[vol] * w for g, w in games) / wsum
        out[k] = (num, den)

    # Plays: each play carries its game's weight, so a play from a game at the
    # wrong role is sampled less often rather than excluded outright.
    for k in ("_ry", "_uy", "_py"):
        vals, wts = [], []
        for g, w in games:
            for y in g[k]:
                vals.append(y)
                wts.append(w)
        out[k] = (np.asarray(vals, dtype=np.float64),
                  np.asarray(wts, dtype=np.float64))
    return out


def position_baselines(logs, meta, seasons, periods):
    """Pooled figures per position, used as the prior every player is pulled
    toward.

    VOLUME is kept as raw per-game values alongside the snap share each was
    recorded at, rather than averaged here, because the average over all games
    at a position is the wrong prior for anybody. The pool is full of backups
    and of halves played by someone who got hurt, so "the average quarterback
    game" is nothing like a starting quarterback's game, and shrinking a
    starter toward it quietly takes about seven yards per game off him. Whoever
    asks for the prior supplies the role it should be conditioned on.

    EFFICIENCY and SCORING RATES are pooled flat. Yards per catch and
    touchdowns per carry depend far less on how big a player's role is than
    volume does, so conditioning them buys little and costs sample size where
    these are thinnest."""
    vol = defaultdict(lambda: defaultdict(list))
    snaps = defaultdict(list)
    plays = defaultdict(lambda: defaultdict(list))
    rate = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for key, byyear in logs.items():
        pos = meta.get(key)
        if not pos:
            continue
        for yr, rows in byyear.items():
            for r in rows:
                g = game_values(r, periods)
                if g is None:
                    continue
                for k in ("rec", "tgt", "car", "cmp", "patt"):
                    vol[pos][k].append(g[k])
                snaps[pos].append(r.get("_snap"))
                for k, v in RATE_OF.items():
                    rate[pos][k][0] += g[k]
                    rate[pos][k][1] += g[v]
                for k in ("_ry", "_uy", "_py"):
                    plays[pos][k].extend(g[k])

    rng = np.random.default_rng(SEED)
    out = {}
    for pos in vol:
        d = {"_vol": {}, "_snaps": np.asarray(
            [np.nan if s is None else s for s in snaps[pos]], dtype=np.float64)}
        for k, vals in vol[pos].items():
            d["_vol"][k] = np.asarray(vals, dtype=np.float64)
        for k, (num, den) in rate[pos].items():
            d[k] = (num / den) if den > 0 else 0.0
        for k, vals in plays[pos].items():
            a = np.asarray(vals, dtype=np.float64)
            if a.size > POS_POOL:
                a = rng.choice(a, size=POS_POOL, replace=False)
            d[k] = a
        out[pos] = d
    return out


def role_prior(base, role_now):
    """The position's volume at THIS role, as a mean and variance per stat.

    Each position game is weighted by how close its snap share was to the role
    being asked about, using the same curve that weights a player's own games.
    So a starter is compared against other starters' games and a rotational
    player against other rotational games. Games with no snap data count fully,
    matching the fallback used everywhere else here.

    With no known role, or too little of the pool nearby to mean anything, this
    falls back to the flat average, which is the old behaviour and still better
    than nothing."""
    volumes = base.get("_vol")
    if not volumes:
        return {}
    snaps = base["_snaps"]
    if role_now is None:
        w = np.ones(len(snaps))
    else:
        d = (snaps - role_now) / 0.22
        w = np.exp(-(d * d))
        w = np.where(np.isnan(snaps), 1.0, w)
        # Kish's effective sample size again. Below a handful of comparable
        # games the conditioned prior is itself noise, so take the flat one.
        wsum = w.sum()
        if wsum <= 0 or (wsum * wsum / max((w * w).sum(), 1e-12)) < 25:
            w = np.ones(len(snaps))
    tot = w.sum()
    out = {}
    for k, vals in volumes.items():
        m = float((vals * w).sum() / tot)
        v = float((((vals - m) ** 2) * w).sum() / tot)
        out[k] = (m, v)
    return out


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------
def draw_counts(rng, mean, var, n, parts=None):
    """Per-game counts, overdispersed to match what he has actually done.

    A negative binomial matched on both moments. When the observed variance is
    no greater than the mean there is nothing to overdisperse and a Poisson is
    the right, simpler answer; forcing a negative binomial there produces an
    enormous shape parameter and numerical nonsense.

    `parts` is the spread of how much of a game he tends to get. Each trial
    draws one and the mean is scaled by it, so the dispersion shape is kept
    while the chance of a short game is carried on top of it."""
    mean = max(float(mean), 1e-9)
    var = float(var)
    lam = mean
    if parts is not None and len(parts) > 1:
        lam = mean * rng.choice(parts, size=n)
        lam = np.maximum(lam, 1e-9)
    if var <= mean * 1.05:
        return rng.poisson(lam, size=None if parts is not None
                           and len(parts) > 1 else n)
    r = mean * mean / (var - mean)
    r = min(max(r, 0.05), 1e6)
    p = r / (r + lam)
    if np.isscalar(p):
        return rng.negative_binomial(r, p, size=n)
    return rng.negative_binomial(r, p)


def mix_pool(own, pos_pool):
    """A player's own plays, topped up with his position's.

    With few plays of his own the shape he shows is mostly noise, so the
    position's shape fills in; with hundreds, his own dominates. Returned as
    values plus sampling probabilities rather than as a resampled array, so no
    information is thrown away before the draw."""
    vals, wts = own
    own_n = float(wts.sum()) if wts.size else 0.0
    if own_n <= 0:
        if pos_pool is None or not len(pos_pool):
            return None, None
        return pos_pool, np.full(len(pos_pool), 1.0 / len(pos_pool))
    share = own_n / (own_n + PRIOR_PLAYS)
    if pos_pool is None or not len(pos_pool) or share >= 0.999:
        return vals, wts / wts.sum()
    p_own = (wts / wts.sum()) * share
    p_pos = np.full(len(pos_pool), (1.0 - share) / len(pos_pool))
    return np.concatenate([vals, pos_pool]), np.concatenate([p_own, p_pos])


def flat_pool(rng, f, kind, base):
    """The player's play pool, resampled once into a flat array.

    Cached on the fit, so a player's three markets on the same quantity share
    it. Sampling a weighted distribution costs a search per draw; sampling a
    flat one is an array index, which is what makes a few hundred thousand
    simulations practical."""
    key = f"_flat{kind}"
    if key not in f:
        vals, probs = mix_pool(f[f"_{kind}"], base.get(f"_{kind}"))
        f[key] = (None if vals is None
                  else rng.choice(vals, size=POOL_FLAT, p=probs))
    return f[key]


def draw_plays(rng, counts, pool, scale=1.0):
    """For each trial, `counts[t]` individual plays.

    Returned as a padded matrix with a validity mask rather than a ragged list,
    because the sum and the maximum are then single vectorised operations. The
    padding is the memory cost of the whole approach and it is small: twenty
    thousand trials by the busiest game anyone has had."""
    k = int(counts.max()) if counts.size else 0
    if k <= 0:
        z = np.zeros((len(counts), 1))
        return z, np.zeros((len(counts), 1), dtype=bool)
    idx = rng.integers(0, len(pool), size=(len(counts), k))
    draws = pool[idx] * scale
    mask = np.arange(k)[None, :] < counts[:, None]
    return draws, mask


def shrink(own, own_n, prior, prior_n):
    """Pull a figure toward its prior by how much evidence stands behind it."""
    if own is None:
        return prior
    return (own_n * own + prior_n * prior) / (own_n + prior_n)


def simulate(rng, stat, line_rows, f, base, mult, prior):
    """Simulate one player's distribution for one market, then read every line
    on it off the same sample.

    Both sides of a line therefore sum to exactly one, and neighbouring lines
    come back correctly ordered, neither of which a hit rate guarantees."""
    eff = f["effGames"]

    def vol(kind, scale=1.0):
        own_m, own_v = f[kind]
        pm, pv = prior.get(kind, (own_m, own_v))
        m = shrink(own_m, eff, pm, PRIOR_GAMES) * scale
        # The variance is shrunk on the same terms, then floored at the mean so
        # a short sample that happens to look steady cannot produce a
        # distribution tighter than chance allows.
        v = max(shrink(own_v, eff, pv, PRIOR_GAMES) * scale * scale, m)
        # Each trial gets its own share of a game. Applied to volume only: a
        # quarterback pulled early throws fewer passes, he does not throw
        # shorter ones.
        return draw_counts(rng, m, v, TRIALS, f.get("_parts"))

    if stat in COUNT:
        kind, _periods, _ms = COUNT[stat]
        # The multiplier moves the count itself. Scaling the line instead would
        # be silently useless here: 4.5 over a multiplier of 1.1 is 4.09, and
        # every integer clearing one clears the other.
        return vol(kind, mult)

    if stat in YARDS:
        kinds, _periods, _ms = YARDS[stat]
        total = np.zeros(TRIALS)
        # The multiplier is split evenly between how many plays and how far
        # each one goes. A defense giving up extra yards may be giving up more
        # catches or longer ones and this cannot tell which, so it assumes
        # both. The mean total is the same either way; the shape is not.
        part = math.sqrt(mult) if mult else 1.0
        for kind in kinds:
            pool = flat_pool(rng, f, kind, base)
            if pool is None:
                continue
            counts = vol(VOLUME_OF[kind], part)
            draws, mask = draw_plays(rng, counts, pool, part)
            total = total + (draws * mask).sum(axis=1)
        return total

    if stat in LONGEST:
        kind, _ms = LONGEST[stat]
        part = math.sqrt(mult) if mult else 1.0
        pool = flat_pool(rng, f, kind, base)
        if pool is None:
            return np.zeros(TRIALS)
        counts = vol(VOLUME_OF[kind], part)
        draws, mask = draw_plays(rng, counts, pool, part)
        # A game with no plays of this kind has a longest of zero, which is a
        # real outcome and the reason the under on a low line ever loses.
        out = np.where(mask, draws, -np.inf).max(axis=1)
        return np.where(np.isfinite(out), out, 0.0).clip(min=0.0)

    if stat in TD:
        kinds, _periods, _ms = TD[stat]
        total = np.zeros(TRIALS, dtype=np.int64)
        for kind in kinds:
            volkind = RATE_OF[kind]
            num, den = f[kind]
            own_rate = (num / den) if den > 0 else None
            rate = shrink(own_rate, den * eff if den else 0.0,
                          base.get(kind, 0.0), PRIOR_RATE)
            rate = min(max(rate * mult, 0.0), 1.0)
            counts = vol(volkind)
            total = total + rng.binomial(counts, rate)
        return total.astype(np.float64)

    return None


# Markets whose answer is driven by how much work a player gets. These are the
# ones a role change wrecks, and the ones this guard covers.
VOLUME_MARKETS = frozenset((
    "Rush Attempts", "Receptions", "Targets", "Pass Attempts", "Completions",
    "Rush Yards", "Receiving Yards", "Rush + Rec Yards", "Pass Yards",
    "Pass + Rush Yards", "1Q Receptions", "1H Receptions", "1Q Targets",
    "1H Targets", "1Q Rush Yards", "1H Rush Yards", "1Q Rec Yards",
    "1H Rec Yards", "1Q Rush Attempts", "1H Rush Attempts", "1Q Pass Yards",
    "1H Pass Yards", "1Q Completions", "1H Completions",
    "1Q Rush + Rec Yards", "1H Rush + Rec Yards",
))

# Disagreement, in percentage points, at which the model stops advertising an
# edge on a volume market and asks the reader to check the news instead. Set
# from the distribution: across volume lines the median disagreement with the
# market is 9.6 points and the 90th percentile is 25, so this is the top tenth.
ROLE_FLAG_GAP = 25.0


def flag_role_divergence(props):
    """Stop the biggest fake edges on the board from looking like finds.

    THE PROBLEM THIS EXISTS FOR
    Every model here is backward looking. Role weighting asks "was this past
    game the same job he has now" and answers it well, but it cannot know about
    a job that changes this week. When a starter is ruled out, the market
    reprices the backup immediately and this model does not, because the backup
    has no history at the new workload. The model then projects a backup's
    volume against a starter's line and reports an enormous edge on the under.

    Those are the LARGEST edges on the page and they are worthless. Woody Marks
    is the case that prompted this: his role reads 55% of snaps because it
    averages two backup games with the one game the starter got hurt in, his
    rush attempts line is 14.5, the model projects 9.6, and the under showed
    +26. The market was right and the model's idea of his job was stale.

    WHAT IS MEASURED
    Not the raw gap between the projection and the line: on a small line the
    projection routinely sits far above it for ordinary reasons, so a ratio
    flags hundreds of harmless rows. Instead the model's probability is
    compared against the market's own de-vigged probability for the same
    question, which is scale free and works the same on a line of 0.5 and a
    line of 300.

    BOTH DIRECTIONS are flagged. A projection far below the line is a role
    increase nobody told the model about. Far above it is the reverse, a player
    who has lost his job or come back into a smaller one. Both are the same
    mistake and both need a human to look at the news.

    This does NOT delete anything. The numbers stay visible and the reader can
    still act on them. What it does is refuse to let these rows sort to the top
    of an edge-ranked table as though they were discoveries."""
    n = 0
    for p in props:
        if p["stat"] not in VOLUME_MARKETS:
            continue
        sim, fair = p.get("sim"), p.get("fairBE")
        if sim is None or fair is None:
            continue
        gap = sim * 100 - fair
        if abs(gap) < ROLE_FLAG_GAP:
            continue
        p["roleFlag"] = True
        p["roleGap"] = round(gap, 1)
        mu, line = p.get("simMu"), p.get("line")
        # The direction of the WARNING comes from the projection against the
        # line, never from the sign of the probability gap. Those point
        # opposite ways on the under: a smaller projected workload makes the
        # under likely, so its probability gap is positive while the workload
        # is lower. Keying the wording off the gap told the reader the exact
        # reverse of what the model thought on every under.
        if mu is None or line is None:
            continue
        if mu < line:
            p["roleWhy"] = (
                f"The market is pricing a bigger workload than this model is "
                f"projecting ({mu} against a line of {line}). That usually "
                f"means his role has changed this week and the model has not "
                f"seen it yet, not that there is value here. Check whether "
                f"somebody ahead of him is hurt before trusting the edge.")
        else:
            p["roleWhy"] = (
                f"This model is projecting a bigger workload than the market "
                f"is pricing ({mu} against a line of {line}). That usually "
                f"means his role has shrunk and the model is still using his "
                f"old one. Check the news before trusting the edge.")
        n += 1
    return n


def main():
    path = os.path.join(DATA, "nfl_props_full.json")
    if not os.path.exists(path):
        log("no nfl_props_full.json; run enrich_props.py first")
        return 1
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    props = doc["props"]

    mpath = os.path.join(DATA, "nfl_matchups.json")
    matchups = {}
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            matchups = json.load(f).get("matchups") or {}

    seasons, current = load_seasons()
    pbp = load_pbp(sorted(seasons, reverse=True))
    if not pbp:
        log("no play by play on disk; nothing can be simulated. "
            "Run fetch_nfl_pbp.py first.")
        return 1
    logs = game_logs(seasons, pbp)

    # Position per player, from the most recent season he appears in.
    meta = {}
    for yr in sorted(seasons, reverse=True):
        for p in seasons[yr]["players"]:
            meta.setdefault(nrm(p["n"]), p["p"])

    years = [y for y in (current, current - 1, current - 2) if y in seasons]
    log(f"simulating from seasons {years}, {TRIALS:,} draws per line")

    # Baselines are period specific: a first quarter is not a third of a game.
    bases = {}
    for label, periods in (("full", FULL), ("h1", H1), ("q1", Q1)):
        bases[label] = position_baselines(logs, meta, seasons, periods)
    log(f"position baselines built for {sorted(bases['full'])}")

    def period_label(periods):
        return "q1" if periods == Q1 else ("h1" if periods == H1 else "full")

    # Group by player and market: both sides and every line on a market share
    # one simulated distribution, which is what makes the two sides sum to one.
    groups = defaultdict(list)
    for p in props:
        groups[(p["player"], p["stat"])].append(p)

    rng = np.random.default_rng(SEED)
    fits = {}
    priors = {}
    counts = defaultdict(int)
    done = 0

    for (player, stat), rows in groups.items():
        spec = (COUNT.get(stat) or YARDS.get(stat) or TD.get(stat)
                or (LONGEST.get(stat) and (None, FULL, LONGEST[stat][1])))
        if spec is None:
            counts["market not simulated"] += len(rows)
            continue
        periods = FULL if stat in LONGEST else spec[1]
        # Imported from enrich_props so the multiplier applied here is the same
        # one the page displays. Identity for a market with its own.
        mstat = MATCHUP_STAT.get(stat, stat)

        key = nrm(player)
        if key not in logs:
            counts["player not in stats data"] += len(rows)
            continue
        pos = meta.get(key)
        if not pos:
            counts["no position known"] += len(rows)
            continue

        label = period_label(periods)
        fkey = (key, label)
        if fkey not in fits:
            role_now = current_role(logs[key], current)
            hist = [r for y in years for r in logs[key].get(y, [])]
            fits[fkey] = fit(hist, periods, role_now)
        f = fits[fkey]
        if f is None:
            counts["no play by play in his games"] += len(rows)
            continue

        # The matchup multiplier for the stat this market is really about. A
        # longest reception is adjusted by how the defense treats receiving
        # yards, because there is no "longest allowed" to measure.
        mult = 1.0
        if mstat:
            mm = matchups.get(f"{rows[0].get('opp', '')}|{pos}|{mstat}")
            if mm:
                mult = mm["mult"]

        base = bases[label].get(pos, {})
        # The prior is conditioned on the role he is playing now, so it is
        # per player and per period rather than per position.
        pkey = (pos, label, round(f.get("roleNow") or -1, 2))
        if pkey not in priors:
            priors[pkey] = role_prior(base, f.get("roleNow"))
        sample = simulate(rng, stat, rows, f, base, mult, priors[pkey])
        if sample is None:
            counts["market not simulated"] += len(rows)
            continue

        for p in rows:
            line = p["line"]
            over = float((sample > line).mean())
            prob = over if p["side"] == "over" else 1.0 - over
            p["sim"] = round(prob, 4)
            p["simMu"] = round(float(sample.mean()), 2)
            p["simGames"] = round(f["effGames"], 1)
            p["simThin"] = f["effGames"] < MIN_GAMES
            if p.get("decimal"):
                p["simEdge"] = round((prob - 1.0 / p["decimal"]) * 100, 1)
            counts["simulated"] += 1
            if p["simThin"]:
                counts["  of those, thin (mostly the position's baseline)"] += 1
        done += 1

    flagged = flag_role_divergence(props)
    log(f"\n{done:,} player-market distributions simulated")
    log(f"{flagged:,} sides flagged as a probable role change rather than an "
        f"edge (disagreement with the market over {ROLE_FLAG_GAP:.0f} points "
        f"on a volume market)")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        log(f"   {v:>6}  {k}")

    doc["simulatedTrials"] = TRIALS
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    log(f"\nrewrote nfl_props_full.json ({os.path.getsize(path) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
