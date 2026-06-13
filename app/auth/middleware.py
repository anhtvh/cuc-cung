"""Auth middleware — JWT cookie → request.state.user (UserInfo | GuestUser).

Cookie "session" (httpOnly, SameSite=Lax) được set bởi /auth/google/callback và /auth/login.
request.state.user_id: str — dùng bởi toàn bộ code hiện tại (backward compat).
request.state.user: UserInfo | GuestUser — dùng bởi code mới cần role/email.
request.state.is_guest: bool — True khi chưa đăng nhập.

Guest isolation: mỗi phiên guest được cấp ID riêng (guest_<hex>) qua cookie "guest_sid"
để tránh nhiều khách chia sẻ cùng bucket lịch sử/memory.
"""

import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.auth.jwt_utils import verify
from app.auth.models import GuestUser, UserInfo

log = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, jwt_secret: str = "", guest_mode: bool = True):
        super().__init__(app)
        self._secret = jwt_secret
        self._guest_mode = guest_mode

    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get("session")
        user: UserInfo | GuestUser = GuestUser()

        if token:
            payload = verify(token, self._secret)
            if payload:
                try:
                    user = UserInfo(
                        id=payload["sub"],
                        email=payload["email"],
                        name=payload.get("name", ""),
                        picture=payload.get("picture", ""),
                        role=payload.get("role", "user"),
                    )
                except (KeyError, TypeError):
                    log.warning("JWT payload malformed, treating as guest")

        is_guest = isinstance(user, GuestUser)
        new_guest_cookie: str | None = None

        if is_guest:
            guest_sid = request.cookies.get("guest_sid")
            if not guest_sid:
                guest_sid = f"guest_{secrets.token_hex(8)}"
                new_guest_cookie = guest_sid
            user_id = guest_sid
        else:
            user_id = user.email

        request.state.user = user
        request.state.user_id = user_id
        request.state.is_guest = is_guest

        response = await call_next(request)

        if new_guest_cookie:
            response.set_cookie(
                "guest_sid", new_guest_cookie,
                httponly=True, samesite="lax", max_age=86400,
            )

        return response


# alias để main.py không cần đổi import
UserIdMiddleware = AuthMiddleware
