/* ============================================================
 * tour.js — guided in-app walkthrough
 * ------------------------------------------------------------
 * A passive, click-through tour that switches tabs for you and
 * spotlights the control being explained. No backend, no video —
 * just narrates the real UI using the sample slate that's already
 * loaded on boot.
 * ============================================================ */
const TOUR_SEEN_KEY = 'slatesims_tour_seen_v1';

const TOUR_STEPS = [
  {
    title: 'Take the 90-second tour',
    body: "Here's how to go from a slate to a DraftKings upload file in five tabs. We'll click through it for you — just hit Next.",
  },
  {
    tab: 'players', target: '.tabs',
    title: '5 tabs, one workflow',
    body: 'Players → Build → Review → Contest → Export. Run them in order. There\'s also a Hand Build tab for single-entry lineups.',
  },
  {
    tab: 'players', target: '#playerTable',
    title: 'Your player pool',
    body: 'Edit Salary or Skill inline, set per-golfer Min/Max exposure, lock 🔒 a must-play, or ban 🚫 someone out of the player pool.',
  },
  {
    tab: 'players', target: '#runSim',
    title: 'Run the simulation',
    body: 'Simulates the whole tournament thousands of times — round by round, with a 36-hole cut — to get every golfer\'s projection, floor, ceiling, Win%, and Cut%.',
  },
  {
    tab: 'players', target: '#cfPreset',
    title: 'Tune for the course',
    body: 'Weight OTT/APP/ARG/PUTT skill to match this week\'s course profile, or pick a preset like "Bomber\'s paradise."',
  },
  {
    tab: 'build', target: '#buildBtn',
    title: 'Build a lineup pool',
    body: 'Builds many optimized lineups, each one against a different simulated outcome of the tournament — so your pool is diverse and correlated, not 20 copies of the same chalk.',
  },
  {
    tab: 'lineups', target: '#exposureTable',
    title: 'Find your leverage',
    body: 'Compares your exposure to each golfer against the field\'s projected ownership. That gap is your edge — fade the chalk, lean into the leverage.',
  },
  {
    tab: 'contest', target: '#runContest',
    title: 'Simulate the contest',
    body: 'Pick a real DK contest (or model one) and rank your lineups by expected ROI against a simulated field, not just raw projected points.',
  },
  {
    tab: 'export', target: '#exportDK',
    title: 'Export to DraftKings',
    body: 'Download the upload CSV, or fill your reserved entries template directly in DraftKings\' Name (ID) format.',
  },
  {
    tab: 'handbuild', target: '#handPool',
    title: 'Playing one entry?',
    body: 'Hand Build lets you draft a single lineup yourself, watching salary remaining update live as you add golfers.',
  },
  {
    title: "You're ready",
    body: 'Head back to tab 1, import this week\'s slate (or just use the sample that\'s already loaded), and hit Run Simulation.',
  },
];

let tourIdx = 0;
let tourEls = null;

function tourSwitchTab(tabKey) {
  const btn = document.querySelector(`.tab[data-tab="${tabKey}"]`);
  if (btn && !btn.classList.contains('active')) btn.click();
}

function tourPlace() {
  const step = TOUR_STEPS[tourIdx];
  const { backdrop, spot, card } = tourEls;
  const target = step.target ? document.querySelector(step.target) : null;

  if (!target) {
    spot.className = 'tour-spot center';
    spot.style.cssText = '';
    card.className = 'tour-card center';
    card.style.cssText = '';
  } else {
    const r = target.getBoundingClientRect();
    const pad = 8;
    spot.className = 'tour-spot';
    spot.style.top = `${Math.max(r.top - pad, 0)}px`;
    spot.style.left = `${Math.max(r.left - pad, 0)}px`;
    spot.style.width = `${r.width + pad * 2}px`;
    spot.style.height = `${r.height + pad * 2}px`;

    card.className = 'tour-card';
    const cardW = 320;
    const margin = 14;
    let top = r.bottom + pad + margin;
    const cardH = card.offsetHeight || 160;
    if (top + cardH > window.innerHeight - margin) {
      top = r.top - pad - margin - cardH;
      if (top < margin) top = Math.max(margin, window.innerHeight - cardH - margin);
    }
    let left = r.left;
    if (left + cardW > window.innerWidth - margin) left = window.innerWidth - cardW - margin;
    if (left < margin) left = margin;
    card.style.top = `${top}px`;
    card.style.left = `${left}px`;
  }
  void backdrop; // backdrop is static full-screen; nothing to position
}

function tourRender() {
  const step = TOUR_STEPS[tourIdx];
  if (step.tab) tourSwitchTab(step.tab);
  const { card } = tourEls;
  const last = tourIdx === TOUR_STEPS.length - 1;
  card.innerHTML = `
    <div class="tour-step">Step ${tourIdx + 1} of ${TOUR_STEPS.length}</div>
    <h3>${step.title}</h3>
    <p>${step.body}</p>
    <div class="tour-actions">
      <button class="tour-skip" id="tourSkip">Skip tour</button>
      <span class="spacer"></span>
      ${tourIdx > 0 ? '<button class="ghost" id="tourBack">Back</button>' : ''}
      <button class="primary" id="tourNext">${last ? 'Finish' : 'Next'}</button>
    </div>`;
  $('#tourSkip').addEventListener('click', endTour);
  if (tourIdx > 0) $('#tourBack').addEventListener('click', () => { tourIdx--; tourRender(); });
  $('#tourNext').addEventListener('click', () => {
    if (last) endTour();
    else { tourIdx++; tourRender(); }
  });
  // Position after layout/tab-switch settles so target rects are accurate.
  requestAnimationFrame(() => requestAnimationFrame(tourPlace));
}

function startTour() {
  tourIdx = 0;
  const backdrop = document.createElement('div');
  backdrop.className = 'tour-backdrop';
  const spot = document.createElement('div');
  spot.className = 'tour-spot';
  const card = document.createElement('div');
  card.className = 'tour-card';
  document.body.append(backdrop, spot, card);
  tourEls = { backdrop, spot, card };
  document.body.style.overflow = 'hidden';
  window.addEventListener('resize', tourPlace);
  tourRender();
  try { localStorage.setItem(TOUR_SEEN_KEY, '1'); } catch (e) { /* ignore */ }
}

function endTour() {
  if (!tourEls) return;
  tourEls.backdrop.remove();
  tourEls.spot.remove();
  tourEls.card.remove();
  tourEls = null;
  document.body.style.overflow = '';
  window.removeEventListener('resize', tourPlace);
}

document.addEventListener('DOMContentLoaded', () => {
  const btn = $('#startTour');
  if (btn) btn.addEventListener('click', startTour);
  let seen = false;
  try { seen = !!localStorage.getItem(TOUR_SEEN_KEY); } catch (e) { /* ignore */ }
  if (!seen) setTimeout(startTour, 600);
});
