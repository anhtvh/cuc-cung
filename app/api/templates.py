"""GET /templates — danh sách mẫu agent dựng sẵn (#8) cho UI hiển thị thẻ chọn nhanh.

Read-only, không cần auth: duyệt mẫu cho mọi người. Việc TẠO agent từ mẫu vẫn đi qua
flow create_* của Master (cần đăng nhập, có governance). Payload nhẹ (key/title/icon/
description) — đồng nhất với event `templates` mà ChatEngine emit từ tool list_templates.
"""

from fastapi import APIRouter

from app.builder.templates import list_template_cards

router = APIRouter(tags=["templates"])


@router.get("/templates")
def get_templates() -> dict:
    return {"templates": list_template_cards()}
