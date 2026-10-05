#!/usr/bin/env python3
"""
seo_nfl.py — write the weekly leaders block into nfl.html as plain HTML.

WHY THIS EXISTS
The stats table on nfl.html is drawn by JavaScript from JSON. Search engines do
execute JavaScript, but on a delay and not dependably, and before this page was
opened up a crawler saw literally zero words on it. This writes real HTML —
actual player names and numbers — straight into the file, so there is something
to index whether or not the renderer ever runs.

It also makes the page change every week. Fresh, genuinely useful content on a
regular cadence is the strongest free ranking signal a small site has.

The block is visible to readers exactly as it is to crawlers. Serving a search
engine something a visitor cannot see is cloaking and gets sites penalised, so
the output is ordinary markup in the normal flow of the page.

Run after fetch_nfl.py; rewrites everything between the SEO:LEADERS markers.
"""
import collections
import datetime
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PAGE = os.path.join(ROOT, "nfl.html")
START = "<!-- SEO:LEADERS:START -->"
END = "<!-- SEO:LEADERS:END -->"

# How many weeks of a trailing window the leader lists describe. Short enough to
# be current, long enough that one freak game cannot top the list.
WINDOW = 3
TOP = 10


def esc(s):
    return html.escape(str(s), quote=True)


def load():
    with open(os.path.join(DATA, "nfl_index.json"), encoding="utf-8") as f:
        idx = json.load(f)
    cur = idx.get("current")
    entry = next((s for s in idx["seasons"] if int(s["season"]) == int(cur)), None)
    if entry is None:
        entry = idx["seasons"][0]
    with open(os.path.join(DATA, entry["file"]), encoding="utf-8") as f:
        return json.load(f)


def aggregate(raw, lo, hi):
    """Same arithmetic as the page: sum the counts, then divide once."""
    meta = {p["id"]: p for p in raw["players"]}
    by = collections.defaultdict(list)
    for r in raw["rows"]:
        if lo <= r["w"] <= hi:
            by[r["i"]].append(r)

    out = []
    for pid, rs in by.items():
        m = meta.get(pid)
        if not m:
            continue
        S = lambda k: sum(r.get(k, 0) for r in rs)  # noqa: E731
        T = lambda k: sum(raw["teams"].get(f"{r['t']}|{r['w']}", {}).get(k, 0) for r in rs)  # noqa: E731
        g = len(rs)
        tg, ca, fp, rec = S("tg"), S("ca"), S("fp"), S("rec")
        a = x = 0.0
        xg = 0
        for r in rs:
            if r.get("xfp") is None:
                continue
            a += r.get("fp", 0) - 0.5 * r.get("rec", 0)
            x += r["xfp"] - 0.5 * r.get("xrec", 0)
            xg += 1
        out.append({
            "name": m["n"], "pos": m["p"], "tm": rs[-1]["t"], "g": g,
            "tgtsh": tg / T("tg") * 100 if T("tg") else None,
            "snap": S("sn") / T("sn") * 100 if T("sn") else None,
            "carsh": ca / T("ca") * 100 if T("ca") else None,
            "hppr": (fp - 0.5 * rec) / g,
            "fpoe": (a - x) / xg if xg else None,
            "rz": S("rz") / g,
            "tg": tg,
        })
    return out


