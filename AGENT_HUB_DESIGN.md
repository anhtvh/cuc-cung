# Agent Hub — Meta-Agent System trên GreenNode AgentBase

> Tài liệu thiết kế cho cuộc thi **GreenNode Claw-a-thon 2026**.
> Deadline nộp bài: **17/06/2026 12:00** (giờ VN).

---

## 1. Context

### 1.1. Bài toán trong công ty

Mọi người trong công ty đang gặp khó khăn khi build và deploy agent: mỗi người
một cách làm, kiến thức nghiệp vụ nằm rải rác trong các prompt cá nhân, người
không rành kỹ thuật không tự tạo được agent cho nhu cầu của mình.

### 1.2. Ràng buộc từ cuộc thi

| Hạng mục | Yêu cầu |
|---|---|
| Nền tảng | Deploy trên **GreenNode AgentBase** (Docker → Container Registry → Custom Agent runtime) |
| Model | Gọi qua **GreenNode MaaS** — ví MaaS 5 triệu, giữ ≥2 triệu ví tổng cho runtime/registry |
| Nộp bài | GitHub public + video demo 2–3 phút + mô tả use case 100–200 chữ + endpoint public (optional, nên có) |
| Build flow | Build agent local → import bộ skill `greennode-agentbase-skills` vào **cùng folder** → `/agentbase-wizard` 9 bước. **Sau bước credential phải DỪNG**, build xong agent mới chạy tiếp (tránh deploy agent rỗng) |
| Memory | Dùng module **Memory của AgentBase**, không lưu `memory.md` local |

### 1.3. Fact kỹ thuật đã xác minh

- GreenNode MaaS expose **2 protocol cùng lúc**, chung 1 API key:
  - Anthropic Messages API: `https://maas-llm-aiplatform-hcm.api.vngcloud.vn`
  - OpenAI-compatible: `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1`
- AgentBase có các module: **Runtime** (deploy/scale/version), **Memory**
  (short-term history + long-term semantic), **MCP Gateway** (Resource Gateway
  quản lý MCP server + auth), **Identity** (inject credential lúc runtime,
  không hardcode), **Policy** (access control).
- Bộ skill của BTC là shell/python gọi REST API của AgentBase → đọc source bộ
  skill sẽ biết chính xác API provision agent/runtime.

---

## 2. Idea

**Một "agent sinh ra agent":** user chỉ cần nói chuyện — mô tả nhu cầu, cung
cấp flow, tài liệu — và **Master Agent** sẽ:

1. **Phỏng vấn** để hiểu nhu cầu;
2. **Chưng cất** thành một agent con: tên gọi + mô tả + persona prompt + bộ skill chuẩn hóa;
3. **Đăng ký** vào hệ thống — agent con dùng được **ngay lập tức, không cần deploy lại**;
4. Sau này, bất kỳ user nào **gọi tên** agent (`@ThamDinhHopDong`) hoặc chỉ cần
   **mô tả nhu cầu** ("tôi cần thẩm định hợp đồng") — hệ thống tự điều phối đến đúng agent.

### 2.1. Định nghĩa "agent" trong hệ thống này

Agent là khái niệm **hành vi**, không phải hạ tầng. Một agent con gồm:

| Thành phần | Là gì |
|---|---|
| Danh tính bền vững | Tên duy nhất, tồn tại qua nhiều phiên, nhiều user dùng chung |
| Chuyên môn riêng | Persona prompt + skills (quy trình chuẩn hóa) + connectors |
| Hành vi có mục tiêu | Nhận input → thực hiện job → output đúng format |
| Khả năng triệu gọi | Gọi đích danh hoặc được router điều phối theo ý định |

Phân biệt: *prompt một lần* (dùng xong vứt) vs *agent* (chuyên môn được đóng
gói + đặt tên + lưu lại + tái sử dụng toàn công ty). Mô hình "agent = config
được lưu, thực thi khi có session" giống hệt cách Anthropic Managed Agents
định nghĩa agent.

### 2.2. Quan hệ Master ↔ agent con

Master là **factory** (sinh ra agent con) và **dispatcher** (điều phối yêu cầu
đến agent con) — orchestrator pattern. Lúc chạy, user nói chuyện **trực tiếp**
với agent con; master không trung gian từng câu.

---

## 3. Kiến trúc

### 3.1. Tổng thể

