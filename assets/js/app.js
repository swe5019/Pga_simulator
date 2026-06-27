/* ============================================================
 * app.js — UI wiring & application state
 * ------------------------------------------------------------
 * Glues the simulation engine, optimizer, and DraftKings I/O to
 * the DOM. No framework, no build step — just load index.html.
 * ============================================================ */

const State = {
  golfers: [],          // current player pool
  simResults: null,     // Map<id, stats> from the last sim run
  build: null,          // { lineups, exposure } from the last build
  hasRealOwnership: false, // true when ownership came from the master file
  dk: null,                // DraftKings overlay metadata (see overlayDk)
  dkPlayers: null,         // Map<normName, {name, dkId, ...}> from dk.json
  contest: null,           // last contest-sim result
  dkContests: null,        // real DK contests + payout tiers (dk_contests.json)
  hand: { ids: [] },       // hand-build lineup in progress (golfer ids)
  sort: { key: 'salary', dir: -1 }, // player table sort (dir: 1 asc, -1 desc)
};

/** Sort value for a golfer in the player table, by column key. */
function playerSortVal(g, key) {
  const r = State.simResults ? State.simResults.get(g.id) : null;
  switch (key) {
    case 'name': return g.name.toLowerCase();
    case 'salary': return g.salary;
    case 'skill': return g.skill;
    case 'proj': return r ? r.mean : -Infinity;
    case 'floor': return r ? r.floor : -Infinity;
    case 'ceil': return r ? r.ceiling : -Infinity;
    case 'cut': return r ? r.cutPct : -Infinity;
    case 'win': { const w = winEquity(g); return w != null ? w : -Infinity; }
    case 't5': return g.top5Prob != null ? g.top5Prob : -Infinity;
    case 't10': return g.top10Prob != null ? g.top10Prob : -Infinity;
    case 'own': return g.ownership != null ? g.ownership : -Infinity;
    case 'exp': return State.build ? (State.build.exposure.get(g.id) || 0) * 100 : -Infinity;
    case 'val': return r ? r.mean / (g.salary / 1000) : -Infinity;
    default: return g.salary;
  }
}

// DraftKings PGA Classic roster rules.
const ROSTER_SIZE = 6;
const SALARY_CAP = 50000;
const SAVED_KEY = 'birdie_saved_lineups';

/** American odds → implied probability (handles +/-). */
function impliedFromAmerican(o) {
  if (o == null || !isFinite(o) || o === 0) return null;
  return o > 0 ? 100 / (o + 100) : -o / (-o + 100);
}

/** Win equity % for a golfer: Odds-tab win prob, else implied from win odds. */
function winEquity(g) {
  if (g.winProb != null) return g.winProb;
  if (g.impliedProb != null) return g.impliedProb;
  const p = impliedFromAmerican(g.winOdds);
  return p != null ? p * 100 : null;
}

/** Resolve a golfer to DraftKings upload form "Name (draftableId)", or null. */
function dkEntryName(g) {
  const p = State.dkPlayers && State.dkPlayers.get(normName(g.name));
  if (p && p.dkId != null) return `${p.name} (${p.dkId})`;
  if (g.dkId != null) return `${g.name} (${g.dkId})`;
  return null;
}

/** Normalize a golfer name for cross-source matching (case/punct/accents/suffix). */
function normName(s) {
  return (s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z ]/g, ' ')
    .replace(/\b(jr|sr|ii|iii|iv)\b/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Overlay DraftKings data (data/dk.json) onto the loaded slate: official contest
 * salaries and OUT/WD status, matched by name. Only applied when the DK event
 * clearly matches the loaded field (≥60% of golfers match), so a stale DK file
 * for a different tournament never corrupts your slate.
 */
async function overlayDk() {
  State.dk = null;
  try {
    const res = await fetch('data/dk.json?t=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) return;
    const dk = await res.json();
    const players = dk.players || [];
    if (!players.length) return;
    const byName = new Map(players.map((p) => [normName(p.name), p]));
    State.dkPlayers = byName; // name -> DK player (for upload id resolution)
    let matched = 0;
    for (const g of State.golfers) if (byName.has(normName(g.name))) matched++;
    // Use the LARGER pool as the denominator: a small DK slate (e.g. a
    // weekend single-round/Showdown slate posted after the main 4-day
    // Classic contest has locked) can match 100% of ITSELF while covering
    // only a fraction of our full-field slate. Math.min would wrongly pass
    // that as a confident match; Math.max requires real field coverage.
    const rate = matched / (Math.max(players.length, State.golfers.length) || 1);
    const applied = rate >= 0.6;
    let dropped = 0;
    let added = 0;
    if (applied) {
      for (const g of State.golfers) {
        const p = byName.get(normName(g.name));
        if (!p) {
          // Not in this week's DK field (e.g. LIV players left over from a
          // major in the master slate) — drop from the playable pool.
          g.notInSlate = true;
          dropped++;
          continue;
        }
        g.notInSlate = false;
        g.dkSalary = p.salary;
        g.salary = p.salary; // official contest salary wins
        g.status = p.status || '';
        g.out = !!p.out;
        g.dkId = p.dkId;
      }
      // Add DK-field players missing from the master so the whole field is present.
      const have = new Set(State.golfers.filter((g) => !g.notInSlate).map((g) => normName(g.name)));
      let idx = State.golfers.length;
      for (const p of players) {
        if (have.has(normName(p.name))) continue;
        State.golfers.push({
          id: 'dk' + idx++,
          name: p.name,
          salary: p.salary,
          skill: Math.max(0.1, (p.salary - 5000) / 5000), // salary-implied until real SG arrives
          variance: 0.8,
          locked: false,
          banned: false,
          selected: true,
          ownership: undefined,
          dkId: p.dkId,
          dkSalary: p.salary,
          status: p.status || '',
          out: !!p.out,
          added: true, // from DK; no master projection yet
        });
        added++;
      }
    }
    State.dk = { event: dk.event, updatedUtc: dk.updatedUtc, matched, total: players.length, applied, dropped, added };
  } catch (e) {
    /* no DK file yet — leave the slate as-is */
  }
}

function renderDkBanner() {
  const el = $('#dkBanner');
  if (!el) return;
  const dk = State.dk;
  if (!dk) {
    el.className = 'banner hidden';
    el.textContent = '';
    return;
  }
  const when = dk.updatedUtc ? new Date(dk.updatedUtc).toLocaleString() : 'recently';
  if (dk.applied) {
    const outs = State.golfers.filter((g) => g.out);
    let msg = `✓ DK overlay — official salaries + status applied for ${dk.event || 'this slate'} (matched ${dk.matched} golfers, updated ${when}).`;
    if (dk.dropped) msg += `  ${dk.dropped} golfer(s) not in the DK field were hidden (e.g. LIV/non-entrants).`;
    if (dk.added) msg += `  ${dk.added} DK-field player(s) added from DK (tagged "no proj" — add them to your master for real projections).`;
    if (outs.length) msg += `  ⚠ ${outs.length} OUT/WD excluded: ${outs.map((g) => g.name).join(', ')}.`;
    el.className = outs.length ? 'banner warn' : 'banner ok';
    el.textContent = msg;
  } else {
    el.className = 'banner warn';
    el.textContent = `DK data is for ${dk.event || 'a different event'} and only matched ${dk.matched} of your golfers — not applied. Update your master to this week's field to sync salaries/status.`;
  }
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const byId = (id) => State.golfers.find((g) => g.id === id);
const money = (n) => '$' + Math.round(n).toLocaleString();
const pct = (n) => (n == null ? '—' : n.toFixed(1) + '%');
const num = (n) => (n == null ? '—' : n.toFixed(1));
/** Projected fantasy points for a golfer (mean of the sim), or null if unrun. */
const projOf = (g) => {
  const r = State.simResults && State.simResults.get(g.id);
  return r ? r.mean : null;
};

/* ---------------------- Tabs ---------------------- */
function initTabs() {
  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach((b) => b.classList.remove('active'));
      $$('.panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      $('#' + btn.dataset.tab).classList.add('active');
      if (btn.dataset.tab === 'handbuild') {
        renderHandBuild();
        renderSaved();
      } else if (btn.dataset.tab === 'accuracy') {
        renderAccuracy();
      }
    });
  });
}

