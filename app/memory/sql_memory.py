"""Fallback memory bằng SQLite (Flow 6) — bảng `messages` trong schema §4."""

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.models import ChatMessage, now_iso
from app.storage.sql import MessageRow


class SqlMemory:
    def __init__(self, engine: Engine):
        self._engine = engine

    def get_history(self, user_id: str, agent_name: str, limit: int = 20) -> list[ChatMessage]:
        with Session(self._engine) as s:
            q = (
                select(MessageRow)
                .where(MessageRow.user_id == user_id, MessageRow.agent_name == agent_name)
                .order_by(MessageRow.id.desc())
                .limit(limit)
            )
            rows = list(s.scalars(q))
        rows.reverse()  # trả về theo thứ tự thời gian
        return [ChatMessage(role=r.role or "user", content=r.content or "") for r in rows]

    def append(self, user_id: str, agent_name: str, role: str, content: str) -> None:
        with Session(self._engine) as s:
            s.add(
                MessageRow(
                    user_id=user_id, agent_name=agent_name, role=role, content=content, created_at=now_iso()
                )
            )
            s.commit()

    def delete_conversation(self, user_id: str, agent_name: str) -> None:
        with Session(self._engine) as s:
            s.execute(
                delete(MessageRow).where(
                    MessageRow.user_id == user_id,
                    MessageRow.agent_name == agent_name,
                )
            )
            s.commit()

    def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        # Semantic search thuộc Memory module (14/06) — fallback không hỗ trợ.
        return []

    def get_recent_agents(self, user_id: str, limit: int = 20) -> list[dict]:
        """Trả danh sách agent user đã chat gần nhất, kèm preview câu trả lời cuối."""
        with Session(self._engine) as s:
            q = (
                select(MessageRow.agent_name, func.max(MessageRow.created_at).label("last_at"))
                .where(MessageRow.user_id == user_id)
                .where(MessageRow.agent_name.is_not(None))
                .group_by(MessageRow.agent_name)
                .order_by(func.max(MessageRow.created_at).desc())
                .limit(limit)
            )
            rows = s.execute(q).all()
            result: list[dict] = []
            for row in rows:
                preview_q = (
                    select(MessageRow.content)
                    .where(MessageRow.user_id == user_id)
                    .where(MessageRow.agent_name == row.agent_name)
                    .where(MessageRow.role == "assistant")
                    .order_by(MessageRow.id.desc())
                    .limit(1)
                )
                preview = s.execute(preview_q).scalar() or ""
                result.append({
                    "agent_name": row.agent_name,
                    "last_text": preview[:60],
                    "updated_at": row.last_at or "",
                })
            return result
