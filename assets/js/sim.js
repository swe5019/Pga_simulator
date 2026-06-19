/* ============================================================
 * sim.js — Hole-by-hole Monte Carlo engine
 * ------------------------------------------------------------
 * The heart of the product. Instead of using a flat average
 * projection with a guessed standard deviation, we simulate an
 * entire 72-hole tournament hole-by-hole for every golfer,
 * thousands of times. This naturally reproduces the things that
 * actually decide DFS golf:
 *   - birdie streaks and bogey-free rounds (correlated within a round)
 *   - eagles on par 5s, the occasional hole-in-one
 *   - the missed cut (no weekend rounds)
 *   - boom/bust shape (skewed, fat upside) rather than a bell curve
 *
 * Each golfer is described by a single "skill" number (strokes
 * gained per round vs. the field). Everything else is derived.
 * ============================================================ */

// A standard par-72 course layout: 4 par-3s, 10 par-4s, 4 par-5s.
const COURSE_PARS = [
  4, 5, 4, 3, 4, 4, 5, 3, 4, // front 9 (par 36)
  4, 4, 3, 5, 4, 4, 5, 3, 4, // back 9  (par 36)
];

// Baseline per-hole outcome probabilities for a field-average golfer,
// split by hole par. These are tuned so an average pro makes roughly
// 3-4 birdies and 2-3 bogeys per round.
const BASE_RATES = {
  3: { eagle: 0.001, birdie: 0.12, bogey: 0.18, doublePlus: 0.03 },
  4: { eagle: 0.003, birdie: 0.18, bogey: 0.16, doublePlus: 0.025 },
  5: { eagle: 0.035, birdie: 0.40, bogey: 0.10, doublePlus: 0.02 },
};