/* ---------------------- Slate setup ---------------------- */
function loadSampleSlate() {
  State.golfers = window.Data.buildSlate(window.Data.SAMPLE_SLATE);
  State.hand.ids = []; // new slate — clear any in-progress hand lineup
  State.simResults = null;
  State.build = null;
  State.hasRealOwnership = false;
  State.dk = null;
  window.Data.projectOwnership(State.golfers, null);
  renderPlayers();
  $('#simStatus').textContent = '';
}

/**
 * On boot, try to load the live slate published from your spreadsheet
 * (data/slate.json, refreshed by the sync workflow). Falls back to the
 * built-in sample if the file isn't there yet or can't be read.
 */
async function loadAutoSlate() {
  try {
    const res = await fetch('data/slate.json?t=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) throw new Error('no slate.json (' + res.status + ')');
    const doc = await res.json();
    const records = Array.isArray(doc) ? doc : doc.golfers;
    if (!records || !records.length) throw new Error('empty slate.json');

    const { golfers, hasOwnership } = window.Data.buildSlateFromMaster(records);
    State.golfers = golfers;
    State.hand.ids = []; // new slate — clear any in-progress hand lineup
    State.simResults = null;
    State.build = null;
    State.hasRealOwnership = hasOwnership;
    // Only model ownership if the file didn't supply real projections.
    if (!hasOwnership) window.Data.projectOwnership(State.golfers, null);
    await overlayDk(); // official salaries + OUT/WD status from DraftKings
    autoDetectCut();
    renderPlayers();

    const when = doc.updatedUtc ? new Date(doc.updatedUtc).toLocaleString() : 'now';
    $('#simStatus').textContent =
      `Loaded ${golfers.length} golfers from your master file (updated ${when}). Run the sim.`;
  } catch (e) {
    // No published slate yet — use the sample so the app still works.
    loadSampleSlate();
  }
}

/* ---------------------- Player table ---------------------- */
function renderPlayers() {
  const tbody = $('#playerTable tbody');
  tbody.innerHTML = '';
  const { key, dir } = State.sort;
  const sorted = [...State.golfers].sort((a, b) => {
    const va = playerSortVal(a, key);
    const vb = playerSortVal(b, key);
    if (typeof va === 'string') return dir * va.localeCompare(vb);
    return dir * (va - vb);
  });
  // Reflect the active sort on the header arrows.
  $$('#playerTable thead th[data-sort]').forEach((th) => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === key) th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
  });

  for (const g of sorted) {
    if (g.notInSlate) continue; // not in this week's DK field — hidden from the pool
    const r = State.simResults ? State.simResults.get(g.id) : null;
    const proj = r ? r.mean : null;
    const value = proj != null ? proj / (g.salary / 1000) : null;
    const exp = State.build ? (State.build.exposure.get(g.id) || 0) * 100 : null;

    const win = winEquity(g);
    const tr = document.createElement('tr');
    if (g.banned) tr.classList.add('banned');
    if (g.locked) tr.classList.add('locked');
    if (g.out) tr.classList.add('out');
    if (!g.selected) tr.classList.add('deselected');
    tr.innerHTML = `
      <td class="ctr"><input type="checkbox" class="selbox" data-id="${g.id}" ${g.selected ? 'checked' : ''}></td>
      <td class="name"><button class="pname" data-id="${g.id}" title="View outcome distribution">${g.name}</button>${g.out ? ' <span class="tag out">OUT</span>' : ''}${g.added ? ' <span class="tag noproj" title="From DK field; no projection in your master yet — using salary-based skill">no proj</span>' : ''}</td>
      <td class="num"><input class="cell" data-id="${g.id}" data-f="salary" value="${g.salary}"></td>
      <td class="num"><input class="cell" data-id="${g.id}" data-f="skill" value="${g.skill}"></td>
      <td class="num"><input class="projcell${g.projLocked ? ' overridden' : ''}" data-id="${g.id}" value="${proj != null ? proj.toFixed(1) : ''}" placeholder="—" title="Manual projection override — leave blank to use the sim"></td>
      <td class="num dim">${r ? num(r.floor) : '—'}</td>
      <td class="num up">${r ? num(r.ceiling) : '—'}</td>
      <td class="num">${r ? num(r.cutPct) : '—'}</td>
      <td class="num">${pct(win)}</td>
      <td class="num dim">${pct(g.top5Prob)}</td>
      <td class="num dim">${pct(g.top10Prob)}</td>
      <td class="num"><input class="owncell${g.ownershipLocked ? ' overridden' : ''}" data-id="${g.id}" value="${g.ownership != null ? g.ownership.toFixed(1) : ''}" placeholder="—" title="Manual ownership override — leave blank to use the model"></td>
      <td class="num">${exp != null ? exp.toFixed(0) + '%' : '—'}</td>
      <td class="num">${value != null ? value.toFixed(2) : '—'}</td>
      <td class="num"><input class="expcell" data-id="${g.id}" data-f="minExp" value="${g.minExp != null ? g.minExp : ''}" placeholder="–"></td>
      <td class="num"><input class="expcell" data-id="${g.id}" data-f="maxExp" value="${g.maxExp != null ? g.maxExp : ''}" placeholder="–"></td>
      <td class="ctr"><button class="toggle ${g.locked ? 'on' : ''}" data-id="${g.id}" data-t="locked">🔒</button></td>
      <td class="ctr"><button class="toggle ${g.banned ? 'on' : ''}" data-id="${g.id}" data-t="banned">🚫</button></td>
    `;
    tbody.appendChild(tr);
  }

  // Inline edits
  tbody.querySelectorAll('input.cell').forEach((inp) => {
    inp.addEventListener('change', () => {
      const g = byId(inp.dataset.id);
      const v = parseFloat(inp.value);
      if (!isNaN(v)) g[inp.dataset.f] = v;
      State.simResults = null; // edits invalidate the sim
      renderPlayers();
    });
  });
  // Min/Max exposure targets (% of lineups). Blank clears the target.
  tbody.querySelectorAll('input.expcell').forEach((inp) => {
    inp.addEventListener('change', () => {
      const g = byId(inp.dataset.id);
      const raw = inp.value.trim();
      const v = parseFloat(raw);
      g[inp.dataset.f] = raw === '' || isNaN(v) ? null : Math.max(0, Math.min(100, v));
    });
  });
  // Player selection (include in the sim/build pool without locking)
  tbody.querySelectorAll('input.selbox').forEach((cb) => {
    cb.addEventListener('change', () => {
      const g = byId(cb.dataset.id);
      g.selected = cb.checked;
      cb.closest('tr').classList.toggle('deselected', !cb.checked);
    });
  });
  // Manual Proj override. Blank clears it and reverts to the sim's number.
  tbody.querySelectorAll('input.projcell').forEach((inp) => {
    inp.addEventListener('change', () => {
      const g = byId(inp.dataset.id);
      const raw = inp.value.trim();
      const v = parseFloat(raw);
      if (raw === '' || isNaN(v)) {
        g.projLocked = false;
        g.projOverride = null;
        if (g._projOrig && State.simResults && State.simResults.get(g.id)) {
          const r = State.simResults.get(g.id);
          r.mean = g._projOrig.mean;
          r.floor = g._projOrig.floor;
          r.ceiling = g._projOrig.ceiling;
        }
      } else {
        g.projLocked = true;
        g.projOverride = v;
        applyProjOverrideToGolfer(g);
      }
      renderPlayers();
    });
  });
  // Manual ownership override. Blank clears it and reverts to the model.
  tbody.querySelectorAll('input.owncell').forEach((inp) => {
    inp.addEventListener('change', () => {
      const g = byId(inp.dataset.id);
      const raw = inp.value.trim();
      const v = parseFloat(raw);
      if (raw === '' || isNaN(v)) {
        g.ownershipLocked = false;
        if (State.hasRealOwnership) {
          if (g._ownOrig != null) g.ownership = g._ownOrig;
        } else {
          window.Data.projectOwnership(State.golfers, State.simResults);
        }
      } else {
        if (g._ownOrig == null) g._ownOrig = g.ownership; // remember the pre-override value once
        g.ownershipLocked = true;
        g.ownership = Math.max(0, Math.min(100, v));
      }
      renderPlayers();
    });
  });
  // Player name → outcome distribution
  tbody.querySelectorAll('button.pname').forEach((b) => {
    b.addEventListener('click', () => openDist(b.dataset.id));
  });
  // Lock / ban toggles
  tbody.querySelectorAll('button.toggle').forEach((b) => {
    b.addEventListener('click', () => {
      const g = byId(b.dataset.id);
      g[b.dataset.t] = !g[b.dataset.t];
      if (g.locked && g.banned) g[b.dataset.t === 'locked' ? 'banned' : 'locked'] = false;
      renderPlayers();
    });
  });

  renderDkBanner();
}

