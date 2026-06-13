"""Auth endpoints: Google OAuth2 + admin password login."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.api.deps import Container, get_container
from app.auth.google_oauth import build_auth_url, exchange_code, get_redirect_uri
from app.auth.jwt_utils import sign
from app.auth.models import GuestUser, UserInfo
from app.auth.password_auth import verify_password

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE = "session"
_COOKIE_OPTS = dict(httponly=True, samesite="lax", secure=False)  # secure=True khi HTTPS


def _set_session(response: Response, user: UserInfo, settings) -> None:
    token = sign(
        {"sub": user.id, "email": user.email, "name": user.name, "picture": user.picture, "role": user.role},
        settings.jwt_secret,
        settings.jwt_expire_hours,
    )
    # secure=True khi production HTTPS (AgentBase serve HTTPS)
    is_secure = not settings.database_url.startswith("sqlite:///")
    response.set_cookie(_COOKIE, token, httponly=True, samesite="lax", secure=is_secure, max_age=settings.jwt_expire_hours * 3600)


@router.get("/google")
def google_login(request: Request, c: Container = Depends(get_container)):
    if not c.settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth chưa được cấu hình (GOOGLE_CLIENT_ID trống)")
    redirect_uri = get_redirect_uri(request)
    url = build_auth_url(c.settings.google_client_id, redirect_uri)
    return RedirectResponse(url)


@router.get("/google/callback")
async def google_callback(
    code: str,
    request: Request,
    c: Container = Depends(get_container),
):
    if not c.settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google OAuth chưa được cấu hình")

    redirect_uri = get_redirect_uri(request)
    try:
        info = await exchange_code(code, c.settings.google_client_id, c.settings.google_client_secret, redirect_uri)
    except Exception as e:
        log.error("Google OAuth exchange failed: %s", e)
        raise HTTPException(status_code=400, detail="Không thể xác thực với Google — thử lại") from e

    row = c.user_repo.upsert_google(
        sub=info.get("sub", info.get("id", "")),
        email=info["email"],
        name=info.get("name", ""),
        picture=info.get("picture", ""),
    )
    user = UserInfo(id=row.id, email=row.email, name=row.name or "", picture=row.picture or "", role=row.role)

    response = RedirectResponse("/web/", status_code=302)
    _set_session(response, user, c.settings)
    return response


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def admin_login(body: LoginRequest, c: Container = Depends(get_container)):
    if not c.settings.admin_email:
        raise HTTPException(status_code=501, detail="Admin chưa được cấu hình")

    row = c.user_repo.get_by_email(body.email)
    if not row or row.role != "admin" or not row.hashed_password:
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")
    if not verify_password(body.password, row.hashed_password):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")

    user = UserInfo(id=row.id, email=row.email, name=row.name or "Admin", picture="", role="admin")
    response_data = {"ok": True, "email": user.email, "name": user.name, "role": user.role}

    from fastapi.responses import JSONResponse
    response = JSONResponse(response_data)
    _set_session(response, user, c.settings)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/web/", status_code=302)
    response.delete_cookie(_COOKIE)
    return response


@router.get("/me")
def me(request: Request, c: Container = Depends(get_container)):
    user = request.state.user
    if isinstance(user, GuestUser):
        return {"role": "guest", "guest_mode": c.settings.guest_mode}
    return {
        "role": user.role,
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "guest_mode": c.settings.guest_mode,
    }
