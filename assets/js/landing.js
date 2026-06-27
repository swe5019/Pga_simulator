/* ============================================================
 * landing.js — SlateSims landing page interactions
 * ------------------------------------------------------------
 * Form handling for sign-up (beta access) and feedback.
 *
 * Setup (one-time, ~2 min):
 *   1. Create a free account at https://formspree.io (verify with
 *      steve@slatesims.com or whatever inbox should get the leads).
 *   2. Create two forms (or one, reused for both) and copy each
 *      form's endpoint, e.g. 'https://formspree.io/f/abcdwxyz'.
 *   3. Paste the endpoints into FORMSPREE_SIGNUP / FORMSPREE_FEEDBACK
 *      below.
 * Formspree then emails CONTACT_EMAIL on every submission, AND
 * auto-emails the visitor a welcome reply (the message is set via
 * the hidden _autoresponse field on each <form> in index.html).
 * Until an endpoint is set, submissions fall back to opening the
 * visitor's email client (mailto) — still captured, just manual.
 * ============================================================ */
const CONTACT_EMAIL = 'steve@slatesims.com';

// Paste your Formspree (or similar) endpoints here to go live with
// auto-collected leads + auto-reply emails. Leave '' to use the
// mailto fallback in the meantime.
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
    .filter(([k, v]) => v && !k.startsWith('_'))
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
      if (note) setNote(note, `Great pick — ${btn.dataset.plan} noted for when the beta wraps. Drop your email below for beta access.`, 'ok');
    });
  });

  wireForm('#signupForm', '#signupNote', FORMSPREE_SIGNUP,
    'SlateSims free trial request', 'signup');
  wireForm('#feedbackForm', '#feedbackNote', FORMSPREE_FEEDBACK,
    'SlateSims feedback', 'feedback');
});