/* ---------------------- Player outcome distribution ---------------------- */
function openDist(id) {
  const g = byId(id);
  const r = State.simResults && State.simResults.get(id);
  const body = $('#distBody');
  $('#distTitle').textContent = g.name;

  if (!r) {
    body.innerHTML = `<p class="hint">Run a simulation first to see ${g.name}'s range of outcomes.</p>`;
  } else {
    const s = r.samples;
    const n = s.length;
    let max = 0;
    for (let i = 0; i < n; i++) if (s[i] > max) max = s[i];
    const BINS = 28;
    const width = (max || 1) / BINS;
    const counts = new Array(BINS).fill(0);
    for (let i = 0; i < n; i++) counts[Math.min(BINS - 1, Math.floor(s[i] / width))]++;
    const cmax = Math.max(...counts) || 1;
    const bars = counts
      .map((c, i) => {
        const h = Math.round((c / cmax) * 100);
        const lo = Math.round(i * width);
        const hi = Math.round((i + 1) * width);
        return `<div class="distbar" title="${lo}–${hi} pts: ${((100 * c) / n).toFixed(1)}% of sims">
          <div class="distfill" style="height:${h}%"></div></div>`;
      })
      .join('');
    body.innerHTML = `
      <div class="diststats">
        <span>Proj <b>${num(r.mean)}</b></span>
        <span>Floor <b class="dim">${num(r.floor)}</b></span>
        <span>Ceiling <b class="up">${num(r.ceiling)}</b></span>
        <span>Top-1% <b class="up">${num(r.p99)}</b></span>
        <span>Make cut <b>${num(r.cutPct)}%</b></span>
      </div>
      <div class="distchart">${bars}</div>
      <div class="distaxis"><span>0</span><span>${Math.round(max)} pts</span></div>
      <p class="hint">Each bar is the share of ${n.toLocaleString()} simulated tournaments landing in that
      DK-point range. The left spike is missed-cut outcomes; the right hump is made-cut scoring — the
      average (${num(r.mean)}) often sits in the valley between, which is exactly why flat projections miss.</p>`;
  }
  $('#distModal').classList.remove('hidden');
}

function closeDist() {
  $('#distModal').classList.add('hidden');
}

/* ---------------------- Course fit (SG weighting) ---------------------- */
const CF_PRESETS = {
  balanced: { ott: 1, app: 1, arg: 1, putt: 1 },
  bomber: { ott: 1.6, app: 1.1, arg: 0.8, putt: 0.8 },
  approach: { ott: 0.9, app: 1.6, arg: 1.0, putt: 0.9 },
  short: { ott: 0.8, app: 1.0, arg: 1.4, putt: 1.4 },
};

function setCfInputs(w) {
  $('#cfOtt').value = w.ott;
  $('#cfApp').value = w.app;
  $('#cfArg').value = w.arg;
  $('#cfPutt').value = w.putt;
}

/**
 * Recompute each golfer's skill by re-weighting their SG components for this
 * week's course. Neutral weights (all 1) reproduce SG_TOT exactly; raising a
 * category emphasizes golfers strong in it (and de-emphasizes the rest), with
 * the overall scale held steady. Golfers without full SG splits are untouched.
 */
function applyCourseFit() {
  const w = {
    ott: parseFloat($('#cfOtt').value) || 0,
    app: parseFloat($('#cfApp').value) || 0,
    arg: parseFloat($('#cfArg').value) || 0,
    putt: parseFloat($('#cfPutt').value) || 0,
  };
  const wsum = w.ott + w.app + w.arg + w.putt;
  const scale = window.Data.SKILL_SCALE;
  let n = 0;
  for (const g of State.golfers) {
    if ([g.sgOtt, g.sgApp, g.sgArg, g.sgPutt].some((v) => v == null)) continue;
    const weighted = w.ott * g.sgOtt + w.app * g.sgApp + w.arg * g.sgArg + w.putt * g.sgPutt;
    // Normalize by mean weight so neutral weights => SG_TOT; emphasis redistributes.
    const eff = wsum > 0 ? (4 * weighted) / wsum : 0;
    g.skill = Math.round(eff * scale * 1000) / 1000;
    n++;
  }
  State.simResults = null; // skills changed — invalidate the sim
  renderPlayers();
  const isNeutral = wsum === 4 && w.ott === 1 && w.app === 1 && w.arg === 1 && w.putt === 1;
  $('#cfStatus').textContent = n
    ? `${isNeutral ? 'Reset to SG total' : 'Course fit applied'} for ${n} golfers — re-run the sim.`
    : 'No golfers have SG splits to weight (import a slate with SG_OTT/APP/ARG/PUTT).';
}