```
User (web chat UI — SSE)
   │
   ▼
┌────────────────────────── Agent Hub (1 web app, deploy 1 lần) ──────────────────────────┐
│                                                                                          │
│  Router ──────────► Registry (SQLite)                                                    │
│   │  gọi tên → tra registry          ┌──────────────┐                                    │
│   │  mô tả ý định → classify         │ agents       │                                    │
│   ▼                                  │ skills       │                                    │
│  Master Agent (factory + dispatcher) │ agent_skills │                                    │
│   tools: list/create/update_agent,   │ connectors   │                                    │
│          create/attach_skill,        │ messages     │                                    │
│          submit_for_review           │ usage_log    │                                    │
│                                      └──────────────┘                                    │
│  Chat Engine: load agent (prompt + skills + connectors) → gọi MaaS → stream về UI        │
│   │                                                                                      │
│   ├── Skill Layer: inject nội dung skill vào system prompt                               │
│   └── Tool/MCP Layer: tool catalog hình dạng MCP (server.tool_name)                      │
│         ├── mock MCP servers (contract-db, company-docs)  ← demo                         │
│         └── AgentBase MCP Gateway                          ← stretch                     │
│                                                                                          │
│  Memory: AgentBase Memory module (interface chung, fallback SQLite)                      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
   │
   ▼
GreenNode MaaS (Anthropic Messages API / OpenAI-compatible, chung 1 key)
```

### 3.2. Agent con = 3 lớp năng lực

```
Agent con
├── 1. Persona prompt   (RIÊNG)  : vai trò, giọng điệu, format output, phạm vi
├── 2. Skills           (CHUNG)  : gói tri thức/quy trình CHUẨN HÓA, versioned,
│                                  review 1 lần — nhiều agent dùng chung
└── 3. Connectors (MCP) (CHỌN)   : tool từ catalog hình dạng MCP, agent khai báo
                                   cần connector nào thì engine mới truyền vào
```

**Tại sao tách skill khỏi prompt:** tính đúng đắn. Quy trình chuẩn (vd checklist
thẩm định hợp đồng 12 mục) được review một lần, mọi agent dùng chung một nguồn
sự thật; sửa skill → mọi agent gắn nó cập nhật theo. Tránh 5 user tạo 5 agent
thẩm định với 5 checklist lệch nhau.

**Không có skill private — chỉ có MỘT catalog chung.** Khác biệt nghiệp vụ thể
hiện bằng skill theo domain (vd `legal-task-style` ≠ `tech-task-style` — hai
skill khác nhau, cùng nằm trong catalog chung); thứ chỉ riêng MỘT agent (giọng
điệu, format đặc thù) thuộc về persona prompt. Quy tắc phân loại: *tái sử dụng
được cho agent khác → skill; chỉ riêng agent này → persona.* Skill `draft`
không submit = riêng tư de-facto (chỉ người tạo dùng được).

**Ranh giới an toàn:** master agent **chọn** skill/connector từ catalog và
**soạn** nội dung skill mới (markdown) — nhưng **không sinh code thực thi**.
Code tool/connector do dev viết sẵn trong catalog.

### 3.3. Contest chỉ có virtual agent — deployed là roadmap production

Agent con trong contest chạy **100% virtual**: row config trong registry, chạy
chung engine Hub, tạo tức thì. Đây là **lựa chọn thiết kế, không phải thiếu
sót**: virtual agent cho phép tạo không cần deploy, governance tập trung, và
skill sửa một chỗ — mọi agent cập nhật theo. Deploy runtime riêng sẽ đóng băng
skill vào artifact, phá vỡ chính lời hứa đó. (Câu trả lời chủ động nếu giám
khảo hỏi "sao không deploy agent con thành runtime riêng?".)

**Roadmap production (ghi README/video, KHÔNG code trong contest):**

| Plugin | Nội dung |
|---|---|
| #1 Builder (đã tách sẵn) | Master factory nằm trong module `app/builder/` + flag `BUILDER_ENABLED` (contest: bật). Production có thể tắt/giới hạn admin; agent định nghĩa declarative qua YAML, review bằng PR |
| #2 Private agent + credential riêng | User thử virtual agent (đã duyệt) → gửi request thăng cấp kèm key/account → admin approve → credential gắn qua **Identity module** — KHÔNG bao giờ lưu key trong DB. State machine mở thêm trạng thái `pending_promotion` |
| #3 Deployed agent (`deploy_agent`) | Provision runtime + endpoint riêng qua API AgentBase — chỉ khi có nhu cầu thật: tích hợp hệ thống ngoài (Slack, CI), cô lập tài nguyên/quyền. Phải giải bài toán sync skill (bake vào artifact vs call-back Hub) trước khi làm |

Schema §4 để sẵn hook (`visibility`, `identity_ref`) để bật plugin #2/#3
không cần migration đập bảng.

---

## 4. Data model (SQLite)

