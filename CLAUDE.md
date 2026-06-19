# Agent Hub — Project Context (đọc file này thay vì khám phá project)

## 1. Dự án là gì

**Agent Hub** — "agent sinh ra agent" cho doanh nghiệp. User chat với Master Agent, mô tả nhu cầu → Master tạo agent con + skill chuẩn hóa, lưu vào registry. Mọi user gọi tên agent hoặc mô tả ý định → hệ thống tự routing đến đúng agent.

Cuộc thi **GreenNode Claw-a-thon 2026**, deadline nộp **17/06/2026 12:00**.
Deploy trên **GreenNode AgentBase** (Docker → Container Registry → Custom Agent runtime).

---

## 2. Quyết định kỹ thuật đã chốt (KHÔNG hỏi lại)

| Quyết định | Chi tiết |
|---|---|
| **Plan A** | SDK `anthropic` + base_url MaaS Anthropic endpoint |
| **Auth MaaS** | `auth_token=` (Bearer), KHÔNG phải `api_key=` |
| **Model chính** | `minimax/minimax-m2.5` (env `MODEL`) |
| **Router/classify** | `qwen/qwen3-5-27b` (env `ROUTER_MODEL`) qua **OpenAI-compat endpoint** — endpoint Anthropic 404 với nhiều model |
| **Endpoint Anthropic** | Chỉ phục vụ một số model (`minimax/minimax-m2.5`, `qwen/qwen3-5-27b`, `google/gemma-4-31b-it`); `gpt-4o-mini` và `gemini-flash-lite` 404 qua Anthropic endpoint |
| **2 endpoints MaaS** | Anthropic: `https://maas-llm-aiplatform-hcm.api.vngcloud.vn` — OpenAI: thêm `/v1`. Chung 1 key |
| **Tool name wire** | Dấu chấm bị cấm → `server__tool` (2 gạch dưới); UI/Review vẫn hiển thị `server.tool` |
| **Agent con = virtual** | Row config trong registry, chạy chung engine Hub, tạo tức thì, không deploy runtime riêng |
| **Env trống** | `.env` có `MODEL=` (trống) đè mất default → đã fix validator fallback trong `app/config.py` |
| **Memory backend** | `MEMORY_BACKEND=agentbase`, store `memory-82c99d4a-6de7-450a-bfaf-251324f188a4` (30 ngày) |
| **MCP Gateway** | `agent-hub-gw` ACTIVE, endpoint `https://gw-agent-hub-gw-111745.agentbase-gateway.aiplatform.vngcloud.vn`, target `websearch` → `/mcp` của app. Bật bằng `MCP_GATEWAY_ENDPOINT=<gateway_url>` sau deploy. |
| **Gateway call path** | `POST {gateway_endpoint}/{target_name}` — gateway route theo target prefix |

---

## 3. Tiến độ hiện tại (13/06/2026 chiều)

| Mốc | Trạng thái |
|---|---|
| Go/no-go checks (cả 3) | ✅ PASS — chốt Plan A |
| Skeleton + toàn bộ code core | ✅ 52/52 test pass |
| Smoke test MaaS thật | ✅ master chat + tool loop + stream SSE OK |
| Router classify thật | ✅ VERIFIED — "thẩm định hợp đồng" → `ThamDinhHopDong/high` |
| Multi-agent orchestration | ✅ run_agent, sub-agent card UI, router detect ≥2 mentions |
| Memory AgentBase cloud | ✅ store tạo, MEMORY_BACKEND=agentbase, lịch sử lưu cloud |
| MCP Gateway thật | ✅ gateway `agent-hub-gw` ACTIVE; PATCH target sau deploy |
| Governance UI end-to-end | ⬜ |
| Deploy AgentBase PUBLIC | ⬜ (tiếp theo) → sau deploy: PATCH gateway target + set MCP_GATEWAY_ENDPOINT |
| Test end-to-end video | ⬜ 15/06 |
| Video + README + nộp | ⬜ 16/06 |

---

## 4. File map (files quan trọng)

