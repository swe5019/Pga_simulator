/**
 * SlateSims lead endpoint — Cloudflare Worker.
 *
 * Replaces Formspree, whose free tier stops accepting submissions after 50 a
 * month and drops the rest silently. This owns the list, has no practical cap
 * on the free plan, and can actually be counted, which is what makes the lead
 * total on the admin page possible.
 *
 * Routes
 *   POST /lead          { email, source } -> { ok: true }
 *   GET  /count?key=…   -> { total, bySource, last7, recent[] }   (admin page)
 *   GET  /export?key=…  -> text/csv of every lead                  (admin page)
 *
 * The browser is the only caller for /lead, so CORS is restricted to the site's
 * own origins. /count and /export need the ADMIN_KEY secret; it is never put in
 * the repo or in admin.html, which is a public file — the admin page asks for
 * it and keeps it in that one browser.
 */

const ALLOWED_ORIGINS = new Set([
  'https://slatesims.com',
  'https://www.slatesims.com',
  'http://localhost:8777',
]);

// A public write endpoint will be found by bots. One address can be written
// this many times an hour before it is turned away.
const RATE_LIMIT = 20;

function cors(origin) {
  const allow = ALLOWED_ORIGINS.has(origin) ? origin : 'https://slatesims.com';
  return {
    'Access-Control-Allow-Origin': allow,
    'Access-Control-Allow-Methods': 'POST, GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

const json = (body, status, origin) => new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json', ...cors(origin) },
});

/** Deliberately permissive. The job is to reject obvious junk, not to argue
 *  with real addresses; over-strict validation loses more good leads than the
 *  bad ones it stops. */
function validEmail(e) {
  return typeof e === 'string' && e.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e);
}

/** Dedupe key. Case folding only — Gmail dot and plus tricks are left alone,
 *  because two addresses that differ there are still two real inboxes and
 *  collapsing them would lose a subscriber. */
const keyOf = (e) => e.trim().toLowerCase();

async function rateLimited(env, ip) {
  if (!ip) return false;
  const win = new Date().toISOString().slice(0, 13); // per hour
  const row = await env.DB.prepare('SELECT window, n FROM rate WHERE ip = ?')
    .bind(ip).first();
  if (!row || row.window !== win) {
    await env.DB.prepare(
      'INSERT INTO rate (ip, window, n) VALUES (?, ?, 1) '
      + 'ON CONFLICT(ip) DO UPDATE SET window = excluded.window, n = 1',
    ).bind(ip, win).run();
    return false;
  }
  if (row.n >= RATE_LIMIT) return true;
  await env.DB.prepare('UPDATE rate SET n = n + 1 WHERE ip = ?').bind(ip).run();
  return false;
}

async function handleLead(request, env, origin) {
  let body = {};
  try {
    const ct = request.headers.get('content-type') || '';
    if (ct.includes('application/json')) body = await request.json();
    else body = Object.fromEntries((await request.formData()).entries());
  } catch (e) {
    return json({ ok: false, error: 'bad body' }, 400, origin);
  }

  // Honeypot: a field no human ever sees, so anything in it is a bot. Answer
  // 200 so the bot believes it worked and does not come back to retry.
  if (body.company) return json({ ok: true }, 200, origin);

  const email = String(body.email || '').trim();
  if (!validEmail(email)) return json({ ok: false, error: 'invalid email' }, 400, origin);

  const ip = request.headers.get('cf-connecting-ip') || '';
  if (await rateLimited(env, ip)) {
    return json({ ok: false, error: 'rate limited' }, 429, origin);
  }

  const now = new Date().toISOString();
  const source = String(body.source || 'unknown').slice(0, 40);
  // One row per address. A repeat visit bumps the counter and the last-seen
  // date rather than adding a duplicate, so the total is a real subscriber
  // count and not a submission count.
  await env.DB.prepare(
    `INSERT INTO leads (email, email_key, source, first_seen, last_seen, hits, referrer, ua, country)
     VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
     ON CONFLICT(email_key) DO UPDATE SET
       last_seen = excluded.last_seen,
       hits = hits + 1,
       source = CASE WHEN leads.source = excluded.source
                     THEN leads.source
                     ELSE leads.source || '+' || excluded.source END`,
  ).bind(
    email, keyOf(email), source, now, now,
    (request.headers.get('referer') || '').slice(0, 300),
    (request.headers.get('user-agent') || '').slice(0, 300),
    request.headers.get('cf-ipcountry') || '',
  ).run();

  return json({ ok: true }, 200, origin);
}

function authed(url, env) {
  return env.ADMIN_KEY && url.searchParams.get('key') === env.ADMIN_KEY;
}

async function handleCount(url, env, origin) {
  if (!authed(url, env)) return json({ ok: false, error: 'unauthorized' }, 401, origin);
  const total = await env.DB.prepare('SELECT COUNT(*) AS n FROM leads').first();
  const bySource = await env.DB.prepare(
    'SELECT source, COUNT(*) AS n FROM leads GROUP BY source ORDER BY n DESC',
  ).all();
  const since = new Date(Date.now() - 7 * 864e5).toISOString();
  const last7 = await env.DB.prepare(
    'SELECT COUNT(*) AS n FROM leads WHERE first_seen >= ?',
  ).bind(since).first();
  const recent = await env.DB.prepare(
    'SELECT email, source, first_seen FROM leads ORDER BY id DESC LIMIT 25',
  ).all();
  return json({
    ok: true,
    total: total.n,
    last7: last7.n,
    bySource: bySource.results,
    recent: recent.results,
  }, 200, origin);
}

async function handleExport(url, env, origin) {
  if (!authed(url, env)) return json({ ok: false, error: 'unauthorized' }, 401, origin);
  const rows = await env.DB.prepare(
    'SELECT email, source, first_seen, last_seen, hits, country FROM leads ORDER BY id',
  ).all();
  const esc = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
  const csv = ['email,source,first_seen,last_seen,hits,country']
    .concat(rows.results.map((r) => [r.email, r.source, r.first_seen, r.last_seen,
      r.hits, r.country].map(esc).join(',')))
    .join('\n');
  return new Response(csv, {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="slatesims-leads.csv"',
      ...cors(origin),
    },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('origin') || '';
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: cors(origin) });
    }
    if (request.method === 'POST' && url.pathname === '/lead') {
      return handleLead(request, env, origin);
    }
    if (request.method === 'GET' && url.pathname === '/count') {
      return handleCount(url, env, origin);
    }
    if (request.method === 'GET' && url.pathname === '/export') {
      return handleExport(url, env, origin);
    }
    return json({ ok: false, error: 'not found' }, 404, origin);
  },
};