```sql
CREATE TABLE agents (
  name           TEXT PRIMARY KEY,     -- "ThamDinhHopDong"
  description    TEXT NOT NULL,        -- viết cho MODEL đọc — input của router
  system_prompt  TEXT NOT NULL,        -- persona
  connectors     TEXT DEFAULT '[]',    -- JSON: ["contract-db", "company-docs"]
  domain         TEXT,                 -- legal | hr | finance | ... (lọc catalog)
  status         TEXT DEFAULT 'draft', -- draft | pending_review | active | rejected
  pending_changes TEXT,                -- JSON: sửa đổi chờ duyệt khi item đang active (Flow 4)
  visibility     TEXT DEFAULT 'company', -- company | private (agent riêng: active nhưng chỉ chủ thấy/dùng)
  identity_ref   TEXT,                 -- hook roadmap #2: trỏ tới Identity module — KHÔNG lưu key trong DB
  -- endpoint_url: bỏ cùng deploy_agent (roadmap #3) — thêm lại bằng migration khi làm
  created_by     TEXT,
  reviewed_by    TEXT, review_note TEXT,
  created_at     TEXT, updated_at TEXT
);

CREATE TABLE skills (
  name        TEXT PRIMARY KEY,        -- convention: <domain>-<viec>, vd "legal-tham-dinh-hop-dong"
  description TEXT NOT NULL,
  content     TEXT NOT NULL,           -- markdown quy trình/checklist
  domain      TEXT,
  status      TEXT DEFAULT 'draft',    -- cùng vòng đời maker-checker như agents
  pending_changes TEXT,                -- JSON: sửa đổi chờ duyệt khi skill đang active (Flow 4)
  version     INTEGER DEFAULT 1,
  created_by  TEXT, reviewed_by TEXT,
  created_at  TEXT, updated_at TEXT
);

CREATE TABLE agent_skills (
  agent_name TEXT REFERENCES agents(name),
  skill_name TEXT REFERENCES skills(name),
  PRIMARY KEY (agent_name, skill_name)
);

CREATE TABLE messages (                -- fallback memory nếu Memory module trục trặc
  id INTEGER PRIMARY KEY,
  user_id TEXT, agent_name TEXT,
  role TEXT, content TEXT, created_at TEXT
);

CREATE TABLE usage_log (               -- theo dõi credit từ ngày 1
  id INTEGER PRIMARY KEY,
  agent_name TEXT, input_tokens INT, output_tokens INT, created_at TEXT
);
```

Master agent là 1 row đặc biệt (`name='master'`) — cùng pipeline chat, khác ở
chỗ được gắn bộ tools quản trị.

---

## 5. Các flow hoạt động

### Flow 1 — Routing (mỗi message vào)

```
POST /chat {user_id, message, agent_name?}
  ├─ agent_name có (UI chọn / sticky session)        → dùng luôn
  ├─ "@TenAgent ..." và tên tồn tại                  → match
  └─ Còn lại → 1 call MaaS classify (JSON output):
       input : danh sách (name, description) — CHỈ agent `active` visibility
               `company` (+ agent `draft`/`private` của chính user đang chat)
       output: {agent_name: string|null, confidence: high|medium|low}
       ├─ match, confidence đủ  → route tới agent đó
       └─ null / low            → route tới MASTER
```

- Sticky session: route 1 lần đầu hội thoại, các message sau giữ nguyên agent
  (chỉ đổi khi user gõ `@tên` khác hoặc bấm "đổi agent"). Cơ chế: client-side —
  UI giữ `agent_name` sau lần route đầu và gửi kèm mọi request; server stateless.
- JSON output: dùng `response_format: json_object` nếu model hỗ trợ, không thì
  prompt "chỉ trả JSON" + parse với 1 retry.

### Flow 2 — Master tạo agent con (tool loop)

```
User ↔ Master (system prompt phỏng vấn: mục đích, input/output, giọng điệu,
               tài liệu/quy trình đính kèm)
  └─ Vòng lặp tool-use:
     tools = [list_agents, get_agent_detail, create_agent, update_agent,
              list_skills, create_skill, attach_skill, submit_for_review]
     1. Gọi MaaS với tools
     2. stop_reason == tool_use → thực thi vào registry → tool_result
        (lỗi validate → is_error: true + message rõ ràng, master tự xử lý)
     3. Lặp đến end_turn
```

Quy tắc trong `master_system.md` (file quan trọng nhất dự án):
1. **Luôn `list_agents` + `list_skills` trước khi tạo** — trùng nhu cầu thì đề
   xuất dùng/update cái có sẵn; quy trình đã có skill chuẩn thì **gắn skill**
   thay vì viết lại vào prompt.
2. Tài liệu/quy trình user cung cấp → chưng cất thành **skill mới** (để tái sử
   dụng) thay vì chôn trong prompt của một agent.
