/* ============================================================
 * scoring.js — DraftKings PGA "Classic" scoring rules
 * ------------------------------------------------------------
 * Single source of truth for how a simulated round of golf
 * converts into DraftKings fantasy points. Keeping this isolated
 * makes it trivial to support other sites later (FanDuel, etc.).
 * ============================================================ */

// Per-hole result codes used by the simulation engine.
// The number is the score relative to par on that hole.
const HOLE = {
  ALBATROSS: -3, // double eagle
  EAGLE: -2,
  BIRDIE: -1,
  PAR: 0,
  BOGEY: 1,
  DOUBLE_PLUS: 2, // double bogey or worse
};

// DraftKings PGA Classic point values.
const DK_SCORING = {
  perHole: {
    albatross: 13,
    eagle: 8,
    birdie: 3,
    par: 0.5,
    bogey: -0.5,
    doublePlus: -1, // double bogey or worse
  },
  bonus: {
    streak3BirdiesPlus: 3, // 3+ birdies (or better) in a row within one round
    bogeyFreeRound: 3,
    allFourRoundsUnder70: 5,
    holeInOne: 5,
  },
};

const STROKES_FOR_RESULT = {
  // Used only for the "rounds under 70" bonus, by summing strokes.
  // strokes = par + relativeScore (per hole)
};

/**
 * Score a single simulated round.
 * @param {Array<{par:number, rel:number, holeInOne:boolean}>} holes - 18 holes
 * @returns {{points:number, strokes:number, bogeyFree:boolean, breakdown:object}}
 */
function scoreRound(holes) {
  const s = DK_SCORING.perHole;
  let points = 0;
  let strokes = 0;
  let bogeyFree = true;
  let birdieRun = 0; // consecutive birdies-or-better
  let streakBonusAwarded = false;
  const breakdown = {
    albatross: 0, eagle: 0, birdie: 0, par: 0, bogey: 0, doublePlus: 0,
    holeInOne: 0, streak: 0, bogeyFree: 0,
  };

  for (const h of holes) {
    strokes += h.par + h.rel;

    if (h.rel <= HOLE.ALBATROSS) {
      points += s.albatross; breakdown.albatross++;
    } else if (h.rel === HOLE.EAGLE) {
      points += s.eagle; breakdown.eagle++;
    } else if (h.rel === HOLE.BIRDIE) {
      points += s.birdie; breakdown.birdie++;
    } else if (h.rel === HOLE.PAR) {
      points += s.par; breakdown.par++;
    } else if (h.rel === HOLE.BOGEY) {
      points += s.bogey; breakdown.bogey++; bogeyFree = false;
    } else {
      points += s.doublePlus; breakdown.doublePlus++; bogeyFree = false;
    }

    // Hole-in-one bonus (rare; flagged by the sim on par 3s)
    if (h.holeInOne) {
      points += DK_SCORING.bonus.holeInOne;
      breakdown.holeInOne++;
    }

    // Birdie-or-better streak tracking (eagles/albatross count)
    if (h.rel <= HOLE.BIRDIE) {
      birdieRun++;
      if (birdieRun >= 3 && !streakBonusAwarded) {
        points += DK_SCORING.bonus.streak3BirdiesPlus;
        breakdown.streak++;
        streakBonusAwarded = true; // DK awards the streak bonus once per round
      }
    } else {
      birdieRun = 0;
    }
  }

  if (bogeyFree) {
    points += DK_SCORING.bonus.bogeyFreeRound;
    breakdown.bogeyFree++;
  }

  return { points, strokes, bogeyFree, breakdown };
}

/**
 * Score a full simulated tournament (array of rounds, each an array of holes).
 * Handles the cross-round "all four rounds under 70" bonus and the missed cut.
 * @param {Array<Array>} rounds
 * @param {boolean} madeCut - whether the golfer played all 4 rounds
 */
function scoreTournament(rounds, madeCut) {
  let points = 0;
  const roundStrokes = [];
  for (const holes of rounds) {
    const r = scoreRound(holes);
    points += r.points;
    roundStrokes.push(r.strokes);
  }

  // "All 4 rounds under 70" bonus only possible if 4 rounds were played.
  if (madeCut && roundStrokes.length === 4 && roundStrokes.every((st) => st < 70)) {
    points += DK_SCORING.bonus.allFourRoundsUnder70;
  }

  return { points, roundStrokes };
}

window.Scoring = { HOLE, DK_SCORING, scoreRound, scoreTournament };