// --- Deterministic RNG (mulberry32) so a given seed is reproducible. ---
function makeRng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Standard normal via Box-Muller, driven by the seeded RNG.
function gauss(rng) {
  let u = 0, v = 0;
  while (u === 0) u = rng();
  while (v === 0) v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Convert a golfer's skill (+ a per-round form swing) into per-hole
 * outcome probabilities for a hole of the given par.
 *
 * skillShift > 0 means the golfer is playing better than the field:
 * birdie/eagle probabilities scale up, bogey/double scale down.
 */
function holeProbs(par, skillShift) {
  const base = BASE_RATES[par];
  // A gentle logistic-style multiplier. ~0.25 strokes/round of skill
  // moves birdie rate by roughly 10-15% relative.
  const up = Math.exp(0.55 * skillShift);   // helps good outcomes
  const down = Math.exp(-0.55 * skillShift); // suppresses bad outcomes

  let eagle = base.eagle * up;
  let birdie = base.birdie * up;
  let bogey = base.bogey * down;
  let doublePlus = base.doublePlus * down;

  // Clamp so probabilities stay sane, then par absorbs the remainder.
  eagle = Math.min(eagle, 0.15);
  birdie = Math.min(birdie, 0.6);
  bogey = Math.min(bogey, 0.45);
  doublePlus = Math.min(doublePlus, 0.2);

  let par0 = 1 - eagle - birdie - bogey - doublePlus;
  if (par0 < 0.05) {
    // Renormalize if an extreme skill pushed things past 1.
    const total = eagle + birdie + bogey + doublePlus + 0.05;
    eagle /= total; birdie /= total; bogey /= total; doublePlus /= total;
    par0 = 0.05 / total;
  }
  return { eagle, birdie, par: par0, bogey, doublePlus };
}

/** Draw a single hole result given probabilities. Returns rel score + flags. */
function drawHole(rng, par, probs) {
  const r = rng();
  let rel;
  if (r < probs.eagle) {
    // On par 5s an "eagle bucket" hit is usually -2; allow rare albatross.
    rel = par === 5 && rng() < 0.02 ? -3 : -2;
  } else if (r < probs.eagle + probs.birdie) {
    rel = -1;
  } else if (r < probs.eagle + probs.birdie + probs.par) {
    rel = 0;
  } else if (r < probs.eagle + probs.birdie + probs.par + probs.bogey) {
    rel = 1;
  } else {
    rel = 2; // double bogey or worse
  }

  // Hole-in-one: only on par 3s, and only when the hole was a birdie (-1 -> ace).
  let holeInOne = false;
  if (par === 3 && rel === -2) rel = -1; // par 3 "eagle" is really an ace
  if (par === 3 && rel === -1 && rng() < 0.012) holeInOne = true;

  return { par, rel, holeInOne };
}

/** Simulate one 18-hole round given the golfer's effective skill that day. */
function simRound(rng, daySkill) {
  const holes = [];
  for (const par of COURSE_PARS) {
    holes.push(drawHole(rng, par, holeProbs(par, daySkill)));
  }
  return holes;
}

/**
 * Simulate ONE full tournament for ONE golfer.
 * Returns the DK fantasy points and whether the cut was made.
 *
 * Cut logic: after 36 holes we compare the golfer's strokes vs. par to a
 * rough cut line. Worse than the line => missed cut => no weekend points.
 */
function simOneTournament(rng, golfer) {
  const skill = golfer.skill;
  // Per-golfer consistency: stars swing less round-to-round than journeymen.
  const formSigma = golfer.variance != null ? golfer.variance : 0.7;

  const rounds = [];
  let strokesVsPar36 = 0;

  for (let rd = 0; rd < 4; rd++) {
    const form = gauss(rng) * formSigma; // today's hot/cold factor
    const daySkill = skill + form;
    const holes = simRound(rng, daySkill);
    rounds.push(holes);
    if (rd < 2) {
      for (const h of holes) strokesVsPar36 += h.rel;
    }
    // Apply the cut after 2 rounds.
    if (rd === 1) {
      // Cut line ~ +1 over par for a 72 course; add noise for field strength.
      const cutLine = 1 + gauss(rng) * 2;
      if (strokesVsPar36 > cutLine) {
        const res = window.Scoring.scoreTournament(rounds, false);
        return { points: res.points, madeCut: false, roundStrokes: res.roundStrokes };
      }
    }
  }

  const res = window.Scoring.scoreTournament(rounds, true);
  return { points: res.points, madeCut: true, roundStrokes: res.roundStrokes };
}

/**
 * Run the full slate simulation.
 * @param {Array} golfers - player pool (each must have id, skill, variance)
 * @param {number} nSims  - number of simulated tournaments
 * @param {number} seed   - RNG seed for reproducibility
 * @param {function} onProgress - optional callback(fractionDone)
 * @returns {Map<id, {samples:Float32Array, mean, ceiling, floor, cutPct, ...}>}
 */
function runSimulation(golfers, nSims, seed, onProgress) {
  const rng = makeRng(seed || 12345);
  const results = new Map();

  for (const g of golfers) {
    results.set(g.id, {
      samples: new Float32Array(nSims),
      madeCutCount: 0,
    });
  }

  for (let i = 0; i < nSims; i++) {
    for (const g of golfers) {
      const r = simOneTournament(rng, g);
      const slot = results.get(g.id);
      slot.samples[i] = r.points;
      if (r.madeCut) slot.madeCutCount++;
    }
    if (onProgress && i % 250 === 0) onProgress(i / nSims);
  }

  // Aggregate summary stats per golfer.
  for (const g of golfers) {
    const slot = results.get(g.id);
    const arr = slot.samples;
    const sorted = Float32Array.from(arr).sort();
    const n = sorted.length;
    let sum = 0;
    for (let k = 0; k < n; k++) sum += sorted[k];
    const mean = sum / n;
    const pct = (p) => sorted[Math.min(n - 1, Math.floor(p * n))];

    slot.mean = mean;
    slot.median = pct(0.5);
    slot.floor = pct(0.1);    // 10th percentile
    slot.ceiling = pct(0.9);  // 90th percentile (GPP upside)
    slot.p99 = pct(0.99);     // tournament-winning spike
    slot.cutPct = (slot.madeCutCount / n) * 100;
    let varSum = 0;
    for (let k = 0; k < n; k++) varSum += (sorted[k] - mean) ** 2;
    slot.stdev = Math.sqrt(varSum / n);
  }

  if (onProgress) onProgress(1);
  return results;
}

window.Sim = { runSimulation, COURSE_PARS, makeRng };
