/* Agent Hub UI — vanilla JS, chỉ gọi REST API. */

const $ = (sel) => document.querySelector(sel);

const state = {
  userId: "guest",    // backward compat — sync từ /auth/me
  user: null,         // { role, email, name, picture } | null (guest)
  stickyAgent: null,  // agent đang route của cuộc hiện tại (gửi làm agent_name)
  activeConvId: null, // thread key của cuộc hiện tại (uuid); null = chưa có cuộc (welcome)
  ragEnabled: false,  // module RAG bật? (từ /auth/me) — quyết định hiện mục Tài liệu
  attachment: null,
  // Map<conversationId, {key, agentName, agentMeta, container, lastText, updatedAt, title, titleSent}>
  convStore: new Map(),
  streaming: new Set(),     // conversation_id đang có stream chạy (chưa kết thúc)
  pendingDelete: new Set(), // conversation_id user đã xoá khi đang stream → DELETE sau khi stream xong
};

// Gọi khi stream của 1 cuộc kết thúc: nếu user đã xoá cuộc đó giữa chừng thì DELETE server NGAY
// BÂY GIỜ (server đã ghi xong memory/conv_meta trong finally) → cuộc không tái xuất (fix #3).
function finishStream(convId) {
  state.streaming.delete(convId);
  if (state.pendingDelete.has(convId)) {
    state.pendingDelete.delete(convId);
    fetch(`/history/${encodeURIComponent(convId)}`, { method: "DELETE", headers: headers() }).catch(() => {});
  }
}

// Sinh conversation_id mới (mỗi "cuộc trò chuyện" độc lập, cho phép nhiều cuộc/agent).
function newConvId() {
  if (window.crypto?.randomUUID) return crypto.randomUUID();
  return "c-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

/* svgIcon + domainIcon: định nghĩa trong ui-icons.js (load trước app.js) */

function headers(extra = {}) {
  // Cookie được gửi tự động (same-origin) — không cần header auth thêm
  return { ...extra };
}

/* ─── Auth state ────────────────────────────────────────── */
async function loadAuthState() {
  try {
    const me = await fetch("/auth/me").then((r) => r.json());
    state.ragEnabled = !!me.rag_enabled;  // bật/tắt mục tài liệu (RAG) trong UI
    if (me.role === "guest") {
      state.user = null;
      state.userId = "guest";
      if (!me.guest_mode) {
        // GUEST_MODE=false — bắt buộc login, không được đóng modal
        openAuthModal(false);
      }
    } else {
      state.user = me;
      state.userId = me.email;
    }
  } catch (_) {
    state.user = null;
    state.userId = "guest";
  }
  renderUserPill();
  refreshTabsForUser();
}

function renderUserPill() {
  const pill = $("#user-pill");
  if (!pill) return;
  if (state.user) {
    const initials = (state.user.name || state.user.email || "?")[0].toUpperCase();
    const avatar = state.user.picture
      ? `<img src="${esc(state.user.picture)}" class="user-avatar-img" referrerpolicy="no-referrer">`
      : `<div class="user-avatar">${initials}</div>`;
    pill.innerHTML = `
      <div class="user-info-pill" onclick="toggleUserMenu(event)">
        ${avatar}
        <span class="user-display-name">${esc(state.user.name || state.user.email)}</span>
        <span class="user-role-badge ${state.user.role}">${state.user.role === "admin" ? "Admin" : ""}</span>
        <span style="font-size:10px;opacity:.5">▾</span>
      </div>
      <div class="user-dropdown" id="user-dropdown" hidden>
        <div class="user-dd-email">${esc(state.user.email)}</div>
        <hr style="border-color:rgba(255,255,255,.08);margin:6px 0">
        <a class="user-dd-item" onclick="doLogout()">Đăng xuất</a>
      </div>`;
  } else {
    pill.innerHTML = `<button class="btn-login" onclick="openAuthModal(true)">Đăng nhập</button>`;
  }
}

function toggleUserMenu(e) {
  e.stopPropagation();
  const dd = $("#user-dropdown");
  if (dd) dd.hidden = !dd.hidden;
}
document.addEventListener("click", () => {
  const dd = $("#user-dropdown");
  if (dd) dd.hidden = true;
});

async function doLogout() {
  await fetch("/auth/logout", { method: "POST" });
  state.user = null;
  state.userId = "guest";
  state.stickyAgent = null;
  state.activeConvId = null;
  state.convStore.clear();
  renderUserPill();
  refreshTabsForUser();
  loadCatalog();
  loadHomeAgents();
  $("#messages").innerHTML = "";
  updateChatHeader(null);
  renderSidebar();
  showWelcome();
}

/* ─── Auth modal ────────────────────────────────────────── */
let _authModalRequired = false;

function openAuthModal(canClose = true) {
  _authModalRequired = !canClose;
  $("#auth-modal").hidden = false;
  const closeBtn = $("#auth-modal-close");
  if (closeBtn) closeBtn.hidden = !canClose;
  const guestNote = $("#auth-guest-note");
  if (guestNote) guestNote.hidden = !canClose;
  // Ẩn Google button nếu không có config — FE tự check qua feature probe
  fetch("/auth/google").then((r) => {
    if (r.status === 501) {
      const gs = $("#auth-google-section");
      if (gs) gs.hidden = true;
      const div = $("#auth-divider");
      if (div) div.hidden = true;
    }
  }).catch(() => {});
}

function closeAuthModal() {
  if (_authModalRequired) return;
  $("#auth-modal").hidden = true;
  $("#auth-error").textContent = "";
}

window.loginGoogle = function() {
  window.location.href = "/auth/google";
};

window.submitAdminLogin = async function() {
  const email = $("#admin-email").value.trim();
  const password = $("#admin-password").value;
  const errEl = $("#auth-error");
  errEl.textContent = "";
  if (!email || !password) { errEl.textContent = "Nhập email và mật khẩu"; return; }
  try {
    const r = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) {
      const d = await r.json();
      errEl.textContent = d.detail || "Đăng nhập thất bại";
      return;
    }
    // Re-fetch /auth/me để lấy full user object (login response thiếu id, picture)
    const me = await fetch("/auth/me").then((r2) => r2.json());
    state.user = me.role === "guest" ? null : me;
    state.userId = me.email || email;
    $("#auth-modal").hidden = true;
    renderUserPill();
    refreshTabsForUser();
    loadCatalog();
    loadHomeAgents();
    restoreHistoryFromServer();
  } catch (_) {
    errEl.textContent = "Lỗi kết nối, thử lại";
  }
};

function refreshTabsForUser() {
  const isAdmin = state.user?.role === "admin";
  const isLoggedIn = !!state.user;
  $("#review-tab").hidden = !isAdmin;
  $("#stats-tab").hidden = !isAdmin;
  // Guest vẫn xem được tab "Của tôi" để xem/dùng trial agents họ đã tạo
  $("#myagents-tab").hidden = false;
  const guestCta = $("#home-guest-cta");
  if (guestCta) guestCta.hidden = isLoggedIn;
  // Sidebar chỉ show với logged-in user
  const sidebar = $("#chat-sidebar");
  if (sidebar) sidebar.style.display = isLoggedIn ? "" : "none";
  if (!isAdmin && ($("#panel-review").classList.contains("active") || $("#panel-stats").classList.contains("active"))) switchTab("home");
}

/* ─── Tabs ──────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => switchTab(btn.dataset.tab))
);

window.switchTab = function(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (name === "catalog")  loadCatalog();
  if (name === "review")   loadReview();
  if (name === "home")     loadHomeAgents();
  if (name === "stats")    loadStats();
  if (name === "myagents") loadMyAgents();
  if (name === "chat" && !$("#messages").children.length) showWelcome();
};

/* ─── Home ──────────────────────────────────────────────── */
let _homeAgentsAll = [];

async function loadHomeAgents() {
  try {
    const data = await fetch("/agents", { headers: headers() }).then((r) => r.json());
    _homeAgentsAll = data;
  } catch (_) {}
  renderHomeAgents();
}

function renderHomeAgents() {
  const q = ($("#home-search")?.value || "").toLowerCase();
  const domain = _homeActiveDomain || "";

  const active = _homeAgentsAll.filter((a) => {
    if (a.status !== "public") return false;
    if (domain && a.domain !== domain) return false;
    if (q && !(a.name + " " + (a.tagline || "") + " " + a.description).toLowerCase().includes(q)) return false;
    return true;
  });

  const cards = active.map((a) => {
    const callsBadge = a.calls >= 5
      ? `<span class="ahc-popular">${svgIcon("fire")} Phổ biến</span>`
      : a.calls > 0
        ? `<span class="ahc-calls">${a.calls} lần</span>`
        : "";
    return `<div class="ahc" onclick="startChatWith('${escJs(a.name)}','${escJs(a.tagline || a.description)}')">
      <span class="ahc-icon">${domainIcon[a.domain] || svgIcon("bot")}</span>
      <div class="ahc-name">${esc(a.name)}${callsBadge}</div>
      <div class="ahc-slug">@${esc(a.slug || a.name)}</div>
      <div class="ahc-desc">${esc(a.tagline || a.description.split(/[.。]/)[0].slice(0, 80))}</div>
      <div class="ahc-tag"><span class="tag">${esc(a.domain || "general")}</span></div>
    </div>`;
  });

  cards.push(`
    <div class="ahc new-card" onclick="startBuilderChat()">
      <span class="ahc-icon">✨</span>
      <div class="ahc-name">Tạo agent mới</div>
      <div class="ahc-desc">Chat với Cục cưng để tạo agent chuyên biệt theo nghiệp vụ của bạn — không cần code.</div>
      <div class="ahc-tag"><span class="tag" style="color:#a5b4fc;background:rgba(99,102,241,.12)">builder</span></div>
    </div>`);

  if (active.length === 0 && (q || domain)) {
    $("#home-agent-grid").innerHTML = `<p class="empty">Không tìm thấy agent phù hợp</p>`;
    // Vẫn thêm nút tạo agent mới
    $("#home-agent-grid").innerHTML += cards[cards.length - 1];
    return;
  }
  $("#home-agent-grid").innerHTML = cards.join("");
}

let _homeActiveDomain = "";

// app.js chạy sau khi DOM đã ready (script ở cuối <body>) — không cần DOMContentLoaded
$("#home-search")?.addEventListener("input", renderHomeAgents);
$("#home-domain-tabs")?.querySelectorAll(".hdt").forEach((btn) => {
  btn.addEventListener("click", () => {
    _homeActiveDomain = btn.dataset.domain;
    $("#home-domain-tabs").querySelectorAll(".hdt").forEach((b) => b.classList.toggle("active", b === btn));
    renderHomeAgents();
  });
});

window.startChatWith = function(name, desc) {
  // Bấm 1 agent → mở CUỘC MỚI với agent đó (thread riêng, cho phép nhiều cuộc/agent).
  saveCurrentConv();
  const convId = newConvId();
  state.activeConvId = convId;
  state.stickyAgent = name;
  _lastRoutedAgent = null;
  _seenHandoffAgents = new Set();
  updateChatHeader(name);
  $("#messages").innerHTML = "";
  const agentData = _agentsCache.find((a) => a.name === name);
  state.convStore.set(convId, { key: convId, agentName: name, agentMeta: agentData ? { domain: agentData.domain } : null, lastText: "", updatedAt: Date.now(), title: null, titleSent: true });
  renderSidebar();
  switchTab("chat");
  if (name === "master") {
    addHandoff("master", "");
  } else {
    addHandoff(name, desc);
    // Auto-trigger khi agent có skill — gửi mention @slug để backend kích hoạt auto_start
    if (agentData?.skills?.length > 0) {
      setTimeout(() => {
        // Chỉ trigger nếu vẫn ở đúng cuộc này và user chưa gõ gì (không ghi đè input).
        if (state.activeConvId === convId && !$("#chat-input").value.trim()) {
          _triggerAgentAutoStart(name, agentData.slug || name);
        }
      }, 350);
    }
  }
};

/* ─── Welcome (chat tab, no messages) ──────────────────── */
async function showWelcome() {
  const msgs = $("#messages");
  if (msgs.children.length > 0) return;

  let agents = [];
  try { agents = await fetch("/agents", { headers: headers() }).then((r) => r.json()); } catch (_) {}
  const active = agents.filter((a) => a.status === "public");
  // #8: đảm bảo có mẫu cho panel "Tạo từ mẫu" (cache rỗng nếu boot fetch chưa xong/ lỗi).
  if (!_templatesCache.length) await loadTemplates();

  const rawName = state.user ? (state.user.name || state.user.email).split(/[@. ]/)[0] : "bạn";
  const hello = rawName.charAt(0).toUpperCase() + rawName.slice(1);
  const welcome = document.createElement("div");
  welcome.id = "welcome";

  const quickCards = active.slice(0, 6).map((a) => {
    const hint = a.tagline || a.description.split(/[.。]/)[0].slice(0, 48);
    return `<button class="wcard" data-msg="${esc(hint)}">
      <span class="wcard-icon">${domainIcon[a.domain] || svgIcon("bot")}</span>
      <div class="wcard-name">${esc(a.name)}</div>
      <div class="wcard-hint">${esc(hint)}</div>
    </button>`;
  });

  const orRow = active.length ? `
    <p class="welcome-or">— hoặc chọn nhanh —</p>
    <div class="welcome-grid">${quickCards.join("")}</div>` : "";

  // Thay 2 path-card (Hỏi bất cứ thứ gì / Tạo trợ lý riêng) bằng carousel tutorial
  // NHÚNG inline (2 bước). Luôn hiện mỗi chat mới — không cần cờ localStorage.
  welcome.innerHTML = `
    <p class="welcome-greeting">Chào ${hello}! 👋</p>
    <p class="welcome-sub">Cục cưng đây — bạn cần gì hôm nay?</p>
    ${welcomeCarouselHTML()}
    ${orRow}`;

  msgs.appendChild(welcome);

  wireWelcomeCarousel(welcome);

  // Lối "Tạo trợ lý riêng" + panel "Tạo từ mẫu" (tplPanel) đã gỡ khỏi màn welcome
  // (thay bằng carousel). Vẫn tạo agent được qua trang chủ / catalog / chat master
  // (master handoff vẫn render templateGridEl — xem renderHandoff).
  // -- code cũ giữ lại để tham chiếu:
  // welcome.querySelector(".wp-chat")...  // focus input
  // tplPanel = ... templateGridEl(...) ; welcome.querySelector(".welcome-paths").after(tplPanel);
  // welcome.querySelector(".wp-create")...  // toggle tplPanel / startChatWith("master")

  // Chỉ quick-card (.welcome-grid gốc); loại .tpl-grid của panel mẫu — thẻ mẫu đã có
  // handler riêng (pickTemplate) nên không gắn chồng handler quick-card vào nó.
  welcome.querySelectorAll(".welcome-grid:not(.tpl-grid) .wcard").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("#chat-input").value = btn.dataset.msg;
      hideWelcome();
      submitChat();
    })
  );
}

