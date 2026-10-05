/* ============================================================
 * nav.js — the sport menubar shared by every page.
 *
 * Click opens a menu; once one is open, hovering a sibling switches to it,
 * which is how every desktop menubar behaves and what stops the nav feeling
 * sticky when you are scanning across sports. Escape, outside-click and
 * focus-loss all close.
 *
 * The markup is duplicated in each page rather than injected here on purpose:
 * injected nav flashes empty on first paint, and on a static site that flash
 * is the first thing a visitor sees.
 * ============================================================ */
(function () {
  const items = Array.from(document.querySelectorAll('.navitem'));
  if (!items.length) return;

  let open = null;

  function close() {
    if (!open) return;
    open.classList.remove('open');
    const btn = open.querySelector('.navbtn');
    if (btn) btn.setAttribute('aria-expanded', 'false');
    open = null;
  }

  function show(item) {
    if (open === item) return;
    close();
    item.classList.add('open');
    const btn = item.querySelector('.navbtn');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    open = item;
  }

  items.forEach((item) => {
    const btn = item.querySelector('.navbtn');
    if (!btn) return;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (open === item) close(); else show(item);
    });
    // Only switch on hover while a menu is already open. Opening on plain
    // hover would fire every time the pointer crosses the header on its way
    // somewhere else.
    item.addEventListener('mouseenter', () => { if (open) show(item); });
  });

  document.addEventListener('click', (e) => {
    if (open && !open.contains(e.target)) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && open) {
      const btn = open.querySelector('.navbtn');
      close();
      if (btn) btn.focus();
    }
  });
  // A menu left open behind a new page is the classic back-button artefact.
  window.addEventListener('pagehide', close);
})();
