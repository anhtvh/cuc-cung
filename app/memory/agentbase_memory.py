"""AgentBase Memory module (Flow 6) — short-term history + long-term semantic.

Bật bằng env MEMORY_BACKEND=agentbase (design §7, swap ngày 14/06).

Isolation guarantee — không có đường nào để user B lấy data của user A:
- actor_id  = user_id       (từ interface param, không bao giờ đoán)
- session_id = "{user_id}__{agent_name}"  (scoped per user per agent)
- namespace  = "/strategies/{strategy_id}/actors/{user_id}"  (long-term records)

Tham chiếu: memory-ops.md, advanced-operations.md trong agentbase-memory skill.
"""

import json
import logging
import threading
import time
from base64 import b64decode

import httpx

from app.core.models import ChatMessage

log = logging.getLogger(__name__)

IAM_TOKEN_URL = "https://iam.api.vngcloud.vn/accounts-api/v2/auth/token"
MEMORY_BASE = "https://agentbase.api.vngcloud.vn/memory"
TOKEN_SAFETY_MARGIN = 60  # refresh token sớm 60s trước khi hết hạn


class _TokenCache:
    def __init__(self) -> None:
        self._token: str = ""
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def is_valid(self) -> bool:
        return bool(self._token) and time.time() < (self._expires_at - TOKEN_SAFETY_MARGIN)

    def set(self, token: str, expires_at: float) -> None:
        self._token = token
        self._expires_at = expires_at

    @property
    def token(self) -> str:
        return self._token

    @property
    def lock(self) -> threading.Lock:
        return self._lock


def _jwt_exp(token: str) -> float:
    """Lấy exp từ JWT payload (không verify signature)."""
    try:
        payload_b64 = token.split(".")[1]
        pad = 4 - len(payload_b64) % 4
        if pad != 4:
            payload_b64 += "=" * pad
        payload = json.loads(b64decode(payload_b64.replace("-", "+").replace("_", "/")))
        return float(payload.get("exp", 0))
    except Exception:
        return 0.0


class AgentBaseMemory:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        store_id: str,
        strategy_id: str = "",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._store_id = store_id
        # strategy_id dùng cho long-term semantic search (search()).
        # Nếu rỗng → search() trả rỗng thay vì lỗi (không chặn flow).
        self._strategy_id = strategy_id
        self._cache = _TokenCache()
        self._http = httpx.Client(timeout=10.0)

    # --- IAM auth ---

    def _get_token(self) -> str:
        with self._cache.lock:
            if self._cache.is_valid():
                return self._cache.token
            resp = self._http.post(
                IAM_TOKEN_URL,
                auth=(self._client_id, self._client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            token = resp.json()["access_token"]
            exp = _jwt_exp(token) or (time.time() + 3600)
            self._cache.set(token, exp)
            return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    # --- Isolation helpers ---

    @staticmethod
    def _session_id(user_id: str, agent_name: str) -> str:
        # Dấu __ không xuất hiện trong naming convention agent (design §3.2).
        # Session khác nhau giữa (user_A, agent_X) và (user_B, agent_X).
        return f"{user_id}__{agent_name}"

    def _events_url(self, user_id: str, session_id: str) -> str:
        # actor_id = user_id — không bao giờ dùng giá trị mặc định hay global.
        return f"{MEMORY_BASE}/memories/{self._store_id}/actors/{user_id}/sessions/{session_id}/events"

    def _namespace(self, user_id: str) -> str:
        # Namespace scoped strictly to user — user B không thể tìm record của user A.
        return f"/strategies/{self._strategy_id}/actors/{user_id}"

    # --- Memory interface ---

    def get_history(self, user_id: str, agent_name: str, limit: int = 20) -> list[ChatMessage]:
        session_id = self._session_id(user_id, agent_name)
        url = self._events_url(user_id, session_id)
        try:
            resp = self._http.get(url, headers=self._headers(), params={"page": 1, "size": limit})
            resp.raise_for_status()
            # API trả newest-first (advanced-operations.md) — reverse về chronological.
            events = list(reversed(resp.json().get("listData", [])))
            result: list[ChatMessage] = []
            for ev in events:
                payload = ev.get("payload", {})
                role = payload.get("role") or ev.get("role", "")
                content = payload.get("message") or payload.get("content") or ev.get("content", "")
                if role and content:
                    result.append(ChatMessage(role=role, content=str(content)))
            return result
        except Exception:
            log.exception("AgentBaseMemory.get_history lỗi (user=%s, agent=%s)", user_id, agent_name)
            return []

    def append(self, user_id: str, agent_name: str, role: str, content: str) -> None:
        session_id = self._session_id(user_id, agent_name)
        url = self._events_url(user_id, session_id)
        body = {
            "payload": {
                "type": "conversational",
                "role": role,
                "message": content,
            }
        }
        # I-08: retry 1 lần với backoff ngắn tránh mất message do HTTP transient error
        for attempt in range(2):
            try:
                resp = self._http.post(url, headers=self._headers(), json=body)
                resp.raise_for_status()
                return
            except Exception:
                if attempt == 0:
                    log.warning("AgentBaseMemory.append thất bại lần 1, thử lại (user=%s, agent=%s)", user_id, agent_name)
                    time.sleep(0.5)
                else:
                    log.exception("AgentBaseMemory.append lỗi sau 2 lần (user=%s, agent=%s)", user_id, agent_name)

    def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        if not self._strategy_id:
            # strategy_id chưa cấu hình → bỏ qua semantic search, không chặn flow
            return []
        namespace = self._namespace(user_id)
        url = f"{MEMORY_BASE}/memories/{self._store_id}/memory-records:search"
        body = {"query": query, "limit": limit}
        try:
            resp = self._http.post(
                url, headers=self._headers(), params={"namespace": namespace}, json=body
            )
            resp.raise_for_status()
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", data.get("listData", []))
            return [str(r.get("memory", "")) for r in records if r.get("memory")]
        except Exception:
            log.exception("AgentBaseMemory.search lỗi (user=%s)", user_id)
            return []