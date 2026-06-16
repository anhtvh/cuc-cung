"""Tool catalog (Flow 5): registry server → provider.

Agent con khai báo connectors=["contract-db"] → engine chỉ truyền tool của
server đó vào model. Code tool do dev viết sẵn — master KHÔNG sinh code (§3.2).
"""

import concurrent.futures
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.llm.base import ToolDef, ToolResult
from app.tools.base import ToolProvider, to_display, to_wire

log = logging.getLogger(__name__)


class SystemProvider:
    """Server `system` — tool thật, luôn được cấp cho mọi agent."""

    server_name = "system"
    is_mock = False

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="get_current_date",
                description="Trả về ngày hiện tại (ISO, múi giờ server).",
            )
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "get_current_date":
            # B-07: trả ngày theo múi giờ Việt Nam UTC+7, không dùng server UTC
            tz_vn = timezone(timedelta(hours=7))
            return datetime.now(tz_vn).date().isoformat()
        raise ValueError(f"tool không tồn tại: {tool_name}")


class ToolCatalog:
    def __init__(self, providers: list[ToolProvider], tool_timeout_seconds: int = 15):
        self._providers: dict[str, ToolProvider] = {p.server_name: p for p in providers}
        self._timeout = tool_timeout_seconds
        # L-05: dùng 1 shared executor thay vì tạo mới mỗi tool call (giảm thread create/teardown)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def has_server(self, server: str) -> bool:
        return server in self._providers

    def server_names(self) -> list[str]:
        return list(self._providers)

    def describe(self, servers: list[str] | None = None) -> list[dict[str, Any]]:
        """Cho trang Review/Catalog: từng server + tool cụ thể, kèm nhãn mock/thật."""
        names = servers if servers is not None else list(self._providers)
        out = []
        for s in names:
            p = self._providers.get(s)
            if p is None:
                continue
            out.append(
                {
                    "server": s,
                    "is_mock": p.is_mock,
                    "tools": [
                        {"name": to_display(to_wire(s, t.name)), "description": t.description}
                        for t in p.list_tools()
                    ],
                }
            )
        return out

    def tools_for(self, connectors: list[str]) -> list[ToolDef]:
        """ToolDef với tên wire `server__tool` để truyền vào model."""
        defs: list[ToolDef] = []
        for server in connectors:
            p = self._providers.get(server)
            if p is None:
                log.warning("connector không có trong catalog, bỏ qua: %s", server)
                continue
            for t in p.list_tools():
                defs.append(
                    ToolDef(
                        name=to_wire(server, t.name),
                        description=t.description,
                        input_schema=t.input_schema,
                        stateful=t.stateful,  # giữ cờ stateful khi đổi sang tên wire (engine dùng để inject _conversation_id)
                    )
                )
        return defs

    def execute(self, wire_name: str, args: dict[str, Any]) -> ToolResult:
        """Thực thi tool có timeout (an toàn Flow 3); lỗi → is_error cho model tự xử lý."""
        server, sep, tool = wire_name.partition("__")
        provider = self._providers.get(server) if sep else None
        if provider is None:
            return ToolResult(content=f"tool không tồn tại: {wire_name}", is_error=True)
        try:
            future = self._executor.submit(provider.call, tool, args)
            return ToolResult(content=future.result(timeout=self._timeout))
        except concurrent.futures.TimeoutError:
            log.error("tool %s timeout sau %ds", wire_name, self._timeout)
            return ToolResult(content=f"tool {to_display(wire_name)} timeout", is_error=True)
        except Exception as e:  # noqa: BLE001 — mọi lỗi tool đều trả về model (Flow 3 bước 5)
            log.exception("tool %s lỗi", wire_name)
            return ToolResult(content=str(e), is_error=True)
