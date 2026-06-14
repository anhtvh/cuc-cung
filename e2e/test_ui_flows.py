"""Các luồng UI quan trọng — chạy trình duyệt thật.

Tập trung vào hành vi CHỈ-CÓ-Ở-FRONTEND mà e2e HTTP-level không thấy:
- validate form client (regression bug tên agent PascalCase),
- ẩn/hiện tab theo role,
- render catalog,
- chặn guest tạo agent.

KHÔNG gọi LLM (tạo agent thật/chat đã được phủ ở e2e HTTP-level) → nhanh & ổn định.
"""
import re

from playwright.sync_api import expect


# ── Ẩn/hiện tab theo role ────────────────────────────────────────────────
def test_tabs_guest(make_page):
    page = make_page()  # guest
    page.goto("/web/", wait_until="networkidle")
    expect(page.locator('[data-tab="home"]')).to_be_visible()
    expect(page.locator('[data-tab="catalog"]')).to_be_visible()
    expect(page.locator("#myagents-tab")).to_be_hidden()
    expect(page.locator("#review-tab")).to_be_hidden()
    expect(page.locator("#stats-tab")).to_be_hidden()


def test_tabs_user(make_page):
    page = make_page("user")
    page.goto("/web/", wait_until="networkidle")
    expect(page.locator("#myagents-tab")).to_be_visible()   # đã đăng nhập
    expect(page.locator("#review-tab")).to_be_hidden()      # không phải admin
    expect(page.locator("#stats-tab")).to_be_hidden()


def test_tabs_admin(make_page):
    page = make_page("admin")
    page.goto("/web/", wait_until="networkidle")
    expect(page.locator("#myagents-tab")).to_be_visible()
    expect(page.locator("#review-tab")).to_be_visible()
    expect(page.locator("#stats-tab")).to_be_visible()


# ── Catalog render ───────────────────────────────────────────────────────
def test_catalog_renders_seeded_agent(make_page):
    page = make_page("user")
    page.goto("/web/", wait_until="networkidle")
    page.locator('[data-tab="catalog"]').click()
    catalog = page.locator("#panel-catalog")
    expect(catalog).to_have_class(re.compile(r"\bactive\b"))
    expect(catalog.get_by_text("Bé Pháp").first).to_be_visible()


# ── Quick-create: validate tên (regression bug hôm nay) ─────────────────
def test_quickcreate_accepts_unicode_name(make_page):
    """Tên có dấu + khoảng trắng ('Bé Kế Toán') PHẢI được chấp nhận (khớp backend)."""
    page = make_page("user")
    page.goto("/web/", wait_until="networkidle")
    expect(page.locator("#myagents-tab")).to_be_visible()  # auth init xong

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))

    page.evaluate("openQuickCreate()")
    expect(page.locator("#qc-modal")).to_be_visible()
    page.fill("#qc-name", "Bé Kế Toán")
    page.fill("#qc-purpose", "Hỗ trợ nghiệp vụ kế toán cơ bản cho phòng tài chính")
    page.locator("#qc-step-1").get_by_role("button", name=re.compile("Tiếp theo")).click()

    # Sang được step 2, không có alert chặn tên
    expect(page.locator("#qc-step-2")).to_have_class(re.compile(r"\bactive\b"))
    assert not dialogs, f"Tên hợp lệ nhưng bị chặn: {dialogs}"


def test_quickcreate_rejects_empty_name(make_page):
    page = make_page("user")
    page.goto("/web/", wait_until="networkidle")
    expect(page.locator("#myagents-tab")).to_be_visible()

    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))

    page.evaluate("openQuickCreate()")
    page.fill("#qc-name", "")
    page.fill("#qc-purpose", "abc")
    page.locator("#qc-step-1").get_by_role("button", name=re.compile("Tiếp theo")).click()

    expect(page.locator("#qc-step-1")).to_have_class(re.compile(r"\bactive\b"))  # vẫn ở step 1
    assert any("nhập tên" in m.lower() for m in dialogs), f"Không cảnh báo tên trống: {dialogs}"


# ── Guest bị chặn tạo agent → mời đăng nhập ─────────────────────────────
def test_guest_create_prompts_login(make_page):
    page = make_page()  # guest
    page.goto("/web/", wait_until="networkidle")
    page.evaluate("openQuickCreate()")
    expect(page.locator("#qc-modal")).to_be_hidden()    # KHÔNG mở wizard
    expect(page.locator("#auth-modal")).to_be_visible()  # mở modal đăng nhập
