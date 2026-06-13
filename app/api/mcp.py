"""MCP server endpoint (JSON-RPC 2.0) — expose web-search tools theo MCP spec.

AgentBase Gateway trỏ vào POST /mcp này. Khi MCP_GATEWAY_ENDPOINT được set,
McpGatewayProvider gọi gateway → gateway forward vào đây → WebSearchProvider thực thi.

Bảo vệ: nếu MCP_GATEWAY_SECRET được set, yêu cầu header X-Mcp-Secret khớp.
Để trống = cho phép local dev không cần secret (không deploy public).
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import Container, get_container

log = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

_JSONRPC_VERSION = "2.0"


def _ok(id_: int | str, result: object) -> dict:
    return {"jsonrpc": _JSONRPC_VERSION, "id": id_, "result": result}


def _err(id_: int | str, code: int, message: str) -> dict:
    return {"jsonrpc": _JSONRPC_VERSION, "id": id_, "error": {"code": code, "message": message}}


@router.post("/mcp")
async def mcp_handler(
    request: Request,
    c: Container = Depends(get_container),
) -> JSONResponse:
    """JSON-RPC 2.0 handler — hỗ trợ tools/list và tools/call."""
    secret = c.settings.mcp_gateway_secret
    if secret and request.headers.get("X-Mcp-Secret", "") != secret:
        return JSONResponse({"error": "Unauthorized"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=200)

    method = body.get("method", "")
    id_ = body.get("id", 1)
    params = body.get("params") or {}

    provider = c.web_search_provider
    if provider is None:
        return JSONResponse(_err(id_, -32603, "web_search_provider không khả dụng"), status_code=200)

    if method == "tools/list":
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema or {"type": "object", "properties": {}},
            }
            for t in provider.list_tools()
        ]
        return JSONResponse(_ok(id_, {"tools": tools}))

    if method == "tools/call":
        tool_name: str = params.get("name", "")
        arguments: dict = params.get("arguments") or {}
        try:
            text = provider.call(tool_name, arguments)
        except ValueError as e:
            return JSONResponse(_ok(id_, {
                "content": [{"type": "text", "text": str(e)}],
                "isError": True,
            }))
        except Exception as e:  # noqa: BLE001
            log.exception("mcp tools/call lỗi tool=%s", tool_name)
            return JSONResponse(_ok(id_, {
                "content": [{"type": "text", "text": f"lỗi hệ thống: {e}"}],
                "isError": True,
            }))
        return JSONResponse(_ok(id_, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }))

    # Method không hỗ trợ
    log.warning("mcp: method không hỗ trợ: %s", method)
    return JSONResponse(_err(id_, -32601, f"Method not found: {method}"), status_code=200)
