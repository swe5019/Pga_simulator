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
// split by hole par. Calibrated (June 2026) against real DraftKings PGA
// scoring: an elite stud projects to a ~95-100 mean with a ~145 ceiling
// (winning score), mid-tier studs ~80-90, value plays ~60-70, and only a
// handful of players carry a 100+ ceiling — matching that ~6 golfers clear
// 100 fantasy points in a typical event. Field-average ~3 birdies / 3 bogeys.
const BASE_RATES = {
  3: { eagle: 0.001, birdie: 0.105, bogey: 0.21, doublePlus: 0.035 },
  4: { eagle: 0.0025, birdie: 0.155, bogey: 0.19, doublePlus: 0.032 },
  5: { eagle: 0.030, birdie: 0.35, bogey: 0.12, doublePlus: 0.028 },
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
  const up = Math.exp(0.40 * skillShift);   // helps good outcomes
  const down = Math.exp(-0.40 * skillShift); // suppresses bad outcomes

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

/**
 * Per-round probability lookup. A round only ever has three distinct pars, but the
 * skill shift is fixed for the day — so derive the three probability sets once
 * instead of recomputing them (two Math.exp each) on all 18 holes.
 */
function roundProbs(daySkill) {
  return { 3: holeProbs(3, daySkill), 4: holeProbs(4, daySkill), 5: holeProbs(5, daySkill) };
}

/** Simulate one 18-hole round given the golfer's effective skill that day. */
function simRound(rng, daySkill) {
  const probs = roundProbs(daySkill);
  const holes = [];
  for (const par of COURSE_PARS) {
    holes.push(drawHole(rng, par, probs[par]));
  }
  return holes;
}

/**
 * Simulate ONE full tournament for ONE golfer.
 * Returns the DK fantasy points and whether the cut was made.
 *
 * Cut logic: after 36 holes we compare the golfer's strokes vs. par to a
 * rough cut line. Worse than the line => missed cut => no weekend points.
 * For no-cut events (Signature events like the Travelers, limited fields)
 * pass hasCut=false and every golfer plays all 4 rounds.
 */
function simOneTournament(rng, golfer, hasCut, fixedCutLine) {
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
    // Apply the cut after 2 rounds (skipped entirely for no-cut events).
    if (hasCut && rd === 1) {
      // With a market make-cut price we use this golfer's calibrated personal
      // threshold (see calibrateCutLines); otherwise fall back to a generic line
      // ~+0.5 over par with noise for field strength.
      let missed;
      if (fixedCutLine != null) {
        missed = strokesVsPar36 > fixedCutLine.line ||
          (strokesVsPar36 === fixedCutLine.line && rng() >= fixedCutLine.tieP);
      } else {
        missed = strokesVsPar36 > 0.5 + gauss(rng) * 2;
      }
      if (missed) {
        const res = window.Scoring.scoreTournament(rounds, false);
        return { points: res.points, madeCut: false, roundStrokes: res.roundStrokes };
      }
    }
  }

  const res = window.Scoring.scoreTournament(rounds, true);
  return { points: res.points, madeCut: true, roundStrokes: res.roundStrokes };
}

/**
 * Turn a market make-cut probability into a personal 36-hole cut threshold.
 *
 * Why not simply overwrite each golfer's cut% after the fact: the cut is the single
 * biggest driver of a DFS projection, because missing it means no weekend rounds at
 * all. Overwriting the displayed number leaves the projection, floor and ceiling
 * still reflecting whatever cut rate the simulation happened to produce — so a
 * golfer priced by the market at 16% to make the cut would keep a projection built
 * on him playing the weekend half the time.
 *
 * Instead we let the market price decide WHEN he survives. Simulate his opening 36
 * holes many times, sort those scores, and take the value at his target percentile.
 * He then makes the cut in exactly that share of tournaments — and crucially, in the
 * ones where he actually played well, so the cut stays correlated with his own form
 * rather than being flipped at random.
 *
 * @param {Array} golfers - need {id, skill, variance, makeCutPct}
 * @param {number} nCal - calibration samples per golfer
 * @param {number} seed - kept separate from the main run so calibration doesn't
 *                        shift the tournament draws
 * @returns {Map<id, number>} 36-hole strokes-vs-par threshold (make cut if <=)
 */
function calibrateCutLines(golfers, nCal, seed) {
  const rng = makeRng(seed);
  const lines = new Map();
  for (const g of golfers) {
    if (g.makeCutPct == null) continue;
    const target = Math.max(0, Math.min(100, g.makeCutPct)) / 100;
    if (target <= 0) { lines.set(g.id, -Infinity); continue; }   // never survives
    if (target >= 1) { lines.set(g.id, Infinity); continue; }    // always survives
    const formSigma = g.variance != null ? g.variance : 0.7;
    const scores = new Float32Array(nCal);
    for (let i = 0; i < nCal; i++) {
      let s = 0;
      for (let rd = 0; rd < 2; rd++) {
        const probs = roundProbs(g.skill + gauss(rng) * formSigma);
        for (const par of COURSE_PARS) s += drawHole(rng, par, probs[par]).rel;
      }
      scores[i] = s;
    }
    scores.sort();
    // Lower strokes are better, so the target-th percentile is the survival line.
    const k = Math.min(nCal, Math.max(1, Math.round(target * nCal))); // how many survive
    const line = scores[k - 1];
    // 36-hole scores are whole strokes, so many rounds land exactly ON the line.
    // Admitting all of them overshoots the target badly (16% priced -> 20% actual).
    // Count the ties and admit only the fraction still needed, breaking the rest
    // at random, which lands the achieved rate on the market price.
    let below = 0, at = 0;
    for (let i = 0; i < nCal; i++) {
      if (scores[i] < line) below++;
      else if (scores[i] === line) at++;
    }
    const tieP = at > 0 ? Math.max(0, Math.min(1, (k - below) / at)) : 1;
    lines.set(g.id, { line, tieP });
  }
  return lines;
}

/**
 * Run the full slate simulation.
 * @param {Array} golfers - player pool (each must have id, skill, variance)
 * @param {number} nSims  - number of simulated tournaments
 * @param {number} seed   - RNG seed for reproducibility
 * @param {function} onProgress - optional callback(fractionDone)
 * @param {object} opts   - { hasCut: boolean } — false for no-cut Signature events
 * @returns {Map<id, {samples:Float32Array, mean, ceiling, floor, cutPct, ...}>}
 */
function runSimulation(golfers, nSims, seed, onProgress, opts) {
  const hasCut = !opts || opts.hasCut !== false; // default: there is a cut
  const rng = makeRng(seed || 12345);
  const results = new Map();

  for (const g of golfers) {
    results.set(g.id, {
      samples: new Float32Array(nSims),
      madeCutCount: 0,
    });
  }

  // Calibrate personal cut lines from market make-cut prices where we have them.
  const cutLines = hasCut ? calibrateCutLines(golfers, 2000, (seed || 12345) ^ 0x5f3759df)
                          : new Map();

  for (let i = 0; i < nSims; i++) {
    for (const g of golfers) {
      const r = simOneTournament(rng, g, hasCut, cutLines.get(g.id));
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

window.Sim = { runSimulation, COURSE_PARS, makeRng, calibrateCutLines };
