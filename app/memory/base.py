"""Memory interface chung (Flow 6): implement SQLite trước, swap Memory module ngày 14/06.

Module khó hơn dự kiến → ship bản SQLite, không chặn deadline (design §8 check #2).
"""

from typing import Protocol

from app.core.models import ChatMessage


class Memory(Protocol):
    # Thread key = conversation_id (tách khỏi agent). agent_name trong append = agent trả lời tin nhắn.
    def get_history(self, user_id: str, conversation_id: str, limit: int = 20) -> list[ChatMessage]: ...

    def append(self, user_id: str, conversation_id: str, agent_name: str, role: str, content: str) -> None: ...

    def search(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        """Long-term semantic (master nhớ user từng tạo gì) — bản SQL trả rỗng."""
        ...