3. Xác nhận toàn bộ config (tên + mô tả + skill gắn + connector) với user
   **trước khi** gọi `create_agent`.
4. Tự soạn `description` chuẩn cho router: 1–2 câu, nêu rõ "dùng khi nào".
5. Template persona prompt: vai trò → phạm vi → format output → điều không làm.

Validate phía app (không tin model): tên unique + đúng naming convention,
prompt ≥ 200 ký tự, không chứa pattern API key/secret, connector phải tồn tại
trong catalog, **dedup check** (xem Flow 2b). **Quyền sở hữu:** update/submit
chỉ owner (`created_by`) hoặc admin; list/get theo visibility (Flow 1).

### Flow 2b — Governance: maker-checker + chống skill rác

**Maker-checker (agent VÀ skill cùng vòng đời):**

```
draft ──submit──► pending_review ──approve──► active
  │                     └──reject (kèm lý do)──► rejected ──maker sửa──► draft
  │
  └─ draft: NGƯỜI TẠO dùng được NGAY (test trong phiên của mình)
            → giữ nguyên demo "tạo xong dùng liền"
     active: cả công ty thấy, router mới điều phối tới
```

- Maker = user tạo qua Master. Checker = admin (danh sách `user_id` admin
  trong config). Master có thêm tool `submit_for_review(name)`.
- **Ràng buộc approve:** agent chỉ lên `active` khi MỌI skill nó gắn đã
  `active` — trang Review hiện agent + skill pending cùng nhau, duyệt một lượt.
  Skill mới LUÔN vào catalog chung ở trạng thái `draft`, kể cả khi được tạo
  cho agent `private` (agent private không kéo skill thành private theo —
  dedup check vẫn áp dụng).
- Trang **Review** (admin) hiển thị **ĐẦY ĐỦ — không duyệt mù**:
  - **Agent**: tên, description (bản router đọc), TOÀN VĂN persona prompt,
    domain, visibility, người tạo, kết quả dedup (ứng viên tương tự nếu có);
  - **Skill gắn kèm**: tên, description, TOÀN VĂN content markdown, version,
    status, người tạo — skill pending hiện CÙNG agent, duyệt một lượt
    (ràng buộc approve ở trên);
  - **Connector (MCP)**: từng server + danh sách tool cụ thể agent sẽ được
    cấp quyền gọi, kèm nhãn mock/thật;
  - **Sửa đổi trên item active**: hiện diff bản đang chạy ↔ bản chờ duyệt
    (`pending_changes`);
  - Approve / Reject — reject bắt buộc nhập lý do.
- Reject KHÔNG phải trạng thái cuối: maker sửa theo lý do → quay về `draft`
  → submit lại.
- Skill còn cần duyệt hơn agent: skill là nguồn sự thật dùng chung — sai một
  skill là sai hàng loạt agent.

**Chống skill rác/trùng lặp — chặn 3 tầng:**

| Tầng | Cơ chế |
|---|---|
| Master (mềm) | Rule prompt: `list_skills` trước; trình skill tương tự cho user trước khi tạo mới |
| **App (cứng + mềm)** | Handler `create_skill`/`create_agent` tự chạy **dedup check**: trùng tên chính xác → hard-block (`is_error`); LLM classify thấy chồng lấn description → **soft-warning** kèm ứng viên trả về tool_result → master trình user quyết định gắn/update cái cũ hay vẫn tạo mới. Không hard-block theo LLM — tránh false positive chặn flow lúc demo live |
| User (nhìn thấy) | Trang **Catalog** trên UI: agent + skill kèm mô tả, search/lọc theo `domain`; hỏi master "có skill gì về X?" → trả lời qua `list_skills` |

Naming convention: skill đặt tên `<domain>-<viec>` (vd `legal-tham-dinh-hop-dong`)
— app validate bằng regex, master được dạy trong system prompt.

### Flow 3 — Chat với agent con

```
1. registry.get(agent_name)
2. Build system prompt = persona
     + nội dung các skill đã gắn (mục "QUY TRÌNH CHUẨN — tuân thủ nghiêm ngặt")
     + (optional) semantic memories liên quan
3. memory.get_history(user_id, agent_name, limit=20)
4. Tools = connector của agent (map từ catalog) — không có thì gọi chay
5. Gọi MaaS (stream) → SSE về UI; tool_use → thực thi connector → loop
   (an toàn: tối đa 5 vòng tool/lượt, timeout mỗi tool, lỗi tool → is_error
   cho model tự xử lý 1 lần rồi dừng lượt)
6. memory.append(...) + ghi usage_log
```

### Flow 4 — Skill lifecycle

