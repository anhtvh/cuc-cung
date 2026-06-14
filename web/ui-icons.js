/* ════════════════════════════════════════════════════════════
   ui-icons.js — line-icon system + chrome (theme toggle, mobile nav)
   Load TRƯỚC app.js. Định nghĩa global: svgIcon(), domainIcon.
   ════════════════════════════════════════════════════════════ */

const _IP = {
  bot: '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 8V4.5M9.5 4.5h5"/><circle cx="9.2" cy="14" r="1.1"/><circle cx="14.8" cy="14" r="1.1"/><path d="M2 13v3M22 13v3"/>',
  sparkle: '<path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z"/>',
  fire: '<path d="M12 3c1 3-1 4-1 6a3 3 0 0 0 6 0c0-1-.4-2-1-2.6 1.8 1 3 3 3 5.6a6 6 0 0 1-12 0c0-3.5 3-5 5-9z"/>',
  legal: '<path d="M12 3v18M7 21h10M5 7h14M5 7l-2 6a4 4 0 0 0 8 0L9 7M19 7l-2 6a4 4 0 0 0 8 0l-2-6"/>',
  finance: '<rect x="2" y="6" width="20" height="13" rx="2"/><circle cx="12" cy="12.5" r="2.5"/><path d="M6 6V4h12v2"/>',
  sales: '<path d="M3 3v18h18"/><path d="M7 14l3-3 3 2 4-5"/>',
  hr: '<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5.5a3 3 0 0 1 0 5.5M21 20a5.5 5.5 0 0 0-4-5.3"/>',
  ops: '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.4l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2.4-1.4L13.7 2h-3.4l-.4 2.8a7 7 0 0 0-2.4 1.4l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2.4 1.4l.4 2.8h3.4l.4-2.8a7 7 0 0 0 2.4-1.4l2.4 1 2-3.4-2-1.6A7 7 0 0 0 19 12z"/>',
  it: '<path d="M8 8l-4 4 4 4M16 8l4 4-4 4M13 5l-2 14"/>',
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.6-.7L3 21l1.4-4.2A8.4 8.4 0 0 1 12 3a8.4 8.4 0 0 1 9 8.5z"/>',
  loader: '<path d="M12 3a9 9 0 1 0 9 9" stroke-linecap="round"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  xmark: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  search: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M2 12h20M12 2a14 14 0 0 1 0 20M12 2a14 14 0 0 0 0 20"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
};

function svgIcon(name, attrs) {
  const p = _IP[name] || _IP.bot;
  return '<svg class="ic" ' + (attrs || "") + ' viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + p + '</svg>';
}

const domainIcon = {
  legal: svgIcon("legal"), finance: svgIcon("finance"), sales: svgIcon("sales"),
  hr: svgIcon("hr"), ops: svgIcon("ops"), it: svgIcon("it"),
};

/* ─── Theme toggle (sáng/tối) + mobile nav burger ─────────── */
(function initChrome() {
  const root = document.documentElement;
  try {
    const saved = localStorage.getItem("cc-theme");
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (_) {}

  const tt = document.getElementById("theme-toggle");
  if (tt) tt.addEventListener("click", function () {
    const cur = root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = cur === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("cc-theme", next); } catch (_) {}
  });

  const burger = document.getElementById("nav-burger");
  const nav = document.getElementById("nav");
  if (burger && nav) {
    burger.addEventListener("click", function (e) { e.stopPropagation(); nav.classList.toggle("open"); });
    nav.querySelectorAll(".tab").forEach(function (t) { t.addEventListener("click", function () { nav.classList.remove("open"); }); });
    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target) && e.target !== burger && !burger.contains(e.target)) nav.classList.remove("open");
    });
  }
})();
