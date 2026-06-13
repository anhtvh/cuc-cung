"""Test orchestration: run_agent handler trong MasterToolset."""

from unittest.mock import MagicMock

import pytest

from app.builder.master import MasterToolset
from app.core.models import Agent, ItemStatus
from app.tools.catalog import ToolCatalog
from tests.conftest import make_agent


class FakeEngine:
    """ChatEngine giả: run_once trả chuỗi cố định."""

    def __init__(self, response: str = "kết quả giả"):
        self.response = response
        self.calls: list[dict] = []

    def run_once(self, user_id: str, agent: Agent, message: str, max_tool_rounds: int = 2) -> str:
        self.calls.append({"user_id": user_id, "agent": agent, "message": message})
        return self.response


def make_toolset(agents_repo, gov, engine=None, user_id="an.nguyen"):
    catalog = ToolCatalog(providers=[])
    return MasterToolset(
        agents=agents_repo,
        skills=MagicMock(),
        governance=gov,
        catalog=catalog,
        user_id=user_id,
        engine=engine,
    )


class TestRunAgent:
    def test_engine_none_returns_error(self, governance, agents):
        agents.create(make_agent("AgentA", status=ItemStatus.public))
        ts = make_toolset(agents, governance, engine=None)
        result = ts._h_run_agent({"agent_name": "AgentA", "task": "test"})
        assert result.is_error
        assert "engine" in result.content.lower() or "bật" in result.content

    def test_cap_enforced(self, governance, agents):
        agents.create(make_agent("AgentB", status=ItemStatus.public))
        engine = FakeEngine("output")
        ts = make_toolset(agents, governance, engine=engine)
        ts._max_agents = 1
        ts._orchestration_count = 1  # đã đạt cap
        result = ts._h_run_agent({"agent_name": "AgentB", "task": "test"})
        assert result.is_error
        assert engine.calls == []  # không gọi

    def test_master_blocked(self, governance, agents):
        engine = FakeEngine()
        ts = make_toolset(agents, governance, engine=engine)
        result = ts._h_run_agent({"agent_name": "master", "task": "test"})
        assert result.is_error
        assert "master" in result.content.lower()

    def test_nonexistent_agent_error(self, governance, agents):
        engine = FakeEngine()
        ts = make_toolset(agents, governance, engine=engine)
        result = ts._h_run_agent({"agent_name": "KhongTonTai", "task": "test"})
        assert result.is_error

    def test_successful_run(self, governance, agents):
        agents.create(make_agent("AgentC", status=ItemStatus.public))
        engine = FakeEngine("đây là kết quả thực")
        ts = make_toolset(agents, governance, engine=engine, user_id="an.nguyen")
        result = ts._h_run_agent({"agent_name": "AgentC", "task": "hỏi gì đó"})
        assert not result.is_error
        assert "đây là kết quả thực" in result.content
        assert "đây là kết quả thực" in result.display_output
        assert ts._orchestration_count == 1
        assert engine.calls[0]["message"] == "hỏi gì đó"

    def test_count_increments(self, governance, agents):
        agents.create(make_agent("AgentD", status=ItemStatus.public))
        agents.create(make_agent("AgentE", status=ItemStatus.public))
        engine = FakeEngine("ok")
        ts = make_toolset(agents, governance, engine=engine)
        ts._h_run_agent({"agent_name": "AgentD", "task": "x"})
        ts._h_run_agent({"agent_name": "AgentE", "task": "y"})
        assert ts._orchestration_count == 2

    def test_private_agent_not_visible_to_other_user(self, governance, agents):
        agents.create(make_agent("AgentPrivate", status=ItemStatus.private, created_by="other.user"))
        engine = FakeEngine()
        ts = make_toolset(agents, governance, engine=engine, user_id="an.nguyen")
        result = ts._h_run_agent({"agent_name": "AgentPrivate", "task": "test"})
        assert result.is_error

    def test_output_truncated_at_4000(self, governance, agents):
        agents.create(make_agent("AgentF", status=ItemStatus.public))
        long_output = "x" * 5000
        engine = FakeEngine(long_output)
        ts = make_toolset(agents, governance, engine=engine)
        result = ts._h_run_agent({"agent_name": "AgentF", "task": "test"})
        assert not result.is_error
        assert len(result.content) <= 4030  # 4000 + prefix "[Kết quả từ @AgentF]\n"
        assert len(result.display_output) <= 3000