/**
 * Auto-set the cut toggle from field size. Signature / limited-field events
 * (e.g. the Travelers) have ~70-78 players and NO cut; full-field events run
 * 132-156 with a 36-hole cut. We flip the checkbox so the default is right,
 * but the user can always override it.
 */
function autoDetectCut() {
  const field = State.golfers.filter((g) => !g.notInSlate).length;
  const cutBox = $('#hasCut');
  if (!cutBox) return;
  cutBox.checked = field >= 100; // <100 golfers ⇒ no-cut Signature/limited field
}

/**
 * Shift one golfer's sim result (mean/floor/ceiling) to match a manual Proj
 * override, preserving the floor/ceiling spread. Uses the fresh snapshot
 * (g._projOrig, captured at sim-run time before any override) as the
 * baseline so repeated edits don't compound on top of a prior override.
 */
function applyProjOverrideToGolfer(g) {
  const r = State.simResults && State.simResults.get(g.id);
  if (!r || !g._projOrig) return;
  const delta = g.projOverride - g._projOrig.mean;
  r.mean = g.projOverride;
  r.floor = g._projOrig.floor + delta;
  r.ceiling = g._projOrig.ceiling + delta;
}

/** Snapshot fresh sim results, then re-apply any locked Proj overrides on top. */
function applyProjOverrides() {
  if (!State.simResults) return;
  for (const g of State.golfers) {
    const r = State.simResults.get(g.id);
    if (!r) continue;
    g._projOrig = { mean: r.mean, floor: r.floor, ceiling: r.ceiling };
    if (g.projLocked && g.projOverride != null) applyProjOverrideToGolfer(g);
  }
}

/* ---------------------- Run simulation ---------------------- */
function runSim() {
  const nSims = parseInt($('#nSims').value, 10);
  const seed = parseInt($('#seed').value, 10) || 12345;
  const status = $('#simStatus');
  status.textContent = 'Simulating…';

  // Defer so the status text paints before the heavy loop.
  const hasCut = $('#hasCut').checked;
  setTimeout(() => {
    const t0 = performance.now();
    State.simResults = window.Sim.runSimulation(State.golfers, nSims, seed, null, { hasCut });
    applyProjOverrides(); // re-apply any manual Proj overrides on top of the fresh sim
    // Keep the master file's real ownership; only model it for the sample slate.
    if (!State.hasRealOwnership) {
      window.Data.projectOwnership(State.golfers, State.simResults);
    }
    const ms = Math.round(performance.now() - t0);
    status.textContent = `✓ ${nSims.toLocaleString()} sims in ${ms} ms`;
    renderPlayers();
    renderHandBuild(); // surface fresh projected points in the hand builder
  }, 30);
}

/* ---------------------- Build pool ---------------------- */
function buildPool() {
  if (!State.simResults) {
    $('#buildStatus').textContent = 'Run a simulation first (tab 1).';
    return;
  }
  // Per-golfer exposure targets (entered as %, stored as 0..1 fractions).
  const maxExpById = new Map();
  const minExpById = new Map();
  for (const g of State.golfers) {
    if (g.maxExp != null) maxExpById.set(g.id, g.maxExp / 100);
    if (g.minExp != null) minExpById.set(g.id, g.minExp / 100);
  }

  const opts = {
    nLineups: parseInt($('#nLineups').value, 10) || 20,
    maxExposure: (parseFloat($('#maxExposure').value) || 100) / 100,
    maxExpById,
    minExpById,
    minSalary: parseInt($('#minSalary').value, 10) || 0,
    locks: new Set(State.golfers.filter((g) => g.locked).map((g) => g.id)),
    // Exclude banned, OUT/WD, deselected players, and anyone not in the DK field.
    bans: new Set(State.golfers.filter((g) => g.banned || g.out || g.notInSlate || !g.selected).map((g) => g.id)),
  };

  $('#buildStatus').textContent = 'Building…';
  setTimeout(() => {
    const t0 = performance.now();
    State.build = window.Optimizer.buildPool(State.golfers, State.simResults, opts);
    State.contest = null; // pool changed; previous ROI no longer valid

    // Re-sort the pool per the chosen objective.
    const key = $('#sortBy').value;
    State.build.lineups.sort((a, b) => b[key] - a[key]);

    const ms = Math.round(performance.now() - t0);
    const n = State.build.lineups.length;
    // Best-effort min-exposure: flag any floors we couldn't reach.
    const miss = State.golfers.filter(
      (g) => g.minExp != null && (State.build.exposure.get(g.id) || 0) * 100 < g.minExp - 0.5
    );
    let msg = `✓ ${n} lineups in ${ms} ms`;
    if (miss.length) {
      msg += ` — couldn't reach min exposure for ${miss.map((g) => g.name).join(', ')}`;
    }
    $('#buildStatus').textContent = msg;
    renderPlayers(); // fill the Exp% column
    renderBuildSummary();
    renderReview();
  }, 30);
}

function renderBuildSummary() {
  const lus = State.build.lineups;
  if (!lus.length) {
    $('#buildSummary').innerHTML = '<p class="hint">No valid lineups — loosen your locks/min-salary.</p>';
    return;
  }
  const avg = (f) => lus.reduce((s, l) => s + l[f], 0) / lus.length;
  const cards = [
    ['Lineups', lus.length],
    ['Avg Sim Score', num(avg('score'))],
    ['Avg projection', num(avg('mean'))],
    ['Avg ceiling', num(avg('ceiling'))],
    ['Best ceiling', num(Math.max(...lus.map((l) => l.ceiling)))],
    ['Avg salary', money(avg('salary'))],
  ];
  $('#buildSummary').innerHTML = cards
    .map(([k, v]) => `<div class="card"><div class="cardv">${v}</div><div class="cardk">${k}</div></div>`)
    .join('');
}

