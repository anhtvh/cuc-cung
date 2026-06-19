"""MCP server `zalopay-deals` — gọi THẲNG API danh sách khuyến mãi chính thức của Zalopay.

Trang zalopay.vn/khuyen-mai là Next.js render động (HTML thô chỉ có taxonomy), nhưng
client gọi 1 endpoint JSON public (proxy same-origin `/api/`, base CMS ẩn server-side) trả
danh sách KM theo danh mục — ta gọi thẳng endpoint đó. KHÔNG cào HTML/sitemap.

Endpoint (verify live 19/06/2026, HTTP 200 JSON, KHÔNG cần auth):
  GET /api/get-new-by-category-for-promotion?category_id={id}&type_status=1&limit={n}&offset=0
  → { error:{code,message}, data:{ data:[...bài KM...], time_now: <epoch_ms> } }

Mỗi bài KM có: id, title, slug, description, start, end (thời hạn KM), published_at, ...
URL bài viết = https://zalopay.vn/{slug}-{id} (verify HTTP 200).

QUAN TRỌNG: `type_status=1` = đã publish, NHƯNG vẫn lẫn KM hết hạn → BẮT BUỘC lọc
`start <= time_now <= end` mới ra KM thực sự còn hiệu lực (chống hiển thị deal chết).

Tools:
  list_deals(category?, limit?) — danh sách KM Zalopay CÒN HẠN, kèm link đã dựng sẵn.
"""

import json
import logging
import unicodedata
from datetime import datetime
from typing import Any

import httpx

from app.llm.base import ToolDef, ToolResult
from app.tools.net import SsrfBlocked, safe_get

log = logging.getLogger(__name__)

_BASE = "https://zalopay.vn"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"

# Danh mục KM (id lấy từ __NEXT_DATA__ của /khuyen-mai). 6 = tất cả KM (danh mục cha).
# type_status=1 publish trả nhiều bài; active thưa nên fetch rộng rồi lọc theo hạn.
_PARENT_ID = 6
_CATEGORIES: dict[int, dict[str, str]] = {
    6: {"slug": "khuyen-mai", "name": "Tất cả khuyến mãi"},
    9: {"slug": "dac-biet", "name": "Đặc biệt"},
    12: {"slug": "mua-sam", "name": "Mua sắm"},
    15: {"slug": "an-uong", "name": "Ăn uống"},
    18: {"slug": "du-lich", "name": "Du lịch"},
    21: {"slug": "hoa-don", "name": "Hóa đơn"},
    24: {"slug": "dien-thoai", "name": "Điện thoại"},
    27: {"slug": "giai-tri", "name": "Giải trí"},
    61: {"slug": "tai-chinh", "name": "Tài chính"},
}
# Fetch rộng (50) để không bỏ sót KM còn hạn (active thưa trong list publish), rồi lọc + cắt.
_FETCH_LIMIT = 50
_DEFAULT_OUTPUT = 12
_MAX_DESC_CHARS = 280


def _norm(s: str) -> str:
    """Bỏ dấu + lowercase để khớp tên/slug danh mục linh hoạt (vd 'ăn uống' ~ 'an uong')."""
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("-", " ").strip()


def _resolve_category(category: Any) -> int:
    """Map category (id / slug / tên VN / từ khoá) → category_id. Không khớp → 6 (tất cả)."""
    if category in (None, ""):
        return _PARENT_ID
    # id số trực tiếp
    try:
        cid = int(category)
        if cid in _CATEGORIES:
            return cid
    except (TypeError, ValueError):
        pass
    q = _norm(str(category))
    for cid, meta in _CATEGORIES.items():
        if q == _norm(meta["slug"]) or q == _norm(meta["name"]) or q in _norm(meta["name"]):
            return cid
    return _PARENT_ID  # không nhận diện được → trả tất cả, không tự đoán sai


