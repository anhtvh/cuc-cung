/* ════════════════════════════════════════════════════════════
   bg-fx.js — nền đốm sao lấp lánh (vanilla, 1 canvas)
   • 3 tầng hạt vẽ bằng radial-gradient mềm (không viền cứng):
       – Glow blobs (~90–130px, teal/xanh lá, opacity 0.08–0.15, 4–5 cái)
       – Medium stars (~14–26px, trắng/xanh, opacity 0.35–0.55, ~26 cái)
       – Tiny dots (~5–9px, opacity 0.15–0.28, ~50 cái)
   • Phân bố grid ngầm + jitter → không cluster, không quá đều
   • Lấp lánh: opacity dao động, chu kỳ lệch nhau (3s/5s/7s…) tránh đồng bộ
   • Trôi rất nhẹ; con trỏ: quầng glow + sao gần sáng lên; click: shockwave
   Canvas cố định sau nội dung, pointer-events:none → không chặn UI.
   ════════════════════════════════════════════════════════════ */
(function () {
  if (window.__bgfx) return;
  window.__bgfx = true;

  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const canvas = document.createElement("canvas");
  canvas.id = "bg-fx";
  canvas.setAttribute("aria-hidden", "true");
  Object.assign(canvas.style, {
    position: "fixed", inset: "0", width: "100%", height: "100%",
    zIndex: "0", pointerEvents: "none", display: "block",
  });
  const ctx = canvas.getContext("2d", { alpha: true });

  function mount() {
    if (document.getElementById("bg-fx")) return;
    document.body.insertBefore(canvas, document.body.firstChild);
  }
  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount);

  let W = 0, H = 0, DPR = 1;
  let particles = [];
  const shocks = [];
  let gridSprite = null, blobSprites = [];
  let starHalo = null, glowTeal = null, glowGreen = null, glowWhite = null;
  let isDark = false;

  const pointer = { x: -9999, y: -9999, active: false };

  /* ─── theme ─── */
  function readTheme() {
    const attr = document.documentElement.getAttribute("data-theme");
    isDark = attr ? attr === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  }
  const COL = {
    blue: "46,134,255", blueDeep: "0,104,255", green: "0,201,92",
    teal: "26,196,178", white: "236,244,255",
  };

  /* ─── soft radial-gradient sprite (vẽ 1 lần, drawImage + scale mỗi frame) ─── */
  function makeSoftSprite(size, rgb, stops) {
    const s = document.createElement("canvas");
    s.width = size; s.height = size;
    const c = s.getContext("2d");
    const r = size / 2;
    const g = c.createRadialGradient(r, r, 0, r, r, r);
    for (const st of stops) g.addColorStop(st[0], "rgba(" + rgb + "," + st[1] + ")");
    c.fillStyle = g;
    c.fillRect(0, 0, size, size);
    return s;
  }
  function buildSprites() {
    // chỉ glow halo + blob là mềm; dot/nhân sao vẽ solid sắc nét (không qua sprite mờ)
    starHalo  = makeSoftSprite(64, COL.white, [[0, 0.9], [0.5, 0.32], [1, 0]]); // quầng mềm sau nhân sao
    glowTeal  = makeSoftSprite(256, COL.teal,  [[0, 0.16], [0.7, 0.04], [1, 0]]);
    glowGreen = makeSoftSprite(256, COL.green, [[0, 0.14], [0.7, 0.035], [1, 0]]);
    glowWhite = makeSoftSprite(256, COL.white, [[0, 0.12], [0.7, 0.03], [1, 0]]);
  }

  /* ─── sizing ─── */
  function resize() {
    DPR = Math.min(window.devicePixelRatio || 1, 1.75);
    W = window.innerWidth;
    H = window.innerHeight;
    canvas.width = Math.round(W * DPR);
    canvas.height = Math.round(H * DPR);
    canvas.style.width = W + "px";
    canvas.style.height = H + "px";
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    buildGrid();
    buildBlobs();
    if (!starHalo) buildSprites();
    initParticles();
  }

  /* ─── distribution: grid ngầm + jitter ─── */
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      const t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function makeFieldParticle(x, y, isStar) {
    const period = [3, 4, 5, 6, 7][Math.floor(Math.random() * 5)] + Math.random() * 1.6; // giây
    const tw = Math.random() < (isStar ? 0.72 : 0.45);
    return {
      tier: isStar ? 1 : 2,
      x, y, pvx: 0, pvy: 0, mvx: 0, mvy: 0,
      dang: Math.random() * Math.PI * 2,
      dsp: isStar ? 0.04 + Math.random() * 0.10 : 0.03 + Math.random() * 0.08, // trôi rất nhẹ
      drift: (Math.random() < 0.5 ? 1 : -1) * (0.0005 + Math.random() * 0.0012),
      size: isStar ? 5 + Math.random() * 3 : 2 + Math.random() * 1.4, // medium 5–8px, tiny 2–3.4px
      alpha: isStar ? 0.78 + Math.random() * 0.18 : 0.6 + Math.random() * 0.2, // sáng, sắc nét
      tw, minTw: isStar ? 0.55 : 0.62,
      twSp: (Math.PI * 2) / (period * 60),
      twPh: Math.random() * Math.PI * 2,
      _glow: 0,
    };
  }

  function placeField(nStar, nDot) {
    const total = nStar + nDot;
    const aspect = W / H;
    const cols = Math.max(3, Math.round(Math.sqrt(total * aspect)));
    const rows = Math.max(3, Math.ceil(total / cols));
    const cells = [];
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) cells.push([c, r]);
    shuffle(cells);
    const cw = W / cols, ch = H / rows;
    for (let i = 0; i < total; i++) {
      const cell = cells[i];
      const x = (cell[0] + 0.12 + Math.random() * 0.76) * cw; // jitter trong ô
      const y = (cell[1] + 0.12 + Math.random() * 0.76) * ch;
      particles.push(makeFieldParticle(x, y, i < nStar));
    }
  }

  function placeGlow(n) {
    for (let i = 0; i < n; i++) {
      const period = 8 + Math.random() * 6;
      particles.push({
        tier: 0,
        glowColor: Math.random() < 0.34 ? "teal" : (Math.random() < 0.5 ? "green" : "white"),
        x: (0.12 + 0.76 * ((i + 0.5) / n) + (Math.random() - 0.5) * 0.22) * W,
        y: (0.18 + Math.random() * 0.62) * H,
        pvx: 0, pvy: 0, mvx: 0, mvy: 0,
        dang: Math.random() * Math.PI * 2,
        dsp: 0.02 + Math.random() * 0.05,
        drift: (Math.random() < 0.5 ? 1 : -1) * (0.0004 + Math.random() * 0.0008),
        size: 110 + Math.random() * 90,       // 110–200px
        alpha: 0.7 + Math.random() * 0.3,      // sprite đã rất mờ; alpha này chỉ điều biến nhẹ
        tw: true, minTw: 0.55,
        twSp: (Math.PI * 2) / (period * 60),
        twPh: Math.random() * Math.PI * 2,
        _glow: 0,
      });
    }
  }

  function initParticles() {
    particles = [];
    const af = clamp((W * H) / (1440 * 900), 0.7, 1.9); // co giãn theo diện tích màn
    const nStar = Math.round((reduce ? 16 : 26) * af);
    const nDot  = Math.round((reduce ? 28 : 50) * af);
    const nGlow = (W > 1700 ? 5 : 4);
    placeGlow(nGlow);          // tầng glow vẽ trước → sao nằm trên
    placeField(nStar, nDot);
  }

  /* ─── grid sprite ─── */
  function buildGrid() {
    const g = document.createElement("canvas");
    g.width = Math.round(W * DPR);
    g.height = Math.round(H * DPR);
    const c = g.getContext("2d");
    c.setTransform(DPR, 0, 0, DPR, 0, 0);
    const step = 46;
    c.strokeStyle = isDark ? "rgba(150,190,255,0.05)" : "rgba(20,60,140,0.04)";
    c.lineWidth = 1;
    c.beginPath();
    for (let x = (W % step) / 2; x <= W; x += step) { c.moveTo(x + 0.5, 0); c.lineTo(x + 0.5, H); }
    for (let y = (H % step) / 2; y <= H; y += step) { c.moveTo(0, y + 0.5); c.lineTo(W, y + 0.5); }
    c.stroke();
    gridSprite = g;
  }

  /* ─── ambient corner glow (wash màu nền) ─── */
  function makeBlob(rgb, radius) {
    const s = document.createElement("canvas");
    const d = Math.ceil(radius * 2);
    s.width = d; s.height = d;
    const c = s.getContext("2d");
    const grad = c.createRadialGradient(radius, radius, 0, radius, radius, radius);
    grad.addColorStop(0, "rgba(" + rgb + ",0.5)");
    grad.addColorStop(0.45, "rgba(" + rgb + ",0.2)");
    grad.addColorStop(1, "rgba(" + rgb + ",0)");
    c.fillStyle = grad;
    c.beginPath();
    c.arc(radius, radius, radius, 0, Math.PI * 2);
    c.fill();
    return { cv: s, r: radius };
  }
  function buildBlobs() {
    const base = Math.min(W, H);
    blobSprites = [
      { sp: makeBlob(COL.blue, base * 0.64), cx: W * 0.22, cy: H * 0.28, ax: W * 0.16, ay: H * 0.14, t: 0, ts: 0.00026 },
      { sp: makeBlob(COL.green, base * 0.56), cx: W * 0.82, cy: H * 0.20, ax: W * 0.15, ay: H * 0.17, t: 1.7, ts: 0.00022 },
      { sp: makeBlob(COL.blueDeep, base * 0.50), cx: W * 0.6, cy: H * 0.85, ax: W * 0.17, ay: H * 0.13, t: 3.1, ts: 0.00024 },
    ];
  }

  /* ─── pointer / touch ─── */
  function setPointer(x, y) { pointer.x = x; pointer.y = y; pointer.active = true; }
  function clearPointer() { pointer.active = false; pointer.x = -9999; pointer.y = -9999; }
  function addShock(x, y) {
    shocks.push({ x, y, r: 0, power: 7.5, max: Math.hypot(W, H) * 0.6 });
    if (shocks.length > 6) shocks.shift();
  }
  window.addEventListener("pointermove", (e) => setPointer(e.clientX, e.clientY), { passive: true });
  window.addEventListener("pointerdown", (e) => { setPointer(e.clientX, e.clientY); addShock(e.clientX, e.clientY); }, { passive: true });
  window.addEventListener("pointerout", (e) => { if (!e.relatedTarget) clearPointer(); }, { passive: true });
  window.addEventListener("blur", clearPointer);
  window.addEventListener("touchend", clearPointer, { passive: true });

  /* ─── physics ─── */
  const CURSOR_R = 168, CURSOR_R2 = CURSOR_R * CURSOR_R;
  const AVOID_R = 130, AVOID_R2 = AVOID_R * AVOID_R;

  function step() {
    for (let i = shocks.length - 1; i >= 0; i--) {
      const s = shocks[i];
      s.r += 13;
      s.power *= 0.965;
      if (s.r > s.max || s.power < 0.25) shocks.splice(i, 1);
    }

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.twPh += p.twSp; // tiến pha lấp lánh

      p.dang += p.drift;
      const bvx = Math.cos(p.dang) * p.dsp;
      const bvy = Math.sin(p.dang) * p.dsp;

      let ax = 0, ay = 0;

      // tương tác con trỏ + shockwave chỉ cho sao/dot (tier !== 0)
      if (p.tier !== 0) {
        if (pointer.active) {
          const dx = p.x - pointer.x, dy = p.y - pointer.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < AVOID_R2 && d2 > 0.01) {
            const d = Math.sqrt(d2);
            const f = (1 - d / AVOID_R);
            const push = f * f * 2.0;
            ax += (dx / d) * push;
            ay += (dy / d) * push;
          }
        }
        for (let k = 0; k < shocks.length; k++) {
          const s = shocks[k];
          const dx = p.x - s.x, dy = p.y - s.y;
          const d = Math.hypot(dx, dy) || 1;
          const ring = Math.abs(d - s.r);
          if (ring < 64) {
            const f = (1 - ring / 64) * s.power;
            ax += (dx / d) * f;
            ay += (dy / d) * f;
          }
        }
      }

      p.pvx = (p.pvx + ax) * 0.9;
      p.pvy = (p.pvy + ay) * 0.9;
      p.mvx = bvx + p.pvx;
      p.mvy = bvy + p.pvy;
      p.x += p.mvx;
      p.y += p.mvy;

      const m = p.tier === 0 ? p.size : 40;
      if (p.x < -m) p.x = W + m; else if (p.x > W + m) p.x = -m;
      if (p.y < -m) p.y = H + m; else if (p.y > H + m) p.y = -m;
    }
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // ambient corner wash
    ctx.globalCompositeOperation = "lighter";
    for (let i = 0; i < blobSprites.length; i++) {
      const b = blobSprites[i];
      b.t += b.ts * 16;
      const x = b.cx + Math.cos(b.t) * b.ax - b.sp.r;
      const y = b.cy + Math.sin(b.t * 0.9) * b.ay - b.sp.r;
      ctx.globalAlpha = isDark ? 0.66 : 0.5;
      ctx.drawImage(b.sp.cv, x, y);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";

    // grid
    if (gridSprite) ctx.drawImage(gridSprite, 0, 0, W, H);

    // cursor halo + brighten nearby stars
    if (pointer.active) {
      const halo = ctx.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, CURSOR_R * 0.7);
      halo.addColorStop(0, "rgba(" + COL.green + ",0.14)");
      halo.addColorStop(1, "rgba(" + COL.green + ",0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(pointer.x, pointer.y, CURSOR_R * 0.7, 0, Math.PI * 2);
      ctx.fill();
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        if (p.tier === 0) continue;
        const dx = p.x - pointer.x, dy = p.y - pointer.y;
        const d2 = dx * dx + dy * dy;
        p._glow = d2 < CURSOR_R2 ? (1 - d2 / CURSOR_R2) : 0;
      }
    } else if (particles.length && particles[particles.length - 1]._glow) {
      for (let i = 0; i < particles.length; i++) particles[i]._glow = 0;
    }

    // shockwave rings
    for (let k = 0; k < shocks.length; k++) {
      const s = shocks[k];
      const al = Math.max(0, s.power / 7.5) * 0.32;
      ctx.strokeStyle = "rgba(" + COL.green + "," + al.toFixed(3) + ")";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.lineWidth = 1;

    // particles — mỗi tầng vẽ khác nhau: blob mềm / sao sắc+glow / dot solid sắc nét
    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      let f = 1;
      if (p.tw) f = p.minTw + (1 - p.minTw) * (0.5 + 0.5 * Math.sin(p.twPh));
      const glow = p._glow || 0;

      if (p.tier === 0) {
        // ── glow blob: radial-gradient mềm, lớn — element duy nhất được phép mờ
        const sprite = p.glowColor === "teal" ? glowTeal : (p.glowColor === "green" ? glowGreen : glowWhite);
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = clamp(p.alpha * f, 0, 1);
        ctx.drawImage(sprite, p.x - p.size / 2, p.y - p.size / 2, p.size, p.size);
        ctx.globalCompositeOperation = "source-over";
        ctx.globalAlpha = 1;
        continue;
      }

      let a = clamp(p.alpha * f + glow * 0.4, 0, 1);
      const isStar = p.tier === 1;

      if (isStar) {
        // ── medium star: quầng glow mềm (≈ box-shadow) + nhân trắng sắc nét
        const halo = (p.size * 3.2) * (1 + glow * 0.5);
        ctx.globalCompositeOperation = "lighter";
        ctx.globalAlpha = clamp((0.6 + glow * 0.4) * f, 0, 1);
        ctx.drawImage(starHalo, p.x - halo / 2, p.y - halo / 2, halo, halo);
        ctx.globalCompositeOperation = "source-over";
        ctx.globalAlpha = 1;
      }

      // ── nhân solid sắc nét (dot + tâm sao) — không blur
      const r = (p.size / 2) * (1 + glow * 0.5);
      ctx.fillStyle = (glow > 0.04 && isStar)
        ? "rgba(" + COL.white + "," + a.toFixed(3) + ")"
        : "rgba(255,255,255," + a.toFixed(3) + ")";
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  let running = true;
  function loop() {
    if (running) { step(); draw(); }
    requestAnimationFrame(loop);
  }
  document.addEventListener("visibilitychange", () => { running = !document.hidden; });

  let rt = null;
  window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(resize, 160); });

  const themeObserver = new MutationObserver(() => { readTheme(); buildGrid(); });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  if (matchMedia) {
    try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { readTheme(); buildGrid(); buildBlobs(); }); } catch (_) {}
  }

  readTheme();
  resize();
  step();
  draw();
  requestAnimationFrame(loop);
})();
