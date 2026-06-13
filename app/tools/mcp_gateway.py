"""AgentBase MCP Gateway provider (Flow 5) — kết nối MCP server thật.

Cách dùng:
  1. Tạo gateway trên AgentBase (xem /agentbase-gateway skill).
  2. Đợi state=ACTIVE, lấy `endpoint` từ GET /gateway/api/v1/gateways/<name>.
  3. Set env: MCP_GATEWAY_ENDPOINT=<endpoint>, MCP_GATEWAY_TARGET=<target-name>.
  4. App tự wire McpGatewayProvider vào catalog khi endpoint được cấu hình.

Inbound auth: IAM Bearer token (VNG Cloud client_credentials).
  - Token lấy từ GREENNODE_CLIENT_ID + GREENNODE_CLIENT_SECRET (đã có trong .env).

MCP JSON-RPC transport: POST <endpoint> với body JSON-RPC 2.0.
  - tools/list → trả về list ToolDef (lọc theo target_name nếu có).
  - tools/call → proxy qua gateway, gateway gắn outbound auth + forward upstream.

Multi-target: gateway có thể có nhiều target. Tool trên wire có dạng
  <target>__<tool> (policy vocab của AgentBase). McpGatewayProvider wrap 1 target:
  strip prefix khi list, gắn lại khi call.
"""

import json
import logging
import threading
import time
from typing import Any

import httpx

from app.llm.base import ToolDef

log = logging.getLogger(__name__)

_IAM_TOKEN_URL = "https://iam.api.vngcloud.vn/accounts-api/v2/auth/token"
_TOKEN_SAFETY_MARGIN = 60  # refresh sớm 60s trước khi hết hạn


class IamTokenProvider:
    """Client-credentials flow → IAM Bearer token, cache thread-safe.

    Dùng chung 1 instance cho mọi McpGatewayProvider trong process.
    """

    def __init__(self, client_id: str, client_secret: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._token: str = ""
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        # I-09: check dưới lock — nếu cần refresh thì release trước khi gọi HTTP
        # (không block mọi thread trong khi 1 thread đang fetch)
        with self._lock:
            if self._token and time.time() < self._expires_at - _TOKEN_SAFETY_MARGIN:
                return self._token
        # Fetch ngoài lock — nhiều thread có thể race nhưng chỉ write vào _token/_expires_at
        resp = httpx.post(
            _IAM_TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        with self._lock:
            self._token = data["access_token"]
            self._expires_at = time.time() + data.get("expires_in", 3600)
        log.info("iam_token: token mới, hết hạn sau %ds", data.get("expires_in", 3600))
        return self._token


class McpGatewayProvider:
    """Wrap 1 target trên AgentBase MCP Gateway → ToolProvider interface chuẩn.

    gateway_endpoint: URL từ GatewayResponse.endpoint (state=ACTIVE).
    target_name: tên target trên gateway (vd "web-search", "hr").
      Nếu gateway chỉ có 1 target và tools/list trả tên trần → để None.
    call_timeout: giây; nên ≤ tool_timeout_seconds trong catalog (mặc định 15s).
    """

    is_mock = False

    _TOOLS_TTL = 60  # giây

    def __init__(
        self,
        server_name: str,
        gateway_endpoint: str,
        token_provider: IamTokenProvider,
        target_name: str | None = None,
        call_timeout: int = 14,
    ):
        self.server_name = server_name
        self._endpoint = gateway_endpoint.rstrip("/")
        self._token = token_provider
        self._target = target_name or None
        self._timeout = call_timeout
        # L-06: cache list_tools — không gọi HTTP mỗi request
        self._tools_cache: list[ToolDef] = []
        self._tools_cache_at: float = 0.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _rpc(self, method: str, params: dict | None = None) -> Any:
        payload: dict = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        resp = httpx.post(
            self._endpoint,
            headers=self._headers(),
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            err = body["error"]
            raise RuntimeError(f"MCP error {err.get('code')}: {err.get('message')}")
        return body.get("result")

    # ------------------------------------------------------------------
    # ToolProvider protocol
    # ------------------------------------------------------------------

    def list_tools(self) -> list[ToolDef]:
        # L-06: trả cache nếu còn trong TTL (60s) — tránh gọi HTTP mỗi request chat
        if self._tools_cache and time.time() - self._tools_cache_at < self._TOOLS_TTL:
            return self._tools_cache
        try:
            result = self._rpc("tools/list")
        except Exception:
            log.exception("mcp_gateway: list_tools thất bại (server=%s)", self.server_name)
            return self._tools_cache  # trả cache cũ nếu refresh fail

        raw: list[dict] = (result or {}).get("tools", [])
        out: list[ToolDef] = []
        prefix = f"{self._target}__" if self._target else ""

        for t in raw:
            raw_name: str = t.get("name", "")
            if prefix:
                if not raw_name.startswith(prefix):
                    continue
                display_name = raw_name[len(prefix):]
            else:
                display_name = raw_name

            out.append(
                ToolDef(
                    name=display_name,
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema") or {"type": "object", "properties": {}},
                )
            )
        self._tools_cache = out
        self._tools_cache_at = time.time()
        log.info("mcp_gateway: list_tools server=%s → %d tool(s) (cache miss)", self.server_name, len(out))
        return out

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        # Gắn target prefix trở lại → gateway routing đúng target
        wire_name = f"{self._target}__{tool_name}" if self._target else tool_name
        result = self._rpc("tools/call", {"name": wire_name, "arguments": args})

        if result is None:
            return ""

        # MCP tools/call trả {"content": [{"type":"text","text":"..."}], "isError": false}
        if result.get("isError"):
            raise RuntimeError(f"tool {wire_name} trả lỗi từ upstream: {result}")

        content: list[dict] = result.get("content", [])
        parts = [c["text"] for c in content if c.get("type") == "text" and c.get("text")]
        return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
