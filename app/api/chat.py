"""POST /chat (SSE) — Flow 1 routing + Flow 2/3 chat. Route mỏng, logic ở core/builder."""

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_is_guest, get_user_id
from app.auth.rate_limiter import get_limiter, get_session_limiter
from app.builder.master import GUEST_BUILDER_NOTE, GUEST_MASTER_TOOLS, MASTER_TOOLS, MasterToolset
from app.core.models import MASTER_AGENT_NAME

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class FileAttachment(BaseModel):
    filename: str
    content_type: str  # "text" | "image"
    text: str | None = None
    base64: str | None = None
    media_type: str | None = None


class ChatRequest(BaseModel):
    message: str
    agent_name: str | None = None  # UI chọn / sticky session (client-side, Flow 1)
    conversation_id: str | None = None  # thread key (nhiều cuộc/agent); None → fallback agent.name
    attachment: FileAttachment | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(
    req: ChatRequest,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
    is_guest: bool = Depends(get_is_guest),
) -> StreamingResponse:
    if not req.message.strip() and not req.attachment and not req.agent_name:
        raise HTTPException(status_code=422, detail="message trống")
    if not get_limiter().is_allowed(user_id):
        raise HTTPException(status_code=429, detail="Model đang quay như chong chóng  Thử lại sau chút xíu nhé! 🌀")
    # I-06: cap tổng số lượt chat per user trong session window (chống cháy credit lúc demo public).
    if not get_session_limiter().is_allowed(user_id):
        raise HTTPException(status_code=429, detail="Bạn đã dùng hết lượt chat trong phiên này — thử lại sau nhé!")

    # B-10: dùng filename + content_type để router classify đúng agent chuyên môn
    routing_message = req.message.strip()
    if not routing_message and req.attachment:
        routing_message = f"Xử lý file '{req.attachment.filename}' ({req.attachment.content_type})"
    decision = c.router.route(user_id, routing_message, req.agent_name)
    agent = c.agents.get(decision.agent_name)
    if agent is None:
        raise HTTPException(status_code=500, detail=f"agent '{decision.agent_name}' không có trong registry — chạy seeds?")
    # Chốt chặn cứng quyền dùng (defense-in-depth): không phụ thuộc 100% vào router lọc.
    if not c.governance.can_use_agent(agent, user_id):
        raise HTTPException(status_code=403, detail="Bạn không có quyền dùng agent này.")

    # Xưng hô đã lưu của user (anh/chị) — guest không có row nên trả None.
    salutation = None if is_guest else c.user_repo.get_salutation(user_id)

    extra_tools = None
    extra_executor = None
    extra_system = None
    if agent.name == MASTER_AGENT_NAME and c.settings.builder_enabled:
        toolset = MasterToolset(
            c.agents, c.skills, c.governance, c.catalog, user_id,
            is_guest=is_guest,
            usage=c.usage,
            tester=c.tester,
            engine=c.engine,
            user_repo=c.user_repo,
        )
        toolset._max_agents = c.settings.orchestration_max_agents
        toolset._sub_rounds = c.settings.orchestration_sub_rounds
        extra_executor = toolset.execute
        # Guest: chỉ chat + dùng agent public — KHÔNG cấp tool tạo/sửa/xóa, mời đăng nhập.
        if is_guest:
            extra_tools = GUEST_MASTER_TOOLS
            extra_system = GUEST_BUILDER_NOTE
        else:
            extra_tools = MASTER_TOOLS

    # Thread key: client gửi conversation_id (uuid). Chưa gửi (guest/client cũ) → fallback agent.name.
    conv_id = req.conversation_id or agent.name

    def event_stream() -> Iterator[str]:
        # L-09: note được set khi sticky agent không còn visible → thông báo cho UI
        yield _sse("meta", {"agent_name": agent.name, "agent_tagline": agent.tagline, "agent_description": agent.description, "agent_slug": agent.slug, "routed_by": decision.routed_by, "confidence": decision.confidence, "note": decision.note, "conversation_id": conv_id})
        attachment = req.attachment.model_dump() if req.attachment else None
        _last_text: list[str] = []  # mutable container để thu text cuối
        try:
            for ev in c.engine.stream(user_id, agent, req.message, attachment=attachment, extra_tools=extra_tools, extra_executor=extra_executor, extra_system=extra_system, salutation=salutation, is_guest=is_guest, conversation_id=conv_id):
                if ev["event"] == "delta":
                    _last_text.append(ev["data"].get("text", ""))
                yield _sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001 — lỗi giữa stream phải báo UI, không chết im lặng
            # Log chi tiết để debug, nhưng KHÔNG lộ message thô của provider (vd "Error code: 404 ...")
            # ra UI — gửi câu thân thiện thay thế.
            log.exception("chat stream lỗi (user=%s, agent=%s): %s", user_id, agent.name, e)
            yield _sse("error", {"message": "Model đang quay như chong chóng 🌀 Thử lại sau chút xíu nhé!"})
        finally:
            # Guest không lưu conv_meta (history không persist qua refresh).
            # .strip() để preview ở sidebar không dính khoảng trắng/newline đầu → trông trống.
            if _last_text and not is_guest:
                preview = "".join(_last_text).strip()[:120]
                if preview:
                    try:
                        c.conv_meta.upsert(user_id, conv_id, agent.name, preview)
                    except Exception:  # noqa: BLE001
                        pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
