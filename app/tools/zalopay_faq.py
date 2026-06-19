"""MCP server `zalopay-faq` — gọi THẲNG FAQ JSON API chính thức của Zalopay.

Trang zalopay.vn/hoi-dap là Next.js render động: HTML thô không chứa nội dung
câu hỏi-đáp, nên fetch HTML (web-search) chỉ thấy app shell. Nhưng client-side
gọi 3 endpoint JSON public (không cần auth) trên host `support.zalopay.vn` —
ta gọi thẳng các endpoint đó để lấy dữ liệu cấu trúc, chính xác hơn search HTML.

Endpoint (đã verify live 19/06/2026, HTTP 200 JSON):
  GET /faq/api/get-category-list                 → danh mục (17 cái)
  GET /faq/api/get-folder-list?categoryId={id}   → thư mục con của 1 danh mục
  GET /faq/api/get-article-list?folderId={id}    → bài viết (kèm LUÔN nội dung trả lời)

Không có endpoint search/detail riêng → get-article-list trả luôn `description_text`
(plain text câu trả lời). Agent điều hướng theo TÊN: category → folder → article.

Tools (tên trần, prefix `zalopay-faq__` khi lên wire):
  list_categories            — liệt kê danh mục FAQ (id + tên)
  list_folders(category_id)  — liệt kê thư mục con trong 1 danh mục
  list_articles(folder_id)   — liệt kê bài + nội dung trả lời trong 1 thư mục
"""

import json
import logging
from typing import Any

import httpx

from app.llm.base import ToolDef, ToolResult
# Dùng chung safe_get (chặn SSRF mọi hop redirect) như web-search để nhất quán bảo mật.
from app.tools.net import SsrfBlocked, safe_get

log = logging.getLogger(__name__)

_BASE = "https://support.zalopay.vn"
# UA giống trình duyệt — endpoint có thể từ chối client lạ.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
# description_text có thể dài; cắt để không phình context. ~3000 ký tự đủ cho 1 câu trả lời FAQ.
_MAX_ANSWER_CHARS = 3000
# Nguồn trích dẫn (API không trả URL bài viết cụ thể, chỉ có id) — citation về trang FAQ chính thức.
_FAQ_PUBLIC_URL = "https://zalopay.vn/hoi-dap"


def _get_json(path: str) -> "dict | ToolResult":
    """GET 1 endpoint FAQ, parse JSON. Trả ToolResult(is_error) khi hỏng — KHÔNG nuốt lỗi."""
    url = f"{_BASE}{path}"
    try:
        resp = safe_get(url, timeout=8, headers={"User-Agent": _UA, "Accept": "application/json"})
        resp.raise_for_status()
    except SsrfBlocked as e:
        return ToolResult(content=str(e), is_error=True)
    except httpx.TimeoutException:
        return ToolResult(content=f"Timeout khi gọi FAQ API ({path}, >8s).", is_error=True)
    except httpx.HTTPStatusError as e:
        return ToolResult(
            content=f"FAQ API trả HTTP {e.response.status_code} ({path}). KHÔNG bịa — báo chưa tra cứu được.",
            is_error=True,
        )
    except Exception as e:  # noqa: BLE001 — mọi lỗi đều trả về model (chống nuốt lỗi)
        log.warning("FAQ API lỗi %s: %s", path, e)
        return ToolResult(content=f"Không gọi được FAQ API ({path}): {e}", is_error=True)
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        return ToolResult(content=f"FAQ API trả về không phải JSON ({path}): {e}", is_error=True)