def table(title, rows, cols, note=None):
    head = "".join(f'<th class="num">{esc(c[1])}</th>' if c[2] else f"<th>{esc(c[1])}</th>"
                   for c in cols)
    body = []
    for i, r in enumerate(rows):
        # Rank and player name are emitted here rather than coming from `cols`,
        # because every one of these tables wants them and in the same place.
        # The name is the whole point of the block: it is what someone actually
        # searches for.
        tds = [f"<td>{i + 1}</td>", f'<td><strong>{esc(r.get("name", ""))}</strong></td>']
        for key, _, isnum, fmt in cols:
            v = r.get(key)
            txt = "—" if v is None else (fmt(v) if fmt else esc(v))
            tds.append(f'<td class="num">{txt}</td>' if isnum else f"<td>{txt}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    n = f'\n          <p class="hint">{esc(note)}</p>' if note else ""
    return (f"        <div>\n          <h3>{esc(title)}</h3>{n}\n"
            f'          <table>\n            <thead><tr><th>#</th><th>Player</th>{head}</tr></thead>\n'
            "            <tbody>\n"
            + "\n".join(f"              {row}" for row in body)
            + "\n            </tbody>\n          </table>\n        </div>")


def pct(v):
    return f"{v:.1f}%"


def one(v):
    return f"{v:.1f}"


def signed(v):
    return f"{v:+.1f}"


def build(raw):
    weeks = raw["weeks"]
    hi = weeks[-1]
    lo = max(weeks[0], hi - WINDOW + 1)
    rows = aggregate(raw, lo, hi)
    season = raw["season"]
    span = f"week {hi}" if lo == hi else f"weeks {lo} to {hi}"

    def top(pos, key, n=TOP, reverse=True, minimum=None):
        pool = [r for r in rows if r["pos"] in pos and r.get(key) is not None]
        if minimum:
            pool = [r for r in pool if r.get(minimum[0], 0) >= minimum[1]]
        pool.sort(key=lambda r: r[key], reverse=reverse)
        return pool[:n]

    NAME = ("name", "Player", False, None)
    TM = ("tm", "Tm", False, None)

    blocks = [
        table(f"Target share leaders, {span}",
              top(("WR", "TE", "RB"), "tgtsh"),
              [TM, ("pos", "Pos", False, None), ("tgtsh", "Tgt%", True, pct),
               ("tg", "Tgt", True, lambda v: f"{v:.0f}")],
              "Share of his team's targets. Around 25% marks a true alpha."),
        table(f"Snap share leaders, {span}",
              top(("WR", "TE", "RB"), "snap"),
              [TM, ("pos", "Pos", False, None), ("snap", "Snap%", True, pct)],
              "Share of his offense's snaps. Separates every-down roles from rotations."),
        table(f"Running back carry share, {span}",
              top(("RB",), "carsh"),
              [TM, ("carsh", "Car%", True, pct), ("rz", "RZ/g", True, one)],
              "Share of team carries, with red zone carries per game."),
        table(f"Best buy-low candidates by FPOE, {span}",
              top(("WR", "TE", "RB", "QB"), "fpoe", reverse=False, minimum=("g", 2)),
              [TM, ("pos", "Pos", False, None), ("fpoe", "FPOE", True, signed),
               ("hppr", "Half", True, one)],
              "Most negative fantasy points over expected: the usage is there, "
              "the scoring has not followed."),
        table(f"Most likely to regress by FPOE, {span}",
              top(("WR", "TE", "RB", "QB"), "fpoe", minimum=("g", 2)),
              [TM, ("pos", "Pos", False, None), ("fpoe", "FPOE", True, signed),
               ("hppr", "Half", True, one)],
              "Scoring well ahead of opportunity, usually on touchdowns the volume "
              "will not keep producing."),
        table(f"Half PPR points per game, {span}",
              top(("WR", "TE", "RB", "QB"), "hppr"),
              [TM, ("pos", "Pos", False, None), ("hppr", "Half", True, one)],
              "Actual half PPR scoring, for reference against the usage above."),
    ]

    built = datetime.datetime.utcnow().strftime("%B %-d, %Y")
    lead_tgt = top(("WR", "TE", "RB"), "tgtsh", 1)
    lead_fpoe = top(("WR", "TE", "RB", "QB"), "fpoe", 1, reverse=False, minimum=("g", 2))
    intro = []
    if lead_tgt:
        t = lead_tgt[0]
        intro.append(f"Over {span} of the {season} NFL season, "
                     f"{esc(t['name'])} ({esc(t['tm'])}) leads all pass catchers with a "
                     f"{t['tgtsh']:.1f}% target share.")
    if lead_fpoe:
        b = lead_fpoe[0]
        intro.append(f"{esc(b['name'])} ({esc(b['tm'])}) is the biggest buy-low signal at "
                     f"{b['fpoe']:+.1f} fantasy points over expected per game, meaning his "
                     f"role is worth noticeably more than he has scored.")

    return (
        f"{START}\n"
        '      <section class="seo-leaders">\n'
        f"        <h2>NFL usage leaders, {span} of the {season} season</h2>\n"
        f'        <p class="seo-updated">Updated {built}. '
        f"All figures cover {span} and are recomputed from the counting stats, not "
        "averaged across weeks.</p>\n"
        f"        <p>{' '.join(intro)}</p>\n"
        '        <div class="seo-leadgrid">\n'
        + "\n".join(blocks)
        + "\n        </div>\n      </section>\n      "
        + END
    )


def main():
    try:
        raw = load()
    except Exception as e:  # noqa: BLE001
        print(f"no NFL data to render: {e}", flush=True)
        return 0
    if not raw.get("rows"):
        print("NFL data has no rows; leaving nfl.html alone", flush=True)
        return 0

    with open(PAGE, encoding="utf-8") as f:
        page = f.read()
    if START not in page or END not in page:
        print("markers missing from nfl.html — refusing to guess where the block goes")
        return 1

    block = build(raw)
    new = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, page, flags=re.S)
    if new == page:
        print("leaders block unchanged")
        return 0
    with open(PAGE, "w", encoding="utf-8") as f:
        f.write(new)
    print(f"wrote leaders block ({len(block)} chars) into nfl.html", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
