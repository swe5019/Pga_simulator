# How to build lineups with this project

What eight scored contests actually support, what they do not, and the order
to do things in. Every number here comes from a file in `data/`. Where the
evidence is thin it says so.

Scored so far: **five showdowns** (8, 9, 13, 15, 16 November) and **three main
slates** (8, 15, 22 November). That is not a lot. Treat a finding backed by
five contests as a lean, not a law.

---

## Part 1 — What is established

### The thing that decides a tournament is WHICH GAME, not which shape

This is the strongest result in the data and the one that keeps repeating.

On 22 November the same construction went both ways on the same slate. A
defence paired with its own running back:

| Team | Field | Top 1% | Return |
|---|---|---|---|
| Denver, with Jonah Coleman | 3.4% | 12.7% | **3.7x** |
| Kansas City, with Emmett Johnson | 7.8% | 2.2% | **0.3x** |
| Los Angeles, with Omarion Hampton | 1.6% | 0.5% | 0.3x |

Identical shape. The Kansas City version was the single most-built stack on
the whole slate and it lost. Nothing about "DST plus your own back" was right
or wrong; Denver's game went 38-24 and Kansas City's went 34-7.

So: pick the game first. The shape is a detail you settle afterwards.

### Depth pays, and three is the threshold

Matched field share against top-1% share on the *same* construction:

| Slate | 2-man | 3-man | 4-man |
|---|---|---|---|
| 8 Nov game stacks | 1.8x | 11.0x | 34.0x |
| 15 Nov game stacks | 3.2x | 35.0x | 16.7x |
| 22 Nov team stacks | 1.5x | 2.6x | 19.5x |

*(medians over the rows FantasyLabs listed)*

**Read these ratios as directional, not literal.** The panel lists stacks
sorted by top-1% share, so everything in it is selected on having done well,
and deeper stacks have mechanically smaller field shares. Both inflate the
ratio, and more so at depth.

The cleanest single piece of evidence is the Dallas ladder from 22 November,
because it contains the popular *and* unpopular versions of the same stack:

| Stack | Field | Top 1% | Return |
|---|---|---|---|
| Prescott + Lamb | 5.4% | 9.6% | 1.8x |
| Prescott + Pickens | 3.5% | 6.3% | 1.8x |
| Lamb + Pickens, no QB | 1.3% | 2.0% | 1.5x |
| Prescott + Spann-Ford + Lamb | 0.7% | 2.6% | 3.7x |
| **Prescott + Lamb + Pickens** | **3.1%** | **29.0%** | **9.4x** |
| Prescott + Spann-Ford + Lamb + Pickens | 0.2% | 3.9% | 19.5x |

The third player is where the payoff is, **and it has to be the right third
player**. Adding Pickens takes the stack from 1.8x to 9.4x; adding Spann-Ford
instead takes it to 3.7x.

And from the winners themselves, which is not subject to any selection
problem: both main-slate winners used a 3+ deep game stack. 8 November was
GB/NE x4, 22 November was DAL/TEN x3.

### Popular is not the same as wrong

The instinct to fade chalk is the single most expensive habit the data argues
against.

- DAL/TEN on 22 November was the **most owned game on the slate** at 191.5% of
  summed ownership, and took **407.0%** of the top 1%. Being there was correct
  *and* crowded.
- Ja'Marr Chase on 15 November was the most-owned showdown captain at 20.1%
  and returned 3.39x, the best on the board.
- Across five showdowns, the most-owned captain has been the top scorer once.
  The other four times he returned between 0.00x and 0.78x.

So the rule is not "avoid the crowd". It is: **the crowd costs you nothing
when it is right, and everything when it is wrong.** You are not paid for
being different, you are paid for being correct in a place few others were.

### Showdown: five contests, five identical patterns