/* ─── Welcome carousel (tutorial 2 bước, nhúng inline) ───── */
// Markup tĩnh (2 slide). Tách hàm để showWelcome chèn vào innerHTML.
function welcomeCarouselHTML() {
  // Thứ tự: mô tả (title + text) LÊN TRÊN, hình minh hoạ (visual) XUỐNG DƯỚI.
  // Không nút Trước/Tiếp — auto-play + dots (xem wireWelcomeCarousel).
  return `
  <div class="onb-inline">
    <div class="onb-track">
      <section class="onb-slide active" data-slide="0">
        <h3 class="onb-title">Bước 1: Mô tả nhu cầu → có agent ngay</h3>
        <p class="onb-text">Gõ <code class="onb-code">@Cục Cưng</code> và mô tả nhu cầu (có thể upload SOP, quy trình). Em đề xuất tên + skill; bạn xác nhận là agent sẵn sàng ở trạng thái <strong>private</strong> (riêng tư) để dùng thử ngay.</p>
        <div class="onb-visual">
          <div class="onb-stack">
            <div class="onb-bubble onb-bubble-user"><span class="onb-mention">@Cục Cưng</span> em cần agent thẩm định hợp đồng</div>
            <svg class="onb-stack-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M6 13l6 6 6-6"/></svg>
            <div class="onb-agent-card">
              <span class="onb-agent-avatar"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 4.6L18.5 9l-4.6 1.9L12 15l-1.9-4.1L5.5 9l4.6-1.4L12 3z"/></svg></span>
              <span class="onb-agent-name">ThamDinhHopDong</span>
              <span class="onb-badge-private">private</span>
            </div>
          </div>
        </div>
      </section>
      <section class="onb-slide" data-slide="1">
        <h3 class="onb-title">Bước 2: Dùng & lan tỏa cho tổ chức</h3>
        <p class="onb-text">Gõ <code class="onb-code">@TênAgent</code> để gọi trực tiếp — agent làm theo đúng quy trình. Khi ưng ý, chia sẻ để cả tổ chức cùng dùng — agent chuyển sang <strong>public</strong>.</p>
        <div class="onb-visual">
          <div class="onb-stack">
            <div class="onb-bubble onb-bubble-user"><span class="onb-mention">@ThamDinhHopDong</span> hãy xem hợp đồng này…</div>
            <svg class="onb-stack-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M6 13l6 6 6-6"/></svg>
            <div class="onb-share">
              <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 10.6l6.8-4.2M8.6 13.4l6.8 4.2"/></svg>
              Chia sẻ cho cả tổ chức
            </div>
          </div>
        </div>
      </section>
    </div>
    <div class="onb-dots">
      <button class="onb-dot active" type="button" data-go="0" aria-label="Bước 1"></button>
      <button class="onb-dot" type="button" data-go="1" aria-label="Bước 2"></button>
    </div>
  </div>`;
}

// Auto-play + dots (không nút). Scope theo root, không global listener.
// Chỉ 1 welcome tồn tại 1 lúc → giữ timer ở module-level, clear khi wire lại.
let _welcomeCarTimer = null;
function wireWelcomeCarousel(root) {
  const car = root.querySelector(".onb-inline");
  if (!car) return;
  const slides = car.querySelectorAll(".onb-slide");
  const dots = car.querySelectorAll(".onb-dot");
  const N = slides.length;
  let idx = 0;
  let paused = false;

  function render() {
    slides.forEach((s, i) => s.classList.toggle("active", i === idx));
    dots.forEach((d, i) => d.classList.toggle("active", i === idx));
  }
  function go(i) { idx = ((i % N) + N) % N; render(); }   // wrap: 0→1→0→1 (tự qua lại)

  function tick() {
    // Self-guard: welcome đã bị gỡ (mở chat mới / gửi tin) → dừng hẳn, tránh rò timer.
    if (!document.body.contains(car)) { clearInterval(_welcomeCarTimer); _welcomeCarTimer = null; return; }
    if (!paused) go(idx + 1);
  }
  function restart() {
    if (_welcomeCarTimer) clearInterval(_welcomeCarTimer);
    _welcomeCarTimer = setInterval(tick, 4000);
  }

  // Hover thì tạm dừng để đọc kịp; rời chuột chạy tiếp.
  car.addEventListener("mouseenter", () => { paused = true; });
  car.addEventListener("mouseleave", () => { paused = false; });
  // Click dot → nhảy slide + reset đồng hồ (không giật ngay sau khi bấm).
  dots.forEach((d) => (d.onclick = () => { go(Number(d.dataset.go)); paused = false; restart(); }));

  render();
  restart();
}

function hideWelcome() {
  const w = $("#welcome");
  if (w) w.remove();
}

/* ─── Chat ──────────────────────────────────────────────── */
function setCurrentAgent(name) {
  // Cập nhật header mới thay cho #current-agent cũ (đã xóa khỏi HTML)
  updateChatHeader(name);
}

$("#reset-agent").addEventListener("click", () => {
  saveCurrentConv();
  state.stickyAgent = null;
  state.activeConvId = null;  // cuộc mới — id sinh khi gửi tin đầu / chọn agent
  updateChatHeader(null);
  clearAttachments();
  hideMentionDropdown();
  $("#messages").innerHTML = "";
  showWelcome();
  renderSidebar();
});

$("#sidebar-new-btn").addEventListener("click", () => {
  saveCurrentConv();
  state.stickyAgent = null;
  state.activeConvId = null;  // cuộc mới — id sinh khi gửi tin đầu / chọn agent
  updateChatHeader(null);
  clearAttachments();
  hideMentionDropdown();
  $("#messages").innerHTML = "";
  showWelcome();
  renderSidebar();
  $("#chat-input").focus();
});

function addMsg(cls, text, agentTag) {
  const div = document.createElement("div");
  div.className = `msg ${cls}`;
  if (agentTag) {
    const tag = document.createElement("span");
    tag.className = "agent-tag";
    tag.textContent = agentTag;
    div.appendChild(tag);
  }
  const content = document.createElement("div");
  content.className = "msg-content";
  content.textContent = text;
  div.appendChild(content);
  $("#messages").appendChild(div);
  scrollBottom();
  return div;
}

/* ─── Sub-agent card (orchestration) ──────────────────────── */
function renderSubAgentCard(agentName, output, isError) {
  const card = document.createElement("div");
  card.className = "subagent-card" + (isError ? " subagent-card-error" : "");
  const agentData = _agentsCache.find((a) => a.slug === agentName || a.name === agentName);
  const icon = domainIcon[agentData?.domain] || svgIcon("bot");
  const label = agentData?.name || agentName;
  card.innerHTML = `
    <div class="sac-header">
      <span class="sac-icon">${icon}</span>
      <span class="sac-name">@${esc(agentName)}</span>
      <span class="sac-label">${esc(label)}</span>
      ${isError ? '<span class="sac-err-badge">lỗi</span>' : ''}
    </div>
    <div class="sac-body">${output ? renderMsg(output) : '<em>Không có kết quả</em>'}</div>`;
  $("#messages").appendChild(card);
  scrollBottom();
  return card;
}

/* ─── Process accordion ─────────────────────────────────────
   Gom các bước xử lý (gọi tool, suy nghĩ trung gian) vào 1 khối thu gọn được,
   TÁCH khỏi câu trả lời cuối — giống cách Claude hiển thị tool-use. */
const TOOL_LABELS = {
  "web-search.search": `${svgIcon("search")} Tìm kiếm web`,
  "web-search.fetch":  `${svgIcon("globe")} Đọc trang`,
  "list_templates":    `${svgIcon("sparkle")} Xem mẫu agent dựng sẵn`,
  "apply_template":    `${svgIcon("sparkle")} Lấy mẫu agent`,
};

function toolStepHtml(data) {
  const base = TOOL_LABELS[data.name] || `${svgIcon("wrench")} ${esc(data.name)}`;
  const inp = data.input || {};
  const arg = inp.query || inp.url || inp.q || inp.keyword || inp.name || "";
  const detail = arg ? ` <span class="ps-arg">${esc(String(arg).slice(0, 90))}</span>` : "";
  const err = data.is_error ? ` <span class="ps-err">— lỗi</span>` : "";
  return `${base}${detail}${err}`;
}

function turnProcess(assistantDiv) {
  let proc = assistantDiv.querySelector(".turn-process");
  if (!proc) {
    proc = document.createElement("div");
    proc.className = "turn-process open";
    proc.innerHTML =
      `<button type="button" class="proc-toggle">` +
        `<span class="proc-ic">${svgIcon("loader")}</span>` +
        `<span class="proc-label">Đang xử lý…</span>` +
        `<span class="proc-caret">▾</span>` +
      `</button><div class="proc-body"></div>`;
    assistantDiv.insertBefore(proc, assistantDiv.querySelector(".msg-content"));
    proc.querySelector(".proc-toggle").addEventListener("click", () => proc.classList.toggle("open"));
  }
  return proc;
}

function turnAddStep(assistantDiv, html, cls = "") {
  const proc = turnProcess(assistantDiv);
  const body = proc.querySelector(".proc-body");
  const step = document.createElement("div");
  step.className = "proc-step" + (cls ? " " + cls : "");
  step.innerHTML = html;
  body.appendChild(step);
  const n = body.querySelectorAll(".proc-step").length;
  proc.querySelector(".proc-label").textContent = `Đã thực hiện ${n} bước`;
  scrollBottom();
}

// Flow 5: nhận file ZIP (base64) backend gửi qua kênh chat → tạo Blob + nút tải trực tiếp.
// Không phụ thuộc URL ngoài (tránh model bịa link); file nằm ngay trong trình duyệt.
function renderArtifactDownload(assistantDiv, data) {
  if (!assistantDiv || !data || !data.content_b64) return;
  const name = data.filename || "project.zip";
  // Dedup THEO filename — một lượt có thể đóng gói NHIỀU file (vd nhiều partner),
  // mỗi file 1 event → mỗi file phải có nút riêng. Chỉ chặn trùng đúng file đó.
  const dedupKey = name.replace(/[^a-zA-Z0-9_.-]/g, "_");
  if (assistantDiv.querySelector(`.artifact-card[data-file="${dedupKey}"]`)) return;
  let url;
  try {
    const bin = atob(data.content_b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
  } catch (e) { return; }
  const size = data.size_kb ? ` (${data.size_kb} KB)` : "";
  const card = document.createElement("div");
  card.className = "artifact-card";
  card.dataset.file = dedupKey;
  card.style.cssText = "margin-top:10px";
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.className = "artifact-dl";
  a.style.cssText = "display:inline-flex;align-items:center;gap:8px;padding:10px 16px;" +
    "background:#0068FF;color:#fff;border-radius:10px;font-weight:600;text-decoration:none;cursor:pointer";
  a.textContent = `📦 Tải ${name}${size}`;
  card.appendChild(a);
  // Append vào message div (NGOÀI .msg-content) — để render text cuối của model ghi đè
  // .msg-content.innerHTML không xoá mất nút này.
  assistantDiv.appendChild(card);
  try { a.click(); } catch (_) {}  // best-effort auto-tải (trình duyệt có thể chặn nếu thiếu user-gesture → user tự bấm nút)
  scrollBottom();
}

/* ─── Template cards (#8 — gợi ý mẫu agent) ───────────────────
   1 nguồn markup (templateGridEl) + 1 handler (pickTemplate) dùng chung cho 3 điểm:
   in-chat (event list_templates), lời chào Cục cưng, panel welcome. */
function templateGridEl(templates, { openMaster }) {
  // Tái dùng pattern thẻ welcome (.welcome-grid + .wcard) cho đồng bộ design.
  const grid = document.createElement("div");
  grid.className = "welcome-grid tpl-grid";
  grid.innerHTML = templates.map((t) => `
    <button class="wcard" data-key="${esc(t.key)}" data-title="${esc(t.title)}">
      <span class="wcard-icon">${svgIcon(t.icon || "bot")}</span>
      <div class="wcard-name">${esc(t.title)}</div>
      <div class="wcard-hint">${esc(t.description || "")}</div>
    </button>`).join("");
  grid.querySelectorAll(".wcard").forEach((btn) =>
    btn.addEventListener("click", () => pickTemplate(btn.dataset.key, btn.dataset.title, openMaster)));
  return grid;
}

function pickTemplate(key, title, openMaster) {
  if (openMaster) {
    startChatWith("master", "");  // welcome: chưa ở conv master → mở trước (đồng bộ, không race)
  } else if (state.streaming.has(state.activeConvId)) {
    return;                       // đang trong conv: chặn gửi chồng khi lượt trước chưa xong
  }
  $("#chat-input").value = `Mình muốn dùng mẫu "${title}" (mã: ${key}).`;
  submitChat();
}

function renderTemplateCards(container, data) {
  if (!container || !data || !Array.isArray(data.templates) || !data.templates.length) return;
  // Idempotent: 1 lượt chỉ render 1 lần (tránh nhân đôi khi re-render/history).
  if (container.querySelector(".tpl-grid")) return;
  // Append NGOÀI .msg-content — để model ghi text cuối (overwrite .msg-content) không xoá thẻ.
  container.appendChild(templateGridEl(data.templates, { openMaster: false }));
  scrollBottom();
}

function finalizeTurnProcess(assistantDiv) {
  const proc = assistantDiv && assistantDiv.querySelector(".turn-process");
  if (!proc) return;
  proc.classList.remove("open");            // thu gọn khi xong — kết quả cuối nổi bật
  proc.classList.add("done");
  proc.querySelector(".proc-ic").innerHTML = svgIcon("check");
}

function addHandoff(name, description) {
  const isMaster = name === "master";
  const short = description ? description.split(/[.。]/)[0] : "";
  const agentData = _agentsCache.find((a) => a.name === name);
  const isPrivate = agentData && agentData.status === "private" && agentData.created_by === state.userId;
  const isRejected = agentData && agentData.status === "rejected" && agentData.created_by === state.userId;

  let statusBadge = "";
  if (isPrivate) {
    statusBadge = `<div class="handoff-status private">🔒 Private — hiện chỉ mình bạn thấy &nbsp;·&nbsp; <button class="link-btn" onclick="submitAgentFromHandoff('${esc(name)}', this)">Submit để chia sẻ →</button></div>`;
  } else if (isRejected) {
    const note = agentData.review_note ? esc(agentData.review_note) : "không có lý do";
    statusBadge = `<div class="handoff-status rejected">❌ Bị từ chối: ${note} &nbsp;·&nbsp; <button class="link-btn" onclick="startChatWith('master','')">Nhờ Master sửa →</button></div>`;
  }

  // #8: chỉ gợi ý mẫu ở lời chào ĐẦU của cuộc trò chuyện master — KHÔNG khi agent escalate
  // quay về master giữa chừng (lúc đó #messages đã có tin nhắn trước).
  const isFreshChat = $("#messages").children.length === 0;

  const card = document.createElement("div");
  card.className = "handoff-card";
  card.innerHTML = `
    <div class="handoff-title">${isMaster ? "✨ Cục cưng" : "👋 " + esc(name)}</div>
    <div class="handoff-body">${
      isMaster
        ? "Chào bạn! Mình là <strong>Cục cưng</strong> — mình có thể giúp bạn tìm agent có sẵn hoặc tạo một agent chuyên biệt riêng. Bạn đang cần gì vậy? 😊"
        : `Chào bạn! Em là <strong>${esc(name)}</strong>${short ? " — " + esc(short) : ""}. Cứ hỏi thoải mái, em ở đây rồi 😊`
    }</div>
    ${statusBadge}`;
  $("#messages").appendChild(card);

  // Thẻ mẫu bấm chọn ngay dưới lời chào (đã trong conv master → openMaster:false).
  if (isMaster && isFreshChat && _templatesCache.length) {
    const lead = document.createElement("div");
    lead.className = "tpl-panel-lead";
    lead.textContent = "Hoặc bắt đầu nhanh từ mẫu:";
    card.appendChild(lead);
    card.appendChild(templateGridEl(_templatesCache, { openMaster: false }));
  }
  scrollBottom();
  return card;
}

function scrollBottom() {
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

/* Trigger auto-start cho agent có skill khi user mở chat bằng cách click card.
   Gửi trực tiếp không qua form submit để không hiện user bubble rỗng. */
async function _triggerAgentAutoStart(agentName, slug) {
  if ($("#send-btn").disabled) return; // đang trong lượt chat khác
  hideWelcome();
  $("#send-btn").disabled = true;
  showTyping();
  builderTracker.reset();

  let assistantDiv = null;
  let assistantText = "";
  const triggerMsg = `@${slug}`;

  // Stream isolation: auto-start gắn cứng vào conversation_id hiện tại (cuộc vừa mở cho agent).
  // User chuyển cuộc khác giữa lúc chào → KHÔNG render vào view mới (tránh bleed).
  const _convId = state.activeConvId;
  state.streaming.add(_convId);  // theo dõi để xử lý xoá-giữa-chừng (#3)
  const _streamKey = _convId;
  let _detached = false;
  const _live = () => {
    if (_detached) return false;
    if (currentConvKey() !== _streamKey) { _detached = true; return false; }
    return true;
  };

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message: triggerMsg, agent_name: agentName, conversation_id: _convId, attachment: null }),
    });
    if (!resp.ok) return;

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const evMatch   = frame.match(/^event: (.+)$/m);
        const dataMatch = frame.match(/^data: (.+)$/m);
        if (!evMatch || !dataMatch) continue;
        const ev   = evMatch[1];
        const data = JSON.parse(dataMatch[1]);

        if (ev === "delta") {
          if (!_live()) { assistantText += data.text; continue; }  // rời hội thoại → không render
          hideTyping();
          if (!assistantDiv) {
            const tag = "@" + agentName;
            assistantDiv = addMsg("assistant", "", tag);
          }
          assistantText += data.text;
          assistantDiv.querySelector(".msg-content").innerHTML = renderMsg(assistantText);
          scrollBottom();
        } else if (ev === "tool") {
          if (!_live()) continue;
          hideTyping();
          if (!assistantDiv) {
            const tag = "@" + agentName;
            assistantDiv = addMsg("assistant", "", tag);
          }
          if (assistantText.trim()) {
            turnAddStep(assistantDiv, `<div class="ps-think">${renderMsg(assistantText)}</div>`, "think");
            assistantText = "";
            assistantDiv.querySelector(".msg-content").innerHTML = "";
          }
          turnAddStep(assistantDiv, toolStepHtml(data), data.is_error ? "err" : "");
          showTyping();
        } else if (ev === "tool_start") {
          // Tool đang chạy (vd websearch ~10s) — hiện loading để user biết đang xử lý.
          if (_live()) showTyping();
        } else if (ev === "artifact") {
          // Flow 5: backend gửi THẲNG file ZIP (base64) qua kênh chat — dựng Blob + nút tải,
          // không cần URL ngoài (tránh model bịa link).
          if (_live()) {
            if (!assistantDiv) assistantDiv = addMsg("assistant", "", "@" + agentName);
            renderArtifactDownload(assistantDiv, data);
          }
        } else if (ev === "templates") {
          // #8: Master gợi ý mẫu agent → thẻ bấm chọn ngay trong tin nhắn.
          if (_live()) {
            if (!assistantDiv) assistantDiv = addMsg("assistant", "", "@" + agentName);
            renderTemplateCards(assistantDiv, data);
          }
        } else if (ev === "done") {
          // Lượt xong → ẩn typing ngay (backend còn ghi memory trước khi đóng stream).
          if (_live()) { hideTyping(); finalizeTurnProcess(assistantDiv); }
        } else if (ev === "delegate") {
          if (!_live()) { break; }
          // Agent con auto-start escalate → chuyển về Master (luôn là escalation ở đây).
          _pendingDelegate = { agent_name: data.agent_name, message: data.message, isEscalation: true };
          break; // dừng đọc frame — server đã return sau delegate, stream sẽ đóng
        } else if (ev === "error") {
          if (_live()) { hideTyping(); addMsg("error", data.message); }
        }
      }
    }
    // Rời hội thoại giữa chừng → KHÔNG render vào view hiện tại; đánh dấu cache cũ để fetch /history.
    if (_detached) {
      const _e = state.convStore.get(_streamKey);
      if (_e) { _e.container = null; _e.lastText = assistantText.slice(0, 60) || _e.lastText; _e.updatedAt = Date.now(); }
      renderSidebar();
      return;
    }
    hideTyping();
    finalizeTurnProcess(assistantDiv);
    if (assistantDiv) {
      const mc = assistantDiv.querySelector(".msg-content");
      if (mc) mc.innerHTML = renderMsg(assistantText);
      if (assistantText) addFeedbackButtons(assistantDiv, agentName, assistantText);
    }
    // Auto-handoff khi agent auto-start escalate về Master (đồng bộ với handler chat chính).
    if (_pendingDelegate) {
      const { agent_name, message: delegateMsg } = _pendingDelegate;
      _pendingDelegate = null;
      addMsg("tool-note", `↩ Đang nhờ Cục cưng tìm người phù hợp hơn…`);
      await new Promise((r) => setTimeout(r, 300));
      await refreshAgentsCache();
      // Delegate = tiếp tục CÙNG cuộc với master (không tạo cuộc mới theo agent).
      state.stickyAgent = agent_name;
      setCurrentAgent(agent_name);
      const _curEntry = state.convStore.get(_convId);
      if (_curEntry) {
        _curEntry.agentName = agent_name;
        const _ad = _agentsCache.find((a) => a.name === agent_name);
        if (_ad) _curEntry.agentMeta = { domain: _ad.domain };
        _curEntry.updatedAt = Date.now();
      }
      renderSidebar();
      const agentData = _agentsCache.find((a) => a.name === agent_name);
      addHandoff(agent_name, agentData?.description || "");
      // Gửi message escalate sang Master — không cần user gõ lại (cùng conversation_id).
      $("#chat-input").value = delegateMsg;
      submitChat();
      return; // handoff tiếp quản; finally vẫn chạy để enable lại nút gửi
    }
    if (assistantText) {
      const entry = state.convStore.get(_convId);
      if (entry) { entry.lastText = assistantText.slice(0, 60); entry.updatedAt = Date.now(); }
      renderSidebar();
    }
  } catch (_) {
    hideTyping();
  } finally {
    finishStream(_convId);  // #3: xoá-giữa-chừng → DELETE sau khi server ghi xong
    $("#send-btn").disabled = false;
    $("#chat-input").focus();
  }
}

