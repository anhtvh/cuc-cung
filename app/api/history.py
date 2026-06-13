"""GET /history — trả danh sách agent user đã chat để restore sidebar khi F5."""

from fastapi import APIRouter, Depends

from app.api.deps import Container, get_container, get_user_id
from app.memory.sql_memory import SqlMemory

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
def get_recent_conversations(
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Trả [{agent_name, last_text, updated_at}] để UI restore sidebar."""
    if isinstance(c.memory, SqlMemory):
        return c.memory.get_recent_agents(user_id)
    # AgentBase memory: không hỗ trợ query ngược, trả rỗng
    return []


@router.get("/{agent_name}")
def get_conversation_messages(
    agent_name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Trả [{role, content}] của một conversation cụ thể để render lại khi click sidebar."""
    if isinstance(c.memory, SqlMemory):
        msgs = c.memory.get_history(user_id, agent_name, limit=50)
        return [{"role": m.role, "content": m.content} for m in msgs]
    return []


@router.delete("/{agent_name}")
def delete_conversation(
    agent_name: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Xóa toàn bộ lịch sử chat của user với agent đó."""
    if isinstance(c.memory, SqlMemory):
        c.memory.delete_conversation(user_id, agent_name)
    return {"deleted": agent_name}
