"""DI cho API layer: current_user + container service (wire ở composition root main.py)."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.config import Settings
from app.core.chat_engine import ChatEngine
from app.core.governance import Governance
from app.core.router import IntentRouter
from app.memory.base import Memory
from app.storage.base import AgentRepo, SkillRepo, UsageRepo
from app.storage.sql import SqlFeedbackRepo
from app.tools.catalog import ToolCatalog
from app.tools.base import ToolProvider


@dataclass
class Container:
    settings: Settings
    agents: AgentRepo
    skills: SkillRepo
    usage: UsageRepo
    feedback: SqlFeedbackRepo
    memory: Memory
    llm: object
    catalog: ToolCatalog
    governance: Governance
    router: IntentRouter
    engine: ChatEngine
    web_search_provider: ToolProvider | None = None
    tester: object | None = None  # AgentTester (HM3 self-test)


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_user_id(request: Request) -> str:
    return request.state.user_id


def require_admin(request: Request) -> str:
    user_id = request.state.user_id
    c: Container = request.app.state.container
    if not c.governance.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Chỉ admin (checker) được truy cập trang Review.")
    return user_id
