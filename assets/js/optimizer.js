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
 *    nLineups          - target number of unique lineups
 *    locks             - Set of golfer ids to force into every lineup
 *    bans              - Set of golfer ids to exclude
 *    maxExposure       - 0..1 cap on the fraction of lineups any golfer appears in
 *    maxExpById        - Map<id, 0..1> per-golfer exposure cap (overrides maxExposure)
 *    minExpById        - Map<id, 0..1> per-golfer exposure floor (best-effort)
 *    minSalary         - minimum total salary to use
 *    randomness        - 0..1, adds ±jitter to projected points for lineup diversity
 *    bracketedOwnership- [{threshold, min, max}] players per lineup with own < threshold
 *    salaryTiers       - [{salMin, salMax, minCount, maxCount}] players per salary tier
 *    minUniquePlayers  - each lineup must differ from all others by at least this many
 *    minTotalOwn       - minimum sum of projected ownership% across all 6 players
 *    maxTotalOwn       - maximum sum of projected ownership% across all 6 players
 *    minWinEquity      - minimum sum of win equity % across all 6 players
 *    winEquityById     - Map<id, number> win equity % per golfer
 * @returns {{lineups:Array, exposure:Map}}
 */
function buildPool(golfers, simResults, opts = {}) {
  const nLineups = opts.nLineups || 20;
  const locks = opts.locks || new Set();
  const bans = opts.bans || new Set();
  const maxExposure = opts.maxExposure != null ? opts.maxExposure : 1;
  const maxExpById = opts.maxExpById || new Map();
  const minExpById = opts.minExpById || new Map();
  const minSalary = opts.minSalary || 0;
  const randomness = opts.randomness || 0;
  const bracketedOwnership = opts.bracketedOwnership || [];
  const salaryTiers = opts.salaryTiers || [];
  const minUniquePlayers = opts.minUniquePlayers || 0;
  const minTotalOwn = opts.minTotalOwn != null ? opts.minTotalOwn : null;
  const maxTotalOwn = opts.maxTotalOwn != null ? opts.maxTotalOwn : null;
  const minWinEquity = opts.minWinEquity || 0;
  const winEquityById = opts.winEquityById || new Map();

  // Pre-build lookup maps for constraint checks (avoids per-lineup array scans).
  const ownMap = new Map(golfers.map((g) => [g.id, g.ownership || 0]));
  const salMap = new Map(golfers.map((g) => [g.id, g.salary]));

  const pool = golfers.filter((g) => !bans.has(g.id));
  const nSims = pool.length ? simResults.get(pool[0].id).samples.length : 0;

  const seen = new Set();
  const lineups = [];
  const useCount = new Map(pool.map((g) => [g.id, 0]));
  // Per-golfer exposure caps (default to the global cap) and floors.
  const maxUses = new Map(
    pool.map((g) => {
      const frac = maxExpById.has(g.id) ? maxExpById.get(g.id) : maxExposure;
      return [g.id, Math.max(0, Math.round(frac * nLineups))];
    })
  );
  const minUses = new Map(
    pool.map((g) => [g.id, Math.round((minExpById.get(g.id) || 0) * nLineups)])
  );

  const rng = window.Sim.makeRng(987654321);

  // Increase attempt budget when extra constraints are active.
  const hasConstraints = bracketedOwnership.length > 0 || salaryTiers.length > 0 || minUniquePlayers > 0 || minTotalOwn != null || maxTotalOwn != null || minWinEquity > 0 || minSalary > 0;
  let attempts = 0;
  const maxAttempts = nLineups * (hasConstraints ? 120 : 40) + 500;

  while (lineups.length < nLineups && attempts < maxAttempts) {
    attempts++;
    const simIndex = Math.floor(rng() * nSims);

    // Objective = this golfer's fantasy points in this one simulated world.
    // Zero-out anyone at their exposure cap; boost anyone below their floor.
    // Randomness adds ±noise to diversify the lineup pool.
    const obj = new Map();
    for (const g of pool) {
      const used = useCount.get(g.id);
      if (used >= maxUses.get(g.id) && !locks.has(g.id)) {
        obj.set(g.id, -1e9);
        continue;
      }
      let v = simResults.get(g.id).samples[simIndex];
      if (randomness > 0) v += (rng() - 0.5) * 2 * randomness * 30;
      const floor = minUses.get(g.id);
      if (floor > 0 && used < floor) {
        // Strongly prefer under-exposed must-plays (neediest first), best-effort.
        v += 500 + 500 * ((floor - used) / floor);
      }
      obj.set(g.id, v);
    }

    const res = optimizeOne(pool, obj, { locks, minSalary });
    if (!res) continue;
    if (minSalary > 0 && res.salary < minSalary) continue;

    const key = lineupKey(res.players);
    if (seen.has(key)) continue;

    // Enforce per-golfer exposure caps on the finished lineup.
    let busts = false;
    for (const id of res.players) {
      if (!locks.has(id) && useCount.get(id) + 1 > maxUses.get(id)) { busts = true; break; }
    }
    if (busts) continue;

    // Ownership bracket constraints: each {threshold, min, max} must be satisfied.
    if (bracketedOwnership.length) {
      let pass = true;
      for (const b of bracketedOwnership) {
        const cnt = res.players.filter((id) => ownMap.get(id) < b.threshold).length;
        if (b.min != null && cnt < b.min) { pass = false; break; }
        if (b.max != null && cnt > b.max) { pass = false; break; }
      }
      if (!pass) continue;
    }

    // Salary tier constraints: each {salMin, salMax, minCount, maxCount} must be satisfied.
    if (salaryTiers.length) {
      let pass = true;
      for (const t of salaryTiers) {
        const cnt = res.players.filter((id) => {
          const s = salMap.get(id);
          return s >= t.salMin && s < t.salMax;
        }).length;
        if (t.minCount != null && cnt < t.minCount) { pass = false; break; }
        if (t.maxCount != null && cnt > t.maxCount) { pass = false; break; }
      }
      if (!pass) continue;
    }

    // Total ownership constraint: sum of all 6 players' projected ownership must be in range.
    if (minTotalOwn != null || maxTotalOwn != null) {
      const ownSum = res.players.reduce((s, id) => s + (ownMap.get(id) || 0), 0);
      if (minTotalOwn != null && ownSum < minTotalOwn) continue;
      if (maxTotalOwn != null && ownSum > maxTotalOwn) continue;
    }

    // Min unique players: this lineup must differ from every existing lineup by ≥ N players.
    if (minUniquePlayers > 0) {
      const candidateSet = new Set(res.players);
      let pass = true;
      for (const lu of lineups) {
        const shared = lu.players.filter((id) => candidateSet.has(id)).length;
        if (DK_RULES.rosterSize - shared < minUniquePlayers) { pass = false; break; }
      }
      if (!pass) continue;
    }

    // Min win equity: sum of all 6 players' win equity % must meet the threshold.
    if (minWinEquity > 0) {
      const weSum = res.players.reduce((s, id) => s + (winEquityById.get(id) || 0), 0);
      if (weSum < minWinEquity) continue;
    }

    seen.add(key);
    for (const id of res.players) useCount.set(id, useCount.get(id) + 1);
    lineups.push({ ...res, simIndex });
  }

  // Score every finished lineup across ALL sims for its true distribution.
  scoreLineups(lineups, simResults, nSims);
  // Composite "Sim Score": upside, projection, and ownership-leverage blended.
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
 * Composite "Sim Score" — SlateSims' answer to SaberSim's saber-score.
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