/* ---------------------- Contest sim / ROI ---------------------- */
/** Load real DK contests (with exact payout tiers) into the picker. */
async function loadDkContests() {
  try {
    const res = await fetch('data/dk_contests.json?t=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) return;
    const doc = await res.json();
    State.dkContests = doc.contests || [];
    const sel = $('#cDkContest');
    State.dkContests.forEach((c, i) => {
      const opt = document.createElement('option');
      opt.value = String(i);
      const fee = c.fee != null ? `$${c.fee}` : '';
      opt.textContent = `${c.name} — ${fee}, ${(c.entries || 0).toLocaleString()} entries`;
      sel.appendChild(opt);
    });
  } catch (e) {
    /* no contests file yet */
  }
}

function selectedDkContest() {
  const v = $('#cDkContest').value;
  if (v === '' || !State.dkContests) return null;
  return State.dkContests[parseInt(v, 10)] || null;
}

function runContest() {
  const status = $('#contestStatus');
  if (!State.build || !State.build.lineups.length) {
    status.textContent = 'Build a lineup pool first (tab 2).';
    return;
  }
  const real = selectedDkContest();
  const fee = real ? real.fee : parseFloat($('#cFee').value) || 1;
  const opts = {
    entries: real ? real.entries : parseInt($('#cEntries').value, 10) || 1000,
    fee,
    structure: $('#cStructure').value,
    tiers: real ? real.tiers : null, // exact DK payouts when a contest is picked
    fieldLineups: parseInt($('#cField').value, 10) || 2000,
    worlds: 4000,
    exclude: new Set(State.golfers.filter((g) => g.banned || g.out || g.notInSlate || !g.selected).map((g) => g.id)),
    rng: window.Sim.makeRng(424242),
  };
  status.textContent = 'Simulating contest…';
  setTimeout(() => {
    const t0 = performance.now();
    State.contest = window.Contest.runContestSim(State.build.lineups, State.golfers, State.simResults, opts);
    State.contest.fee = fee;
    State.contest.payoutSource = real ? `exact DK payouts — ${real.name}` : 'modeled payouts';
    const ms = Math.round(performance.now() - t0);
    status.textContent =
      `✓ ${State.contest.results.length} lineups vs ${State.contest.fieldSize.toLocaleString()}-lineup field, ${State.contest.payoutSource} (${ms} ms)`;
    renderContest();
  }, 30);
}

function renderContest() {
  const c = State.contest;
  if (!c) return;
  const res = [...c.results].sort((a, b) => b.roi - a.roi);
  const fee = c.fee || 1;
  const avgRoi = res.reduce((s, r) => s + r.roi, 0) / res.length;
  const avgCash = res.reduce((s, r) => s + r.cashPct, 0) / res.length;
  const totalProfit = res.reduce((s, r) => s + r.expPay, 0) - res.length * fee;

  $('#contestSummary').innerHTML = [
    ['Avg ROI', avgRoi.toFixed(0) + '%'],
    ['Best ROI', Math.max(...res.map((r) => r.roi)).toFixed(0) + '%'],
    ['Avg cash%', avgCash.toFixed(1) + '%'],
    ['Field sampled', c.fieldSize.toLocaleString()],
    [`Exp. profit (${res.length}×$${fee})`, '$' + totalProfit.toFixed(0)],
  ]
    .map(([k, v]) => `<div class="card"><div class="cardv">${v}</div><div class="cardk">${k}</div></div>`)
    .join('');

  $('#contestTable tbody').innerHTML = res
    .map((r, i) => {
      const names = r.players
        .map((id) => byId(id))
        .sort((a, b) => b.salary - a.salary)
        .map((g) => `<span class="chip">${g.name} <em>${(g.salary / 1000).toFixed(1)}k</em></span>`)
        .join('');
      const cls = r.roi >= 0 ? 'up' : 'down';
      const sign = r.roi >= 0 ? '+' : '';
      return `<tr>
        <td>#${i + 1}</td>
        <td><div class="chips">${names}</div></td>
        <td class="num">${num(r.avgPts)}</td>
        <td class="num ${cls}">${sign}${r.roi.toFixed(0)}%</td>
        <td class="num">${r.cashPct.toFixed(1)}%</td>
        <td class="num">${r.winPct.toFixed(2)}%</td>
        <td class="num">$${r.expPay.toFixed(2)}</td>
      </tr>`;
    })
    .join('');
}

/* ---------------------- Review: leverage + lineups ---------------------- */
function renderReview() {
  if (!State.build) return;
  const exp = State.build.exposure;

  // Leverage table — every golfer that appears, sorted by leverage.
  const rows = State.golfers
    .map((g) => {
      const myExp = (exp.get(g.id) || 0) * 100;
      const own = g.ownership || 0;
      return { g, myExp, own, lev: myExp - own };
    })
    .filter((r) => r.myExp > 0)
    .sort((a, b) => b.lev - a.lev);

  const tbody = $('#exposureTable tbody');
  tbody.innerHTML = rows
    .map((r) => {
      const cls = r.lev >= 0 ? 'up' : 'down';
      const sign = r.lev >= 0 ? '+' : '';
      return `<tr>
        <td class="name">${r.g.name}</td>
        <td class="num dim">${r.own.toFixed(1)}%</td>
        <td class="num">${r.myExp.toFixed(1)}%</td>
        <td class="num ${cls}">${sign}${r.lev.toFixed(1)}</td>
      </tr>`;
    })
    .join('');

  // Lineup cards — vertical: each golfer stacked with salary / ownership / fpts,
  // totals in the footer, plus a one-tap Save button.
  $('#poolCount').textContent = `— ${State.build.lineups.length} lineups`;
  const list = $('#lineupList');
  list.innerHTML = State.build.lineups
    .map((lu, i) => {
      const players = lu.players.map(byId).sort((a, b) => b.salary - a.salary);
      let totOwn = 0;
      let totProj = 0;
      const rows = players
        .map((g) => {
          const fp = projOf(g);
          totOwn += g.ownership || 0;
          if (fp != null) totProj += fp;
          return `<tr>
            <td class="hn">${g.name}</td>
            <td class="num">${money(g.salary)}</td>
            <td class="num dim">${g.ownership != null ? g.ownership.toFixed(1) : '—'}</td>
            <td class="num">${fp != null ? fp.toFixed(1) : '—'}</td>
          </tr>`;
        })
        .join('');
      return `<div class="lineup">
        <div class="lhead">
          <span class="lnum">#${i + 1}</span>
          <span class="lstat">Score <b class="up">${num(lu.score)}</b></span>
          <span class="lstat">Ceil <b>${num(lu.ceiling)}</b></span>
          <button class="savelu" data-lu="${i}" title="Save to your saved lineups">＋ Save</button>
        </div>
        <table class="lut">
          <thead><tr><th>Golfer</th><th class="num">Sal</th><th class="num">Own</th><th class="num">Fpts</th></tr></thead>
          <tbody>${rows}</tbody>
          <tfoot><tr>
            <td>Total</td>
            <td class="num">${money(lu.salary)}</td>
            <td class="num">${totOwn.toFixed(0)}%</td>
            <td class="num">${totProj ? totProj.toFixed(1) : num(lu.mean)}</td>
          </tr></tfoot>
        </table>
      </div>`;
    })
    .join('');

  $$('#lineupList .savelu').forEach((btn) => {
    btn.addEventListener('click', () => {
      const lu = State.build.lineups[+btn.dataset.lu];
      saveLineup(lu.players.map(byId), 'pool');
      btn.textContent = '✓ Saved';
      btn.classList.add('saved');
    });
  });
}

/* ---------------------- Hand build (manual single lineup) ---------------------- */
/** Golfers available to roster: in this week's field and not OUT/WD. */
function rosterableGolfers() {
  return State.golfers
    .filter((g) => !g.notInSlate && !g.out)
    .sort((a, b) => b.salary - a.salary);
}

function handPlayers() {
  return State.hand.ids.map(byId).filter(Boolean);
}

function addToHand(id) {
  const h = State.hand;
  if (h.ids.includes(id) || h.ids.length >= ROSTER_SIZE) return;
  const g = byId(id);
  const used = handPlayers().reduce((s, x) => s + x.salary, 0);
  if (used + g.salary > SALARY_CAP) return; // would blow the cap
  h.ids.push(id);
  renderHandBuild();
}

function removeFromHand(id) {
  State.hand.ids = State.hand.ids.filter((x) => x !== id);
  renderHandBuild();
}

function clearHand() {
  State.hand.ids = [];
  renderHandBuild();
}

/** Re-draw the hand-build summary, current lineup, and the add-pool table. */
function renderHandBuild() {
  if (!$('#handLineup')) return; // tab not in DOM
  const players = handPlayers();
  const used = players.reduce((s, g) => s + g.salary, 0);
  const remaining = SALARY_CAP - used;
  const spotsLeft = ROSTER_SIZE - players.length;
  const totProj = players.reduce((s, g) => s + (projOf(g) || 0), 0);
  const totOwn = players.reduce((s, g) => s + (g.ownership || 0), 0);
  const perRemain = spotsLeft > 0 ? Math.floor(remaining / spotsLeft) : 0;

  // Summary cards
  $('#handSummary').innerHTML = [
    [`${players.length} / ${ROSTER_SIZE}`, 'Golfers'],
    [money(remaining), 'Salary left'],
    [spotsLeft > 0 ? money(perRemain) : '—', 'Avg / spot left'],
    [totProj ? totProj.toFixed(1) : '—', 'Proj pts'],
    [totOwn ? totOwn.toFixed(0) + '%' : '—', 'Total own'],
  ]
    .map(([v, k]) => `<div class="card"><div class="cardv">${v}</div><div class="cardk">${k}</div></div>`)
    .join('');
  $('#handSpots').textContent = `— ${players.length} / ${ROSTER_SIZE} · ${money(remaining)} left`;

  // Current lineup (filled + empty slots)
  const slots = players
    .sort((a, b) => b.salary - a.salary)
    .map((g) => {
      const fp = projOf(g);
      return `<div class="hbslot">
        <span>${g.name}</span>
        <span class="hbsal">${money(g.salary)}</span>
        <span class="hbsal">${fp != null ? fp.toFixed(1) + ' pts' : '—'}</span>
        <button class="rm" data-id="${g.id}">Remove</button>
      </div>`;
    });
  for (let i = players.length; i < ROSTER_SIZE; i++) {
    slots.push(`<div class="hbslot empty"><span>Empty slot ${i + 1}</span><span></span><span></span><span></span></div>`);
  }
  $('#handLineup').innerHTML = slots.join('');

  // Save button enabled only with a legal full lineup.
  const saveBtn = $('#handSave');
  saveBtn.disabled = !(players.length === ROSTER_SIZE && used <= SALARY_CAP);

  // Add-pool table
  const inLineup = new Set(State.hand.ids);
  $('#handPool tbody').innerHTML = rosterableGolfers()
    .map((g) => {
      const fp = projOf(g);
      const full = players.length >= ROSTER_SIZE;
      const overCap = used + g.salary > SALARY_CAP;
      const has = inLineup.has(g.id);
      const disabled = has || full || overCap;
      const label = has ? 'Added' : overCap ? 'Over cap' : 'Add';
      return `<tr class="${has ? 'inlineup' : ''}">
        <td class="name">${g.name}${g.out ? ' <span class="tag out">OUT</span>' : ''}</td>
        <td class="num">${money(g.salary)}</td>
        <td class="num dim">${g.ownership != null ? g.ownership.toFixed(1) : '—'}</td>
        <td class="num">${fp != null ? fp.toFixed(1) : '—'}</td>
        <td class="ctr"><button class="addbtn" data-id="${g.id}" ${disabled ? 'disabled' : ''}>${label}</button></td>
      </tr>`;
    })
    .join('');

  $$('#handPool .addbtn').forEach((b) =>
    b.addEventListener('click', () => addToHand(b.dataset.id))
  );
  $$('#handLineup .rm').forEach((b) =>
    b.addEventListener('click', () => removeFromHand(b.dataset.id))
  );
}

/* ---------------------- Saved lineups (localStorage) ---------------------- */
function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(SAVED_KEY)) || [];
  } catch (e) {
    return [];
  }
}

