/* ============================================================
 * contest.js — Contest simulation (ROI per lineup)
 * ------------------------------------------------------------
 * Birdie's answer to SaberSim's "Contest Sims". For each of your
 * lineups we estimate expected ROI in a specific contest by:
 *   1. generating an ownership-weighted FIELD of opponent lineups,
 *   2. scoring your lineups and the field across the simulated
 *      tournaments (the same Monte Carlo worlds as the sim),
 *   3. ranking you within the field each world and paying you out
 *      of a modeled payout structure for that contest.
 *
 * Payouts are MODELED approximations (rake + top-heavy curve), good
 * for ranking lineups by contest-fit — not exact DK prize tables.
 * ============================================================ */

const CONTEST_RAKE = { gpp: 0.15, se: 0.15, dub: 0.1 };

/** Pick one golfer index by ownership weight (cumulative scan). */
function weightedPick(elig, cum, total, rng) {
  const x = rng() * total;
  let lo = 0;
  let hi = cum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] < x) lo = mid + 1;
    else hi = mid;
  }
  return elig[lo];
}

/**
 * Generate F valid DK field lineups, ownership-weighted. First 5 golfers are
 * sampled by ownership; the 6th is drawn from those that keep salary <= cap.
 */
function generateField(golfers, opts) {
  const cap = 50000;
  const size = 6;
  const minSal = opts.minFieldSalary || 46000;
  const F = opts.fieldLineups || 2000;
  const exclude = opts.exclude || new Set();
  const rng = opts.rng;

  const elig = golfers.filter((g) => !exclude.has(g.id) && (g.ownership || 0) >= 0);
  const weights = elig.map((g) => Math.max(0.01, g.ownership || 1));
  const cum = [];
  let total = 0;
  for (const w of weights) { total += w; cum.push(total); }

  const field = [];
  let guard = 0;
  const maxGuard = F * 60;
  while (field.length < F && guard++ < maxGuard) {
    const used = new Set();
    const ids = [];
    let sal = 0;
    let ok = true;
    for (let s = 0; s < size - 1; s++) {
      let g = null;
      for (let t = 0; t < 40; t++) {
        const c = weightedPick(elig, cum, total, rng);
        if (!used.has(c.id)) { g = c; break; }
      }
      if (!g) { ok = false; break; }
      used.add(g.id); ids.push(g.id); sal += g.salary;
    }
    if (!ok) continue;
    // 6th golfer: weighted among those that fit under the cap.
    const room = cap - sal;
    const fits = elig.filter((g) => !used.has(g.id) && g.salary <= room);
    if (!fits.length) continue;
    let fsum = 0;
    const fcum = [];
    for (const g of fits) { fsum += Math.max(0.01, g.ownership || 1); fcum.push(fsum); }
    const last = weightedPick(fits, fcum, fsum, rng);
    sal += last.salary; ids.push(last.id);
    if (sal < minSal || sal > cap) continue;
    field.push(ids);
  }
  return field;
}

/** Build a modeled payout: returns prizeForRank(rank), prizePool, paidSpots. */
function buildPayout(structure, entries, fee) {
  const rake = CONTEST_RAKE[structure] != null ? CONTEST_RAKE[structure] : 0.15;
  const prizePool = entries * fee * (1 - rake);

  if (structure === 'dub') {
    const paid = Math.max(1, Math.floor(entries * 0.45));
    const each = prizePool / paid;
    return { prizeForRank: (r) => (r <= paid ? each : 0), prizePool, paidSpots: paid };
  }

  // GPP / single-entry: top-heavy power-law with a min-cash floor.
  const cashFrac = structure === 'se' ? 0.18 : 0.2;
  const power = structure === 'se' ? 0.9 : 1.15;
  const paid = Math.max(1, Math.floor(entries * cashFrac));
  const prizes = new Float64Array(paid);
  let sum = 0;
  for (let r = 1; r <= paid; r++) { const w = Math.pow(r, -power); prizes[r - 1] = w; sum += w; }
  const minCash = 1.5 * fee;
  for (let i = 0; i < paid; i++) prizes[i] = (prizePool * prizes[i]) / sum;
  for (let i = 0; i < paid; i++) if (prizes[i] < minCash) prizes[i] = minCash;
  let tot = 0;
  for (let i = 0; i < paid; i++) tot += prizes[i];
  if (tot > prizePool) { const s = prizePool / tot; for (let i = 0; i < paid; i++) prizes[i] *= s; }
  return { prizeForRank: (r) => (r >= 1 && r <= paid ? prizes[r - 1] : 0), prizePool, paidSpots: paid };
}

/**
 * Run the contest simulation.
 * @param {Array} myLineups - [{players:[ids]}] from the build
 * @param {Array} golfers   - full pool (need ownership + salary)
 * @param {Map} simResults  - per-golfer {samples}
 * @param {object} opts - {entries, fee, structure, fieldLineups, worlds, exclude, rng}
 * @returns {{results, field, payout}}
 */
function runContestSim(myLineups, golfers, simResults, opts = {}) {
  const fee = opts.fee || 20;
  const entries = opts.entries || 1000;
  const structure = opts.structure || 'gpp';
  const rng = opts.rng || window.Sim.makeRng(424242);

  const anyId = myLineups[0].players[0];
  const nSims = simResults.get(anyId).samples.length;
  const W = Math.min(nSims, opts.worlds || 4000);

  const field = generateField(golfers, { ...opts, rng });
  const Ff = field.length;
  const payout = buildPayout(structure, entries, fee);
  const sampleOf = (id) => simResults.get(id).samples;

  const agg = myLineups.map(() => ({ sumPrize: 0, cash: 0, sumPts: 0, win: 0 }));
  const ft = new Float64Array(Ff);

  for (let w = 0; w < W; w++) {
    for (let f = 0; f < Ff; f++) {
      let t = 0;
      const ids = field[f];
      for (let k = 0; k < ids.length; k++) t += sampleOf(ids[k])[w];
      ft[f] = t;
    }
    ft.sort();
    for (let m = 0; m < myLineups.length; m++) {
      let t = 0;
      const ids = myLineups[m].players;
      for (let k = 0; k < ids.length; k++) t += sampleOf(ids[k])[w];
      // number of field lineups strictly beating me
      let lo = 0;
      let hi = Ff;
      while (lo < hi) { const mid = (lo + hi) >> 1; if (ft[mid] <= t) lo = mid + 1; else hi = mid; }
      const numGreater = Ff - lo;
      let rank = Math.floor((numGreater / Ff) * entries) + 1;
      if (rank < 1) rank = 1;
      if (rank > entries) rank = entries;
      const prize = payout.prizeForRank(rank);
      const a = agg[m];
      a.sumPrize += prize;
      if (prize > 0) a.cash++;
      if (rank === 1) a.win++;
      a.sumPts += t;
    }
  }

  const results = myLineups.map((lu, m) => {
    const a = agg[m];
    const expPay = a.sumPrize / W;
    return {
      idx: m,
      players: lu.players,
      roi: (expPay / fee - 1) * 100,
      cashPct: (a.cash / W) * 100,
      winPct: (a.win / W) * 100,
      expPay,
      avgPts: a.sumPts / W,
    };
  });

  return { results, fieldSize: Ff, payout, worlds: W };
}

window.Contest = { runContestSim, generateField, buildPayout };
