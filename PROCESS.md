# How to build lineups with this project

What eight scored contests actually support, what they do not, and the order
to do things in. Every number here comes from a file in `data/`. Where the
evidence is thin it says so.

Scored so far: **six showdowns** (8, 9, 13, 15, 16, 19 November) and **three
main slates** (8, 15, 22 November). That is not a lot. Treat a finding backed by
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

### Showdown: six contests

| | 8 Nov | 9 Nov | 13 Nov | 15 Nov | 16 Nov | 19 Nov |
|---|---|---|---|---|---|---|
| Captain | Irving (RB) | Cook (RB) | Likely (TE) | Chase (WR) | Hampton (RB) | **Stroud (QB)** |
| Total ownership | 169.6% | 166.1% | 151.3% | 149.6% | 175.0% | **189.4%** |
| Duplicates | 32 | 13 | 1 | 8 | 11 | 11 |
| Team split | 3-3 | 5-1 | 4-2 | 4-2 | 4-2 | 5-1 |

1. **The quarterback usually goes in the FLEX, but not always: 5 of 6.** On
   19 November C.J. Stroud was captained and won. The mechanism still holds
   and it explains the exception. A captain multiplies salary as well as
   score, so it buys concentration rather than value, and you want
   concentration on the widest tail; a quarterback's 90th percentile is about
   1.6x his mean against 1.9x for a top receiver. Searching every legal
   lineup on that slate beforehand, a quarterback captain was likeliest to
   clear 140 and 160 points and a receiver captain likeliest to clear 180 and
   200.

   **I read that crossover wrong and it cost all three recommended lineups.**
   I assumed a 643,587-entry field meant the target was 180-plus, so I ruled
   out the quarterback. The game finished 26-3 and the winning lineup scored
   **99.49**. The target score is set by the GAME, not by the size of the
   field:

   | Showdown | Real game total | Winning lineup |
   |---|---|---|
   | 9 Nov | 29 | 90.21 |
   | 19 Nov | 29 | 99.49 |
   | 13 Nov | 45 | 136.71 |
   | 8 Nov | 51 | 118.81 |

   So: take the target off the simulation's own distribution of winning
   scores, then pick the captain for that target. Below about 170 you want the
   quarterback's floor; above it you want a receiver's tail.
2. **Leverage goes to whoever captained the top scorer. 6 for 6.**
3. **Winners are chalk-heavy and duplicated.** 149.6% to **189.4%** of summed
   ownership, 1 to 32 duplicates. Not one was a unique lineup.
4. **The team split is not a rule.** 4-2 three times, 5-1 twice, 3-3 once.
5. **In a blowout the winning side's defence is close to mandatory.** Houston
   Defense was 28.1% owned and appeared in **100% of the top 1%**.

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

- **No kicker model at all, and it has now cost a slate.** On 19 November
  Ka'imi Fairbairn was 35.1% owned and appeared in **100% of the top 1%**,
  and the other kicker, Spencer Shrader, was in 80.2% of it. The project
  cannot see either. The 9 November winner carried two kickers. Their absence
  from any build here is ignorance, not a fade, and it is the single most
  valuable gap left to close.
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
does not touch the field model, together with summed projected scoring by
game, which is the one quantity measured to predict a game's top-1% share
(+0.41, see step 3). On 22 November DAL/TEN had the highest summed projection on
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

### Step 3. Do not try to out-pick the field one player at a time

An earlier version of this step said "fade a player when the simulation
disagrees with his price". That is not executable and the data does not
support it. Tested across all 270 labelled players, against how much more
represented a player was in the top 1% than in the field overall:

| Pre-lock quantity | Correlation |
|---|---|
| points per $1,000, which is what the field prices on | +0.08 |
| **ceiling** per $1,000 | +0.07 |
| ceiling divided by mean, the shape of the upside | −0.01 |
| the board's boom rate | +0.13 |
| salary | +0.05 |

Nothing. Splitting each ownership band by ceiling per dollar separates the
halves by about a point, and in two of three bands it points the wrong way.
There is no measurable signal here, and the reason is partly structural: the
ownership model is itself built from projection over salary, so comparing the
simulation to the price is close to comparing the model to itself.

**The same question at the GAME level does have an answer.** Summed projected
scoring for a game correlates **+0.41** with that game's share of the top 1%,
five times the best player-level number:

| | Captured share of all top-1% | A random pick would get |
|---|---|---|
| Top game by projection | 34.5% | 9% |
| Top 2 games | 37.9% | 18% |
| **Top 3 games** | **47.7%** | 27% |
| Top 4 games | 53.6% | 36% |

And the single best game of the slate was inside the top three by projection
**all three times**: GB/NE ranked 3rd, DAL/SF 1st, DAL/TEN 1st.

Note the top-1 row is unreliable: on 8 November the highest-projected game
returned 7% while the third-ranked one returned 150%. Three is the robust
number, one is a coin flip.

So the practical rule is the opposite of player picking. **Choose two or three
games from the top of the projection list, then take whoever that game's
correlation hands you, chalk or not.** Prescott at 21.7% and Lamb at 33.1%
were both chalk on 22 November and both correct. The decision that carries
information is which game; the players inside it are mostly determined once
you have chosen.

### Step 3b. Do not override the tool's script-conditional output with a pattern

This is the mistake that lost 19 November, and it is worth its own step.

The showdown page splits its results by game script. For IND at HOU its
blowout bucket, 33.2% of simulated games, had **"CPT QB, 5-1 HOU"** as the
top shape at 22%, with Stroud as the captain in 41% of those games. The game
was a blowout. The winner was 5-1 Houston with Stroud captained. The tool
named the winning construction before lock.

I discarded it because five previous contests had never seen a quarterback
captained, and built three lineups that scored 76.06, 72.86 and 65.46 against
the winner's 99.49.

A cross-contest pattern is a prior over all game scripts. The script-bucket
output is conditional on the one in front of you. When they disagree, the
conditional one is the one that knows something.

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

Check the data first, every time. Pick two or three games off the top of the
projection list, because that is the only decision with measurable signal in
it: +0.41 at game level against +0.13 for the best player-level number anyone
here has found. Go three deep with real correlation. Take whoever those games
hand you, chalk included. Be different in one place, not six. Add up the
ownership before you lock.
