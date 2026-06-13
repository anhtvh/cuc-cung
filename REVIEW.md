# Agent Hub — Rà soát toàn diện (13/06/2026)

Tài liệu này liệt kê **bug thật, logic lủng, điểm cải thiện** và **điểm innovation** sau khi đọc toàn bộ source (app/, tests/, seeds/, migrations/).

---

## 1. Bugs thật (sai hành vi, cần fix trước demo)

### B-01 · `GET /skills` lộ private skill của người khác
**File:** `app/api/skills.py:12` — `list_skills` và `get_skill` không lọc theo `user_id`.  
Mọi user đều thấy (và đọc được full content markdown của) skill private của người khác — vi phạm model bảo mật "private chỉ owner/admin thấy".

```python
# Hiện tại: trả hết
skills = c.skills.list()

# Fix: lọc giống master._h_list_skills
skills = [
    s for s in c.skills.list()
    if s.status == ItemStatus.public or s.created_by == user_id
]
```

### B-02 · `GET /skills/{name}` cũng không check quyền
**File:** `app/api/skills.py:44` — `get_skill` trả full data (kể cả content, pending_changes) mà không kiểm tra visibility.

### B-03 · `review.py` gọi `dedup_candidates` không truyền `user_id`
**File:** `app/api/review.py:57`  
```python
c.governance.dedup_candidates("agent", a.name, a.description)
# user_id bị bỏ → default "" → can_use_agent check sai visibility
```
Kết quả dedup trên trang Review có thể bao gồm agent private của người khác.

### B-04 · Slug trùng nhau khi tên agent khác nhau sau slugify
**File:** `app/core/models.py:16` — `slugify()`  
Ví dụ: agent "Bé Bơ" và "Be Bo" đều ra slug `be-bo`. Router `@mention` dùng slug → trỏ sai agent. Không có constraint unique slug check ở tầng Governance khi `create_agent`.

### B-05 · `_h_update_agent` mutate dict của caller
**File:** `app/builder/master.py:377`  
```python
def _h_update_agent(self, args: dict) -> ToolResult:
    name = str(args.pop("name"))   # ← pop mutate args input
```
Nếu framework hay test tái sử dụng dict, data bị mất. Nên dùng `args.get("name")` + dict mới.

### B-06 · `openai_client.chat_with_tools` không stream text ở vòng cuối
**File:** `app/llm/openai_client.py:84` — Hàm `chat_with_tools` dùng non-stream API (`stream` không được truyền):  
```python
resp = self._client.chat.completions.create(
    model=..., messages=convo, tools=api_tools   # không có stream=True
)
if msg.content:
    yield TextDelta(msg.content)  # dump toàn bộ text 1 lần
```
User thấy blank → đột ngột xuất hiện toàn bộ text. Ngược lại `chat()` dùng streaming đúng.

### B-07 · `get_current_date` trả server-local date, không timezone-aware
**File:** `app/tools/catalog.py:33`  
```python
return date.today().isoformat()  # Server UTC, user Việt Nam UTC+7
```
Sau 17:00 UTC, date trả về lệch 1 ngày so với thực tế của user.

### B-08 · `SqlAgentRepo.delete` không atomic
**File:** `app/storage/sql.py:234–241`  
Năm lệnh `s.execute(delete(...))` trong một session: nếu execute thứ 3 fail, DB ở trạng thái partial delete (AgentSkillRow xóa rồi nhưng AgentRow chưa xóa). Cần bọc trong 1 transaction rõ ràng.

### B-09 · `AgentBaseMemory` dùng `httpx.Client` đồng bộ trong ASGI context
**File:** `app/memory/agentbase_memory.py:81`  
```python
self._http = httpx.Client(timeout=10.0)  # blocking sync client
```
FastAPI chạy trên ASGI; mọi request qua Starlette eventloop. Gọi sync I/O bên trong (dù wrapped qua threadpool của Starlette StreamingResponse) có thể block event loop ở các điểm không kiểm soát. Nên dùng `httpx.AsyncClient` + `await`, hoặc explicit `run_in_executor`.

### B-10 · `chat.py` routing khi message trống + có attachment dùng string cứng
**File:** `app/api/chat.py:47`  
```python
routing_message = req.message.strip() or "Hãy xử lý tài liệu đính kèm."
```
Router classify bằng câu generic → hầu hết fallback về master thay vì agent chuyên môn đúng. Nên truyền `filename` hoặc content-type vào routing string để classify tốt hơn.

---

## 2. Logic lủng (flow đúng intent nhưng implementation chưa kín)

### L-01 · Escalation / Delegate không tự re-route — phụ thuộc hoàn toàn frontend
**File:** `app/core/chat_engine.py:205–212`  
Khi agent con gọi `escalate` hoặc master gọi `delegate_to_agent`, engine yield event `delegate` rồi dừng. ChatEngine **không** tự gọi agent mới — phụ thuộc frontend nhận event `delegate` và POST `/chat` mới với `agent_name` tương ứng.

