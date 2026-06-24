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
 * Strokes-gained → skill calibration.
 * The sim was tuned for skill ~0.25–1.6 (strokes/round vs. field), while real
 * SG_TOT runs higher (elite ~2.7). This scalar keeps the field shape realistic
 * when feeding raw SG_TOT. Bump it up to spread the field, down to compress it.
 */
const SKILL_SCALE = 0.6;

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
  const golfers = records
    .filter((r) => r.name && r.salary)
    .map((r, i) => {
      const skill =
        r.skill != null
          ? r.skill // explicit (e.g. DK AvgPointsPerGame path)
          : r.sgTot != null
          ? r.sgTot * SKILL_SCALE // real strokes-gained, scaled to sim range
          : Math.max(0.1, (r.salary - 5000) / 5000); // salary-implied fallback
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
    // Cap any single golfer's projected ownership at a believable ceiling.
    g.ownership = Math.min(55, (heat[i] / sum) * targetTotal);
  });
  return golfers;
}

window.Data = { SAMPLE_SLATE, SKILL_SCALE, buildSlate, buildSlateFromMaster, projectOwnership };
