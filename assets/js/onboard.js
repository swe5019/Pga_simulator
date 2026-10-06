/* ============================================================
 * onboard.js — free-signup access panel wiring
 * ------------------------------------------------------------
 * The actual hide/show of the app is done with the "locked" class
 * on <html>, set synchronously by an inline <script> in app.html's
 * <head> (so it can't be skipped by a blocked/slow external file).
 * This script only wires the entry form's submit handler and clears
 * "locked" once a visitor signs up. No backend on this site, so this
 * is a soft client-side gate, not real security — it makes "free
 * signup" the front door and captures every lead via Formspree.
 * ============================================================ */
const ONBOARD_KEY = 'slatesims_access_granted';
const ONBOARD_FORMSPREE = 'https://formspree.io/f/mvzjronw';
const ONBOARD_CONTACT_EMAIL = 'steve@slatesims.com';

function onboardBackupLead(fields) {
  try {
    const key = 'birdie_leads';
    const all = JSON.parse(localStorage.getItem(key) || '[]');
    all.push({ kind: 'app-entry', ...fields, ts: Date.now() });
    localStorage.setItem(key, JSON.stringify(all));
  } catch (e) { /* ignore */ }
}

function onboardGrant() {
  try { localStorage.setItem(ONBOARD_KEY, '1'); } catch (e) { /* ignore */ }
  document.documentElement.classList.remove('locked');
}

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('entryForm');
  const note = document.getElementById('entryNote');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    // Tag the origin so PGA, NFL and landing-page leads can be told apart in
    // the Formspree inbox. leadgate.js sends the same field.
    if (!fd.has('source')) fd.append('source', 'PGA');
    const fields = Object.fromEntries(fd.entries());
    onboardBackupLead(fields);
    note.textContent = 'Unlocking…';
    note.className = 'entrynote';

    // leadgate.js owns the Worker-then-Formspree-then-mailto chain, so the PGA
    // gate and the NFL unlock send leads the same way and only one place needs
    // changing when the endpoint moves.
    if (window.LeadGate && typeof window.LeadGate.submit === 'function') {
      await window.LeadGate.submit(fields.email, 'PGA');
      onboardGrant();
      return;
    }

    let ok = false;
    try {
      const res = await fetch(ONBOARD_FORMSPREE, { method: 'POST', headers: { Accept: 'application/json' }, body: fd });
      ok = res.ok;
    } catch (err) { ok = false; }

    if (!ok) {
      // Formspree unreachable — don't block access over a network hiccup;
      // fall back to mailto so the lead still reaches us, then let them in.
      window.location.href =
        `mailto:${ONBOARD_CONTACT_EMAIL}?subject=${encodeURIComponent('New SlateSims app access signup')}` +
        `&body=${encodeURIComponent('email: ' + fields.email)}`;
    }
    onboardGrant();
  });
});
