"""Test xưng hô anh/chị: lưu preference + inject vào system prompt (em → anh/chị)."""

import pytest

from app.builder.master import MasterToolset
from app.core.chat_engine import ChatEngine
from app.storage.sql import SqlUserRepo, UserRow, now_iso
from app.tools.catalog import ToolCatalog
from sqlalchemy.orm import Session

from tests.conftest import make_agent


@pytest.fixture
def user_repo(engine):
    repo = SqlUserRepo(engine)
    with Session(engine) as s:
        s.add(UserRow(id="u1", email="an@x.com", name="An", role="user", created_at=now_iso()))
        s.commit()
    return repo


class _FakeMemory:
    def get_history(self, *a, **k):
        return []

    def search(self, *a, **k):
        return []

    def append(self, *a, **k):
        pass


def _engine_obj(agents, skills):
    return ChatEngine(agents, skills, usage=None, memory=_FakeMemory(), llm=None, catalog=ToolCatalog(providers=[]))


class TestUserRepoSalutation:
    def test_set_and_get(self, user_repo):
        assert user_repo.get_salutation("an@x.com") is None
        assert user_repo.set_salutation("an@x.com", "anh") is True
        assert user_repo.get_salutation("an@x.com") == "anh"

    def test_set_unknown_user_returns_false(self, user_repo):
        assert user_repo.set_salutation("guest_abc", "chị") is False


class TestSetSalutationTool:
    def _toolset(self, agents, skills, governance, user_repo, user_id="an@x.com", is_guest=False):
        return MasterToolset(
            agents=agents, skills=skills, governance=governance,
            catalog=ToolCatalog(providers=[]), user_id=user_id,
            is_guest=is_guest, user_repo=user_repo,
        )

    def test_saves_salutation(self, governance, agents, skills, user_repo):
        ts = self._toolset(agents, skills, governance, user_repo)
        res = ts.execute("set_salutation", {"salutation": "chị"})
        assert not res.is_error
        assert user_repo.get_salutation("an@x.com") == "chị"

    def test_invalid_value_rejected(self, governance, agents, skills, user_repo):
        ts = self._toolset(agents, skills, governance, user_repo)
        res = ts.execute("set_salutation", {"salutation": "ngài"})
        assert res.is_error

    def test_guest_blocked(self, governance, agents, skills, user_repo):
        ts = self._toolset(agents, skills, governance, user_repo, user_id="guest_x", is_guest=True)
        res = ts.execute("set_salutation", {"salutation": "anh"})
        assert res.is_error  # _GUEST_BLOCKED_TOOLS chặn


class TestSystemPromptAddressing:
    def test_agent_con_uses_salutation(self, agents, skills):
        agents.create(make_agent(name="BeGa"))
        eng = _engine_obj(agents, skills)
        sp = eng.build_system_prompt(agents.get("BeGa"), "u1", salutation="anh")
        assert "gọi user là **anh**" in sp
        assert "gọi user là **bạn**" not in sp

    def test_agent_con_unknown_falls_back_anh_chi(self, agents, skills):
        agents.create(make_agent(name="BeGa"))
        eng = _engine_obj(agents, skills)
        sp = eng.build_system_prompt(agents.get("BeGa"), "u1", salutation=None)
        assert "anh/chị" in sp

    def test_master_known_salutation(self, agents, skills):
        agents.create(make_agent(name="master"))
        eng = _engine_obj(agents, skills)
        sp = eng.build_system_prompt(agents.get("master"), "u1", salutation="chị")
        assert "gọi user là **chị**" in sp

    def test_master_unknown_logged_in_asks(self, agents, skills):
        agents.create(make_agent(name="master"))
        eng = _engine_obj(agents, skills)
        sp = eng.build_system_prompt(agents.get("master"), "u1", salutation=None, is_guest=False)
        assert "anh hay chị" in sp  # hướng dẫn hỏi 1 lần

    def test_master_guest_no_ask(self, agents, skills):
        agents.create(make_agent(name="master"))
        eng = _engine_obj(agents, skills)
        sp = eng.build_system_prompt(agents.get("master"), "u1", salutation=None, is_guest=True)
        assert "anh hay chị" not in sp  # guest không bị hỏi