Nếu frontend bỏ qua event này (xử lý sai), user thấy blank hoặc stream đứt mà không có phản hồi. Nên có fallback: emit một text delta ngắn giải thích trạng thái khi delegate, trước khi dừng stream.

### L-02 · `submit_for_review` không tự submit skill đi kèm — dễ block approve
**File:** `app/builder/master.py:430–438`  
Handler chỉ warning bằng text trong `note`:
```
"LƯU Ý: agent gắn skill còn private [...] — submit cả các skill này..."
```
Model có thể bỏ qua warning text trong tool result (phổ biến với tool loop nhanh). Agent bị kẹt `pending_review` vô thời hạn vì skill chưa submit. Nên hỏi model gọi `submit_for_review(kind=skill, name=X)` ngay sau, hoặc auto-submit skill private gắn theo agent.

### L-03 · `build_system_prompt` search memory bằng `agent.name` làm query
**File:** `app/core/chat_engine.py:106`  
```python
memories = self._memory.search(user_id, agent.name)
```
`agent.name` không phải query có nghĩa ngữ nghĩa. Khi AgentBase Memory được kết nối (14/06), semantic search bằng tên agent sẽ cho kết quả không liên quan. Query đúng phải là current user message hoặc context gần nhất. Cần thêm `message` param vào `build_system_prompt`.

### L-04 · System prompt không có guard context limit
**File:** `app/core/chat_engine.py:92–115`  
System prompt = persona + N skill (mỗi skill có thể vài KB markdown) + memory + suffix. Không có mechanism estimate/truncate khi vượt context limit model. Agent nhiều skill lớn sẽ bị model truncate silently → skill cuối bị cắt, agent xử lý thiếu quy trình.

### L-05 · `ToolCatalog.execute` tạo mới `ThreadPoolExecutor` mỗi lần call
**File:** `app/tools/catalog.py:89–94`  
```python
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(provider.call, tool, args)
```
Mỗi tool call = tạo thread mới + shutdown. Trong tool loop 5 vòng × nhiều tool = nhiều thread creation/teardown. Nên dùng 1 shared executor ở catalog level hoặc đơn giản hơn: dùng `threading.Thread` + `Event` + timeout.

### L-06 · `McpGatewayProvider.list_tools` gọi HTTP mỗi request
**File:** `app/tools/mcp_gateway.py:124–152`  
Mỗi request chat với agent có gateway connector → gọi `tools/list` qua HTTP. Không có cache. Nếu MCP server bị chậm, nó block trước khi chat bắt đầu. Nên cache kết quả với TTL (vd 60s).

### L-07 · `governance.dedup_candidates` gửi full catalog listing lên LLM mỗi lần
**File:** `app/core/governance.py:162–192`  
Khi catalog lớn (100+ agent/skill), listing string rất dài, tốn credit router_model. Nếu dedup LLM fail, bỏ qua (silent), tốn credit mà không có lợi. Nên: pre-filter bằng domain trước khi gửi lên LLM, chỉ gửi cùng domain.

### L-08 · Slug trùng không bị phát hiện (liên quan B-04)
**File:** `app/core/governance.py:145` — `check_duplicate_name` chỉ check exact name (PK). Không check slug collision. Hai agent tên khác nhau → slug giống → `@mention` trỏ sai → silent routing bug.

### L-09 · `visible_agents` không có master trong candidates nhưng router fallback về master
**File:** `app/core/router.py:28–29`  
Router lấy `candidates = visible_agents(user_id)` (không bao gồm master). Khi classify fail hoặc không có candidate nào → fallback master. Điều này OK. Nhưng nếu user explicit mention slug của một agent không còn visible (đã reject sau khi user đã set sticky), router log warning và classify lại — có thể route tới agent không expect, không thông báo user.

### L-10 · `ensure_seed` tạo `_SAMPLE_SKILL` với `status=public` nhưng không review
**File:** `seeds/demo_data.py:15–41`  
`_SAMPLE_SKILL` seed với `status=ItemStatus.public` và `reviewed_by="admin"` directly, bypassing governance flow. Đây OK cho demo nhưng tạo precedent cho code khác bypass flow. Nên dùng helper seed rõ ràng.

### L-11 · `SqlAgentRepo.update` set `updated_at` hai lần
**File:** `app/storage/sql.py:208` + `app/core/governance.py:237,241,244`  
`governance.propose_update` set `item.updated_at = now_iso()` → gọi `repo.update(item)` → `update` lại set `agent.updated_at = now_iso()`. Double-write: lần 2 thắng, nhưng có thể gây confusion khi trace.

---

