# Agent Hub — Implementation Status

> Tracking thực thi theo `AGENT_HUB_DESIGN.md` §6 (cấu trúc) + §7 (timeline).
> Cập nhật lần cuối: **12/06/2026 chiều**.

---

## 1. Trạng thái tổng quan theo timeline §7

| Mốc | Việc | Trạng thái |
|---|---|---|
| 12/06 sáng | Go/no-go checks §8 | ✅ XONG — cả 3 PASS, chốt **Plan A** (native tool-use) |
| **12/06 chiều–tối** | **Skeleton production + llm/ + storage/ + core/ + builder/ + chat SSE + UI v1** | ✅ **~95% — code xong, 27/27 test pass, master chat chạy thật với MaaS; còn 1 fix routing CHƯA verify (mục 4)** |
| 13/06 sáng | Hoàn thiện governance UI flow end-to-end, tinh chỉnh theo test thật | ⬜ |
| 13/06 chiều | Deploy bản thật qua wizard → runtime PUBLIC | ⬜ |
| 14/06 | Memory module + MCP Gateway 1 server thật + redeploy | ⬜ |
| 15/06 | Test end-to-end như user thật theo kịch bản video §10 | ⬜ |
| 16/06 | Video + use case + README + **NỘP** | ⬜ |
| 17/06 sáng | Buffer | ⬜ |

