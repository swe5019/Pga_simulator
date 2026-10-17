#!/usr/bin/env python3
"""
build_nfl_slate.py — the DraftKings main slate board. Writes
data/nfl_slate_board.json.

WHAT THIS ADDS OVER THE PROJECTIONS PAGE
A projection says how many points a player scores. A slate board says whether
he is worth rostering, which is a different question, because it depends on his
salary and on how many other people are going to roster him. A 20 point
projection at 8700 and the same 20 at 4700 are not the same play, and a 20 that
everybody is on is not the same as a 20 nobody has.

THE UNIVERSE IS DRAFTKINGS, NOT THE PROJECTIONS
Every player DK lists is shown, including the ones with no projection. 58% of
the slate joined to a projection on the first attempt, and the missing names
were Lamar Jackson, Saquon Barkley, Breece Hall: players whose betting lines
have been pulled, who are correctly absent from the projections and who must
still appear here, because DK is still offering them and a board that hides
them is lying about what the slate contains. They show with a blank projection
and the reason.

OWNERSHIP, AND WHAT IS HONEST ABOUT IT
There is no NFL ownership training data yet, so this is a theory driven model
and is labelled as one. It rests on two things.

  THE CONSTRAINT, which is the part most ownership models get wrong. A lineup
  has exactly one quarterback, so every quarterback's ownership on a slate must
  sum to 100%. Two running backs plus a share of the flex means every running
  back sums to about 230%. That is arithmetic, not opinion, and enforcing it
  stops the usual failure where a model likes eight quarterbacks and quietly
  claims 180% of lineups contain one.

  THE APPEAL, which is opinion and is stated as such. Players are rostered for
  value, for salary salience, and for upside, so appeal is a weighted blend of
  points per thousand, a mild pull toward expensive players who are obviously
  good, and ceiling. A softmax turns appeal into shares, and its temperature
  decides how concentrated the field is.

THE THREE CONTEST COLUMNS ARE ONE MODEL, NOT THREE
Single entry, high stakes and mass multi entry differ by temperature and by how
much ceiling matters, because those fields behave differently: casual single
entry play concentrates on obvious value, sharp high stakes play spreads out
and chases leverage, and mass multi entry spreads furthest because an entrant
is filling two hundred lineups and cannot put the same player in all of them.
Those are documented assumptions about behaviour, not three separately
measured models, and the page says so.

Every build archives its own ownership to data/ownership_history/ so that when
real contest results arrive this becomes checkable rather than permanently
unfalsifiable.
"""
import datetime
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HIST = os.path.join(DATA, "ownership_history")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_props import nrm  # noqa: E402

# DraftKings NFL classic: QB, RB, RB, WR, WR, WR, TE, FLEX, DST.
# The flex is shared out roughly as it is used in practice, which is mostly
# receivers, then backs, then the occasional tight end.
FLEX_SPLIT = {"RB": 0.30, "WR": 0.55, "TE": 0.15}
BASE_SLOTS = {"QB": 1.0, "RB": 2.0, "WR": 3.0, "TE": 1.0, "DST": 1.0}

# How appeal is built. Value dominates, because that is what people actually
# sort by, but not alone: a cheap player with a good value number and no path
# to a usable score is not rostered, and an expensive obvious stud is rostered
# past his value.
W_VALUE = 1.00      # points per thousand of salary
W_SALARY = 0.22     # the pull toward expensive players who are plainly good
W_CEILING = 0.35    # upside, which matters more the larger the field

# Contest behaviour. Temperature is how concentrated the field is: lower means
# more of the money piles onto the same few players.
CONTESTS = {
    # Casual, one lineup, picks the obvious plays.
    "se": {"temp": 0.78, "ceil": 0.20,
           "label": "Single entry: concentrated on obvious value"},
    # Sharp money, aware of what the field is doing, actively avoids it.
    "hs": {"temp": 1.00, "ceil": 0.45,
           "label": "High stakes: flatter, pays for upside"},
    # Two hundred lineups each, so the same player cannot be in all of them.
    "mme": {"temp": 1.25, "ceil": 0.60,
            "label": "Mass multi entry: flattest, chases ceiling"},
}

# A score a position needs on this slate to belong in a winning lineup, taken
# from the slate itself rather than fixed: the Nth best projected player at
# that position, where N is roughly how many make a good lineup.
BOOM_RANK = {"QB": 3, "RB": 6, "WR": 9, "TE": 3}