def _to_ms(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000
    except (ValueError, AttributeError):
        return None


def _iso_date(iso: str | None) -> str | None:
    """ISO → 'YYYY-MM-DD' cho hiển thị; không parse được → trả nguyên/None."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return iso


class ZalopayDealsProvider:
    server_name = "zalopay-deals"
    is_mock = False  # API thật của Zalopay

    def list_tools(self) -> list[ToolDef]:
        cat_hint = ", ".join(f"{m['slug']}={m['name']}" for cid, m in _CATEGORIES.items() if cid != _PARENT_ID)
        return [
            ToolDef(
                name="list_deals",
                description=(
                    "Lấy danh sách khuyến mãi Zalopay ĐANG CÒN HẠN (realtime, từ API chính thức), "
                    "kèm link bài viết dựng sẵn + ngày hết hạn. Đã lọc bỏ KM hết hạn. "
                    "Bỏ trống category để lấy TẤT CẢ; hoặc lọc theo danh mục: "
                    f"{cat_hint}."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "Danh mục KM (slug hoặc tên, vd 'an-uong'/'Ăn uống'). Bỏ trống = tất cả.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": f"Số KM trả về tối đa (mặc định {_DEFAULT_OUTPUT}).",
                        },
                    },
                },
            )
        ]

    def call(self, tool_name: str, args: dict[str, Any]) -> "str | ToolResult":
        if tool_name == "list_deals":
            return self._list_deals(args)
        raise ValueError(f"tool không tồn tại: {tool_name}")

    def _list_deals(self, args: dict) -> "str | ToolResult":
        cid = _resolve_category(args.get("category"))
        try:
            out_limit = int(args.get("limit") or _DEFAULT_OUTPUT)
        except (TypeError, ValueError):
            out_limit = _DEFAULT_OUTPUT
        out_limit = max(1, min(out_limit, 30))

        # LUÔN query danh mục cha (6): feed cha sắp xếp ưu tiên KM mới/đang chạy nên lọc ra KM
        # còn hạn ổn định. Feed sub-category (21, 18...) lại xếp bài HẾT HẠN lên đầu → 50 bài đầu
        # toàn hết hạn, miss KM active. Vì vậy lọc theo danh mục con làm CLIENT-SIDE qua
        # news_sub_category.id của từng bài, không gọi endpoint sub-category.
        url = (
            f"{_BASE}/api/get-new-by-category-for-promotion"
            f"?category_id={_PARENT_ID}&type_status=1&limit={_FETCH_LIMIT}&offset=0"
        )
        try:
            resp = safe_get(
                url, timeout=10,
                headers={"User-Agent": _UA, "Accept": "application/json", "Referer": f"{_BASE}/khuyen-mai"},
            )
            resp.raise_for_status()
            payload = resp.json()
        except SsrfBlocked as e:
            return ToolResult(content=str(e), is_error=True)
        except httpx.TimeoutException:
            return ToolResult(content="Timeout khi gọi API khuyến mãi Zalopay (>10s).", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                content=f"API khuyến mãi trả HTTP {e.response.status_code}. KHÔNG bịa — báo chưa lấy được KM.",
                is_error=True,
            )
        except Exception as e:  # noqa: BLE001 — mọi lỗi còn lại (JSON hỏng, mạng...) đều trả model
            log.warning("API khuyến mãi lỗi: %s", e)
            return ToolResult(content=f"Không lấy được danh sách KM: {e}", is_error=True)

        data = (payload.get("data") or {})
        items = data.get("data") or []
        now = data.get("time_now")
        if now is None:
            return ToolResult(content="API khuyến mãi thiếu time_now — không lọc được hạn; báo chưa lấy được.", is_error=True)

        deals = []
        for a in items:
            # Lọc theo danh mục con (nếu user yêu cầu) qua news_sub_category.id — client-side.
            sub = a.get("news_sub_category") or {}
            sub_id = sub.get("id") if isinstance(sub, dict) else None
            sub_name = sub.get("name") if isinstance(sub, dict) else None
            if cid != _PARENT_ID and sub_id != cid:
                continue
            start_ms, end_ms = _to_ms(a.get("start")), _to_ms(a.get("end"))
            # Lọc còn hạn: start <= now <= end. Thiếu mốc nào → coi như mở phía đó (vẫn xét phía còn lại).
            if start_ms is not None and now < start_ms:
                continue  # chưa bắt đầu
            if end_ms is not None and now > end_ms:
                continue  # đã hết hạn
            slug, _id = a.get("slug"), a.get("id")
            if not slug or not _id:
                continue
            desc = (a.get("description") or "").strip()
            deals.append({
                "title": a.get("title"),
                "category": sub_name,  # danh mục con để agent gợi ý theo nhu cầu, không cần gọi thêm
                "url": f"{_BASE}/{slug}-{_id}",
                "valid_until": _iso_date(a.get("end")),
                "valid_from": _iso_date(a.get("start")),
                "_end_ms": end_ms if end_ms is not None else float("inf"),
                "description": desc[:_MAX_DESC_CHARS],
            })

        if not deals:
            scope = _CATEGORIES[cid]["name"]
            return ToolResult(
                content=(
                    f"Không có KM nào CÒN HẠN trong danh mục '{scope}' lúc này "
                    "(các bài publish đều đã hết hạn hoặc chưa bắt đầu). KHÔNG bịa — báo user thật. "
                    "Có thể thử bỏ lọc danh mục để xem toàn bộ KM còn hạn."
                ),
                is_error=True,
            )

        # Sắp xếp KM sắp hết hạn lên trước (urgency) để agent ưu tiên đúng.
        deals.sort(key=lambda d: d["_end_ms"])
        for d in deals:
            d.pop("_end_ms", None)
        return json.dumps(
            {
                "category": _CATEGORIES[cid]["name"],
                "count": len(deals[:out_limit]),
                "deals": deals[:out_limit],
                "source": f"{_BASE}/khuyen-mai",
            },
            ensure_ascii=False,
        )
