# SlateSims — Go-to-Market & Pricing Strategy

> Working strategy doc. Numbers on competitors are from public pricing pages (June 2026);
> verify before publishing. This is a starting framework, not a final plan.

---

## 1. The thesis

**Whoever has the most accurate ownership projections wins.** In DFS golf, edge comes from
*leverage* — being over/under the field on the right players. Leverage is only as good as the
ownership number it's measured against. SlateSims' wedge is a **purpose-built, automated,
continuously-validated ownership model (LightGBM, ~2.4% MAE LOTO)** that plugs directly into a
full sim/optimizer/contest-ROI stack. We compete on **accuracy + automation + price**, not on
being yet another optimizer.

---

## 2. Competitive landscape (public pricing, verify)

> **Important — apples vs. oranges on price (read this first).** SaberSim and
> Stokastic's headline prices below are **multi-sport, all-access** subscriptions
> (NFL/NBA/MLB/PGA in one bill). They are **not** golf-only prices. SlateSims is
> launching **PGA-only**, so the honest like-for-like comparison is **Data Golf
> (~$30/mo, golf-only)** — that's the real anchor for our price band, not the
> $97–$400 multi-sport bundles. We can still *position against* the incumbents
> ("you're paying $200 for a bundle; get sharper golf ownership for less"), but
> we should not pretend $59 is "60% off SaberSim" when SaberSim's $97 also buys
> five other sports. A PGA-only buyer compares us to Data Golf and to the
> golf-only slice of those bundles (most don't sell one).

| Product | What it is | Monthly price | Notes |
|---|---|---|---|
| **SaberSim** | Sims + optimizer + contest sims, multi-sport | **$97 / $197 / $297** (Starter/Standard/Ultimate) | Most polished optimizer; Ultimate adds contest sims. Priciest *optimizer*. |
| **Stokastic** (ex-Awesemo) | Projections + ownership + sims, multi-sport | **$199.95 / $399.95** (Core/MAX All-Access) | Strong brand + content; runs frequent promo codes (15–50% off around events). |
| **Daily Fantasy Fuel** | Projections + ownership + optimizer | mid-tier sub | **Free 7-day trial** — proves trials are table stakes. |
| **Data Golf** | Predictive golf model + DFS projections | ~$30/mo (golf-only, model-first) | Closest to "best model" positioning; respected stats brand. |
| **RotoWire / Fantasy Alarm / RotoGrinders** | Projections, ownership, optimizer bundled in broader sub | $10–$40/mo | Generalist; ownership is one feature among many. |

**Takeaways:**
- The "sims + optimizer" tier is **expensive ($97–$400/mo)** and multi-sport-bundled.
- **Golf-only, model-first** tools (Data Golf) sit much cheaper (~$30) — that's the price band a
  focused golf product lives in.
- **Free trials are standard.** Promo discounting around majors is standard.
- Nobody is selling on **"best ownership MAE, fully automated, bring-your-own-edge."** That's open.

---

## 3. Positioning

**"The sharpest ownership projections in DFS golf — and the tools to leverage them."**

Differentiators (in priority order):
1. **Accuracy-first ownership** — published, back-tested MAE; we show our work (LOTO MAE per slate).
   Competitors don't publish accuracy. Make it our headline and our proof.
2. **Automation** — DK salaries/IDs/status/payouts pulled automatically; model retrains itself; no
   weekly Colab/CSV grind.
3. **Full stack in one** — projections → sim → optimizer (Sim Score) → contest ROI (exact DK
   payouts) → entries-file upload. SaberSim-parity features at a fraction of the price.
4. **Bring-your-own-edge (pro tier)** — power users can feed their own SG/odds/projections; the
   model and sims run on *their* numbers. No competitor offers this.
5. **Price built for the actual bankroll** — priced relative to a $1–$10/week DK player, not a
   $200/mo multi-sport grinder. A real edge shouldn't cost more than the entries it's used on.

---

## 4. Target segments

- **Primary: small-stakes DK players ($1–$10/week)** — the largest pool of golf-DFS entrants by
  far; currently priced out of every "sims + optimizer" tool on the market (all $25+/mo minimum).
  Pitch: a real edge for less than the cost of one extra lineup.
- **Secondary: mid-stakes players scaling up** — graduate from the entry tier as their bankroll
  grows; want ownership + optimizer without a $200–$400 multi-sport bundle.
- **Tertiary: serious grinders** — multi-entry, currently pay SaberSim/Stokastic. Pitch: same edge,
  better ownership, lower price.
- **Quaternary (moat): sharps/syndicates** — want to run *their own* models with automation. Pitch:
  the only platform that runs your edge end-to-end. Highest willingness-to-pay, lowest volume.

---

## 5. Pricing strategy

**Anchor to the small-stakes bankroll, not the incumbent's price list.** Someone playing
$1–$10/week on DraftKings will not pay $25–$97/mo for a tool — that's 3–10x their weekly action.
The tiers below price relative to *their* spend, with a true single-event micro-pass as the
funnel-opener, and let players graduate to richer tiers as their bankroll grows.

| Tier | Target | Launch price | Includes |
|---|---|---|---|
| **Free trial** | Acquisition | **14 days, full access, no card required** | Everything in Plus for one event cycle. |
| **Single Slate** | Impulse buy / first-timers | **$2.99 / event** | One tournament — ownership + projections + optimizer. No subscription. |
| **Starter** | Small-stakes ($1–$10/wk) | **$7.99/mo** | Ownership projections + win/top-5/top-10 equity, sim projections, basic optimizer, DK upload. |
| **Plus** | Players scaling up | **$19.99/mo** | Everything in Starter: contest ROI (exact payouts), exposure tools, entries-file automation, course-fit, larger lineup builds. |
| **Edge / BYO-model** | Sharps | **$39–$49/mo** | Bring-your-own SG/odds/projections, model auto-retrain, API/export, priority. |
| **Annual** | Retention | **2 months free (~17% off)** | Smooths seasonal churn. |

**Rationale (small-stakes-first framing):**
- **Single Slate at $2.99** is the real entry point — cheaper than a single rebuy, no commitment,
  no card-on-file anxiety. It's the natural next step after the free trial for someone who isn't
  ready to subscribe, and it converts casual/one-off majors traffic that a weekly pass priced at
  $9.99 would have priced out.
- **Starter at $7.99/mo** is the headline tier: roughly the cost of one extra DK entry per month,
  positioned explicitly as "less than what you'd spend chasing the rake without an edge."
- **Plus at $19.99/mo** is still well under Data Golf-plus-an-optimizer money, and is where players
  land once they're multi-entry or want contest ROI.
- **Edge** stays a high-margin tail tier for sharps/syndicates — it protects margin without being
  the product's main pitch anymore.
- **Messaging shift:** lead with "what does your DK budget actually support?" instead of "60%
  cheaper than SaberSim." The small-stakes player doesn't benchmark against SaberSim at all.
- **Founding-member lifetime/locked-rate** offer for the first 50–100 Starter users → early cash,
  loyalty, and word-of-mouth advocates.
- **Event promos** (15–25% off Single Slate around majors/Signature events) to spike trials when
  casual DFS interest peaks.

**Avoid:** assuming small-stakes means low LTV. Volume at $2.99–$7.99 with near-zero infra cost
can out-earn a small base of $45–$79 grinders, and it builds the funnel the higher tiers convert
from.

---

## 6. Free trial & conversion

- **14-day full-access trial** timed to **one full slate cycle** (Tue projections → Sun results) so
  users feel the whole loop and *see a result*.
- **A/B test card-required vs. not.** No-card = more trials, lower intent; card-required = fewer,
  higher conversion. Start no-card to build top-of-funnel and testimonials.
- **"Beat your last week" hook** — show their lineups' contest-ROI vs. the field after Sunday.
- **Onboarding that reaches the aha fast:** preloaded current slate, one-click optimal pool,
  ownership + leverage visible immediately.
- **Win-back & retention:** weekly "ownership accuracy report" email (our MAE vs. actual) — turns
  our core metric into recurring proof and a reason to stay.

---

## 7. Acquisition channels (DFS-specific)

1. **X/Twitter DFS golf community** — the center of gravity. Post **free weekly ownership + leverage
   board** every Tuesday; gate the full tool behind trial. Tag/engage known golf DFS accounts.
2. **Discord** — run a community; free tier gets a daily ownership snapshot, paid gets the platform.
3. **Content/SEO** — "[Event] DFS ownership projections" pages each week (this is exactly what
   Stokastic/RotoGrinders rank for). Our automation makes this nearly free to produce.
4. **Affiliates/promo codes** — DFS content creators & podcasts run on affiliate codes; mirror the
   category playbook (creator code → 15% off, rev-share).
5. **Proof-of-accuracy marketing** — publish back-tested MAE and post-slate "we said X%, actual was
   Y%" recaps. Nobody else does this; it's credible and differentiating.
6. **"Beat the rake" campaign** — aimed at the $1–$10/week player: "You're playing $5 GPPs without
   knowing real ownership. A real edge costs $2.99 for the week." Run on r/dfsports, casual DFS
   Discords, and TikTok/Shorts — channels the $97–$400 incumbents don't bother with because their
   price floor doesn't fit a casual audience.

---

## 8. Phased rollout

- **Phase 0 — Private beta (now → 4 wks):** 10–25 hand-picked golf grinders, free. Goal: validate
  ownership accuracy live vs. SaberSim/Stokastic, fix workflow gaps, collect testimonials + MAE
  proof. Instrument everything.
- **Phase 1 — Founding launch (4–8 wks):** open with founding-member pricing (locked low rate /
  lifetime for first 50–100). Free weekly ownership board on X to seed funnel. Card-optional trial.
- **Phase 2 — Public launch (season ramp / a major):** standard pricing + tiers live, event promos,
  affiliate program, content engine. Time it to a high-interest event.
- **Phase 3 — Expand:** Edge/BYO-model tier, then adjacent slates (Showdown, opposite-field), then
  potentially other sports *only if* the ownership-model advantage transfers.

---

## 9. Unit economics & targets (rough)

- **Infra cost is ~$0** (GitHub Pages + Actions, client-side compute). Near-100% gross margin →
  pricing freedom and runway to win on volume at low price points.
- **Illustrative:** 1,000 Starter @ $7.99 ≈ $8k MRR; 2,000 mixed (Single Slate/Starter/Plus/Edge)
  ≈ $15–20k MRR. Volume requirement is higher than the grinder-priced model, but the addressable
  audience (small-stakes players) is an order of magnitude bigger.
- **Watch:** Single Slate → Starter conversion (the real funnel metric now, not just trial→paid),
  trial→paid conversion (target 20–30% card-required, 5–10% no-card), monthly churn (DFS is
  seasonal — target <8% in-season; expect summer/major spikes), CAC (mostly content/affiliate →
  low, should be lower still given casual channels are underpriced by competitors).
- **Seasonality:** golf DFS peaks Thu–Sun and around majors/Signatures; revenue is lumpy. Annual
  plans + multi-sport expansion later smooth it.

---

## 10. Moats & risks

**Moats:** proprietary ownership model + the data flywheel (every slate's actual ownership improves
the model); bring-your-own-edge (sticky for sharps); automation/UX; near-zero cost structure.

**Risks:**
- **DK API / data dependence** — if DraftKings changes/blocks endpoints, the auto-pull breaks. Keep
  a manual-CSV fallback (already built).
- **Incumbent response** — they could cut price or publish accuracy. Stay ahead on MAE and ship the
  BYO-model tier they can't easily copy.
- **Seasonality & churn** — mitigate with annual plans and an accuracy-email retention loop.
- **Compliance/ToS** — scraping DK and DFS-adjacent tooling: review DK ToS and DFS regulations
  before charging money; add clear terms.

---

## 11. Immediate next steps

1. **Lock the accuracy story** — keep improving MAE (Optuna search underway) and build the public
   "MAE vs. actual" recap. This is the whole pitch.
2. **Stand up billing** — Stripe + the tier gates above; start with founding-member pricing.
3. **Ship the free weekly ownership board** (X + a public page) — top-of-funnel engine.
4. **Recruit 10–25 beta grinders** for live validation + testimonials.
5. **Verify competitor pricing & DK/DFS ToS** before public launch.
6. **Instrument** trial→paid, churn, channel attribution from day one.
