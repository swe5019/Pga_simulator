/* ============================================================
 * slate.js — the DraftKings slate board.
 *
 * Reads data/nfl_slate_board.json, written by tools/build_nfl_slate.py.
 * Presentation and filtering only. Every number was computed and checked
 * upstream, including the ownership constraint that each position's
 * projected ownership adds to the number of roster slots it fills.
 *
 * SOFT GATE, same as the other NFL pages: salary and projection are free to
 * everyone including crawlers, ownership and leverage need an email. Columns
 * lock rather than the document, which keeps the page indexable.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    rows: [],
    contest: 'mme',
    pos: '',
    game: '',
    q: '',
    hideThin: true,
    hideNoProj: true,
    labels: {},
    sort: { key: 'proj', dir: -1 },
  };

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const n1 = (v) => (v == null ? '—' : Number(v).toFixed(1));
  const own = (r) => (r.own ? r.own[state.contest] : null);

  const COLS = [
    ['player', 'Player', '', 'Player'],
    ['team', 'Tm', '', 'Team'],
    ['opp', 'Opp', '', 'Opponent'],
    ['pos', 'Pos', '', 'Position'],
    ['sal', '$', 'num', 'DraftKings salary'],
    ['gpp', 'Leverage', 'num', 'Boom rate minus ownership. Positive means the field is '
      + 'under-rostering the outcome he actually produces, which is the number worth '
      + 'sorting on.'],
    ['expected', 'Exp', 'num', 'What a player at this price and position is expected to '
      + 'score, fitted across the slate using only players with a real role.'],
    ['value', 'Value', 'num', 'Projection minus what his price normally returns. Zero means '
      + 'he scores like a typical starter at his salary, positive means he beats his price '
      + 'tag. Not points per dollar, which mechanically favours cheap players.'],
    ['ownc', 'Own%', 'num', 'Projected ownership for the selected contest type. A model, '
      + 'not a measurement: there is no NFL ownership data to train on yet.'],
    ['proj', 'Proj', 'num', 'Median outcome in DraftKings scoring'],
    ['ceil', 'Ceiling', 'num', '90th percentile. One game in ten is this good or better.'],
    ['super', 'Super', 'num', 'The one game in thirty that wins a tournament.'],
    ['boom', 'Boom%', 'num', 'How often he clears the score his position actually needs '
      + 'on THIS slate, taken from the slate rather than fixed.'],
  ];
  const LOCKED = new Set(['gpp', 'ownc', 'boom', 'super', 'ceil', 'expected']);
  const visibleCols = () => (unlocked() ? COLS : COLS.filter((c) => !LOCKED.has(c[0])));

  function cell(r, k) {
    switch (k) {
      case 'ownc': { const v = own(r); return v == null ? '—' : v.toFixed(1) + '%'; }
      case 'boom': return r.boom == null ? '—' : r.boom.toFixed(1) + '%';
      case 'gpp': return r.gpp == null ? '—' : (r.gpp > 0 ? '+' : '') + r.gpp.toFixed(1);
      case 'value': return r.value == null ? '—'
        : (r.value > 0 ? '+' : '') + r.value.toFixed(1);
      case 'expected': return n1(r.expected);
      case 'proj': case 'ceil': case 'super': return n1(r[k]);
      case 'sal': return r.sal ? r.sal.toLocaleString() : '—';
      default: return r[k] == null ? '—' : r[k];
    }
  }

  const sortVal = (r, k) => (k === 'ownc' ? own(r) : r[k]);

  /* Why a player has no numbers, which is information rather than an omission. */
  function whyTip(r) {
    if (r.why) return r.why;
    if (r.selfOut) {
      return `On the injury report: ${r.selfBasis}`
        + (r.selfInjury ? ` (${r.selfInjury})` : '')
        + '. Projected as if he plays, because the market still has lines on him.';
    }
    if (r.outAhead) {
      const n = r.roleCtxN;
      return `${r.outBasis}. In the ${n} game${n === 1 ? '' : 's'} without him he `
        + `took ${r.roleCtx}% of the snaps, and his role is read at that figure.`;
    }
    return '';
  }

  function render() {
    const cols = visibleCols();
    if (!cols.some((c) => c[0] === state.sort.key)) state.sort = { key: 'proj', dir: -1 };

    $('#slTable thead tr').innerHTML = cols.map(([k, label, cls, tip]) => {
      const on = state.sort.key === k ? ' sorted' : '';
      const arrow = state.sort.key === k ? (state.sort.dir === -1 ? ' ↓' : ' ↑') : '';
      return `<th class="${cls} sortable${on}" data-k="${k}" title="${esc(tip)}">${label}${arrow}</th>`;
    }).join('');

    const rows = state.rows.filter((r) => {
      if (state.pos && r.pos !== state.pos) return false;
      if (state.game && `${r.team}@${r.opp}` !== state.game
          && `${r.opp}@${r.team}` !== state.game) return false;
      if (state.q) {
        const q = state.q.toLowerCase();
        if (!`${r.player} ${r.team} ${r.opp} ${r.pos}`.toLowerCase().includes(q)) return false;
      }
      if (state.hideNoProj && r.proj == null) return false;
      // Thin players carry ceilings wide enough to take over any leverage
      // ranking, so they are hidden here by default rather than quietly
      // distorted into looking narrower than they are.
      if (state.hideThin && r.thin) return false;
      return true;
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
    $('#slTable tbody').innerHTML = shown.map((r) => {
      const tds = cols.map(([k, , cls]) => {
        let extra = '';
        let tip = '';
        if (k === 'player') { extra = ' name'; tip = whyTip(r); }
        if ((k === 'value' || k === 'expected') && r.expected != null) {
          tip = `A ${r.pos} at $${r.sal.toLocaleString()} is expected to score `
            + `${r.expected}. This one projects ${r.proj}, so he beats his price `
            + `by ${(r.value > 0 ? '+' : '')}${r.value}.`
            + (r.ppk != null ? ` Points per $1,000 is ${r.ppk}, shown only because `
              + 'people expect it; it mostly ranks by how cheap a player is.' : '');
        }
        if (k === 'gpp' && r.gpp != null) extra = r.gpp > 0 ? ' up' : ' down';
        if (k === 'value' && r.value != null) extra = r.value > 0 ? ' up' : ' down';
        if (k === 'expected') extra = ' dim';
        if (k === 'ceil') extra = ' up';
        if (k === 'ownc' && own(r) != null && own(r) >= 20) extra = ' down';
        const t = tip ? ` title="${esc(tip)}"` : '';
        let mark = '';
        if (k === 'player') {
          if (r.selfOut) mark += ' <span class="injself" aria-label="on the injury report">✚</span>';
          else if (r.outAhead) mark += ' <span class="injup" aria-label="bigger role">▲</span>';
          if (r.thin) mark += ' <span class="thinflag">thin</span>';
          if (r.proj == null) mark += ' <span class="thinflag">no proj</span>';
        }
        return `<td class="${cls}${extra}"${t}>${esc(cell(r, k))}${mark}</td>`;
      }).join('');
      return `<tr>${tds}</tr>`;
    }).join('');

    const lab = state.labels[state.contest] || state.contest;
    $('#slCount').textContent = (rows.length > shown.length
      ? `Showing the top ${shown.length} of ${rows.length}. Narrow the filters to see the rest.`
      : `${rows.length} players.`) + `  Ownership shown for: ${lab}.`;

    $$('#slTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
        render();
      });
    });
  }

  function syncLock() {
    const bar = $('#slUnlock');
    if (bar) bar.classList.toggle('hidden', unlocked());
  }

  function meta(doc) {
    const s = doc.slate || {};
    const d = doc.built ? new Date(doc.built) : null;
    const when = d ? d.toLocaleString(undefined, { month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit' }) : '';
    $('#slTitle').textContent = `NFL DFS Slate Board — ${s.name || 'Main Slate'}`;
    $('#slMeta').textContent = `— ${doc.count} players, ${doc.projected} projected, `
      + `DraftKings scoring, from 10,000 correlated slate simulations. Updated ${when}.`;
    state.labels = doc.contests || {};
    const t = doc.thresholds || {};
    const parts = Object.keys(t).sort().map((k) => `${k} ${t[k]}`);
    const el = $('#slInj');
    const hurt = state.rows.filter((r) => r.selfOut).length;
    const up = state.rows.filter((r) => r.outAhead && !r.selfOut).length;
    if (el) {
      const bits = [];
      if (parts.length) {
        bits.push(`<b>Score each position needs on this slate:</b> ${parts.join(', ')}. `
          + `Boom% is how often a player clears his.`);
      }
      if (hurt || up) {
        bits.push(`${hurt} player${hurt === 1 ? ' is' : 's are'} on the injury report (✚) `
          + `and ${up} have somebody ahead of them out (▲).`);
      }
      el.innerHTML = bits.join(' ');
    }
  }

  async function boot() {
    if (!$('#slate')) return;
    let doc;
    try {
      const res = await fetch('data/nfl_slate_board.json?v=' + Date.now());
      doc = await res.json();
    } catch (e) {
      $('#slMeta').textContent = '— slate board unavailable right now';
      return;
    }
    state.rows = doc.players || [];
    const games = new Set();
    state.rows.forEach((r) => { if (r.team && r.opp) games.add([r.team, r.opp].sort().join('@')); });
    $('#slGame').innerHTML = '<option value="">All games</option>'
      + Array.from(games).sort().map((g) => `<option value="${g}">${g.replace('@', ' @ ')}</option>`).join('');
    meta(doc);
    syncLock();
    render();

    $$('.slown').forEach((b) => b.addEventListener('click', () => {
      $$('.slown').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.contest = b.dataset.c;
      render();
    }));
    $$('.slpos').forEach((b) => b.addEventListener('click', () => {
      $$('.slpos').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.pos = b.dataset.p;
      render();
    }));
    $('#slGame').addEventListener('change', (e) => { state.game = e.target.value; render(); });
    $('#slSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    $('#slHideThin').addEventListener('change', (e) => { state.hideThin = e.target.checked; render(); });
    $('#slHideNoProj').addEventListener('change', (e) => { state.hideNoProj = e.target.checked; render(); });

    const btn = $('#slUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'Ownership, leverage, boom rates and ceilings are free with your email.',
          'NFL-slate', () => { syncLock(); render(); });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