```
Tạo   : master chưng cất tài liệu user → create_skill (markdown) → review được
Gắn   : attach_skill(agent, skill) — n:n
Dùng  : inject content vào system prompt lúc chat (MVP)
        / progressive disclosure qua tool load_skill (stretch — tiết kiệm token)
Sửa   : draft → sửa trực tiếp, không cần duyệt lại
        active → nội dung mới ghi vào `pending_changes`, bản active VẪN
        phục vụ bình thường; admin duyệt (Review hiện diff cũ ↔ mới) →
        áp dụng + version+1 → MỌI agent gắn nó nhận bản mới (đã qua duyệt).
        KHÔNG có đường sửa item active lan thẳng ra mà không duyệt lại.
```

### Flow 5 — Tool/MCP layer

```
Catalog (dev viết sẵn, hình dạng MCP — tên dạng server.tool_name):
  contract-db.search_contracts     ← mock: trả hợp đồng mẫu
  contract-db.get_contract         ← mock
  company-docs.search_policy       ← mock: tra quy định công ty
  system.get_current_date          ← thật

Agent con khai báo connectors=["contract-db"] → engine chỉ truyền các tool
thuộc server đó vào model. Mock server = module Python trong Hub, cùng
interface với MCP client thật → cắm server thật qua AgentBase MCP Gateway
không phải sửa flow (stretch).
```

> Minh bạch: trong video + README ghi rõ connector nào là mock, kiến trúc sẵn
> sàng cắm MCP server thật qua Gateway. Không giấu.

### Flow 6 — Memory

- Short-term: lịch sử per `(user_id, agent_name)` — AgentBase Memory module.
- Long-term: semantic search (master nhớ user từng tạo gì, sở thích gì).
- `memory.py` viết theo interface chung (`get_history/append/search`):
  implement SQLite trước (ngày 1–2), swap sang Memory module ngày 3.
  Module khó hơn dự kiến → ship bản SQLite, không chặn deadline.

### Flow 7 — Deploy Hub lên AgentBase (1 lần)

```
1. /agentbase-wizard bước 1: GREENNODE_CLIENT_ID/SECRET → DỪNG
2. Build app xong → wizard tiếp: Docker build (python:3.12-slim, uvicorn,
   EXPOSE 8000) → push Container Registry → Custom Agent runtime PUBLIC
3. Inject MAAS_API_KEY qua Identity module (không bake vào image)
4. Verify endpoint từ mạng khác (bẫy "localhost" — guide §5.2)
```

---

## 6. Tech stack

| Layer | Lựa chọn | Lý do |
|---|---|---|
| Backend | Python 3.12 + FastAPI | Sample BTC dùng FastAPI; Memory module có ví dụ LangChain; vibe-code nhanh nhất |
| LLM client | SDK `anthropic` với base_url → MaaS (hoặc `openai` → `/v1`) | Đổi 2 dòng config; Messages API có tool-use schema rõ |
| Registry | SQLite (volume mount) | 1 file, đủ cho demo |
| Memory | AgentBase Memory module, fallback SQLite | Yêu cầu ngầm của BTC |
| Frontend | HTML + vanilla JS + SSE: trang Chat, trang **Catalog** (agent/skill, search theo domain), trang **Review** (admin duyệt). User identity demo: user switcher đơn giản (header `X-User-Id`, lưu localStorage) — seed 3 persona: 2 user thường + 1 admin, khớp kịch bản video §10 | Không framework |
| Tool layer | Catalog hình dạng MCP + mock servers | §5 Flow 5 |
| Deploy | Dockerfile + `greennode-agentbase-skills` | Chuẩn cuộc thi |
| Secrets | AgentBase Identity module | Không hardcode key |

### Wrapper LLM chống rủi ro model (`llm.py`)

```python
class LLMClient:
    def chat(self, system, messages, stream=True) -> Iterator[str]: ...
    def chat_with_tools(self, system, messages, tools) -> ToolLoopResult: ...
    def classify_json(self, system, message, schema) -> dict: ...
```

- **Plan A:** native tool-use qua Anthropic Messages endpoint.
- **Plan B** (model pool tool-calling yếu, vd gemma): `chat_with_tools` chuyển
  sang prompt-based JSON `{action, args}` + parse. Flow không đổi một dòng.
- Việc đầu tiên ngày 1: list models + test 1 tool call → chốt A hay B.

### Cấu trúc project (production-ready)

Nguyên tắc: **core nghiệp vụ không import FastAPI / SQLAlchemy / SDK LLM** —
mọi thứ bên ngoài (DB, LLM, memory, tool, auth) đi qua interface (Protocol),
implementation được wire ở composition root (`main.py`). Sau cuộc thi, đổi hạ
tầng = thêm 1 file implementation + đổi config, **không sửa core**.

