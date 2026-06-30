/* ============================================================
 * data.js — Sample slate + projected-ownership model
 * ------------------------------------------------------------
 * Ships with a representative DraftKings PGA slate so the app
 * works the moment it loads. Replace it any time by importing a
 * DraftKings salaries CSV (see app.js / README).
 *
 * Each golfer has:
 *   id, name, salary, skill, variance
 *
 * skill   = strokes-gained-per-round vs. the field (the only knob
 *           the sim really needs; higher = better).
 * variance= round-to-round consistency (lower = steadier).
 *
 * Projected ownership is NOT hand-entered — it's modeled from
 * salary + value so it reacts automatically to the slate, the
 * same way the real DFS field behaves.
 * ============================================================ */

const SAMPLE_SLATE = [
  { name: 'Scottie Scheffler', salary: 12000, skill: 1.55, variance: 0.55 },
  { name: 'Rory McIlroy',      salary: 11200, skill: 1.30, variance: 0.70 },
  { name: 'Xander Schauffele', salary: 10600, skill: 1.20, variance: 0.55 },
  { name: 'Collin Morikawa',   salary: 10100, skill: 1.10, variance: 0.60 },
  { name: 'Ludvig Aberg',      salary: 9800,  skill: 1.05, variance: 0.75 },
  { name: 'Viktor Hovland',    salary: 9400,  skill: 0.95, variance: 0.80 },
  { name: 'Patrick Cantlay',   salary: 9100,  skill: 0.92, variance: 0.55 },
  { name: 'Hideki Matsuyama',  salary: 8900,  skill: 0.90, variance: 0.75 },
  { name: 'Justin Thomas',     salary: 8700,  skill: 0.85, variance: 0.80 },
  { name: 'Wyndham Clark',     salary: 8500,  skill: 0.80, variance: 0.85 },
  { name: 'Tommy Fleetwood',   salary: 8300,  skill: 0.82, variance: 0.60 },
  { name: 'Max Homa',          salary: 8100,  skill: 0.74, variance: 0.75 },
  { name: 'Sahith Theegala',   salary: 7900,  skill: 0.72, variance: 0.85 },
  { name: 'Russell Henley',    salary: 7700,  skill: 0.76, variance: 0.55 },
  { name: 'Tony Finau',        salary: 7600,  skill: 0.70, variance: 0.80 },
  { name: 'Sungjae Im',        salary: 7500,  skill: 0.68, variance: 0.60 },
  { name: 'Jason Day',         salary: 7400,  skill: 0.66, variance: 0.80 },
  { name: 'Sepp Straka',       salary: 7300,  skill: 0.67, variance: 0.65 },
  { name: 'Cameron Young',     salary: 7200,  skill: 0.64, variance: 0.90 },
  { name: 'Corey Conners',     salary: 7100,  skill: 0.63, variance: 0.60 },
  { name: 'Akshay Bhatia',     salary: 7000,  skill: 0.60, variance: 0.90 },
  { name: 'Brian Harman',      salary: 6900,  skill: 0.58, variance: 0.70 },
  { name: 'Si Woo Kim',        salary: 6800,  skill: 0.56, variance: 0.85 },
  { name: 'Tom Kim',           salary: 6700,  skill: 0.55, variance: 0.85 },
  { name: 'Keegan Bradley',    salary: 6600,  skill: 0.54, variance: 0.75 },
  { name: 'Aaron Rai',         salary: 6500,  skill: 0.52, variance: 0.65 },
  { name: 'J.T. Poston',       salary: 6400,  skill: 0.48, variance: 0.80 },
  { name: 'Denny McCarthy',    salary: 6300,  skill: 0.50, variance: 0.60 },
  { name: 'Mackenzie Hughes',  salary: 6200,  skill: 0.44, variance: 0.85 },
  { name: 'Nick Taylor',       salary: 6100,  skill: 0.45, variance: 0.80 },
  { name: 'Adam Scott',        salary: 6000,  skill: 0.46, variance: 0.75 },
  { name: 'Taylor Moore',      salary: 5900,  skill: 0.38, variance: 0.90 },
  { name: 'Lucas Glover',      salary: 5800,  skill: 0.40, variance: 0.80 },
  { name: 'Davis Thompson',    salary: 5700,  skill: 0.36, variance: 0.90 },
  { name: 'Eric Cole',         salary: 5600,  skill: 0.32, variance: 0.95 },
  { name: 'Ben Griffin',       salary: 5500,  skill: 0.34, variance: 0.90 },
  { name: 'Adam Hadwin',       salary: 5400,  skill: 0.33, variance: 0.80 },
  { name: 'Chris Kirk',        salary: 5300,  skill: 0.35, variance: 0.75 },
  { name: 'Matt Kuchar',       salary: 5200,  skill: 0.28, variance: 0.80 },
  { name: 'K.H. Lee',          salary: 5000,  skill: 0.25, variance: 0.95 },
];

