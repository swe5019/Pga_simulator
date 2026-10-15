/* ============================================================
 * props.js — NFL player props table.
 *
 * Reads data/nfl_props_full.json: every Underdog line, both sides, with hit
 * rates and matchup multipliers already attached by the Python pipeline. This
 * file does presentation and filtering only. No modelling happens here, so the
 * number on screen is the number that was verified upstream.
 *
 * SOFT GATE, same shape as the stats page. Lines, prices and break-even are
 * free to everyone including crawlers; hit rates, matchup and edge need an
 * email. Locking columns rather than the document is what keeps the page
 * indexable — the old localStorage gate rendered zero words to a crawler.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const state = {
    rows: [],
    grp: 'all',
    side: 'all',
    game: '',
    pos: '',
    roleUp: false,
    q: '',
    hideThin: true,
    edgeOnly: false,
    agree: false,
    showRoleFlag: false,
    sort: { key: 'histEdge', dir: -1 },
  };

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();

  /* Which market each Underdog stat name belongs to. Splits stay a group of
   * their own because a first quarter line is a different kind of bet, not
   * because they lack data. */
  const GROUP = (stat) => {
    const s = stat || '';
    if (/^1Q|^1H/.test(s)) return 'split';
    if (/TD|Touchdown/i.test(s)) return 'td';
    if (/Rec|Target/i.test(s)) return 'rec';
    if (/Rush|Carr/i.test(s)) return 'rush';
    if (/Pass|Completion|INT|Interception|Sack/i.test(s)) return 'pass';
    return 'other';
  };

  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  const pct = (v) => (v == null ? '—' : (v * 100).toFixed(1) + '%');
  const sgn = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(1));

  /* Break-even straight off the published price. No assumption about which
   * kind of entry slip this pick ends up on is needed, because Underdog prices
   * every pick individually. */
  const be = (r) => (r.decimal ? 1 / r.decimal : null);

  const COLS = [
    ['player', 'Player', '', 'Player'],
    ['team', 'Tm', '', 'Team'],
    ['opp', 'Opp', '', 'Opponent'],
    ['stat', 'Market', '', 'What the line is on'],
    ['line', 'Line', 'num', 'The number Underdog is offering'],
    ['side', 'Side', '', 'Higher or lower'],
    ['american', 'Price', 'num', 'Underdog price for this side'],
    ['bePct', 'BE%', 'num', 'Break-even: how often this has to win to stop losing money'],
    ['histRate', 'Hit%', 'num', 'How often he has cleared this number, weighted so games '
      + 'in a different role count for less, then pulled toward the price by how much '
      + 'comparable evidence there is'],
    ['histEdge', 'Edge', 'num', 'Hit% minus BE%. Positive means history clears the price. '
      + 'This is not a projection.'],
    ['sim', 'SIM%', 'num', 'A simulation of this line: his volume and his per-play results '
      + 'fitted separately from his individual plays, then played out many thousands of '
      + 'times. Unlike Hit% this is not pulled toward the price, so it is free to '
      + 'disagree with the market. Hover for the projection behind it.'],
    ['simEdge', 'Sim Edge', 'num', 'SIM% minus BE%. Positive means the simulation clears '
      + 'the price.'],
    ['simMu', 'Proj', 'num', 'The simulated average outcome. Compare it with the line.'],
    ['l1', 'L1', 'num', 'This season, plain count'],
    ['l2', 'L2', 'num', 'This season plus last, plain count'],
    ['l3', 'L3', 'num', 'Three seasons, plain count'],
    ['histEff', 'Games', 'num', 'Games worth of COMPARABLE evidence, after weighting by '
      + 'role. Lower than games played when his job has changed.'],
    ['mu', 'Matchup', 'num', 'What this defense has allowed this position in this stat '
      + 'versus expected. Hover for the week by week breakdown.'],
  ];
  /* Columns an email unlocks. Everything else is open. */
  const LOCKED = new Set(['histRate', 'histEdge', 'l1', 'l2', 'l3', 'histEff', 'mu',
    'sim', 'simEdge', 'simMu']);

  function visibleCols() {
    return unlocked() ? COLS : COLS.filter((c) => !LOCKED.has(c[0]));
  }

  function cell(r, key) {
    switch (key) {
      case 'bePct': return be(r) == null ? '—' : (be(r) * 100).toFixed(1) + '%';
      case 'histRate': return pct(r.histRate);
      case 'histEdge': return sgn(r.histEdge);
      case 'histEff': return r.histEff == null ? '—' : r.histEff.toFixed(1);
      case 'l1': case 'l2': case 'l3': {
        const h = r.hits && r.hits[key];
        return h && h.n ? `${h.h}/${h.n}` : '—';
      }
      case 'mu': return r.mu == null ? '—' : '×' + r.mu.toFixed(2);
      case 'sim': return pct(r.sim);
      case 'simEdge': return sgn(r.simEdge);
      case 'simMu': return r.simMu == null ? '—' : String(r.simMu);
      case 'side': return r.side === 'over' ? 'Higher' : 'Lower';
      case 'line': return r.line;
      default: return r[key] == null ? '—' : r[key];
    }
  }

  function sortVal(r, key) {
    switch (key) {
      case 'bePct': return be(r);
      case 'l1': case 'l2': case 'l3': {
        const h = r.hits && r.hits[key];
        return h && h.n ? h.h / h.n : null;
      }
      default: return r[key];
    }
  }

  function passes(r) {
    if (state.grp !== 'all' && GROUP(r.stat) !== state.grp) return false;
    if (state.side !== 'all' && r.side !== state.side) return false;
    if (state.game && `${r.team}@${r.opp}` !== state.game
        && `${r.opp}@${r.team}` !== state.game) return false;
    if (state.pos && r.pos !== state.pos) return false;
    // Players with somebody ahead of them on the injury report. This is the
    // one filter that finds opportunity rather than screening it out.
    if (state.roleUp && !(r.outAhead && !r.selfOut)) return false;
    if (state.q) {
      const q = state.q.toLowerCase();
      if (!(`${r.player} ${r.team} ${r.opp} ${r.stat}`.toLowerCase().includes(q))) return false;
    }
    // Thin and edge filters only mean anything once the history columns are
    // visible, so they are ignored while locked rather than silently hiding
    // rows for a reason the reader cannot see.
    if (unlocked()) {
      if (state.hideThin && r.thin) return false;
      if (state.edgeOnly && !(r.histEdge > 0)) return false;
      // A row where the model and the market disagree this much about how
      // much work a player gets is almost always a role the model has not
      // seen yet, and its edge is the largest on the board precisely because
      // it is wrong. Kept out of the edge filters unless asked for, since
      // those filters exist to surface findings.
      if (r.roleFlag && !state.showRoleFlag
          && (state.edgeOnly || state.agree)) return false;
      // Where two methods built on different things point the same way. The
      // hit rate counts whole games and leans on the price; the simulation
      // rebuilds the game from individual plays and ignores the price. Both
      // positive is a far stronger signal than either alone.
      if (state.agree && !(r.histEdge > 0 && r.simEdge > 0)) return false;
    }
    return true;
  }

  /* The drill-down behind a matchup multiplier, as a title attribute so it
   * needs no extra machinery and still works on a phone's long press. */
  function matchupTip(r) {
    if (!r.muGames || !r.muGames.length) return '';
    // A derived market has no multiplier of its own, so it borrows its
    // parent's. Say which, rather than letting it read as a measurement of
    // something that was never measured.
    const what = r.muFrom
      ? `${r.muFrom} (there is no "${r.stat}" allowed to measure, so this market `
        + `borrows it)`
      : r.stat;
    const head = `${r.opp} vs ${r.pos}, ${what}: ×${r.mu.toFixed(2)} over ${r.muN} player-games`;
    const lines = r.muGames.map((g) =>
      `wk${g.wk} ${g.tm} (${g.n}) ${g.act} vs expected ${g.exp}`);
    return `${head}\n${lines.join('\n')}`;
  }

  /* What the simulation actually did, so a reader can see whether a SIM% is
   * standing on anything. */
  function simTip(r) {
    if (r.sim == null) return '';
    const bits = [`Simulated average ${r.simMu} against a line of ${r.line}`];
    if (r.simGames != null) {
      bits.push(`fitted on ${r.simGames} games worth of comparable history`);
    }
    if (r.simThin) {
      bits.push('THIN: too little of his own history, so this leans on the '
        + 'average for his position and role rather than on him');
    }
    if (r.histRate != null) {
      const d = Math.abs(r.sim - r.histRate) * 100;
      bits.push(d < 5
        ? 'Agrees with the hit rate'
        : `Disagrees with the hit rate by ${d.toFixed(0)} points, which usually `
          + 'means his volume or his efficiency has moved');
    }
    return bits.join('. ') + '.';
  }

  /* Why this row's edge should not be trusted. */
  function roleFlagTip(r) {
    return r.roleWhy || '';
  }

  /* The injury picture behind a row, which is the most useful thing on it when
   * it applies: who is out, what that is based on, and how much bigger this
   * player's job was the last time that man did not play. */
  function injuryTip(r) {
    if (r.selfOut) {
      return `ON THE INJURY REPORT: ${r.selfBasis}`
        + (r.selfInjury ? ` (${r.selfInjury})` : '')
        + '. Whether he plays at all is the open question, so treat every '
        + 'number on this row as provisional.';
    }
    if (!r.outAhead) return '';
    if (r.roleUnknown) {
      return `${r.outBasis}. He has never played a game without him, so there `
        + 'is nothing to measure his bigger role against and no honest '
        + 'projection to make. The market is the better guide here.';
    }
    if (r.roleCtx == null) return `${r.outBasis}.`;
    const n = r.roleCtxN;
    return `${r.outBasis}. In the ${n} game${n === 1 ? '' : 's'} he has played `
      + `without him he was on the field for ${r.roleCtx}% of snaps, against `
      + `${r.roleBefore}% alongside him, so his role is read at the higher `
      + `figure this week.`
      + (n < 3 ? ` That rests on ${n === 1 ? 'a single game' : 'two games'}, `
        + 'so it is marked thin and pulled hard toward the market.' : '');
  }

  function roleTip(r) {
    const inj = injuryTip(r);
    if (inj) return inj;
    if (r.roleShift == null) return '';
    const dir = r.roleShift > 0 ? 'bigger' : 'smaller';
    return `Role now ${r.roleNow}% of snaps versus ${r.roleHist}% across his history, `
      + `a ${Math.abs(r.roleShift).toFixed(0)} point ${dir} job. His past games are `
      + `weighted down accordingly.`;
  }

  function render() {
    const cols = visibleCols();
    if (!cols.some((c) => c[0] === state.sort.key)) {
      state.sort = { key: 'line', dir: -1 };
    }

    $('#prTable thead tr').innerHTML = cols.map(([k, label, cls, tip]) => {
      const on = state.sort.key === k ? ' sorted' : '';
      const arrow = state.sort.key === k ? (state.sort.dir === -1 ? ' ↓' : ' ↑') : '';
      return `<th class="${cls} sortable${on}" data-k="${k}" title="${esc(tip)}">${label}${arrow}</th>`;
    }).join('');

    let rows = state.rows.filter(passes);
    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      const x = sortVal(a, key), y = sortVal(b, key);
      if (typeof x === 'string' || typeof y === 'string') {
        return -dir * String(x || '').localeCompare(String(y || ''));
      }
      if (x == null && y == null) return 0;
      if (x == null) return 1;     // blanks sink whichever way the column points
      if (y == null) return -1;
      return dir * (x - y);
    });

    const shown = rows.slice(0, 400);
    $('#prTable tbody').innerHTML = shown.map((r) => {
      const tds = cols.map(([k, , cls]) => {
        let extra = '';
        let tip = '';
        if (k === 'histEdge' && r.histEdge != null) {
          extra = r.histEdge > 0 ? ' up' : (r.histEdge < 0 ? ' down' : ' dim');
        }
        // Both edge columns are greyed on a flagged row rather than shown in
        // green, because green is a recommendation and this is not one.
        if (r.roleFlag && (k === 'histEdge' || k === 'simEdge')) {
          extra = ' dim';
          tip = roleFlagTip(r);
        }
        if (k === 'mu' && r.mu != null) {
          extra = r.mu > 1.05 ? ' up' : (r.mu < 0.95 ? ' down' : ' dim');
          tip = matchupTip(r);
        }
        if (k === 'simEdge' && r.simEdge != null) {
          extra = r.simEdge > 0 ? ' up' : (r.simEdge < 0 ? ' down' : ' dim');
        }
        if ((k === 'sim' || k === 'simMu') && r.sim != null) {
          if (r.simThin) extra = ' dim';
          tip = simTip(r);
        }
        if (k === 'player') {
          extra = ' name';
          tip = roleTip(r);
        }
        if (k === 'histEff' && r.thin) extra = ' dim';
        const t = tip ? ` title="${esc(tip)}"` : '';
        const flag = (k === 'player' && r.roleShift != null && Math.abs(r.roleShift) >= 15)
          ? ' <span class="roleflag" aria-label="role changed">⤴</span>' : '';
        const warn = (k === 'player' && r.roleFlag)
          ? ` <span class="rolewarn" title="${esc(roleFlagTip(r))}" aria-label="role may have changed">⚠</span>`
          : '';
        // Somebody ahead of him is out, which is worth seeing at a glance
        // rather than only on hover.
        let inj = '';
        if (k === 'player') {
          if (r.selfOut) {
            inj = ' <span class="injself" aria-label="on the injury report">✚</span>';
          } else if (r.outAhead) {
            inj = ' <span class="injup" aria-label="bigger role, someone ahead is out">▲</span>';
          }
        }
        const thin = (k === 'player' && r.thin) ? ' <span class="thinflag">thin</span>' : '';
        return `<td class="${cls}${extra}"${t}>${esc(cell(r, k))}${flag}${warn}${inj}${thin}</td>`;
      }).join('');
      return `<tr>${tds}</tr>`;
    }).join('');

    const flags = rows.filter((r) => r.roleFlag).length;
    const note = flags
      ? ` ${flags} carry a ⚠, meaning the model and the market disagree sharply about`
        + ` how much work the player gets, which is usually a role change rather than value.`
      : '';
    $('#prCount').textContent = (rows.length > shown.length
      ? `Showing the top ${shown.length} of ${rows.length} lines. Narrow the filters to see the rest.`
      : `${rows.length} lines.`) + note;

    $$('#prTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
        render();
      });
    });
  }

  function syncLock() {
    const open = unlocked();
    const bar = $('#prUnlock');
    if (bar) bar.classList.toggle('hidden', open);
    ['#prHideThin', '#prEdgeOnly', '#prAgree', '#prShowRoleFlag'].forEach((sel) => {
      const el = $(sel);
      if (el) el.disabled = !open;
    });
  }

  function fillFilters() {
    const games = new Set();
    const poss = new Set();
    state.rows.forEach((r) => {
      if (r.team && r.opp) games.add([r.team, r.opp].sort().join('@'));
      if (r.pos) poss.add(r.pos);
    });
    $('#prGame').innerHTML = '<option value="">All games</option>'
      + Array.from(games).sort().map((g) => `<option value="${g}">${g.replace('@', ' @ ')}</option>`).join('');
    $('#prPos').innerHTML = '<option value="">All</option>'
      + Array.from(poss).sort().map((p) => `<option value="${p}">${p}</option>`).join('');
  }

  function meta(doc) {
    const d = doc.built ? new Date(doc.built) : null;
    const when = d ? d.toLocaleString(undefined, { month: 'short', day: 'numeric',
      hour: 'numeric', minute: '2-digit' }) : '';
    const withHist = state.rows.filter((r) => r.hits).length;
    const withSim = state.rows.filter((r) => r.sim != null).length;
    const trials = doc.simulatedTrials
      ? ` at ${doc.simulatedTrials.toLocaleString()} draws each` : '';
    $('#prMeta').textContent = `— ${doc.count.toLocaleString()} lines from Underdog, `
      + `updated ${when}. ${withHist.toLocaleString()} carry hit rates and `
      + `${withSim.toLocaleString()} are simulated${trials}.`;
    const up = new Set(state.rows.filter((r) => r.outAhead && !r.selfOut).map((r) => r.player));
    const outs = new Set(state.rows.filter((r) => r.selfOut).map((r) => r.player));
    const injEl = $('#prInj');
    if (injEl) {
      injEl.innerHTML = (up.size || outs.size)
        ? `<b>Injury report:</b> ${outs.size} player${outs.size === 1 ? '' : 's'} with `
          + `props are on it themselves (✚), and ${up.size} have somebody ahead of them `
          + `out (▲), which usually means a bigger role than their history shows. `
          + `Hover a name for who is out and what it is based on.`
        : '';
    }
    const noHist = state.rows.length - withHist;
    $('#prWarn').textContent = noHist
      ? `${noHist.toLocaleString()} of these carry a line but no history: kicking and `
        + `defensive markets are not in the stats pipeline yet. They are shown with `
        + `blank history rather than a guessed one.`
      : '';
  }

  async function boot() {
    if (!$('#props')) return;
    let doc;
    try {
      const res = await fetch('data/nfl_props_full.json?v=' + Date.now());
      doc = await res.json();
    } catch (e) {
      $('#prMeta').textContent = '— prop lines unavailable right now';
      return;
    }
    state.rows = doc.props || [];
    fillFilters();
    meta(doc);
    syncLock();
    render();

    $$('.prgrp').forEach((b) => b.addEventListener('click', () => {
      $$('.prgrp').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.grp = b.dataset.grp;
      render();
    }));
    $$('.prside').forEach((b) => b.addEventListener('click', () => {
      $$('.prside').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.side = b.dataset.side;
      render();
    }));
    $('#prGame').addEventListener('change', (e) => { state.game = e.target.value; render(); });
    $('#prPos').addEventListener('change', (e) => { state.pos = e.target.value; render(); });
    $('#prSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    $('#prHideThin').addEventListener('change', (e) => { state.hideThin = e.target.checked; render(); });
    $('#prEdgeOnly').addEventListener('change', (e) => { state.edgeOnly = e.target.checked; render(); });
    $('#prAgree').addEventListener('change', (e) => { state.agree = e.target.checked; render(); });
    $('#prShowRoleFlag').addEventListener('change', (e) => {
      state.showRoleFlag = e.target.checked; render();
    });
    $('#prRoleUp').addEventListener('change', (e) => {
      state.roleUp = e.target.checked; render();
    });

    const btn = $('#prUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'Hit rates, matchup multipliers and the edge columns are free with your email.',
          'NFL-props',
          () => { syncLock(); render(); });
      });
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
