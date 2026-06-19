"""Domain models thuần Pydantic (design §4, §6) — không dùng dict thô.

Module core KHÔNG import FastAPI / SQLAlchemy / SDK LLM.
"""

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


def slugify(name: str) -> str:
    """Chuyển tên tự do (Unicode, dấu tiếng Việt) → ASCII slug dùng cho @mention."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    return slug or "agent"

MASTER_AGENT_NAME = "master"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ItemStatus(str, Enum):
    """Vòng đời maker-checker chung cho agent VÀ skill (Flow 2b)."""

    private = "private"
    pending_review = "pending_review"
    public = "public"
    rejected = "rejected"


class Visibility(str, Enum):
    company = "company"
    private = "private"


class Agent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tagline: str | None = None  # hiển thị ngắn trên UI card (vd "Hỗ trợ review hợp đồng")
    slug: str | None = None     # ASCII handle cho @mention (tự sinh từ name nếu để trống)
    description: str  # viết cho MODEL đọc — input của router (Flow 1)
    system_prompt: str  # persona
    connectors: list[str] = Field(default_factory=list)
    domain: str | None = None
    status: ItemStatus = ItemStatus.private
    # I-05: agent chuyên môn chặt có thể tắt để không escalate quá sớm khi hơi lệch domain
    escalate_enabled: bool = True
    # Agent closed-domain (chỉ trả lời từ nguồn riêng, vd FAQ/Deals/Docs Zalopay) tắt = False
    # → engine KHÔNG cấp web-search always-on, buộc bám nguồn chính thức, không search ngoài (chống bịa).
    web_search_enabled: bool = True
    pending_changes: dict[str, Any] | None = None  # sửa đổi chờ duyệt khi đang public (Flow 4)
    visibility: Visibility = Visibility.company
    identity_ref: str | None = None  # hook roadmap #2 — KHÔNG lưu key trong DB
    org_id: str | None = None  # hook multi-tenant, contest không dùng
    created_by: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    @model_validator(mode="after")
    def _auto_slug(self) -> "Agent":
        if not self.slug:
            self.slug = slugify(self.name)
        return self


class Skill(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str  # convention: <domain>-<viec>, vd "legal-tham-dinh-hop-dong"
    description: str
    content: str  # markdown quy trình/checklist
    domain: str | None = None
    status: ItemStatus = ItemStatus.private
    pending_changes: dict[str, Any] | None = None
    version: int = 1
    org_id: str | None = None
    created_by: str | None = None
    reviewed_by: str | None = None
    review_note: str | None = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class RouteDecision(BaseModel):
    """Kết quả Flow 1."""

    agent_name: str
    # "explicit" (UI chọn/sticky) | "mention" (@tên) | "classify" | "fallback_master"
    routed_by: str
    confidence: str | None = None
    # L-09: thông báo cho API layer khi route bị override (vd sticky agent hết visible)
    note: str | None = None
