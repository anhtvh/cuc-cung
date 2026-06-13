"""MCP server `web-search` — tìm kiếm web thật bằng DuckDuckGo (thư viện ddgs).

Không cần API key. Production: swap sang connector `web-search-live`
qua AgentBase MCP Gateway khi mcp_gateway_endpoint được cấu hình.

Tools:
  search — DDG text search, trả title+url+snippet (dùng để đánh giá URL nào đáng đọc)
  fetch  — tải nội dung full một trang web, trả plain text đã làm sạch (≤6000 ký tự)
"""

import ipaddress
import json
import logging
import re
import socket as _socket
from typing import Any
from urllib.parse import urlparse

from app.llm.base import ToolDef

log = logging.getLogger(__name__)

_FALLBACK_RESULTS = [
    {
        "title": "Không tìm được kết quả",
        "url": "",
        "snippet": "Tìm kiếm web thất bại. Thử lại sau hoặc kiểm tra kết nối mạng.",
    }
]

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_MAX_FETCH_CHARS = 12_000


def _ssrf_check(url: str) -> str | None:
    """Trả error message nếu URL trỏ vào mạng nội bộ, None nếu OK."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return "URL thiếu hostname"
    try:
        resolved = _socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
        if any(ip in net for net in _PRIVATE_NETS):
            return f"URL trỏ đến địa chỉ nội mạng ({resolved}) — không được phép"
    except (_socket.gaierror, ValueError):
        pass
    return None


def _ddg_search(query: str, n: int) -> list[dict]:
    try:
        from ddgs import DDGS
        with DDGS() as ddg:
            raw = list(ddg.text(query, max_results=n))
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in raw
        ]
    except Exception as e:
        log.warning("DDG search lỗi: %s", e)
        return []


def _fetch_page(url: str) -> dict:
    """Fetch + làm sạch HTML, trả {"title", "text", "truncated", "error?"}."""
    import httpx
    from bs4 import BeautifulSoup

    if not url.startswith(("http://", "https://")):
        return {"error": "URL phải bắt đầu bằng http:// hoặc https://"}
    err = _ssrf_check(url)
    if err:
        return {"error": err}
    try:
        resp = httpx.get(
            url, timeout=5, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
    except httpx.TimeoutException:
        return {"error": f"Timeout khi fetch '{url}' (>10s)"}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} khi fetch '{url}'"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"Không fetch được: {e}"}

    ct = resp.headers.get("content-type", "")
    if "text/html" not in ct and "text/plain" not in ct:
        return {"error": f"Content-type '{ct}' không hỗ trợ (chỉ HTML/text)"}

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else url
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n")).strip()
    truncated = len(text) > _MAX_FETCH_CHARS
    return {
        "title": title,
        "text": text[:_MAX_FETCH_CHARS],
        "truncated": truncated,
    }


class WebSearchProvider:
    server_name = "web-search"
    is_mock = False

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="search",
                description=(
                    "Tìm kiếm thông tin thời gian thực trên web (DuckDuckGo). "
                    "Trả về danh sách kết quả gồm tiêu đề, URL và đoạn trích ngắn. "
                    "Dùng để tìm URL uy tín, sau đó gọi `web-search__fetch` để đọc nội dung đầy đủ."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Câu truy vấn tìm kiếm"},
                        "num_results": {
                            "type": "integer",
                            "description": "Số kết quả (mặc định 5, tối đa 8)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            ToolDef(
                name="fetch",
                description=(
                    "Tải và đọc nội dung đầy đủ một trang web (tối đa 12000 ký tự). "
                    "Dùng SAU khi đã search và chọn được URL đáng tin cậy từ kết quả. "
                    "Trả về title và plain text đã làm sạch."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL cần đọc (phải lấy từ kết quả search)"},
                    },
                    "required": ["url"],
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "search":
            return self._search(args)
        if tool_name == "fetch":
            return self._fetch(args)
        raise ValueError(f"tool không tồn tại: {tool_name}")

    def _search(self, args: dict) -> str:
        query = str(args.get("query", "")).strip()
        n = min(int(args.get("num_results", 5)), 8)
        if not query:
            return json.dumps({"error": "query trống"}, ensure_ascii=False)
        results = _ddg_search(query, n)
        if not results:
            log.warning("DDG trả rỗng cho query=%r", query)
            results = _FALLBACK_RESULTS
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)

    def _fetch(self, args: dict) -> str:
        url = str(args.get("url", "")).strip()
        if not url:
            return json.dumps({"error": "url trống"}, ensure_ascii=False)
        result = _fetch_page(url)
        if "error" in result:
            log.warning("web-search fetch lỗi url=%r: %s", url, result["error"])
        return json.dumps({"url": url, **result}, ensure_ascii=False)
