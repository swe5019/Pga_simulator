/* ============================================================
 * optimizer.js — Simulation-driven lineup pool builder
 * ------------------------------------------------------------
 * This is the "Build" phase. Rather than producing one
 * mathematically optimal lineup off flat projections (which the
 * whole field also finds), we build a POOL of lineups, each one
 * optimized against a single simulated tournament drawn from the
 * Monte Carlo run. Different simulated worlds => different optimal
 * lineups => a naturally diverse, correlated, high-upside pool.
 *
 * DraftKings PGA Classic roster rules:
 *   - exactly 6 golfers
 *   - total salary <= $50,000
 * ============================================================ */

const DK_RULES = {
  rosterSize: 6,
  salaryCap: 50000,
};

/**
 * Greedy + local-swap knapsack for one objective vector.
 * Maximizes total objective points for exactly 6 golfers under the cap.
 *
 * @param {Array} pool - eligible golfers [{id, salary, ...}]
 * @param {Map<id, number>} obj - objective value per golfer for THIS sim
 * @param {object} opts - {locks:Set, minSalary}
 */
function optimizeOne(pool, obj, opts = {}) {
  const locks = opts.locks || new Set();
  const minSalary = opts.minSalary || 0;
  const cap = DK_RULES.salaryCap;
  const size = DK_RULES.rosterSize;

  // Start with locked players.
  const lineup = [];
  let salary = 0;
  for (const g of pool) {
    if (locks.has(g.id)) { lineup.push(g); salary += g.salary; }
  }
  if (lineup.length > size || salary > cap) return null;

  const remaining = pool.filter((g) => !locks.has(g.id));
  // Greedy fill by objective-per-dollar, respecting the cap.
  remaining.sort((a, b) => (obj.get(b.id) / b.salary) - (obj.get(a.id) / a.salary));

  for (const g of remaining) {
    if (lineup.length >= size) break;
    const spotsLeft = size - lineup.length;
    // Reserve at least the cheapest possible filler for remaining spots.
    if (salary + g.salary <= cap) {
      lineup.push(g);
      salary += g.salary;
    }
  }
  if (lineup.length < size) return null;

  // Local improvement: try swaps that raise objective while staying legal.
  const inLineup = new Set(lineup.map((g) => g.id));
  let improved = true;
  let guard = 0;
  while (improved && guard++ < 60) {
    improved = false;
    for (let i = 0; i < lineup.length; i++) {
      const out = lineup[i];
      if (locks.has(out.id)) continue;
      for (const cand of remaining) {
        if (inLineup.has(cand.id)) continue;
        const newSalary = salary - out.salary + cand.salary;
        if (newSalary > cap) continue;
        if (obj.get(cand.id) > obj.get(out.id)) {
          inLineup.delete(out.id); inLineup.add(cand.id);
          lineup[i] = cand; salary = newSalary;
          improved = true;
          break;
        }
      }
    }
  }

  if (salary < minSalary) {
    // Try to upgrade the cheapest non-locked golfer to use more salary.
    for (let i = 0; i < lineup.length && salary < minSalary; i++) {
      const out = lineup[i];
      if (locks.has(out.id)) continue;
      let best = null;
      for (const cand of remaining) {
        if (inLineup.has(cand.id)) continue;
        const newSalary = salary - out.salary + cand.salary;
        if (newSalary <= cap && cand.salary > out.salary) {
          if (!best || obj.get(cand.id) > obj.get(best.id)) best = cand;
        }
      }
      if (best) {
        inLineup.delete(out.id); inLineup.add(best.id);
        salary = salary - out.salary + best.salary;
        lineup[i] = best;
      }
    }
  }

  return { players: lineup.map((g) => g.id), salary };
}

/** Stable key for de-duplicating lineups regardless of player order. */
function lineupKey(ids) {
  return [...ids].sort().join('|');
}

/**
 * Build a lineup pool from the simulation results.
 *
 * @param {Array} golfers - full pool with {id, salary}
 * @param {Map} simResults - output of Sim.runSimulation (has .samples per id)
 * @param {object} opts:
 *    nLineups   - target number of unique lineups
 *    locks      - Set of golfer ids to force into every lineup
 *    bans       - Set of golfer ids to exclude
 *    maxExposure- 0..1 cap on the fraction of lineups any golfer appears in
 *    minSalary  - minimum total salary to use
 *    randomness - 0..1, how much to jitter each sim's objective for diversity
 * @returns {{lineups:Array, exposure:Map}}
 */
