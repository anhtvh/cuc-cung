# Review UI/UX — Agent Hub (Cục Cưng)

**Ngày:** 2026-06-14 · **Phạm vi:** toàn bộ `web/` (index.html + app.js + style.css) đối chiếu backend.
**Mục tiêu:** kiểm UI có thể hiện đúng concept *"giải đáp mọi thắc mắc → tạo agent → dùng → quản lý nhanh qua bước đơn giản → lan toả (public)"*; tìm điểm cải thiện UX; đảm bảo FE↔BE nhất quán.
**Trạng thái:** chỉ phân tích — **chưa sửa code**, chờ anh chọn hạng mục để action.

---

## 0. Kết luận nhanh
Nền tảng UX **vững**: 6 tab rõ ràng, 2 lối tạo agent (wizard + chat), routing tự động, empty/loading/typing states, quản lý vòng đời agent đầy đủ, FE↔BE **khớp 100% endpoint** (không có call mồ côi). Concept "hỏi-đáp / tạo / dùng / quản lý" thể hiện tốt. Điểm yếu chính: **trụ cột "lan toả (public)" bị thể hiện mờ**, vài chỗ **trùng lặp & thiếu nhất quán nhỏ**, và một **mâu thuẫn FE↔hành vi master** ở wizard. Không có lỗi chặn.

---

## 1. Đối chiếu concept (5 trụ cột)

| Trụ cột | Thể hiện ở đâu | Đánh giá |
|---|---|---|
| **Giải đáp mọi thắc mắc** | Hero "Hỏi gì cũng có" + path-card "Hỏi bất cứ thứ gì" + ô chat "Mô tả nhu cầu…" + auto-routing/classify | ✅ Mạnh, rõ ngay từ home |
| **Tạo agent qua bước đơn giản** | Path-card "Đặt hàng trợ lý riêng" → wizard 3 bước (Mô tả→Quy trình→Xác nhận); hoặc chat với Cục cưng | ✅ Tốt — wizard có step-bar trực quan |
| **Sử dụng** | Kho Agent, "Trợ lý có sẵn" ở home (lọc domain + search), @mention, click card → chat | ✅ Tốt, nhiều lối vào |
| **Quản lý nhanh** | Tab "Của tôi": badge trạng thái (Nháp/Chờ duyệt/Đang dùng/Từ chối) + nút Sửa/Gửi duyệt/Hủy/Gửi lại/Xóa/Chat + review_note | ✅ Đầy đủ, hành động theo trạng thái đúng |
| **Lan toả (public)** | submit→approve→company; catalog hiện agent company; "🔥 Phổ biến" theo `calls` | ⚠️ **Mờ** — xem C1 |

---

## 2. Audit nhất quán FE ↔ BE

**Endpoint:** mọi `fetch()` trong app.js đều khớp route backend (auth/agents/skills/review/feedback/history/chat/upload). **Không có call mồ côi, không endpoint thừa.** ✅

| Khía cạnh | Trạng thái |
|---|---|
| Validate tên agent (client vs `AGENT_NAME_RE`) | ✅ Đã đồng bộ (fix gần đây) |
| File upload accept (chat: txt/md/pdf/docx/png/jpg; wizard: txt/md/pdf/docx) | ✅ Khớp backend (`/upload` + ảnh không vào skill wizard có chủ đích) |
| Field map edit modal (tagline/description/system_prompt/domain/visibility) ↔ `AgentEditRequest` | ✅ Khớp |
| Persona ≥200 ký tự (validate khi sửa) | ⚠️ Modal không báo trước min-length → xem K4 |
| Hành vi master sau wizard ("không cần hỏi thêm") ↔ master_system.md (luôn dedup + draft + xác nhận) | ⚠️ **Mâu thuẫn** → xem K1 |
| Error giữa stream | ✅ Đã sanitize (fix gần đây) |

---

## 3. Phát hiện UX (theo mức ưu tiên)

### 🔴 P1 — nên cải thiện trước demo
- **C1 — Trụ cột "lan toả" thể hiện mờ.** Vòng lặp *tạo → chia sẻ → cả công ty dùng* là điểm khác biệt cốt lõi nhưng UI chỉ gói trong nút "Gửi duyệt". Thiếu *social proof / tác động*: không hiện "ai tạo" (`created_by` có trong data nhưng không render), không nhấn "agent của bạn đang được N người dùng", không có khoảnh khắc "chúc mừng — agent đã lan toả cả công ty" sau khi approve.
  → **Đề xuất:** hiện maker ("tạo bởi An") + lượt dùng nổi bật trên card; toast/badge "Đã chia sẻ toàn công ty 🎉" khi agent thành company; mục "Agent của team" tôn vinh agent phổ biến.
- **K1 — Wizard mâu thuẫn hành vi master.** `executeQuickCreate` gửi message *"…không cần hỏi thêm, thực hiện ngay"* (app.js:2046) nhưng master_system.md mới yêu cầu **luôn** dedup-check + soạn draft + chờ user xác nhận. Hệ quả: master hoặc bỏ qua quy tắc của chính nó, hoặc vẫn hỏi lại → user (vừa điền wizard) thấy "sao còn hỏi nữa". 
  → **Đề xuất:** đổi câu wizard thành *"…dưới đây là thông tin, em kiểm tra trùng lặp rồi xác nhận với anh/chị trước khi tạo"*, và set kỳ vọng ở step 3 ("Cục cưng sẽ xác nhận trong Chat trước khi tạo").
- **K2 — "Agent của tôi" hiển thị 2 nơi.** Tab "Của tôi" (`#panel-myagents`) **và** section trong Catalog (`#my-agents-section`) — trùng lặp, dễ rối, 2 code path render khác nhau.
  → **Đề xuất:** giữ 1 nơi (tab "Của tôi") hoặc làm rõ vai trò (catalog = duyệt/dùng; "Của tôi" = quản lý).
