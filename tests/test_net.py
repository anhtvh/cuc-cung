"""Test SSRF guard dùng chung (app.tools.net) — chặn IP nội mạng kể cả qua redirect."""

import pytest

from app.tools import net


def _fake_resolver(host: str) -> str:
    """safe.test → IP public; IP literal (vd 169.254.169.254) trả về chính nó (không cần DNS)."""
    return {"safe.test": "93.184.216.34"}.get(host, host)


class TestSsrfCheck:
    def test_block_loopback(self, monkeypatch):
        monkeypatch.setattr(net._socket, "gethostbyname", _fake_resolver)
        assert net.ssrf_check("http://127.0.0.1/") is not None

    def test_block_cloud_metadata(self, monkeypatch):
        monkeypatch.setattr(net._socket, "gethostbyname", _fake_resolver)
        assert net.ssrf_check("http://169.254.169.254/latest/meta-data/") is not None

    def test_allow_public(self, monkeypatch):
        monkeypatch.setattr(net._socket, "gethostbyname", _fake_resolver)
        assert net.ssrf_check("http://safe.test/page") is None

    def test_missing_host(self):
        assert net.ssrf_check("http:///nopath") == "URL thiếu hostname"


class _FakeResp:
    def __init__(self, *, is_redirect: bool, location: str | None = None):
        self.is_redirect = is_redirect
        self.headers = {"location": location} if location else {}


class _FakeClient:
    """Mô phỏng server trả 302 về địa chỉ nội mạng — kiểm guard re-check mỗi hop."""

    def __init__(self, redirect_to: str, *args, **kwargs):
        self._redirect_to = redirect_to

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url: str):
        # URL public ban đầu → redirect tới nội mạng (giả lập tấn công SSRF qua 302).
        if url == "http://safe.test/":
            return _FakeResp(is_redirect=True, location=self._redirect_to)
        return _FakeResp(is_redirect=False)


class TestSafeGetRedirect:
    def test_redirect_to_internal_blocked(self, monkeypatch):
        monkeypatch.setattr(net._socket, "gethostbyname", _fake_resolver)
        monkeypatch.setattr(
            net.httpx, "Client",
            lambda *a, **k: _FakeClient("http://169.254.169.254/", *a, **k),
        )
        # URL gốc an toàn nhưng redirect về metadata endpoint → phải raise SsrfBlocked.
        with pytest.raises(net.SsrfBlocked):
            net.safe_get("http://safe.test/", timeout=5)

    def test_no_redirect_ok(self, monkeypatch):
        monkeypatch.setattr(net._socket, "gethostbyname", _fake_resolver)

        class _Direct(_FakeClient):
            def get(self, url):
                return _FakeResp(is_redirect=False)

        monkeypatch.setattr(net.httpx, "Client", lambda *a, **k: _Direct("", *a, **k))
        resp = net.safe_get("http://safe.test/", timeout=5)
        assert resp.is_redirect is False
