"""Test enforce guest_mode trong AuthMiddleware — guest_mode=False chặn guest ở route bảo vệ."""

from app.auth.middleware import AuthMiddleware


def _mw(guest_mode: bool) -> AuthMiddleware:
    # app=None: chỉ test _guest_blocked, không chạy dispatch thật.
    return AuthMiddleware(app=None, guest_mode=guest_mode)


class TestGuestBlocked:
    def test_guest_mode_on_allows_all(self):
        mw = _mw(True)
        assert not mw._guest_blocked("/chat")
        assert not mw._guest_blocked("/agents")

    def test_guest_mode_off_blocks_protected(self):
        mw = _mw(False)
        assert mw._guest_blocked("/chat")
        assert mw._guest_blocked("/agents")
        assert mw._guest_blocked("/feedback")

    def test_guest_mode_off_allows_login_paths(self):
        mw = _mw(False)
        assert not mw._guest_blocked("/auth/me")
        assert not mw._guest_blocked("/auth/login")
        assert not mw._guest_blocked("/web/index.html")
        assert not mw._guest_blocked("/health")
        assert not mw._guest_blocked("/healthz")
        assert not mw._guest_blocked("/")  # redirect → /web/