```
cuccung/
├── app/
│   ├── main.py                  # app factory + composition root (wire mọi impl theo config)
│   ├── config.py                # pydantic-settings — toàn bộ config từ env, không hardcode
│   ├── api/                     # HTTP layer — route mỏng, KHÔNG chứa logic
│   │   ├── deps.py              # DI: current_user, services
│   │   ├── chat.py              # POST /chat (SSE)
│   │   ├── agents.py            # CRUD agents (Catalog)
│   │   ├── skills.py
│   │   └── review.py            # admin: approve/reject
│   ├── core/                    # domain thuần — không import framework/SDK
│   │   ├── models.py            # Pydantic: Agent, Skill, AgentStatus... (không dùng dict thô)
│   │   ├── router.py            # Flow 1: routing theo tên / ý định
│   │   ├── chat_engine.py       # Flow 3: build prompt + stream + tool loop
│   │   ├── governance.py        # Flow 2b: state machine maker-checker, validate, dedup
│   │   └── prompts/
│   │       └── router_system.md
│   ├── builder/                 # PLUGIN #1 (roadmap §3.3) — Flow 2: master factory
│   │   ├── master.py            #   tool loop + handlers; flag BUILDER_ENABLED (contest: bật)
│   │   └── master_system.md
│   ├── llm/
│   │   ├── base.py              # LLMClient protocol: chat / chat_with_tools / classify_json
│   │   ├── anthropic_client.py  # Plan A — MaaS Anthropic Messages
│   │   └── openai_client.py     # Plan B — hoặc provider khác sau này
│   ├── storage/
│   │   ├── base.py              # AgentRepo / SkillRepo / UsageRepo protocols
│   │   └── sql.py               # SQLAlchemy 2.0 — SQLite contest, Postgres = đổi DSN
│   ├── memory/
│   │   ├── base.py              # get_history / append / search
│   │   ├── sql_memory.py        # fallback
│   │   └── agentbase_memory.py  # Memory module
│   ├── tools/
│   │   ├── base.py              # ToolProvider protocol — hình dạng MCP (server.tool_name)
│   │   ├── catalog.py           # registry tool → provider
│   │   ├── mock/                # contract_db.py, company_docs.py
│   │   └── mcp_gateway.py       # AgentBase Gateway — stretch contest, chính thức production
│   └── auth/
│       └── middleware.py        # contest: user_id từ header; production: swap OIDC/SSO
├── web/                         # static UI — CHỈ gọi REST API → thay frontend không đụng backend
├── migrations/                  # alembic từ ngày 1 — schema evolve không đập DB
├── seeds/demo_data.py           # tái tạo agent/skill mẫu nếu DB rỗng (chống mất SQLite — rủi ro #6)
├── tests/                       # state machine governance, router, validate, dedup
├── Dockerfile
├── docker-compose.yml           # dev local
├── pyproject.toml
└── greennode-agentbase-skills/  # clone vào CÙNG folder (yêu cầu BTC)
```

**Đường mở rộng sau cuộc thi** (lý do của từng quyết định trên):

