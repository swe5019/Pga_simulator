/* ============================================================
 * nfl.js — NFL advanced stats tab (MOCKUP)
 * ------------------------------------------------------------
 * Self-contained on purpose: it touches no golf State, no sim,
 * no optimizer. Everything here is sample data so the layout and
 * interactions can be judged before any real feed is wired up.
 *
 * If this ships for real, the numbers would come from nflverse
 * (nflfastR) weekly player stats, which are published as static
 * files in GitHub releases — fetchable by a workflow exactly like
 * fetch-dk.yml, and with no API edge that can block the runner.
 * ============================================================ */
(function () {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));

  // Column sets per position. NFL stats are position-specific, so one table
  // across all four would be mostly blank cells — the switcher swaps these.
  const COLS = {
    WR: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['opp', 'Opp', ''],
      ['sal', 'Sal', 'num'],
      ['snap', 'Snap%', 'num', 'Share of offensive snaps'],
      ['routes', 'Routes', 'num', 'Routes run per game'],
      ['tprr', 'TPRR', 'num', 'Targets per route run — the cleanest usage rate'],
      ['tgtsh', 'Tgt%', 'num', 'Share of team targets'],
      ['adot', 'aDOT', 'num', 'Average depth of target'],
      ['airsh', 'Air%', 'num', 'Share of team air yards'],
      ['wopr', 'WOPR', 'num', 'Weighted opportunity rating: target share + air yards share'],
      ['rz', 'RZ', 'num', 'Red zone targets per game'],
      ['yprr', 'YPRR', 'num', 'Yards per route run — efficiency'],
      ['edge', 'Edge', 'num', 'Usage rank minus salary rank. Positive means underpriced for his role.'],
    ],
    TE: null, // same shape as WR
    RB: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['opp', 'Opp', ''],
      ['sal', 'Sal', 'num'],
      ['snap', 'Snap%', 'num', 'Share of offensive snaps'],
      ['carsh', 'Car%', 'num', 'Share of team carries'],
      ['rz', 'RZ', 'num', 'Red zone carries per game'],
      ['gl', 'GL', 'num', 'Goal line carries per game'],
      ['tgtsh', 'Tgt%', 'num', 'Share of team targets — what separates RB1s in PPR'],
      ['ybc', 'YBC', 'num', 'Yards before contact per attempt — blocking'],
      ['yac', 'YAC', 'num', 'Yards after contact per attempt — the back himself'],
      ['edge', 'Edge', 'num', 'Usage rank minus salary rank. Positive means underpriced for his role.'],
    ],
    QB: [
      ['name', 'Player', ''], ['tm', 'Tm', ''], ['opp', 'Opp', ''],
      ['sal', 'Sal', 'num'],
      ['db', 'DB', 'num', 'Dropbacks per game'],
      ['adot', 'aDOT', 'num', 'Average depth of target'],
      ['prs', 'Prs%', 'num', 'Pressure rate faced'],
      ['ttt', 'TTT', 'num', 'Time to throw, seconds'],
      ['cpoe', 'CPOE', 'num', 'Completion percentage over expected'],
      ['epa', 'EPA', 'num', 'EPA per dropback'],
      ['rush', 'Rush', 'num', 'Rush attempts per game — the DFS separator at QB'],
      ['edge', 'Edge', 'num', 'Usage rank minus salary rank. Positive means underpriced for his role.'],
    ],
  };
  COLS.TE = COLS.WR;

  // Sample rows. Deliberately plausible rather than accurate — this is a layout
  // mockup, and the banner says so.
  const DATA = {
    WR: [
      { name: 'Puka Nacua', tm: 'LAR', opp: 'SEA', sal: 8600, snap: 94, routes: 38, tprr: 0.29, tgtsh: 31.2, adot: 9.1, airsh: 34, wopr: 0.81, rz: 1.7, yprr: 2.61, edge: 4 },
      { name: 'Jaxon Smith-Njigba', tm: 'SEA', opp: 'LAR', sal: 7900, snap: 91, routes: 36, tprr: 0.27, tgtsh: 28.8, adot: 8.4, airsh: 30, wopr: 0.74, rz: 1.3, yprr: 2.44, edge: 6 },
      { name: 'Rome Odunze', tm: 'CHI', opp: 'MIN', sal: 6200, snap: 88, routes: 34, tprr: 0.24, tgtsh: 25.1, adot: 12.6, airsh: 33, wopr: 0.69, rz: 1.1, yprr: 2.02, edge: 11 },
      { name: 'Ladd McConkey', tm: 'LAC', opp: 'DEN', sal: 6800, snap: 86, routes: 33, tprr: 0.25, tgtsh: 24.6, adot: 7.9, airsh: 26, wopr: 0.63, rz: 1.4, yprr: 2.31, edge: 5 },
      { name: 'Jordan Addison', tm: 'MIN', opp: 'CHI', sal: 5900, snap: 83, routes: 31, tprr: 0.22, tgtsh: 22.4, adot: 11.2, airsh: 28, wopr: 0.60, rz: 0.9, yprr: 1.88, edge: 8 },
      { name: 'Tetairoa McMillan', tm: 'CAR', opp: 'ATL', sal: 5400, snap: 90, routes: 35, tprr: 0.26, tgtsh: 27.3, adot: 10.4, airsh: 31, wopr: 0.72, rz: 1.2, yprr: 1.74, edge: 14 },
      { name: 'Khalil Shakir', tm: 'BUF', opp: 'NE', sal: 5100, snap: 79, routes: 29, tprr: 0.21, tgtsh: 19.8, adot: 5.6, airsh: 16, wopr: 0.44, rz: 0.7, yprr: 2.12, edge: -2 },
      { name: 'Xavier Worthy', tm: 'KC', opp: 'LV', sal: 6400, snap: 81, routes: 32, tprr: 0.20, tgtsh: 20.6, adot: 13.1, airsh: 29, wopr: 0.58, rz: 0.8, yprr: 1.66, edge: -3 },
      { name: 'Keon Coleman', tm: 'BUF', opp: 'NE', sal: 4600, snap: 72, routes: 27, tprr: 0.18, tgtsh: 17.2, adot: 14.8, airsh: 27, wopr: 0.53, rz: 0.9, yprr: 1.59, edge: 9 },
      { name: 'Jalen McMillan', tm: 'TB', opp: 'NO', sal: 3800, snap: 68, routes: 25, tprr: 0.16, tgtsh: 14.9, adot: 9.7, airsh: 18, wopr: 0.39, rz: 0.6, yprr: 1.41, edge: 3 },
    ],
    TE: [
      { name: 'Brock Bowers', tm: 'LV', opp: 'KC', sal: 7100, snap: 92, routes: 35, tprr: 0.27, tgtsh: 28.4, adot: 7.2, airsh: 24, wopr: 0.67, rz: 1.6, yprr: 2.38, edge: 2 },
      { name: 'Trey McBride', tm: 'ARI', opp: 'SF', sal: 6600, snap: 89, routes: 33, tprr: 0.26, tgtsh: 26.9, adot: 6.4, airsh: 21, wopr: 0.62, rz: 1.4, yprr: 2.19, edge: 4 },
      { name: 'Tucker Kraft', tm: 'GB', opp: 'DET', sal: 4900, snap: 78, routes: 28, tprr: 0.21, tgtsh: 19.3, adot: 8.1, airsh: 19, wopr: 0.48, rz: 1.1, yprr: 2.04, edge: 10 },
      { name: 'Colston Loveland', tm: 'CHI', opp: 'MIN', sal: 3600, snap: 71, routes: 26, tprr: 0.19, tgtsh: 16.8, adot: 7.6, airsh: 15, wopr: 0.40, rz: 0.8, yprr: 1.72, edge: 7 },
      { name: 'Dalton Kincaid', tm: 'BUF', opp: 'NE', sal: 4200, snap: 69, routes: 24, tprr: 0.17, tgtsh: 15.1, adot: 6.9, airsh: 13, wopr: 0.35, rz: 0.7, yprr: 1.55, edge: -4 },
    ],
    RB: [
      { name: 'Bijan Robinson', tm: 'ATL', opp: 'CAR', sal: 9200, snap: 82, carsh: 68, rz: 3.4, gl: 1.6, tgtsh: 14.2, ybc: 2.9, yac: 3.4, edge: 1 },
      { name: 'Jahmyr Gibbs', tm: 'DET', opp: 'GB', sal: 8800, snap: 61, carsh: 54, rz: 2.8, gl: 1.1, tgtsh: 12.8, ybc: 3.2, yac: 3.1, edge: 3 },
      { name: 'Omarion Hampton', tm: 'LAC', opp: 'DEN', sal: 6900, snap: 74, carsh: 71, rz: 3.1, gl: 1.4, tgtsh: 8.4, ybc: 2.4, yac: 2.9, edge: 8 },
      { name: 'Kenneth Walker III', tm: 'SEA', opp: 'LAR', sal: 6100, snap: 58, carsh: 59, rz: 2.6, gl: 1.2, tgtsh: 9.1, ybc: 2.1, yac: 3.3, edge: 5 },
      { name: 'Chase Brown', tm: 'CIN', opp: 'BAL', sal: 5800, snap: 69, carsh: 63, rz: 2.2, gl: 0.9, tgtsh: 11.6, ybc: 2.6, yac: 2.8, edge: 6 },
      { name: 'Tyrone Tracy Jr.', tm: 'NYG', opp: 'DAL', sal: 4700, snap: 64, carsh: 57, rz: 1.9, gl: 0.7, tgtsh: 10.3, ybc: 2.2, yac: 3.0, edge: 12 },
      { name: 'Rhamondre Stevenson', tm: 'NE', opp: 'BUF', sal: 4300, snap: 52, carsh: 49, rz: 1.7, gl: 0.8, tgtsh: 7.9, ybc: 1.9, yac: 2.6, edge: -5 },
    ],
    QB: [
      { name: 'Lamar Jackson', tm: 'BAL', opp: 'CIN', sal: 8400, db: 36, adot: 9.4, prs: 24, ttt: 2.91, cpoe: 5.1, epa: 0.24, rush: 8.2, edge: 2 },
      { name: 'Jayden Daniels', tm: 'WAS', opp: 'PHI', sal: 8100, db: 38, adot: 8.1, prs: 27, ttt: 2.78, cpoe: 4.4, epa: 0.19, rush: 7.6, edge: 4 },
      { name: 'Josh Allen', tm: 'BUF', opp: 'NE', sal: 8600, db: 37, adot: 8.9, prs: 22, ttt: 2.84, cpoe: 3.2, epa: 0.21, rush: 6.1, edge: -1 },
      { name: 'Caleb Williams', tm: 'CHI', opp: 'MIN', sal: 6300, db: 40, adot: 9.8, prs: 31, ttt: 3.06, cpoe: 1.6, epa: 0.09, rush: 4.8, edge: 9 },
      { name: 'Bo Nix', tm: 'DEN', opp: 'LAC', sal: 5700, db: 39, adot: 7.2, prs: 26, ttt: 2.69, cpoe: 0.8, epa: 0.06, rush: 5.2, edge: 6 },
      { name: 'Drake Maye', tm: 'NE', opp: 'BUF', sal: 6000, db: 41, adot: 8.6, prs: 33, ttt: 2.97, cpoe: 2.9, epa: 0.11, rush: 4.1, edge: 7 },
    ],
  };

  const ENV = [
    { tm: 'BUF', tot: 27.5, spd: -7.5, plays: 66, proe: 4.2 },
    { tm: 'LAR', tot: 25.0, spd: -2.5, plays: 64, proe: 2.8 },
    { tm: 'BAL', tot: 26.5, spd: -3.0, plays: 65, proe: 1.4 },
    { tm: 'DET', tot: 26.0, spd: -2.0, plays: 67, proe: -0.6 },
    { tm: 'CHI', tot: 23.5, spd: 1.5, plays: 68, proe: 6.1 },
    { tm: 'SEA', tot: 22.5, spd: 2.5, plays: 63, proe: 3.3 },
    { tm: 'KC', tot: 24.5, spd: -5.5, plays: 62, proe: 0.9 },
    { tm: 'CAR', tot: 19.5, spd: 4.5, plays: 61, proe: 7.4 },
  ];

  const state = { pos: 'WR', win: 'L3', q: '', sort: { key: 'edge', dir: -1 } };

  const fmt = (k, v) => {
    if (v == null) return '—';
    if (k === 'sal') return '$' + v.toLocaleString();
    if (k === 'edge') return (v > 0 ? '+' : '') + v;
    if (['tprr', 'wopr', 'yprr', 'epa', 'ttt', 'ybc', 'yac'].includes(k)) return v.toFixed(2);
    if (['snap', 'tgtsh', 'airsh', 'carsh', 'prs'].includes(k)) return v.toFixed(1) + '%';
    if (typeof v === 'number' && !Number.isInteger(v)) return v.toFixed(1);
    return v;
  };

  function render() {
    const cols = COLS[state.pos];
    const head = $('#nflTable thead tr');
    head.innerHTML = cols.map(([k, label, cls, tip]) => {
      const t = tip ? ` title="${tip}"` : '';
      const on = state.sort.key === k ? ' sorted' : '';
      return `<th class="${cls} sortable${on}" data-k="${k}"${t}>${label}</th>`;
    }).join('');

    let rows = DATA[state.pos].slice();
    if (state.q) {
      const q = state.q.toLowerCase();
      rows = rows.filter((r) => r.name.toLowerCase().includes(q) ||
                                r.tm.toLowerCase().includes(q) ||
                                (r.opp || '').toLowerCase().includes(q));
    }
    const { key, dir } = state.sort;
    // dir -1 is descending (biggest first), which is what every numeric column
    // here wants on first click: highest usage, highest salary, biggest edge.
    rows.sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === 'string') return -dir * x.localeCompare(y);
      return dir * ((x == null ? -1e9 : x) - (y == null ? -1e9 : y));
    });

    $('#nflTable tbody').innerHTML = rows.map((r) => `<tr>${cols.map(([k, , cls]) => {
      let extra = '';
      if (k === 'edge') extra = r.edge > 0 ? ' up' : (r.edge < 0 ? ' down' : ' dim');
      if (k === 'name') extra = ' name';
      return `<td class="${cls}${extra}">${fmt(k, r[k])}</td>`;
    }).join('')}</tr>`).join('');

    $('#nflCount').textContent = `— ${rows.length} ${state.pos}, ` +
      (state.win === 'S' ? 'season' : 'last ' + state.win.slice(1));
    $('#nflEnvTable tbody').innerHTML = ENV
      .slice().sort((a, b) => b.tot - a.tot)
      .map((e) => `<tr>
        <td class="name">${e.tm}</td>
        <td class="num">${e.tot.toFixed(1)}</td>
        <td class="num dim">${e.spd > 0 ? '+' : ''}${e.spd.toFixed(1)}</td>
        <td class="num">${e.plays}</td>
        <td class="num ${e.proe > 0 ? 'up' : 'down'}">${e.proe > 0 ? '+' : ''}${e.proe.toFixed(1)}</td>
      </tr>`).join('');

    $$('#nflTable th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const k = th.dataset.k;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
        render();
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('nfl')) return;
    $('#nflMeta').textContent = '— Week 5, sample slate';
    $$('.nflpos').forEach((b) => b.addEventListener('click', () => {
      $$('.nflpos').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.pos = b.dataset.pos;
      state.sort = { key: 'edge', dir: -1 };
      render();
    }));
    $$('.nflwin').forEach((b) => b.addEventListener('click', () => {
      $$('.nflwin').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      state.win = b.dataset.win;
      render();
    }));
    $('#nflSearch').addEventListener('input', (e) => { state.q = e.target.value; render(); });
    render();
  });
})();
