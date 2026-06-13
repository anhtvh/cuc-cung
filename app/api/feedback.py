"""POST /feedback — thumbs up/down trên mỗi câu trả lời của agent."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_user_id, require_admin

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    agent_name: str
    rating: int              # 1 = tốt, -1 = tệ
    message_preview: str = ""


@router.post("")
def submit_feedback(
    req: FeedbackRequest,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    if req.rating not in (1, -1):
        raise HTTPException(status_code=422, detail="rating phải là 1 (tốt) hoặc -1 (tệ)")
    c.feedback.add(user_id, req.agent_name, req.rating, req.message_preview)
    return {"ok": True}


@router.get("/stats")
def feedback_stats(
    c: Container = Depends(get_container),
    _admin: str = Depends(require_admin),
):
    """Admin: tổng hợp thumbs up/down theo agent."""
    return c.feedback.stats_by_agent()
