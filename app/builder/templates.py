"""Thư viện mẫu agent (#8) — blueprint sẵn để Master rút ngắn phỏng vấn.

Mẫu là FILE trong repo (app/builder/templates/*.json) — versioned theo git, giống
master_system.md là nguồn sự thật. Loader đọc + validate 1 lần lúc import; file lỗi
schema bị loại sớm (log warning) để KHÔNG lọt vào tool / không làm chết app.

Mẫu KHÔNG phải agent có sẵn: chỉ là bản nháp (persona + skill draft + connector gợi ý).
Master gọi apply_template lấy blueprint → trình user xem → tạo qua flow create_* như
thường (governance/dedup/self_test giữ nguyên).
"""

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# persona phải ≥200 ký tự để khớp ngưỡng governance (validate_agent_payload) — mẫu apply
# vào không bị create_agent từ chối vì prompt quá ngắn.
_MIN_PERSONA_CHARS = 200


class SkillDraft(BaseModel):
    name_suffix: str  # ghép với tên agent khi tạo skill thật (Master tự đặt)
    description: str
    content: str  # markdown quy trình/checklist


class AcceptanceCase(BaseModel):
    q: str
    expect: str


class AgentTemplate(BaseModel):
    key: str
    title: str
    icon: str = "bot"
    description: str
    suggested_connectors: list[str] = Field(default_factory=list)
    needs_knowledge: bool = False
    persona_template: str = Field(min_length=_MIN_PERSONA_CHARS)
    skill_drafts: list[SkillDraft] = Field(default_factory=list)
    acceptance_cases: list[AcceptanceCase] = Field(default_factory=list)


def _load() -> dict[str, AgentTemplate]:
    """Đọc + validate mọi *.json. File lỗi → log + bỏ qua (không chết app)."""
    out: dict[str, AgentTemplate] = {}
    if not _TEMPLATES_DIR.is_dir():
        log.warning("thư mục templates không tồn tại: %s", _TEMPLATES_DIR)
        return out
    for path in sorted(_TEMPLATES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            tpl = AgentTemplate.model_validate(data)
        except (json.JSONDecodeError, ValidationError, OSError) as e:
            log.warning("template lỗi, bỏ qua %s: %s", path.name, e)
            continue
        if tpl.key in out:
            log.warning("template trùng key '%s' (%s) — bỏ qua bản sau", tpl.key, path.name)
            continue
        out[tpl.key] = tpl
    return out


# Nạp 1 lần lúc import (mẫu tĩnh trong repo). Nếu cần hot-reload thì gọi _load() lại.
_TEMPLATES: dict[str, AgentTemplate] = _load()


def get_template(key: str) -> AgentTemplate | None:
    return _TEMPLATES.get(key)


def list_template_cards() -> list[dict]:
    """Payload NHẸ cho UI — chỉ {key, title, icon, description}, KHÔNG kèm persona/skill
    (tránh SSE nặng; full content lấy qua apply_template)."""
    return [
        {"key": t.key, "title": t.title, "icon": t.icon, "description": t.description}
        for t in _TEMPLATES.values()
    ]
