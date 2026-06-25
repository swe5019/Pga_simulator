# Birdie — Go-to-Market & Pricing Strategy

> Working strategy doc. Numbers on competitors are from public pricing pages (June 2026);
> verify before publishing. This is a starting framework, not a final plan.

---

## 1. The thesis

**Whoever has the most accurate ownership projections wins.** In DFS golf, edge comes from
*leverage* — being over/under the field on the right players. Leverage is only as good as the
ownership number it's measured against. Birdie's wedge is a **purpose-built, automated,
continuously-validated ownership model (LightGBM, ~2.4% MAE LOTO)** that plugs directly into a
full sim/optimizer/contest-ROI stack. We compete on **accuracy + automation + price**, not on
being yet another optimizer.

---

## 2. Competitive landscape (public pricing, verify)

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
3. **Full stack in one** — projections → sim → optimizer (Birdie Score) → contest ROI (exact DK
   payouts) → entries-file upload. SaberSim-parity features at a fraction of the price.
4. **Bring-your-own-edge (pro tier)** — power users can feed their own SG/odds/projections; the
   model and sims run on *their* numbers. No competitor offers this.
5. **Price** — golf-focused, undercutting the multi-sport incumbents.

---

## 4. Target segments

- **Primary: serious golf DFS grinders** — play weekly, multi-entry, have a bankroll, currently
  pay SaberSim/Stokastic. Pitch: same edge, better ownership, lower price.
- **Secondary: model-curious mid-stakes players** — want good ownership + an optimizer without a
  $200–$400 multi-sport bundle. Pitch: golf-only, affordable, accurate.
- **Tertiary (moat): sharps/syndicates** — want to run *their own* models with automation. Pitch:
  the only platform that runs your edge end-to-end. Highest willingness-to-pay.

---

## 5. Pricing strategy

**Anchor below the incumbents, monetize accuracy, expand to a pro tier.**

| Tier | Target | Launch price | Includes |
|---|---|---|---|
| **Free trial** | Acquisition | **14 days, full access, no card OR card-required** (test both) | Everything in Pro for one event cycle. |
| **Core** | Mid-stakes | **$29/mo** (or $19 intro) | Ownership projections + win/top-5/top-10 equity, sim projections, basic optimizer, DK upload. |
| **Pro** | Grinders | **$59/mo** | Everything: contest ROI (exact payouts), exposure tools, entries-file automation, course-fit, larger lineup builds. |
| **Edge / BYO-model** | Sharps | **$99–$149/mo** | Bring-your-own SG/odds/projections, model auto-retrain, API/export, priority. |
| **Annual** | Retention | **2 months free (~17% off)** | Smooths seasonal churn. |

**Rationale:**
- **Undercut hard at the top of funnel.** Pro at **$59** sits *below* SaberSim Starter ($97) and
  *well below* Stokastic ($200+). That's the "switch and save" wedge while still a healthy SaaS price.
- **Core at $29** matches the Data Golf model-first band and converts price-sensitive players who'd
  never pay $97.
- **Edge tier** captures the high-WTP sharps and protects margin — our true differentiator.
- **Intro pricing** ($19 Core / first-month discount) to seed reviews and testimonials; raise to
  standard after the first ~100 paying users.
- **Event promos** (15–25% off around majors/Signature events) to match category norms and spike
  trials when DFS interest peaks.
- **Founding-member lifetime/locked-rate** offer for the first 50–100 users → early cash, loyalty,
  and word-of-mouth advocates.

**Avoid:** racing to the absolute bottom. Too-cheap signals "low quality" in a market where the
product *is* the edge. Undercut the incumbents meaningfully (~40–70% cheaper) but stay a real
SaaS price so the brand reads "premium model, fair price," not "free tool."

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
6. **Head-to-head "switch" campaign** — "Paying $200 for ownership? Ours is more accurate at $59."

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
  pricing freedom and runway to undercut.
- **Illustrative:** 200 Pro @ $59 = ~$11.8k MRR; 500 mixed (Core/Pro/Edge) ≈ $20–25k MRR.
- **Watch:** trial→paid conversion (target 20–30% card-required, 5–10% no-card), monthly churn
  (DFS is seasonal — target <8% in-season; expect summer/major spikes), CAC (mostly content/affiliate
  → low).
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
