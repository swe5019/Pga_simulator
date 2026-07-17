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
    // Upgrade cheapest non-locked players first (most room for salary gain),
    // picking the highest-salary valid replacement each time.
    const upgradeable = lineup
      .map((g, i) => ({ g, i }))
      .filter(({ g }) => !locks.has(g.id))
      .sort((a, b) => a.g.salary - b.g.salary);
    for (const { g: out, i } of upgradeable) {
      if (salary >= minSalary) break;
      let best = null;
      for (const cand of remaining) {
        if (inLineup.has(cand.id)) continue;
        const newSalary = salary - out.salary + cand.salary;
        if (newSalary <= cap && cand.salary > out.salary) {
          if (!best || cand.salary > best.salary) best = cand;
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
  const allLineups = []; // full candidate pool before exposure post-selection
  // useCount tracks only floor (minExp) progress during the build phase.
  const useCount = new Map(pool.map((g) => [g.id, 0]));
  const minUses = new Map(
    pool.map((g) => [g.id, Math.round((minExpById.get(g.id) || 0) * nLineups)])
  );

  const rng = window.Sim.makeRng(987654321);

  const hasConstraints = bracketedOwnership.length > 0 || salaryTiers.length > 0 || minUniquePlayers > 0 || minTotalOwn != null || maxTotalOwn != null || minWinEquity > 0 || minSalary > 0;
  // Stop when 1500 consecutive attempts find nothing new — space is genuinely exhausted.
  // This is independent of nLineups so requesting 10 vs 150 explores the same space.
  const maxNoProgress = hasConstraints ? 1500 : 600;
  // Hard ceiling: never build more candidates than we'll ever need.
  const buildCap = Math.max(nLineups * 20, 500);
  let attempts = 0;
  let noProgress = 0;

  while (noProgress < maxNoProgress && attempts < 200000 && allLineups.length < buildCap) {
    attempts++;
    if (allLineups.length > 0) noProgress++;
    const simIndex = Math.floor(rng() * nSims);

    // Objective = sim points for this world. Boost players below their minExp floor.
    const obj = new Map();
    for (const g of pool) {
      let v = simResults.get(g.id).samples[simIndex];
      if (randomness > 0) v += (rng() - 0.5) * 2 * randomness * 30;
      const floor = minUses.get(g.id);
      const used = useCount.get(g.id);
      if (floor > 0 && used < floor) {
        v += 500 + 500 * ((floor - used) / floor);
      }
      obj.set(g.id, v);
    }

    // Diversity cap: limit each player's BUILD appearances to an ABSOLUTE ceiling
    // of floor(cap * nLineups). This stops one dominant player from crowding the
    // candidate pool (so post-selection has enough non-chalk lineups to choose from)
    // WITHOUT starving early iterations — the ceiling is a fixed count, not a running
    // ratio, so a 50%-of-150 player stays available for their first 75 appearances.
    const iterPool = pool.filter((g) => {
      if (locks.has(g.id)) return true;
      const capFrac = maxExpById.has(g.id) ? maxExpById.get(g.id) : maxExposure;
      if (capFrac >= 1) return true;
      const buildLimit = Math.max(1, Math.floor(capFrac * nLineups));
      return (useCount.get(g.id) || 0) < buildLimit;
    });

    const res = optimizeOne(iterPool, obj, { locks, minSalary });
    if (!res) continue;
    if (minSalary > 0 && res.salary < minSalary) continue;

    const key = lineupKey(res.players);
    if (seen.has(key)) continue;

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

    // Total ownership constraint.
    if (minTotalOwn != null || maxTotalOwn != null) {
      const ownSum = res.players.reduce((s, id) => s + (ownMap.get(id) || 0), 0);
      if (minTotalOwn != null && ownSum < minTotalOwn) continue;
      if (maxTotalOwn != null && ownSum > maxTotalOwn) continue;
    }

    // Min unique players: this lineup must differ from every existing lineup by ≥ N players.
    if (minUniquePlayers > 0) {
      const candidateSet = new Set(res.players);
      let pass = true;
      for (const lu of allLineups) {
        const shared = lu.players.filter((id) => candidateSet.has(id)).length;
        if (DK_RULES.rosterSize - shared < minUniquePlayers) { pass = false; break; }
      }
      if (!pass) continue;
    }

    // Min win equity.
    if (minWinEquity > 0) {
      const weSum = res.players.reduce((s, id) => s + (winEquityById.get(id) || 0), 0);
      if (weSum < minWinEquity) continue;
    }

    seen.add(key);
    for (const id of res.players) useCount.set(id, useCount.get(id) + 1);
    allLineups.push({ ...res, simIndex });
    noProgress = 0;
  }

  // Score every candidate lineup across ALL sims for its true distribution.
  scoreLineups(allLineups, simResults, nSims);
  scoreComposite(allLineups, golfers);

  // Sort all candidates by composite score descending.
  allLineups.sort((a, b) => b.score - a.score);

  const capFor = (id) => (maxExpById.has(id) ? maxExpById.get(id) : maxExposure);

  // Greedy top-down selection honoring per-golfer caps against a FIXED denominator T:
  // a lineup is added only while each capped player's count stays <= floor(cap * T).
  function selectWithTarget(T) {
    const count = new Map();
    const out = [];
    for (const lu of allLineups) {
      if (out.length >= nLineups) break;
      let ok = true;
      for (const id of lu.players) {
        if (locks.has(id)) continue;
        const cap = capFor(id);
        if (cap >= 1) continue;
        if ((count.get(id) || 0) + 1 > Math.floor(cap * T)) { ok = false; break; }
      }
      if (!ok) continue;
      out.push(lu);
      for (const id of lu.players) count.set(id, (count.get(id) || 0) + 1);
    }
    return out;
  }

  // Find the largest pool whose exposures actually honor the caps. Start with the
  // requested count as the denominator — this gives generous limits (e.g. 50% of 150
  // = 75) so there's no small-size starvation where floor(cap * 1) = 0 blocks the
  // very first lineup. Then descend: if we returned fewer than the denominator we
  // assumed, the true denominator is smaller, so tighten and re-select until the size
  // stabilizes. At the fixpoint size == denominator, so every count <= floor(cap*size)
  // => count/size <= cap for every player. No player can exceed their cap.
  let lineups = selectWithTarget(nLineups);
  let guard = 0;
  while (lineups.length > 0 && lineups.length < nLineups && guard++ < 200) {
    const next = selectWithTarget(lineups.length);
    if (next.length >= lineups.length) { lineups = next; break; }
    lineups = next;
  }

  // Safety net: never return an empty pool when valid lineups exist. If a capped
  // player is effectively mandatory (present in ~every lineup that satisfies the
  // other constraints), honoring their cap is impossible — fall back to the top
  // scoring lineups so the user still gets a pool. capExceeded (below) reports which
  // caps could not be met so the UI can explain why.
  if (lineups.length === 0 && allLineups.length > 0) {
    lineups = allLineups.slice(0, nLineups);
  }

  const postUseCount = new Map(pool.map((g) => [g.id, 0]));
  for (const lu of lineups) {
    for (const id of lu.players) postUseCount.set(id, (postUseCount.get(id) || 0) + 1);
  }
  const exposure = new Map();
  const capExceeded = [];
  for (const [id, c] of postUseCount) {
    if (c > 0) {
      const frac = c / lineups.length;
      exposure.set(id, frac);
      const cap = capFor(id);
      if (cap < 1 && frac > cap + 1e-9) capExceeded.push({ id, exposure: frac, cap });
    }
  }

  return { lineups, exposure, attempts, capExceeded, requested: nLineups };
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
