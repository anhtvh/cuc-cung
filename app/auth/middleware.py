"""User identity (design §6): contest đọc header X-User-Id (user switcher trên UI);
production swap file này sang OIDC/SSO — user_id đã đi qua MỘT chỗ duy nhất.

I-02 SECURITY NOTE: X-User-Id có thể bị giả mạo bởi bất kỳ client nào (kể cả
đặt "admin" để access trang Review). Đây là trade-off cố ý cho môi trường contest
internal — production PHẢI swap sang OIDC/SSO trước khi expose ra internet.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

DEFAULT_USER = "anonymous"


class UserIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user_id = request.headers.get("X-User-Id", DEFAULT_USER).strip() or DEFAULT_USER
        return await call_next(request)
