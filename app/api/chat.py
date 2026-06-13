"""POST /chat (SSE) — Flow 1 routing + Flow 2/3 chat. Route mỏng, logic ở core/builder."""

import json
import logging
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_user_id
from app.auth.rate_limiter import get_limiter
from app.builder.master import MASTER_TOOLS, MasterToolset
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
    attachment: FileAttachment | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
def chat(
    req: ChatRequest,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> StreamingResponse:
    if not req.message.strip() and not req.attachment and not req.agent_name:
        raise HTTPException(status_code=422, detail="message trống")
    if not get_limiter().is_allowed(user_id):
        raise HTTPException(status_code=429, detail="Quá nhiều yêu cầu — thử lại sau ít phút nhé! 🙏")

    # B-10: dùng filename + content_type để router classify đúng agent chuyên môn
    routing_message = req.message.strip()
    if not routing_message and req.attachment:
        routing_message = f"Xử lý file '{req.attachment.filename}' ({req.attachment.content_type})"
    decision = c.router.route(user_id, routing_message, req.agent_name)
    agent = c.agents.get(decision.agent_name)
    if agent is None:
        raise HTTPException(status_code=500, detail=f"agent '{decision.agent_name}' không có trong registry — chạy seeds?")

    extra_tools = None
    extra_executor = None
    if agent.name == MASTER_AGENT_NAME and c.settings.builder_enabled:
        toolset = MasterToolset(
            c.agents, c.skills, c.governance, c.catalog, user_id,
            usage=c.usage,
            tester=c.tester,
            engine=c.engine,
        )
        toolset._max_agents = c.settings.orchestration_max_agents
        toolset._sub_rounds = c.settings.orchestration_sub_rounds
        extra_tools = MASTER_TOOLS
        extra_executor = toolset.execute

    def event_stream() -> Iterator[str]:
        # L-09: note được set khi sticky agent không còn visible → thông báo cho UI
        yield _sse("meta", {"agent_name": agent.name, "agent_tagline": agent.tagline, "agent_description": agent.description, "agent_slug": agent.slug, "routed_by": decision.routed_by, "confidence": decision.confidence, "note": decision.note})
        attachment = req.attachment.model_dump() if req.attachment else None
        _last_text: list[str] = []  # mutable container để thu text cuối
        try:
            for ev in c.engine.stream(user_id, agent, req.message, attachment=attachment, extra_tools=extra_tools, extra_executor=extra_executor):
                if ev["event"] == "delta":
                    _last_text.append(ev["data"].get("text", ""))
                yield _sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001 — lỗi giữa stream phải báo UI, không chết im lặng
            log.exception("chat stream lỗi (user=%s, agent=%s)", user_id, agent.name)
            yield _sse("error", {"message": str(e)})
        finally:
            # Guest không lưu conv_meta (history không persist qua refresh)
            if _last_text and user_id != "guest":
                try:
                    c.conv_meta.upsert(user_id, agent.name, "".join(_last_text)[:120])
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