function persistSaved(arr) {
  try {
    localStorage.setItem(SAVED_KEY, JSON.stringify(arr));
  } catch (e) {
    /* storage full / disabled — non-fatal */
  }
}

/** Save a lineup (array of golfer objects) to localStorage. */
function saveLineup(golfers, source) {
  const arr = loadSaved();
  arr.unshift({
    ts: Date.now(),
    source: source || 'hand',
    salary: golfers.reduce((s, g) => s + g.salary, 0),
    players: golfers
      .slice()
      .sort((a, b) => b.salary - a.salary)
      .map((g) => ({ id: g.id, name: g.name, salary: g.salary })),
  });
  persistSaved(arr);
  renderSaved();
}

function removeSaved(ts) {
  persistSaved(loadSaved().filter((l) => l.ts !== ts));
  renderSaved();
}

function clearSaved() {
  if (!loadSaved().length) return;
  if (!window.confirm('Delete all saved lineups?')) return;
  persistSaved([]);
  renderSaved();
}

function renderSaved() {
  const wrap = $('#savedList');
  if (!wrap) return;
  const saved = loadSaved();
  $('#savedCount').textContent = saved.length ? `— ${saved.length}` : '';
  if (!saved.length) {
    wrap.innerHTML = `<div class="hbslot empty"><span>No saved lineups yet — build one and hit Save.</span></div>`;
    return;
  }
  wrap.innerHTML = saved
    .map((l) => {
      const when = new Date(l.ts).toLocaleString();
      const names = l.players.map((p) => p.name).join(', ');
      return `<div class="hbslot savedcard">
        <div class="savedmeta">
          <span>${money(l.salary)}</span>
          <span>${l.source === 'pool' ? 'from pool' : 'hand built'}</span>
          <span>${when}</span>
          <button class="rm" data-ts="${l.ts}">✕</button>
        </div>
        <div class="savednames">${names}</div>
      </div>`;
    })
    .join('');
  $$('#savedList .rm').forEach((b) =>
    b.addEventListener('click', () => removeSaved(+b.dataset.ts))
  );
}

/** Export all saved lineups as a DraftKings upload CSV. */
function exportSaved() {
  const saved = loadSaved();
  if (!saved.length) {
    $('#exportPreview').textContent = 'No saved lineups to export.';
    return;
  }
  const header = 'G,G,G,G,G,G';
  const lines = saved.map((l) =>
    l.players
      .map((p) => {
        const g = byId(p.id);
        return (g && dkEntryName(g)) || p.name;
      })
      .join(',')
  );
  download('birdie_saved_lineups.csv', [header, ...lines].join('\n'));
}

/* ---------------------- Accuracy page (predicted vs. actual ownership) ---------------------- */
let _accLoaded = false;

/** Parse a 'M/D/YY' date for sorting; returns a comparable number (or 0). */
function parseEventDate(s) {
  const m = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec((s || '').trim());
  if (!m) return 0;
  let [, mo, d, y] = m;
  y = y.length === 2 ? '20' + y : y;
  return new Date(+y, +mo - 1, +d).getTime() || 0;
}