- **I1 — Dùng `alert()`/`confirm()` dù đã có `showToast`.** Validate tên, submit, xóa đều dùng native dialog (xấu, chặn UI, lệch tông). 
  → **Đề xuất:** thay bằng toast + confirm-modal nhất quán.
- **D1 — Demo trống domain.** Seed chỉ có Bé Pháp → các tab domain (finance/sales/hr/ops/it) ở home đa phần rỗng → cảm giác sản phẩm trống lúc demo.
  → **Đề xuất:** seed thêm 4–6 agent demo đa domain (chỉ cho demo).
- **R1 — Cần verify responsive thật.** Có 5 `@media` (≤680/600/500) nhưng chat có sidebar — cần kiểm trên mobile (sidebar có collapse không, nav có tràn không). Có thể thêm test Playwright viewport mobile.

### 🟡 P2 — nice-to-have / đánh bóng
- **C2 — Lệch tông thương hiệu:** icon 🏭 (nhà máy) cạnh tên "Cục cưng" (dễ thương) + hero thân thiện. → cân nhắc icon thân thiện hơn (✨/🐣/🤖).
- **K3 — Thuật ngữ lẫn lộn:** "agent" vs "trợ lý"; "Kho Agent" vs "Trợ lý có sẵn" cho cùng concept. → thống nhất 1 cặp từ.
- **K4 — Edit persona không hint min-length:** rút gọn <200 ký tự → 409 khó hiểu. → thêm bộ đếm ký tự + hint "tối thiểu 200".
- **I2 — Accessibility:** nút icon-only (＋ ↑ ✕ 📎) thiếu `aria-label` → khó cho screen reader.
- **I3 — Thiếu skeleton/spinner** khi load catalog/myagents/stats → nháy trống 1 nhịp.
- **I4 — Badge "Đang dùng" cho agent public+private (tạm ẩn)** gây hiểu nhầm (thực ra không ai khác thấy). → badge riêng "Đang ẩn".

---

## 4. Backlog đề xuất (anh chọn để tôi action)

| # | Hạng mục | Loại | Ước lượng |
|---|---|---|---|
| 1 | K1 — sửa message wizard + kỳ vọng step 3 | FE copy | Nhỏ |
| 2 | I1 — thay alert/confirm bằng toast/modal | FE | Vừa |
| 3 | C1 — hiện maker + lượt dùng + mừng "đã lan toả" | FE | Vừa |
| 4 | K2 — hợp nhất "Agent của tôi" 1 nơi | FE | Nhỏ–Vừa |
| 5 | D1 — seed agent demo đa domain | seed | Nhỏ |
| 6 | K4 — đếm ký tự persona ở edit modal | FE | Nhỏ |
| 7 | I4 — badge "Đang ẩn" | FE | Nhỏ |
| 8 | C2/K3 — thống nhất icon + thuật ngữ | FE copy | Nhỏ |
| 9 | I2/I3 — aria-label + skeleton | FE | Vừa |
| 10 | R1 — verify responsive (+ test Playwright viewport) | QA | Vừa |

---

## 5. Điểm đã làm tốt (giữ nguyên)
- Home 2-path rõ ràng (Hỏi / Tạo) — onboarding trực quan.
- Wizard 3 bước có step-bar; hand-off mượt sang chat (auto-send).
- Routing đa lối: click card / @mention / mô tả tự nhiên → classify.
- Quản lý vòng đời agent đầy đủ, nút theo trạng thái chính xác, hiện review_note khi bị từ chối.
- Empty states thân thiện ở mọi list ("Không có gì chờ duyệt 🎉"…); typing indicator có nhãn xoay.
- FE↔BE khớp endpoint hoàn toàn; có cache-busting; guest isolation rõ.
- Stats có insight thật (token theo agent, tỉ lệ hài lòng từ feedback).

---

## 6. Cập nhật — đã xử lý toàn bộ P1 (2026-06-14)

| Mục | Đã làm | File |
|---|---|---|
| **C1** Lan toả | Maker attribution + lượt dùng trên card catalog; dòng trạng thái chia sẻ ở "Của tôi" (🔒 riêng / ⏳ chờ duyệt / ✅ cả công ty / 🙈 đang ẩn); toast "đã gửi duyệt 🎉" | app.js, style.css |
| **K1** Wizard↔master | Đổi message wizard sang "kiểm tra trùng + soạn nháp + xác nhận trước khi tạo"; step 3 nêu rõ "xác nhận trong Chat" | app.js, index.html |
| **K2** Gộp "Của tôi" | Bỏ section trùng khỏi Catalog (comment lại), quản lý gói gọn ở tab "Của tôi" | index.html, app.js |
| **I1** Toast/confirm | Thay toàn bộ `alert()`/`confirm()` bằng `showToast` + `showConfirm` (confirm-modal mới) | app.js, index.html, style.css |
| **D1** Seed demo | Thêm 4 agent demo (Tài chính/Sales/Nhân sự/IT) đa domain | seeds/demo_data.py |
| **R1** Responsive | Phát hiện tràn ngang mobile (header 591px@390) → vá: nav co/cuộn, ẩn brand-sub; thêm test viewport | style.css, e2e/ |

**Kiểm chứng:** 8/8 Playwright UI e2e pass (gồm test mobile-viewport + toast), 121/121 unit pass.
**P2 còn lại** (chưa làm, chờ anh): C2 icon brand, K3 thuật ngữ, K4 đếm ký tự persona, I2 aria-label, I3 skeleton.
