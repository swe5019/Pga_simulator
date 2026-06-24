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
  filters: {},             // active pool filters (see passesFilter)
};

/**
 * Pool filters. A golfer is "in the pool" when it clears every active threshold.
 * Locked golfers always stay in (an explicit lock beats a filter). Missing data
 * (e.g. no SG_T2G) fails a threshold that needs it, so set only filters your
 * data supports.
 */
function passesFilter(g) {
  const f = State.filters;
  if (g.locked) return true;
  if (f.minSalary != null && !(g.salary >= f.minSalary)) return false;
  if (f.maxSalary != null && !(g.salary <= f.maxSalary)) return false;
  if (f.minT2G != null && !(g.sgT2g != null && g.sgT2g >= f.minT2G)) return false;
  if (f.minTot != null && !(g.sgTot != null && g.sgTot >= f.minTot)) return false;
  if (f.maxOwn != null && !(g.ownership != null && g.ownership <= f.maxOwn)) return false;
  return true;
}

/** A golfer is excluded from sim/build if banned or filtered out of the pool. */
function inPool(g) {
  return !g.banned && passesFilter(g);
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const byId = (id) => State.golfers.find((g) => g.id === id);
const money = (n) => '$' + Math.round(n).toLocaleString();
const pct = (n) => (n == null ? '—' : n.toFixed(1) + '%');
const num = (n) => (n == null ? '—' : n.toFixed(1));

/* ---------------------- Tabs ---------------------- */
function initTabs() {
  $$('.tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach((b) => b.classList.remove('active'));
      $$('.panel').forEach((p) => p.classList.remove('active'));
      btn.classList.add('active');
      $('#' + btn.dataset.tab).classList.add('active');
    });
  });
}

