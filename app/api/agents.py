"""CRUD đọc agents cho trang Catalog (Flow 2b tầng 'User nhìn thấy')."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_user_id, require_login
from app.core.governance import GovernanceError
from app.core.models import MASTER_AGENT_NAME, Visibility

router = APIRouter(prefix="/agents", tags=["agents"])


def _agent_dict(a, c: Container, calls_map: dict) -> dict:
    return {
        "id": a.id,
        "name": a.name,
        "tagline": a.tagline,
        "slug": a.slug,
        "description": a.description,
        "domain": a.domain,
        "status": a.status.value,
        "visibility": a.visibility.value,
        "created_by": a.created_by,
        "skills": c.agents.skills_of(a.name),
        "connectors": a.connectors,
        "has_pending_changes": a.pending_changes is not None,
        "review_note": a.review_note,
        "calls": calls_map.get(a.name, 0),
    }


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
    return [_agent_dict(a, c, calls_map) for a in agents]


@router.get("/mine")
def my_agents(
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Agents do user hiện tại tạo (mọi status)."""
    agents = c.agents.list(created_by=user.email)
    agents = [a for a in agents if a.name != MASTER_AGENT_NAME]
    calls_map = c.usage.call_counts()
    return [_agent_dict(a, c, calls_map) for a in agents]


@router.post("/{name}/submit")
def submit_agent(
    name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    try:
        item = c.governance.submit_for_review("agent", name, user_id)
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


@router.delete("/{name}")
def delete_agent(
    name: str,
    c: Container = Depends(get_container),
    user: object = Depends(require_login),
):
    """Xóa agent — chỉ owner, chỉ khi visibility=private.
    Admin có thể xóa bất kỳ agent nào (kể cả public) để quản trị.
    """
    agent = c.agents.get(name)
    if agent is None or name == MASTER_AGENT_NAME:
        raise HTTPException(status_code=404, detail=f"agent '{name}' không tồn tại")

    is_admin = c.governance.is_admin(user.email)
    is_owner = agent.created_by == user.email

    if not is_owner and not is_admin:
        raise HTTPException(status_code=403, detail="Bạn không có quyền xóa agent này")

    if not is_admin and agent.visibility != Visibility.private:
        raise HTTPException(
            status_code=403,
            detail="Chỉ có thể xóa agent private. Agent public cần admin xóa hoặc bạn liên hệ admin để hủy kích hoạt.",
        )

    c.agents.delete(name)
    return {"deleted": name}


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
