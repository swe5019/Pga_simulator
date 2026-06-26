/* ============================================================
 * landing.js — SlateSims landing page interactions
 * ------------------------------------------------------------
 * Form handling for sign-up / free-trial, feedback, and contact.
 *
 * Lead delivery works out of the box via a mailto fallback (opens
 * the visitor's email client to CONTACT_EMAIL). To collect leads
 * automatically with no email client, create a free Formspree form
 * (https://formspree.io) and paste its endpoint into FORMSPREE_*
 * below — submissions then POST straight to your inbox/dashboard.
 * ============================================================ */
const CONTACT_EMAIL = 'ebeck2317@gmail.com';

// Optional: paste a Formspree (or similar) endpoint to auto-collect leads.
// e.g. 'https://formspree.io/f/abcdwxyz'. Leave '' to use the mailto fallback.
const FORMSPREE_SIGNUP = '';
const FORMSPREE_FEEDBACK = '';

const $ = (s) => document.querySelector(s);

/** POST a form to an endpoint (Formspree-style). Returns true on success. */
async function postForm(endpoint, data) {
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { Accept: 'application/json' },
      body: data,
    });
    return res.ok;
  } catch (e) {
    return false;
  }
}

/** Build + open a mailto with the form contents (no-backend fallback). */
function mailtoFallback(subject, fields) {
  const body = Object.entries(fields)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}: ${v}`)
    .join('\n');
  window.location.href =
    `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`;
}

/** Keep a local backup of leads so nothing is ever lost. */
function backupLead(kind, fields) {
  try {
    const key = 'birdie_leads';
    const all = JSON.parse(localStorage.getItem(key) || '[]');
    all.push({ kind, ...fields, ts: Date.now() });
    localStorage.setItem(key, JSON.stringify(all));
  } catch (e) {
    /* ignore */
  }
}

function setNote(el, msg, cls) {
  el.textContent = msg;
  el.className = 'formnote ' + (cls || '');
}

/** Generic submit handler: try Formspree, else mailto. */
function wireForm(formSel, noteSel, endpoint, subject, kind) {
  const form = $(formSel);
  const note = $(noteSel);
  if (!form) return;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const fields = Object.fromEntries(fd.entries());
    backupLead(kind, fields);
    setNote(note, 'Sending…', '');
    if (endpoint) {
      const ok = await postForm(endpoint, fd);
      if (ok) {
        form.reset();
        setNote(note, "✓ You're in — we'll be in touch shortly. Welcome to SlateSims!", 'ok');
        return;
      }
      setNote(note, 'Network hiccup — opening your email app instead…', 'err');
    }
    mailtoFallback(subject, fields);
    setNote(note, "✓ Thanks! Finish in your email app and we'll get you set up.", 'ok');
  });
}

document.addEventListener('DOMContentLoaded', () => {
  const yr = $('#yr');
  if (yr) yr.textContent = new Date().getFullYear();

  // Pricing CTA → preselect plan and jump to the form.
  document.querySelectorAll('[data-plan]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const plan = $('#signupPlan');
      if (plan) plan.value = btn.dataset.plan;
      const note = $('#signupNote');
      if (note) setNote(note, `Great pick — starting your ${btn.dataset.plan} free trial. Drop your email below.`, 'ok');
    });
  });

  wireForm('#signupForm', '#signupNote', FORMSPREE_SIGNUP,
    'SlateSims free trial request', 'signup');
  wireForm('#feedbackForm', '#feedbackNote', FORMSPREE_FEEDBACK,
    'SlateSims feedback', 'feedback');
});