| | 8 Nov | 9 Nov | 13 Nov | 15 Nov | 16 Nov |
|---|---|---|---|---|---|
| Captain | Irving (RB) | Cook (RB) | Likely (TE) | Chase (WR) | Hampton (RB) |
| Total ownership | 169.6% | 166.1% | 151.3% | 149.6% | 175.0% |
| Duplicates | 32 | 13 | 1 | 8 | 11 |
| Team split | 3-3 | 5-1 | 4-2 | 4-2 | 4-2 |

1. **The quarterback goes in the FLEX and is never the captain. 5 for 5.** The
   captain has never been a quarterback either. The mechanical reason is
   better than the record: a captain multiplies salary as well as score, so it
   buys concentration rather than value, and you want concentration on the
   widest tail. A quarterback's 90th percentile is typically about 1.6x his
   mean against 1.9x for a top receiver. His worth is his floor, and a floor
   wins nothing in a 600,000-entry field. Searching every legal lineup on
   19 November, a quarterback captain was likeliest to clear 140 and 160
   points and a receiver captain likeliest to clear 180 and 200 — the
   crossover sits near 170, and tournaments are won above it.
2. **Leverage goes to whoever captained the top scorer. 5 for 5**, between
   3.4x and 11.2x.
3. **Winners are chalk-heavy and duplicated.** 149.6% to 175.0% of summed
   ownership, 1 to 32 duplicates. Not one was a unique lineup.
4. **The team split is not a rule.** 4-2 three times, 5-1 once, 3-3 once.

### Main-slate winners are NOT reliably chalky, unlike showdown winners

Do not carry finding 3 across formats. The two main-slate winners on file:

| | Total ownership | Points | Game stack |
|---|---|---|---|
| 8 Nov | **90.6%** | 221.38 | GB/NE x4 |
| 22 Nov | **161.4%** | 219.30 | DAL/TEN x3 |

Across nine roster slots, 90.6% is an average of 10% per player: genuinely
contrarian. 161.4% is about 18%: moderately chalky. With two observations
there is no band to aim at, and the showdown band does not transfer.

### The two ownership markets are not the same market

Captain ownership sums to 100% across a showdown slate; flex sums to 500%.
Of the 45 players appearing in both on the same slate, the ratio between their
two shares runs from **1.4 to 32**. As a power law on salary the captain
market has an exponent near **3.3** and the flex market near **1.46**. One is
steep and winner-take-most; the other is nearly flat. The field captains
expensive skill players and flexes everybody else — a flexed quarterback
averages 50.8% against 16 to 23% for every other position at comparable money.

### How much to trust each model

| Model | Mean error | Against baseline | Notes |
|---|---|---|---|
| Main-slate ownership | **3.25 pts** | 5.48 | 270 players, 3 contests, +0.75 correlation |
| Showdown captain ownership | **3.4 pts** | 5.7 | 45 captains, 5 contests |
| Showdown flex ownership | **7.5 pts** | 12.2 | 98 players, about a third of a typical value |

Read all three in bands, never as figures. None will tell you 18% from 24%.

**Never divide a win rate by a modelled ownership to make a leverage number.**
Tested: on the two showdowns where it could be checked, that division ranked
the actual winning captain 12th of 21 and 20th of 23, against 1st and 10th for
the raw win rate alone. The models are monotone in salary, so the ratio
collapses toward "win rate per dollar" and promotes cheap players who do not
win.

---

## Part 2 — What is NOT established

Be honest about these; several have already cost real money.

- **No kicker model at all.** The field rostered kickers at 26% and 33% in two
  recent showdowns and the 9 November winner carried two of them. Their
  absence from any build here is ignorance, not a fade.
- **No lineup-level field model.** Summing the slot ownerships gives a
  lineup's field share, which is the unit contests report. It does **not** give
  the chance anybody built that exact lineup, because entries are stacked, not
  drawn independently. Duplicate counts are not predictable yet.
- **Projections can be badly wrong on thin history.** Joe Milton III projected
  28.5 points off two effective games and scored 6.34. That one projection
  also inverted the whole field model for 22 November.