## 3. Điểm cần cải thiện (không phải bug, nhưng ảnh hưởng chất lượng)

### I-01 · Thiếu index database — query chậm khi dữ liệu lớn
**File:** `app/storage/sql.py`  
Bảng `messages` không có index `(user_id, agent_name)` — `get_history` full scan.  
Bảng `usage_log` không có index `agent_name` — `top_agents` GROUP BY full scan.  
Bảng `agents` không có index `created_by` — `list(created_by=X)` full scan.  
Với demo SQLite ít dữ liệu: OK. Với Postgres production: block.

### I-02 · Auth header dễ bị giả mạo trong môi trường contest
**File:** `app/auth/middleware.py:13`  
```python
request.state.user_id = request.headers.get("X-User-Id", DEFAULT_USER).strip()
```
Bất kỳ client nào cũng tự đặt `X-User-Id: admin` → access trang Review. Contest môi trường internal nên OK, nhưng cần note rõ trong video/README.

### I-03 · `parse_json_loose` regex `{.*}` có thể match sai với text dài
**File:** `app/llm/base.py:100`  
```python
m = re.search(r"\{.*\}", text, re.DOTALL)
```
Regex greedy + DOTALL → match từ `{` đầu tiên đến `}` cuối cùng của text, có thể bao gồm ngoài block JSON nếu model thêm text thừa sau JSON. Nên dùng non-greedy hoặc balanced-bracket parser.

### I-04 · AGENT_NAME_RE cho phép multiple spaces
**File:** `app/core/governance.py:32`  
Pattern `[\w ]{2,64}` cho phép "Bé  Bơ" (2 space). Sau slugify → `be-bo` (cùng slug với "Bé Bơ"). Nên normalize: `re.sub(r'\s+', ' ', name.strip())` trước khi validate.

### I-05 · `_ESCALATE_TOOL` inject cho mọi agent con kể cả khi không có tool nào
**File:** `app/core/chat_engine.py:169`  
Escalate tool inject vô điều kiện cho mọi non-master agent. Agent chuyên môn chặt (ví dụ chỉ xử lý hợp đồng) sẽ hay gọi `escalate` với câu hỏi hơi lệch domain thay vì cố gắng trả lời. Nên cho phép config `escalate_enabled` per-agent.