Quyết định kỹ thuật đã chốt (từ check §8, áp vào code):
- **Plan A**: SDK `anthropic` + base_url MaaS, **auth bằng `auth_token=`** (Bearer), KHÔNG phải `api_key=`.
- Model chính: `minimax/minimax-m2.5` (env `MODEL`); router/classify/dedup dùng model rẻ (env `ROUTER_MODEL`, mặc định `openai/gpt-4o-mini`) — chống cạn credit (rủi ro #3).
- Tên tool trên wire: API chỉ cho `[a-zA-Z0-9_-]` → `server.tool` mã hoá thành `server__tool`, hiển thị dạng chấm ở UI/Review.

---

## 2. Đã làm xong (12/06 chiều) — file đã viết

### Nền móng
| File | Nội dung |
|---|---|
| `pyproject.toml` | FastAPI, SQLAlchemy 2, alembic, anthropic, openai, pytest. Python ≥3.12 |
| `app/config.py` | pydantic-settings, toàn bộ config từ env (đổi config không rebuild image) |
| `app/core/models.py` | Pydantic: `Agent`, `Skill`, `ItemStatus`, `Visibility`, `RouteDecision` — đủ hook `visibility`/`identity_ref`/`org_id` (§4) |

### Storage + Memory
| File | Nội dung |
|---|---|
| `app/storage/base.py` | Protocols `AgentRepo`/`SkillRepo`/`UsageRepo` — core không import SQLAlchemy |
| `app/storage/sql.py` | SQLAlchemy 2.0, đủ 5 bảng §4. Postgres = đổi DSN |
| `app/memory/base.py` + `sql_memory.py` | Interface `get_history/append/search` + fallback SQLite (Flow 6) |
| `app/memory/agentbase_memory.py` | Skeleton Memory module — implement 14/06 |
| `migrations/` + `alembic.ini` | Alembic từ ngày 1, migration `0001_initial`, tự upgrade lúc khởi động |

### LLM layer (Plan A/B)
| File | Nội dung |
|---|---|
| `app/llm/base.py` | Protocol `chat / chat_with_tools / classify_json`, event stream (TextDelta/ToolCallEvent/Done), `parse_json_loose` |
| `app/llm/anthropic_client.py` | **Plan A** — tool loop native, stream, retry JSON 1 lần, `auth_token=` |
| `app/llm/openai_client.py` | **Plan B** / provider khác — cùng protocol, swap bằng env `LLM_PROVIDER` |

### Core flows
| File | Flow trong design |
|---|---|
| `app/core/router.py` + `prompts/router_system.md` | **Flow 1**: explicit → @mention → classify (model rẻ, JSON) → fallback master. Classify lỗi → về master, không chặn chat |
| `app/core/chat_engine.py` | **Flow 3**: persona + inject skill ("QUY TRÌNH CHUẨN") + history (limit 20) + tools theo connector; max 5 vòng tool, timeout/tool, ghi memory + usage_log kể cả khi stream đứt |
| `app/core/governance.py` | **Flow 2b + 4**: state machine draft→pending_review→active/rejected; approve agent đòi MỌI skill active; reject bắt buộc lý do; sửa item active → `pending_changes` (version+1 khi duyệt skill); validate tên/độ dài prompt/secret pattern/connector; dedup cứng (tên) + mềm (LLM, không hard-block) |

### Builder (plugin #1) + Tools
| File | Nội dung |
|---|---|
| `app/builder/master.py` | **Flow 2**: 8 tools (`list/create/update_agent`, `list/create_skill`, `attach_skill`, `get_agent_detail`, `submit_for_review`) + handlers validate qua Governance, lỗi → `is_error` cho master tự xử. Flag `BUILDER_ENABLED` |
| `app/builder/master_system.md` | File quan trọng nhất: quy tắc phỏng vấn, list trước khi tạo, chưng cất skill, xác nhận trước create, naming, template persona |
| `app/tools/base.py` + `catalog.py` | ToolProvider protocol hình dạng MCP + catalog, nhãn mock/thật, thực thi có timeout |
| `app/tools/mock/contract_db.py`, `company_docs.py` | 2 mock MCP server demo (Flow 5) |
| `app/tools/mcp_gateway.py` | Skeleton Gateway — implement 14/06 |

### API + Auth + UI
| File | Nội dung |
|---|---|
| `app/api/chat.py` | POST /chat SSE: meta (routed agent → sticky) / delta / tool / done / error |
| `app/api/agents.py`, `skills.py` | Catalog đọc theo visibility |
| `app/api/review.py` | Trang Review admin: toàn văn persona + skill content + connector từng tool + diff `pending_changes` + dedup candidates; approve/reject |
| `app/auth/middleware.py` | `X-User-Id` header — production swap OIDC/SSO một chỗ |
| `app/main.py` | Composition root: wire mọi impl theo env, JSON logging, alembic upgrade, seed |
| `web/` (index.html, app.js, style.css) | UI v1: Chat SSE + sticky agent + user switcher 3 persona (An/Bình/Admin) + Catalog (search/lọc domain) + Review |

### Hạ tầng + chống lệch
| File | Nội dung |
|---|---|
| `seeds/demo_data.py` | Master row (prompt sync từ file mỗi lần khởi động) + agent/skill mẫu `ThamDinhHopDong` khi DB rỗng (rủi ro #6) |
| `Dockerfile` + `docker-compose.yml` | python:3.12-slim, EXPOSE 8000, volume `data/`, không bake key |
| `tests/` | 28 test cho phần dễ vỡ: state machine governance, validate/secret/dedup, router (FakeLLM — không tốn credit) |

---

## 3. Quyết định trong lúc implement (ngoài design, cần biết khi review)

1. **Tên tool wire `server__tool`** thay vì `server.tool` — API Anthropic/OpenAI cấm dấu chấm trong tên tool. UI/Review vẫn hiển thị dạng chấm.
2. **Server `system` luôn được cấp cho mọi agent** (chỉ có `get_current_date`, tool thật vô hại).
3. **Master system prompt**: file `master_system.md` là nguồn sự thật — seed tự đồng bộ vào row `master` mỗi lần khởi động (sửa prompt không cần đụng DB).
4. **Sticky session** đúng design: client giữ `agent_name` (app.js), server stateless; nút "đổi agent" để bỏ sticky.
5. **Local dev chạy Python 3.14** (máy không có 3.12) — code target 3.12+, Docker vẫn `python:3.12-slim` đúng chuẩn cuộc thi.
6. Dedup mềm dùng `ROUTER_MODEL` (rẻ); LLM lỗi → bỏ qua dedup, không chặn flow (tránh vỡ demo live).

---

## 4. Nhật ký verify 12/06 chiều — đã chạy gì, dừng ở đâu

### Đã chạy & PASS
- [x] venv (Python 3.14 local) + `pip install -e ".[dev]"` — deps OK
- [x] `pytest` — **27/27 pass** ngay lần đầu (governance, validate, router)
- [x] `uvicorn app.main:app --port 8000` — migration 0001 tự áp, seed master + `ThamDinhHopDong` OK
- [x] REST: `/healthz` 200; `/agents` đúng visibility; `/skills` OK; `/review/pending` 403 với user thường, 200 với admin; UI `/web/` 200
- [x] **Smoke test thật với MaaS**: chat master (explicit) → stream SSE chuẩn, master tự gọi tool `list_agents`, trả lời tiếng Việt đúng persona. usage_log ghi nhận (6200 in / 669 out tokens)

### Bug phát hiện & đã fix trong session
1. **`.env` có `MODEL=` (trống) đè mất default → 404 "model not found"**
   → fix `app/config.py`: `model_validator` coi env trống = dùng default. ✅ verified.
2. **Router classify 404**: endpoint **Anthropic** của MaaS CHỈ phục vụ MỘT SỐ model —
   `openai/gpt-4o-mini`, `gemini/gemini-2.5-flash-lite`, `deepseek/deepseek-v4-flash` đều 404
   qua `/v1/messages` (test trực tiếp; `qwen/qwen3-5-27b` và `minimax/minimax-m2.5` thì OK).
   Model list từ `/v1/models` là của endpoint OpenAI, không phản ánh pool Anthropic.
   → fix `app/main.py`: thêm `make_router_llm()` — router/dedup classify **luôn đi endpoint
   OpenAI-compatible** (chung key, đủ pool, có `response_format`), model chính vẫn Plan A Anthropic.
   → fix `app/config.py`: `router_model` mặc định đổi thành `qwen/qwen3-5-27b` (chỉ 3 model active:
   minimax/minimax-m2.5, qwen/qwen3-5-27b, google/gemma-4-31b-it; gpt-4o-mini 404).
   ✅ **VERIFIED 13/06**: classify "thẩm định hợp đồng" → ThamDinhHopDong/high; chào hỏi → fallback_master.

### ⏭️ Việc đầu tiên của session sau (verify fix #2)
✅ **DONE 13/06** — xem kết quả ở mục Bug #2 bên trên.

### Việc còn lại của mốc 12/06 (sau khi verify)
- [ ] Test tạo agent end-to-end bằng hội thoại trên UI (master phỏng vấn → create_skill → create_agent → test draft)
- [ ] Anh tự chạy kịch bản demo 5 phút cuối ngày (quy tắc chống lệch §7)

## 5. Kế hoạch các ngày tới (giữ nguyên §7)

- **13/06 sáng** — những phần code đã có sẵn skeleton nhưng cần hoàn thiện/kiểm thử kỹ qua UI: trang Review + Catalog end-to-end, dedup soft-warning trong hội thoại thật, seeds, thêm test còn thiếu.
- **13/06 chiều** — deploy bản đầy đủ: chạy tiếp `/agentbase-wizard` (đã dừng sau bước credential đúng luật BTC) → Docker build → push registry → runtime PUBLIC → verify từ mạng khác + volume mount SQLite.
- **14/06** — swap `MEMORY_BACKEND=agentbase` (implement `agentbase_memory.py`), MCP Gateway 1 server thật (`mcp_gateway.py`), agent private, redeploy.
- **15/06** — test người thật theo kịch bản video §10, fix theo feedback, seed agent demo.
- **16/06** — video 2–3 phút, use case ~150 chữ (draft sẵn §11), README, nộp.
