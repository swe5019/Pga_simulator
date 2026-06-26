# ⛳ SlateSims — PGA DFS Simulator for DraftKings

A play-by-play golf simulator and lineup builder for **DraftKings PGA** contests.
Think SaberSim, but focused on one sport, and built to be faster and easier to use.

It runs **entirely in your browser** — no install, no server, no account. Your data
never leaves your machine. Open `index.html` and it works immediately with a sample slate.

## Why it's different

Most tools project a flat average for each golfer and bolt on a guessed standard
deviation. Golf doesn't behave like that. SlateSims simulates **every golfer's full
72-hole tournament, hole by hole, thousands of times**. That naturally reproduces the
things that actually decide DFS golf:

- birdie streaks and bogey-free rounds (correlated *within* a round)
- eagles on par 5s and the occasional hole-in-one
- the missed cut (no weekend rounds, no points)
- true boom/bust shape — skewed with a fat ceiling, not a tidy bell curve

The DraftKings **Classic** scoring rules (birdies, eagles, streak/bogey-free/4-rounds-under-70
bonuses, hole-in-one) are applied to every simulated round, so the projections, floors,
and ceilings are the real fantasy-point distributions — not a guess.

## The workflow (4 tabs)

1. **Players / Simulate** — Edit salary & skill inline, lock 🔒 or ban 🚫 golfers, and
   run the Monte Carlo. You get projection, floor (10th pct), ceiling (90th pct),
   make-cut %, projected ownership, and value for every golfer.
2. **Build** — Generate a diverse pool of lineups. Each lineup is optimized against a
   *single simulated tournament*, so the pool reflects distinct, realistic ways the event
   can play out — not 20 copies of the same chalk. Controls for lineup count, max
   exposure, min salary, and whether to optimize for cash (mean), GPP (ceiling), or the
   Milly Maker (top-1% spike).
3. **Review** — Your edge lives in the **leverage** column: your exposure minus the
   field's projected ownership. Plus the full lineup pool with projections and salary.
4. **Export** — Download a **DraftKings-ready upload CSV**, or a detailed pool with
   projections for your own records.

## Using your own slate

Click **Import DK Salaries CSV** on the Players tab and select the `DKSalaries.csv`
DraftKings gives you on the contest page. SlateSims reads the `Name` and `Salary` columns
(and `AvgPointsPerGame` if present) to seed each golfer. Tune any **Skill** value inline
— skill is *strokes gained per round vs. the field* (higher = better) — then re-run the
sim. This is where your own research becomes your edge.

## DraftKings rules modeled

- Roster: **6 golfers**, salary cap **$50,000**
- Classic scoring: birdie +3, eagle +8, albatross +13, par +0.5, bogey −0.5,
  double+ −1; bonuses: 3-birdie streak +3, bogey-free round +3, all 4 rounds under 70 +5,
  hole-in-one +5

## Project layout

```
index.html              # UI shell (4 tabs)
assets/css/styles.css   # styling
assets/js/scoring.js    # DraftKings scoring rules (single source of truth)
assets/js/sim.js        # hole-by-hole Monte Carlo engine
assets/js/optimizer.js  # simulation-driven lineup pool builder
assets/js/data.js       # sample slate + projected-ownership model
assets/js/app.js        # UI wiring, CSV import/export, state
```

## Run it

Just open `index.html` in a browser. To serve locally:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000
```

Performance: a 40-golfer slate at 5,000 sims runs in ~1 second; a 20-lineup build in
~20 ms. Bump to 10k–25k sims for sharper tails before a big GPP.

## Roadmap ideas

- Course-fit weighting (par-5 scoring, driving vs. putting course profiles)
- Group/stacking rules and "if-this-then-that" lineup constraints
- Live ownership import and late-swap
- Saved projection sets and shareable slates
- Optional cloud backend for shared projections and accounts
