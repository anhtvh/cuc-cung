"""Trang Review (admin) — Flow 2b: hiển thị ĐẦY ĐỦ, không duyệt mù.

Agent pending kèm TOÀN VĂN persona + skill gắn (toàn văn content) + connector
(từng tool, nhãn mock/thật) + diff pending_changes trên item active.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Container, get_container, require_admin
from app.core.governance import GovernanceError
from app.core.models import MASTER_AGENT_NAME, ItemStatus

router = APIRouter(prefix="/review", tags=["review"])


def _skill_full(c: Container, name: str) -> dict | None:
    s = c.skills.get(name)
    if s is None:
        return None
    return {
        "name": s.name,
        "description": s.description,
        "content": s.content,  # TOÀN VĂN markdown
        "domain": s.domain,
        "status": s.status.value,
        "version": s.version,
        "created_by": s.created_by,
        "pending_changes": s.pending_changes,
    }


@router.get("/pending")
def pending(c: Container = Depends(get_container), admin: str = Depends(require_admin)):
    agents = []
    # pending_review + item active có pending_changes (Flow 4 — hiện diff cũ ↔ mới)
    for a in c.agents.list():
        if a.status != ItemStatus.pending_review and not a.pending_changes:
            continue
        skill_names = c.agents.skills_of(a.name)
        agents.append(
            {
                "name": a.name,
                "slug": a.slug,
                "description": a.description,
                "system_prompt": a.system_prompt,  # TOÀN VĂN persona
                "domain": a.domain,
                "status": a.status.value,
                "visibility": a.visibility.value,
                "created_by": a.created_by,
                "pending_changes": a.pending_changes,
                "review_note": a.review_note,
                # skill pending hiện CÙNG agent, duyệt một lượt (ràng buộc approve)
                "skills": [sf for n in skill_names if (sf := _skill_full(c, n))],
                # từng server + tool cụ thể agent được cấp quyền gọi, nhãn mock/thật
                "connectors": c.catalog.describe(a.connectors),
                # B-03: truyền user_id + domain để lọc visibility và pre-filter đúng (L-07)
                "dedup_candidates": c.governance.dedup_candidates("agent", a.name, a.description, user_id=admin, domain=a.domain),
            }
        )

    skills = [
        sf
        for s in c.skills.list()
        if (s.status == ItemStatus.pending_review or s.pending_changes) and (sf := _skill_full(c, s.name))
    ]
    return {"agents": agents, "skills": skills}


class RejectRequest(BaseModel):
    reason: str  # reject bắt buộc nhập lý do


@router.post("/{kind}/{name}/approve")
def approve(kind: str, name: str, c: Container = Depends(get_container), admin: str = Depends(require_admin)):
    if kind not in ("agent", "skill"):
        raise HTTPException(status_code=422, detail="kind phải là agent|skill")
    try:
        item = c.governance.approve(kind, name, admin)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"approved": name, "kind": kind, "status": item.status.value}


@router.post("/{kind}/{name}/reject")
def reject(
    kind: str,
    name: str,
    req: RejectRequest,
    c: Container = Depends(get_container),
    admin: str = Depends(require_admin),
):
    if kind not in ("agent", "skill"):
        raise HTTPException(status_code=422, detail="kind phải là agent|skill")
    try:
        item = c.governance.reject(kind, name, admin, req.reason)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"rejected": name, "kind": kind, "status": item.status.value, "reason": req.reason}


@router.get("/admin/stats")
def admin_stats(c: Container = Depends(get_container), _admin: str = Depends(require_admin)):
    """Dashboard admin: usage token, feedback, tổng số tài nguyên."""
    # Counts
    all_agents = c.agents.list()
    all_skills = c.skills.list()
    active_agents = [a for a in all_agents if a.status.value == "public" and a.name != MASTER_AGENT_NAME]
    active_skills = [s for s in all_skills if s.status.value == "public"]

    usage = c.usage.stats()
    feedback = c.feedback.stats_by_agent()
    total_users = c.usage.distinct_users()

    # Tổng token
    total_in = sum(r["in_tokens"] for r in usage)
    total_out = sum(r["out_tokens"] for r in usage)

    return {
        "counts": {
            "agents_active": len(active_agents),
            "agents_total": len(all_agents) - 1,   # trừ master
            "skills_active": len(active_skills),
            "skills_total": len(all_skills),
            "users": total_users,
        },
        "tokens": {
            "total_in": total_in,
            "total_out": total_out,
            "total": total_in + total_out,
        },
        "usage_by_agent": usage,
        "feedback_by_agent": feedback,
    }