/* ---------------------- Slate setup ---------------------- */
function loadSampleSlate() {
  State.golfers = window.Data.buildSlate(window.Data.SAMPLE_SLATE);
  State.simResults = null;
  State.build = null;
  State.hasRealOwnership = false;
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
    State.simResults = null;
    State.build = null;
    State.hasRealOwnership = hasOwnership;
    // Only model ownership if the file didn't supply real projections.
    if (!hasOwnership) window.Data.projectOwnership(State.golfers, null);
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
  const sorted = [...State.golfers].sort((a, b) => b.salary - a.salary);

  for (const g of sorted) {
    const r = State.simResults ? State.simResults.get(g.id) : null;
    const proj = r ? r.mean : null;
    const value = proj != null ? proj / (g.salary / 1000) : null;

    const tr = document.createElement('tr');
    if (g.banned) tr.classList.add('banned');
    if (g.locked) tr.classList.add('locked');
    if (!g.banned && !passesFilter(g)) tr.classList.add('filtered');
    tr.innerHTML = `
      <td class="name">${g.name}</td>
      <td class="num"><input class="cell" data-id="${g.id}" data-f="salary" value="${g.salary}"></td>
      <td class="num"><input class="cell" data-id="${g.id}" data-f="skill" value="${g.skill}"></td>
      <td class="num">${num(proj)}</td>
      <td class="num dim">${r ? num(r.floor) : '—'}</td>
      <td class="num up">${r ? num(r.ceiling) : '—'}</td>
      <td class="num">${r ? num(r.cutPct) : '—'}</td>
      <td class="num">${pct(g.ownership)}</td>
      <td class="num">${value != null ? value.toFixed(2) : '—'}</td>
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
  // Lock / ban toggles
  tbody.querySelectorAll('button.toggle').forEach((b) => {
    b.addEventListener('click', () => {
      const g = byId(b.dataset.id);
      g[b.dataset.t] = !g[b.dataset.t];
      if (g.locked && g.banned) g[b.dataset.t === 'locked' ? 'banned' : 'locked'] = false;
      renderPlayers();
    });
  });

  updatePoolStat();
}

/* ---------------------- Pool filters ---------------------- */
function updatePoolStat() {
  const total = State.golfers.length;
  const kept = State.golfers.filter(inPool).length;
  const el = $('#poolStat');
  if (!el) return;
  const active = Object.keys(State.filters).length > 0;
  el.textContent = total ? `Pool: ${kept} of ${total} golfers${active ? '' : ' (no filters)'}` : '';
}

function readFilters() {
  const val = (id) => {
    const v = parseFloat($(id).value);
    return Number.isFinite(v) ? v : null;
  };
  const f = {
    minSalary: val('#fMinSalary'),
    maxSalary: val('#fMaxSalary'),
    minT2G: val('#fMinT2G'),
    minTot: val('#fMinTot'),
    maxOwn: val('#fMaxOwn'),
  };
  // Keep only the thresholds actually set, so updatePoolStat can tell if any are active.
  State.filters = Object.fromEntries(Object.entries(f).filter(([, v]) => v != null));
}

function applyFilters() {
  readFilters();
  renderPlayers();
}

function clearFilters() {
  ['#fMinSalary', '#fMaxSalary', '#fMinT2G', '#fMinTot', '#fMaxOwn'].forEach((id) => {
    $(id).value = '';
  });
  State.filters = {};
  renderPlayers();
}

/* ---------------------- Run simulation ---------------------- */
function runSim() {
  const nSims = parseInt($('#nSims').value, 10);
  const seed = parseInt($('#seed').value, 10) || 12345;
  const status = $('#simStatus');
  status.textContent = 'Simulating…';

  // Defer so the status text paints before the heavy loop.
  setTimeout(() => {
    const t0 = performance.now();
    State.simResults = window.Sim.runSimulation(State.golfers, nSims, seed);
    // Keep the master file's real ownership; only model it for the sample slate.
    if (!State.hasRealOwnership) {
      window.Data.projectOwnership(State.golfers, State.simResults);
    }
    const ms = Math.round(performance.now() - t0);
    status.textContent = `✓ ${nSims.toLocaleString()} sims in ${ms} ms`;
    renderPlayers();
  }, 30);
}

/* ---------------------- Build pool ---------------------- */
function buildPool() {
  if (!State.simResults) {
    $('#buildStatus').textContent = 'Run a simulation first (tab 1).';
    return;
  }
  const opts = {
    nLineups: parseInt($('#nLineups').value, 10) || 20,
    maxExposure: (parseFloat($('#maxExposure').value) || 100) / 100,
    minSalary: parseInt($('#minSalary').value, 10) || 0,
    locks: new Set(State.golfers.filter((g) => g.locked).map((g) => g.id)),
    // Exclude banned golfers and anyone filtered out of the pool.
    bans: new Set(State.golfers.filter((g) => !inPool(g)).map((g) => g.id)),
  };

  $('#buildStatus').textContent = 'Building…';
  setTimeout(() => {
    const t0 = performance.now();
    State.build = window.Optimizer.buildPool(State.golfers, State.simResults, opts);

    // Re-sort the pool per the chosen objective.
    const key = $('#sortBy').value;
    State.build.lineups.sort((a, b) => b[key] - a[key]);

    const ms = Math.round(performance.now() - t0);
    $('#buildStatus').textContent =
      `✓ ${State.build.lineups.length} lineups in ${ms} ms`;
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
    ['Avg projection', num(avg('mean'))],
    ['Avg ceiling', num(avg('ceiling'))],
    ['Best ceiling', num(Math.max(...lus.map((l) => l.ceiling)))],
    ['Avg salary', money(avg('salary'))],
  ];
  $('#buildSummary').innerHTML = cards
    .map(([k, v]) => `<div class="card"><div class="cardv">${v}</div><div class="cardk">${k}</div></div>`)
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

  // Lineup cards
  $('#poolCount').textContent = `— ${State.build.lineups.length} lineups`;
  const list = $('#lineupList');
  list.innerHTML = State.build.lineups
    .map((lu, i) => {
      const names = lu.players
        .map((id) => byId(id))
        .sort((a, b) => b.salary - a.salary)
        .map((g) => `<span class="chip">${g.name} <em>${(g.salary / 1000).toFixed(1)}k</em></span>`)
        .join('');
      return `<div class="lineup">
        <div class="lhead">
          <span class="lnum">#${i + 1}</span>
          <span class="lstat">Proj <b>${num(lu.mean)}</b></span>
          <span class="lstat">Ceil <b class="up">${num(lu.ceiling)}</b></span>
          <span class="lstat">${money(lu.salary)}</span>
        </div>
        <div class="chips">${names}</div>
      </div>`;
    })
    .join('');
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
function exportDk() {
  if (!State.build || !State.build.lineups.length) {
    $('#exportPreview').textContent = 'Build a pool first.';
    return;
  }
  // DraftKings PGA upload header: 6 generic golfer slots.
  const header = ['G', 'G', 'G', 'G', 'G', 'G'];
  const rows = State.build.lineups.map((lu) =>
    lu.players
      .map((id) => byId(id))
      .sort((a, b) => b.salary - a.salary)
      .map((g) => g.name)
  );
  const csv = [header.join(','), ...rows.map((r) => r.join(','))].join('\n');
  download('draftkings_pga_upload.csv', csv);
  $('#exportPreview').textContent = csv.split('\n').slice(0, 8).join('\n') +
    (rows.length > 7 ? `\n… (${rows.length} lineups)` : '');
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
  $('#resetSlate').addEventListener('click', loadSampleSlate);
  $('#applyFilters').addEventListener('click', applyFilters);
  $('#clearFilters').addEventListener('click', clearFilters);
  ['#fMinSalary', '#fMaxSalary', '#fMinT2G', '#fMinTot', '#fMaxOwn'].forEach((id) => {
    $(id).addEventListener('change', applyFilters);
  });
  $('#exportDK').addEventListener('click', exportDk);
  $('#exportDetailed').addEventListener('click', exportDetailed);
  $('#importCsv').addEventListener('change', (e) => {
    if (e.target.files[0]) importCsv(e.target.files[0]);
  });
}

document.addEventListener('DOMContentLoaded', init);
