# Báo cáo E2E Test — Agent Hub (Cục Cưng)

**Ngày:** 2026-06-14 · **Cách test:** HTTP + SSE script, mô phỏng 3 persona (Guest / User "An","Bình" / Admin) qua JWT cookie, LLM MaaS **live**. DB cô lập (`hub_e2e.db`), self-test tắt.

## Tổng quan
Phần lớn flow **chạy đúng**: routing (explicit/@mention/classify/fallback), authz/IDOR, governance state machine cơ bản, Flow 2 (master tạo agent), cô lập private, salutation persistence, guest-block, validate input, switch/handoff giữa agent. Tìm thấy **4 bug thật + 1 vấn đề behavior — TẤT CẢ đã FIX & verify**, cùng vài quan sát nhỏ. (Bug #1–#3 đợt 1; Bug #4 + behavior #5 đợt 2 — phần switch agent.) Tổng **120/120 unit test pass**.

---

## 🔴 BUG #1 — App crash khi boot/login do passlib + bcrypt (CRITICAL — chặn deploy) — ✅ ĐÃ FIX

> **Fix:** pin `bcrypt>=4.0,<4.1` trong `pyproject.toml`. Verify: `hash_password`/`verify_password` chạy đúng.


**Hiện tượng:** Set `ADMIN_PASSWORD` → app **crash ngay khi khởi động**. Không set thì `/auth/login` (đăng nhập admin) sẽ **500**.

```
ValueError: password cannot be longer than 72 bytes...
  app/main.py:205  user_repo.seed_admin(..., hash_password(...))
  app/auth/password_auth.py:7  _ctx.hash(password)
```

**Nguyên nhân:** `passlib 1.7.4` **không tương thích** `bcrypt 5.0.0` (đã cài). `pyproject.toml` để `passlib[bcrypt]>=1.7`, **bcrypt không pin** → khi build Docker (`python:3.12-slim`) pip vẫn kéo bcrypt 5.x → **dính y hệt, không phải lỗi riêng Python 3.14 local**.

**Tác động:** Admin password login hỏng hoàn toàn; nếu set `ADMIN_PASSWORD` thì cả app không boot. (Google OAuth không qua bcrypt nên không dính.)

**Repro:** `ADMIN_EMAIL=x ADMIN_PASSWORD=y uvicorn app.main:app` → crash.

**Đề xuất fix:** pin `bcrypt<4.1` trong `pyproject.toml`, hoặc bỏ passlib dùng thư viện `bcrypt` trực tiếp (nhớ tự cắt 72 byte).

---

## 🔴 BUG #2 — Sửa/duyệt `visibility` gây 500 + kẹt state (HIGH) — ✅ ĐÃ FIX

> **Fix:** thêm `_coerce_field()` trong `governance.py` coerce string→enum trước `setattr` ở cả `approve()` và `propose_update()`. Thêm 2 regression test (`test_governance.py`). Verify: cả 2 trigger hết crash, 115/115 test pass.


**Hiện tượng:** Đổi `visibility` của agent → **500** (`AttributeError: 'str' object has no attribute 'value'`), agent kẹt trạng thái.

**2 đường kích hoạt (đã xác minh):**
1. **Agent draft/rejected**: user sửa `visibility` (modal Sửa) → 500 ngay.
2. **Agent active**: sửa `visibility=company` → vào `pending_changes` → admin **approve** → 500 + pending kẹt vĩnh viễn.

> `visibility=private` trên agent active **không** nổ — vì code có nhánh coerce enum riêng (`governance.py:281`). Chỉ giá trị đi qua `pending_changes`/setattr thô mới gãy.

**Nguyên nhân:** `governance.approve()` (TH1) và `propose_update()` (nhánh draft/rejected) gán **string thô** vào field enum:
```python
# app/core/governance.py:359  (approve)
for k, v in item.pending_changes.items():
    setattr(item, k, v)          # item.visibility = "company"  (str, không phải Visibility)
# app/core/governance.py:295  (propose_update draft/rejected)
for k, v in fields.items():
    setattr(item, k, v)
```
Sau đó persist nổ tại `app/storage/sql.py:168 → r.visibility = a.visibility.value`.

**Đề xuất fix:** coerce enum trước khi set (vd `Visibility(v)` cho field `visibility`, `ItemStatus(...)` nếu có), hoặc bật `validate_assignment=True` trên model Pydantic, hoặc chuẩn hoá khi đọc/ghi pending_changes.

---

## 🟠 NGHỊCH LÝ #3 — "Submit duyệt → approve" nhưng agent vẫn vô hình với công ty (MEDIUM-HIGH) — ✅ ĐÃ FIX

> **Fix:** `submit_for_review` agent có `visibility=private` → tự nâng `company` (submit = ý định chia sẻ; lúc pending vẫn chỉ owner dùng vì status≠public). Lời hứa "cả công ty thấy" thành đúng; use-case "tạm ẩn" (public→private sau approve) không bị ảnh hưởng. Thêm regression test. Verify offline + HTTP: sau approve agent thành `public+company`, user khác dùng được.


**Hiện tượng:** An tạo agent (master đặt `visibility=private`), submit duyệt, admin approve → `status=public` nhưng `visibility` **vẫn private** → **Bình/guest không thấy, không dùng được**. Maker-checker coi như vô nghĩa.

**Vênh thông điệp:** tool `submit_for_review` mô tả *"Sau khi approve, cả công ty thấy và router điều phối tới"* (`app/builder/master.py:130`) — **lời hứa sai** khi visibility=private. `approve()` chỉ đổi `status`, **không đụng** `visibility` (`governance.py:382`).

**Kết hợp Bug #2:** cách "tự nhiên" để chia sẻ là đổi visibility→company → **crash**. ⇒ Trên thực tế, agent lỡ tạo ở private gần như **không thể chia sẻ công ty** qua flow chuẩn. (Chỉ hoạt động nếu master set company ngay lúc create — mà model có thể tự chọn private như lần test này.)

**Đề xuất:** (a) chặn submit_for_review agent visibility=private (hỏi user muốn share không), hoặc (b) approve agent ⇒ set visibility=company, hoặc (c) ít nhất sửa thông điệp + cảnh báo admin "agent này private, duyệt xong vẫn chỉ owner dùng".

---

## 🟡 Quan sát nhỏ
- **Không có API sửa skill trực tiếp** (`/skills` chỉ có GET + submit) — Flow 4 (sửa skill active → version+1) **chỉ đi qua master chat**. Nếu UI có nút "Sửa skill" thì cần kiểm lại.
- **`/mcp` mở khi `MCP_GATEWAY_SECRET` trống** — đúng thiết kế (đã có warning ở main.py), nhưng nhớ set secret khi deploy public.
- **`/upload` không yêu cầu đăng nhập** — guest upload được file 5MB rồi đẩy vào chat; rủi ro thấp nhưng nên cân nhắc rate-limit.
- Note ở fallback sticky (L-09) ghi "đang chờ duyệt hoặc bị từ chối" — với agent public+private thì lý do thật là "không được chia sẻ", thông điệp hơi lệch (cosmetic).

---

## ✅ Đã verify PASS
| Hạng mục | Kết quả |
|---|---|
| Authz/IDOR (user sửa/xóa/submit agent người khác, truy cập master) | 403/404 đúng |
| Admin gating (`/review/*`, `/admin/stats`) cho guest/user | 403 đúng |
| Routing: explicit / @mention / @mention-không-tồn-tại / classify / orchestrate(≥2) / fallback | đúng hết |
| Governance: active edit→pending_changes (vẫn phục vụ), approve áp dụng, reject revert | đúng (trừ field visibility — Bug #2) |
| Ràng buộc approve agent: mọi skill phải active | chặn đúng (409) |
| Flow 2: master phỏng vấn → create_skill/create_agent/attach_skill → draft dùng ngay | đúng |
| Cô lập: agent private chỉ owner thấy (Bình/guest 404) | đúng |
| Salutation: hỏi 1 lần, lưu "anh", không hỏi lại | đúng |
| Guest tạo agent → bị mời đăng nhập, không cấp tool tạo | đúng |
| Validate: message rỗng → 422; SSE stream hoàn tất, không chết im | đúng |

*(Chưa test trên browser thật: Google OAuth callback, render UI tab theo role, sub-agent card — cần trình duyệt.)*

---

# Đợt 2 — Test switch / handoff giữa các agent

Seed thêm **Bé Bếp** (domain cooking) cạnh **Bé Pháp** (legal). Driver mô phỏng đúng UI: theo event `delegate` qua các hop (A→master→B).

## 🔴 BUG #4 — Escalation loop ngược về chính agent vừa escalate (HIGH) — ✅ ĐÃ FIX

**Hiện tượng:** Hỏi Bé Pháp (legal) một câu off-domain (nấu ăn) → Bé Pháp gọi tool `escalate` đúng (`delegate→master`), nhưng hop kế tiếp **quay lại Bé Pháp**, KHÔNG tới master — và Bé Pháp đi trả lời luôn câu ngoài chuyên môn (đưa công thức phở). Tính năng "off-domain → switch về master" **hỏng hoàn toàn**.

**Nguyên nhân:** engine sinh marker `"[Escalated từ @Bé Pháp: <lý do>]\n\n<gốc>"` và UI gửi lại với `agent_name=master`. Nhưng `router.route()` chạy bước **@mention theo tên trước bước sticky** (`router.py` step 1b) → bắt `@Bé Pháp` **nằm trong marker** → route ngược về Bé Pháp. PROBE xác nhận deterministic: gửi marker + sticky=master vẫn ra `routed_by=mention, agent=Bé Pháp`.

**Fix:** thêm bước 0 trong `router.route()` — nếu message bắt đầu bằng marker `[Escalated từ ` thì **luôn về master** (`routed_by="escalate"`), chặn trước mọi bước mention. Thêm regression test (`test_router.py`). Verify HTTP: off-domain → Bé Pháp escalate → **master nhận & trả lời/tư vấn** ✓.

## 🟡 QUAN SÁT #5 — Việc *quyết định* escalate không ổn định (model-dependent) — ✅ ĐÃ FIX (hướng B+C)

> **Đã chốt & triển khai hướng B+C** (giữ web-search cho mọi agent, không cắt):
> - **B — scope-guard deterministic ở router** (`router.py::_in_scope`): mỗi lượt sticky tới agent con có `escalate_enabled`, chạy 1 call model rẻ hỏi `in_scope?`. Off-scope rõ ràng → chuyển Master ngay (`routed_by="escalate"`), không phụ thuộc model lớn nhớ gọi tool. Bảo thủ + fail-open: tin nhắn <12 ký tự (chào/cảm ơn) và lỗi LLM → coi in-scope. Agent broad set `escalate_enabled=False` để tự do trả lời mọi thứ.
> - **C — prompt priority + lint** (`chat_engine.py`, `governance.py`): siết `_ESCALATION_PROMPT_SUFFIX` thành "kiểm tra scope ĐẦU TIÊN, off-scope thì escalate, CẤM web-search trả lời lạc đề"; `_WEB_SEARCH_PROMPT_SUFFIX` thêm "chỉ dùng cho câu in-scope"; lint cảnh báo persona thiếu scope-guard.
> - **Verify live (nhất quán):** 4/4 câu off-domain (thời tiết, du lịch, dịch, nấu ăn) hỏi Bé Pháp → đều `escalate→master`, master trả lời; 2/2 câu in-domain → giữ Bé Pháp, không escalate nhầm. 120/120 unit test pass (+3 scope-guard test).
> - **Chi phí:** +1 call model rẻ (gemma) mỗi lượt sticky của agent con; bỏ qua khi tin nhắn ngắn / `escalate_enabled=False`.

**(Bối cảnh ban đầu — vấn đề đã xử lý):**

Cơ chế routing/handoff giờ **đúng** (Bug #4 đã fix). Nhưng *agent có thực sự escalate hay không* lại **không nhất quán**:
- Cùng câu "du lịch Đà Nẵng": lúc gọi `escalate`, lúc chỉ **nói** "để em nhờ người phù hợp hơn" mà **không gọi tool** → user bị treo, không ai tiếp nhận.
- "Thời tiết Hà Nội": Bé Pháp (agent pháp lý) **tự dùng web-search trả lời** thay vì escalate.

**Nguyên nhân gốc:** `ALWAYS_ON_SERVERS = ["system", "web-search"]` (`chat_engine.py:20`) cấp **web-search cho MỌI agent** + prompt `_WEB_SEARCH_PROMPT_SUFFIX` bảo "gặp câu hỏi thực tế thì search & trả lời". Cái này **xung đột** với `_ESCALATION_PROMPT_SUFFIX` ("ngoài scope thì escalate"). Model (minimax-m2.5) xử lý mâu thuẫn không nhất quán → agent domain hẹp hay tự trả lời off-domain.

**Hướng xử lý (cần anh chọn — đây là tradeoff sản phẩm, chưa tự sửa):**
1. Ưu tiên escalation: chỉ inject web-search khi agent thật sự gắn connector `web-search` (bỏ khỏi ALWAYS_ON) → agent domain hẹp không có "đường tự trả lời", buộc escalate.
2. Siết prompt: nói rõ "off-domain → escalate TRƯỚC, web-search chỉ dùng cho câu IN-domain cần dữ liệu mới".
3. Chấp nhận hiện trạng (agent tiện thì trả lời, tiện thì escalate) nếu UX này ổn.

## ✅ Switch scenarios verify PASS
| Kịch bản | Kết quả |
|---|---|
| In-domain (legal hỏi Bé Pháp) | Bé Pháp tự trả lời, KHÔNG escalate ✓ |
| Off-domain → escalate → **master trả lời** | ✓ (sau fix #4) |
| Explicit `@mention` switch giữa cuộc (Bé Pháp → @be-bep) | sang Bé Bếp đúng ✓ |
| Đa-mention (`@be-phap @be-bep`) → orchestrate | `routed_by=orchestrate` → master điều phối ✓ |
| Marker escalation luôn về master (mọi sticky) | ✓ deterministic (unit + HTTP) |

*Lưu ý: `escalate_enabled` (per-agent, default True) tắt được để agent domain chặt không escalate sớm — nhưng KHÔNG có trong `AgentEditRequest` của API `PUT /agents`, chỉ set qua master tool `update_agent`. Nếu UI muốn cho user toggle thì cần bổ sung field.*

---

# Đợt 3 — Trải nghiệm view-user (Tier 1 đầy đủ + Tier 2 chọn lọc)

Mục tiêu: "trải nghiệm đúng & tốt", không chỉ "có chạy". Seed thêm Bé Bếp (cooking) + Trợ Lý HR (draft của user An). 3 persona qua JWT, LLM live cho nhóm Tier 2.

## ✅ PASS — chức năng & UX đúng
| Nhóm | Kịch bản | Kết quả |
|---|---|---|
| **A. History** | sidebar restore (F5), load messages, rename, delete (sạch + không lộ conv khác), empty state, **guest KHÔNG persist** | ✓ |
| **C. Upload** | .txt/.md/.docx trích đúng; ảnh detect bằng **magic bytes** (jpeg giả .png → đúng image/jpeg); >5MB→413; định dạng lạ→415; PDF hỏng→422 thân thiện | ✓ |
| **C8. Upload→thẩm định** | upload hợp đồng → Bé Pháp đọc nội dung, lập bảng rủi ro (bắt điều khoản đơn phương chấm dứt) | ✓ |
| **D. Feedback** | 👍/👎 ghi nhận, validate rating, admin stats tổng hợp đúng, non-admin xem stats→403 | ✓ |
| **E. Catalog** | list + lọc domain; chi tiết agent: skills, connectors (nhãn) | ✓ |
| **F. Của tôi (lifecycle)** | tạo→draft; sửa draft áp ngay; **đổi visibility (verify Bug#2 trên UI path — hết 500)**; submit→**tự nâng company (Bug#3)**→approve→**Bình thấy**; sửa active→pending_changes (bản cũ vẫn chạy)→approve áp dụng; owner xoá active bị chặn, admin xoá được | ✓ |
| **B. Memory** | multi-turn nhớ đúng (mã HĐ + đối tác); memory **tách theo (user,agent)** — agent khác không biết | ✓ |
| **H. Orchestration** | `@A @B` → orchestrate → master `run_agent`×2 chạy cả 2 agent + tổng hợp | ✓ |
| **I. Web-search** | câu real-time in-domain → search→fetch DuckDuckGo thật, trả kết quả có nguồn | ✓ |
| **K. Resilience** | rate-limit→429 thân thiện; lỗi giữa stream→meta gửi trước rồi error event (không crash/blank); empty state hợp lý | ✓ |

## 🟡 Quan sát UX (đề xuất cải thiện) — TẤT CẢ ĐÃ FIX
1. **Lỗi giữa stream lộ message thô provider** — ✅ FIX: `chat.py` gửi câu thân thiện ra UI, log giữ chi tiết.
2. **`last_text` preview dính `\n\n` đầu** — ✅ FIX: `.strip()` + bỏ qua preview rỗng trong `chat.py`.
3. **Dedup không proactive khi tạo trùng** — ✅ FIX: `master_system.md` đưa kiểm tra trùng thành **bước 1** (gọi `list_agents`/`list_skills` NGAY, nêu agent trùng trước khi phỏng vấn). Verify live: request trùng Bé Pháp → master cảnh báo "đã có @Bé Pháp, dùng luôn hay tạo mới" trước khi phỏng vấn.
4. **Bất đối xứng validate** — ✅ FIX: `submit_for_review` re-validate payload (đối xứng `propose_update`, fail-safe không để item invalid lên public). Regression test trong `test_governance.py`.

**Kết luận đợt 3:** trải nghiệm user các tính năng cốt lõi **đúng và mượt**; không phát sinh bug chặn. 4 điểm UX nêu trên đều đã xử lý. Tổng **121/121 unit test pass**.

---

# Đợt 4 — Verify end-to-end flow tạo agent (sau restart app)

Restart app với DB sạch để seed sync `master_system.md` mới (xác nhận prompt bước-1-dedup đã vào DB). Drive flow tạo agent thật qua master, góc nhìn user An, LLM live.

| Bước | Kết quả |
|---|---|
| Turn 1 — "tạo agent viết JD tuyển dụng" | Master gọi `list_agents`/`list_skills` **NGAY** (dedup proactive #3), xác nhận chưa có → mới phỏng vấn ✓ |
| Turn 2 — cấp đủ thông tin | Master soạn **draft skill + persona** cho user xem trước khi tạo ✓ |
| Turn 3 — xác nhận tạo | `create_skill` → `create_agent` → `attach_skill` → agent **VietJD_IT** (draft, skill gắn, slug `vietjd-it`) ✓ |
| Dùng thử ngay (owner) | JD in-domain → tạo JD đủ 3 phần ✓ |
| Scope-guard | "viết hợp đồng lao động" (off-domain) → `routed_by=escalate` → master ✓ (#4/#5 chạy trên agent vừa tạo) |
| Submit | pending + **visibility tự nâng `company`** (#3) ✓ |
| Admin approve skill + agent | active ✓ |
| Cross-user | Bình **thấy + dùng được** VietJD_IT, tạo JD thành công ✓ |

**Kết luận cuối:** toàn bộ chuỗi *mô tả → dedup-check → phỏng vấn → draft → tạo → dùng thử → escalate → submit → duyệt → chia sẻ công ty* chạy thông suốt với tất cả fix tích hợp. Platform sẵn sàng demo.

---

## Tổng kết toàn bộ (4 đợt e2e)
**6 bug + 4 quan sát UX — tất cả ĐÃ FIX & verify; 121/121 unit test pass.**
1. Boot/login crash bcrypt (CRITICAL) · 2. Visibility 500 · 3. Approve vô hình công ty · 4. Escalate loop ngược · 5. Escalate flaky (scope-guard B+C) · 6. Lỗi-stream lộ raw · 7. Preview dính newline · 8. Dedup proactive · 9. Validate đối xứng.
