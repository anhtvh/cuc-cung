"""Auth middleware — JWT cookie → request.state.user (UserInfo | GuestUser).

Cookie "session" (httpOnly, SameSite=Lax) được set bởi /auth/google/callback và /auth/login.
request.state.user_id: str — dùng bởi toàn bộ code hiện tại (backward compat).
request.state.user: UserInfo | GuestUser — dùng bởi code mới cần role/email.
"""

import logging

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

        request.state.user = user
        # backward compat: user_id = email cho logged-in, "guest" cho guest
        request.state.user_id = user.email if isinstance(user, UserInfo) else "guest"
        return await call_next(request)


# alias để main.py không cần đổi import
UserIdMiddleware = AuthMiddleware