| Muốn | Đổi gì | Nhờ đâu |
|---|---|---|
| Postgres thay SQLite | đổi DSN trong env | SQLAlchemy + alembic từ đầu |
| SSO/OIDC công ty | swap `auth/middleware.py` | user_id đã đi qua 1 chỗ duy nhất |
| Multi-tenant | bật cột `org_id` (thêm sẵn, nullable, contest không dùng) | schema §4 + alembic |
| Private agent + credential riêng (roadmap #2) | dùng `visibility`/`identity_ref` + Identity module | hook schema §4 có sẵn |
| Provider LLM khác / multi-model | thêm file trong `llm/` | LLMClient protocol |
| MCP server thật | thêm provider qua Gateway | ToolProvider chung interface với mock |
| Frontend React/mobile | thay `web/` | API-first, route không chứa logic |
| Observability | structured logging JSON có sẵn từ ngày 1 → đổ vào stack nào cũng được | |

**Không làm trước (kể cả code rẻ):** RBAC chi tiết hơn admin-list, queue/worker,
rate limiting, multi-region — chưa có user thật thì chưa có dữ liệu để thiết kế đúng.

---

## 7. Kế hoạch theo ngày (12/06 → 17/06) — Claude vibe-code

**Giả định nền tảng:** code do Claude viết → khối lượng code không còn là
bottleneck (nén ~3–4×). Bottleneck thật chuyển sang 3 thứ **không nén được**:
(a) ẩn số bên ngoài — hành vi MaaS, API AgentBase, deploy; (b) thời gian
**người** test thật + quay video; (c) credit. Hệ quả chiến lược: các stretch
goal chứng minh "dùng platform đúng nghĩa" (Memory module, MCP Gateway) trở nên
**rẻ → nâng lên chính thức** — cùng Runtime (host Hub) và Identity (inject key)
là đủ 4 module AgentBase, trả lời câu hỏi giám khảo "platform đem lại gì?".

| Ngày | Việc | Bottleneck thật | Output cuối ngày |
|---|---|---|---|
| **12/06 sáng** | **Go/no-go checks (§8)** — cần credential + thao tác của anh, không phải code: list models + test tool-call (chốt Plan A/B); tra spec Memory module; thử MCP Gateway | Credential, portal | 3 check có kết quả |
| **12/06 chiều–tối** | Claude dựng **toàn bộ skeleton production (§6)** + `llm/` + `storage/` + `core/master.py` tool loop + `core/router.py` + chat engine + SSE + UI chat v1 — chạy được local | Kết quả check sáng | Tạo agent bằng hội thoại được trên máy local |
| **13/06 sáng** | Claude hoàn thiện: governance (state machine + trang Review + Catalog), dedup (soft-warning), tool catalog + 2 mock MCP, seeds, tests | — | Full flow end-to-end local |
| **13/06 chiều** | **Deploy bản thật luôn** (không chỉ hello-world — code đã đủ): wizard 9 bước → runtime PUBLIC → verify từ mạng khác, verify volume mount SQLite | Wizard, platform, mạng | Endpoint public chạy bản đầy đủ — **sớm 2 ngày so plan cũ** |
| **14/06** | Tích hợp **Memory module** (swap từ fallback) + MCP Gateway 1 server thật (nếu check #3 pass) + agent `private` (visibility); redeploy | API AgentBase | Câu chuyện "platform-native" hoàn chỉnh |
| **15/06** | **Anh test end-to-end như người dùng thật** theo đúng kịch bản video (§10), Claude fix theo feedback; seed agent mẫu cho demo; chạy thử kịch bản 2 lần | Thời gian người | Demo chạy mượt, không bất ngờ |
| **16/06** | Video 2–3 phút; use case 100–200 chữ; README; repo + video public; **NỘP** | Người quay/dựng | Đã submit, còn 1 ngày dư |
| **17/06 sáng** | Buffer fix theo review | — | — |

**Cắt bỏ khỏi scope:** vaults phức tạp, versioning/rollback agent, Slack bot,
multi-tenant (chỉ để sẵn cột `org_id`), master tự sinh code tool, RBAC,
`deploy_agent` + credential riêng cho user (→ roadmap §3.3, hook schema để sẵn).

**Rủi ro mới khi vibe-code & xử lý:** code sinh nhanh → anh chưa đọc kỹ → khó
debug lúc demo live. Xử lý: (a) tests cho phần dễ vỡ (state machine, router,
validate) chạy trong CI/local trước mỗi deploy; (b) cuối **mỗi** ngày anh tự
chạy kịch bản demo 5 phút — phát hiện lệch sớm, không dồn về 15/06; (c) mọi
config qua env để fix production không cần rebuild image.

---

## 8. Go/No-Go checks (làm sáng 12/06, mỗi cái ≤ 1 giờ)

| # | Check | Nếu PASS | Nếu FAIL |
|---|---|---|---|
| 1 | Model pool MaaS có model tool-calling tốt? (test 1 call) | Plan A (native tools) | Plan B (JSON prompt-based) |
| 2 | Memory module REST API tiếp cận được? | Tích hợp 14/06 | Ship fallback SQLite, ghi rõ README |
| 3 | MCP Gateway connect được server thật? | 1 server thật qua Gateway (14/06) | Mock-only, ghi rõ minh bạch |

(Check provision API agent/runtime đã bỏ cùng `deploy_agent` — xem roadmap §3.3.)

**Kết quả (chạy 12/06): CẢ 3 PASS — chốt Plan A.**

1. **PASS cả 2 protocol** — test `minimax/minimax-m2.5` trả `tool_calls` (OpenAI)
   và `tool_use` (Anthropic) chuẩn. **Lưu ý quan trọng:** endpoint Anthropic
   auth bằng `Authorization: Bearer`, KHÔNG phải `x-api-key` → SDK `anthropic`
   phải dùng `auth_token=` thay vì `api_key=`. Model pool mạnh: `openai/gpt-5`,
   `gemini/gemini-2.5-pro`, `deepseek/deepseek-v4-pro`, `qwen/qwen3.7-plus`,
   `minimax/minimax-m2.5`; model rẻ cho router/classify: `openai/gpt-4o-mini`,
   `gemini/gemini-2.5-flash-lite`, `deepseek/deepseek-v4-flash`; có embedding
   (`baai/bge-m3`, `qwen/qwen3-embedding-8b`) nếu cần semantic search.
2. **PASS** — `GET /memory/memories` HTTP 200 qua IAM token (list rỗng, đúng vì
   chưa tạo store) → tích hợp Memory module ngày 14/06 như kế hoạch.
3. **PASS** — `GET /gateway/api/v1/gateways` HTTP 200 → stretch 1 MCP server
   thật qua Gateway khả thi.

Hạ tầng phụ trợ đã sẵn: IAM token lấy qua `get_token.sh` của bộ skill BTC
(cache ở `.agentbase/`), `jq` đã cài, credential trong `.env` (gitignored).

---

## 9. Rủi ro & xử lý

| # | Rủi ro | Xử lý |
|---|---|---|
| 1 | Model MaaS tool-calling yếu | Wrapper Plan A/B — flow không đổi |
| 2 | Deploy lần đầu trễ → kẹt deadline | Deploy hello-world ngay 13/06, không đợi 15/06 |
| 3 | Credit cạn | `usage_log` từ commit đầu; router/classify dùng model nhỏ nhất pool |
| 4 | Memory module spec không rõ | Interface + fallback SQLite |
| 5 | Re-route giữa hội thoại gây nhảy agent | Sticky session |
| 6 | SQLite mất khi container restart | Mount volume qua Runtime; không được thì chấp nhận cho demo, ghi README |
| 7 | Master tạo agent/skill kém chất lượng | Maker-checker (Flow 2b): draft → admin duyệt mới `active`; validate phía app; tinh chỉnh `master_system.md` theo các agent đầu tiên |
| 8 | Skill rác / trùng lặp tích tụ theo thời gian | Dedup check cứng ở handler + Catalog cho user nhìn thấy + naming convention `<domain>-<viec>` |

---

## 10. Kịch bản video demo (2–3 phút)

1. **Cảnh 1 — Tạo agent bằng hội thoại** (user mô tả nhu cầu thẩm định hợp
   đồng + đưa checklist chuẩn → Master phỏng vấn → chưng cất thành skill
   `legal-tham-dinh-hop-dong` + agent `ThamDinhHopDong` → xác nhận → tạo,
   trạng thái `draft` → maker **test ngay** với một hợp đồng mẫu).
   Câu chốt: *"tạo agent mới không cần deploy lại — chỉ là một câu chat."*
2. **Cảnh 2 — Maker-checker (governance)**: maker ưng kết quả → "submit để
   duyệt" → chuyển màn hình admin: trang Review hiện agent + skill pending,
   admin xem config → **Approve** → badge `active`, cả công ty thấy trong
   Catalog. Câu chốt: *"agent chỉ lan ra toàn công ty sau khi được duyệt —
   đúng đắn và có kiểm soát."* (5–10 giây)
3. **Cảnh 3 — Gọi đích danh**: user khác gõ `@ThamDinhHopDong` + paste hợp
   đồng → agent thẩm định theo đúng checklist chuẩn (skill đảm bảo đúng đắn),
   connector `contract-db` lấy hợp đồng mẫu để đối chiếu.
4. **Cảnh 4 — Routing theo ý định**: user thứ ba gõ "tôi cần thẩm định hợp
   đồng với đối tác mới" → hệ thống tự kết nối đúng agent.
5. **Cảnh 5 — Fallback**: nhu cầu chưa có agent → Master đề nghị tạo mới.
6. **Câu kết (1 câu, overlay roadmap)**: *"bước tiếp theo: private agent với
   credential riêng qua Identity module, và thăng cấp runtime riêng khi cần
   tích hợp hệ thống ngoài."* — thay cảnh deploy_agent cũ (đã cắt, roadmap §3.3).

## 11. Use case description (draft ~150 chữ, cho form nộp bài)

> Agent Hub là "agent sinh ra agent" cho doanh nghiệp: nhân viên không cần biết
> kỹ thuật, chỉ cần chat với Master Agent — mô tả nhu cầu, cung cấp quy trình,
> tài liệu — và một agent chuyên môn mới được tạo ra ngay lập tức, không cần
> deploy lại. Tri thức nghiệp vụ được chưng cất thành các **skill chuẩn hóa**
> dùng chung (review một lần, mọi agent cùng tuân thủ), đảm bảo tính đúng đắn
> và nhất quán. Agent con được đặt tên, lưu trữ tập trung; bất kỳ ai trong
> công ty gọi tên hoặc chỉ cần mô tả nhu cầu là hệ thống tự điều phối đến đúng
> agent. Cơ chế maker-checker đảm bảo agent/skill chỉ phổ biến toàn công ty
> sau khi được duyệt. Agent con có thể kết nối dữ liệu qua connector chuẩn
> MCP. Xây trên GreenNode AgentBase: runtime, memory tập trung, access control.
