/* Agent Hub UI — vanilla JS, chỉ gọi REST API. */

const $ = (sel) => document.querySelector(sel);

const state = {
  userId: localStorage.getItem("hub_user") || "an.nguyen",
  stickyAgent: null,
  adminIds: ["admin"],
  attachment: null,
  convStore: new Map(), // Map<agentKey, {key, agentName, agentMeta, container, lastText, updatedAt}>
};

const domainIcon = { legal: "⚖️", finance: "💰", sales: "📊", hr: "👥", ops: "⚙️", it: "💻" };
const userLabels  = { "an.nguyen": "A", "binh.tran": "B", admin: "Ad" };

function headers(extra = {}) {
  return { "X-User-Id": state.userId, ...extra };
}

/* ─── User switcher ─────────────────────────────────────── */
const userSwitcher = $("#user-switcher");
userSwitcher.value = state.userId;

function syncAvatar() {
  $("#user-avatar").textContent = userLabels[state.userId] || state.userId[0].toUpperCase();
}
syncAvatar();

userSwitcher.addEventListener("change", () => {
  state.userId = userSwitcher.value;
  localStorage.setItem("hub_user", state.userId);
  state.stickyAgent = null;
  state.convStore.clear();
  clearAttachments();
  hideMentionDropdown();
  $("#messages").innerHTML = "";
  updateChatHeader(null);
  renderSidebar();
  syncAvatar();
  refreshTabsForUser();
  loadCatalog();
  refreshAgentsCache();
  showWelcome();
});

function refreshTabsForUser() {
  const isAdmin = state.adminIds.includes(state.userId);
  $("#review-tab").hidden = !isAdmin;
  $("#stats-tab").hidden = !isAdmin;
  if (!isAdmin && ($("#panel-review").classList.contains("active") || $("#panel-stats").classList.contains("active"))) switchTab("home");
}

/* ─── Tabs ──────────────────────────────────────────────── */
document.querySelectorAll(".tab").forEach((btn) =>
  btn.addEventListener("click", () => switchTab(btn.dataset.tab))
);

