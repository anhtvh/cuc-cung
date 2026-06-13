"""CRUD đọc agents cho trang Catalog (Flow 2b tầng 'User nhìn thấy')."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_user_id, require_login
from app.core.governance import GovernanceError
from app.core.models import MASTER_AGENT_NAME, Visibility

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_dict(a, skills_map: dict, calls_map: dict, include_prompt: bool = False) -> dict:
    d = {
        "id": a.id,
        "name": a.name,
        "tagline": a.tagline,
        "slug": a.slug,
        "description": a.description,
        "domain": a.domain,
        "status": a.status.value,
        "visibility": a.visibility.value,
        "created_by": a.created_by,
        "skills": skills_map.get(a.name, []),
        "connectors": a.connectors,
        "has_pending_changes": a.pending_changes is not None,
        "review_note": a.review_note,
        "calls": calls_map.get(a.name, 0),
    }
    if include_prompt:
        d["system_prompt"] = a.system_prompt
    return d


@router.get("")
def list_agents(
    domain: str | None = None,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    agents = c.governance.visible_agents(user_id)
    if domain:
        agents = [a for a in agents if a.domain == domain]
    calls_map: dict[str, int] = c.usage.call_counts()
    skills_map = c.agents.skills_of_many([a.name for a in agents])
    return [_agent_dict(a, skills_map, calls_map) for a in agents]


@router.get("/mine")
def my_agents(
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Agents do user hiện tại tạo (mọi status). Trả system_prompt để modal Sửa dùng."""
    agents = c.agents.list(created_by=user.email)
    agents = [a for a in agents if a.name != MASTER_AGENT_NAME]
    calls_map = c.usage.call_counts()
    skills_map = c.agents.skills_of_many([a.name for a in agents])
    return [_agent_dict(a, skills_map, calls_map, include_prompt=True) for a in agents]


@router.post("/{name}/submit")
def submit_agent(
    name: str,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    try:
        item = c.governance.submit_for_review("agent", name, user.email)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"submitted": name, "status": item.status.value}


class AgentEditRequest(BaseModel):
    description: str | None = None
    system_prompt: str | None = None
    tagline: str | None = None
    domain: str | None = None
    visibility: str | None = None
    connectors: list[str] | None = None


@router.put("/{name}")
def update_agent(
    name: str,
    body: AgentEditRequest,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Edit agent — chỉ owner hoặc admin. Active agent → ghi pending_changes."""
    agent = c.agents.get(name)
    if agent is None or name == MASTER_AGENT_NAME:
        raise HTTPException(status_code=404, detail=f"agent '{name}' không tồn tại")
    if not c.governance.can_edit(agent, user.email):
        raise HTTPException(status_code=403, detail="Bạn không có quyền sửa agent này")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="Không có field nào để cập nhật")

    try:
        updated = c.governance.propose_update("agent", name, updates, user.email)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"updated": name, "status": updated.status.value}


@router.post("/{name}/retract")
def retract_agent(
    name: str,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Hủy nộp duyệt — đưa agent từ pending_review về private (chỉ owner hoặc admin)."""
    try:
        item = c.governance.retract_submission("agent", name, user.email)
    except GovernanceError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"retracted": name, "status": item.status.value}


@router.delete("/{name}")
def delete_agent(
    name: str,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Xóa agent — owner chỉ xóa được khi status private/rejected; admin xóa bất kỳ.
    Cascade: skill private chỉ dùng bởi agent này → xóa luôn; skill public/pending/dùng chung → chỉ gỡ liên kết.
    """
    from app.core.models import ItemStatus as IS
    agent = c.agents.get(name)
    if agent is None or name == MASTER_AGENT_NAME:
        raise HTTPException(status_code=404, detail=f"agent '{name}' không tồn tại")

    is_admin = c.governance.is_admin(user.email)
    is_owner = agent.created_by == user.email

    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa agent này")

    if not is_admin and agent.status not in (IS.private, IS.rejected):
        raise HTTPException(
            status_code=403,
            detail=f"Chỉ xóa được agent đang private hoặc rejected (hiện tại: {agent.status.value}). Hủy nộp duyệt trước khi xóa.",
        )

    # Xác định skill private dùng riêng cho agent này → sẽ xóa cùng
    skill_names = c.agents.skills_of(name)
    skills_to_delete: list[str] = []
    for sn in skill_names:
        skill = c.skills.get(sn)
        if skill and skill.status == IS.private:
            others = [a for a in c.agents.agents_using_skill(sn) if a != name]
            if not others:
                skills_to_delete.append(sn)

    # Xóa agent (cascade: agent_skills, messages, usage_log, conv_meta, feedback_log)
    c.agents.delete(name)

    # Xóa skill private exclusive (agent_skills đã bị cascade xóa rồi nên chỉ xóa SkillRow)
    deleted_skills: list[str] = []
    for sn in skills_to_delete:
        try:
            c.skills.delete(sn)
            deleted_skills.append(sn)
        except Exception:  # noqa: BLE001 — skill đã bị xóa trước đó thì bỏ qua
            pass

    return {"deleted": name, "deleted_skills": deleted_skills}


@router.get("/{name}")
def get_agent(
    name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    agent = c.agents.get(name)
    if agent is None or name == MASTER_AGENT_NAME or not c.governance.can_use_agent(agent, user_id):
        raise HTTPException(status_code=404, detail=f"agent '{name}' không tồn tại hoặc bạn không có quyền xem")
    data = agent.model_dump(mode="json")
    data["skills"] = c.agents.skills_of(name)
    data["connector_detail"] = c.catalog.describe(agent.connectors)
    return data
