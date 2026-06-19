"""MCP server `zalopay-docs` — tra cứu tài liệu tích hợp Zalopay (docs.zalopay.vn).

docs.zalopay.vn là site **Docusaurus (SSG, server-render)** → nội dung nằm SẴN trong HTML,
fetch là đọc được (khác hẳn trang khuyến mãi/FAQ vốn là SPA). Khám phá trang qua `sitemap.xml`
(Docusaurus tự sinh, phủ MỌI trang) thay vì lần theo link.

Locale: sitemap chỉ liệt kê locale mặc định `en` (path `/docs/...`). Bản tiếng Việt ở
`/vi/docs/...` (cùng path, chèn `/vi`) → ta map sang `/vi` để ưu tiên tiếng Việt; trang chưa
dịch sẽ fallback nội dung en nhưng vẫn HTTP 200.

Tools:
  list_docs(section?) — liệt kê URL tài liệu (từ sitemap), lọc theo nhánh; dùng để chọn trang đọc.
  read_doc(url)       — đọc nội dung đầy đủ 1 trang doc (server-render) → plain text.
"""

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.llm.base import ToolDef, ToolResult
from app.tools.net import SsrfBlocked, safe_get

log = logging.getLogger(__name__)

_BASE = "https://docs.zalopay.vn"
_SITEMAP = f"{_BASE}/sitemap.xml"
_VI_PREFIX = "/vi"  # chèn vào trước /docs/... để lấy bản tiếng Việt
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
_MAX_CONTENT_CHARS = 8000  # trang spec API có thể dài

# Các nhánh tài liệu chính (segment đầu sau /docs/) — để mô tả tool & lọc.
_SECTIONS = {
    "miniapp": "SDK MiniApp (device, storage, user, ui, navigator, payment, location)",
    "specs": "Đặc tả API (order-create, refund, callback, tokenization, agreement, disbursement...)",
    "guides": "Hướng dẫn tích hợp (payment-acceptance, extension-products: Shopify/WordPress...)",
    "developer-tools": "Công cụ dev (glossary, status-codes, test wallets, security)",
    "sdk": "SDK chung (intro, quickstart)",
}
_LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
_NEXT_DOC_RE = re.compile(r"/docs/(?!tags\b)")  # trang doc thật, bỏ /docs/tags


