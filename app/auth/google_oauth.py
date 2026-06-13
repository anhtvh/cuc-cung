"""Google OAuth2 Authorization Code flow."""

from urllib.parse import urlencode

import httpx

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def build_auth_url(client_id: str, redirect_uri: str, state: str = "") -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    if state:
        params["state"] = state
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    """Exchange authorization code → userinfo dict {sub, email, name, picture}."""
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(_TOKEN_URL, data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        info_resp = await client.get(
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        info_resp.raise_for_status()
        return info_resp.json()


def get_redirect_uri(request, base_url: str = "") -> str:
    """Auto-detect redirect_uri. Nếu GOOGLE_REDIRECT_BASE set → dùng cố định (tránh host-header injection)."""
    if base_url:
        return f"{base_url.rstrip('/')}/auth/google/callback"
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/auth/google/callback"