```
app/
  main.py                — composition root: wire mọi impl theo env, alembic upgrade, seed
  config.py              — pydantic-settings; validator fallback cho env trống
  core/
    models.py            — Pydantic: Agent, Skill, ItemStatus, Visibility, RouteDecision
    router.py            — Flow 1: explicit / @mention / classify → agent
    chat_engine.py       — Flow 3: persona + skills + history + tool loop (max 10 vòng; builder 20). Cắt thực tế thường là SLA 55s, không phải số vòng.
    governance.py        — Flow 2b: state machine draft→pending→active/rejected, validate, dedup
    prompts/router_system.md
  builder/
    master.py            — 8 tools quản trị agent/skill; flag BUILDER_ENABLED
    master_system.md     — FILE QUAN TRỌNG NHẤT: quy tắc phỏng vấn, chưng cất skill
  llm/
    anthropic_client.py  — Plan A (stream + tool loop + retry JSON)
    openai_client.py     — Plan B / router classify
  storage/sql.py         — SQLAlchemy 2.0; 5 bảng (agents, skills, agent_skills, messages, usage_log)
  memory/
    sql_memory.py        — fallback SQLite
    agentbase_memory.py  — IAM auth + get_history/append/search; MEMORY_BACKEND=agentbase để bật
  tools/
    catalog.py           — registry tool → provider
    mock/contract_db.py, company_docs.py — mock MCP server demo
    mcp_gateway.py       — IamTokenProvider + McpGatewayProvider; gateway agent-hub-gw ACTIVE trên AgentBase
  api/
    chat.py              — POST /chat SSE
    review.py            — admin approve/reject
  auth/middleware.py     — X-User-Id header; production swap OIDC/SSO
seeds/demo_data.py       — master row + ThamDinhHopDong khi DB rỗng
web/                     — Chat SSE + user switcher (An/Bình/Admin) + Catalog + Review
migrations/              — alembic 0001_initial, tự upgrade khi khởi động
```

---

## 5. Flows tóm tắt

- **Flow 1 (routing)**: agent_name có → dùng; @mention → match; còn lại → classify JSON (model rẻ, OpenAI endpoint) → master nếu null/low.
- **Flow 2 (master tạo agent)**: tool loop: `list_agents/skills` → phỏng vấn → `create_skill` → `create_agent` → `attach_skill` → `submit_for_review`. Validate phía app (unique name, prompt ≥200 ký tự, no secret pattern, dedup).
- **Flow 2b (governance)**: `draft → pending_review → active/rejected`. Draft = maker dùng ngay. Active = cả công ty thấy. Approve agent → phải tất cả skill active.
- **Flow 3 (chat)**: load agent config → system prompt = persona + skills + memories → history 20 tin → MaaS stream → tool loop → ghi memory + usage_log.
- **Flow 4 (skill lifecycle)**: skill active sửa → ghi `pending_changes` (bản active vẫn chạy) → admin duyệt → version+1, tất cả agent gắn nó cập nhật.

---

## 6. Data model ngắn

```
agents   : name(PK), description, system_prompt, connectors(JSON), domain, status, pending_changes, visibility, created_by
skills   : name(PK), description, content(markdown), domain, status, pending_changes, version, created_by
agent_skills : agent_name, skill_name (n:n)
messages : user_id, agent_name, role, content (fallback memory)
usage_log: agent_name, input_tokens, output_tokens
```

Master = row đặc biệt `name='master'` — seed từ `master_system.md` mỗi lần khởi động.

---

## 7. Chạy local

```bash
# Dev
uvicorn app.main:app --reload --port 8000
# Hoặc
docker-compose up

# Test
pytest  # phải 27+ pass trước khi deploy
```

Python 3.14 local (target code 3.12+), Docker `python:3.12-slim`.

---

## 8. Gotchas không được quên

1. Endpoint Anthropic của MaaS **không** phục vụ `gpt-4o-mini` / `gemini-flash-lite` — 404. Router LUÔN đi OpenAI endpoint.
2. SDK `anthropic` với MaaS: `auth_token=` không phải `api_key=`.
3. Biến `.env` trống (vd `MODEL=`) đè mất default — đã có fallback, đừng xóa.
4. Tool name trên wire: `server__tool` (2 gạch), UI hiển thị `server.tool`.
5. `/agentbase-wizard` đã DỪNG sau bước credential — chỉ chạy tiếp khi code đã đủ (tránh deploy agent rỗng).
6. `master_system.md` là nguồn sự thật của master prompt — seed tự sync vào DB khi khởi động, không sửa DB thủ công.
7. **MCP Gateway route**: gọi `POST {gateway_endpoint}/{target_name}` (không phải root). `McpGatewayProvider._rpc_url()` đã xử lý tự động. Gateway hiện `agent-hub-gw`, target `websearch`. Sau deploy: PATCH target endpoint về `{deployed_app_url}/mcp` rồi set `MCP_GATEWAY_ENDPOINT`.
8. **Sau deploy**: chạy 2 lệnh: (1) PATCH gateway target URL, (2) set `MCP_GATEWAY_ENDPOINT=https://gw-agent-hub-gw-111745.agentbase-gateway.aiplatform.vngcloud.vn` trong env container → app tự dùng gateway thay DuckDuckGo local.