/** Assign stable ids and default editable fields. */
function buildSlate(rawList) {
  return rawList.map((g, i) => ({
    id: 'g' + i,
    name: g.name,
    salary: g.salary,
    skill: g.skill,
    variance: g.variance != null ? g.variance : 0.75,
    locked: false,
    banned: false,
    selected: true,
  }));
}

/**
 * Skill calibration — blend of betting-market odds and strokes-gained.
 *
 * The sim is tuned for skill ~0.0–1.5 (strokes/round vs. the simulated field).
 * Rather than feed raw SG (which varies wildly week to week and is a noisier
 * signal of who will actually score), we STANDARDIZE each input to a z-score
 * within the slate and BLEND them, weighting the sharper market signal more:
 *
 *   marketZ  = avg of z(win odds), z(top-5 odds), z(top-10 odds)
 *   skillZ   = MARKET_WEIGHT * marketZ + (1 - MARKET_WEIGHT) * z(SG_TOT)
 *   skill    = SKILL_CENTER + SKILL_Z * skillZ   (clamped to [SKILL_MIN, SKILL_MAX])
 *
 * This is why a golfer with elite win/top-5/top-10 odds (e.g. Scheffler)
 * outprojects one with a flashier SG number but weak odds (e.g. Clark),
 * regardless of the SG profile. Falls back gracefully to whichever signal is
 * present. Calibrated so the best player projects to a ~88 mean (an elite DK
 * average), the median ~60, value plays mid-40s — only ~6 carry a 100+ ceiling.
 */
const SKILL_CENTER = 0.45;
const SKILL_Z = 0.35;
const SKILL_MIN = -0.25;
const SKILL_MAX = 1.5;
const MARKET_WEIGHT = 0.80; // odds vs. SG_TOT in the skill blend
// Flat fallback multiplier used only when we can't standardize (e.g. a DK CSV
// import that has no SG/odds for the field, or a single golfer).
const SKILL_SCALE = 0.6;

/** Mean & std of a numeric array (population std). */
function meanStd(arr) {
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const sd =
    Math.sqrt(arr.reduce((a, b) => a + (b - mean) ** 2, 0) / arr.length) || 1;
  return { mean, sd };
}

/**
 * Field z-score function for a signal. Need ≥5 values to standardize;
 * otherwise returns a function that always answers null (signal skipped).
 */
function zfun(vals) {
  const v = vals.filter((x) => x != null);
  if (v.length < 5) return () => null;
  const { mean, sd } = meanStd(v);
  return (x) => (x == null ? null : (x - mean) / sd);
}

/**
 * Betting-market z-score function: avg of z(win prob), z(top-5 prob),
 * z(top-10 prob) — whichever are present — for each record in the given
 * field. Shared by the initial slate build and course-fit re-weighting so
 * both use the exact same market signal.
 */
function computeMarketZ(records) {
  const winVal = (r) => (r.winProb != null ? r.winProb : r.impliedProb);
  const zWin = zfun(records.map(winVal));
  const zT5 = zfun(records.map((r) => r.top5Prob));
  const zT10 = zfun(records.map((r) => r.top10Prob));
  return (r) => {
    const zs = [zWin(winVal(r)), zT5(r.top5Prob), zT10(r.top10Prob)].filter((x) => x != null);
    return zs.length ? zs.reduce((a, b) => a + b, 0) / zs.length : null;
  };
}

const clampSkill = (z) =>
  Math.max(SKILL_MIN, Math.min(SKILL_MAX, SKILL_CENTER + SKILL_Z * z));

/**
 * Build the slate from an imported "master" record set (e.g. data/slate.json,
 * sourced from your spreadsheet's Sheet1). Each record may carry:
 *   name, salary, sgTot, ownership, winOdds, impliedProb, leverage, leverageTier
 * skill comes from real SG_TOT (scaled); if SG_TOT is missing we fall back to a
 * salary-implied estimate. Real ownership is preserved as-is (not re-modeled).
 * Returns { golfers, hasOwnership }.
 */
