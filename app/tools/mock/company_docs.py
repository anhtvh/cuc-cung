"""Mock MCP server `company-docs` (Flow 5) — tra quy định công ty cho demo."""

import json
from typing import Any

from app.llm.base import ToolDef

_POLICIES = [
    {
        "id": "QD-PL-01",
        "title": "Quy định thẩm quyền ký hợp đồng",
        "summary": "Hợp đồng > 1 tỷ VND phải có phê duyệt CFO; > 5 tỷ phải qua HĐQT. Mọi hợp đồng phải qua phòng Pháp chế review trước khi ký.",
    },
    {
        "id": "QD-PL-02",
        "title": "Quy định điều khoản bắt buộc trong hợp đồng",
        "summary": "Bắt buộc có: giới hạn trách nhiệm (liability cap), điều khoản chấm dứt, bảo mật thông tin, luật áp dụng Việt Nam, giải quyết tranh chấp tại VIAC.",
    },
    {
        "id": "QD-HR-01",
        "title": "Quy định nghỉ phép",
        "summary": "12 ngày phép năm, cộng 1 ngày mỗi 5 năm thâm niên. Nghỉ quá 3 ngày liên tục cần manager duyệt trước 1 tuần.",
    },
]


class CompanyDocsProvider:
    server_name = "company-docs"
    is_mock = True

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="search_policy",
                description="Tra cứu quy định/chính sách nội bộ công ty theo từ khóa.",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string", "description": "Từ khóa"}},
                    "required": ["query"],
                },
            )
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "search_policy":
            q = str(args.get("query", "")).lower()
            hits = [p for p in _POLICIES if not q or q in json.dumps(p, ensure_ascii=False).lower()]
            return json.dumps({"results": hits or _POLICIES}, ensure_ascii=False)
        raise ValueError(f"tool không tồn tại: {tool_name}")
