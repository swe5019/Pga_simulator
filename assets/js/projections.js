/* ============================================================
 * projections.js — NFL fantasy projections table and stack pricing.
 *
 * Reads data/nfl_projections.json, written by tools/build_projections.py.
 * Presentation and filtering only. Every number here was computed and verified
 * upstream, so what is on screen is what the backtest checked.
 *
 * SOFT GATE, the same shape as the other two NFL pages. The projection itself
 * is free to everyone including crawlers; floor, ceiling, the chance of a
 * twenty point game and the stack table need an email. Columns lock, not the
 * document, which is what keeps the page indexable.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    rows: [],
    stacks: [],
    score: 'half',
    pos: '',
    game: '',
    q: '',
    hideThin: false,
    anchoredOnly: false,
    sort: { key: 'med', dir: -1 },
  };

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();

  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const n1 = (v) => (v == null ? '—' : Number(v).toFixed(1));
  const pct = (v) => (v == null ? '—' : (v * 100).toFixed(0) + '%');

  /* The numbers for whichever scoring system is selected. */
  const S = (r) => r[state.score] || {};

  const COLS = [
    ['player', 'Player', '', 'Player'],
    ['pos', 'Pos', '', 'Position'],
    ['team', 'Tm', '', 'Team'],
    ['opp', 'Opp', '', 'Opponent'],
    ['med', 'Proj', 'num', 'The median outcome. Half the simulated games land above it.'],
    ['p25', 'Floor', 'num', '25th percentile. What a bad but not disastrous game looks like, '
      + 'which is what cash games care about.'],
    ['p90', 'Ceiling', 'num', '90th percentile. One game in ten is this good or better, '
      + 'which is what wins tournaments.'],
    ['p20', '20+', 'num', 'Chance of a twenty point game.'],
    ['mean', 'Mean', 'num', 'The average. Sits above the median because the upside tail is '
      + 'longer than the downside, and touchdowns are what stretch it.'],
    ['anchors', 'Lines', 'num', 'How many betting lines anchor this player. More means the '
      + 'projection leans more on the market and less on the model.'],
  ];
  const LOCKED = new Set(['p25', 'p90', 'p20']);

  const visibleCols = () => (unlocked() ? COLS : COLS.filter((c) => !LOCKED.has(c[0])));

  function cell(r, key) {
    switch (key) {
      case 'med': case 'p25': case 'p90': return n1(S(r)[key]);
      case 'mean': return n1(S(r).mean);
      case 'p20': return pct(S(r).p20);
      case 'anchors': return (r.anchors || []).length || '—';
      default: return r[key] == null ? '—' : r[key];
    }
  }

  function sortVal(r, key) {
    switch (key) {
      case 'med': case 'p25': case 'p90': return S(r)[key];
      case 'mean': return S(r).mean;
      case 'p20': return S(r).p20;
      case 'anchors': return (r.anchors || []).length;
      default: return r[key];
    }
  }

  /* Which betting lines are holding this projection up. Worth showing because
   * a player with six anchors and one with none are different kinds of
   * estimate, however similar their projections look. */
  function anchorTip(r) {
    if (!r.anchors || !r.anchors.length) {
      return 'No betting lines on this player, so the projection is the model '
        + 'alone. Treat it as a rougher estimate than a market anchored one.';
    }
    const head = `Anchored to ${r.anchors.length} betting line`
      + `${r.anchors.length === 1 ? '' : 's'}:`;
    const lines = r.anchors.map((a) => {
      const hit = a.got != null ? `, simulation says ${a.got}%` : '';
      return `${a.stat} ${a.line} at a fair ${a.fair}%${hit}`;
    });
    return `${head}\n${lines.join('\n')}`;
  }

  function injuryTip(r) {
    if (r.roleUnknown) {
      return `${r.outBasis}. He has never played a game without him, so there is `
        + 'nothing to measure a bigger role against. The projection leans on the '
        + 'betting line instead of pretending to know.';
    }
    if (r.outAhead) {
      const n = r.roleCtxN;
      return `${r.outBasis}. In the ${n} game${n === 1 ? '' : 's'} he has played `
        + `without him he took ${r.roleCtx}% of the snaps, and his role is read at `
        + `that figure this week`
        + (n < 3 ? ', which rests on too little to be confident about.' : '.');
    }
    return '';
  }

  function render() {
    const cols = visibleCols();
    if (!cols.some((c) => c[0] === state.sort.key)) state.sort = { key: 'med', dir: -1 };

    $('#pjTable thead tr').innerHTML = cols.map(([k, label, cls, tip]) => {
      const on = state.sort.key === k ? ' sorted' : '';
      const arrow = state.sort.key === k ? (state.sort.dir === -1 ? ' ↓' : ' ↑') : '';
      return `<th class="${cls} sortable${on}" data-k="${k}" title="${esc(tip)}">${label}${arrow}</th>`;
    }).join('');

    let rows = state.rows.filter((r) => {
      if (state.pos && r.pos !== state.pos) return false;
      if (state.game && `${r.team}@${r.opp}` !== state.game
          && `${r.opp}@${r.team}` !== state.game) return false;
      if (state.q) {
        const q = state.q.toLowerCase();
        if (!`${r.player} ${r.team} ${r.opp} ${r.pos}`.toLowerCase().includes(q)) return false;
      }
      if (state.hideThin && r.thin) return false;
      if (state.anchoredOnly && !(r.anchors && r.anchors.length)) return false;
      // A player projected for almost nothing is noise in a table this long.
      return S(r).mean >= 1.0;
    });

    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      const x = sortVal(a, key), y = sortVal(b, key);
      if (typeof x === 'string' || typeof y === 'string') {
        return -dir * String(x || '').localeCompare(String(y || ''));
      }
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return dir * (x - y);
    });

    const shown = rows.slice(0, 300);
    $('#pjTable tbody').innerHTML = shown.map((r) => {
      const tds = cols.map(([k, , cls]) => {
        let extra = '';
        let tip = '';
        if (k === 'player') {
          extra = ' name';
          tip = injuryTip(r);
        }
        if (k === 'anchors') {
          tip = anchorTip(r);
          if (!(r.anchors && r.anchors.length)) extra = ' dim';
        }
        if (k === 'p90') extra = ' up';
        if (k === 'p25') extra = ' dim';
        const t = tip ? ` title="${esc(tip)}"` : '';
        const inj = (k === 'player' && r.outAhead)
          ? ' <span class="injup" aria-label="bigger role, someone ahead is out">▲</span>' : '';
        const thin = (k === 'player' && r.thin) ? ' <span class="thinflag">thin</span>' : '';
        return `<td class="${cls}${extra}"${t}>${esc(cell(r, k))}${inj}${thin}</td>`;
      }).join('');
      return `<tr>${tds}</tr>`;
    }).join('');

    $('#pjCount').textContent = rows.length > shown.length
      ? `Showing the top ${shown.length} of ${rows.length} players. Narrow the filters to see the rest.`
      : `${rows.length} players.`;

    $$('#pjTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
        render();
      });
    });

    renderStacks();
  }

  function renderStacks() {
    const wrap = $('#pjStacks');
    if (!wrap) return;
    if (!unlocked()) {
      wrap.querySelector('.tablewrap').innerHTML =
        '<p class="hint">Stack pricing unlocks with your email, along with floor and ceiling.</p>';
      return;
    }
    let list = state.stacks.slice();
    if (state.game) {
      list = list.filter((s) => `${s.qbTeam}@${s.mateTeam}` === state.game
        || `${s.mateTeam}@${s.qbTeam}` === state.game
        || s.qbTeam === state.game.split('@')[0] || s.qbTeam === state.game.split('@')[1]);
    }
    if (state.q) {
      const q = state.q.toLowerCase();
      list = list.filter((s) => `${s.qb} ${s.mate}`.toLowerCase().includes(q));
    }
    list.sort((a, b) => b.lift - a.lift);
    const head = ['Quarterback', 'With', 'Pos', 'Type', 'Corr', 'Both big', 'Lift'];
    const tips = ['', '', '', 'Same team, or the receiver on the other side of the game',
      'How much their fantasy points move together',
      'How often both land in their own top 30% in the same game',
      'That chance divided by 0.09, which is what independence would give. '
      + '1.00 means the pairing adds nothing.'];
    $('#pjStackTable thead tr').innerHTML = head.map((h, i) =>
      `<th class="${i >= 4 ? 'num' : ''}" title="${esc(tips[i])}">${h}</th>`).join('');
    $('#pjStackTable tbody').innerHTML = list.slice(0, 60).map((s) => {
      const cls = s.lift >= 1.3 ? ' up' : (s.lift < 1.05 ? ' dim' : '');
      return `<tr><td class="name">${esc(s.qb)}</td><td>${esc(s.mate)}</td>`
        + `<td>${esc(s.matePos)}</td>`
        + `<td class="${s.same ? '' : 'dim'}">${s.same ? 'stack' : 'bring back'}</td>`
        + `<td class="num">${s.corr > 0 ? '+' : ''}${s.corr.toFixed(2)}</td>`
        + `<td class="num">${(s.both * 100).toFixed(0)}%</td>`
        + `<td class="num${cls}">${s.lift.toFixed(2)}×</td></tr>`;
    }).join('');
  }

  function syncLock() {
    const bar = $('#pjUnlock');
    if (bar) bar.classList.toggle('hidden', unlocked());
  }

  function fillFilters() {
    const games = new Set();
    state.rows.forEach((r) => { if (r.team && r.opp) games.add([r.team, r.opp].sort().join('@')); });
    $('#pjGame').innerHTML = '<option value="">All games</option>'
      + Array.from(games).sort().map((g) => `<option value="${g}">${g.replace('@', ' @ ')}</option>`).join('');
  }

  function meta(doc) {
    const d = doc.built ? new Date(doc.built) : null;
    const when = d ? d.toLocaleString(undefined, { month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit' }) : '';
    $('#pjMeta').textContent = `— ${doc.count.toLocaleString()} players, `
      + `${doc.anchoredPlayers.toLocaleString()} anchored to betting lines, `
      + `${doc.trials.toLocaleString()} simulated games each, updated ${when}`;
    const up = state.rows.filter((r) => r.outAhead).length;
    const el = $('#pjInj');
    if (el) {
      el.innerHTML = up
        ? `<b>${up}</b> player${up === 1 ? ' has' : 's have'} somebody ahead of them on the `
          + `injury report (▲), so their role is read from the games that man missed rather `
          + `than from a season average. Hover a name for the detail.`
        : '';
    }
  }

  async function boot() {
    if (!$('#proj')) return;
    let doc;
    try {
      const res = await fetch('data/nfl_projections.json?v=' + Date.now());
      doc = await res.json();
    } catch (e) {
      $('#pjMeta').textContent = '— projections unavailable right now';
      return;
    }
    state.rows = doc.players || [];
    state.stacks = doc.stacks || [];
    fillFilters();
    meta(doc);
    syncLock();
    render();

    $$('.pjscore').forEach((b) => b.addEventListener('click', () => {
      $$('.pjscore').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.score = b.dataset.s;
      render();
    }));
    $$('.pjpos').forEach((b) => b.addEventListener('click', () => {
      $$('.pjpos').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.pos = b.dataset.p;
      render();
    }));
    $('#pjGame').addEventListener('change', (e) => { state.game = e.target.value; render(); });
    $('#pjSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    $('#pjHideThin').addEventListener('change', (e) => { state.hideThin = e.target.checked; render(); });
    $('#pjAnchored').addEventListener('change', (e) => { state.anchoredOnly = e.target.checked; render(); });

    const btn = $('#pjUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'Floor, ceiling, the chance of a twenty point game and the stack pricing '
          + 'are free with your email.',
          'NFL-projections',
          () => { syncLock(); render(); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
