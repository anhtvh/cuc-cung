"""MCP server `web-search` — tìm kiếm web thật bằng DuckDuckGo (thư viện ddgs).

Không cần API key. Production: swap sang connector `web-search-live`
qua AgentBase MCP Gateway khi mcp_gateway_endpoint được cấu hình.

Tools:
  search — DDG text search, trả title+url+snippet (dùng để đánh giá URL nào đáng đọc)
  fetch  — tải nội dung full một trang web, trả plain text đã làm sạch (≤6000 ký tự)
"""

import json
import logging
import re
from typing import Any

from app.llm.base import ToolDef, ToolResult
# SSRF guard chuyển sang app.tools.net.safe_get — kiểm IP nội mạng ở MỌI hop redirect,
# không chỉ URL gốc (guard cũ _ssrf_check + follow_redirects=True bị bypass qua 302).
from app.tools.net import SsrfBlocked, safe_get

log = logging.getLogger(__name__)

# Cũ: _FALLBACK_RESULTS trả về như một "kết quả" bình thường (is_error=False) khi DDG rỗng/lỗi
# → model nuốt nhầm thành "đã search xong" rồi trả lời từ trí nhớ training (bịa). Bỏ; nay lỗi
# search trả ToolResult(is_error=True) để model biết RÕ là thất bại (xem _search).
# _FALLBACK_RESULTS = [
#     {"title": "Không tìm được kết quả", "url": "",
#      "snippet": "Tìm kiếm web thất bại. Thử lại sau hoặc kiểm tra kết nối mạng."}
# ]

_MAX_FETCH_CHARS = 12_000


class SearchFailed(Exception):
    """DDG search thất bại do hạ tầng (mạng/429/captcha) — KHÁC với 'ra 0 kết quả'."""


def _ddg_search(query: str, n: int) -> list[dict]:
    # Cũ: except → return [] → _search không phân biệt "lỗi hạ tầng" với "không có kết quả",
    # cả hai đều thành fallback "thành công" → model bịa. Nay raise SearchFailed khi lỗi thật
    # để _search đánh dấu is_error; [] chỉ còn nghĩa "thật sự không có kết quả nào".
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
        raise SearchFailed(str(e)) from e


def _fetch_page(url: str) -> dict:
    """Fetch + làm sạch HTML, trả {"title", "text", "truncated", "error?"}."""
    import httpx
    from bs4 import BeautifulSoup

    if not url.startswith(("http://", "https://")):
        return {"error": "URL phải bắt đầu bằng http:// hoặc https://"}
    try:
        # safe_get: kiểm SSRF ở mỗi hop redirect (chống 302 → IP nội mạng).
        resp = safe_get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except SsrfBlocked as e:
        return {"error": str(e)}
    except httpx.TimeoutException:
        return {"error": f"Timeout khi fetch '{url}' (>5s)"}
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

    # Trả str khi thành công, ToolResult(is_error=True) khi thất bại — để model phân biệt
    # "có dữ liệu" với "tra cứu hỏng/không có" và KHÔNG bịa khi không có dữ liệu thật.
    def call(self, tool_name: str, args: dict[str, Any]) -> "str | ToolResult":
        if tool_name == "search":
            return self._search(args)
        if tool_name == "fetch":
            return self._fetch(args)
        raise ValueError(f"tool không tồn tại: {tool_name}")

    def _search(self, args: dict) -> "str | ToolResult":
        query = str(args.get("query", "")).strip()
        n = min(int(args.get("num_results", 5)), 8)
        if not query:
            return ToolResult(content="Lỗi: query tìm kiếm trống.", is_error=True)
        # Cũ: lỗi hạ tầng và "ra rỗng" đều bị nhồi _FALLBACK_RESULTS rồi trả thành công → model
        # tưởng đã search xong và tự bịa. Nay tách 2 nhánh, cả hai đều is_error=True kèm chỉ thị
        # rõ "KHÔNG có dữ liệu, đừng bịa".
        try:
            results = _ddg_search(query, n)
        except SearchFailed as e:
            log.warning("DDG search thất bại query=%r: %s", query, e)
            return ToolResult(
                content=(
                    f"Tìm kiếm web THẤT BẠI cho '{query}' ({e}). Không lấy được kết quả nào. "
                    "KHÔNG bịa thông tin — hãy nói thẳng với user là chưa tra cứu được."
                ),
                is_error=True,
            )
        if not results:
            log.warning("DDG trả rỗng cho query=%r", query)
            return ToolResult(
                content=(
                    f"Không tìm thấy kết quả nào cho '{query}'. KHÔNG có dữ liệu để trả lời — "
                    "đừng bịa; nói thẳng là không tìm được thông tin hoặc thử từ khoá khác."
                ),
                is_error=True,
            )
        return json.dumps({"query": query, "results": results}, ensure_ascii=False)

    def _fetch(self, args: dict) -> "str | ToolResult":
        url = str(args.get("url", "")).strip()
        if not url:
            return ToolResult(content="Lỗi: url trống.", is_error=True)
        result = _fetch_page(url)
        if "error" in result:
            # Cũ: trả {"url", "error"} thành công (is_error=False) → model bỏ qua lỗi, lấy nội dung
            # trang từ trí nhớ. Nay is_error=True để model biết fetch HỎNG → thử URL khác/không bịa.
            log.warning("web-search fetch lỗi url=%r: %s", url, result["error"])
            return ToolResult(
                content=(
                    f"Không đọc được nội dung '{url}': {result['error']}. "
                    "Thử URL khác trong kết quả search; KHÔNG bịa nội dung trang."
                ),
                is_error=True,
            )
        return json.dumps({"url": url, **result}, ensure_ascii=False)