class ZalopayDocsProvider:
    server_name = "zalopay-docs"
    is_mock = False  # tài liệu công khai thật của Zalopay

    def __init__(self) -> None:
        # Cache danh sách doc (sitemap ~162 URL, ít đổi). Race vô hại: cùng lắm fetch 2 lần.
        self._docs_cache: list[str] | None = None

    def list_tools(self) -> list[ToolDef]:
        sect = "; ".join(f"`{k}`={v}" for k, v in _SECTIONS.items())
        return [
            ToolDef(
                name="list_docs",
                description=(
                    "Liệt kê URL các trang tài liệu tích hợp Zalopay (lấy từ sitemap, bản tiếng Việt). "
                    "Dùng để CHỌN trang phù hợp câu hỏi rồi gọi read_doc. NÊN truyền `section` để thu hẹp. "
                    f"Các nhánh: {sect}."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": "Nhánh tài liệu cần lọc (vd 'miniapp', 'specs', 'guides'). Bỏ trống = tất cả.",
                        }
                    },
                },
            ),
            ToolDef(
                name="read_doc",
                description=(
                    "Đọc nội dung đầy đủ một trang tài liệu Zalopay (hướng dẫn, tham số API, mã lỗi, "
                    "ví dụ). Truyền NGUYÊN `url` lấy từ list_docs."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL trang doc (lấy từ list_docs)."},
                    },
                    "required": ["url"],
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> "str | ToolResult":
        if tool_name == "list_docs":
            return self._list_docs(args)
        if tool_name == "read_doc":
            return self._read_doc(args)
        raise ValueError(f"tool không tồn tại: {tool_name}")

    def _load_docs(self) -> "list[str] | ToolResult":
        """Parse sitemap → danh sách URL doc tiếng Việt. Cache lại sau lần đầu."""
        if self._docs_cache is not None:
            return self._docs_cache
        try:
            resp = safe_get(_SITEMAP, timeout=10, headers={"User-Agent": _UA})
            resp.raise_for_status()
        except SsrfBlocked as e:
            return ToolResult(content=str(e), is_error=True)
        except httpx.TimeoutException:
            return ToolResult(content="Timeout khi tải sitemap docs Zalopay (>10s).", is_error=True)
        except Exception as e:  # noqa: BLE001
            log.warning("tải sitemap docs lỗi: %s", e)
            return ToolResult(content=f"Không tải được sitemap docs: {e}", is_error=True)

        urls: list[str] = []
        for loc in _LOC_RE.findall(resp.text):
            path = urlparse(loc).path
            if not _NEXT_DOC_RE.search(path):
                continue  # bỏ /search, /markdown-page, /docs/tags, trang chủ
            # Map sang tiếng Việt: chèn /vi trước /docs/... (tránh nhân đôi nếu sitemap đã có /vi).
            vi_path = path if path.startswith("/vi/") else _VI_PREFIX + path
            urls.append(f"{_BASE}{vi_path}")
        if not urls:
            return ToolResult(
                content="Sitemap docs không có trang nào — cấu trúc có thể đã đổi. KHÔNG bịa.",
                is_error=True,
            )
        self._docs_cache = urls
        return urls

    def _list_docs(self, args: dict) -> "str | ToolResult":
        docs = self._load_docs()
        if isinstance(docs, ToolResult):
            return docs
        section = str(args.get("section") or "").strip().lower().lstrip("/")
        if section:
            # khớp segment nhánh: .../vi/docs/<section>/...
            docs = [u for u in docs if f"/docs/{section}/" in u or u.rstrip("/").endswith(f"/docs/{section}")]
            if not docs:
                return ToolResult(
                    content=(
                        f"Không có trang nào trong nhánh '{section}'. "
                        f"Các nhánh hợp lệ: {', '.join(_SECTIONS)}. Bỏ section để xem tất cả."
                    ),
                    is_error=True,
                )
        import json
        return json.dumps(
            {"count": len(docs), "sections": list(_SECTIONS), "docs": docs},
            ensure_ascii=False,
        )

    def _read_doc(self, args: dict) -> "str | ToolResult":
        url = str(args.get("url", "")).strip()
        if urlparse(url).hostname not in ("docs.zalopay.vn",):
            return ToolResult(content="url phải thuộc docs.zalopay.vn (lấy từ list_docs).", is_error=True)
        try:
            resp = safe_get(url, timeout=10, headers={"User-Agent": _UA})
            resp.raise_for_status()
        except SsrfBlocked as e:
            return ToolResult(content=str(e), is_error=True)
        except httpx.TimeoutException:
            return ToolResult(content=f"Timeout khi đọc doc ({url}, >10s).", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"Trang doc trả HTTP {e.response.status_code} ({url}). Có thể URL sai — KHÔNG bịa nội dung.",
                is_error=True,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("read_doc lỗi %s: %s", url, e)
            return ToolResult(content=f"Không đọc được doc ({url}): {e}", is_error=True)

        from bs4 import BeautifulSoup  # lazy import (giống web_search)

        soup = BeautifulSoup(resp.text, "html.parser")
        # Docusaurus: nội dung chính nằm trong <article>; bỏ điều hướng/mục lục/script.
        article = soup.find("article") or soup
        for tag in article(["nav", "footer", "header", "script", "style", "aside"]):
            tag.decompose()
        title = (soup.title.string or "").strip() if soup.title else url
        text = re.sub(r"\n{3,}", "\n\n", article.get_text("\n")).strip()
        if not text:
            return ToolResult(
                content=f"Trang doc ({url}) không trích được nội dung. KHÔNG bịa — báo user xem trực tiếp.",
                is_error=True,
            )
        import json
        return json.dumps(
            {
                "title": title,
                "url": url,
                "content": text[:_MAX_CONTENT_CHARS],
                "truncated": len(text) > _MAX_CONTENT_CHARS,
            },
            ensure_ascii=False,
        )