window.switchTab = function(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `panel-${name}`));
  if (name === "catalog") loadCatalog();
  if (name === "review")  loadReview();
  if (name === "home")    loadHomeAgents();
  if (name === "stats")   loadStats();
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
      ? `<span class="ahc-popular">🔥 Phổ biến</span>`
      : a.calls > 0
        ? `<span class="ahc-calls">${a.calls} lần</span>`
        : "";
    return `<div class="ahc" onclick="startChatWith('${esc(a.name)}','${esc(a.tagline || a.description)}')">
      <span class="ahc-icon">${domainIcon[a.domain] || "🤖"}</span>
      <div class="ahc-name">${esc(a.name)}${callsBadge}</div>
      <div class="ahc-slug">@${esc(a.slug || a.name)}</div>
      <div class="ahc-desc">${esc(a.tagline || a.description.split(/[.。]/)[0].slice(0, 80))}</div>
      <div class="ahc-tag"><span class="tag">${esc(a.domain || "general")}</span></div>
    </div>`;
  });

  cards.push(`
    <div class="ahc new-card" onclick="startChatWith('master','')">
      <span class="ahc-icon">✨</span>
      <div class="ahc-name">Tạo agent mới</div>
      <div class="ahc-desc">Chat với Master để tạo agent chuyên biệt theo nghiệp vụ của bạn — không cần code.</div>
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
  saveCurrentConv();
  state.stickyAgent = name;
  updateChatHeader(name);
  $("#messages").innerHTML = "";
  // Tạo entry trong convStore nếu chưa có
  if (!state.convStore.has(name)) {
    const agentData = _agentsCache.find((a) => a.name === name);
    state.convStore.set(name, { key: name, agentName: name, agentMeta: agentData ? { domain: agentData.domain } : null, lastText: "", updatedAt: Date.now() });
  } else {
    state.convStore.get(name).updatedAt = Date.now();
  }
  renderSidebar();
  switchTab("chat");
  if (name === "master") {
    addHandoff("master", "");
  } else {
    addHandoff(name, desc);
  }
};

/* ─── Welcome (chat tab, no messages) ──────────────────── */
async function showWelcome() {
  const msgs = $("#messages");
  if (msgs.children.length > 0) return;

  let agents = [];
  try { agents = await fetch("/agents", { headers: headers() }).then((r) => r.json()); } catch (_) {}
  const active = agents.filter((a) => a.status === "public");

  const firstName = state.userId.split(".")[0];
  const welcome = document.createElement("div");
  welcome.id = "welcome";

  const cards = active.map((a) => {
    const hint = a.tagline || a.description.split(/[.。]/)[0].slice(0, 52);
    return `<button class="wcard" data-msg="${esc(hint)}">
      <span class="wcard-icon">${domainIcon[a.domain] || "🤖"}</span>
      <div class="wcard-name">${esc(a.name)}</div>
      <div class="wcard-hint">${esc(hint)}</div>
    </button>`;
  });
  cards.push(`<button class="wcard" data-msg="Tôi muốn tạo một agent mới">
    <span class="wcard-icon">✨</span>
    <div class="wcard-name">Tạo agent mới</div>
    <div class="wcard-hint">Master phỏng vấn và tạo agent cho bạn</div>
  </button>`);

  welcome.innerHTML = `
    <p class="welcome-greeting">Chào ${firstName}! 👋</p>
    <p class="welcome-sub">Gõ câu hỏi tự nhiên, hoặc chọn một gợi ý bên dưới để bắt đầu nhé</p>
    <div class="welcome-grid">${cards.join("")}</div>`;
  msgs.appendChild(welcome);

  welcome.querySelectorAll(".wcard").forEach((btn) =>
    btn.addEventListener("click", () => {
      $("#chat-input").value = btn.dataset.msg;
      hideWelcome();
      submitChat();
    })
  );
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
  const icon = domainIcon[agentData?.domain] || "🤖";
  const label = agentData?.name || agentName;
  card.innerHTML = `
    <div class="sac-header">
      <span class="sac-icon">${icon}</span>
      <span class="sac-name">@${esc(agentName)}</span>
      <span class="sac-label">${esc(label)}</span>
      ${isError ? '<span class="sac-err-badge">lỗi</span>' : ''}
    </div>
    <div class="sac-body">${output ? renderMarkdown(output) : '<em>Không có kết quả</em>'}</div>`;
  $("#messages").appendChild(card);
  scrollBottom();
  return card;
}

/* ─── Process accordion ─────────────────────────────────────
   Gom các bước xử lý (gọi tool, suy nghĩ trung gian) vào 1 khối thu gọn được,
   TÁCH khỏi câu trả lời cuối — giống cách Claude hiển thị tool-use. */
const TOOL_LABELS = {
  "web-search.search": "🔎 Tìm kiếm web",
  "web-search.fetch":  "🌐 Đọc nội dung trang",
};

function toolStepHtml(data) {
  const base = TOOL_LABELS[data.name] || `🔧 ${esc(data.name)}`;
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
        `<span class="proc-ic">⚙</span>` +
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

function finalizeTurnProcess(assistantDiv) {
  const proc = assistantDiv && assistantDiv.querySelector(".turn-process");
  if (!proc) return;
  proc.classList.remove("open");            // thu gọn khi xong — kết quả cuối nổi bật
  proc.classList.add("done");
  proc.querySelector(".proc-ic").textContent = "✓";
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

  const card = document.createElement("div");
  card.className = "handoff-card";
  card.innerHTML = `
    <div class="handoff-title">${isMaster ? "✨ Master" : "👋 " + esc(name)}</div>
    <div class="handoff-body">${
      isMaster
        ? "Chào bạn! Mình là <strong>Master</strong> — chuyên giúp tạo agent mới 🏗️. Bạn muốn tìm agent có sẵn hay xây một con riêng? Kể mình nghe nhé!"
        : `Chào bạn! Mình là <strong>${esc(name)}</strong>${short ? " — " + esc(short) : ""}. Cứ hỏi thoải mái, mình ở đây rồi 😊`
    }</div>
    ${statusBadge}`;
  $("#messages").appendChild(card);
  scrollBottom();
  return card;
}

function scrollBottom() {
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

/* ─── Conv store (per-agent conversation persistence) ─── */
function currentConvKey() {
  return state.stickyAgent || "__auto__";
}

function saveCurrentConv() {
  const msgs = $("#messages");
  const hasReal = [...msgs.children].some((el) => el.id !== "welcome");
  if (!hasReal) return;
  const key = currentConvKey();
  const container = document.createElement("div");
  while (msgs.firstChild) container.appendChild(msgs.firstChild);
  const existing = state.convStore.get(key) || {};
  state.convStore.set(key, { ...existing, key, agentName: state.stickyAgent, container, updatedAt: Date.now() });
}

async function restoreConv(key) {
  const msgs = $("#messages");
  const entry = state.convStore.get(key);
  if (entry && entry.container && entry.container.children.length) {
    // In-memory (session hiện tại)
    while (entry.container.firstChild) msgs.appendChild(entry.container.firstChild);
    scrollBottom();
    return;
  }
  // Fetch lịch sử từ server (sau F5)
  const agentName = key === "__auto__" ? null : key;
  if (agentName) {
    try {
      const history = await fetch(`/history/${encodeURIComponent(agentName)}`, { headers: headers() })
        .then((r) => r.ok ? r.json() : []);
      if (history.length) {
        addHandoff(agentName, "");
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
            const tag = agentName === "master" ? "Master Agent" : "@" + agentName;
            const div = addMsg("assistant", "", tag);
            div.querySelector(".msg-content").innerHTML = renderMarkdown(msg.content);
          }
        }
        scrollBottom();
        return;
      }
    } catch (_) {}
  }
  showWelcome();
}

window.switchToConv = async function(key) {
  if (key === currentConvKey()) return;
  saveCurrentConv();
  state.stickyAgent = key === "__auto__" ? null : key;
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
    state.stickyAgent = null;
    updateChatHeader(null);
    $("#messages").innerHTML = "";
    showWelcome();
  }
  renderSidebar();
  const agentName = key === "__auto__" ? null : key;
  if (agentName) {
    try {
      await fetch(`/history/${encodeURIComponent(agentName)}`, { method: "DELETE", headers: headers() });
    } catch (_) {}
  }
};

function updateChatHeader(agentName) {
  const avatar = $("#chd-avatar");
  const nameEl = $("#chd-name");
  const subEl  = $("#chd-sub");
  if (!agentName) {
    avatar.textContent = "✦";
    avatar.className   = "chd-avatar chd-avatar-auto";
    nameEl.textContent = "Tự điều phối";
    subEl.textContent  = "Hệ thống tự tìm agent phù hợp nhất";
    return;
  }
  if (agentName === "master") {
    avatar.textContent = "M";
    avatar.className   = "chd-avatar chd-avatar-master";
    nameEl.textContent = "Master Agent";
    subEl.textContent  = "Factory + điều phối — tạo agent mới hoặc kết nối chuyên gia";
    return;
  }
  const a = _agentsCache.find((x) => x.name === agentName);
  const domain = a?.domain || "default";
  avatar.textContent = agentName[0].toUpperCase();
  avatar.className   = `chd-avatar chd-avatar-${domain}`;
  nameEl.textContent = a?.name || agentName;
  subEl.textContent  = a?.tagline || a?.description?.split(/[.。]/)[0]?.slice(0, 80) || "";
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
    const displayName = !agentName ? "Tự điều phối" : agentName === "master" ? "Master" : agentName;
    const firstChar   = !agentName ? "✦" : agentName[0].toUpperCase();
    const domain = e.agentMeta?.domain || (agentName === "master" ? "master" : !agentName ? "auto" : "default");
    const preview = (e.lastText || "…").slice(0, 48);
    return `<div class="conv-item${isActive ? " active" : ""}" onclick="switchToConv('${esc(e.key)}')" data-key="${esc(e.key)}">
      <div class="conv-av conv-av-${domain}">${firstChar}</div>
      <div class="conv-info">
        <div class="conv-name">${esc(displayName)}</div>
        <div class="conv-last">${esc(preview)}</div>
      </div>
      <button class="conv-del" onclick="event.stopPropagation(); deleteConv('${esc(e.key)}')" title="Xóa cuộc trò chuyện">✕</button>
    </div>`;
  }).join("");
}

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
    setTimeout(() => setLabel("Sắp xong, đang hoàn thiện câu trả lời…"), 45000),
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
    delete_agent:      { label: 'Xóa agent',                 phase: 'build' },
    attach_skill:      { label: 'Gắn skill vào agent',       phase: 'build' },
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
    return this.TOOLS[name]?.label || name;
  },

  _render() {
    if (!this.el) return;
    const stepsHtml = this.steps.map((s) => `
      <div class="bt-step ${s.isError ? 'error' : 'done'}">
        <span class="bt-icon">${s.isError ? '❌' : '✅'}</span>
        <span class="bt-label">${s.label}</span>
      </div>`).join('');
    this.el.innerHTML = `
      <div class="bt-header">🔨 Đang xây dựng cho bạn…</div>
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
        <span class="bt-icon">${s.isError ? '❌' : '✅'}</span>
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
      <div class="abc-avatar" id="abc-avatar">🤖</div>
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

  // Tạo convStore entry khi bắt đầu send (trước khi meta event đổi stickyAgent)
  const _preSendKey = currentConvKey();
  if (!state.convStore.has(_preSendKey)) {
    state.convStore.set(_preSendKey, { key: _preSendKey, agentName: state.stickyAgent, agentMeta: null, lastText: message.slice(0, 60), updatedAt: Date.now() });
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

  try {
    const resp = await fetch("/chat", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ message, agent_name: state.stickyAgent, attachment: attachmentPayload }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      addMsg("error", `Lỗi ${resp.status}: ${err.detail}`);
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
          const _prevKey = state.stickyAgent || "__auto__";
          state.stickyAgent = data.agent_name;
          setCurrentAgent(data.agent_name);

          // Migrate convStore: nếu đang ở __auto__ và được route sang agent → chuyển entry
          if (_prevKey !== data.agent_name) {
            if (state.convStore.has(_prevKey) && !state.convStore.has(data.agent_name)) {
              const _e = state.convStore.get(_prevKey);
              state.convStore.delete(_prevKey);
              _e.key = data.agent_name; _e.agentName = data.agent_name;
              state.convStore.set(data.agent_name, _e);
            } else if (!state.convStore.has(data.agent_name)) {
              state.convStore.set(data.agent_name, { key: data.agent_name, agentName: data.agent_name, agentMeta: null, lastText: "", updatedAt: Date.now() });
            }
          }
          const _metaEntry = state.convStore.get(data.agent_name);
          if (_metaEntry) {
            _metaEntry.updatedAt = Date.now();
            const _aData = _agentsCache.find((a) => a.name === data.agent_name);
            if (_aData) _metaEntry.agentMeta = { domain: _aData.domain };
          }
          renderSidebar();

          // Handoff card khi agent thay đổi (không repeat trong sticky session)
          if (data.agent_name !== _lastRoutedAgent && data.routed_by !== "explicit") {
            addHandoff(data.agent_name, data.agent_description || "");
          }
          _lastRoutedAgent = data.agent_name;

        } else if (ev === "delta") {
          hideTyping();
          if (!assistantDiv) {
            const tag = state.stickyAgent === "master" ? "Master Agent" : "@" + state.stickyAgent;
            assistantDiv = addMsg("assistant", "", tag);
          }
          assistantText += data.text;
          assistantDiv.querySelector(".msg-content").innerHTML = renderMarkdown(assistantText);
          scrollBottom();

        } else if (ev === "tool") {
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
              const tag = state.stickyAgent === "master" ? "Master Agent" : "@" + state.stickyAgent;
              assistantDiv = addMsg("assistant", "", tag);
            }
            // Narration trước khi gọi tool = "suy nghĩ" → gấp vào quá trình, không lẫn vào kết quả
            if (assistantText.trim()) {
              turnAddStep(assistantDiv, `<div class="ps-think">${renderMarkdown(assistantText)}</div>`, "think");
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

        } else if (ev === "delegate") {
          const isEscalation = state.stickyAgent && state.stickyAgent !== "master";
          _pendingDelegate = { agent_name: data.agent_name, message: data.message, isEscalation };
          break; // dừng đọc stream — agent mới sẽ tiếp tục

        } else if (ev === "done") {
          lastStopReason = data.stop_reason || null;

        } else if (ev === "error") {
          hideTyping();
          addMsg("error", data.message);
        }
      }
    }
    hideTyping();
    builderTracker.finish();
    finalizeTurnProcess(assistantDiv);  // thu gọn "quá trình xử lý" — kết quả cuối nổi bật
    // Luôn refresh sau mỗi stream — bắt mọi trường hợp master tạo/xóa agent
    refreshAgentsCache();
    // Render markdown sau khi stream xong
    if (assistantDiv) {
      const mc = assistantDiv.querySelector(".msg-content");
      if (mc) mc.innerHTML = renderMarkdown(assistantText);
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
    // Cập nhật preview text trong sidebar
    if (assistantText) {
      const _doneKey = currentConvKey();
      const _doneEntry = state.convStore.get(_doneKey);
      if (_doneEntry) { _doneEntry.lastText = assistantText.slice(0, 60); _doneEntry.updatedAt = Date.now(); }
      renderSidebar();
    }

    // Auto-handoff: master delegate → agent, hoặc agent escalate → master → agent
    if (_pendingDelegate) {
      const { agent_name, message: delegateMsg, isEscalation } = _pendingDelegate;
      _pendingDelegate = null;

      if (isEscalation) {
        // Escalation từ agent con: hiện toast để user biết chuyện gì đang xảy ra
        addMsg("tool-note", `↩ Đang hỏi Master tìm người phù hợp hơn…`);
      }

      await new Promise((r) => setTimeout(r, isEscalation ? 300 : 500));
      await refreshAgentsCache();
      state.stickyAgent = agent_name;
      setCurrentAgent(agent_name);
      if (!state.convStore.has(agent_name)) {
        const _ad = _agentsCache.find((a) => a.name === agent_name);
        state.convStore.set(agent_name, { key: agent_name, agentName: agent_name, agentMeta: _ad ? { domain: _ad.domain } : null, lastText: "", updatedAt: Date.now() });
      } else {
        state.convStore.get(agent_name).updatedAt = Date.now();
      }
      renderSidebar();
      const agentData = _agentsCache.find((a) => a.name === agent_name);
      addHandoff(agent_name, agentData?.description || "");
      // Gửi message gốc sang agent mới — không cần user gõ lại
      $("#chat-input").value = delegateMsg;
      submitChat();
    }
  } catch (err) {
    hideTyping();
    addMsg("error", `Ủa, mất kết nối rồi 😅 Thử lại nhé! (${err.message})`);
  } finally {
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
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitChat(); }
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
    if (!resp.ok) { alert((await resp.json().catch(() => ({}))).detail || `Lỗi upload ${resp.status}`); return; }
    addAttachment(await resp.json());
  } catch (err) {
    removePlaceholderChip(placeholderId);
    alert(`Upload thất bại: ${err.message}`);
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

/* ─── Catalog ───────────────────────────────────────────── */
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

async function loadCatalog() {
  const [agents, skills] = await Promise.all([
    fetch("/agents", { headers: headers() }).then((r) => r.json()),
    fetch("/skills", { headers: headers() }).then((r) => r.json()),
  ]);
  const q      = $("#catalog-search").value.toLowerCase();
  const domain = $("#catalog-domain").value;

  const domains = [...new Set([...agents, ...skills].map((x) => x.domain).filter(Boolean))];
  const sel = $("#catalog-domain"), cur = sel.value;
  sel.innerHTML = '<option value="">Mọi domain</option>' + domains.map((d) => `<option>${d}</option>`).join("");
  sel.value = cur;

  // "Agent của tôi" — draft/pending/rejected của current user
  const mine = agents.filter((a) => a.created_by === state.userId && a.status !== "public");
  const mySection = $("#my-agents-section");
  if (mine.length) {
    $("#my-agent-list").innerHTML = mine.map(myAgentCard).join("");
    mySection.hidden = false;
  } else {
    mySection.hidden = true;
  }

  const match = (x) => (!domain || x.domain === domain) && (!q || (x.name + " " + (x.tagline || "") + " " + (x.slug || "") + " " + x.description).toLowerCase().includes(q));

  // Tất cả agents (active + không phải của mình)
  const publicAgents = agents.filter((a) => a.status === "public" || a.created_by !== state.userId);
  $("#agent-list").innerHTML = publicAgents.filter(match).map((a) => {
    const callsStr = a.calls >= 5
      ? `<span class="calls-badge popular">🔥 ${a.calls} lần</span>`
      : a.calls > 0
        ? `<span class="calls-badge">${a.calls} lần</span>`
        : "";
    return `<div class="ccard">
      <div class="ccard-name">
        ${esc(a.name)} <span class="ccard-slug">@${esc(a.slug || a.name)}</span>
        <span class="badge ${a.status}">${a.status}</span>
        ${a.has_pending_changes ? '<span class="badge pending_review">sửa đổi chờ duyệt</span>' : ""}
        ${callsStr}
      </div>
      <div class="ccard-desc">${esc(a.tagline || a.description.split(/[.。]/)[0].slice(0, 100))}</div>
      <div class="ccard-meta">domain: ${a.domain || "—"} · skills: ${a.skills.join(", ") || "—"}</div>
    </div>`;
  }).join("") || '<div class="empty">Chưa có agent nào đang active</div>';

  $("#skill-list").innerHTML = skills.filter(match).map((s) => `
    <div class="ccard">
      <div class="ccard-name">
        ${esc(s.name)}
        <span class="badge ${s.status}">${s.status} v${s.version}</span>
      </div>
      <div class="ccard-desc">${esc(s.description)}</div>
      <div class="ccard-meta">domain: ${s.domain || "—"} · tạo bởi: ${s.created_by || "—"}</div>
    </div>`).join("") || '<div class="empty">Chưa có skill</div>';
}
$("#catalog-search").addEventListener("input", loadCatalog);
$("#catalog-domain").addEventListener("change", loadCatalog);

/* ─── Review ────────────────────────────────────────────── */
async function loadReview() {
  const resp = await fetch("/review/pending", { headers: headers() });
  if (!resp.ok) { $("#pending-list").innerHTML = '<div class="empty">Chỉ admin xem được trang này.</div>'; return; }
  const data = await resp.json();
  const blocks = [];

  for (const a of data.agents) {
    blocks.push(`<div class="review-card">
      <h3>🤖 ${esc(a.name)} <code class="agent-slug">@${esc(a.slug || a.name)}</code> <span class="badge ${a.status}">${a.status}</span></h3>
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
  const resp = await fetch(`/review/${kind}/${name}/${action}`, {
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
  if (btn) { btn.disabled = true; btn.textContent = "Đang gửi…"; }
  try {
    const resp = await fetch(`/agents/${encodeURIComponent(name)}/submit`, {
      method: "POST",
      headers: headers(),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      alert(err.detail || `Lỗi ${resp.status}`);
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
    alert(`Không gửi được: ${err.message}`);
    if (btn) { btn.disabled = false; btn.textContent = "🚀 Submit để chia sẻ"; }
  }
};

window.submitAgentFromHandoff = async function (name, btn) {
  await submitAgentForReview(name, btn);
};

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function highlightMentionsHtml(text) {
  return esc(text).replace(/@([a-z][a-z0-9-]*)/g, '<span class="mention-tag">@$1</span>');
}

/* Inline-level markdown: code, link, bold, italic, mention. Tự escape HTML. */
function renderInline(s) {
  // Tách inline code ra placeholder để không bị xử lý bold/italic bên trong
  const codes = [];
  let h = String(s ?? "").replace(/`([^`\n]+)`/g, (_m, c) => {
    codes.push(c);
    return `${codes.length - 1}`;
  });
  h = esc(h);
  // Link [text](url) — chỉ http/https
  h = h.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  // Bold trước, italic sau (để **x** không bị * nuốt)
  h = h.replace(/\*\*([^*]+?)\*\*/g, "<strong>$1</strong>");
  h = h.replace(/(^|[^*])\*([^*\n]+?)\*(?!\*)/g, "$1<em>$2</em>");
  // @mention
  h = h.replace(/@([a-z][a-z0-9-]*)/g, '<span class="mention-tag">@$1</span>');
  // Khôi phục inline code
  h = h.replace(/(\d+)/g, (_m, i) => `<code>${esc(codes[i])}</code>`);
  return h;
}

/* Block-level markdown → HTML: heading, list (ul/ol), code fence, quote, hr, paragraph.
   Đủ cho chat agent — không phải full CommonMark nhưng xử lý đúng các pattern thường gặp. */
function renderMarkdown(src) {
  if (!src) return "";

  // 1) Rút code fence ``` ra placeholder (giữ nguyên nội dung bên trong)
  const blocks = [];
  let text = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (_m, _lang, code) => {
    blocks.push(`<pre class="code-block"><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return ` ${blocks.length - 1} `;
  });

  const out = [];
  let para = [];
  let quote = [];
  let listTag = null; // 'ul' | 'ol'

  const flushPara = () => { if (para.length) { out.push("<p>" + renderInline(para.join(" ")) + "</p>"); para = []; } };
  const closeList = () => { if (listTag) { out.push(`</${listTag}>`); listTag = null; } };
  const flushQuote = () => { if (quote.length) { out.push("<blockquote>" + renderInline(quote.join(" ")) + "</blockquote>"); quote = []; } };
  const flushAll = () => { flushPara(); flushQuote(); closeList(); };

  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    const cbMatch = line.match(/^ (\d+) $/);

    if (cbMatch) {                                   // code block độc lập
      flushAll();
      out.push(blocks[+cbMatch[1]]);
    } else if (!line.trim()) {                       // dòng trống → ngắt block
      flushAll();
    } else if (/^#{1,6}\s+/.test(line)) {            // heading
      flushAll();
      const m = line.match(/^(#{1,6})\s+(.*)$/);
      const lvl = Math.min(m[1].length, 4);          // h5/h6 dồn về h4 cho gọn
      out.push(`<h${lvl}>${renderInline(m[2])}</h${lvl}>`);
    } else if (/^\s*[-*+]\s+/.test(line) && !/^\s*([-*_])\1{2,}\s*$/.test(line)) { // bullet
      flushPara(); flushQuote();
      if (listTag !== "ul") { closeList(); out.push("<ul>"); listTag = "ul"; }
      out.push("<li>" + renderInline(line.replace(/^\s*[-*+]\s+/, "")) + "</li>");
    } else if (/^\s*\d+\.\s+/.test(line)) {           // numbered list
      flushPara(); flushQuote();
      if (listTag !== "ol") { closeList(); out.push("<ol>"); listTag = "ol"; }
      out.push("<li>" + renderInline(line.replace(/^\s*\d+\.\s+/, "")) + "</li>");
    } else if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {  // horizontal rule
      flushAll();
      out.push("<hr>");
    } else if (/^>\s?/.test(line)) {                  // blockquote
      flushPara(); closeList();
      quote.push(line.replace(/^>\s?/, ""));
    } else {                                          // text thường → gộp vào paragraph
      flushQuote(); closeList();
      para.push(line.trim());
    }
  }
  flushAll();

  // 2) Khôi phục code block còn sót (vd nằm trong paragraph)
  return out.join("\n").replace(/ (\d+) /g, (_m, i) => blocks[+i]);
}

/* ─── @mention dropdown ─────────────────────────────────── */
function showMentionDropdown(agents) {
  const dd = $("#mention-dropdown");
  if (!agents.length) { hideMentionDropdown(); return; }
  mention.selIdx = 0;
  dd.innerHTML = agents.slice(0, 6).map((a, i) => `
    <div class="mention-item${i === 0 ? " active" : ""}" data-name="${esc(a.slug || a.name)}">
      <span class="mi-icon">${domainIcon[a.domain] || "🤖"}</span>
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
  name: "master", slug: "master",
  description: "Tạo agent mới hoặc điều phối sang chuyên gia phù hợp",
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
    if (!name) { $("#qc-name").focus(); return alert("Vui lòng nhập tên agent."); }
    if (!/^[A-Z][A-Za-z0-9]+$/.test(name)) return alert("Tên phải dạng PascalCase, không dấu, không khoảng trắng.\nvd: ThamDinhHopDong");
    if (!purpose) { $("#qc-purpose").focus(); return alert("Vui lòng mô tả mục đích agent."); }
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
  const domainLabels = { legal:"⚖️ Legal", finance:"💰 Finance", sales:"📊 Sales", hr:"👥 HR", ops:"⚙️ Operations", it:"💻 IT", other:"📌 Khác" };
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
      return alert(err.detail || "Upload thất bại");
    }
    const data = await resp.json();
    if (data.content_type === "text") {
      qc.skillContent = data.text;
      qc.skillFilename = data.filename;
      qcSetUploadDone(data.filename);
      $("#qc-content").value = "";
    } else {
      qcSetUploadIdle();
      alert("Ảnh không hỗ trợ trong wizard — dùng .pdf .docx .txt");
    }
  } catch (err) {
    qcSetUploadIdle();
    alert("Upload thất bại: " + err.message);
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
    '📎 Click để chọn file<br><span style="font-size:11px;color:var(--tx3)">.txt .md .pdf .docx — tối đa 5 MB</span>';
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

  const msg = `Tạo agent mới với thông tin đầy đủ sau, không cần hỏi thêm:

**Tên:** ${qc.name}
**Domain:** ${qc.domain}
**Mục đích:** ${qc.purpose}${skillSection}

Hãy thực hiện ngay: (1) kiểm tra trùng lặp, (2) tạo skill từ quy trình nếu có, (3) tạo agent, (4) gắn skill, (5) báo tôi kết quả.`;

  closeQuickCreate();
  btn.disabled = false;
  btn.textContent = "🚀 Tạo ngay";

  // Switch sang chat, route thẳng tới master
  saveCurrentConv();
  state.stickyAgent = "master";
  setCurrentAgent("master");
  if (!state.convStore.has("master")) {
    state.convStore.set("master", { key: "master", agentName: "master", agentMeta: null, lastText: "", updatedAt: Date.now() });
  } else {
    state.convStore.get("master").updatedAt = Date.now();
  }
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
    <button class="fb-btn" data-val="1" title="Câu trả lời tốt">👍</button>
    <button class="fb-btn" data-val="-1" title="Câu trả lời chưa ổn">👎</button>`;
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
    // Populate convStore từ server nếu chưa có (không ghi đè session hiện tại)
    for (const entry of data) {
      const key = entry.agent_name;
      if (!state.convStore.has(key)) {
        const agentData = _agentsCache.find((a) => a.name === key);
        state.convStore.set(key, {
          key,
          agentName: key,
          agentMeta: agentData ? { domain: agentData.domain } : null,
          lastText: entry.last_text || "…",
          updatedAt: entry.updated_at ? new Date(entry.updated_at).getTime() : Date.now(),
          container: null,  // không có DOM — click sẽ bắt đầu chat mới với history từ server
        });
      }
    }
    renderSidebar();
  } catch (_) {}
}

/* ─── Init ──────────────────────────────────────────────── */
refreshTabsForUser();
loadCatalog();
loadHomeAgents();
// Restore sidebar từ server sau khi agents cache đã load
refreshAgentsCache().then(() => restoreHistoryFromServer());
