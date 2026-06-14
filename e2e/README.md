# UI e2e (Playwright)

Bộ test trình duyệt THẬT cho lớp bug **chỉ-có-ở-frontend** mà e2e HTTP-level không thấy:
validate form client, ẩn/hiện tab theo role, render catalog, luồng modal, chặn guest.

Cố ý đặt **ngoài `tests/`** nên `pytest` mặc định (`testpaths=["tests"]`) KHÔNG chạy bộ này —
nó cần khởi động server + tải browser, chậm hơn unit test.

## Cài (1 lần)
```bash
pip install -e ".[e2e]"     # hoặc: pip install pytest-playwright playwright
playwright install chromium
```

## Chạy
```bash
pytest e2e/                       # headless (CI)
pytest e2e/ --headed              # xem trình duyệt chạy
pytest e2e/ --headed --slowmo 400 # chạy chậm để quan sát
pytest e2e/ -k quickcreate        # lọc test
```

Conftest tự khởi động `uvicorn` (DB tạm, JWT secret cố định, seed mặc định) trên cổng
ngẫu nhiên và tắt sau khi xong — **không cần** server chạy sẵn. Đăng nhập theo role được
giả lập bằng cookie JWT (bypass Google OAuth), không gọi LLM nên nhanh & ổn định.

## Đang phủ
- Ẩn/hiện tab theo role: guest / user / admin (`#myagents-tab`, `#review-tab`, `#stats-tab`)
- Render catalog (agent seed hiển thị)
- Quick-create validate tên: chấp nhận Unicode + khoảng trắng (regression bug PascalCase), chặn tên trống
- Guest bấm tạo agent → mời đăng nhập, không mở wizard

## Mở rộng gợi ý
- Modal Sửa agent (đổi visibility) — verify UI không lỗi
- Chuyển tab giữ trạng thái, sidebar history render
- Upload chip hiển thị khi đính kèm file