class ZalopayFaqProvider:
    server_name = "zalopay-faq"
    is_mock = False  # API thật của Zalopay, không phải mock

    def list_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="list_categories",
                description=(
                    "Liệt kê toàn bộ danh mục FAQ chính thức của Zalopay (id + tên). "
                    "Gọi ĐẦU TIÊN để chọn danh mục khớp câu hỏi (vd 'Nạp tiền/Rút tiền', "
                    "'Chuyển tiền/Nhận tiền', 'An toàn bảo mật'...), rồi dùng id để gọi list_folders."
                ),
            ),
            ToolDef(
                name="list_folders",
                description=(
                    "Liệt kê thư mục con (id + tên) trong 1 danh mục FAQ. "
                    "Dùng category_id lấy từ list_categories. Chọn thư mục khớp nhất rồi gọi list_articles."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "category_id": {
                            "type": "integer",
                            "description": "id danh mục (lấy từ list_categories)",
                        }
                    },
                    "required": ["category_id"],
                },
            ),
            ToolDef(
                name="list_articles",
                description=(
                    "Liệt kê các bài viết FAQ trong 1 thư mục, KÈM LUÔN nội dung trả lời "
                    "(answer là plain text). Dùng folder_id lấy từ list_folders. "
                    "Đọc answer của bài khớp câu hỏi để trả lời — không cần fetch trang web."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "integer",
                            "description": "id thư mục (lấy từ list_folders)",
                        }
                    },
                    "required": ["folder_id"],
                },
            ),
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> "str | ToolResult":
        if tool_name == "list_categories":
            return self._list_categories()
        if tool_name == "list_folders":
            return self._list_folders(args)
        if tool_name == "list_articles":
            return self._list_articles(args)
        raise ValueError(f"tool không tồn tại: {tool_name}")

    def _list_categories(self) -> "str | ToolResult":
        res = _get_json("/faq/api/get-category-list")
        if isinstance(res, ToolResult):
            return res
        cats = res.get("data") or []
        if not cats:
            return ToolResult(
                content="FAQ API không trả danh mục nào. KHÔNG bịa — báo user chưa tra cứu được.",
                is_error=True,
            )
        out = [{"id": c.get("id"), "name": c.get("name")} for c in cats if c.get("id")]
        return json.dumps({"categories": out}, ensure_ascii=False)

    def _list_folders(self, args: dict) -> "str | ToolResult":
        cid = args.get("category_id")
        if cid in (None, ""):
            return ToolResult(content="Lỗi: thiếu category_id.", is_error=True)
        res = _get_json(f"/faq/api/get-folder-list?categoryId={cid}")
        if isinstance(res, ToolResult):
            return res
        folders = res.get("data") or []
        if not folders:
            return ToolResult(
                content=(
                    f"Danh mục {cid} không có thư mục nào (id sai hoặc rỗng). "
                    "Kiểm tra lại id từ list_categories; KHÔNG bịa."
                ),
                is_error=True,
            )
        out = [{"id": f.get("id"), "name": f.get("name")} for f in folders if f.get("id")]
        return json.dumps({"category_id": cid, "folders": out}, ensure_ascii=False)

    def _list_articles(self, args: dict) -> "str | ToolResult":
        fid = args.get("folder_id")
        if fid in (None, ""):
            return ToolResult(content="Lỗi: thiếu folder_id.", is_error=True)
        res = _get_json(f"/faq/api/get-article-list?folderId={fid}")
        if isinstance(res, ToolResult):
            return res
        arts = res.get("data") or []
        if not arts:
            return ToolResult(
                content=(
                    f"Thư mục {fid} không có bài viết nào (id sai hoặc rỗng). "
                    "Thử thư mục khác từ list_folders; KHÔNG bịa câu trả lời."
                ),
                is_error=True,
            )
        out = []
        for a in arts:
            answer = (a.get("description_text") or "").strip()
            truncated = len(answer) > _MAX_ANSWER_CHARS
            item = {
                "id": a.get("id"),
                "title": a.get("title"),
                "answer": answer[:_MAX_ANSWER_CHARS],
                "truncated": truncated,
                "updated_at": a.get("updated_at"),
            }
            # cta_link là chuỗi JSON (có zpa_link liên hệ CSKH) — bóc zpa_link nếu có để gợi ý liên hệ.
            cta_raw = a.get("cta_link")
            if cta_raw:
                try:
                    cta = json.loads(cta_raw) if isinstance(cta_raw, str) else cta_raw
                    if isinstance(cta, dict) and cta.get("zpa_link"):
                        item["contact_link"] = cta.get("zpa_link")
                except (json.JSONDecodeError, TypeError):
                    pass  # cta_link hỏng định dạng → bỏ qua, không chặn câu trả lời chính
            out.append(item)
        return json.dumps(
            {"folder_id": fid, "source": _FAQ_PUBLIC_URL, "articles": out},
            ensure_ascii=False,
        )
