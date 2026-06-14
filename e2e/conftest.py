"""Playwright UI e2e — chạy trình duyệt THẬT để bắt lớp bug UI-only mà e2e HTTP-level
không thấy (validate client, ẩn/hiện tab theo role, render, luồng modal).

CỐ Ý đặt ngoài `tests/` (testpaths=["tests"]) để `pytest` mặc định KHÔNG chạy —
bộ này cần server + browser nên chạy riêng:

    pytest e2e/                  # headless
    pytest e2e/ --headed        # xem trình duyệt chạy
    pytest e2e/ --headed --slowmo 400

Yêu cầu (đã cài 1 lần): pip install pytest-playwright && playwright install chromium
"""
import datetime
import os
import pathlib
import socket
import subprocess
import sys
import time
import tempfile
import urllib.request

import jwt
import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
VENV_PY = sys.executable  # python đang chạy pytest (trong .venv)
JWT_SECRET = "e2e-ui-secret"
ADMIN_EMAIL = "admin@e2e.local"

# email/name theo role để mint cookie phiên (bypass Google OAuth khi test UI)
_ROLE = {"user": ("an@e2e.local", "An"), "admin": (ADMIN_EMAIL, "Admin")}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_health(base: str, timeout: float = 40) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=2) as r:
                if r.status == 200:
                    return
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(0.3)
    raise RuntimeError(f"Server không lên trong {timeout}s ({last})")


@pytest.fixture(scope="session")
def server():
    """Khởi động uvicorn thật với DB tạm + JWT secret cố định + seed mặc định (Bé Pháp)."""
    port = _free_port()
    db = tempfile.mktemp(suffix="_uie2e.db")
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db}",
        "JWT_SECRET": JWT_SECRET,
        "SELF_TEST_ENABLED": "false",   # UI test không cần LLM tự test
        "GUEST_MODE": "true",
        "RATE_LIMIT_PER_MINUTE": "0",
        "ADMIN_EMAIL": ADMIN_EMAIL,     # admin_ids tự thêm email này (is_admin=True)
    }
    proc = subprocess.Popen(
        [VENV_PY, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=str(PROJECT_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_health(base)
    except Exception:
        proc.terminate()
        raise
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        proc.kill()
    for suf in ("", "-shm", "-wal"):
        try:
            os.remove(db + suf)
        except OSError:
            pass


def _mint(email: str, name: str, role: str) -> str:
    exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)
    return jwt.encode(
        {"sub": email, "email": email, "name": name, "picture": "", "role": role, "exp": exp},
        JWT_SECRET, algorithm="HS256",
    )


@pytest.fixture
def make_page(browser, server):
    """make_page(role=None|'user'|'admin') → Page đã set cookie phiên tương ứng.

    role=None → guest (không cookie). Mỗi page có context riêng (cookie cô lập).
    """
    contexts = []

    def _make(role=None):
        ctx = browser.new_context(base_url=server)
        if role:
            email, name = _ROLE[role]
            ctx.add_cookies([{"name": "session", "value": _mint(email, name, role), "url": server}])
        contexts.append(ctx)
        page = ctx.new_page()
        page.set_default_timeout(8000)
        return page

    yield _make
    for ctx in contexts:
        ctx.close()