/* Tạo tiêu đề tự động từ tin nhắn đầu tiên (tối đa 48 ký tự, cắt ở ranh giới từ). */
function autoTitle(message) {
  const clean = message.trim().replace(/\s+/g, " ");
  if (clean.length <= 48) return clean;
  const cut = clean.slice(0, 48);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > 20 ? cut.slice(0, lastSpace) : cut) + "…";
}

/* ─── Conv store (per-conversation persistence, key = conversation_id) ─── */
function currentConvKey() {
  return state.activeConvId;  // null nếu chưa có cuộc nào (welcome)
}

function saveCurrentConv() {
  const msgs = $("#messages");
  const hasReal = [...msgs.children].some((el) => el.id !== "welcome");
  const key = currentConvKey();
  if (!hasReal || !key) return;  // không có cuộc đang mở → bỏ qua
  const container = document.createElement("div");
  while (msgs.firstChild) container.appendChild(msgs.firstChild);
  const existing = state.convStore.get(key) || {};
  // agentName giữ theo entry (agent đã route), fallback stickyAgent hiện tại.
  state.convStore.set(key, { ...existing, key, agentName: existing.agentName ?? state.stickyAgent, container, updatedAt: Date.now() });
}

async function restoreConv(key) {
  const msgs = $("#messages");
  if (!key) { showWelcome(); return; }
  const entry = state.convStore.get(key);
  if (entry && entry.container && entry.container.children.length) {
    // In-memory (session hiện tại)
    while (entry.container.firstChild) msgs.appendChild(entry.container.firstChild);
    scrollBottom();
    return;
  }
  // Fetch lịch sử từ server theo conversation_id (sau F5 hoặc cuộc chạy nền xong).
  const agentName = entry?.agentName || null;
  try {
    const history = await fetch(`/history/${encodeURIComponent(key)}`, { headers: headers() })
      .then((r) => r.ok ? r.json() : []);
    if (history.length) {
      if (agentName) addHandoff(agentName, "");
      for (const msg of history) {
        if (msg.role === "user") {
          const div = document.createElement("div");
          div.className = "msg user";
          const mc = document.createElement("span");
          mc.className = "msg-content";
          mc.textContent = msg.content;
          div.appendChild(mc);
          msgs.appendChild(div);
        } else if (msg.role === "assistant") {
          const tag = agentName === "master" ? "Cục cưng" : (agentName ? "@" + agentName : "");
          const div = addMsg("assistant", "", tag);
          div.querySelector(".msg-content").innerHTML = renderMsg(msg.content);
        }
      }
      scrollBottom();
      return;
    }
  } catch (_) {}
  showWelcome();
}

window.switchToConv = async function(key) {
  if (key === currentConvKey()) return;
  saveCurrentConv();
  state.activeConvId = key;
  state.stickyAgent = state.convStore.get(key)?.agentName ?? null;  // agent route của cuộc đó
  updateChatHeader(state.stickyAgent);
  $("#messages").innerHTML = "";
  await restoreConv(key);
  renderSidebar();
  hideMentionDropdown();
};

window.deleteConv = async function(key) {
  const isActive = key === currentConvKey();
  state.convStore.delete(key);
  if (isActive) {
    state.activeConvId = null;
    state.stickyAgent = null;
    updateChatHeader(null);
    $("#messages").innerHTML = "";
    showWelcome();
  }
  renderSidebar();
  // #3: nếu cuộc đang có stream chạy → hoãn DELETE tới khi stream xong (server ghi xong),
  // tránh memory.append trong finally của backend ghi lại sau khi đã xoá (cuộc tái xuất).
  if (state.streaming.has(key)) {
    state.pendingDelete.add(key);
    return;
  }
  try {
    await fetch(`/history/${encodeURIComponent(key)}`, { method: "DELETE", headers: headers() });
  } catch (_) {}
};

function updateChatHeader(agentName) {
  setInputPlaceholder(agentName);  // placeholder ô input bám theo ngữ cảnh agent (Hướng A/B)
  const avatar = $("#chd-avatar");
  const nameEl = $("#chd-name");
  const subEl  = $("#chd-sub");
  if (!agentName) {
    avatar.innerHTML = svgIcon("sparkle");
    avatar.className   = "chd-avatar chd-avatar-auto";
    nameEl.textContent = "Tự điều phối";
    subEl.textContent  = "Hệ thống tự tìm agent phù hợp nhất";
    return;
  }
  if (agentName === "master") {
    avatar.textContent = "Đ";
    avatar.className   = "chd-avatar chd-avatar-master";
    nameEl.textContent = "Cục cưng";
    subEl.textContent  = "Tạo agent mới hoặc kết nối bạn với đúng chuyên gia — cứ chat tự nhiên nhé 😊";
    return;
  }
  const a = _agentsCache.find((x) => x.name === agentName);
  const domain = a?.domain || "default";
  avatar.textContent = agentName[0].toUpperCase();
  avatar.className   = `chd-avatar chd-avatar-${domain}`;
  nameEl.textContent = a?.name || agentName;
  subEl.textContent  = a?.tagline || a?.description?.split(/[.。]/)[0]?.slice(0, 80) || "";
}

/* ─── Placeholder gợi ý cách dùng ────────────────────────────
   Hướng A: placeholder bám theo agent đang chat (master / agent cụ thể).
   Hướng B: khi tự điều phối (agentName == null) thì xoay vòng các gợi ý
            để "dạy" user @mention, đính kèm, đặt agent riêng…           */
const AUTO_HINTS = [
  "Mô tả việc cần làm — mình tự tìm đúng agent giúp bạn…",
  "Gõ @ để gọi thẳng một agent có sẵn…",
  "Đính kèm file (📎) để mình đọc và xử lý giúp bạn…",
  "VD: “Soạn email phản hồi khách hàng khiếu nại”…",
  "Cần trợ lý riêng? Mô tả việc cần → mình tạo chuyên gia ngay…",
];
let _phRotateTimer = null;  // interval xoay placeholder ở chế độ tự điều phối
let _phRotateIdx = 0;

function _stopPhRotate() {
  if (_phRotateTimer) { clearInterval(_phRotateTimer); _phRotateTimer = null; }
}

function setInputPlaceholder(agentName) {
  const input = $("#chat-input");
  if (!input) return;
  _stopPhRotate();  // đổi ngữ cảnh → luôn dừng vòng xoay cũ trước

  // Master: gợi ý cách "đặt hàng" một trợ lý mới
  if (agentName === "master") {
    input.placeholder = "VD: “Tạo trợ lý kiểm tra hợp đồng theo checklist phòng pháp chế”…";
    return;
  }
  // Agent cụ thể: gợi ý ngay theo tagline/mô tả của chính agent đó
  if (agentName) {
    const a = _agentsCache.find((x) => x.name === agentName);
    const tag = a?.tagline || a?.description?.split(/[.。]/)[0]?.slice(0, 50);
    const disp = a?.name || agentName;
    input.placeholder = tag ? `Hỏi ${disp} — ${tag}…` : `Nhắn cho ${disp}…`;
    return;
  }
  // Tự điều phối: Hướng B — xoay vòng gợi ý (chỉ đổi khi ô input đang trống)
  _phRotateIdx = 0;
  input.placeholder = AUTO_HINTS[0];
  _phRotateTimer = setInterval(() => {
    // Bỏ qua nếu user đang gõ (placeholder không hiện) hoặc đã chốt agent
    if (input.value.trim() || state.stickyAgent) return;
    _phRotateIdx = (_phRotateIdx + 1) % AUTO_HINTS.length;
    input.placeholder = AUTO_HINTS[_phRotateIdx];
  }, 3500);
}

function renderSidebar() {
  const list = $("#sidebar-list");
  const currentKey = currentConvKey();
  const entries = [...state.convStore.values()].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
  if (!entries.length) {
    list.innerHTML = '<div class="sidebar-empty">Chưa có cuộc trò chuyện nào</div>';
    return;
  }
  list.innerHTML = entries.map((e) => {
    const isActive   = e.key === currentKey;
    const agentName  = e.agentName;
    const displayName = !agentName ? "Tự điều phối" : agentName === "master" ? "Cục cưng" : agentName;
    const convTitle   = e.title || displayName;
    const firstChar   = !agentName ? svgIcon("sparkle") : esc(agentName[0].toUpperCase());
    const domain = e.agentMeta?.domain || (agentName === "master" ? "master" : !agentName ? "auto" : "default");
    const preview = (e.lastText || "…").slice(0, 48);
    return `<div class="conv-item${isActive ? " active" : ""}" onclick="switchToConv('${esc(e.key)}')" data-key="${esc(e.key)}">
      <div class="conv-av conv-av-${domain}">${firstChar}</div>
      <div class="conv-info">
        <div class="conv-name">${esc(convTitle)}</div>
        <div class="conv-last">${esc(preview)}</div>
      </div>
      <button class="conv-rename" onclick="event.stopPropagation(); startRename('${esc(e.key)}')" title="Đổi tên">✏</button>
      <button class="conv-del" onclick="event.stopPropagation(); deleteConv('${esc(e.key)}')" title="Xóa cuộc trò chuyện">✕</button>
    </div>`;
  }).join("");
}

/* ─── Conversation rename ────────────────────────────────── */
window.startRename = function(key) {
  const item = document.querySelector(`.conv-item[data-key="${CSS.escape(key)}"]`);
  if (!item) return;
  const nameEl = item.querySelector(".conv-name");
  if (!nameEl) return;
  const entry = state.convStore.get(key);
  const original = entry?.title || nameEl.textContent;

  const input = document.createElement("input");
  input.className = "conv-rename-input";
  input.value = original;
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let cancelled = false;
  const commit = async () => {
    const newTitle = cancelled ? original : (input.value.trim() || original);
    const div = document.createElement("div");
    div.className = "conv-name";
    div.textContent = newTitle;
    input.replaceWith(div);
    if (!cancelled && entry) {
      entry.title = newTitle;
      entry.titleSent = true;
      // key = conversation_id → PATCH title theo cuộc.
      fetch(`/history/${encodeURIComponent(key)}/title`, {
        method: "PATCH",
        headers: headers({ "Content-Type": "application/json" }),
        body: JSON.stringify({ title: newTitle }),
      }).catch(() => {});
    }
    // Re-render sidebar để title mới hiển thị đồng bộ
    if (!cancelled) renderSidebar();
  };
  input.addEventListener("blur", commit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); input.blur(); }
    if (e.key === "Escape") { e.preventDefault(); cancelled = true; input.blur(); }
  });
};