/** Fetch data/history/index.json once and render the MAE trend + table. */
async function renderAccuracy() {
  if (_accLoaded) return; // single fetch; cheap and avoids re-hitting on every tab open
  _accLoaded = true;
  const chart = $('#accChart');
  const axis = $('#accAxis');
  const tbody = $('#accTable tbody');
  const summary = $('#accSummary');
  try {
    const res = await fetch('data/history/index.json?t=' + Date.now(), { cache: 'no-store' });
    if (!res.ok) throw new Error('no history yet (' + res.status + ')');
    const doc = await res.json();
    const events = (doc.events || []).slice().sort(
      (a, b) => parseEventDate(a.date) - parseEventDate(b.date)
    );
    const scored = events.filter((e) => e.maePct != null);
    const headToHead = scored.filter((e) => e.colabMaePct != null);

    // Summary cards
    const avgOf = (arr, f) => (arr.length ? arr.reduce((s, e) => s + f(e), 0) / arr.length : null);
    const avg = avgOf(scored, (e) => e.maePct);
    const avgColab = avgOf(headToHead, (e) => e.colabMaePct);
    const webWins = headToHead.filter((e) => e.maePct < e.colabMaePct).length;
    const cards = [
      [events.length, 'Events archived'],
      [scored.length, 'With results'],
      [avg != null ? avg.toFixed(2) : '—', 'Website avg MAE'],
    ];
    if (headToHead.length) {
      cards.push([avgColab != null ? avgColab.toFixed(2) : '—', 'Your Colab avg MAE']);
      cards.push([`${webWins}–${headToHead.length - webWins}`, 'Website–Colab record']);
    } else {
      const best = scored.length ? Math.min(...scored.map((e) => e.maePct)) : null;
      cards.push([best != null ? best.toFixed(2) : '—', 'Best MAE (pts)']);
    }
    summary.innerHTML = cards
      .map(([v, k]) => `<div class="card"><div class="cardv">${v}</div><div class="cardk">${k}</div></div>`)
      .join('');

    // Bar chart of MAE per scored event (shorter bar = sharper). We invert the
    // height so a LOWER MAE shows as a TALLER (better) bar.
    if (scored.length) {
      const maxMae = Math.max(...scored.map((e) => e.maePct), 0.1);
      chart.innerHTML = scored
        .map((e) => {
          const h = Math.max(4, (1 - e.maePct / (maxMae * 1.15)) * 100);
          return `<div class="distbar" title="${e.tournament}: ${e.maePct.toFixed(2)} pts MAE">
            <div class="distfill" style="height:${h}%"></div></div>`;
        })
        .join('');
      axis.innerHTML = `<span>← earlier</span><span>taller = sharper (lower MAE)</span><span>latest →</span>`;
    } else {
      chart.innerHTML = `<div class="hint" style="margin:auto">No results yet — add Actual_Ownership to your Data tab and the chart fills in after the next sync.</div>`;
      axis.innerHTML = '';
    }

    // Table (newest first) — website MAE vs your Colab MAE, head to head.
    tbody.innerHTML = events
      .slice()
      .reverse()
      .map((e) => {
        let winner;
        if (!e.hasActual) {
          winner = '<span class="tag noproj">pending</span>';
        } else if (e.maePct != null && e.colabMaePct != null) {
          const webBetter = e.maePct < e.colabMaePct;
          const tie = e.maePct === e.colabMaePct;
          winner = tie
            ? '<span class="dim">tie</span>'
            : `<span class="up">${webBetter ? 'Website' : 'Colab'}</span>`;
        } else {
          winner = '<span class="tag" style="background:#11241a;color:var(--green2);border:1px solid #1c3b29">scored</span>';
        }
        const lower = e.maePct != null && e.colabMaePct != null;
        const webCls = lower && e.maePct < e.colabMaePct ? 'up' : '';
        const colCls = lower && e.colabMaePct < e.maePct ? 'up' : '';
        return `<tr>
          <td class="name">${e.tournament}</td>
          <td class="num dim">${e.date || '—'}</td>
          <td class="num ${webCls}">${e.maePct != null ? e.maePct.toFixed(2) : '—'}</td>
          <td class="num ${colCls}">${e.colabMaePct != null ? e.colabMaePct.toFixed(2) : '—'}</td>
          <td class="num">${winner}</td>
        </tr>`;
      })
      .join('');
  } catch (e) {
    summary.innerHTML = '';
    chart.innerHTML = '';
    axis.innerHTML = '';
    tbody.innerHTML = `<tr><td colspan="5" class="dim">No history archived yet — it builds automatically after each sync. (${e.message})</td></tr>`;
  }
}

/* ---------------------- CSV import (DraftKings salaries) ---------------------- */
function importCsv(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const records = parseDkSalaries(reader.result);
      if (!records.length) throw new Error('No rows parsed');
      const { golfers, hasOwnership } = window.Data.buildSlateFromMaster(records);
      State.golfers = golfers;
      State.hand.ids = []; // new slate — clear any in-progress hand lineup
      State.simResults = null;
      State.build = null;
      State.hasRealOwnership = hasOwnership;
      if (!hasOwnership) window.Data.projectOwnership(State.golfers, null);
      renderPlayers();
      $('#simStatus').textContent = `Imported ${golfers.length} golfers — run the sim.`;
    } catch (e) {
      $('#simStatus').textContent = 'Import failed: ' + e.message;
    }
  };
  reader.readAsText(file);
}

/**
 * Parse a DraftKings "DKSalaries" CSV. We look for Name + Salary columns
 * and derive a starting skill estimate from salary (you can tune inline).
 * Accepts an optional "AvgPointsPerGame" column to seed skill more accurately.
 */
function parseDkSalaries(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const header = splitCsvLine(lines[0]).map((h) => h.trim().toLowerCase());
  const nameIdx = header.findIndex((h) => h === 'name' || h === 'name + id');
  const salIdx = header.findIndex((h) => h === 'salary');
  const avgIdx = header.findIndex((h) => h.includes('avgpoints'));
  // Master-file columns (if you import a CSV exported from Sheet1).
  const sgIdx = header.findIndex((h) => h === 'sg_tot' || h === 'sg_total');
  const ownIdx = header.findIndex(
    (h) => h === 'predicted_ownership_pct' || h === 'ownership' || h === 'own%'
  );
  if (nameIdx < 0 || salIdx < 0) throw new Error('need Name and Salary columns');

  const num = (v) => {
    const n = parseFloat((v || '').toString().replace(/[^0-9.\-]/g, ''));
    return Number.isFinite(n) ? n : null;
  };

  const records = [];
  for (let i = 1; i < lines.length; i++) {
    const c = splitCsvLine(lines[i]);
    const name = (c[nameIdx] || '').replace(/\s*\(\d+\)\s*$/, '').trim();
    const salary = parseInt((c[salIdx] || '').replace(/[^0-9]/g, ''), 10);
    if (!name || !salary) continue;
    const rec = { name, salary, variance: 0.8 };
    if (sgIdx >= 0 && num(c[sgIdx]) != null) {
      rec.sgTot = num(c[sgIdx]); // real strokes-gained drives skill
    } else if (avgIdx >= 0 && c[avgIdx]) {
      // Map avg DK points (~60-95) to skill roughly centered at 0.6.
      rec.skill = Math.max(0.1, (parseFloat(c[avgIdx]) - 60) / 25);
    } // else buildSlateFromMaster falls back to salary-implied skill
    if (ownIdx >= 0 && num(c[ownIdx]) != null) rec.ownership = num(c[ownIdx]);
    records.push(rec);
  }
  return records;
}

// Minimal CSV splitter that respects quoted fields.
function splitCsvLine(line) {
  const out = [];
  let cur = '', q = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') q = !q;
    else if (ch === ',' && !q) { out.push(cur); cur = ''; }
    else cur += ch;
  }
  out.push(cur);
  return out;
}