# A player needs this much expected involvement to count toward the price
# curve. The point is to exclude people who are not really playing: a deep
# backup priced at 3000 who will not touch the ball scores zero, and letting
# those into the fit drags the curve at cheap prices down toward nothing, which
# then makes every cheap player who DOES play look like enormous value. That is
# the single thing that makes a naive value column useless.
# Per position, because "a real role" means completely different volumes at
# each. A starting quarterback throws thirty times and his backup throws none,
# so one shared threshold either lets every backup quarterback into the fit or
# throws out half the receivers. A single figure of two touches left the
# quarterback curve expecting 1.6 points at four thousand dollars, which made
# every cheap starter look like a miracle.
MIN_ROLE = {"QB": 15.0, "RB": 5.0, "WR": 3.0, "TE": 2.0}
MIN_ROLE_DEFAULT = 3.0
# How wide a window the rolling median uses, as a share of the position's
# players. Wide enough to be steady, narrow enough to follow the curve.
FIT_WINDOW = 0.30


def log(*a):
    print(*a, flush=True)


def price_curve(group):
    """Expected DK score at each salary for one position.

    WHY A CURVE AND NOT POINTS PER DOLLAR. Points per thousand is the usual
    value column and it is mechanically biased: salary does not buy points at
    a constant rate, so the cheapest players always look like the best value
    and the column mostly ranks by price. Comparing a player against what his
    OWN price typically returns removes that, and the number means something
    plain: zero is a player scoring like a typical starter at his price, and
    positive is beating his price tag.

    Fitted with a rolling median and then forced upward-only, because a steady
    middle beats a least squares line that one 40 point ceiling can tilt, and
    because expected score cannot genuinely fall as salary rises. With no
    usable sample the position gets no curve at all rather than a guessed one.
    """
    pts = sorted(((p["sal"], p["proj"]) for p in group), key=lambda x: x[0])
    n = len(pts)
    if n < 8:
        return None
    w = max(3, int(n * FIT_WINDOW))
    xs = [x for x, _ in pts]
    fitted = []
    for i in range(n):
        lo = max(0, i - w // 2)
        hi = min(n, lo + w)
        lo = max(0, hi - w)
        win = sorted(y for _, y in pts[lo:hi])
        fitted.append(win[len(win) // 2])
    # Monotone: paying more cannot be expected to return less.
    for i in range(1, n):
        if fitted[i] < fitted[i - 1]:
            fitted[i] = fitted[i - 1]
    return xs, fitted


def curve_value(curve, sal):
    """Expected score at this salary, interpolated along the fitted curve."""
    if not curve:
        return None
    xs, ys = curve
    if sal <= xs[0]:
        return ys[0]
    if sal >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if sal <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            y0, y1 = ys[i - 1], ys[i]
            if x1 == x0:
                return y1
            t = (sal - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return ys[-1]


def pick_slate(doc):
    """The main slate: the biggest classic one that has not started."""
    now = datetime.datetime.now(datetime.timezone.utc)
    classics = [s for s in doc["slates"] if s.get("kind") == "classic"]
    future = []
    for s in classics:
        try:
            st = datetime.datetime.fromisoformat(s["start"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if st > now:
            future.append((s["teams"], st, s))
    if future:
        future.sort(key=lambda x: (-x[0], x[1]))
        return future[0][2]
    if classics:
        return max(classics, key=lambda s: s.get("teams", 0))
    return None


def curve_at(curve, x):
    """P(score >= x), read off the stored threshold curve with straight line
    interpolation between the points it carries."""
    if not curve:
        return None
    pts = sorted((float(k), v) for k, v in curve.items())
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        # Beyond the last threshold, decay rather than clamp, so a player who
        # can reach 40 is not treated the same as one who cannot.
        last_x, last_p = pts[-1]
        prev_x, prev_p = pts[-2]
        if last_p <= 0 or prev_p <= 0:
            return last_p
        rate = (math.log(prev_p) - math.log(last_p)) / (last_x - prev_x)
        return max(last_p * math.exp(-rate * (x - last_x)), 0.0)
    for (x0, p0), (x1, p1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return p0
            t = (x - x0) / (x1 - x0)
            return p0 + t * (p1 - p0)
    return pts[-1][1]


def ownership(players, scoring):
    """Projected ownership for each contest type, position by position.

    Normalised so that the total at each position equals the number of roster
    slots it fills. That constraint is arithmetic: one quarterback per lineup
    means every quarterback on the slate shares 100% between them."""
    slots = dict(BASE_SLOTS)
    for pos, share in FLEX_SPLIT.items():
        slots[pos] = slots.get(pos, 0.0) + share

    by_pos = defaultdict(list)
    for p in players:
        if p.get("proj") is None or not p.get("sal"):
            continue
        by_pos[p["pos"]].append(p)

    for pos, group in by_pos.items():
        total = slots.get(pos, 1.0) * 100.0
        vals = [(p["proj"] / (p["sal"] / 1000.0)) for p in group]
        ceils = [p.get("ceil") or p["proj"] for p in group]
        sals = [p["sal"] for p in group]
        if not vals:
            continue
        # Standardised inside the position, since a value of 3.0 means
        # something different at quarterback than at tight end.
        def z(xs):
            m = sum(xs) / len(xs)
            sd = (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
            return [((x - m) / sd) if sd > 1e-9 else 0.0 for x in xs]

        zv, zc, zs = z(vals), z(ceils), z(sals)
        for key, cfg in CONTESTS.items():
            appeal = [W_VALUE * zv[i] + W_SALARY * zs[i]
                      + (W_CEILING + cfg["ceil"]) * zc[i]
                      for i in range(len(group))]
            t = max(cfg["temp"], 1e-6)
            mx = max(appeal)
            ex = [math.exp((a - mx) / t) for a in appeal]
            s = sum(ex) or 1.0
            for i, p in enumerate(group):
                own = total * ex[i] / s
                # Nobody is in every lineup, and the cap stops a softmax from
                # claiming so on a thin slate.
                p.setdefault("own", {})[key] = round(min(own, 75.0), 1)


def main():
    dk_path = os.path.join(DATA, "nfl_dk.json")
    pr_path = os.path.join(DATA, "nfl_projections.json")
    if not os.path.exists(dk_path):
        log("no nfl_dk.json; run fetch_nfl.py first")
        return 1
    if not os.path.exists(pr_path):
        log("no nfl_projections.json; run build_projections.py first")
        return 1
    with open(dk_path, encoding="utf-8") as f:
        dk = json.load(f)
    with open(pr_path, encoding="utf-8") as f:
        pr = json.load(f)

    slate = pick_slate(dk)
    if slate is None:
        log("no classic slate on offer")
        return 1
    log(f"slate: {slate['name']}  ({slate['teams']} teams, "
        f"{len(slate['players'])} players, draft group {slate['dg']})")

    proj = {nrm(p["player"]): p for p in pr["players"]}
    # DraftKings calls a defense by its nickname ("Rams") and the projections
    # call it by team ("LA DST"), so those two never match on name. Defenses
    # join on the team code instead, which is the only thing both agree on.
    proj_dst = {p["team"]: p for p in pr["players"] if p["pos"] == "DST"}
    scoring = "dk"

    players, matched, unmatched = [], 0, defaultdict(int)
    for d in slate["players"]:
        key = nrm(d["n"])
        pp = proj_dst.get(d["tm"]) if d["pos"] == "DST" else proj.get(key)
        row = {"player": d["n"], "pos": d["pos"], "team": d["tm"],
               "sal": d["sal"]}
        if pp:
            sc = pp.get(scoring) or {}
            st = pp.get("stats") or {}
            row.update({
                "opp": pp.get("opp"),
                # Expected involvement, used to decide who is really playing
                # and therefore belongs in the price curve.
                "touches": round((st.get("tgt") or 0) + (st.get("car") or 0)
                                 + (st.get("patt") or 0), 2),
                "proj": sc.get("mean"), "med": sc.get("med"),
                "floor": sc.get("p25"), "ceil": sc.get("ceil"),
                "super": sc.get("super"),
                "curve": sc.get("curve"),
                "thin": pp.get("thin"), "anchors": len(pp.get("anchors") or []),
            })
            for k in ("outAhead", "outBasis", "roleCtx", "roleCtxN",
                      "selfOut", "selfBasis", "selfInjury", "roleUnknown"):
                if k in pp:
                    row[k] = pp[k]
            matched += 1
        else:
            row["why"] = ("No projection. Either he has not played in weeks and "
                          "carries no betting lines, which is what a player on "
                          "injured reserve looks like, or he is hurt and the "
                          "market has pulled his lines, or he is not on a current "
                          "roster. DraftKings still lists him, so he is shown "
                          "rather than hidden.")
            unmatched[d["pos"]] += 1
        players.append(row)

    log(f"{matched} of {len(players)} DK players carry a projection")
    if unmatched:
        log("   without one: " + ", ".join(f"{v} {k}" for k, v in
                                           sorted(unmatched.items(),
                                                  key=lambda kv: -kv[1])))

    # Super ceiling, and how often a player reaches what his position needs on
    # THIS slate rather than some fixed number.
    by_pos = defaultdict(list)
    for p in players:
        if p.get("proj") is not None:
            by_pos[p["pos"]].append(p)
    thresholds = {}
    for pos, group in by_pos.items():
        n = BOOM_RANK.get(pos)
        if not n or len(group) < n:
            continue
        ranked = sorted(group, key=lambda p: -(p.get("ceil") or 0))
        thresholds[pos] = round(ranked[n - 1].get("ceil") or 0, 1)
    log("   score each position needs on this slate: "
        + ", ".join(f"{k} {v}" for k, v in sorted(thresholds.items())))

    for p in players:
        c = p.get("curve")
        if not c:
            continue
        t = thresholds.get(p["pos"])
        if t:
            p["boom"] = round(curve_at(c, t) * 100, 1)


    ownership(players, scoring)

    # VALUE, against the price curve rather than as points per dollar.
    curves, fitn = {}, {}
    for pos, group in by_pos.items():
        floor = MIN_ROLE.get(pos, MIN_ROLE_DEFAULT)
        real = [p for p in group if (p.get("touches") or 0) >= floor]
        c = price_curve(real)
        if c:
            curves[pos] = c
            fitn[pos] = len(real)
    log("\nprice curve, expected DK score at a salary, fitted per position")
    log("   (only players with a real role count, so cheap prices are not "
        "dragged down by people who will not play)")
    for pos in sorted(curves):
        xs, ys = curves[pos]
        log("   %-3s %3d with a real role (%.0f+ touches)   "
            "%5d -> %4.1f pts   %5d -> %4.1f pts"
            % (pos, fitn[pos], MIN_ROLE.get(pos, MIN_ROLE_DEFAULT),
               xs[0], ys[0], xs[-1], ys[-1]))
    for pos, group in by_pos.items():
        if pos not in curves:
            continue
        for p in group:
            exp = curve_value(curves[pos], p["sal"])
            if exp is None:
                continue
            p["expected"] = round(exp, 1)
            p["value"] = round(p["proj"] - exp, 1)
            p["ppk"] = round(p["proj"] / (p["sal"] / 1000.0), 2)

    for p in players:
        if p.get("proj") is None or not p.get("sal"):
            continue
        own = p.get("own") or {}
        # Leverage: how often he delivers what the slate needs, against how
        # much of the field is on him. Positive means the field is
        # under-rostering the outcome he actually produces.
        if p.get("boom") is not None and own.get("mme") is not None:
            p["gpp"] = round(p["boom"] - own["mme"], 1)

    players.sort(key=lambda p: -(p.get("proj") or -1))
    built = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "built": built,
        "slate": {"name": slate["name"], "dg": slate["dg"],
                  "start": slate["start"], "teams": slate["teams"],
                  "games": slate["teams"] // 2},
        "scoring": scoring,
        "count": len(players),
        "projected": matched,
        "thresholds": thresholds,
        "priceCurve": {pos: {"sal": xs, "exp": [round(y, 2) for y in ys]}
                       for pos, (xs, ys) in curves.items()},
        "contests": {k: v["label"] for k, v in CONTESTS.items()},
        "ownershipCalibrated": False,
        "players": players,
    }
    out = os.path.join(DATA, "nfl_slate_board.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    log(f"\nwrote nfl_slate_board.json ({os.path.getsize(out) // 1024} KB)")

    # Archived so that the ownership model stops being unfalsifiable the
    # moment real contest results exist to compare it against.
    os.makedirs(HIST, exist_ok=True)
    snap = {
        "built": built, "dg": slate["dg"], "slate": slate["name"],
        "ownership": {p["player"]: p["own"] for p in players if p.get("own")},
        # Salary and projection archived alongside, so that once actual
        # results exist the price curve can be refitted on what players really
        # scored at each price rather than on what this model expected them to.
        "priced": {p["player"]: [p["sal"], p.get("proj")]
                   for p in players if p.get("sal")},
    }
    sp = os.path.join(HIST, f"own_{built[:10]}_{slate['dg']}.json")
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(snap, f, separators=(",", ":"))
    log(f"archived projected ownership to {os.path.relpath(sp, ROOT)}")

    # Does the constraint hold. If quarterback ownership does not sum to 100
    # the normalisation is broken and every number on the page is wrong.
    log("\nownership sums, which are arithmetic rather than opinion:")
    for pos in ("QB", "RB", "WR", "TE"):
        want = (BASE_SLOTS.get(pos, 0) + FLEX_SPLIT.get(pos, 0)) * 100
        for key in CONTESTS:
            got = sum(p["own"][key] for p in players
                      if p.get("own") and p["pos"] == pos)
            flag = "" if abs(got - want) < max(2.0, want * 0.03) else "   <-- OFF"
            log(f"   {pos:<3} {key:<4} {got:7.1f}% against {want:6.1f}%{flag}")

    log("\ntop 12 by leverage, which is boom rate minus mass multi entry ownership:")
    log("%-24s %-4s %6s %6s %6s %6s %7s %7s %7s"
        % ("player", "pos", "$", "proj", "exp", "value", "boom%", "own%", "gpp"))
    rank = [p for p in players if p.get("gpp") is not None]
    for p in sorted(rank, key=lambda p: -p["gpp"])[:12]:
        log("%-24s %-4s %6d %6.1f %6.1f %+6.1f %7.1f %7.1f %+7.1f"
            % (p["player"][:24], p["pos"], p["sal"], p["proj"],
               p.get("expected") or 0, p.get("value") or 0,
               p["boom"], p["own"]["mme"], p["gpp"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
