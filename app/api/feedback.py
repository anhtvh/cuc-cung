"""POST /feedback — thumbs up/down trên mỗi câu trả lời của agent."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Container, get_container, require_admin, require_login

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    agent_name: str
    rating: int              # 1 = tốt, -1 = tệ
    message_preview: str = ""


@router.post("")
def submit_feedback(
    req: FeedbackRequest,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),  # chặn guest (id tạm) spam feedback → méo thống kê
):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating phải là 1 (tốt) hoặc -1 (tệ)")
    # Validate agent tồn tại — tránh ghi feedback rác cho agent không có trong registry.
    if c.agents.get(req.agent_name) is None:
        raise HTTPException(status_code=404, detail=f"agent '{req.agent_name}' không tồn tại")
    c.feedback.add(user.email, req.agent_name, req.rating, req.message_preview)
    return {"ok": True}


@router.get("/stats")
def feedback_stats(
    c: Container = Depends(get_container),
    _admin: str = Depends(require_admin),
):
    """Admin: tổng hợp thumbs up/down theo agent."""
    return c.feedback.stats_by_agent()