/* ---------------------- CSV export ---------------------- */
/** Lineups ordered for assignment: by contest ROI if available, else Sim Score. */
function orderedLineups() {
  const lus = State.build.lineups;
  if (State.contest && State.contest.results) {
    const roi = new Map(State.contest.results.map((r) => [r.players.join('|'), r.roi]));
    return [...lus].sort((a, b) => (roi.get(b.players.join('|')) || 0) - (roi.get(a.players.join('|')) || 0));
  }
  return [...lus].sort((a, b) => b.score - a.score);
}

function exportDk() {
  if (!State.build || !State.build.lineups.length) {
    $('#exportPreview').textContent = 'Build a pool first.';
    return;
  }
  // DraftKings PGA upload: 6 golfer slots as "Name (ID)".
  const header = ['G', 'G', 'G', 'G', 'G', 'G'];
  let missing = 0;
  const rows = State.build.lineups.map((lu) =>
    lu.players
      .map((id) => byId(id))
      .sort((a, b) => b.salary - a.salary)
      .map((g) => {
        const e = dkEntryName(g);
        if (!e) missing++;
        return e || g.name;
      })
  );
  const csv = [header.join(','), ...rows.map((r) => r.join(','))].join('\n');
  download('draftkings_pga_upload.csv', csv);
  const note = missing
    ? `\n⚠ ${missing} slot(s) lack a DK ID — run the DK sync so names map to IDs.`
    : '\n✓ All golfers resolved to DK IDs.';
  $('#exportPreview').textContent =
    csv.split('\n').slice(0, 8).join('\n') +
    (rows.length > 7 ? `\n… (${rows.length} lineups)` : '') + note;
}

/**
 * Fill a DraftKings entries template: assign a unique best lineup to each entry
 * row (by contest ROI if a contest sim was run, else Sim Score) and write the
 * 6 golfer columns as "Name (ID)". Keeps every other column untouched.
 */
function fillEntries(file) {
  if (!State.build || !State.build.lineups.length) {
    $('#exportPreview').textContent = 'Build a pool first.';
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const lines = reader.result.split(/\r?\n/).filter((l) => l.trim().length);
      const header = splitCsvLine(lines[0]);
      const gCols = [];
      header.forEach((h, i) => { if (h.trim().toUpperCase() === 'G') gCols.push(i); });
      if (gCols.length < 6) throw new Error('template needs 6 "G" columns (found ' + gCols.length + ')');

      const lus = orderedLineups();
      const toSlots = (lu) =>
        lu.players
          .map((id) => byId(id))
          .sort((a, b) => b.salary - a.salary)
          .map((g) => dkEntryName(g) || g.name);

      let assigned = 0;
      let reused = 0;
      const out = [header.join(',')];
      for (let r = 1; r < lines.length; r++) {
        const cells = splitCsvLine(lines[r]);
        while (cells.length < header.length) cells.push('');
        const lu = lus[assigned % lus.length];
        if (assigned >= lus.length) reused++;
        const slots = toSlots(lu);
        gCols.forEach((ci, k) => { cells[ci] = slots[k] != null ? slots[k] : ''; });
        out.push(cells.map((c) => (/[",]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(','));
        assigned++;
      }

      download('draftkings_entries_filled.csv', out.join('\n'));
      let note = `✓ Filled ${assigned} entries from ${lus.length} lineups`;
      note += State.contest ? ' (ranked by contest ROI).' : ' (ranked by Sim Score).';
      if (reused) note += ` ⚠ ${reused} entries reused lineups (more entries than unique lineups — build more).`;
      $('#exportPreview').textContent = note + '\n' + out.slice(0, 6).join('\n');
    } catch (e) {
      $('#exportPreview').textContent = 'Entries fill failed: ' + e.message;
    }
  };
  reader.readAsText(file);
}

function exportDetailed() {
  if (!State.build || !State.build.lineups.length) {
    $('#exportPreview').textContent = 'Build a pool first.';
    return;
  }
  const header = ['Lineup', 'Salary', 'Proj', 'Floor', 'Ceiling', 'P99', 'Golfers'];
  const rows = State.build.lineups.map((lu, i) => {
    const names = lu.players
      .map((id) => byId(id).name)
      .join('; ');
    return [i + 1, lu.salary, num(lu.mean), num(lu.floor), num(lu.ceiling), num(lu.p99), `"${names}"`].join(',');
  });
  const csv = [header.join(','), ...rows].join('\n');
  download('birdie_pool_detailed.csv', csv);
  $('#exportPreview').textContent = csv.split('\n').slice(0, 8).join('\n');
}

function download(filename, text) {
  const blob = new Blob([text], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------------------- Boot ---------------------- */
function init() {
  initTabs();
  loadAutoSlate();
  $('#runSim').addEventListener('click', runSim);
  $('#buildBtn').addEventListener('click', buildPool);
  $('#runContest').addEventListener('click', runContest);
  loadDkContests();
  $('#cDkContest').addEventListener('change', () => {
    const real = selectedDkContest();
    const fee = $('#cFee');
    const entries = $('#cEntries');
    if (real) {
      fee.value = real.fee;
      entries.value = real.entries;
      fee.disabled = true;
      entries.disabled = true;
      $('#cStructure').disabled = true;
    } else {
      fee.disabled = false;
      entries.disabled = false;
      $('#cStructure').disabled = false;
    }
  });
  $('#cfApply').addEventListener('click', applyCourseFit);
  $('#cfPreset').addEventListener('change', (e) => {
    const p = CF_PRESETS[e.target.value];
    if (p) setCfInputs(p);
  });
  ['#cfOtt', '#cfApp', '#cfArg', '#cfPutt'].forEach((id) => {
    $(id).addEventListener('input', () => { $('#cfPreset').value = 'custom'; });
  });
  $('#resetSlate').addEventListener('click', loadSampleSlate);
  $('#selAll').addEventListener('change', (e) => {
    const on = e.target.checked;
    State.golfers.forEach((g) => { if (!g.notInSlate) g.selected = on; });
    renderPlayers();
  });
  $('#distClose').addEventListener('click', closeDist);
  $('#distModal').addEventListener('click', (e) => {
    if (e.target.id === 'distModal') closeDist(); // click backdrop to close
  });
  $('#exportDK').addEventListener('click', exportDk);
  $('#exportDetailed').addEventListener('click', exportDetailed);
  $('#entriesFile').addEventListener('change', (e) => {
    if (e.target.files[0]) fillEntries(e.target.files[0]);
  });
  $('#importCsv').addEventListener('change', (e) => {
    if (e.target.files[0]) importCsv(e.target.files[0]);
  });
  // Sortable player-table headers: click to sort, click again to reverse.
  $$('#playerTable thead th[data-sort]').forEach((th) => {
    th.classList.add('sortable');
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (State.sort.key === key) State.sort.dir *= -1;
      else State.sort = { key, dir: key === 'name' ? 1 : -1 };
      renderPlayers();
    });
  });
  // Hand build + saved lineups
  $('#handSave').addEventListener('click', () => {
    const players = handPlayers();
    if (players.length !== ROSTER_SIZE) return;
    saveLineup(players, 'hand');
    clearHand();
  });
  $('#handClear').addEventListener('click', clearHand);
  $('#savedExport').addEventListener('click', exportSaved);
  $('#savedClear').addEventListener('click', clearSaved);
  renderSaved();
}

document.addEventListener('DOMContentLoaded', init);
