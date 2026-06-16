# Đóng góp cho Agent Hub

Agent Hub theo kiến trúc **plug-and-play**: thêm năng lực mới = **khai báo**, không phải sửa
engine. Tài liệu này mô tả 3 loại đóng góp và đúng những file bạn cần đụng. Quy ước chung:

- Output của agent **100% tiếng Việt**; tên tool trên wire dùng `server__tool` (2 gạch dưới).
- Conventional commit (`feat/fix/refactor/chore`), **không** hardcode secret/PII.
- `pytest` phải xanh trước khi mở PR (`./.venv/bin/python -m pytest -q`).

---

## Loại 1 — Agent mới (không viết code)

Một agent = persona + (tuỳ chọn) skill + danh sách connector có sẵn. Không cần code Python.

**Cách A — qua Master (khuyến nghị):** chat với Master Agent, mô tả nhu cầu. Master phỏng vấn,
chưng cất skill, tạo agent (Flow 2). Agent vào trạng thái `private` (maker dùng ngay) → submit
review → `public`.

**Cách B — seed sẵn trong repo:** thêm một `Agent(...)` (và `Skill(...)` nếu cần) trong
`seeds/demo_data.py`. Tham khảo các agent mẫu ở cuối file đó. Tối thiểu:

```python
Agent(
    name="Tên Agent",
    tagline="mô tả ngắn hiển thị trên card",
    description="viết CHO MODEL đọc — input của router (Flow 1)",
    system_prompt="persona + quy tắc hành xử…",
    connectors=["web-search"],   # tên server có trong catalog (xem Loại 2)
    domain="…", created_by="admin",
)
```

**Checklist PR:** tên agent unique · `description` đủ để router phân loại · `system_prompt`
rõ phạm vi (để agent biết khi nào `escalate`) · connectors khai đúng tên server tồn tại.

---

## Loại 2 — Connector / tool mới (viết ToolProvider)

Khi agent cần gọi API/tool thật (hoặc mô phỏng). Bạn viết một **provider** theo protocol
`app/tools/base.py::ToolProvider`.

1. **Tạo provider** `app/tools/<ten>.py`:

```python
class MyProvider:
    server_name = "my-service"   # tên connector agent khai trong `connectors`
    is_mock = False              # True nếu tool là mô phỏng (hiện nhãn trên trang Review)

    def list_tools(self) -> list[ToolDef]:
        return [ToolDef(name="do_thing", description="…", input_schema={...})]

    def call(self, tool_name: str, args: dict) -> str:
        ...  # trả str; raise lỗi → engine bắt và trả model tự xử lý
```

2. **Wire 1 dòng** vào `app/main.py` — thêm `MyProvider()` vào list `providers`.

3. **Tool ghi trạng thái** (sinh file/ghi workspace theo cuộc hội thoại): đánh dấu
   `ToolDef(..., stateful=True)`. Engine tự inject `_conversation_id` vào `args` khi gọi — **không**
   cần (và không được) để model tự cấp. Đây là cơ chế plug-and-play: engine nhận biết qua **cờ**,
   không qua tên tool.

4. **Tool sinh file tải về:** thêm 1 dòng map prefix → reader artifact trong
   `app/core/chat_engine.py::_ARTIFACT_READERS` để UI hiện nút tải.

5. **Test:** thêm `tests/test_<ten>.py` cho `list_tools()` + `call()`.

**Checklist PR:** `server_name` unique · `is_mock` đúng thực tế · tool stateful đã đánh cờ ·
có test · không nuốt lỗi im lặng.

---

## Loại 3 — Agent nâng cao (kiểu Upia)

Agent có **năng lực đặc biệt**: workspace ghi file + đóng gói ZIP, nạp tài liệu lớn vào RAG
theo cuộc, hoặc tinh chỉnh tool-loop (chạy non-stream/parallel cho lượt dài). Trước đây phần
này hard-code theo tên agent trong engine; nay **khai báo declarative** — **không sửa engine**.

1. Seed agent như **Loại 1** (persona + connectors gồm provider cung cấp tool nâng cao).

2. Provider của bạn đánh dấu các tool workspace là `stateful=True` (xem Loại 2, bước 3).

3. **Khai báo 1 entry** trong `app/core/capabilities.py::_PROFILES`:

```python
"TênAgent": AgentProfile(
    # tool chỉ lộ khi bật experimental; ngoài ra ẩn để giữ flow mặc định:
    workspace_tools=("my-service__save_file", "my-service__package"),
    # markdown nối vào system prompt khi experimental bật:
    extra_system_notes=(_AGENTS_DIR / "tenagent" / "experimental_mode.md",),
    large_doc_rag=True, rag_min_chars=8000,   # tài liệu ≥ ngưỡng → nạp RAG theo cuộc
    execution=ExecutionProfile(stream=False, parallel_tools=True),  # lượt dài
),
```

4. Capability "experimental" chỉ bật khi env `UPIA_EXPERIMENTAL_MODE=true` (cờ global cho chế
   độ thử nghiệm). Tắt → agent chạy như Loại 1 bình thường.

5. **Test:** xem `tests/test_capabilities.py` + `tests/test_engine_workspace_gating.py` làm mẫu —
   khoá hành vi ẩn/lộ tool và giá trị profile.

**Vì sao tách `workspace_tools` (ẩn-trừ-khi-bật) khỏi tool connector thường:** tool workspace
chỉ nên xuất hiện ở chế độ thử nghiệm; ngoài ra agent giữ đúng flow gốc. `CapabilityResolver`
quản lý: `gated_tools()` (luôn biết tập cần ẩn, độc lập cờ) và `active_profile()` (chỉ có hiệu
lực khi experimental bật).

---

## Bản đồ nhanh "đụng file nào"

| Đóng góp | File chính | Có sửa engine? |
|---|---|---|
| Agent mới | `seeds/demo_data.py` (hoặc qua Master UI) | Không |
| Connector mới | `app/tools/<ten>.py` + 1 dòng `app/main.py` | Không |
| Agent nâng cao | seed + 1 entry `app/core/capabilities.py` | Không |

Engine (`app/core/chat_engine.py`) là code generic — nếu PR của bạn phải sửa nó để thêm một
agent/connector, hãy dừng lại và mở issue: nhiều khả năng cần thêm một **cờ/field khai báo**
thay vì nhánh `if` theo tên.
