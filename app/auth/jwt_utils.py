from datetime import datetime, timedelta, timezone

import jwt

_ALGORITHM = "HS256"
_FALLBACK_SECRET = "dev-only-insecure-secret-change-in-production"


def sign(payload: dict, secret: str, expire_hours: int = 168) -> str:
    secret = secret or _FALLBACK_SECRET
    data = {**payload, "exp": datetime.now(timezone.utc) + timedelta(hours=expire_hours)}
    return jwt.encode(data, secret, algorithm=_ALGORITHM)


def verify(token: str, secret: str) -> dict | None:
    secret = secret or _FALLBACK_SECRET
    try:
        return jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
