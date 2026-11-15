/* ============================================================
 * showdown.js — which captain and which shape win a single-game slate.
 *
 * Reads data/nfl_showdown_scenarios.json, written by
 * tools/discover_showdown.py. Presentation only.
 *
 * The file holds SEVERAL slates in `slates`, ordered soonest first, so index 0
 * is the game that has to be decided next. A selector switches between them
 * rather than the page picking one, because on a Sunday both the evening game
 * and Monday's are live decisions at the same time.
 *
 * WHAT THIS PAGE DOES NOT SHOW, DELIBERATELY
 * There is no field column and no leverage column. The file says so itself
 * with hasFieldModel, and the page reads that flag rather than assuming: a
 * showdown field needs a CAPTAIN ownership model, captain ownership summing to
 * 100% and flex to 500%, and no such model exists yet. Since a lineup's payoff
 * depends on how many other people built it, an unvalidated denominator is
 * worse than an absent one, so the page states the gap instead of filling it.
 *
 * SOFT GATE, same as the other NFL pages: the win rates are free to everyone
 * including crawlers. The partner lists and the game-script breakdown need an
 * email. Sections gate rather than the document, which keeps it indexable.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);

  const state = { doc: null, idx: 0, sort: { key: 'pWin', dir: -1 } };

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const pct = (v) => (v == null ? '—' : (100 * v).toFixed(1) + '%');
  const money = (v) => (v == null ? '—' : '$' + Number(v).toLocaleString());

  const cur = () => (state.doc.slates || [])[state.idx] || null;

  /* Kickoff as something a human can act on. The file carries UTC; the reader
   * cares how long they have, so both are shown. */
  function whenText(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const hrs = (d - new Date()) / 3600000;
    const local = d.toLocaleString(undefined, {
      weekday: 'short', hour: 'numeric', minute: '2-digit',
    });
    if (hrs < 0) return `${local} · already locked`;
    if (hrs < 1) return `${local} · locks in ${Math.round(hrs * 60)} min`;
    return `${local} · locks in ${hrs.toFixed(1)}h`;
  }

  function renderPicker() {
    const sl = state.doc.slates || [];
    const box = $('#sdPicker');
    if (sl.length < 2) { box.innerHTML = ''; return; }
    box.innerHTML = sl.map((r, i) => {
      const s = r.slate || {};
      return `<button type="button" class="slatebtn${i === state.idx ? ' on' : ''}"
        data-i="${i}">${esc(s.name || 'slate')}
        <span class="muted">${(s.entries || 0).toLocaleString()} entries</span></button>`;
    }).join('');
  }

  function renderMeta() {
    const r = cur();
    const s = r.slate || {};
    const d = state.doc.built ? new Date(state.doc.built) : null;
    const built = d ? d.toLocaleString(undefined,
      { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
      : 'unknown';
    $('#sdTitle').textContent = s.name || 'NFL Showdown Scenarios';
    $('#sdMeta').textContent = `— ${whenText(s.start)}, `
      + `${(s.entries || 0).toLocaleString()} entries, `
      + `${(r.trials || 0).toLocaleString()} simulated games, updated ${built}`;
    $('#sdSolve').textContent = r.exactSolve
      ? `Solved exactly: every one of the ${r.poolSize} players with a `
        + `projection was tried as captain, and every legal filling of the `
        + `other five slots was scored. ${r.poolSize} of ${r.priced} priced `
        + `players carry a projection; the rest are backups and the two kickers, `
        + `which have no model yet.`
      : `Solved on a reduced candidate set, because this pool is unusually `
        + `large (${r.poolSize} players). Shapes are reliable; a single `
        + `captain near the boundary may not be.`;
  }

  function renderCaptains() {
    const r = cur();
    const open = unlocked();
    const rows = (r.captains || []).slice();
    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === 'string' || typeof y === 'string') {
        return -dir * String(x || '').localeCompare(String(y || ''));
      }
      return dir * ((x || 0) - (y || 0));
    });
    const cols = [
      ['player', 'Captain', '', 'The player in the captain slot.'],
      ['pos', 'Pos', '', 'Position. Any position may captain in showdown.'],
      ['team', 'Team', '', 'Which side he is on.'],
      ['sal', 'Flex $', 'num', 'What he costs in a normal slot.'],
      ['cptSal', 'Captain $', 'num',
        'What he costs as captain: one and a half times the flex price. '
        + 'He also scores one and a half times, which is why this slot decides '
        + 'the lineup.'],
      ['pWin', 'Wins%', 'num',
        'Share of simulated games whose best possible lineup captained him. '
        + 'Measured, with nothing about the field in it.'],
    ];
    $('#sdCapHead').innerHTML = cols.map(([k, label, cls, tip]) =>
      `<th class="${cls} sortable${key === k ? ' sorted' : ''}" data-k="${k}"
        title="${esc(tip)}">${label}${key === k ? (dir === -1 ? ' ↓' : ' ↑') : ''}</th>`
    ).join('');

    $('#sdCapBody').innerHTML = rows.map((c) => {
      const mates = Object.entries(c.partners || {});
      const detail = (open && mates.length)
        ? `<tr class="subrow"><td colspan="${cols.length}" class="sub-detail">`
          + '<span class="muted">most often with:</span> '
          + mates.map(([n, v]) =>
            `${esc(n)} <span class="muted">(${Math.round(100 * v / (c.wins || 1))}%)</span>`)
            .join(' · ')
          + '</td></tr>'
        : '';
      return '<tr>'
        + `<td>${esc(c.player)}</td><td>${esc(c.pos)}</td><td>${esc(c.team)}</td>`
        + `<td class="num">${money(c.sal)}</td>`
        + `<td class="num">${money(c.cptSal)}</td>`
        + `<td class="num">${pct(c.pWin)}</td></tr>` + detail;
    }).join('');
  }

  function renderShapes() {
    const r = cur();
    $('#sdShapes').innerHTML = '<table><thead><tr>'
      + '<th title="The captain\'s position, then how the six players split '
      + 'across the two teams. The first number is the captain\'s own side.">'
      + 'Shape</th><th class="num">Wins%</th></tr></thead><tbody>'
      + (r.shapes || []).slice(0, 14).map((s) =>
        `<tr><td>${esc(s.shape)}</td><td class="num">${pct(s.pWin)}</td></tr>`)
        .join('')
      + '</tbody></table>';

    $('#sdSplits').innerHTML = (r.splits || []).map((s) =>
      `<span class="chip"><b>${esc(s.split)}</b> ${pct(s.pWin)}</span>`).join(' ');
  }

  function renderScripts() {
    const r = cur();
    const box = $('#sdScripts');
    if (!unlocked()) {
      box.innerHTML = '<p class="hint">The game-script breakdown is free with '
        + 'your email. It is the part that changes what you build: a blowout and '
        + 'a shootout want different captains and a different split.</p>';
      return;
    }
    box.innerHTML = (r.scripts || []).map((sc) => {
      const shapes = (sc.shapes || []).slice(0, 3).map((s) =>
        `<li>${esc(s.shape)} <span class="muted">`
        + `${(100 * s.pWithin).toFixed(1)}% of those</span></li>`).join('');
      const caps = (sc.captains || []).slice(0, 3).map((c) =>
        `${esc(c.player)} <span class="muted">`
        + `(${Math.round(100 * c.pWithin)}%)</span>`).join(' · ');
      return `<div class="scriptcard"><h3>${esc(sc.script)}`
        + ` <span class="muted">${pct(sc.pWin)} of games</span></h3>`
        + `<ul>${shapes}</ul>`
        + `<p class="muted">usual captain:</p><p>${caps}</p></div>`;
    }).join('');
  }

  function syncLock() {
    const bar = $('#sdUnlock');
    if (bar) bar.style.display = unlocked() ? 'none' : '';
  }

  function renderAll() {
    renderPicker();
    renderMeta();
    renderCaptains();
    renderShapes();
    renderScripts();
    syncLock();
  }

  async function boot() {
    let doc;
    try {
      const res = await fetch('data/nfl_showdown_scenarios.json?v=' + Date.now());
      doc = await res.json();
    } catch (e) {
      $('#sdMeta').textContent = '— showdown scenarios unavailable right now';
      return;
    }
    // Written before the multi-slate change, or written by hand: either way the
    // page should degrade rather than throw.
    if (!doc || !Array.isArray(doc.slates) || !doc.slates.length) {
      $('#sdMeta').textContent = '— no showdown slate is posted right now. '
        + 'DraftKings puts single-game slates up a day or two ahead.';
      return;
    }
    state.doc = doc;

    // The flag is read rather than assumed, so that the day a field model does
    // exist this warning stops appearing on its own.
    const warn = $('#sdWarn');
    if (warn && doc.hasFieldModel) warn.style.display = 'none';

    renderAll();

    $('#sdPicker').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-i]');
      if (!b) return;
      state.idx = Number(b.dataset.i) || 0;
      renderAll();
    });
    $('#sdCapHead').addEventListener('click', (e) => {
      const th = e.target.closest('th[data-k]');
      if (!th) return;
      const k = th.dataset.k;
      state.sort = state.sort.key === k
        ? { key: k, dir: -state.sort.dir } : { key: k, dir: -1 };
      renderCaptains();
    });
    const btn = $('#sdUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'The game script breakdown and the partner lists are free with your email.',
          'NFL-showdown', () => { renderAll(); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
