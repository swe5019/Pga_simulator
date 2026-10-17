/* ============================================================
 * optimizer-nfl.js — DraftKings NFL lineup optimizer, plus the contest
 * simulator's results.
 *
 * Reads data/nfl_slate_board.json for the pool and data/nfl_contest.json for
 * the field simulation. The optimizer runs here in the browser so locking,
 * excluding and rebuilding are instant; the contest simulation is far too
 * heavy for that and is computed at build time.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const CAP = 50000;
  const MAX_PER_TEAM = 8;
  const NEED = { QB: 1, RB: 2, WR: 3, TE: 1, DST: 1 };
  const FLEX_OK = ['RB', 'WR', 'TE'];

  const state = {
    pool: [], contest: [], contestMeta: null,
    locks: new Set(), excl: new Set(),
    pos: '', q: '', lineups: [],
  };

  const unlocked = () => !window.LeadGate || window.LeadGate.granted();
  const esc = (v) => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const money = (v) => (v == null ? '—' : '$' + v.toLocaleString());

  /* ---------- the optimizer ----------
   * Randomised multi start with a local swap pass. Not a formal solver: an
   * exact one would need a MILP library, and the gap between exact and this
   * is far smaller than the error already in the projections. The randomness
   * is the useful part anyway, because twenty identical optimal lineups are
   * worth less than twenty good different ones. */
  function buildOne(rng, pool, opts, used, total) {
    const noise = opts.rand / 100;
    const score = new Map();
    pool.forEach((p) => {
      // Exposure is enforced by pushing a player's score down once he is
      // already in too many lineups, rather than by banning him outright,
      // so the cap bends the search instead of breaking it.
      const over = total > 0 && (used.get(p.id) || 0) / total > opts.exp / 100;
      const jitter = 1 + (rng() * 2 - 1) * noise;
      score.set(p.id, p.proj * jitter * (over ? 0.35 : 1));
    });

    const picked = [];
    const byTeam = new Map();
    let salary = 0;

    const canAdd = (p) => {
      if (picked.some((x) => x.id === p.id)) return false;
      if ((byTeam.get(p.team) || 0) + 1 > MAX_PER_TEAM) return false;
      return true;
    };
    const add = (p) => {
      picked.push(p); salary += p.sal;
      byTeam.set(p.team, (byTeam.get(p.team) || 0) + 1);
    };

    // Locks first, since everything else has to fit around them.
    for (const id of state.locks) {
      const p = pool.find((x) => x.id === id);
      if (p && canAdd(p)) add(p);
    }

    // THE FLEX IS DECIDED UP FRONT, not filled with what is left over.
    //
    // Filling it last meant it was always chosen after the salary was nearly
    // spent, so it took the cheapest body available and every single lineup
    // came back with two tight ends. Folding the flex into the position
    // requirements before anything is picked lets it compete for budget on
    // equal terms. Which position it goes to is drawn at the rate the flex is
    // actually used, which is mostly receivers, then backs, then the
    // occasional tight end.
    const roll = rng();
    const flexPos = roll < 0.55 ? 'WR' : (roll < 0.85 ? 'RB' : 'TE');
    const need = { QB: 1, RB: 2, WR: 3, TE: 1, DST: 1 };
    need[flexPos] += 1;

    const countAt = (pos) => picked.filter((x) => x.pos === pos).length;
    const slotsLeft = () => {
      let n = 9 - picked.length;
      return n;
    };
    const fill = (pos) => {
      const want_n = need[pos] - countAt(pos);
      for (let k = 0; k < want_n; k += 1) {
        const want = pool.filter((p) => p.pos === pos && canAdd(p));
        if (!want.length) return false;
        // Reserve the minimum the remaining slots will cost.
        const after = slotsLeft() - 1;
        const reserve = after * 2500;
        const afford = want.filter((p) => salary + p.sal + reserve <= CAP);
        if (afford.length) {
          afford.sort((a, b) => score.get(b.id) - score.get(a.id));
          add(afford[0]);
        } else {
          // Nothing fits the remaining budget. Taking the best anyway is what
          // put fourteen of twenty lineups over the cap; take the cheapest
          // and let the repair pass sort it out or reject the lineup.
          want.sort((a, b) => a.sal - b.sal);
          add(want[0]);
        }
      }
      return true;
    };

    // Scarcest first: a quarterback and a defense have one slot each and the
    // fewest substitutes, so committing them late is how a build paints
    // itself into a corner.
    for (const pos of ['QB', 'DST', 'TE', 'RB', 'WR']) {
      if (!fill(pos)) return null;
    }
    if (picked.length !== 9) return null;

    // Stack the quarterback, because the measured correlation says that is
    // what wins tournaments, not because it is conventional.
    if (opts.stack) {
      const qb = picked.find((p) => p.pos === 'QB');
      if (qb && !picked.some((p) => p.team === qb.team && ['WR', 'TE'].includes(p.pos))) {
        const mates = pool.filter((p) => p.team === qb.team
          && ['WR', 'TE'].includes(p.pos) && canAdd(p));
        const drop = picked.filter((p) => ['WR', 'TE'].includes(p.pos)
          && !state.locks.has(p.id));
        if (mates.length && drop.length) {
          drop.sort((a, b) => score.get(a.id) - score.get(b.id));
          mates.sort((a, b) => score.get(b.id) - score.get(a.id));
          for (const m of mates) {
            const out = drop.find((d) => d.pos === m.pos || FLEX_OK.includes(m.pos));
            if (!out) continue;
            if (salary - out.sal + m.sal <= CAP) {
              picked.splice(picked.indexOf(out), 1);
              salary -= out.sal;
              byTeam.set(out.team, byTeam.get(out.team) - 1);
              add(m);
              break;
            }
          }
        }
      }
    }

    // REPAIR FIRST, IMPROVE SECOND. A lineup over the cap is not a lineup,
    // and an optimizer that emits one is worse than no optimizer, because it
    // looks authoritative and cannot be entered.
    let guard = 0;
    while (salary > CAP && guard < 40) {
      guard += 1;
      const swappable = picked
        .map((cur, i) => {
          if (state.locks.has(cur.id)) return null;
          const alts = pool.filter((p) => p.pos === cur.pos && !picked.includes(p)
            && p.sal < cur.sal);
          if (!alts.length) return null;
          // The swap that sheds the most salary for the least projection.
          alts.sort((a, b) => (cur.sal - b.sal) / Math.max(cur.proj - b.proj, 0.1)
            - (cur.sal - a.sal) / Math.max(cur.proj - a.proj, 0.1));
          return { i, cur, best: alts[0] };
        })
        .filter(Boolean);
      if (!swappable.length) break;
      swappable.sort((a, b) =>
        (b.cur.sal - b.best.sal) / Math.max(b.cur.proj - b.best.proj, 0.1)
        - (a.cur.sal - a.best.sal) / Math.max(a.cur.proj - a.best.proj, 0.1));
      const { i, cur, best } = swappable[0];
      salary = salary - cur.sal + best.sal;
      byTeam.set(cur.team, byTeam.get(cur.team) - 1);
      byTeam.set(best.team, (byTeam.get(best.team) || 0) + 1);
      picked[i] = best;
    }
    if (salary > CAP) return null;

    // One improvement pass: swap any player for a better one at his position
    // that still fits.
    for (let pass = 0; pass < 2; pass += 1) {
      for (let i = 0; i < picked.length; i += 1) {
        const cur = picked[i];
        if (state.locks.has(cur.id)) continue;
        const alts = pool.filter((p) => p.pos === cur.pos && !picked.includes(p)
          && salary - cur.sal + p.sal <= CAP
          && score.get(p.id) > score.get(cur.id));
        if (!alts.length) continue;
        alts.sort((a, b) => score.get(b.id) - score.get(a.id));
        const best = alts[0];
        const t = new Map(byTeam);
        t.set(cur.team, (t.get(cur.team) || 1) - 1);
        t.set(best.team, (t.get(best.team) || 0) + 1);
        if (Math.max(...t.values()) > MAX_PER_TEAM) continue;
        salary = salary - cur.sal + best.sal;
        byTeam.set(cur.team, byTeam.get(cur.team) - 1);
        byTeam.set(best.team, (byTeam.get(best.team) || 0) + 1);
        picked[i] = best;
      }
    }
    if (picked.length !== 9 || salary > CAP) return null;
    const counts = {};
    picked.forEach((p) => { counts[p.pos] = (counts[p.pos] || 0) + 1; });
    if ((counts.QB || 0) !== 1 || (counts.DST || 0) !== 1) return null;
    if ((counts.RB || 0) < 2 || (counts.WR || 0) < 3 || (counts.TE || 0) < 1) return null;
    return { players: picked.slice(), sal: salary,
             proj: picked.reduce((a, p) => a + p.proj, 0),
             ceil: picked.reduce((a, p) => a + (p.ceil || p.proj), 0),
             own: picked.reduce((a, p) => a + (p.own || 0), 0) };
  }

  function run() {
    const opts = {
      n: Math.max(1, Math.min(150, +$('#opN').value || 20)),
      exp: Math.max(5, Math.min(100, +$('#opExp').value || 60)),
      rand: Math.max(0, Math.min(100, +$('#opRand').value || 25)),
      stack: $('#opStack').checked,
    };
    const pool = state.pool.filter((p) => !state.excl.has(p.id) && p.proj != null);
    let seed = 12345;
    const rng = () => {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      return seed / 0x7fffffff;
    };
    const used = new Map();
    const out = [];
    const seen = new Set();
    let tries = 0;
    while (out.length < opts.n && tries < opts.n * 40) {
      tries += 1;
      const lu = buildOne(rng, pool, opts, used, out.length);
      if (!lu) continue;
      const sig = lu.players.map((p) => p.id).sort().join('|');
      if (seen.has(sig)) continue;
      seen.add(sig);
      lu.players.forEach((p) => used.set(p.id, (used.get(p.id) || 0) + 1));
      out.push(lu);
    }
    state.lineups = out;
    $('#opStatus').textContent = out.length < opts.n
      ? `Built ${out.length} distinct lineups from ${tries} attempts. Asking for more `
        + `than the pool can make distinct, or tight locks and exposure caps, is the `
        + `usual reason for falling short.`
      : `${out.length} lineups. Average projection `
        + `${(out.reduce((a, l) => a + l.proj, 0) / out.length).toFixed(1)}, `
        + `average salary ${money(Math.round(out.reduce((a, l) => a + l.sal, 0) / out.length))}.`;
    renderLineups();
    renderPool();
  }

  function renderLineups() {
    const head = ['#', 'Lineup', 'Salary', 'Proj', 'Ceiling', 'Own sum'];
    $('#opLineups thead tr').innerHTML = head.map((h, i) =>
      `<th class="${i >= 2 ? 'num' : ''}">${h}</th>`).join('');
    $('#opLineups tbody').innerHTML = state.lineups.map((l, i) => {
      const order = { QB: 0, RB: 1, WR: 2, TE: 3, DST: 4 };
      const names = l.players.slice()
        .sort((a, b) => order[a.pos] - order[b.pos] || b.proj - a.proj)
        .map((p) => `${esc(p.name)} <span class="dim">${p.pos}</span>`).join(', ');
      const over = l.sal > CAP ? ' down' : '';
      return `<tr><td>${i + 1}</td><td class="name">${names}</td>`
        + `<td class="num${over}">${money(l.sal)}</td>`
        + `<td class="num">${l.proj.toFixed(1)}</td>`
        + `<td class="num up">${l.ceil.toFixed(1)}</td>`
        + `<td class="num dim">${l.own.toFixed(0)}%</td></tr>`;
    }).join('');
  }

  function renderPool() {
    const total = state.lineups.length;
    const used = new Map();
    state.lineups.forEach((l) => l.players.forEach((p) =>
      used.set(p.id, (used.get(p.id) || 0) + 1)));
    const head = ['Player', 'Pos', 'Tm', 'Opp', '$', 'Proj', 'Ceiling', 'Own%', 'Used'];
    $('#opPool thead tr').innerHTML = head.map((h, i) =>
      `<th class="${i >= 4 ? 'num' : ''}">${h}</th>`).join('');
    const rows = state.pool.filter((p) => {
      if (state.pos && p.pos !== state.pos) return false;
      if (state.q && !`${p.name} ${p.team} ${p.opp}`.toLowerCase()
        .includes(state.q.toLowerCase())) return false;
      return p.proj != null;
    }).sort((a, b) => b.proj - a.proj).slice(0, 200);
    $('#opPool tbody').innerHTML = rows.map((p) => {
      const cls = state.locks.has(p.id) ? ' style="background:rgba(63,185,80,.14)"'
        : (state.excl.has(p.id) ? ' style="opacity:.4"' : '');
      const u = used.get(p.id) || 0;
      const pct = total ? ((100 * u) / total).toFixed(0) + '%' : '—';
      const tag = state.locks.has(p.id) ? ' <span class="injup">lock</span>'
        : (state.excl.has(p.id) ? ' <span class="rolewarn">out</span>' : '');
      return `<tr data-id="${esc(p.id)}"${cls} style="cursor:pointer${cls ? ';' + cls.slice(8, -1) : ''}">`
        + `<td class="name">${esc(p.name)}${tag}</td><td>${p.pos}</td><td>${esc(p.team)}</td>`
        + `<td>${esc(p.opp || '')}</td><td class="num">${money(p.sal)}</td>`
        + `<td class="num">${p.proj.toFixed(1)}</td>`
        + `<td class="num up">${(p.ceil || 0).toFixed(1)}</td>`
        + `<td class="num dim">${(p.own || 0).toFixed(1)}%</td>`
        + `<td class="num">${pct}</td></tr>`;
    }).join('');
    $$('#opPool tbody tr').forEach((tr) => {
      tr.addEventListener('click', () => {
        const id = tr.dataset.id;
        if (state.locks.has(id)) { state.locks.delete(id); state.excl.add(id); }
        else if (state.excl.has(id)) { state.excl.delete(id); }
        else { state.locks.add(id); }
        renderPool();
      });
    });
  }

  function renderContest() {
    const m = state.contestMeta;
    if (!m) return;
    $('#opContestMeta').innerHTML = `A field of <b>${m.field.toLocaleString()}</b> lineups `
      + `drawn at projected ownership, each scored in <b>${m.trials.toLocaleString()}</b> `
      + `correlated simulated slates. <b>Win ×</b> is how often a lineup containing him `
      + `wins against a random entry: 1.50 means half again as often. Ownership here is `
      + `a model with no training data behind it yet, so read the ordering rather than `
      + `the exact figures.`;
    const head = ['Player', 'Pos', 'Tm', '$', 'Own%', 'In field', 'Win ×', 'Cash ×'];
    const tips = ['', '', '', '', 'Projected ownership', 'Share of simulated lineups holding him',
      'Win rate of lineups with him against a random lineup',
      'Same for finishing in the paid places'];
    $('#opContest thead tr').innerHTML = head.map((h, i) =>
      `<th class="${i >= 3 ? 'num' : ''}" title="${esc(tips[i])}">${h}</th>`).join('');
    const rows = state.contest.filter((r) => !r.thinField).slice(0, 80);
    $('#opContest tbody').innerHTML = rows.map((r) => {
      const cls = r.winRate >= 1.15 ? ' up' : (r.winRate < 0.9 ? ' down' : '');
      return `<tr><td class="name">${esc(r.player)}</td><td>${r.pos}</td>`
        + `<td>${esc(r.team)}</td><td class="num">${money(r.sal)}</td>`
        + `<td class="num dim">${r.own.toFixed(1)}%</td>`
        + `<td class="num dim">${r.fieldPct.toFixed(1)}%</td>`
        + `<td class="num${cls}">${r.winRate.toFixed(2)}</td>`
        + `<td class="num">${(r.cashRate || 0).toFixed(2)}</td></tr>`;
    }).join('');
  }

  function syncLock() {
    const open = unlocked();
    const bar = $('#opUnlock');
    if (bar) bar.classList.toggle('hidden', open);
    const body = $('#opBody');
    if (body) body.style.display = open ? '' : 'none';
  }

  async function boot() {
    if (!$('#opt')) return;
    let board; let contest = null;
    try {
      board = await (await fetch('data/nfl_slate_board.json?v=' + Date.now())).json();
    } catch (e) {
      $('#opMeta').textContent = '— slate unavailable right now';
      return;
    }
    try {
      contest = await (await fetch('data/nfl_contest.json?v=' + Date.now())).json();
    } catch (e) { contest = null; }

    state.pool = (board.players || []).filter((p) => p.proj != null && p.sal)
      .map((p) => ({
        id: `${p.player}|${p.pos}`, name: p.player, pos: p.pos, team: p.team,
        opp: p.opp, sal: p.sal, proj: p.proj, ceil: p.ceil,
        own: (p.own || {}).mme,
      }));
    const s = board.slate || {};
    $('#opTitle').textContent = `NFL DFS Optimizer — ${s.name || 'Main Slate'}`;
    $('#opMeta').textContent = `— ${state.pool.length} players with a projection, `
      + `DraftKings scoring, $${CAP.toLocaleString()} cap.`;
    if (contest) {
      state.contest = contest.players || [];
      state.contestMeta = contest;
    }
    syncLock();
    renderPool();
    renderContest();

    $('#opRun').addEventListener('click', run);
    $('#opClear').addEventListener('click', () => {
      state.locks.clear(); state.excl.clear(); renderPool();
    });
    $$('.oppos').forEach((b) => b.addEventListener('click', () => {
      $$('.oppos').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.pos = b.dataset.p; renderPool();
    }));
    $('#opSearch').addEventListener('input', (e) => { state.q = e.target.value; renderPool(); });
    const btn = $('#opUnlockBtn');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!window.LeadGate) return;
        window.LeadGate.prompt(
          'The optimizer and the contest leverage table are free with your email.',
          'NFL-optimizer', () => { syncLock(); renderPool(); renderContest(); });
      });
    }
    if (unlocked()) run();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
}());