function buildSlateFromMaster(records) {
  let hasOwnership = false;
  const valid = records.filter((r) => r.name && r.salary);

  const zSg = zfun(valid.map((r) => r.sgTot));
  const marketZ = computeMarketZ(valid);

  const golfers = valid
    .map((r, i) => {
      const mz = marketZ(r); // odds-implied z (null if no odds in the slate)
      const sz = zSg(r.sgTot); // SG_TOT z (null if no/too-few SG values)
      let skill;
      if (r.skill != null) {
        skill = r.skill; // explicit (e.g. DK AvgPointsPerGame path)
      } else if (mz != null && sz != null) {
        skill = clampSkill(MARKET_WEIGHT * mz + (1 - MARKET_WEIGHT) * sz); // blend
      } else if (mz != null) {
        skill = clampSkill(mz); // odds only
      } else if (sz != null) {
        skill = clampSkill(sz); // SG only
      } else if (r.sgTot != null) {
        skill = r.sgTot * SKILL_SCALE; // flat fallback (too few to standardize)
      } else {
        skill = Math.max(0.1, (r.salary - 5000) / 5000); // salary-implied fallback
      }
      if (r.ownership != null) hasOwnership = true;
      return {
        id: 'g' + i,
        name: r.name,
        salary: r.salary,
        skill: Math.round(skill * 1000) / 1000,
        variance: r.variance != null ? r.variance : 0.75,
        locked: false,
        banned: false,
        selected: true,
        ownership: r.ownership != null ? r.ownership : undefined,
        // Extras carried through for display / filtering / future use.
        sgTot: r.sgTot,
        sgT2g: r.sgT2g,
        sgPutt: r.sgPutt,
        sgArg: r.sgArg,
        sgApp: r.sgApp,
        sgOtt: r.sgOtt,
        winOdds: r.winOdds,
        impliedProb: r.impliedProb,
        winProb: r.winProb,
        top5Prob: r.top5Prob,
        top10Prob: r.top10Prob,
        leverage: r.leverage,
        leverageTier: r.leverageTier,
      };
    });
  return { golfers, hasOwnership };
}

/**
 * Projected ownership model.
 * The DFS field piles onto perceived value (projected points per $1,000)
 * with extra gravity toward marquee/high-salary names. We turn a "heat"
 * score into ownership via a softmax-like normalization that sums to a
 * realistic ~600% total (6 roster spots * 100%).
 *
 * @param {Array} golfers
 * @param {Map} simResults - to read projected mean points (optional)
 */
function projectOwnership(golfers, simResults) {
  // Raw signals the field reacts to: projected points and value (pts/$1k).
  const proj = golfers.map((g) => (simResults ? simResults.get(g.id).mean : g.skill * 70));
  const value = golfers.map((g, i) => proj[i] / (g.salary / 1000));

  // Standardize each signal so we can blend them on a common scale.
  const z = (arr) => {
    const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
    const sd = Math.sqrt(arr.reduce((a, b) => a + (b - mean) ** 2, 0) / arr.length) || 1;
    return arr.map((x) => (x - mean) / sd);
  };
  const zProj = z(proj);
  const zValue = z(value);

  // The field chases projection harder than pure value, and concentrates
  // ownership exponentially on the top of both. These coefficients produce a
  // realistic shape: studs 25-40%, mid-tier 8-18%, punts low single digits.
  const heat = golfers.map((_, i) => Math.exp(1.25 * zProj[i] + 0.85 * zValue[i]));
  const sum = heat.reduce((a, b) => a + b, 0);

  const targetTotal = 6 * 100; // 6 roster spots * 100%
  golfers.forEach((g, i) => {
    if (g.ownershipLocked) return; // manual override — leave the user's number alone
    // Cap any single golfer's projected ownership at a believable ceiling.
    g.ownership = Math.min(55, (heat[i] / sum) * targetTotal);
  });
  return golfers;
}

window.Data = {
  SAMPLE_SLATE, SKILL_SCALE, MARKET_WEIGHT,
  buildSlate, buildSlateFromMaster, projectOwnership,
  zfun, computeMarketZ, clampSkill,
};