function showTyping() {
  hideTyping();
  const el = document.createElement("div");
  el.className = "typing";
  el.id = "typing-indicator";
  el.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div><span class="typing-label" id="typing-label"></span>';
  $("#messages").appendChild(el);
  scrollBottom();
  // Nhãn trạng thái theo nhịp SLA ~1 phút — để user biết agent đang chạy, không treo.
  const setLabel = (t) => { const l = $("#typing-label"); if (l) { l.textContent = t; l.classList.add("visible"); } };
  _typingTimers = [
    setTimeout(() => setLabel("Đang phân tích…"), 3000),
    setTimeout(() => setLabel("Đang tra cứu dữ liệu…"), 10000),
    setTimeout(() => setLabel("Dữ liệu khá lớn, đang tổng hợp phần liên quan…"), 25000),
    setTimeout(() => setLabel("Tác vụ nhiều bước, vẫn đang xử lý…"), 45000),
    setTimeout(() => setLabel("Vẫn đang chạy — tác vụ phức tạp có thể mất 1-2 phút…"), 90000),
  ];
}
function hideTyping() {
  _typingTimers.forEach(clearTimeout);
  _typingTimers = [];
  const el = $("#typing-indicator");
  if (el) el.remove();
}

let _lastRoutedAgent = null;
let _typingTimers = [];
let _pendingDelegate = null; // {agent_name, message} — set khi master delegate
let _seenHandoffAgents = new Set(); // track agent đã hiện handoff card trong session hiện tại

/* ─── Builder Tracker ───────────────────────────────────── */
const builderTracker = {
  el: null,
  steps: [],
  agentName: null,
  agentCreatedOk: false,

  TOOLS: {
    list_agents:       { label: 'Kiểm tra agent hiện có',    phase: 'check' },
    list_skills:       { label: 'Kiểm tra skill hiện có',    phase: 'check' },
    get_agent_detail:  { label: 'Lấy thông tin agent',       phase: 'check' },
    create_skill:      { label: 'Tạo skill',                 phase: 'build' },
    create_agent:      { label: 'Tạo agent',                 phase: 'build' },
    update_agent:      { label: 'Cập nhật agent',            phase: 'build' },
    update_skill:      { label: 'Cập nhật skill',            phase: 'build' },
    delete_agent:      { label: 'Xóa agent',                 phase: 'build' },
    attach_skill:      { label: 'Gắn skill vào agent',       phase: 'build' },
    fetch_url:         { label: 'Đọc tài liệu tham khảo',    phase: 'build' },
    self_test_agent:   { label: 'Kiểm thử agent',            phase: 'review' },
    submit_for_review: { label: 'Nộp duyệt',                 phase: 'review' },
  },

  isBuilderTool(name) { return !!this.TOOLS[name]; },

  reset() { this.el = null; this.steps = []; this.agentName = null; this.agentCreatedOk = false; },

  onTool(name, input, isError) {
    const info = this.TOOLS[name];
    if (!info) return;

    if (name === 'create_agent' && input?.name) {
      this.agentName = input.name;
      if (!isError) this.agentCreatedOk = true;
    }

    const label = this._label(name, input);
    this.steps.push({ label, isError });

    if (!this.el) {
      this.el = document.createElement('div');
      this.el.className = 'builder-tracker';
      $("#messages").appendChild(this.el);
    }
    this._render();
  },

  _label(name, input) {
    if (name === 'create_skill'      && input?.name)       return `Tạo skill: <code>${esc(input.name)}</code>`;
    if (name === 'create_agent'      && input?.name)       return `Tạo agent: <code>@${esc(input.name)}</code>`;
    if (name === 'delete_agent'      && input?.name)       return `Xóa agent: <code>@${esc(input.name)}</code>`;
    if (name === 'attach_skill'      && input?.skill_name) return `Gắn skill: <code>${esc(input.skill_name)}</code>`;
    if (name === 'submit_for_review' && input?.name) return `Nộp duyệt: <code>@${esc(input.name)}</code>`;
    if (name === 'update_agent'      && input?.name)       return `Cập nhật: <code>@${esc(input.name)}</code>`;
    if (name === 'update_skill'      && input?.name)       return `Cập nhật skill: <code>${esc(input.name)}</code>`;
    return this.TOOLS[name]?.label || name;
  },

  _render() {
    if (!this.el) return;
    const stepsHtml = this.steps.map((s) => `
      <div class="bt-step ${s.isError ? 'error' : 'done'}">
        <span class="bt-icon">${s.isError ? svgIcon("xmark") : svgIcon("check")}</span>
        <span class="bt-label">${s.label}</span>
      </div>`).join('');
    this.el.innerHTML = `
      <div class="bt-header">${svgIcon("wrench")} Đang xây dựng…</div>
      <div class="bt-steps">${stepsHtml}</div>`;
    scrollBottom();
  },

  finish() {
    if (!this.el || !this.steps.length) return;
    const hasError  = this.steps.some((s) => s.isError);
    const submitted = this.steps.some((s) => s.label.includes('Nộp duyệt'));
    const name      = this.agentName;

    const stepsHtml = this.steps.map((s) => `
      <div class="bt-step ${s.isError ? 'error' : 'done'}">
        <span class="bt-icon">${s.isError ? svgIcon("xmark") : svgIcon("check")}</span>
        <span class="bt-label">${s.label}</span>
      </div>`).join('');

    const shareCta = (!hasError && name && !submitted) ? `
      <div class="bt-share-cta">
        <div class="bt-share-msg">🔒 Hiện chỉ mình bạn dùng được. Muốn cả team thấy không?</div>
        <button class="btn-cta-sm" onclick="submitAgentForReview('${esc(name)}', this)">🚀 Submit để chia sẻ</button>
      </div>` : (submitted ? `<div class="bt-submitted-note">✅ Đã nộp duyệt thành công!<br><span class="bt-submit-hint">Admin sẽ review và thông báo kết quả. Khi approved, cả team thấy và dùng được ngay.<br>Theo dõi trạng thái tại <strong>Catalog → "Agent của tôi"</strong>.</span></div>` : '');

    const agentSlug = (_agentsCache.find((a) => a.name === name)?.slug) || slugifyName(name || "");
    const summary = (!hasError && name) ? `
      <div class="bt-summary">
        <div class="bt-summary-title">🎉 ${esc(name)} đã sẵn sàng!</div>
        <div class="bt-next">
          → Gõ <code>@${esc(agentSlug)}</code> ngay trong chat để thử nghiệm<br>
          → Khi hài lòng, submit để admin duyệt — cả team sẽ dùng được
        </div>
        ${shareCta}
      </div>` : '';

    this.el.innerHTML = `
      <div class="bt-header ${hasError ? 'error' : 'success'}">
        ${hasError ? '⚠️ Có lỗi xảy ra, bạn xem lại nhé' : `✅ Xong rồi!${name ? ' @' + esc(name) + ' đã được tạo' : ''} 🎉`}
      </div>
      <div class="bt-steps">${stepsHtml}</div>
      ${summary}`;
    scrollBottom();
    if (this.agentCreatedOk && name) setTimeout(() => showAgentBirthPopup(name), 400);
  },
};

/* ─── Agent Birth Popup ──────────────────────────────────── */
const _DOMAIN_BIRTH_MSG = {
  legal:   'Em chuyên về pháp lý và hợp đồng. Mọi rủi ro pháp lý — cứ để em lo! ⚖️',
  finance: 'Số liệu tài chính là ngôn ngữ mẹ đẻ của em. Hỏi gì em cũng tính được! 💰',
  sales:   'Pipeline, quota hay forecast — em handle hết. Cùng đạt target thôi! 📊',
  hr:      'Em hiểu người như hiểu code vậy. Mọi vấn đề nhân sự cứ thả cho em! 👥',
  ops:     'Quy trình trơn tru là sứ mệnh của em. Giao việc đi, em lo! ⚙️',
  it:      'Bug hay architecture — em đều handle. Stack nào em cũng rành cả! 💻',
};

