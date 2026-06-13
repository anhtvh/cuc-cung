"""DI cho API layer: current_user + container service (wire ở composition root main.py)."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.auth.models import GuestUser, UserInfo
from app.config import Settings
from app.core.chat_engine import ChatEngine
from app.core.governance import Governance
from app.core.router import IntentRouter
from app.memory.base import Memory
from app.storage.base import AgentRepo, SkillRepo, UsageRepo
from app.storage.sql import SqlConvMetaRepo, SqlFeedbackRepo, SqlUserRepo
from app.tools.catalog import ToolCatalog
from app.tools.base import ToolProvider


@dataclass
class Container:
    settings: Settings
    agents: AgentRepo
    skills: SkillRepo
    usage: UsageRepo
    feedback: SqlFeedbackRepo
    conv_meta: SqlConvMetaRepo
    user_repo: SqlUserRepo
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


def get_current_user(request: Request) -> UserInfo | GuestUser:
    return request.state.user


def require_login(request: Request) -> UserInfo:
    """Trả UserInfo nếu đã đăng nhập, 401 nếu guest."""
    user = request.state.user
    if isinstance(user, GuestUser):
        raise HTTPException(status_code=401, detail="Vui lòng đăng nhập để sử dụng tính năng này")
    return user


def require_admin(request: Request) -> str:
    user_id = request.state.user_id
    c: Container = request.app.state.container
    if not c.governance.is_admin(user_id):
        raise HTTPException(status_code=403, detail="Chỉ admin (checker) được truy cập trang Review.")
    return user_id
