"""Mock MCP server `contract-db` (Flow 5) — trả hợp đồng mẫu cho demo.

Minh bạch: đây là mock; production cắm server thật qua AgentBase MCP Gateway.
"""

import json
from typing import Any

from app.llm.base import ToolDef, ToolResult

_SAMPLE_CONTRACTS = [
    {
        "id": "HD-2026-001",
        "title": "Hợp đồng cung cấp dịch vụ cloud — VNG Cloud",
        "partner": "VNG Cloud",
        "value_vnd": 1_200_000_000,
        "term": "12 tháng, gia hạn tự động",
        "payment": "thanh toán quý, net 30",
        "liability_cap": "100% giá trị hợp đồng",
        "termination": "báo trước 60 ngày",
    },
    {
        "id": "HD-2026-002",
        "title": "Hợp đồng thuê văn phòng — Saigon Centre",
        "partner": "Keppel Land",
        "value_vnd": 3_600_000_000,
        "term": "36 tháng",
        "payment": "thanh toán tháng, đặt cọc 3 tháng",
        "liability_cap": "không quy định",
        "termination": "không được đơn phương chấm dứt trong 24 tháng đầu",
    },
    {
        "id": "HD-2026-003",
        "title": "Hợp đồng outsource phát triển phần mềm",
        "partner": "FPT Software",
        "value_vnd": 850_000_000,
        "term": "6 tháng theo milestone",
        "payment": "theo milestone, giữ lại 10% đến nghiệm thu",
        "liability_cap": "50% giá trị hợp đồng",
        "termination": "báo trước 30 ngày, đền bù milestone dở dang",
    },
]


class ContractDbProvider:
    server_name = "contract-db"
    is_mock = True

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="search_contracts",
                description="Tìm hợp đồng trong kho theo từ khóa (tên đối tác, loại hợp đồng...). Trả danh sách tóm tắt.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Từ khóa tìm kiếm"}},
                    "required": ["query"],
                },
            ),
            ToolDef(
                name="get_contract",
                description="Lấy chi tiết một hợp đồng theo id (vd HD-2026-001).",
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string", "description": "Mã hợp đồng"}},
                    "required": ["id"],
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> "str | ToolResult":
        if tool_name == "search_contracts":
            q = str(args.get("query", "")).lower()
            hits = [
                {"id": c["id"], "title": c["title"], "partner": c["partner"]}
                for c in _SAMPLE_CONTRACTS
                if not q or q in json.dumps(c, ensure_ascii=False).lower()
            ]
            # Cũ: `hits or _SAMPLE_CONTRACTS[:1]` — không khớp gì vẫn trả HD-2026-001 như thể khớp
            # → agent nói về hợp đồng không liên quan như có thật (bịa). Nay rỗng → is_error rõ ràng.
            if not hits:
                return ToolResult(
                    content=(
                        f"Không tìm thấy hợp đồng nào khớp '{args.get('query', '')}'. "
                        "KHÔNG có hợp đồng phù hợp trong kho — đừng bịa; báo user là không tìm thấy."
                    ),
                    is_error=True,
                )
            return json.dumps({"results": hits}, ensure_ascii=False)
        if tool_name == "get_contract":
            cid = str(args.get("id", "")).upper()
            for c in _SAMPLE_CONTRACTS:
                if c["id"] == cid:
                    return json.dumps(c, ensure_ascii=False)
            raise ValueError(f"không tìm thấy hợp đồng {cid}")
        raise ValueError(f"tool không tồn tại: {tool_name}")
