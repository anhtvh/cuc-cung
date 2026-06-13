"""Đọc skill catalog chung cho trang Catalog — search/lọc theo domain (Flow 2b)."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Container, get_container, get_user_id
from app.core.governance import GovernanceError
from app.core.models import ItemStatus

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
def list_skills(
    domain: str | None = None,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    skills = c.skills.list()
    # B-01: chỉ trả skill public hoặc skill của chính user (private người khác → ẩn)
    skills = [s for s in skills if s.status == ItemStatus.public or s.created_by == user_id]
    if domain:
        skills = [s for s in skills if s.domain == domain]
    return [
        {
            "name": s.name,
            "description": s.description,
            "domain": s.domain,
            "status": s.status.value,
            "version": s.version,
            "created_by": s.created_by,
            "has_pending_changes": s.pending_changes is not None,
        }
        for s in skills
    ]


@router.post("/{name}/submit")
def submit_skill(
    name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    try:
        item = c.governance.submit_for_review("skill", name, user_id)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"submitted": name, "status": item.status.value}


@router.get("/{name}")
def get_skill(
    name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    skill = c.skills.get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"skill '{name}' không tồn tại")
    # B-02: kiểm tra quyền xem — chỉ owner, admin, hoặc skill public
    if skill.status != ItemStatus.public and skill.created_by != user_id and not c.governance.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Bạn không có quyền xem skill này.")
    data = skill.model_dump(mode="json")
    data["used_by_agents"] = c.agents.agents_using_skill(name)
    return data
