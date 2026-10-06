/* ============================================================
 * leadgate.js — email capture shared by the PGA app and the NFL page.
 *
 * TWO DIFFERENT GATES, ON PURPOSE.
 *
 * The PGA app is a HARD gate: html.locked hides the whole shell until an email
 * is given (that part lives in onboard.js and app.html's inline head script).
 * That page is a tool, not content, and it has nothing to lose in search.
 *
 * The NFL page is a SOFT gate. It is the only page on the site a search engine
 * can actually read — hiding it put its indexable word count at zero. So the
 * page stays fully open and crawlable: the weekly leaders, the standard box
 * score, the explainer and the current season are free to everyone, including
 * crawlers. An email unlocks the advanced metrics, DraftKings salaries, Edge
 * and past seasons. Nothing a visitor can see is hidden from a crawler, which
 * is the line that separates a paywall from cloaking.
 *
 * Both write to the same Formspree endpoint, tagged with a source so you can
 * tell where a lead came from.
 *
 * FORMSPREE FREE TIER CAPS AT 50 SUBMISSIONS PER MONTH. Over that, posts are
 * rejected and leads are lost. This cannot be counted from here — a static page
 * has no way to read your Formspree total — so it has to be watched on the
 * Formspree dashboard. Every submission is also mirrored into localStorage, but
 * that is per browser and is a crash backup, not a list you can export.
 * ============================================================ */
(function () {
  const KEY = 'slatesims_access_granted';
  const ENDPOINT = 'https://formspree.io/f/mvzjronw';
  const CONTACT = 'steve@slatesims.com';

  function granted() {
    try { return !!localStorage.getItem(KEY); } catch (e) { return false; }
  }

  function grant() {
    try { localStorage.setItem(KEY, '1'); } catch (e) { /* private mode */ }
  }

  function backup(fields) {
    try {
      const all = JSON.parse(localStorage.getItem('birdie_leads') || '[]');
      all.push({ ...fields, ts: Date.now() });
      localStorage.setItem('birdie_leads', JSON.stringify(all));
    } catch (e) { /* ignore */ }
  }

  /* Returns true when the lead is away (or we gave up and let them in anyway).
   * A network problem must never cost someone access: they gave us the email,
   * which is the thing we actually wanted. */
  async function submit(email, source) {
    const fields = { email, source, _subject: `SlateSims ${source} signup` };
    backup(fields);
    try {
      const body = new FormData();
      Object.entries(fields).forEach(([k, v]) => body.append(k, v));
      const res = await fetch(ENDPOINT, {
        method: 'POST', headers: { Accept: 'application/json' }, body,
      });
      if (res.ok) return true;
    } catch (e) { /* fall through */ }
    // Formspree unreachable or over its monthly cap. Hand the lead to mail so
    // it is not silently dropped, then let them in regardless.
    try {
      window.open(`mailto:${CONTACT}?subject=${encodeURIComponent('SlateSims ' + source + ' signup')}`
        + `&body=${encodeURIComponent('email: ' + email)}`, '_blank');
    } catch (e) { /* ignore */ }
    return false;
  }

  let overlay = null;

  function close() {
    if (overlay) overlay.classList.remove('open');
  }

  function build() {
    overlay = document.createElement('div');
    overlay.className = 'lg-overlay';
    overlay.innerHTML = `
      <div class="lg-card" role="dialog" aria-modal="true" aria-labelledby="lgTitle">
        <button class="lg-x" type="button" aria-label="Close">×</button>
        <h2 id="lgTitle">Free — just your email</h2>
        <p class="lg-why"></p>
        <form class="lg-form">
          <input type="email" name="email" required placeholder="you@email.com"
                 autocomplete="email" />
          <button type="submit" class="primary">Unlock →</button>
        </form>
        <p class="lg-note" aria-live="polite"></p>
        <p class="lg-micro">No credit card · No spam · Unlocks this browser instantly</p>
      </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('.lg-x').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
    overlay.querySelector('.lg-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = overlay.querySelector('input[name=email]');
      const note = overlay.querySelector('.lg-note');
      note.textContent = 'Unlocking…';
      const ok = await submit(input.value.trim(), overlay.dataset.source || 'app');
      grant();
      note.textContent = ok ? 'You’re in.' : 'You’re in.';
      close();
      if (typeof overlay._onGrant === 'function') overlay._onGrant();
    });
    return overlay;
  }

  /* why: one line naming the thing they just tried to use, so the ask is
   * obviously connected to the click that triggered it. */
  function prompt(why, source, onGrant) {
    if (!overlay) build();
    overlay.querySelector('.lg-why').textContent = why;
    overlay.dataset.source = source;
    overlay._onGrant = onGrant;
    overlay.classList.add('open');
    setTimeout(() => {
      const i = overlay.querySelector('input[name=email]');
      if (i) i.focus();
    }, 30);
  }

  window.LeadGate = { granted, prompt, submit, grant };
})();
