"""GET /history — trả danh sách agent user đã chat để restore sidebar khi F5."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import Container, get_container, get_user_id

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
def get_recent_conversations(
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Trả [{conversation_id, agent_name, title, last_text, updated_at}] để UI restore sidebar.

    Dùng conv_meta (SQLite) — hoạt động với mọi memory backend kể cả AgentBase.
    """
    return c.conv_meta.list(user_id)


@router.get("/{conversation_id}")
def get_conversation_messages(
    conversation_id: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Trả [{role, content}] của một conversation cụ thể để render lại khi click sidebar.

    Gọi trực tiếp memory.get_history() — hoạt động với mọi backend (SqlMemory, AgentBaseMemory).
    """
    msgs = c.memory.get_history(user_id, conversation_id, limit=50)
    return [{"role": m.role, "content": m.content} for m in msgs]


class ConvTitleRequest(BaseModel):
    title: str


@router.patch("/{conversation_id}/title")
def update_conversation_title(
    conversation_id: str,
    body: ConvTitleRequest,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Đặt tên hiển thị cho một conversation (auto-title từ tin nhắn đầu hoặc user rename)."""
    title = body.title.strip()
    if not title:
        return {"ok": False, "reason": "title trống"}
    c.conv_meta.rename(user_id, conversation_id, title)
    return {"ok": True, "conversation_id": conversation_id, "title": title}


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    c: Container = Depends(get_container),
    user_id: str = Depends(get_user_id),
):
    """Xóa toàn bộ lịch sử chat của một cuộc trò chuyện.

    SqlMemory: xóa cả bảng messages. AgentBase: không hỗ trợ delete session — bỏ qua.
    conv_meta luôn xóa bất kể backend.
    """
    from app.memory.sql_memory import SqlMemory
    if isinstance(c.memory, SqlMemory):
        c.memory.delete_conversation(user_id, conversation_id)
    c.conv_meta.delete(user_id, conversation_id)
    return {"deleted": conversation_id}