- **The game-level field model inverted once.** It called PHI/PIT the most
  crowded game; it finished least owned of ten, 8.4% of ownership and 1.0% of
  the top 1%. Caused by Milton. Treat the leverage and field columns on the
  scenarios page as the least reliable thing in the project.
- **Scheduled refreshes are unreliable.** On 22 November none of the three
  Sunday pre-lock cron runs fired, leaving the data 15.7 hours stale with
  under an hour to lock.

---

## Part 3 — The process

### Step 0. Check the data before you look at a single number

This step has caught more money than any model in the project.

1. **How old are the props?** `data/nfl_props.json` carries `built`. If it is
   more than a few hours old on a game day, trigger `fetch-props.yml` by hand
   and wait. Do not trust the cron.
2. **Who has no markets?** Any non-defence player priced $4,000 or more with
   zero prop anchors. Across three contests, **23 of 23 such players went
   unrostered** against 93% of the 43 who had markets. They are almost always
   out, and their projection is a role prior with nothing behind it. This has
   bitten three times: Justin Jefferson, Alec Pierce, Wan'Dale Robinson.
3. **What got pulled?** Run `tools/detect_pulled_markets.py`. A book removing
   a player's volume markets usually means news is coming. Their modelled
   ownership is biased low, so they look contrarian when they are the
   opposite.
4. **Anything with a huge projection and thin history?** Cross-check against
   the player's own market lines. Milton's projection sat 15.1 points above
   what his anchors implied, the largest gap on the slate.

### Step 1. Pick the game

Use the **optimum column** on the scenarios page, which is pure simulation and
does not touch the field model. Cross-check it against summed projected
scoring by game. On 22 November DAL/TEN had the highest summed projection on
the slate (253.9) and the top two entries in the optimum column, and it took
407% of the top 1%.

Do **not** pick the game by the leverage or field columns yet. That is the
part that inverted.

### Step 2. Go three deep in it, minimum

Two is not enough: 2-man stacks return 1.5x to 3.2x and that is before the
selection bias is taken out. Three is the threshold in every dataset, and both
main-slate winners went three or four.

Get the correlation right, not just the count: quarterback plus his own pass
catchers plus a bring-back from the other side. Prescott + Lamb + Pickens
returned 9.4x; Prescott + Spann-Ford + Lamb returned 3.7x. Same depth.

### Step 3. Take the chalk where the chalk is correct

Do not fade a player because he is popular. Fade him when the simulation
disagrees with his price. The question is never "how owned is he" but "is the
field right about him".

### Step 4. Spend your differentiation on ONE decision

Showdown makes this explicit: all five winners were chalk in five slots and
different in exactly one, the captain. On a main slate the equivalent is the
bring-back or the last flex. The 22 November winner ran Prescott and Lamb,
both chalk, with Chimere Dike at 3.3% as the third piece.

Being strange in six places does not multiply your edge, it just lowers your
score.

### Step 5. Price the whole lineup before you lock

Add up every slot's modelled ownership.

- **Showdown**: the five winners landed between 149.6% and 175.0%. Outside
  that band, ask why. On 19 November a build whose captain was owned 0.5%
  priced out at 198.3% once the flex was counted, because its five other slots
  were the most crowded in the game. It looked contrarian and was the opposite.
- **Main slate**: two winners at 90.6% and 161.4%. No band yet. Use the number
  to catch an accident, not to hit a target.

### Step 6. Capture the result

Every contest you transcribe makes the next week's models measurably better.
Three slates took the ownership model from 3.97 to 3.25 mean error. The
highest-value things to capture, in order:

1. Main-slate field exposure by position, with the top 20/10/1% columns.
2. The winning lineup with per-player ownership.
3. Team stacks and game stacks panels.
4. For showdowns, the captain market all the way down the tail — the low-owned
   rows are exactly the ones every capture so far has been missing, and the
   captain model's weakest point is how concentrated a market gets.

---

## The short version

Pick the game from the simulation. Go three deep with real correlation. Take
the chalk when the chalk is right. Be different in one place, not six. Add up
the ownership before you lock. Check the data first, every time.