### I-06 · Không có rate limiting — master tool loop có thể gọi LLM vô tận trong 1 session
**File:** `app/config.py:32` — `max_tool_rounds=5` chỉ giới hạn vòng tool trong 1 call. Không giới hạn số call `/chat` per user/session. User trigger master → 5 vòng MaaS call; gửi tiếp → 5 vòng nữa. Credit cạn nhanh (rủi ro #3 đã biết nhưng chưa có giảm thiểu kỹ thuật).

### I-07 · `upload.py` không validate content vs extension
**File:** `app/api/upload.py:34–37`  
Media type output dựa vào extension:
```python
media_type = "image/png" if name.endswith(".png") else "image/jpeg"
```
File `.jpg` với content là PNG (hoặc ngược lại) trả sai media_type → model vision API lỗi. Nên dùng `imghdr` hoặc magic bytes để detect thật.

### I-08 · `AgentBaseMemory` không retry khi `append` fail
**File:** `app/memory/agentbase_memory.py:144–158`  
Message event mất khi HTTP fail, không retry. History bị hổng. Nên retry 1 lần với backoff ngắn.

### I-09 · `IamTokenProvider` lock giữ trong khi gọi HTTP
**File:** `app/tools/mcp_gateway.py:50–66`  
```python
with self._lock:
    if self._token and ...: return self._token
    resp = httpx.post(IAM_TOKEN_URL, ...)  # blocking I/O trong lock
```
Nhiều thread chờ lock trong khi 1 thread đang fetch token. Nên dùng pattern: check lock, nếu cần refresh thì release lock → fetch → acquire lại → set.

### I-10 · Test coverage thiếu API layer và upload
**File:** `tests/`  
Coverage tốt ở core governance và router. Không có test cho:
- `app/api/chat.py` (SSE stream + delegate event)
- `app/api/upload.py` (PDF/DOCX extraction)
- `app/tools/catalog.py` (timeout, wire name)
- `app/builder/master.py` handler-level (chỉ test qua governance)

### I-11 · Dockerfile không pin Python patch version
**File:** `Dockerfile`  
`FROM python:3.12-slim` (không pin patch) → build lại khác ngày có thể dùng Python khác. Nên `python:3.12.10-slim` cụ thể.

---

## 4. Điểm Innovation nổi bật

### N-01 · "Agent sinh agent" với maker-checker governance
Flow 2 (master phỏng vấn → tạo agent) + Flow 2b (draft → pending → active/rejected) là ý tưởng core mạnh nhất của project. Người dùng không cần biết prompting — master làm thay; admin đảm bảo chất lượng trước khi agent đến tay toàn công ty.

### N-02 · Shared Skill — single source of truth
Skill là markdown độc lập, N agent gắn chung → khi admin duyệt update skill, tất cả agent gắn nó tự cập nhật (Flow 4). Đây là kiến trúc "content reuse" đúng hướng: tránh drift khi nhiều agent copy-paste cùng quy trình nhưng riêng lẻ.

### N-03 · Virtual agent — không deploy, chạy chung engine
Agent con là row config trong DB, không cần build/deploy container riêng. Tạo agent mới = tức thì, không có cold start. Scale agent catalog mà không scale infra.

### N-04 · Escalation tool — agent tự biết giới hạn scope
Agent con được inject `escalate` tool; khi gặp out-of-scope tự delegate về master thay vì hallucinate. Pattern này ("graceful degradation với tool") đang là best practice nhưng ít sản phẩm nào làm ở level agent-level self-awareness.

### N-05 · Dedup LLM để tránh catalog bloat
Khi tạo agent/skill mới, classify tương đồng bằng LLM (soft-block), tránh "100 agent làm cùng việc" về dài hạn. Kết hợp với hard-block exact name và soft-warning semantic → 3 tầng dedup.

### N-06 · Slug auto-generation từ tên Unicode tiếng Việt
`slugify("Bé Pháp")` → `@be-phap` cho @mention. Người dùng Việt đặt tên tự nhiên, hệ thống tự tạo handle ASCII — UX tốt hơn hầu hết hệ thống yêu cầu user tự nhập slug.

### N-07 · Two-endpoint strategy cho MaaS (Anthropic + OpenAI compat)
Nhận ra endpoint Anthropic của MaaS không phục vụ đủ model pool và dùng OpenAI-compat endpoint cho router/dedup (model rẻ) trong khi giữ Anthropic native cho chat (tool-use native). Pragmatic engineering trong điều kiện platform mới.

### N-08 · Fetch URL → distill skill (fetch_url tool)
Master có thể nhận link URL → fetch và trình bày nội dung → user xác nhận → tạo skill. Workflow "doc → knowledge extraction → skill" hoàn chỉnh mà không cần user biết prompt engineering.

---

## Tóm tắt ưu tiên

| Mức | Items | Hành động |
|---|---|---|
| **Fix ngay (trước demo)** | B-01, B-02, B-03, B-04, L-01 | Fix code + test |
| **Fix hôm nay** | B-05, B-06, B-07, L-02, L-03 | Fix + smoke test |
| **Cải thiện nếu còn thời gian** | L-05, L-06, I-01, I-03 | Refactor nhẹ |
| **Note trong README/video** | I-02 (auth), I-06 (rate limit) | Disclaimer |
| **Roadmap sau contest** | I-09, I-11, I-10 | Backlog |

---

## Trạng thái fix (13/06/2026)

| ID | Mô tả ngắn | Status |
|---|---|---|
| L-04 | System prompt context guard (truncate skill >8k chars) | ✅ `chat_engine.py` |
| L-05 | Shared ThreadPoolExecutor trong ToolCatalog | ✅ `catalog.py` |
| L-06 | Cache list_tools MCP Gateway với TTL 60s | ✅ `mcp_gateway.py` |
| L-07 | Pre-filter by domain trước khi gửi LLM dedup | ✅ `governance.py` |
| L-08 | Slug trùng hard-block | ✅ đã cover trong B-04 |
| L-09 | Stale sticky agent → fallback master với note | ✅ `router.py` |
| L-10 | Seed bypass governance — thêm comment rõ ràng | ✅ `demo_data.py` |
| L-11 | Double `updated_at` write — bỏ set trong governance | ✅ `governance.py` |
| I-01 | DB indexes (messages, usage_log, agents) | ✅ migration 0003 |
| I-02 | Auth note comment về security risk contest | ✅ `middleware.py` |
| I-03 | parse_json_loose dùng rfind thay greedy regex | ✅ `base.py` |
| I-04 | Reject double-space trong agent name | ✅ `governance.py` |
| I-05 | escalate_enabled per-agent flag | ✅ `models.py` + migration 0003 |
| I-06 | max_chat_calls_per_session config field | ✅ `config.py` |
| I-07 | Magic bytes detect image type | ✅ `upload.py` |
| I-08 | Retry 1 lần khi AgentBaseMemory.append fail | ✅ `agentbase_memory.py` |
| I-09 | IamTokenProvider không giữ lock khi gọi HTTP | ✅ `mcp_gateway.py` |
| I-10 | Tests cho upload + catalog + parse_json_loose | ✅ `test_upload.py`, `test_catalog.py` |
| I-11 | Pin Python patch version trong Dockerfile | ✅ `python:3.12.10-slim` |
