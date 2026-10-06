/* ============================================================
 * nfl.js — NFL advanced stats reference.
 *
 * Reads data/nfl_<season>.json, which ships RAW WEEKLY COUNTS, not rates, and
 * data/nfl_dk.json for salaries. Every rate on screen is computed here, over
 * whatever week window is selected, by summing the counts across that window
 * and dividing once. That is the whole reason the feed is shaped the way it is:
 * averaging four weekly target shares is not the target share over four weeks,
 * and the difference is largest for exactly the players whose role changed,
 * which are the players this page exists to find.
 *
 * Columns are position-specific. One table across QB/RB/WR/TE would be mostly
 * empty cells, so the position buttons swap the column set.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  const DATA_DIR = 'data/';

  /* ---------- state ---------- */
  const state = {
    index: null,
    season: null,
    raw: null,          // parsed nfl_<season>.json
    dk: null,           // parsed nfl_dk.json
    slate: null,        // chosen DK slate
    pos: 'WR',
    view: 'all',        // 'std' | 'adv' | 'all'
    basis: 'total',     // 'total' | 'pg' — governs the standard counting columns
    from: null,
    to: null,
    q: '',
    sort: { key: 'tgtsh', dir: -1 },   // replaced by defaultSortKey() on first render
  };

  /* ---------- column sets ----------
   * [key, label, cssClass, tooltip]. Keys match what agg() produces. */
  const EDGE_TIP = 'Usage rank minus salary rank over this window. Positive means '
    + 'the market has not priced his role yet.';
  const ROUTE_TIP = 'Routes are reconstructed from who was on the field for each dropback, '
    + 'because nobody publishes charted routes for free. A back or tight end who stayed '
    + 'in to block still counts as a route, so their rate reads a little low; for wide '
    + 'receivers it lands within a route or two per game of the charted figure.';

  const FPOE_TIP = 'Half PPR points per game minus what his opportunity was worth. '
    + 'Expected points price every target and carry by its depth and field position, so '
    + 'this separates a bad run of finishing from a bad role. Negative is usually the buy: '
    + 'the usage is already there and the scoring has not followed. Positive tends to '
    + 'regress, because it was built on touchdowns the volume does not support.';

  // Points columns are shared by every position, so they are defined once and
  // spliced in rather than repeated four times and drifting apart.
  const PTS = [
    ['hppr', 'Half', 'num', 'Half PPR fantasy points per game. 0.5 per reception.'],
    ['ppr', 'PPR', 'num', 'Full PPR fantasy points per game. 1 per reception. '
      + 'Scoring is 0.04 per passing yard, 4 per passing TD, -2 per interception, '
      + '0.1 per rushing or receiving yard, 6 per TD and -2 per fumble lost.'],
    ['fpoe', 'FPOE', 'num', FPOE_TIP],
  ];

  /* ---------- standard box score ----------
   * Counting stats here honour the totals / per game switch; the header label
   * changes with it so a total is never mistaken for an average. Rates (Catch%,
   * Y/R, YPC, Cmp%) are identical either way and carry no suffix. */
  const CATCH_TIP = 'Catch rate: receptions divided by targets.';
  const STD = {
    WR: [
      ['tg_c', 'Tgt', 'num', 'Targets'],
      ['rec_c', 'Rec', 'num', 'Receptions'],
      ['ry_c', 'RecYd', 'num', 'Receiving yards'],
      ['rtd_c', 'RecTD', 'num', 'Receiving touchdowns'],
      ['ypr', 'Y/R', 'num', 'Yards per reception'],
      ['catch', 'Catch%', 'num', CATCH_TIP],
      ['ca_c', 'Rush', 'num', 'Rushing attempts'],
      ['ru_c', 'RuYd', 'num', 'Rushing yards'],
      ['td_c', 'TD', 'num', 'Total touchdowns: receiving, rushing and passing'],
      ['fl_c', 'FL', 'num', 'Fumbles lost'],
    ],
    RB: [
      ['ca_c', 'Att', 'num', 'Rushing attempts'],
      ['ru_c', 'RuYd', 'num', 'Rushing yards'],
      ['utd_c', 'RuTD', 'num', 'Rushing touchdowns'],
      ['ypc', 'YPC', 'num', 'Yards per carry'],
      ['tg_c', 'Tgt', 'num', 'Targets'],
      ['rec_c', 'Rec', 'num', 'Receptions'],
      ['ry_c', 'RecYd', 'num', 'Receiving yards'],
      ['rtd_c', 'RecTD', 'num', 'Receiving touchdowns'],
      ['catch', 'Catch%', 'num', CATCH_TIP],
      ['td_c', 'TD', 'num', 'Total touchdowns: receiving, rushing and passing'],
      ['fl_c', 'FL', 'num', 'Fumbles lost'],
    ],
    QB: [
      ['cmp_c', 'Cmp', 'num', 'Completions'],
      ['att_c', 'Att', 'num', 'Pass attempts'],
      ['cmppct', 'Cmp%', 'num', 'Completion percentage'],
      ['py_c', 'PaYd', 'num', 'Passing yards'],
      ['ptd_c', 'PaTD', 'num', 'Passing touchdowns'],
      ['int_c', 'INT', 'num', 'Interceptions thrown'],
      ['sk_c', 'Sck', 'num', 'Times sacked'],
      ['ca_c', 'Rush', 'num', 'Rushing attempts'],
      ['ru_c', 'RuYd', 'num', 'Rushing yards'],
      ['utd_c', 'RuTD', 'num', 'Rushing touchdowns'],
      ['fl_c', 'FL', 'num', 'Fumbles lost'],
    ],
  };
  STD.TE = STD.WR;

  /* Counting columns: the ones the totals / per game switch applies to. Rates
   * are deliberately absent, because a rate is the same on either basis. */
  const COUNT_COLS = new Set(['tg_c', 'rec_c', 'ry_c', 'rtd_c', 'ca_c', 'ru_c', 'utd_c',
    'cmp_c', 'att_c', 'py_c', 'ptd_c', 'int_c', 'sk_c', 'td_c', 'fl_c']);

  const COLS = {
    WR: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['g', 'G', 'num', 'Games in this window'],
      ['sal', 'Sal', 'num', 'DraftKings salary for the selected slate'],
      ['snap', 'Snap%', 'num', 'Share of his team\'s offensive snaps'],
      ['routes', 'Rts/g', 'num', ROUTE_TIP],
      ['tprr', 'TPRR', 'num', 'Targets per route run. The cleanest usage rate there is: '
        + 'it is immune to how often his offense threw. ' + ROUTE_TIP],
      ['tgtsh', 'Tgt%', 'num', 'Share of team targets'],
      ['adot', 'aDOT', 'num', 'Average depth of target, in yards'],
      ['airsh', 'Air%', 'num', 'Share of team air yards'],
      ['wopr', 'WOPR', 'num', 'Weighted opportunity rating: 1.5 x target share + 0.7 x air yards share'],
      ['rz', 'RZ/g', 'num', 'Targets per game inside the 20'],
      ['yprr', 'YPRR', 'num', 'Yards per route run. ' + ROUTE_TIP],
      ['sep', 'Sep', 'num', 'Next Gen Stats average separation at the catch point, in yards'],
      ['yacoe', 'YACOE', 'num', 'Yards after catch over expected, per reception'],
      ['edge', 'Edge', 'num', EDGE_TIP],
    ],
    TE: null,
    RB: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['g', 'G', 'num', 'Games in this window'],
      ['sal', 'Sal', 'num', 'DraftKings salary for the selected slate'],
      ['snap', 'Snap%', 'num', 'Share of his team\'s offensive snaps'],
      ['carsh', 'Car%', 'num', 'Share of team carries'],
      ['rzc', 'RZ/g', 'num', 'Carries per game inside the 20'],
      ['glc', 'GL/g', 'num', 'Carries per game inside the 5. The touchdown column.'],
      ['tgtsh', 'Tgt%', 'num', 'Share of team targets. In PPR this is what separates an RB1 from a committee back.'],
      ['tgpg', 'Tgt/g', 'num', 'Targets per game'],
      ['ypc', 'YPC', 'num', 'Yards per carry'],
      ['ryoe', 'RYOE', 'num', 'Next Gen Stats rush yards over expected, per attempt. '
        + 'Positive means he beats what the blocking gave him.'],
      ['edge', 'Edge', 'num', EDGE_TIP],
    ],
    QB: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['g', 'G', 'num', 'Games in this window'],
      ['sal', 'Sal', 'num', 'DraftKings salary for the selected slate'],
      ['dbpg', 'DB/g', 'num', 'Dropbacks per game'],
      ['adot', 'aDOT', 'num', 'Average depth of target, in yards'],
      ['iay', 'IAY', 'num', 'Next Gen Stats average intended air yards'],
      ['ttt', 'TTT', 'num', 'Next Gen Stats time to throw, in seconds'],
      ['cpoe', 'CPOE', 'num', 'Completion percentage over expected'],
      ['epa', 'EPA', 'num', 'Expected points added per dropback'],
      ['rush', 'Rush/g', 'num', 'Rush attempts per game. The DFS separator at quarterback.'],
      ['ypg', 'PaYd/g', 'num', 'Passing yards per game'],
      ['edge', 'Edge', 'num', EDGE_TIP],
    ],
  };
  // Splice the points block in just after Sal on every position, so the three
  // things a reader checks first — what he costs, what he scores, whether his
  // usage supports it — sit next to each other. Done here rather than written
  // into each list so the four cannot drift apart.
  ['WR', 'RB', 'QB'].forEach((pos) => {
    const at = COLS[pos].findIndex((c) => c[0] === 'sal');
    COLS[pos] = COLS[pos].slice(0, at + 1).concat(PTS, COLS[pos].slice(at + 1));
  });
  COLS.TE = COLS.WR;

  /* Columns that only exist when the season has participation data. */
  const ROUTE_COLS = new Set(['routes', 'tprr', 'yprr']);
  /* Only renders when the expected-points feed covered this season. */
  const EXP_COLS = new Set(['fpoe']);

  /* The column each position opens on when there is no salary feed and so no
   * Edge to lead with. It has to be position-specific: quarterbacks have no
   * target share, so defaulting everyone to Tgt% sorted the QB table by a
   * column of nulls and floated one-dropback backups to the top. */
  const DEFAULT_SORT = { QB: 'dbpg', RB: 'carsh', WR: 'tgtsh', TE: 'tgtsh' };
  const defaultSortKey = () => (slateApplies() ? 'edge' : DEFAULT_SORT[state.pos] || 'tgtsh');

  /* ---------- helpers ---------- */
  // nflverse and DraftKings disagree about three franchises. Normalising both
  // sides here is cheaper than carrying a mapping through the Python feed.
  const TEAM_FIX = { LA: 'LAR', STL: 'LAR', SD: 'LAC', OAK: 'LV', WSH: 'WAS', JAC: 'JAX', ARZ: 'ARI' };
  const team = (t) => TEAM_FIX[(t || '').toUpperCase()] || (t || '').toUpperCase();

  // Must survive "A.J. Brown" vs "AJ Brown" and "Marvin Harrison Jr." vs
  // "Marvin Harrison". Mirrors nrm() in tools/fetch_nfl.py.
  function nrm(s) {
    return (s || '').toLowerCase()
      .replace(/[.'`,]/g, '')
      .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, '')
      .replace(/[^a-z]+/g, '');
  }

  const div = (a, b) => (b > 0 ? a / b : null);
  const sum = (rows, k) => rows.reduce((t, r) => t + (r[k] || 0), 0);

  /* Volume-weighted mean, for the handful of Next Gen rates that cannot be
   * decomposed into counts. A flat mean would let a one-target week swing a
   * season figure as hard as a twelve-target week. */
  function wmean(rows, key, weightKey) {
    let n = 0, d = 0;
    rows.forEach((r) => {
      if (r[key] == null) return;
      const w = r[weightKey] || 0;
      if (w <= 0) return;
      n += r[key] * w;
      d += w;
    });
    return d > 0 ? n / d : null;
  }

  /* ---------- aggregation ---------- */
  function agg() {
    const raw = state.raw;
    if (!raw) return [];
    const meta = new Map(raw.players.map((p) => [p.id, p]));
    const byPlayer = new Map();
    raw.rows.forEach((r) => {
      if (r.w < state.from || r.w > state.to) return;
      if (!byPlayer.has(r.i)) byPlayer.set(r.i, []);
      byPlayer.get(r.i).push(r);
    });

    const out = [];
    byPlayer.forEach((rows, id) => {
      const m = meta.get(id);
      if (!m || m.p !== state.pos) return;

      // Team denominators are summed over the SAME weeks the player appeared,
      // so a player who missed three games is measured against the snaps and
      // targets of the games he actually played, not the team's whole window.
      let tSn = 0, tTg = 0, tAy = 0, tCa = 0, tDb = 0;
      rows.forEach((r) => {
        const t = raw.teams[`${r.t}|${r.w}`] || {};
        tSn += t.sn || 0; tTg += t.tg || 0; tAy += t.ay || 0;
        tCa += t.ca || 0; tDb += t.db || 0;
      });

      const g = rows.length;
      const tg = sum(rows, 'tg'), ay = sum(rows, 'ay'), ry = sum(rows, 'ry');
      const ca = sum(rows, 'ca'), ru = sum(rows, 'ru'), rt = sum(rows, 'rt');
      const att = sum(rows, 'att'), db = tDb && sum(rows, 'att') + sum(rows, 'sk');
      const tgtsh = div(tg, tTg), airsh = div(ay, tAy);

      const row = {
        id,
        name: m.n,
        tm: team(rows[rows.length - 1].t),
        opp: team(rows[rows.length - 1].o),
        g,
        snap: div(sum(rows, 'sn'), tSn) != null ? div(sum(rows, 'sn'), tSn) * 100 : null,
        tgtsh: tgtsh != null ? tgtsh * 100 : null,
        airsh: airsh != null ? airsh * 100 : null,
        // Receivers' aDOT is their own air yards over their targets; a
        // quarterback's is the air yards he THREW over his attempts, which is a
        // different numerator entirely. Reading the receiving one for a QB is
        // how the column came out blank.
        adot: state.pos === 'QB' ? div(sum(rows, 'pay'), att) : div(ay, tg),
        rz: div(sum(rows, 'rz'), g),
        tgpg: div(tg, g),
        carsh: div(ca, tCa) != null ? div(ca, tCa) * 100 : null,
        rzc: div(sum(rows, 'rzc'), g),
        glc: div(sum(rows, 'glc'), g),
        ypc: div(ru, ca),
        rush: div(sum(rows, 'qra'), g),
        dbpg: div(att + sum(rows, 'sk'), g),
        ypg: div(sum(rows, 'py'), g),
        cpoe: div(sum(rows, 'cpoeN'), att),
        epa: div(sum(rows, 'pepa'), att + sum(rows, 'sk')),
        sep: wmean(rows, 'sep', 'tg'),
        yacoe: wmean(rows, 'yacoe', 'rec'),
        ttt: wmean(rows, 'ttt', 'att'),
        iay: wmean(rows, 'iay', 'att'),
        ryoe: wmean(rows, 'ryoe', 'ca'),
      };
      // Standard box score. Stored as season/window TOTALS; the page divides
      // by games when the basis switch is on per game, so one set of numbers
      // serves both views and the two can never drift apart.
      // tg, ay, ry, ca, ru and att are already in scope from the usage block.
      const rec = sum(rows, 'rec');
      const rtd = sum(rows, 'rtd'), utd = sum(rows, 'utd'), ptd = sum(rows, 'ptd');
      const cmp = sum(rows, 'cmp');
      row.tg_c = tg;
      row.rec_c = rec;
      row.ry_c = ry;
      row.rtd_c = rtd;
      row.ca_c = ca;
      row.ru_c = ru;
      row.utd_c = utd;
      row.cmp_c = cmp;
      row.att_c = att;
      row.py_c = sum(rows, 'py');
      row.ptd_c = ptd;
      row.int_c = sum(rows, 'int');
      row.sk_c = sum(rows, 'sk');
      row.fl_c = sum(rows, 'fl');
      row.td_c = rtd + utd + ptd;
      // Rates are computed from the window totals, never averaged from weekly
      // rates, for the same reason every other rate on this page is.
      row.ypr = div(ry, rec);
      row.catch = div(rec, tg) != null ? div(rec, tg) * 100 : null;
      row.cmppct = div(cmp, att) != null ? div(cmp, att) * 100 : null;

      // Points. Half PPR is full PPR with half a point taken back per
      // reception, which is exact rather than a second scoring pass.
      const fp = sum(rows, 'fp');
      row.ppr = div(fp, g);
      row.hppr = div(fp - 0.5 * rec, g);
      // FPOE is averaged over only the weeks the model actually priced. Summing
      // actual points across every week while summing expected across the
      // subset that has a reading would charge a player for games the model
      // never saw, and the gap would look like underperformance.
      let aHalf = 0, xHalf = 0, xg = 0;
      rows.forEach((r) => {
        if (r.xfp == null) return;
        aHalf += (r.fp || 0) - 0.5 * (r.rec || 0);
        xHalf += r.xfp - 0.5 * (r.xrec || 0);
        xg += 1;
      });
      row.fpoe = xg ? (aHalf - xHalf) / xg : null;

      // WOPR is defined on shares, so it only exists when both shares do.
      row.wopr = (tgtsh != null && airsh != null) ? 1.5 * tgtsh + 0.7 * airsh : null;
      if (raw.hasRoutes && rt > 0) {
        row.routes = rt / g;
        row.tprr = div(tg, rt);
        row.yprr = div(ry, rt);
      }
      // A player with no involvement at all in the window is noise in a table
      // meant for picking lineups.
      if (!row.g || (!tg && !ca && !att)) return;
      out.push(row);
    });

    attachSalaries(out);
    attachEdge(out);
    return out;
  }

  /* ---------- salaries and Edge ---------- */
  function attachSalaries(rows) {
    const slate = slateApplies() ? state.slate : null;
    if (!slate) { rows.forEach((r) => { r.sal = null; }); return; }
    const byName = new Map();
    slate.players.forEach((p) => {
      const k = nrm(p.n);
      // DK lists a player once per slate, but defences and duplicates exist;
      // first write wins so a stray entry cannot overwrite a real salary.
      if (!byName.has(k)) byName.set(k, p);
    });
    rows.forEach((r) => {
      const hit = byName.get(nrm(r.name));
      r.sal = hit ? hit.sal : null;
      if (hit && hit.tm) r.dkTm = team(hit.tm);
    });
  }

  /* Edge: usage rank minus salary rank, both within this position and window.
   * Usage is deliberately the same opportunity measure the position's table
   * leads with, so the number means what the columns above it say. */
  function attachEdge(rows) {
    const priced = rows.filter((r) => r.sal != null);
    if (priced.length < 8) { rows.forEach((r) => { r.edge = null; }); return; }
    const usageOf = (r) => {
      if (state.pos === 'QB') return r.dbpg != null ? r.dbpg + 2.2 * (r.rush || 0) : null;
      if (state.pos === 'RB') return (r.carsh || 0) + 1.4 * (r.tgtsh || 0) + 6 * (r.glc || 0);
      return r.wopr != null ? r.wopr : (r.tgtsh || 0);
    };
    const withUsage = priced.filter((r) => usageOf(r) != null);
    const byUsage = withUsage.slice().sort((a, b) => usageOf(b) - usageOf(a));
    const bySal = withUsage.slice().sort((a, b) => b.sal - a.sal);
    const uRank = new Map(byUsage.map((r, i) => [r.id, i + 1]));
    const sRank = new Map(bySal.map((r, i) => [r.id, i + 1]));
    rows.forEach((r) => {
      r.edge = (uRank.has(r.id) && sRank.has(r.id)) ? sRank.get(r.id) - uRank.get(r.id) : null;
    });
  }

  /* ---------- formatting ---------- */
  const PCT = new Set(['snap', 'tgtsh', 'airsh', 'carsh', 'cpoe', 'catch', 'cmppct']);
  /* Counting stats print whole on a totals basis and to one decimal per game. */
  const WHOLE = new Set(['sal', 'edge', 'g']);
  const TWO = new Set(['tprr', 'yprr', 'wopr', 'epa', 'ttt', 'ryoe', 'yacoe', 'sep']);
  /* Signed, because the sign is the whole message. */
  const SIGNED = new Set(['fpoe']);

  function fmt(k, v) {
    if (v == null || Number.isNaN(v)) return '—';
    if (k === 'name' || k === 'tm') return v;
    if (k === 'sal') return '$' + v.toLocaleString();
    if (k === 'edge') return (v > 0 ? '+' : '') + v;
    if (SIGNED.has(k)) return (v > 0 ? '+' : '') + v.toFixed(1);
    if (k === 'g') return String(v);
    if (COUNT_COLS.has(k)) return state.basis === 'pg' ? v.toFixed(1) : String(Math.round(v));
    if (PCT.has(k)) return v.toFixed(1) + '%';
    if (TWO.has(k)) return v.toFixed(2);
    return v.toFixed(1);
  }

  /* ---------- render ---------- */
  /* A DraftKings slate prices the upcoming week of the CURRENT season. Showing
   * it beside a past season's stats would put next week's salary next to last
   * year's usage, and Edge would be ranking one against the other. So salary
   * and Edge exist only on the season the slate belongs to. */
  const slateApplies = () => !!state.slate && state.index
    && +state.season === +state.index.current;

  /* Columns that open every view: who he is, what he costs, what he scored.
   * Edge closes every view for the same reason — it is the verdict column. */
  const LEAD = new Set(['name', 'tm', 'g', 'sal', 'hppr', 'ppr', 'fpoe']);

  function visibleCols() {
    const adv = COLS[state.pos].filter((c) => !LEAD.has(c[0]) && c[0] !== 'edge');
    const lead = COLS[state.pos].filter((c) => LEAD.has(c[0]));
    const edge = COLS[state.pos].filter((c) => c[0] === 'edge');
    const std = STD[state.pos] || [];

    let cols;
    if (state.view === 'std') cols = lead.concat(std, edge);
    else if (state.view === 'adv') cols = lead.concat(adv, edge);
    else cols = lead.concat(std, adv, edge);

    if (!state.raw || !state.raw.hasRoutes) cols = cols.filter((c) => !ROUTE_COLS.has(c[0]));
    if (!state.raw || !state.raw.hasExp) cols = cols.filter((c) => !EXP_COLS.has(c[0]));
    if (!slateApplies()) cols = cols.filter((c) => c[0] !== 'sal' && c[0] !== 'edge');
    // FPOE is an advanced read, so it stays out of the plain box score view.
    if (state.view === 'std') cols = cols.filter((c) => c[0] !== 'fpoe');
    return cols;
  }

  /* A counting column's header says which basis it is on, so a season total is
   * never read as a per-game average. Rates get no suffix because they are the
   * same number either way. */
  function headerFor(k, label) {
    if (!COUNT_COLS.has(k)) return label;
    return state.basis === 'pg' ? label + '/g' : label;
  }

  /* The stored value is always the window TOTAL; per game divides here. Doing it
   * at render time rather than in agg() means the two bases cannot disagree. */
  function cellValue(r, k) {
    const v = r[k];
    if (v == null) return null;
    if (COUNT_COLS.has(k) && state.basis === 'pg') return r.g ? v / r.g : null;
    return v;
  }

  function render() {
    const cols = visibleCols();
    // A sort key can vanish when the column set changes (switching to a season
    // with no routes while sorted by TPRR), which would silently sort by
    // nothing. Fall back instead.
    if (!cols.some((c) => c[0] === state.sort.key)) {
      state.sort = { key: defaultSortKey(), dir: -1 };
    }

    $('#nflTable thead tr').innerHTML = cols.map(([k, label, cls, tip]) => {
      const t = tip ? ` title="${tip.replace(/"/g, '&quot;')}"` : '';
      const on = state.sort.key === k ? ' sorted' : '';
      const arrow = state.sort.key === k ? (state.sort.dir === -1 ? ' ↓' : ' ↑') : '';
      return `<th class="${cls} sortable${on}" data-k="${k}"${t}>${headerFor(k, label)}${arrow}</th>`;
    }).join('');

    let rows = agg();
    if (state.q) {
      const q = state.q.toLowerCase();
      rows = rows.filter((r) => r.name.toLowerCase().includes(q)
        || r.tm.toLowerCase().includes(q) || (r.opp || '').toLowerCase().includes(q));
    }
    // When a slate is loaded, players who are not on it are not actionable.
    if (slateApplies() && $('#nflSlateOnly') && $('#nflSlateOnly').checked) {
      rows = rows.filter((r) => r.sal != null);
    }

    const { key, dir } = state.sort;
    rows.sort((a, b) => {
      // Sort on what the cell actually shows. Sorting the stored total while
      // displaying a per-game figure would order the table by a number that is
      // nowhere on screen.
      const x = cellValue(a, key), y = cellValue(b, key);
      if (typeof x === 'string' || typeof y === 'string') {
        return -dir * String(x || '').localeCompare(String(y || ''));
      }
      // Blanks always sink, whichever way the column is pointing, so an
      // ascending sort does not open with a screenful of dashes.
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return dir * (x - y);
    });

    $('#nflTable tbody').innerHTML = rows.map((r) => `<tr>${cols.map(([k, , cls]) => {
      let extra = '';
      if (k === 'edge' && r.edge != null) extra = r.edge > 0 ? ' up' : (r.edge < 0 ? ' down' : ' dim');
      if (k === 'fpoe' && r.fpoe != null) extra = r.fpoe > 0 ? ' up' : (r.fpoe < 0 ? ' down' : ' dim');
      if (k === 'name') extra = ' name';
      return `<td class="${cls}${extra}">${fmt(k, cellValue(r, k))}</td>`;
    }).join('')}</tr>`).join('');

    const span = state.from === state.to ? `week ${state.from}` : `weeks ${state.from}–${state.to}`;
    $('#nflCount').textContent = `— ${rows.length} ${state.pos}, ${span}`;

    $$('#nflTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
        render();
      });
    });
    renderEnv();
  }

  /* Game environment: pace and pass rate per team over the same window.
   * Vegas totals are not here because this site has no odds feed; what it does
   * have is how each offence actually behaved, which is the more stable input
   * anyway. */
  function renderEnv() {
    const raw = state.raw;
    if (!raw) return;
    const byTeam = new Map();
    Object.keys(raw.teams).forEach((k) => {
      const [tm, wk] = k.split('|');
      if (+wk < state.from || +wk > state.to) return;
      if (!byTeam.has(tm)) byTeam.set(tm, { tm, g: 0, plays: 0, db: 0, tg: 0, ca: 0, ay: 0 });
      const t = byTeam.get(tm), v = raw.teams[k];
      t.g += 1; t.plays += v.plays || 0; t.db += v.db || 0;
      t.tg += v.tg || 0; t.ca += v.ca || 0; t.ay += v.ay || 0;
    });
    const list = Array.from(byTeam.values())
      .filter((t) => t.g > 0 && t.plays > 0)
      .map((t) => ({
        tm: team(t.tm),
        plays: t.plays / t.g,
        pass: t.plays ? (t.db / t.plays) * 100 : 0,
        ay: t.db ? t.ay / t.db : 0,
      }))
      .sort((a, b) => b.plays - a.plays);
    $('#nflEnvTable tbody').innerHTML = list.map((t) => `<tr>
      <td class="name">${t.tm}</td>
      <td class="num">${t.plays.toFixed(1)}</td>
      <td class="num">${t.pass.toFixed(1)}%</td>
      <td class="num">${t.ay.toFixed(1)}</td>
    </tr>`).join('');
  }

  /* ---------- controls ---------- */
  function fillWeeks() {
    const weeks = state.raw.weeks;
    ['#nflFrom', '#nflTo'].forEach((sel) => {
      $(sel).innerHTML = weeks.map((w) => `<option value="${w}">Wk ${w}</option>`).join('');
    });
    $('#nflFrom').value = state.from;
    $('#nflTo').value = state.to;
  }

  function setWindow(from, to) {
    const weeks = state.raw.weeks;
    const lo = weeks[0], hi = weeks[weeks.length - 1];
    state.from = Math.max(lo, Math.min(hi, from));
    state.to = Math.max(state.from, Math.min(hi, to));
    $('#nflFrom').value = state.from;
    $('#nflTo').value = state.to;
    $$('.nflwin').forEach((b) => {
      const n = +b.dataset.win;
      b.classList.toggle('active',
        state.to === hi && (n === 0 ? state.from === lo : state.from === hi - n + 1));
    });
  }

  function renderMeta() {
    const bits = [];
    if (state.raw) {
      bits.push(`${state.season} season, through week ${state.raw.weeks[state.raw.weeks.length - 1]}`);
    }
    if (slateApplies()) bits.push(`${state.slate.name} salaries`);
    else if (state.slate) bits.push('salaries hidden: the slate is for '
      + `${state.index.current}, not ${state.season}`);
    else bits.push('no DraftKings slate loaded');
    $('#nflMeta').textContent = '— ' + bits.join(' · ');

    // The season can change after boot, so the slate controls have to be
    // re-evaluated here rather than once in fillSlates.
    const only = $('#nflSlateOnly');
    if (only) {
      only.disabled = !slateApplies();
      if (only.disabled) only.checked = false;
    }

    const note = $('#nflNote');
    if (!note) return;
    // A showdown prices one game on its own curve, so Edge compares a player
    // against six opponents rather than the week's whole field. Worth saying,
    // because the column looks identical either way.
    if (state.slate && state.slate.kind === 'showdown') {
      note.textContent = 'This is a single-game showdown slate. Its salaries run on their own '
        + 'curve, so Edge here ranks a player only against the others in that one game, not '
        + 'against the full slate. Pick a Main slate to compare across the week.';
      note.classList.remove('hidden');
      return;
    }
    if (state.raw && !state.raw.hasRoutes) {
      note.textContent = 'Routes, TPRR and YPRR need participation data, which nflverse has '
        + `not published for ${state.season} yet. Those columns are hidden for this season `
        + 'and will appear on their own once it lands. Earlier seasons have them now.';
      note.classList.remove('hidden');
    } else {
      note.classList.add('hidden');
    }
  }

  async function loadSeason(season) {
    const entry = state.index.seasons.find((s) => +s.season === +season);
    if (!entry) return;
    state.season = +season;
    const res = await fetch(DATA_DIR + entry.file + '?v=' + Date.now());
    state.raw = await res.json();
    const weeks = state.raw.weeks;
    // Opens on the full season. A trailing window is better for catching a role
    // that just changed, but it is a narrower claim than most people want from
    // a reference table, and the Last 1/3/5 buttons are one click away.
    state.from = weeks[0];
    state.to = weeks[weeks.length - 1];
    fillWeeks();
    setWindow(state.from, state.to);
    renderMeta();
    render();
  }

  function fillSlates() {
    const sel = $('#nflSlate');
    if (!state.dk || !state.dk.slates || !state.dk.slates.length) {
      sel.innerHTML = '<option>No slate posted</option>';
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    sel.innerHTML = state.dk.slates
      .map((s, i) => `<option value="${i}">${s.name}</option>`).join('');
    state.slate = state.dk.slates[0];
  }

  async function boot() {
    if (!document.getElementById('nfl')) return;
    try {
      const res = await fetch(DATA_DIR + 'nfl_index.json?v=' + Date.now());
      state.index = await res.json();
    } catch (e) {
      $('#nflMeta').textContent = '— stats feed unavailable';
      return;
    }
    $('#nflSeason').innerHTML = state.index.seasons
      .map((s) => `<option value="${s.season}">${s.season}</option>`).join('');

    // Salaries are optional: the DK lobby blocks our runner often enough that
    // the page must be fully usable without them.
    try {
      const res = await fetch(DATA_DIR + 'nfl_dk.json?v=' + Date.now());
      if (res.ok) state.dk = await res.json();
    } catch (e) { /* no salaries this run */ }
    fillSlates();

    await loadSeason(state.index.seasons[0].season);

    $('#nflSeason').addEventListener('change', (e) => loadSeason(e.target.value));
    $('#nflSlate').addEventListener('change', (e) => {
      state.slate = state.dk.slates[+e.target.value] || null;
      renderMeta();
      render();
    });
    $('#nflFrom').addEventListener('change', () => {
      setWindow(+$('#nflFrom').value, Math.max(+$('#nflFrom').value, state.to));
      render();
    });
    $('#nflTo').addEventListener('change', () => {
      setWindow(Math.min(state.from, +$('#nflTo').value), +$('#nflTo').value);
      render();
    });
    $$('.nflwin').forEach((b) => b.addEventListener('click', () => {
      const n = +b.dataset.win;
      const weeks = state.raw.weeks;
      const hi = weeks[weeks.length - 1];
      setWindow(n === 0 ? weeks[0] : hi - n + 1, hi);
      render();
    }));
    $$('.nflview').forEach((b) => b.addEventListener('click', () => {
      $$('.nflview').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.view = b.dataset.view;
      render();
    }));
    $$('.nflbasis').forEach((b) => b.addEventListener('click', () => {
      $$('.nflbasis').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.basis = b.dataset.basis;
      render();
    }));
    $$('.nflpos').forEach((b) => b.addEventListener('click', () => {
      $$('.nflpos').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.pos = b.dataset.pos;
      state.sort = { key: defaultSortKey(), dir: -1 };
      render();
    }));
    $('#nflSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    const only = $('#nflSlateOnly');
    if (only) {
      only.disabled = !slateApplies();
      only.addEventListener('change', render);
    }
  }

  document.addEventListener('DOMContentLoaded', boot);
})();
