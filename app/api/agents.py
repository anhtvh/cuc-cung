"""CRUD đọc agents cho trang Catalog (Flow 2b tầng 'User nhìn thấy')."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Container, get_container, get_user_id
from app.core.governance import GovernanceError
from app.core.models import MASTER_AGENT_NAME

router = APIRouter(prefix="/agents", tags=["agents"])


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
    return [
        {
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
        for a in agents
    ]


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
