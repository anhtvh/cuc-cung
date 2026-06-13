"""ToolProvider protocol — hình dạng MCP `server.tool_name` (Flow 5).

Mock server cùng interface với MCP client thật → cắm AgentBase MCP Gateway
không phải sửa flow.

Tên trên wire: API Anthropic/OpenAI chỉ cho phép [a-zA-Z0-9_-] trong tên tool
→ dấu chấm `server.tool` được mã hoá thành `server__tool` khi truyền vào model,
hiển thị dạng chấm ở catalog/UI.
"""

from typing import Any, Protocol

from app.llm.base import ToolDef

WIRE_SEP = "__"


def to_wire(server: str, tool: str) -> str:
    return f"{server}{WIRE_SEP}{tool}"


def to_display(wire_name: str) -> str:
    server, _, tool = wire_name.partition(WIRE_SEP)
    return f"{server}.{tool}" if tool else wire_name


class ToolProvider(Protocol):
    server_name: str
    is_mock: bool  # minh bạch trong video/README + trang Review (Flow 2b)

    def list_tools(self) -> list[ToolDef]:
        """ToolDef.name là tên TRẦN (chưa prefix server)."""
        ...

    def call(self, tool_name: str, args: dict[str, Any]) -> str: ...
