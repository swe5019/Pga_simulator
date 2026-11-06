/* ============================================================
 * scenarios.js — which games can win this slate, and who is already there.
 *
 * Reads data/nfl_scenarios.json, written by tools/discover_scenarios.py.
 * Presentation only.
 *
 * The page is deliberately blunt about what is and is not trustworthy here.
 * The win column is measured: it is the share of simulated slates whose best
 * possible lineup had that shape. The field column is a MODEL of what other
 * entries look like, and it is built on projected ownership that has been
 * measured against one real contest and found over-dispersed. Leverage is the
 * ratio of the two, so it inherits every weakness of the weaker half, and the
 * page says so next to the number rather than in a footnote.
 *
 * SOFT GATE, same as the other NFL pages: the win column is free to everyone
 * including crawlers, the field and leverage columns need an email. Columns
 * lock rather than the document, which keeps the page indexable.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    rows: [],
    shapes: [],
    q: '',
    minWins: 5,
    sort: { key: 'leverage', dir: -1 },
  };

  /* What counts as a "cheap correlation" play: enough ceiling to actually
   * matter, at low enough ownership to be worth taking instead of the obvious
   * piece. Gunnar Helm was the shape last week, 14.9 ceiling at 1.2%
   * projected, and he captured nearly the same game correlation as the
   * bring-backs everyone else used while freeing the salary that bought the
   * quarterback.
   *
   * The ceiling floor is doing real work. Ranked on ratio alone the list fills
   * with players owned at a tenth of a percent who project for two points:
   * their ratios are enormous and they are not plays. */
  const CHEAP_MIN_CEIL = 14;
  const CHEAP_MAX_OWN = 7;
  /* A real role, not just a cheap name. Without this the list fills with
   * backup quarterbacks and third tight ends who clear the ceiling bar on a
   * wide distribution and will not see the field. */
  const CHEAP_MIN_PROJ = 6;
  /* Ownership is never divided by less than this. Projected ownership carries
   * about four points of average error against the one real contest it has
   * been checked on, so the difference between 0.2% and 0.8% is noise, and
   * dividing by it turns noise into a ranking: a quarterback owned at a tenth
   * of a percent came out at 138x and was not a play at all. */
  const CHEAP_OWN_FLOOR = 1.0;

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const pct = (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%');

  const COLS = [
    ['game', 'Game', '', 'The two teams whose players this scenario stacks.'],
    ['depth', 'Deep', 'num', 'How many of the nine roster spots come from that game. '
      + 'Four deep means four of your players are in one game, so they rise and '
      + 'fall together.'],
    ['pWin', 'Wins%', 'num', 'Share of simulated slates where the best possible lineup '
      + 'had this shape. This half is measured, not assumed.'],
    ['field', 'Field%', 'num', 'Share of a simulated field of 4,000 entries built this '
      + 'way. A MODEL of the crowd, resting on projected ownership that is known to be '
      + 'over-dispersed, so treat it as a rough guide.'],
    ['leverage', 'Lev', 'num', 'Wins divided by field. Above 1 means the shape wins more '
      + 'often than entries are built that way. It inherits every weakness of the field '
      + 'column, so use it to rank, not to size a bet.'],
    ['cheap', 'Cheap correlation', '', 'The player in that game who carries the most '
      + 'ceiling per point of ownership, among those with a real role and a real '
      + 'ceiling rather than a wide one. Takes almost '
      + 'the same game correlation as the obvious piece at a fraction of the '
      + 'ownership, which is what frees salary elsewhere. Ownership here is projected, '
      + 'so trust the ordering more than the level.'],
    ['wins', 'Trials', 'num', 'How many simulated slates this is counted from. Small '
      + 'counts are noisy.'],
  ];
  const LOCKED = new Set(['field', 'leverage', 'cheap']);
  const visibleCols = () => (unlocked() ? COLS : COLS.filter((c) => !LOCKED.has(c[0])));

  function cell(r, k) {
    switch (k) {
      case 'pWin': case 'field': return pct(r[k]);
      case 'leverage': return r.leverage == null ? '—' : r.leverage.toFixed(2) + '×';
      case 'depth': return 'x' + r.depth;
      case 'cheap': {
        const c = (r.cheapList || [])[0];
        return c ? `${c.player} ${c.ratio.toFixed(0)}×` : '—';
      }
      case 'wins': return r.wins;
      default: return r[k] == null ? '—' : r[k];
    }
  }

  function render() {
    const cols = visibleCols();
    if (!cols.some((c) => c[0] === state.sort.key)) state.sort = { key: 'pWin', dir: -1 };

    $('#scTable thead tr').innerHTML = cols.map(([k, label, cls, tip]) => {
      const on = state.sort.key === k ? ' sorted' : '';
      const arrow = state.sort.key === k ? (state.sort.dir === -1 ? ' ↓' : ' ↑') : '';
      return `<th class="${cls} sortable${on}" data-k="${k}" title="${esc(tip)}">${label}${arrow}</th>`;
    }).join('');

    const rows = state.rows.filter((r) => {
      if (r.wins < state.minWins) return false;
      if (state.q && !`${r.game} ${(r.players || []).join(' ')}`
        .toLowerCase().includes(state.q.toLowerCase())) return false;
      return true;
    });

    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === 'string' || typeof y === 'string') {
        return -dir * String(x || '').localeCompare(String(y || ''));
      }
      if (x == null) return 1;
      if (y == null) return -1;
      return dir * (x - y);
    });

    $('#scTable tbody').innerHTML = rows.map((r) => {
      const who = (r.players || []).slice(0, 5).join(', ');
      const comp = Object.keys(r.companions || {}).slice(0, 2).join(', ');
      const cheap = unlocked()
        ? (r.cheapList || []).slice(0, 3).map((c) =>
          `${esc(c.player)} <span class="muted">($${c.sal.toLocaleString()}, `
          + `${c.own.toFixed(1)}% own, ${c.proj.toFixed(1)} proj, `
          + `${c.ceil.toFixed(1)} ceil)</span>`).join(' · ')
        : '';
      const lines = [];
      if (who) {
        lines.push(`<span class="muted">most often:</span> ${esc(who)}`
          + (comp ? ` <span class="muted">· paired with:</span> ${esc(comp)}` : ''));
      }
      if (cheap) lines.push(`<span class="muted">cheap correlation:</span> ${cheap}`);
      const detail = lines.length
        ? `<tr class="subrow"><td colspan="${cols.length}" class="sub-detail">`
          + lines.join('<br>') + '</td></tr>'
        : '';
      return '<tr>' + cols.map(([k, , cls]) =>
        `<td class="${cls}">${esc(cell(r, k))}</td>`).join('') + '</tr>' + detail;
    }).join('');

    $('#scCount').textContent = `${rows.length} scenario${rows.length === 1 ? '' : 's'} `
      + `shown, each seen in at least ${state.minWins} of ${state.trials} simulated slates.`;
    renderShapes();
  }

  function renderShapes() {
    if (!state.shapes.length) return;
    const locked = !unlocked();
    $('#scShapes').innerHTML = '<table><thead><tr>'
      + '<th title="How many players come from one game, then the second game. '
      + '&quot;4-2&quot; is four from one game and two from another.">Shape</th>'
      + '<th class="num">Wins%</th>'
      + (locked ? '' : '<th class="num">Field%</th><th class="num">Lev</th>')
      + '</tr></thead><tbody>'
      + state.shapes.map((s) => {
        const lev = s.field ? s.pWin / s.field : null;
        return `<tr><td>${esc(s.shape)}</td><td class="num">${pct(s.pWin)}</td>`
          + (locked ? '' : `<td class="num">${pct(s.field)}</td>`
            + `<td class="num">${lev == null ? '—' : lev.toFixed(2) + '×'}</td>`)
          + '</tr>';
      }).join('')
      + '</tbody></table>';
  }

  function meta(doc) {
    const sl = doc.slate || {};
    const d = doc.built ? new Date(doc.built) : null;
    const when = d ? d.toLocaleString(undefined,
      { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'unknown';
    $('#scMeta').textContent = `— ${sl.name || 'slate'}, `
      + `${doc.trials.toLocaleString()} simulated slates against a modelled field of `
      + `${doc.field.toLocaleString()}, updated ${when}`;
  }

  function syncLock() {
    const bar = $('#scUnlock');
    if (bar) bar.style.display = unlocked() ? 'none' : '';
  }

  async function boot() {
    let doc;
    try {
      const res = await fetch('data/nfl_scenarios.json?v=' + Date.now());
      doc = await res.json();
    } catch (e) {
      $('#scMeta').textContent = '— scenarios unavailable right now';
      return;
    }
    // The scenario file carries only names, so salary, ceiling and ownership
    // are joined from the slate board. A failure here costs the cheap
    // correlation column and nothing else, so the page still renders.
    const byGame = {};
    try {
      const bres = await fetch('data/nfl_slate_board.json?v=' + Date.now());
      const board = await bres.json();
      (board.players || []).forEach((p) => {
        const o = p.own ? p.own.mme : null;
        if (!p.team || !p.opp || o == null) return;
        if (!['QB', 'RB', 'WR', 'TE'].includes(p.pos)) return;
        if ((p.ceil || 0) < CHEAP_MIN_CEIL || o > CHEAP_MAX_OWN) return;
        if ((p.proj || 0) < CHEAP_MIN_PROJ) return;
        const g = [p.team, p.opp].sort().join('/');
        (byGame[g] = byGame[g] || []).push({
          player: p.player, pos: p.pos, team: p.team, sal: p.sal,
          ceil: p.ceil, own: o, proj: p.proj,
          ratio: p.ceil / Math.max(o, CHEAP_OWN_FLOOR),
        });
      });
      Object.values(byGame).forEach((l) => l.sort((a, b) => b.ratio - a.ratio));
    } catch (e) { /* board unavailable; the column simply stays empty */ }
    state.trials = doc.trials;
    state.shapes = doc.shapes || [];
    // "CIN/TEN x4" is one string upstream because that is how it is counted.
    // Split here so the game and the depth can be sorted on separately.
    state.rows = (doc.scenarios || []).map((s) => {
      const m = /^(.*) x(\d+)$/.exec(s.scenario);
      const game = m ? m[1] : s.scenario;
      return Object.assign({}, s, {
        game,
        depth: m ? Number(m[2]) : 0,
        cheapList: byGame[game] || [],
      });
    }).filter((s) => s.depth > 0);
    meta(doc);
    syncLock();
    render();

    $('#scTable thead').addEventListener('click', (e) => {
      const th = e.target.closest('th[data-k]');
      if (!th) return;
      const k = th.dataset.k;
      state.sort = state.sort.key === k
        ? { key: k, dir: -state.sort.dir } : { key: k, dir: -1 };
      render();
    });
    $('#scSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    $('#scMinWins').addEventListener('change', (e) => {
      state.minWins = Number(e.target.value) || 1;
      render();
    });

    const btn = $('#scUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'The field and leverage columns are free with your email.',
          'NFL-scenarios', () => { syncLock(); render(); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