function showAgentBirthPopup(agentName) {
  document.getElementById('agent-birth-overlay')?.remove();

  const rawUser   = state.userId || '';
  const firstName = rawUser.split('.')[0];
  const hello     = firstName.charAt(0).toUpperCase() + firstName.slice(1);
  const agentData = _agentsCache.find((a) => a.name === agentName);
  const domain    = agentData?.domain || '';
  const tagline   = _DOMAIN_BIRTH_MSG[domain] || 'Em sẵn sàng phục vụ bạn hết mình, mọi lúc mọi nơi! 🌟';
  const greeting  = `Chào ${hello}!\nEm là ${agentName}.\n${tagline}`;

  const overlay = document.createElement('div');
  overlay.id    = 'agent-birth-overlay';
  overlay.innerHTML = `
    <div id="agent-birth-card">
      <div class="abc-corner tl"></div><div class="abc-corner tr"></div>
      <div class="abc-corner bl"></div><div class="abc-corner br"></div>
      <div class="abc-scanlines"></div>
      <div class="abc-boot">
        <div class="abc-line" id="abl-1">[&nbsp;SYSTEM&nbsp;]&nbsp;AGENT CORE LOADED ............. OK</div>
        <div class="abc-line" id="abl-2">[&nbsp;INIT&nbsp;&nbsp;&nbsp;]&nbsp;PERSONALITY MATRIX .......... OK</div>
        <div class="abc-line" id="abl-3">[&nbsp;READY&nbsp;&nbsp;]&nbsp;STATUS — <span style="color:#6ee7b7">ONLINE ✓</span></div>
      </div>
      <div class="abc-divider" id="abc-divider"></div>
      <div class="abc-avatar" id="abc-avatar">${svgIcon("bot")}</div>
      <div class="abc-name"  id="abc-name"></div>
      <div class="abc-greeting-wrap">
        <span class="abc-greeting" id="abc-greeting"></span><span class="abc-cursor">▊</span>
      </div>
      <div class="abc-actions" id="abc-actions">
        <button class="abc-btn-test" onclick="testAgentFromBirth('${esc(agentName)}')">[ Thử chat ngay 🚀 ]</button>
        <button class="abc-dismiss"  onclick="dismissAgentBirth()">[ Để sau ]</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  overlay.addEventListener('click', (e) => { if (e.target === overlay) dismissAgentBirth(); });

  const seq = [
    [280,  () => _$('abl-1').classList.add('show')],
    [620,  () => _$('abl-2').classList.add('show')],
    [960,  () => _$('abl-3').classList.add('show')],
    [1250, () => { _$('abc-divider').classList.add('show'); _$('abc-avatar').classList.add('show'); }],
    [1550, () => { _$('abc-name').textContent = agentName; _$('abc-name').classList.add('glitch'); }],
    [2100, () => _typeOut(greeting, _$('abc-greeting'), 22, () => _$('abc-actions')?.classList.add('show'))],
  ];
  seq.forEach(([ms, fn]) => setTimeout(fn, ms));

  document.addEventListener('keydown', _abKeydown);
}
function _$(id) { return document.getElementById(id); }
function _abKeydown(e) { if (e.key === 'Escape') { dismissAgentBirth(); } }
function _typeOut(text, el, speed, onDone) {
  let i = 0;
  const t = setInterval(() => {
    if (!el || !document.body.contains(el)) { clearInterval(t); return; }
    el.textContent = text.slice(0, ++i);
    if (i >= text.length) { clearInterval(t); onDone?.(); }
  }, speed);
}
window.dismissAgentBirth = function () {
  document.removeEventListener('keydown', _abKeydown);
  const ov = document.getElementById('agent-birth-overlay');
  if (!ov) return;
  ov.style.animation = 'abOverlayOut .18s ease forwards';
  setTimeout(() => ov.remove(), 200);
};

window.testAgentFromBirth = function (name) {
  dismissAgentBirth();
  // Nhỏ delay để overlay fade-out xong rồi mới switch tab
  setTimeout(() => startChatWith(name, ''), 220);
};

function submitChat() {
  $("#chat-form").requestSubmit();
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message && !state.attachments.length) return;
  hideMentionDropdown();
  input.value = "";
  input.style.height = "auto";
  $("#send-btn").disabled = true;
  hideWelcome();
  builderTracker.reset();

  // Cuộc hiện tại chưa có id (gửi từ welcome) → tạo conversation_id mới.
  if (!state.activeConvId) state.activeConvId = newConvId();
  const _convId = state.activeConvId;
  state.streaming.add(_convId);  // theo dõi để xử lý xoá-giữa-chừng (#3)
  if (!state.convStore.has(_convId)) {
    state.convStore.set(_convId, { key: _convId, agentName: state.stickyAgent, agentMeta: null, lastText: message.slice(0, 60), updatedAt: Date.now(), title: autoTitle(message), titleSent: false });
    renderSidebar();
  }

  // User bubble
  const userDiv = document.createElement("div");
  userDiv.className = "msg user";
  if (state.attachments.length) {
    const badge = document.createElement("span");
    badge.className = "file-badge";
    badge.textContent = `📎 ${state.attachments.map((a) => a.filename).join(", ")}`;
    userDiv.appendChild(badge);
  }
  if (message) {
    const mc = document.createElement("span");
    mc.className = "msg-content";
    mc.innerHTML = highlightMentionsHtml(message);
    userDiv.appendChild(mc);
  }
  $("#messages").appendChild(userDiv);
  scrollBottom();
  showTyping();

  const attachmentPayload = buildCombinedAttachment();
  clearAttachments();

  let assistantDiv = null;
  let assistantText = "";
  let lastStopReason = null; // SLA: bắt "sla_deadline"/"timeout" để chú thích cho user

  // Stream gắn cứng vào conversation_id của nó (ID ổn định, không đổi khi re-route).
  // User chuyển cuộc giữa chừng → ngừng render vào view mới (tránh bleed). _detached: latch.
  const _streamKey = _convId;
  let _detached = false;
  const _live = () => {
    if (_detached) return false;
    if (currentConvKey() !== _streamKey) { _detached = true; return false; }
    return true;
  };

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message, agent_name: state.stickyAgent, conversation_id: _convId, attachment: attachmentPayload }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      addMsg("error", err.detail || "Có lỗi xảy ra, thử lại nhé! 😅");
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const evMatch   = frame.match(/^event: (.+)$/m);
        const dataMatch = frame.match(/^data: (.+)$/m);
        if (!evMatch || !dataMatch) continue;
        const ev   = evMatch[1];
        const data = JSON.parse(dataMatch[1]);

        if (ev === "meta") {
          // conversation_id ổn định (không migrate). Chỉ cập nhật agent đã route cho cuộc này.
          const _metaEntry = state.convStore.get(_convId);
          if (_metaEntry) {
            _metaEntry.agentName = data.agent_name;  // agent route của cuộc (hiển thị/icon/sidebar)
            _metaEntry.updatedAt = Date.now();
            const _aData = _agentsCache.find((a) => a.name === data.agent_name);
            if (_aData) _metaEntry.agentMeta = { domain: _aData.domain };
          }
          // Chỉ đổi global state (stickyAgent/header) khi user CÒN đang xem cuộc này.
          if (_live()) {
            state.stickyAgent = data.agent_name;
            setCurrentAgent(data.agent_name);
            // Handoff card khi agent thay đổi — chỉ chào 1 lần/agent/session
            if (data.agent_name !== _lastRoutedAgent && data.routed_by !== "explicit" && !_seenHandoffAgents.has(data.agent_name)) {
              _seenHandoffAgents.add(data.agent_name);
              addHandoff(data.agent_name, data.agent_description || "");
            }
            _lastRoutedAgent = data.agent_name;
          }
          renderSidebar();

        } else if (ev === "tool_start") {
          // Tool sắp/đang chạy (vd websearch, fetch ~10-15s) — hiện loading để user
          // biết agent đang xử lý, tránh cảm giác "agent đã trả lời xong nhưng treo".
          if (_live()) showTyping();

        } else if (ev === "delta") {
          if (!_live()) { assistantText += data.text; continue; }  // rời hội thoại → không render
          hideTyping();
          if (!assistantDiv) {
            const tag = state.stickyAgent === "master" ? "Cục cưng" : "@" + state.stickyAgent;
            assistantDiv = addMsg("assistant", "", tag);
          }
          assistantText += data.text;
          assistantDiv.querySelector(".msg-content").innerHTML = renderMsg(assistantText);
          scrollBottom();

        } else if (ev === "tool") {
          if (!_live()) continue;  // rời hội thoại → không render tool vào view khác
          hideTyping();
          if (data.name === "run_agent") {
            // Orchestration: render sub-agent card ngay trong messages (không gom vào accordion)
            const agentArg = data.input?.agent_name || "";
            renderSubAgentCard(agentArg, data.output, data.is_error);
            // Reset assistantDiv để Master tổng hợp nằm BÊN DƯỚI các card
            assistantDiv = null; assistantText = "";
          } else if (builderTracker.isBuilderTool(data.name)) {
            builderTracker.onTool(data.name, data.input, data.is_error);
            // Builder: reset để câu chốt của Master nằm BÊN DƯỚI tracker (giữ thứ tự đúng)
            assistantDiv = null; assistantText = "";
          } else {
            // Agent thường: gom vào accordion "quá trình xử lý", giữ NGUYÊN 1 bubble cho cả lượt
            if (!assistantDiv) {
              const tag = state.stickyAgent === "master" ? "Cục cưng" : "@" + state.stickyAgent;
              assistantDiv = addMsg("assistant", "", tag);
            }
            // Narration trước khi gọi tool = "suy nghĩ" → gấp vào quá trình, không lẫn vào kết quả
            if (assistantText.trim()) {
              turnAddStep(assistantDiv, `<div class="ps-think">${renderMsg(assistantText)}</div>`, "think");
              assistantText = "";
              assistantDiv.querySelector(".msg-content").innerHTML = "";
            }
            turnAddStep(assistantDiv, toolStepHtml(data), data.is_error ? "err" : "");
          }
          // Refresh cache ngay khi tool thay đổi danh sách agent — không đợi cuối stream
          if (!data.is_error && (data.name === "create_agent" || data.name === "delete_agent" || data.name === "update_agent")) {
            refreshAgentsCache();
          }
          showTyping();

        } else if (ev === "artifact") {
          // Flow 5: Upia đóng gói xong → backend gửi THẲNG file ZIP (base64) qua kênh chat.
          // Dựng Blob + nút tải ngay dưới tin nhắn (không phụ thuộc URL ngoài / model bịa link).
          if (_live()) {
            if (!assistantDiv) {
              const tag = state.stickyAgent === "master" ? "Cục cưng" : "@" + state.stickyAgent;
              assistantDiv = addMsg("assistant", "", tag);
            }
            renderArtifactDownload(assistantDiv, data);
          }

        } else if (ev === "templates") {
          // #8: Master gợi ý mẫu agent → thẻ bấm chọn ngay trong tin nhắn (kênh chat chính).
          if (_live()) {
            if (!assistantDiv) {
              const tag = state.stickyAgent === "master" ? "Cục cưng" : "@" + state.stickyAgent;
              assistantDiv = addMsg("assistant", "", tag);
            }
            renderTemplateCards(assistantDiv, data);
          }

        } else if (ev === "delegate") {
          // Rời hội thoại → bỏ qua auto-delegate (không hijack hội thoại đang xem).
          if (!_live()) { break; }
          const isEscalation = state.stickyAgent && state.stickyAgent !== "master";
          _pendingDelegate = { agent_name: data.agent_name, message: data.message, isEscalation };
          break; // dừng đọc stream — agent mới sẽ tiếp tục

        } else if (ev === "done") {
          lastStopReason = data.stop_reason || null;
          // Lượt đã xong → ẩn typing NGAY, không đợi kết nối đóng. Backend còn ghi memory
          // (agentbase = HTTP ~vài giây) sau khi gửi done → stream chưa đóng → nếu chờ
          // post-loop mới hideTyping thì typing quay tiếp dù đáp án đã hiện (bug đã gặp).
          if (_live()) { hideTyping(); builderTracker.finish(); finalizeTurnProcess(assistantDiv); }

        } else if (ev === "error") {
          if (_live()) { hideTyping(); addMsg("error", data.message); }
        }
      }
    }
    // Stream đã chạy trong nền (user đã rời sang hội thoại khác): KHÔNG render vào view hiện tại.
    // Backend vẫn lưu hội thoại → đánh dấu cache cũ để khi quay lại sẽ fetch /history (đầy đủ).
    if (_detached) {
      refreshAgentsCache();
      const _e = state.convStore.get(_streamKey);
      if (_e) { _e.container = null; _e.lastText = assistantText.slice(0, 60) || _e.lastText; _e.updatedAt = Date.now(); }
      renderSidebar();
      return;
    }
    hideTyping();
    builderTracker.finish();
    finalizeTurnProcess(assistantDiv);  // thu gọn "quá trình xử lý" — kết quả cuối nổi bật
    // Luôn refresh sau mỗi stream — bắt mọi trường hợp master tạo/xóa agent
    refreshAgentsCache();
    // Render markdown sau khi stream xong
    if (assistantDiv) {
      const mc = assistantDiv.querySelector(".msg-content");
      if (mc) mc.innerHTML = renderMsg(assistantText);

      // Fallback: model gọi nhiều tool nhưng không sinh kết quả cuối (minimax pattern) →
      // lấy nội dung "think" step cuối cùng trong accordion lên bubble chính.
      if (!assistantText.trim()) {
        const proc = assistantDiv.querySelector(".turn-process");
        const thinkSteps = proc ? proc.querySelectorAll(".proc-step.think") : [];
        if (thinkSteps.length > 0) {
          const lastThink = thinkSteps[thinkSteps.length - 1].querySelector(".ps-think");
          if (lastThink && mc) {
            mc.innerHTML = lastThink.innerHTML;
            assistantText = lastThink.innerText || lastThink.textContent || "";
            lastThink.closest(".proc-step").remove();
            const remaining = proc.querySelectorAll(".proc-step");
            if (remaining.length === 0) proc.remove();
          }
        }
      }

      // SLA: agent bị cắt do chạm giới hạn thời gian / timeout → báo user biết câu trả lời
      // dựa trên dữ liệu hiện có, không phải lỗi treo.
      if (lastStopReason === "sla_deadline" || lastStopReason === "timeout") {
        const note = document.createElement("div");
        note.className = "sla-note";
        note.textContent = "⏱ Dữ liệu khá lớn — câu trả lời dựa trên phần đã phân tích kịp. Bạn cứ hỏi tiếp nếu cần đi sâu hơn nhé.";
        mc.appendChild(note);
      }
      // Thêm thumbs up/down để thu thập feedback
      if (assistantText && state.stickyAgent && state.stickyAgent !== "master") {
        addFeedbackButtons(assistantDiv, state.stickyAgent, assistantText);
      }
    }
    // Cập nhật preview text trong sidebar + lưu auto-title lên server (lần đầu)
    if (assistantText) {
      const _doneEntry = state.convStore.get(_convId);
      if (_doneEntry) {
        _doneEntry.lastText = assistantText.slice(0, 60);
        _doneEntry.updatedAt = Date.now();
        if (!_doneEntry.titleSent && _doneEntry.title) {
          _doneEntry.titleSent = true;
          fetch(`/history/${encodeURIComponent(_convId)}/title`, {
            method: "PATCH",
            headers: headers({ "Content-Type": "application/json" }),
            body: JSON.stringify({ title: _doneEntry.title }),
          }).catch(() => {});
        }
      }
      renderSidebar();
    }

    // Auto-handoff: master delegate → agent, hoặc agent escalate → master → agent
    if (_pendingDelegate) {
      const { agent_name, message: delegateMsg, isEscalation } = _pendingDelegate;
      _pendingDelegate = null;

      if (isEscalation) {
        // Escalation từ agent con: hiện toast để user biết chuyện gì đang xảy ra
        addMsg("tool-note", `↩ Đang nhờ Cục cưng tìm người phù hợp hơn…`);
      }

      await new Promise((r) => setTimeout(r, isEscalation ? 300 : 500));
      await refreshAgentsCache();
      // Delegate = TIẾP TỤC cùng cuộc với agent mới (KHÔNG tạo cuộc mới theo agent).
      state.stickyAgent = agent_name;
      setCurrentAgent(agent_name);
      const _curEntry = state.convStore.get(_convId);
      if (_curEntry) {
        _curEntry.agentName = agent_name;
        const _ad = _agentsCache.find((a) => a.name === agent_name);
        if (_ad) _curEntry.agentMeta = { domain: _ad.domain };
        _curEntry.updatedAt = Date.now();
      }
      renderSidebar();
      const agentData = _agentsCache.find((a) => a.name === agent_name);
      addHandoff(agent_name, agentData?.description || "");
      // Gửi message gốc sang agent mới — không cần user gõ lại (cùng conversation_id)
      $("#chat-input").value = delegateMsg;
      submitChat();
    }
  } catch (err) {
    hideTyping();
    addMsg("error", "Model đang quay như chong chóng 🌀 Thử lại sau chút xíu nhé!!");
  } finally {
    finishStream(_convId);  // #3: nếu user đã xoá cuộc này giữa chừng → DELETE sau khi server ghi xong
    $("#send-btn").disabled = false;
    input.focus();
  }
});

// Auto-resize + mention autocomplete
$("#chat-input").addEventListener("input", function () {
  this.style.height = "auto";
  this.style.height = Math.min(this.scrollHeight, 120) + "px";
  handleMentionInput();
});

$("#chat-input").addEventListener("keydown", (e) => {
  if (mention.active) {
    const items = [...$("#mention-dropdown").querySelectorAll(".mention-item")];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      mention.selIdx = Math.min(mention.selIdx + 1, items.length - 1);
      items.forEach((el, i) => el.classList.toggle("active", i === mention.selIdx));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      mention.selIdx = Math.max(mention.selIdx - 1, 0);
      items.forEach((el, i) => el.classList.toggle("active", i === mention.selIdx));
    } else if (e.key === "Enter" || e.key === "Tab") {
      e.preventDefault();
      const active = items[mention.selIdx];
      if (active) selectMention(active.dataset.name);
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideMentionDropdown();
    }
    return;
  }
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submitChat(); }
});

/* ─── File upload (multi) ───────────────────────────────── */
state.attachments = []; // [{filename, content_type, text?, base64?, media_type?}]

/* ─── Slug util (mirror logic của backend slugify()) ────── */
function slugifyName(name) {
  return name.normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "agent";
}

/* ─── Agents cache (for @mention autocomplete) ──────────── */
let _agentsCache = [];
async function refreshAgentsCache() {
  try {
    const data = await fetch("/agents", { headers: headers() }).then((r) => r.json());
    _agentsCache = data.filter((a) => a.status !== "rejected");
  } catch (_) {}
}
refreshAgentsCache();

// #8: mẫu agent dựng sẵn — nạp 1 lần, cache cho 3 điểm gợi ý (welcome panel, lời chào
// Cục cưng, in-chat). Lỗi → rỗng (graceful, các điểm tự fallback).
let _templatesCache = [];
async function loadTemplates() {
  try {
    const data = await fetch("/templates", { headers: headers() }).then((r) => r.json());
    _templatesCache = Array.isArray(data.templates) ? data.templates : [];
  } catch (_) { _templatesCache = []; }
}
loadTemplates();

/* ─── @mention state ────────────────────────────────────── */
const mention = { active: false, query: "", atPos: -1, selIdx: 0 };

$("#file-input").addEventListener("change", async (e) => {
  const files = [...e.target.files];
  e.target.value = "";
  for (const file of files) await uploadOneFile(file);
});

async function uploadOneFile(file) {
  if (/\.(txt|md)$/i.test(file.name)) {
    addAttachment({ filename: file.name, content_type: "text", text: await file.text() });
    return;
  }
  // Hiện chip placeholder "đang xử lý..."
  const placeholderId = "ph-" + Date.now() + Math.random();
  renderPlaceholderChip(placeholderId, file.name);

  const fd = new FormData();
  fd.append("file", file);
  try {
    const resp = await fetch("/upload", { method: "POST", headers: headers(), body: fd });
    removePlaceholderChip(placeholderId);
    if (!resp.ok) { showToast((await resp.json().catch(() => ({}))).detail || `Lỗi upload ${resp.status}`, true); return; }
    addAttachment(await resp.json());
  } catch (err) {
    removePlaceholderChip(placeholderId);
    showToast(`Upload thất bại: ${err.message}`, true);
  }
}

function addAttachment(att) {
  state.attachments.push(att);
  renderAttachmentChips();
  $("#chat-input").focus();
}

function removeAttachment(idx) {
  state.attachments.splice(idx, 1);
  renderAttachmentChips();
}

function clearAttachments() {
  state.attachments = [];
  renderAttachmentChips();
}

function renderAttachmentChips() {
  const preview = $("#attachment-preview");
  // Giữ lại placeholder chips (đang upload), xóa các chip đã confirmed
  const placeholders = [...preview.querySelectorAll(".att-chip[data-placeholder]")];
  preview.innerHTML = "";
  placeholders.forEach((p) => preview.appendChild(p));

  state.attachments.forEach((att, i) => {
    const icon = att.content_type === "image" ? "🖼" : "📄";
    const chip = document.createElement("div");
    chip.className = "att-chip";
    chip.innerHTML = `<span>${icon}</span><span class="att-chip-name">${esc(att.filename)}</span>
      <button class="att-chip-remove" title="Bỏ file">✕</button>`;
    chip.querySelector("button").addEventListener("click", () => removeAttachment(i));
    preview.appendChild(chip);
  });

  preview.hidden = preview.children.length === 0;
}

function renderPlaceholderChip(id, filename) {
  const preview = $("#attachment-preview");
  preview.hidden = false;
  const chip = document.createElement("div");
  chip.className = "att-chip";
  chip.dataset.placeholder = id;
  chip.style.opacity = ".5";
  chip.innerHTML = `<span>⏳</span><span class="att-chip-name">${esc(filename)}</span>`;
  preview.appendChild(chip);
}
function removePlaceholderChip(id) {
  const el = $(`[data-placeholder="${id}"]`);
  if (el) el.remove();
  if (!$("#attachment-preview").children.length && !state.attachments.length)
    $("#attachment-preview").hidden = true;
}

function buildCombinedAttachment() {
  if (!state.attachments.length) return null;
  const texts  = state.attachments.filter((a) => a.content_type === "text");
  const images = state.attachments.filter((a) => a.content_type === "image");

  // Chỉ có ảnh → trả ảnh đầu tiên (Anthropic vision)
  if (images.length && !texts.length) return images[0];

  // Có text (± ảnh bị bỏ qua vì không thể ghép với text trong 1 request)
  if (texts.length) {
    const combined = texts.map((a) => `[${a.filename}]\n${a.text}`).join("\n\n---\n\n");
    const names    = texts.map((a) => a.filename).join(", ");
    if (images.length) addMsg("tool-note", `⚠ Ảnh (${images.map(i=>i.filename).join(", ")}) bỏ qua khi có file text — upload riêng nếu cần vision.`);
    return { filename: names, content_type: "text", text: combined };
  }
  return null;
}

/* ─── Catalog (Kho Agent) ───────────────────────────────── */
let _mpActiveDomain = "";

const STATUS_LABEL = {
  private:        { icon: "🟡", text: "Private — chỉ mình bạn",   cls: "private" },
  pending_review: { icon: "🔵", text: "Đang chờ admin duyệt",    cls: "pending_review" },
  public:         { icon: "🟢", text: "Đang chia sẻ với team",   cls: "public" },
  rejected:       { icon: "🔴", text: "Bị từ chối",              cls: "rejected" },
};

function myAgentCard(a) {
  const sl = STATUS_LABEL[a.status] || { icon: "⚪", text: a.status, cls: "" };
  let action = "";
  if (a.status === "private") {
    action = `<button class="btn-sm btn-share" onclick="submitAgentForReview('${esc(a.name)}', this)">🚀 Submit để chia sẻ</button>`;
  } else if (a.status === "pending_review") {
    action = `<span class="ccard-waiting">⏳ Đang chờ admin duyệt — khi approved, cả team dùng được</span>`;
  } else if (a.status === "rejected") {
    action = `<button class="btn-sm" onclick="startChatWith('master','')">✏️ Nhờ Master sửa lại</button>`;
  } else if (a.status === "public") {
    action = `<span class="ccard-active-note">✅ Cả team đang dùng được</span>`;
  }
  const rejectNote = a.review_note ? `<div class="ccard-reject-note">Lý do: ${esc(a.review_note)}</div>` : "";
  return `
    <div class="ccard my-ccard">
      <div class="ccard-name">
        @${esc(a.name)}
        <span class="badge ${sl.cls}">${sl.icon} ${sl.text}</span>
      </div>
      <div class="ccard-desc">${esc(a.description)}</div>
      ${rejectNote}
      <div class="ccard-meta">domain: ${a.domain || "—"} · skills: ${a.skills.join(", ") || "—"}</div>
      <div class="ccard-actions">${action}</div>
    </div>`;
}

// C1: hiển thị người tạo agent (lan toả/social proof). Email → phần trước @, "admin" → "Admin".
function makerName(email) {
  if (!email) return "";
  if (email === "admin") return "Admin";
  return email.split("@")[0];
}

function mpCard(a) {
  const icon = domainIcon[a.domain] || svgIcon("bot");
  const domainLabel = { legal:"Pháp lý", finance:"Tài chính", sales:"Sales", hr:"Nhân sự", ops:"Vận hành", it:"IT" }[a.domain] || (a.domain || "");
  const tagline = a.tagline || a.description.split(/[.。]/)[0].slice(0, 90);
  const callsBit = a.calls >= 5 ? `Phổ biến · ${a.calls} lượt` : a.calls > 0 ? `${a.calls} lượt` : "";
  const makerBit = a.created_by ? `tạo bởi ${makerName(a.created_by)}` : "";
  const meta = [domainLabel, makerBit, callsBit].filter(Boolean).join(" · ");
  const safeTag = esc(tagline);
  const safeName = esc(a.name);
  const jsTag = escJs(tagline);
  const jsName = escJs(a.name);
  return `<div class="mp-card" onclick="startChatWith('${jsName}','${jsTag}')">
    <div class="mp-card-icon">${icon}</div>
    <div class="mp-card-name">${safeName}</div>
    <div class="mp-card-tagline">${safeTag}</div>
    <div class="mp-card-footer">
      <div class="mp-card-meta">${esc(meta)}</div>
      <button class="btn-talk" onclick="event.stopPropagation();startChatWith('${jsName}','${jsTag}')">Nói chuyện →</button>
    </div>
  </div>`;
}

async function loadCatalog() {
  try {
    const agents = await fetch("/agents", { headers: headers() }).then((r) => r.json());
    const q = ($("#catalog-search")?.value || "").toLowerCase();
    const domain = _mpActiveDomain;

    // K2: "Agent của tôi" đã chuyển hẳn sang tab "Của tôi" (#panel-myagents / loadMyAgents).
    // Không render lại trong Catalog nữa để tránh trùng lặp 2 nơi.
    // const mine = agents.filter((a) => a.created_by === state.userId && a.status !== "public");
    // const mySection = $("#my-agents-section");
    // if (mine.length) {
    //   $("#my-agent-list").innerHTML = mine.map(myAgentCard).join("");
    //   mySection.hidden = false;
    // } else {
    //   mySection.hidden = true;
    // }

    const match = (a) => (!domain || a.domain === domain) && (!q || (a.name + " " + (a.tagline || "") + " " + a.description).toLowerCase().includes(q));
    const publicAgents = agents.filter((a) => a.status === "public").filter(match);

    // Phổ biến — chỉ hiện khi không filter
    const featured = publicAgents.filter((a) => a.calls >= 3).sort((a, b) => b.calls - a.calls).slice(0, 4);
    const mpFeatured = $("#mp-featured");
    if (mpFeatured) {
      if (featured.length && !q && !domain) {
        $("#mp-featured-list").innerHTML = featured.map(mpCard).join("");
        mpFeatured.hidden = false;
      } else {
        mpFeatured.hidden = true;
      }
    }

    $("#agent-list").innerHTML = publicAgents.map(mpCard).join("")
      || '<div class="empty">Chưa có agent nào phù hợp</div>';
  } catch (_) {}
}
$("#catalog-search").addEventListener("input", loadCatalog);

// mp-cats (category pills)
document.querySelectorAll(".mp-cat").forEach((btn) => {
  btn.addEventListener("click", () => {
    _mpActiveDomain = btn.dataset.domain;
    document.querySelectorAll(".mp-cat").forEach((b) => b.classList.toggle("active", b === btn));
    loadCatalog();
  });
});

/* ─── Review ────────────────────────────────────────────── */
async function loadReview() {
  const resp = await fetch("/review/pending", { headers: headers() });
  if (!resp.ok) { $("#pending-list").innerHTML = '<div class="empty">Chỉ admin xem được trang này.</div>'; return; }
  const data = await resp.json();
  const blocks = [];

  for (const a of data.agents) {
    blocks.push(`<div class="review-card">
      <h3>${svgIcon("bot")} ${esc(a.name)} <code class="agent-slug">@${esc(a.slug || a.name)}</code> <span class="badge ${a.status}">${a.status}</span></h3>
      <div class="review-meta">Tạo bởi ${a.created_by} · domain: ${a.domain || "—"} · ${a.visibility}</div>
      <div class="review-desc">${esc(a.description)}</div>
      <details open><summary>Persona prompt</summary><pre>${esc(a.system_prompt)}</pre></details>
      ${a.pending_changes ? `<div class="diff-block"><strong>Sửa đổi chờ duyệt:</strong><pre>${esc(JSON.stringify(a.pending_changes, null, 2))}</pre></div>` : ""}
      ${a.skills.map((s) => `
        <details><summary>📜 Skill: ${s.name} <span class="badge ${s.status}">${s.status} v${s.version}</span></summary>
          <pre>${esc(s.content)}</pre>
          ${s.status === "private" ? reviewActionsSkillPrivate(s.name)
            : (s.status === "pending_review" || s.pending_changes) ? reviewActions("skill", s.name)
            : ""}
        </details>`).join("")}
      ${a.connectors.map((c) => `
        <details><summary>🔌 ${c.server} <span class="badge ${c.is_mock ? "mock" : "real"}">${c.is_mock ? "mock" : "thật"}</span></summary>
          <pre>${esc(c.tools.map((t) => `${t.name} — ${t.description}`).join("\n"))}</pre>
        </details>`).join("")}
      ${a.dedup_candidates.length ? `<div class="diff-block">⚠️ Agent tương tự: <pre>${esc(a.dedup_candidates.map((d) => `${d.name}: ${d.description}`).join("\n"))}</pre></div>` : ""}
      ${(() => {
        const blocking = a.skills.filter(s => s.status !== "public");
        return blocking.length
          ? `<div class="review-blocker">⛔ Cần duyệt skill trước khi approve agent: ${blocking.map(s => `<code>${esc(s.name)}</code> <span class="badge ${s.status}">${s.status}</span>`).join(", ")}</div>`
          : "";
      })()}
      ${reviewActions("agent", a.name)}
    </div>`);
  }

  const standalone = data.skills.filter((s) => !data.agents.some((a) => a.skills.some((as) => as.name === s.name)));
  for (const s of standalone) {
    blocks.push(`<div class="review-card">
      <h3>📜 ${s.name} <span class="badge ${s.status}">${s.status} v${s.version}</span></h3>
      <div class="review-meta">Tạo bởi ${s.created_by} · domain: ${s.domain || "—"}</div>
      <details open><summary>Nội dung</summary><pre>${esc(s.content)}</pre></details>
      ${s.pending_changes ? `<div class="diff-block"><pre>${esc(JSON.stringify(s.pending_changes, null, 2))}</pre></div>` : ""}
      ${reviewActions("skill", s.name)}
    </div>`);
  }

  $("#pending-list").innerHTML = blocks.join("") || '<div class="empty">Không có gì chờ duyệt 🎉</div>';
}

function showToast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = `review-toast ${isError ? "review-toast-error" : "review-toast-ok"}`;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add("visible"));
  setTimeout(() => {
    el.classList.remove("visible");
    setTimeout(() => el.remove(), 300);
  }, 2800);
}

// I1: confirm-modal nhất quán thay window.confirm() — trả Promise<bool>.
function showConfirm(message, { okText = "Xác nhận", danger = false } = {}) {
  return new Promise((resolve) => {
    const ov = $("#confirm-modal");
    $("#confirm-msg").textContent = message;
    const okBtn = $("#confirm-ok");
    const cancelBtn = $("#confirm-cancel");
    okBtn.textContent = okText;
    okBtn.className = danger ? "btn-cta btn-danger" : "btn-cta";
    ov.hidden = false;
    const done = (val) => {
      ov.hidden = true;
      okBtn.onclick = cancelBtn.onclick = ov.onclick = null;
      resolve(val);
    };
    okBtn.onclick = () => done(true);
    cancelBtn.onclick = () => done(false);
    ov.onclick = (e) => { if (e.target === ov) done(false); };
  });
}

function reviewActions(kind, name) {
  return `<div class="review-actions">
    <button class="btn-approve" onclick="decide('${kind}','${name}','approve',this)">Approve</button>
    <button class="btn-reject"  onclick="decide('${kind}','${name}','reject',this)">Reject</button>
  </div>`;
}

function reviewActionsSkillPrivate(name) {
  return `<div class="review-actions review-actions-warn">
    <span class="review-skill-private-note">⚠️ Skill chưa được submit — maker quên submit skill này.</span>
    <button class="btn-approve" onclick="submitAndApproveSkill('${name}',this)">⚡ Submit & Approve</button>
    <button class="btn-reject"  onclick="decide('skill','${name}','reject',this)">Reject</button>
  </div>`;
}

window.submitAndApproveSkill = async (name, btn) => {
  if (btn) { btn.disabled = true; btn.textContent = "Đang xử lý…"; }
  const r1 = await fetch(`/skills/${encodeURIComponent(name)}/submit`, {
    method: "POST",
    headers: headers(),
  });
  if (!r1.ok) {
    showToast((await r1.json().catch(() => ({}))).detail || `Submit thất bại ${r1.status}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "⚡ Submit & Approve"; }
    return;
  }
  const r2 = await fetch(`/review/skill/${encodeURIComponent(name)}/approve`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
  });
  if (!r2.ok) {
    showToast((await r2.json().catch(() => ({}))).detail || `Approve thất bại ${r2.status}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "⚡ Submit & Approve"; }
    return;
  }
  showToast(`✅ Skill "${name}" đã được approve`, false);
  loadReview();
};

window.decide = async (kind, name, action, btn) => {
  let body = null;
  if (action === "reject") {
    const reason = prompt(`Lý do reject ${kind} '${name}' (bắt buộc):`);
    if (!reason) return;
    body = JSON.stringify({ reason });
  }
  if (btn) { btn.disabled = true; btn.textContent = action === "approve" ? "Đang duyệt…" : "Đang từ chối…"; }
  const resp = await fetch(`/review/${kind}/${encodeURIComponent(name)}/${action}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body,
  });
  if (!resp.ok) {
    showToast((await resp.json().catch(() => ({}))).detail || `Lỗi ${resp.status}`, true);
    if (btn) { btn.disabled = false; btn.textContent = action === "approve" ? "Approve" : "Reject"; }
    return;
  }
  const label = action === "approve"
    ? `✅ Đã approve ${kind} "${name}"`
    : `✅ Đã reject ${kind} "${name}"`;
  showToast(label, false);
  loadReview();
};

