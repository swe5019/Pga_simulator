/* ============================================================
 * gate.js — free-signup access gate for app.html
 * ------------------------------------------------------------
 * No backend on this site, so this is a client-side soft gate:
 * it covers the app with a free email signup until submitted,
 * then remembers the visitor in this browser (localStorage) so
 * it doesn't ask again. It's not real security — a technical
 * visitor could bypass it — but it makes "free signup, no card"
 * the entry point and captures every lead, same as the landing
 * page's Formspree form.
 * ============================================================ */
const GATE_KEY = 'slatesims_access_granted';
const GATE_FORMSPREE = 'https://formspree.io/f/mvzjronw';
const GATE_CONTACT_EMAIL = 'steve@slatesims.com';

function gateHasAccess() {
  try { return !!localStorage.getItem(GATE_KEY); } catch (e) { return false; }
}

function gateGrant() {
  try { localStorage.setItem(GATE_KEY, '1'); } catch (e) { /* ignore */ }
}

function gateBackupLead(fields) {
  try {
    const key = 'birdie_leads';
    const all = JSON.parse(localStorage.getItem(key) || '[]');
    all.push({ kind: 'app-gate', ...fields, ts: Date.now() });
    localStorage.setItem(key, JSON.stringify(all));
  } catch (e) { /* ignore */ }
}

function initGate() {
  if (gateHasAccess()) return;

  const overlay = document.createElement('div');
  overlay.className = 'gate';
  overlay.innerHTML = `
    <div class="gatecard">
      <h2>Free beta access</h2>
      <p>SlateSims is free during the beta. Drop your email and you're straight in — no
        credit card, no cost.</p>
      <form id="gateForm">
        <input type="email" name="email" required placeholder="you@email.com" autocomplete="email" />
        <input type="hidden" name="_subject" value="New SlateSims app access signup" />
        <input type="hidden" name="_autoresponse" value="Thanks for signing up for the SlateSims beta! Your access is unlocked — jump back in any time at https://slatesims.com/app.html, no login needed (your data stays in your browser). We'd love your feedback after this week's tournament; just reply to this email. — Steve, SlateSims" />
        <button type="submit" class="primary">Get free access →</button>
      </form>
      <p class="gatenote" id="gateNote"></p>
      <p class="gatemicro">No credit card · No spam · Unlocks this browser instantly</p>
    </div>`;
  document.body.appendChild(overlay);
  document.body.style.overflow = 'hidden';

  const form = overlay.querySelector('#gateForm');
  const note = overlay.querySelector('#gateNote');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const fields = Object.fromEntries(fd.entries());
    gateBackupLead(fields);
    note.textContent = 'Unlocking…';
    note.className = 'gatenote';

    let ok = false;
    try {
      const res = await fetch(GATE_FORMSPREE, { method: 'POST', headers: { Accept: 'application/json' }, body: fd });
      ok = res.ok;
    } catch (err) { ok = false; }

    if (!ok) {
      // Formspree unreachable — don't block access over a network hiccup;
      // fall back to mailto so the lead still reaches us, then let them in.
      window.location.href =
        `mailto:${GATE_CONTACT_EMAIL}?subject=${encodeURIComponent('New SlateSims app access signup')}` +
        `&body=${encodeURIComponent('email: ' + fields.email)}`;
    }
    gateGrant();
    overlay.remove();
    document.body.style.overflow = '';
  });
}

document.addEventListener('DOMContentLoaded', initGate);