function buildPool(golfers, simResults, opts = {}) {
  const nLineups = opts.nLineups || 20;
  const locks = opts.locks || new Set();
  const bans = opts.bans || new Set();
  const maxExposure = opts.maxExposure != null ? opts.maxExposure : 1;
  const minSalary = opts.minSalary || 0;

  const pool = golfers.filter((g) => !bans.has(g.id));
  const nSims = pool.length ? simResults.get(pool[0].id).samples.length : 0;

  const seen = new Set();
  const lineups = [];
  const useCount = new Map(pool.map((g) => [g.id, 0]));
  const maxUses = Math.ceil(maxExposure * nLineups);

  const rng = window.Sim.makeRng(987654321);

  // Try far more sims than needed; skip duplicates and exposure-busting builds.
  let attempts = 0;
  const maxAttempts = nLineups * 40 + 500;

  while (lineups.length < nLineups && attempts < maxAttempts) {
    attempts++;
    const simIndex = Math.floor(rng() * nSims);

    // Objective = this golfer's fantasy points in this one simulated world,
    // but zero-out anyone already at their exposure cap.
    const obj = new Map();
    for (const g of pool) {
      if (useCount.get(g.id) >= maxUses && !locks.has(g.id)) {
        obj.set(g.id, -1e9);
      } else {
        obj.set(g.id, simResults.get(g.id).samples[simIndex]);
      }
    }

    const res = optimizeOne(pool, obj, { locks, minSalary });
    if (!res) continue;

    const key = lineupKey(res.players);
    if (seen.has(key)) continue;

    // Enforce exposure caps on the finished lineup.
    let busts = false;
    for (const id of res.players) {
      if (!locks.has(id) && useCount.get(id) + 1 > maxUses) { busts = true; break; }
    }
    if (busts) continue;

    seen.add(key);
    for (const id of res.players) useCount.set(id, useCount.get(id) + 1);
    lineups.push({ ...res, simIndex });
  }

  // Score every finished lineup across ALL sims for its true distribution.
  scoreLineups(lineups, simResults, nSims);
  // Composite "Birdie Score": upside, projection, and ownership-leverage blended.
  scoreComposite(lineups, golfers);

  // Sort the pool by the composite score by default.
  lineups.sort((a, b) => b.score - a.score);

  const exposure = new Map();
  for (const [id, c] of useCount) {
    if (c > 0) exposure.set(id, c / lineups.length);
  }

  return { lineups, exposure, attempts };
}

/** Compute mean / ceiling / floor of each lineup over the full sim set. */
function scoreLineups(lineups, simResults, nSims) {
  for (const lu of lineups) {
    const totals = new Float64Array(nSims);
    for (const id of lu.players) {
      const s = simResults.get(id).samples;
      for (let i = 0; i < nSims; i++) totals[i] += s[i];
    }
    const sorted = Float64Array.from(totals).sort();
    let sum = 0;
    for (let i = 0; i < nSims; i++) sum += sorted[i];
    lu.mean = sum / nSims;
    lu.ceiling = sorted[Math.floor(0.9 * nSims)];
    lu.floor = sorted[Math.floor(0.1 * nSims)];
    lu.p99 = sorted[Math.floor(0.99 * nSims)];
  }
}

/**
 * Composite "Birdie Score" — Birdie's answer to SaberSim's saber-score.
 * Rewards projection and tournament-winning upside (99th pct) while penalizing
 * total projected ownership, so unique high-ceiling lineups rise to the top.
 * Sets lu.ownSum (sum of projected ownership) and lu.score on each lineup.
 */
function scoreComposite(lineups, golfers) {
  if (!lineups.length) return;
  const own = new Map(golfers.map((g) => [g.id, g.ownership || 0]));
  for (const lu of lineups) {
    lu.ownSum = lu.players.reduce((s, id) => s + (own.get(id) || 0), 0);
  }
  const z = (vals) => {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length;
    const sd = Math.sqrt(vals.reduce((a, b) => a + (b - m) ** 2, 0) / vals.length) || 1;
    return vals.map((v) => (v - m) / sd);
  };
  const zMean = z(lineups.map((l) => l.mean));
  const zUpside = z(lineups.map((l) => l.p99)); // tournament-winning spike
  const zOwn = z(lineups.map((l) => l.ownSum));
  lineups.forEach((lu, i) => {
    // Equal weight on projection and upside, minus ownership; scaled for readability.
    lu.score = 100 + 10 * (zMean[i] + zUpside[i] - zOwn[i]);
  });
}

window.Optimizer = { DK_RULES, buildPool, optimizeOne, lineupKey };