/* ─── Submit agent for review ───────────────────────────── */
window.submitAgentForReview = async function (name, btn) {
  if (!state.user) {
    openAuthModal(true);
    showToast("Đăng nhập để chia sẻ agent — agent thử nghiệm sẽ được giữ lại tự động 🔒");
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = "Đang gửi…"; }
  try {
    const resp = await fetch(`/agents/${encodeURIComponent(name)}/submit`, {
      method: "POST",
      headers: headers(),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      showToast(err.detail || `Lỗi ${resp.status}`, true);
      if (btn) { btn.disabled = false; btn.textContent = "🚀 Submit để chia sẻ"; }
      return;
    }
    if (btn) {
      const container = btn.closest(".bt-share-cta, .ccard-actions, .handoff-status");
      const note = document.createElement("div");
      note.className = "bt-submitted-note";
      note.innerHTML = `✅ Đã nộp duyệt thành công!<br>
        <span class="bt-submit-hint">Admin sẽ review sớm — khi được duyệt, cả team dùng được.<br>
        Theo dõi trạng thái tại <strong>Catalog → "Agent của tôi"</strong>.</span>`;
      if (container) {
        container.replaceWith(note);
      } else {
        btn.replaceWith(note);
      }
    }
    await refreshAgentsCache();
    if ($("#panel-catalog").classList.contains("active")) loadCatalog();
  } catch (err) {
    showToast(`Không gửi được: ${err.message}`, true);
    if (btn) { btn.disabled = false; btn.textContent = "🚀 Submit để chia sẻ"; }
  }
};

window.submitAgentFromHandoff = async function (name, btn) {
  await submitAgentForReview(name, btn);
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

/* Escape cho JS string đơn bên trong HTML attribute onclick="...('${escJs(x)}',...)".
   Escape \ ' \n \r trước, rồi HTML-escape " & để không phá vỡ attribute. */
function escJs(s) {
  return String(s ?? "")
    .replace(/\\/g, "\\\\")
    .replace(/'/g, "\\'")
    .replace(/\n/g, "\\n")
    .replace(/\r/g, "\\r")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;");
}

function highlightMentionsHtml(text) {
  return esc(text).replace(/@([a-z][a-z0-9-]*)/g, (_, slug) => {
    const isMaster = slug === "cuc-cung" || slug === "master";
    const a = isMaster ? null : _agentsCache.find(x => x.slug === slug);
    const display = isMaster ? "Cục cưng" : (a?.name || slug);
    return `<span class="mention-tag">@${esc(display)}</span>`;
  });
}

/* Inline-level markdown: code, link, bold, italic, mention. Tự escape HTML. */
function renderInline(s) {
  // Tách inline code ra placeholder để không bị xử lý bold/italic bên trong
  const codes = [];
  let h = String(s ?? "").replace(/`([^`\n]+)`/g, (_m, c) => {
    codes.push(c);
    return `\u0001${codes.length - 1}\u0001`;
  });
  h = esc(h);
  // Link tải BỊA kiểu local (sandbox:/file:/tmp/var) → bỏ URL chết, chỉ giữ text.
  // File ZIP thật đến qua nút "📦 Tải" (artifact button), không qua link trong văn bản.
  h = h.replace(/\[([^\]]+)\]\((?:sandbox:|file:)[^\s)]*\)/g, "$1");
  h = h.replace(/\[([^\]]+)\]\((?:\/tmp\/|\/var\/|\.\/)[^\s)]*\)/g, "$1");
  // Link [text](url) — chỉ http/https
  h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  // Bold trước, italic sau (để **x** không bị * nuốt)
  h = h.replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>");
  // @mention
  h = h.replace(/@([a-z][a-z0-9-]*)/g, '<span class="mention-tag">@$1</span>');
  // Khôi phục inline code
  h = h.replace(/\u0001(\d+)\u0001/g, (_m, i) => `<code>${esc(codes[i])}</code>`);
  return h;
}

/* Block-level markdown → HTML: heading, list (ul/ol), code fence, quote, hr, table, paragraph.
   Đủ cho chat agent — không phải full CommonMark nhưng xử lý đúng các pattern thường gặp. */
function buildTableHtml(rows) {
  const isSep = (r) => {
    const cells = r.split("|").slice(1, -1);
    return cells.length > 0 && cells.every((c) => /^[\s\-:]+$/.test(c));
  };
  const parseRow = (r) => r.split("|").slice(1, -1).map((c) => c.trim());
  const dataRows = rows.filter((r, i) => !(i === 1 && isSep(r)));
  const headerCells = parseRow(dataRows[0] || "");
  const bodyRows = dataRows.slice(1);
  const ths = headerCells.map((h) => `<th>${renderInline(h)}</th>`).join("");
  const trs = bodyRows.map((r) => `<tr>${parseRow(r).map((c) => `<td>${renderInline(c)}</td>`).join("")}</tr>`).join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

const _EMOJI_ICON_MAP = {
  '🔍': 'search', '🔎': 'search',
  '✅': 'check',  '☑️': 'check',
  '❌': 'xmark',  '✖️': 'xmark',
  '🤖': 'bot',
  '💬': 'chat',   '🗨️': 'chat',
  '✨': 'sparkle', '⭐': 'sparkle', '💫': 'sparkle',
  '🌍': 'globe',  '🌐': 'globe',   '🌎': 'globe',
  '🔧': 'wrench', '⚙️': 'wrench',
  '🔥': 'fire',
};

const _EMOJI_STRIP = [
  '👋','😊','😀','😁','😄','😃','🙂','😉','🥰','😍','🤩','🎉','🎊','🎈','🎁',
  '👏','🙏','💪','👍','👎','🫡','🤝','💡','📌','📎','📝','📊','📈','📉',
  '🏆','💎','🚀','⚡','🎯','💰','💸','🛒','🛍️','💳','🏦',
  '😅','😂','🤣','😭','😢','😤','😡','🥺','😱','🤔','🤷',
];

function mapEmojiToIcons(html) {
  let out = html;
  for (const [em, name] of Object.entries(_EMOJI_ICON_MAP)) {
    out = out.replaceAll(em, `<span class="ei">${svgIcon(name)}</span>`);
  }
  for (const em of _EMOJI_STRIP) {
    out = out.replaceAll(em, '');
  }
  return out;
}

function renderMsg(text) {
  return mapEmojiToIcons(renderMarkdown(text));
}

function renderMarkdown(src) {
  if (!src) return "";

  // 1) Rút code fence ``` ra placeholder (giữ nguyên nội dung bên trong)
  const blocks = [];
  let text = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    blocks.push(`<pre class="code-block"><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });

  const out = [];
  let para = [];
  let quote = [];
  let listTag = null; // 'ul' | 'ol'
  let tableRows = []; // accumulate |..| lines

  const flushPara = () => { if (para.length) { out.push("<p>" + renderInline(para.join(" ")) + "</p>"); para = []; } };
  const closeList = () => { if (listTag) { out.push(`</${listTag}>`); listTag = null; } };
  const flushQuote = () => { if (quote.length) { out.push("<blockquote>" + renderInline(quote.join(" ")) + "</blockquote>"); quote = []; } };
  const flushTable = () => { if (tableRows.length) { out.push(buildTableHtml(tableRows)); tableRows = []; } };
  const flushAll = () => { flushPara(); flushQuote(); closeList(); flushTable(); };

  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    const cbMatch = line.match(/^\u0000(\d+)\u0000$/);

    if (cbMatch) {                                   // code block độc lập
      flushAll();
      out.push(blocks[+cbMatch[1]]);
    } else if (!line.trim()) {                       // dòng trống → ngắt block
      flushAll();
    } else if (/^\|.+\|/.test(line)) {              // table row
      flushPara(); flushQuote(); closeList();
      tableRows.push(line);
    } else if (/^#{1,6}\s+/.test(line)) {            // heading
      flushAll();
      const m = line.match(/^(#{1,6})\s+(.*)$/);
      const lvl = Math.min(m[1].length, 4);          // h5/h6 dồn về h4 cho gọn
      out.push(`<h${lvl}>${renderInline(m[2])}</h${lvl}>`);
    } else if (/^\s*[-*+]\s+/.test(line) && !/^\s*([-*_])\1{2,}\s*$/.test(line)) { // bullet
      flushPara(); flushQuote(); flushTable();
      if (listTag !== "ul") { closeList(); out.push("<ul>"); listTag = "ul"; }
      out.push("<li>" + renderInline(line.replace(/^\s*[-*+]\s+/, "")) + "</li>");
    } else if (/^\s*\d+\.\s+/.test(line)) {           // numbered list
      flushPara(); flushQuote(); flushTable();
      if (listTag !== "ol") { closeList(); out.push("<ol>"); listTag = "ol"; }
      out.push("<li>" + renderInline(line.replace(/^\s*\d+\.\s+/, "")) + "</li>");
    } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {  // horizontal rule
      flushAll();
      out.push("<hr>");
    } else if (/^>\s?/.test(line)) {                  // blockquote
      flushPara(); closeList(); flushTable();
      quote.push(line.replace(/^>\s?/, ""));
    } else {                                          // text thường → gộp vào paragraph
      flushQuote(); closeList(); flushTable();
      para.push(line.trim());
    }
  }
  flushAll();

  // 2) Khôi phục code block còn sót (vd nằm trong paragraph)
  return out.join("\n").replace(/\u0000(\d+)\u0000/g, (_m, i) => blocks[+i]);
}

/* ─── @mention dropdown ─────────────────────────────────── */
function showMentionDropdown(agents) {
  const dd = $("#mention-dropdown");
  if (!agents.length) { hideMentionDropdown(); return; }
  mention.selIdx = 0;
  dd.innerHTML = agents.slice(0, 6).map((a, i) => `
    <div class="mention-item${i === 0 ? " active" : ""}" data-name="${esc(a.slug || a.name)}">
      <span class="mi-icon">${domainIcon[a.domain] || svgIcon("bot")}</span>
      <span class="mi-name">${esc(a.name)}</span>
      <span class="mi-handle">@${esc(a.slug || a.name)}</span>
      <span class="mi-desc">${esc(a.tagline || a.description.split(/[.。]/)[0].slice(0, 60))}</span>
    </div>`).join("");
  dd.querySelectorAll(".mention-item").forEach((el) => {
    el.addEventListener("mousedown", (e) => { e.preventDefault(); selectMention(el.dataset.name); });
  });
  dd.hidden = false;
  mention.active = true;
}

function hideMentionDropdown() {
  const dd = $("#mention-dropdown");
  dd.hidden = true;
  mention.active = false;
  mention.query = "";
  mention.atPos = -1;
}

function selectMention(name) {
  const input = $("#chat-input");
  const val = input.value;
  const before = val.slice(0, mention.atPos);
  const after = val.slice(mention.atPos + 1 + mention.query.length);
  input.value = before + "@" + name + " " + after;
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 120) + "px";
  const pos = mention.atPos + name.length + 2;
  input.setSelectionRange(pos, pos);
  hideMentionDropdown();
  input.focus();
}

const _MASTER_MENTION_ENTRY = {
  name: "Cục cưng", slug: "cuc-cung",
  description: "Tạo agent mới hoặc kết nối bạn với đúng chuyên gia",
  domain: "master", status: "public",
};

function handleMentionInput() {
  const input = $("#chat-input");
  const textBefore = input.value.slice(0, input.selectionStart);
  const atMatch = textBefore.match(/@([a-z0-9-]*)$/);
  if (atMatch) {
    mention.atPos = textBefore.lastIndexOf("@");
    mention.query = atMatch[1];
    const q = mention.query.toLowerCase();
    const pool = [_MASTER_MENTION_ENTRY, ..._agentsCache];
    const filtered = pool.filter((a) =>
      !q || (a.slug || "").startsWith(q) || a.name.toLowerCase().includes(q)
    );
    showMentionDropdown(filtered);
  } else {
    if (mention.active) hideMentionDropdown();
  }
}

/* ─── Quick Create Wizard ───────────────────────────────── */
const qc = {
  step: 1,
  name: "", domain: "legal", purpose: "",
  skillContent: "", skillFilename: null,
};

// Guest muốn tạo agent → mời đăng nhập (guest chỉ chat + dùng agent public).
function promptLoginForCreate() {
  openAuthModal(true);
  showToast("Đăng nhập để tạo trợ lý riêng nhé! 😊");
}

// Vào luồng tạo agent qua chat với Cục cưng — guest tạo được (trial mode).
window.startBuilderChat = function () {
  startChatWith("master", "");
};

window.openQuickCreate = function () {
  // reset state
  Object.assign(qc, { step: 1, name: "", domain: "legal", purpose: "", skillContent: "", skillFilename: null });
  $("#qc-name").value = "";
  $("#qc-domain").value = "legal";
  $("#qc-purpose").value = "";
  $("#qc-content").value = "";
  $("#qc-file").value = "";
  qcSetUploadIdle();
  qcRenderStep(1);
  $("#qc-modal").hidden = false;
};

window.closeQuickCreate = function () {
  $("#qc-modal").hidden = true;
};

// Close on backdrop click
$("#qc-modal").addEventListener("click", (e) => {
  if (e.target === $("#qc-modal")) closeQuickCreate();
});

window.qcNext = function (from) {
  if (from === 1) {
    const name = $("#qc-name").value.trim();
    const purpose = $("#qc-purpose").value.trim();
    if (!name) { $("#qc-name").focus(); showToast("Vui lòng nhập tên agent.", true); return; }
    // Khớp AGENT_NAME_RE backend: 2-64 ký tự Unicode (có dấu) + khoảng trắng, không thừa ở đầu/cuối.
    if (!/^[\p{L}\p{M}\p{N}_ ]{2,64}$/u.test(name)) { showToast("Tên agent: 2–64 ký tự, có thể có dấu và khoảng trắng (vd: Bé Pháp). Không dùng ký tự đặc biệt.", true); return; }
    if (!purpose) { $("#qc-purpose").focus(); showToast("Vui lòng mô tả mục đích agent.", true); return; }
    qc.name = name;
    qc.domain = $("#qc-domain").value;
    qc.purpose = purpose;
    qcRenderStep(2);
  } else if (from === 2) {
    // Nội dung từ textarea (file đã upload thì qc.skillContent đã được set)
    const pasted = $("#qc-content").value.trim();
    if (pasted && !qc.skillContent) qc.skillContent = pasted;
    qcRenderPreview();
    qcRenderStep(3);
  }
};

window.qcBack = function (from) {
  qcRenderStep(from - 1);
};

function qcRenderStep(n) {
  qc.step = n;
  // Panels
  [1, 2, 3].forEach((i) => {
    $("#qc-step-" + i).classList.toggle("active", i === n);
  });
  // Step dots
  [1, 2, 3].forEach((i) => {
    const dot = $("#sd-" + i);
    dot.classList.toggle("active", i === n);
    dot.classList.toggle("done", i < n);
    const circle = dot.querySelector(".dot-circle");
    circle.textContent = i < n ? "✓" : String(i);
  });
  // Step lines
  [1, 2].forEach((i) => {
    $("#sl-" + i).classList.toggle("done", i < n);
  });
}

function qcRenderPreview() {
  const domainLabels = { legal:"Pháp lý", finance:"Tài chính", sales:"Sales", hr:"Nhân sự", ops:"Vận hành", it:"IT", other:"Khác" };
  $("#prev-name").textContent = "@" + qc.name;
  $("#prev-domain").textContent = domainLabels[qc.domain] || qc.domain;
  $("#prev-purpose").textContent = qc.purpose;

  const skillRow = $("#prev-skill-row");
  if (qc.skillContent) {
    const label = qc.skillFilename ? `📎 ${qc.skillFilename}\n\n` : "";
    $("#prev-skill").textContent = label + qc.skillContent.slice(0, 300) + (qc.skillContent.length > 300 ? "…" : "");
    skillRow.hidden = false;
  } else {
    skillRow.hidden = true;
  }
}

/* File upload in step 2 */
$("#qc-file").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = "";

  if (/\.(txt|md)$/i.test(file.name)) {
    qc.skillContent = await file.text();
    qc.skillFilename = file.name;
    qcSetUploadDone(file.name);
    // Clear textarea nếu có
    $("#qc-content").value = "";
    return;
  }

  const label = $("#qc-upload-label");
  label.querySelector("#qc-upload-text").innerHTML = "⏳ Đang trích nội dung…";

  const fd = new FormData();
  fd.append("file", file);
  try {
    const resp = await fetch("/upload", { method: "POST", headers: headers(), body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      qcSetUploadIdle();
      showToast(err.detail || "Upload thất bại", true);
      return;
    }
    const data = await resp.json();
    if (data.content_type === "text") {
      qc.skillContent = data.text;
      qc.skillFilename = data.filename;
      qcSetUploadDone(data.filename);
      $("#qc-content").value = "";
    } else {
      qcSetUploadIdle();
      showToast("Ảnh không hỗ trợ trong wizard — dùng .pdf .docx .txt .csv .xlsx", true);
    }
  } catch (err) {
    qcSetUploadIdle();
    showToast("Upload thất bại: " + err.message, true);
  }
});

function qcSetUploadDone(filename) {
  const label = $("#qc-upload-label");
  label.classList.add("has-file");
  label.querySelector("#qc-upload-text").innerHTML = `✓ ${esc(filename)} <span style="font-size:11px;color:var(--tx3)">— click để đổi file</span>`;
}
function qcSetUploadIdle() {
  const label = $("#qc-upload-label");
  label.classList.remove("has-file");
  label.querySelector("#qc-upload-text").innerHTML =
    '📎 Click để chọn file<br><span style="font-size:11px;color:var(--tx3)">.txt .md .pdf .docx .csv .xlsx — tối đa 5 MB</span>';
  qc.skillContent = "";
  qc.skillFilename = null;
}

window.executeQuickCreate = async function () {
  const btn = $("#qc-submit-btn");
  btn.disabled = true;
  btn.textContent = "Đang gửi…";

  // Compose message có cấu trúc gửi cho master
  const skillSection = qc.skillContent
    ? `\n\n**Quy trình/tài liệu chuẩn** (chưng cất thành skill mới):\n${qc.skillContent}`
    : "";

  const msg = `Tôi muốn tạo agent với thông tin dưới đây (đã đủ, KHÔNG cần phỏng vấn thêm 5 câu):

**Tên:** ${qc.name}
**Domain:** ${qc.domain}
**Mục đích:** ${qc.purpose}${skillSection}

Hãy: (1) kiểm tra trùng lặp trước, (2) nếu có quy trình thì chưng cất thành skill, (3) soạn nhanh bản nháp persona + skill cho tôi xem và xác nhận, (4) sau khi tôi đồng ý thì tạo agent + gắn skill + báo kết quả.`;

  closeQuickCreate();
  btn.disabled = false;
  btn.textContent = "🚀 Tạo ngay";

  // Switch sang chat, mở CUỘC MỚI route thẳng tới master.
  saveCurrentConv();
  const _convId = newConvId();
  state.activeConvId = _convId;
  state.stickyAgent = "master";
  setCurrentAgent("master");
  state.convStore.set(_convId, { key: _convId, agentName: "master", agentMeta: null, lastText: "", updatedAt: Date.now(), title: null, titleSent: true });
  renderSidebar();
  $("#messages").innerHTML = "";
  switchTab("chat");

  // Một tick để DOM render xong
  await new Promise((r) => setTimeout(r, 80));
  $("#chat-input").value = msg;
  submitChat();
};

/* ─── Feedback (thumbs up/down) ─────────────────────────── */
function addFeedbackButtons(msgDiv, agentName, text) {
  const row = document.createElement("div");
  row.className = "feedback-row";
  row.innerHTML = `
    <button class="fb-btn" data-val="1" title="Câu trả lời tốt">${svgIcon("thumb-up")}</button>
    <button class="fb-btn" data-val="-1" title="Câu trả lời chưa ổn">${svgIcon("thumb-down")}</button>`;
  msgDiv.appendChild(row);
  row.querySelectorAll(".fb-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (row.dataset.voted) return;
      row.dataset.voted = "1";
      const rating = parseInt(btn.dataset.val, 10);
      btn.classList.add("active");
      row.querySelectorAll(".fb-btn").forEach((b) => b.disabled = true);
      const thanks = document.createElement("span");
      thanks.className = "fb-thanks";
      thanks.textContent = rating === 1 ? "Cảm ơn! 🙏" : "Cảm ơn phản hồi!";
      row.appendChild(thanks);
      try {
        await fetch("/feedback", {
          method: "POST",
          headers: headers({ "Content-Type": "application/json" }),
          body: JSON.stringify({ agent_name: agentName, rating, message_preview: text.slice(0, 200) }),
        });
      } catch (_) {}
    });
  });
}

/* ─── Admin stats ────────────────────────────────────────── */
async function loadStats() {
  const resp = await fetch("/review/admin/stats", { headers: headers() });
  if (!resp.ok) {
    $("#usage-tbody").innerHTML = `<tr><td colspan="5">Chỉ admin xem được.</td></tr>`;
    return;
  }
  const d = await resp.json();

  // Overview cards
  const c = d.counts || {};
  const t = d.tokens || {};
  const $n = (id, v) => { const el = $(`#${id} .sc-num`); if (el) el.textContent = v; };
  $n("sc-agents", c.agents_active ?? "—");
  $n("sc-skills", c.skills_active ?? "—");
  $n("sc-users",  c.users ?? "—");
  $n("sc-tokens", ((t.total || 0) / 1000).toFixed(1) + "k");

  // Usage table
  const usage = d.usage_by_agent || [];
  if (usage.length) {
    $("#usage-tbody").innerHTML = usage.map((r) => `
      <tr>
        <td><strong>@${esc(r.agent)}</strong></td>
        <td>${r.calls}</td>
        <td>${(r.in_tokens / 1000).toFixed(1)}k</td>
        <td>${(r.out_tokens / 1000).toFixed(1)}k</td>
        <td>${(r.total_tokens / 1000).toFixed(1)}k</td>
      </tr>`).join("");
  } else {
    $("#usage-tbody").innerHTML = `<tr><td colspan="5" style="color:var(--tx3)">Chưa có data</td></tr>`;
  }

  // Feedback table
  const fb = d.feedback_by_agent || [];
  if (fb.length) {
    $("#feedback-tbody").innerHTML = fb.map((r) => {
      const total = r.up + r.down;
      const pct = total ? Math.round(r.up / total * 100) : 0;
      return `<tr>
        <td><strong>@${esc(r.agent)}</strong></td>
        <td style="color:#6ee7b7">${r.up}</td>
        <td style="color:#f87171">${r.down}</td>
        <td>${pct}%</td>
      </tr>`;
    }).join("");
  } else {
    $("#feedback-tbody").innerHTML = `<tr><td colspan="4" style="color:var(--tx3)">Chưa có phản hồi</td></tr>`;
  }
}

/* ─── History restore (sidebar khi F5) ──────────────────── */
async function restoreHistoryFromServer() {
  try {
    const data = await fetch("/history", { headers: headers() }).then((r) => r.ok ? r.json() : []);
    if (!data.length) return;
    // Populate convStore từ server nếu chưa có (không ghi đè session hiện tại).
    // Key = conversation_id; agentName = agent hiện tại của cuộc (để hiển thị/icon).
    for (const entry of data) {
      const key = entry.conversation_id || entry.agent_name;  // fallback row cũ
      const agentName = entry.agent_name || null;
      if (!state.convStore.has(key)) {
        const agentData = _agentsCache.find((a) => a.name === agentName);
        state.convStore.set(key, {
          key,
          agentName,
          agentMeta: agentData ? { domain: agentData.domain } : null,
          lastText: entry.last_text || "…",
          updatedAt: entry.updated_at ? new Date(entry.updated_at).getTime() : Date.now(),
          title: entry.title || null,
          titleSent: true,  // đã lưu trên server rồi
          container: null,  // không có DOM — click sẽ fetch /history/{conversation_id}
        });
      }
    }
    renderSidebar();
  } catch (_) {}
}

/* ─── My Agents ─────────────────────────────────────────── */
async function loadMyAgents() {
  const grid = $("#myagents-list");
  if (!grid) return;
  grid.innerHTML = `<p class="empty">Đang tải…</p>`;
  try {
    const agents = await fetch("/agents/mine", { headers: headers() }).then((r) => r.json());
    const isGuest = !state.user;
    if (!agents.length) {
      const msg = isGuest
        ? `Bạn chưa tạo agent thử nghiệm nào. <button class="link-btn-inline" onclick="startChatWith('master','')">Thử tạo ngay →</button>`
        : `Bạn chưa tạo agent nào. <button class="link-btn-inline" onclick="startChatWith('master','')">Tạo ngay →</button>`;
      grid.innerHTML = `<p class="empty">${msg}</p>`;
      return;
    }
    const statusBadge = { private: "Nháp", pending_review: "Chờ duyệt", public: "Đang dùng", rejected: "Từ chối" };
    const statusColor = { private: "#94a3b8", pending_review: "#fbbf24", public: "#6ee7b7", rejected: "#f87171" };
    const guestBanner = isGuest ? `<div class="guest-trial-banner">
      🧪 Chế độ thử nghiệm — agent chỉ hiển thị với bạn trong 24h.
      <button class="link-btn-inline" onclick="openAuthModal(true)">Đăng nhập để lưu vĩnh viễn →</button>
    </div>` : "";
    grid.innerHTML = guestBanner + agents.map((a) => {
      const st = a.status;
      const color = statusColor[st] || "#94a3b8";
      const label = statusBadge[st] || st;
      const isAdmin = state.user?.role === "admin";
      // Guest không sửa/xóa/submit qua UI (API vẫn block ở server)
      const canEdit = !isGuest && st !== "pending_review" && (st !== "public" || isAdmin);
      const canDelete = !isGuest && (st === "private" || st === "rejected");
      const canSubmit = !isGuest && st === "private";
      const canRetract = !isGuest && st === "pending_review";
      const canResubmit = !isGuest && st === "rejected";
      // C1 (lan toả): dòng trạng thái chia sẻ rõ ràng theo vòng đời private→pending→public.
      let shareNote = "";
      if (st === "public") {
        shareNote = a.visibility === "company"
          ? `✅ Cả công ty đang dùng${a.calls ? ` · ${a.calls} lượt` : ""}`
          : "🙈 Đang ẩn khỏi công ty (chỉ mình bạn dùng)";  // public + private = tạm ẩn (I4)
        // Siết quyền: agent đã public chỉ nhà quản lý cập nhật được.
        if (!isAdmin) shareNote += "<br>🛡️ Đã duyệt — chỉ nhà quản lý cập nhật được";
      } else if (st === "pending_review") {
        shareNote = "⏳ Chờ duyệt — duyệt xong cả công ty dùng được";
      } else if (st === "private") {
        shareNote = "🔒 Riêng bạn — bấm “Gửi duyệt” để chia sẻ cả công ty";
      }
      // JSON safe cho data attribute: esc() đổi " → &quot; để không vỡ attribute
      const safeAgent = esc(JSON.stringify(a));
      return `<div class="mp-card">
        <div class="mp-card-hd">
          <span class="mp-icon">${domainIcon[a.domain] || svgIcon("bot")}</span>
          <span class="mp-badge" style="background:${color}22;color:${color}">${label}</span>
        </div>
        <div class="mp-name">${esc(a.name)}</div>
        <div class="mp-desc">${esc(a.tagline || a.description.slice(0, 80))}</div>
        ${shareNote ? `<div class="mp-share-note">${shareNote}</div>` : ""}
        ${a.review_note ? `<div class="mp-review-note">${svgIcon("chat")} ${esc(a.review_note)}</div>` : ""}
        <div class="mp-actions">
          ${canEdit ? `<button class="btn-sm" data-agent="${safeAgent}" onclick="openAgentEditModal(JSON.parse(this.dataset.agent))">Sửa</button>` : ""}
          ${canSubmit ? `<button class="btn-sm btn-sm-primary" onclick="submitMyAgent('${esc(a.name)}')">Gửi duyệt</button>` : ""}
          ${isGuest && st === "private" ? `<button class="btn-sm btn-sm-primary" onclick="openAuthModal(true)">Đăng nhập để chia sẻ</button>` : ""}
          ${canRetract ? `<button class="btn-sm" onclick="retractMyAgent('${esc(a.name)}')">Hủy nộp duyệt</button>` : ""}
          ${canResubmit ? `<button class="btn-sm btn-sm-primary" onclick="submitMyAgent('${esc(a.name)}')">Gửi lại</button>` : ""}
          ${canDelete ? `<button class="btn-sm btn-sm-danger" onclick="deleteMyAgent('${esc(a.name)}')">Xóa</button>` : ""}
          <button class="btn-sm" onclick="startChatWith('${esc(a.name)}','')">Chat →</button>
        </div>
      </div>`;
    }).join("");
  } catch (e) {
    grid.innerHTML = `<p class="empty">Lỗi tải danh sách: ${esc(String(e))}</p>`;
  }
}

window.submitMyAgent = async function(name) {
  try {
    const r = await fetch(`/agents/${encodeURIComponent(name)}/submit`, { method: "POST", headers: headers() });
    const d = await r.json();
    if (!r.ok) { showToast(d.detail || "Lỗi gửi duyệt", true); return; }
    showToast("Đã gửi duyệt! Admin duyệt xong là cả công ty dùng được 🎉");  // C1: nhấn "lan toả"
    loadMyAgents();
    refreshAgentsCache();
  } catch (e) { showToast("Lỗi kết nối", true); }
};

window.deleteMyAgent = async function(name) {
  if (!(await showConfirm(`Xóa agent "${name}"? Hành động này không thể hoàn tác.`, { okText: "Xóa", danger: true }))) return;
  const r = await fetch(`/agents/${encodeURIComponent(name)}`, { method: "DELETE", headers: headers() });
  const d = await r.json();
  if (!r.ok) { showToast(d.detail || "Lỗi xóa", true); return; }
  showToast(`Đã xóa agent "${name}"`);
  loadMyAgents();
  refreshAgentsCache();
};

window.retractMyAgent = async function(name) {
  if (!(await showConfirm(`Hủy nộp duyệt agent "${name}"?\nAgent sẽ về trạng thái Nháp, bạn có thể sửa và gửi lại.`, { okText: "Hủy nộp duyệt" }))) return;
  const r = await fetch(`/agents/${encodeURIComponent(name)}/retract`, { method: "POST", headers: headers() });
  const d = await r.json();
  if (!r.ok) { showToast(d.detail || "Lỗi hủy nộp duyệt", true); return; }
  loadMyAgents();
  refreshAgentsCache();
};

window.openAgentEditModal = function(agent) {
  $("#ae-name").value = agent.name;
  $("#ae-tagline").value = agent.tagline || "";
  $("#ae-description").value = agent.description || "";
  $("#ae-prompt").value = agent.system_prompt || "";
  $("#ae-domain").value = agent.domain || "";
  // Bỏ sửa visibility trong form (đi qua flow chia sẻ riêng) — field đã gỡ khỏi modal.
  $("#ae-error").textContent = "";
  // Tài liệu kiến thức (RAG) — chỉ hiện khi module bật.
  const kb = $("#ae-knowledge");
  if (state.ragEnabled) {
    kb.style.display = "";
    $("#ae-doc-status").textContent = "";
    _wireDocUpload(agent.name);
    loadAgentDocs(agent.name);
  } else {
    kb.style.display = "none";
  }
  $("#agent-edit-modal").hidden = false;
};

window.closeAgentEditModal = function() {
  $("#agent-edit-modal").hidden = true;
};

async function loadAgentDocs(agentName) {
  const list = $("#ae-doc-list");
  list.innerHTML = '<span style="font-size:12px;color:var(--tx3)">Đang tải…</span>';
  try {
    const r = await fetch(`/agents/${encodeURIComponent(agentName)}/docs`, { headers: headers() });
    if (!r.ok) { list.innerHTML = ""; return; }
    const { docs } = await r.json();
    if (!docs.length) { list.innerHTML = '<span style="font-size:12px;color:var(--tx3)">Chưa có tài liệu nào.</span>'; return; }
    list.innerHTML = docs.map((d) => `
      <div style="display:flex;align-items:center;gap:8px;font-size:13px">
        <span>📄</span>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(d.filename)}</span>
        <span style="color:var(--tx3);font-size:11px">${d.chunk_count} đoạn</span>
        <button class="btn-sm btn-sm-danger" onclick="deleteAgentDoc('${esc(agentName)}',${d.id})">✕</button>
      </div>`).join("");
  } catch (_) { list.innerHTML = ""; }
}

let _docUploadAgent = null;
function _wireDocUpload(agentName) {
  _docUploadAgent = agentName;
  const input = $("#ae-doc-file");
  input.value = "";
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    const status = $("#ae-doc-status");
    status.textContent = "Đang xử lý tài liệu…";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await fetch(`/agents/${encodeURIComponent(_docUploadAgent)}/docs`, { method: "POST", headers: headers(), body: fd });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) { status.textContent = "Lỗi: " + (d.detail || r.status); return; }
      status.textContent = `Đã thêm (${d.chunk_count} đoạn) ✓`;
      loadAgentDocs(_docUploadAgent);
    } catch (e) {
      status.textContent = "Lỗi tải lên: " + e.message;
    }
    input.value = "";
  };
}

window.deleteAgentDoc = async function(agentName, docId) {
  if (!(await showConfirm("Xoá tài liệu này khỏi kiến thức của agent?", { okText: "Xoá" }))) return;
  try {
    await fetch(`/agents/${encodeURIComponent(agentName)}/docs/${docId}`, { method: "DELETE", headers: headers() });
  } catch (_) {}
  loadAgentDocs(agentName);
};

window.saveAgentEdit = async function() {
  const name = $("#ae-name").value;
  const body = {
    tagline: $("#ae-tagline").value.trim() || null,
    description: $("#ae-description").value.trim() || null,
    system_prompt: $("#ae-prompt").value.trim() || null,
    domain: $("#ae-domain").value || null,
    // visibility KHÔNG gửi từ form sửa — quản lý qua flow chia sẻ (submit/hạ riêng tư).
  };
  const errEl = $("#ae-error");
  errEl.textContent = "";
  try {
    const r = await fetch(`/agents/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!r.ok) { errEl.textContent = d.detail || "Lỗi lưu"; return; }
    closeAgentEditModal();
    loadMyAgents();
    refreshAgentsCache();
  } catch (e) { errEl.textContent = "Lỗi kết nối"; }
};

// Onboarding modal (cờ localStorage) đã thay bằng carousel NHÚNG trong welcome
// chat — xem welcomeCarouselHTML() + wireWelcomeCarousel() ở trên. Bỏ initOnboarding.

/* ─── Init ──────────────────────────────────────────────── */
// 1. Load auth state trước, sau đó mới render tabs + catalog
loadAuthState().then(() => {
  loadCatalog();
  loadHomeAgents();
  // Restore sidebar chỉ khi đã login
  if (state.user) {
    refreshAgentsCache().then(() => restoreHistoryFromServer());
  } else {
    refreshAgentsCache();
  }
});
