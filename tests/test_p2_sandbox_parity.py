"""P2-1: sandbox run_once khớp runtime stream.

Cùng dùng _assemble_tools → run_once inject đúng escalate/request_update/knowledge_search như
runtime, và surface marker khi agent chuyển hướng (để judge thấy hành vi scope).
"""

from unittest.mock import MagicMock

from app.core.chat_engine import ChatEngine
from app.llm.base import Done, TextDelta, ToolCallEvent, ToolDef, ToolResult, ToolStartEvent
from tests.conftest import make_agent


def _engine(agents, skills, llm, *, knowledge=None):
    memory = MagicMock()
    memory.get_history.return_value = []
    memory.search.return_value = []
    catalog = MagicMock()
    catalog.tools_for.return_value = [ToolDef(name="system__noop", description="noop")]
    catalog.execute.return_value = ToolResult(content="x")
    return ChatEngine(agents, skills, MagicMock(), memory, llm, catalog, knowledge=knowledge)


# ─── parity tool-set ─────────────────────────────────────────────────────────

class TestAssembleToolsParity:
    def test_subagent_with_escalate_gets_both_tools(self, agents, skills):
        engine = _engine(agents, skills, MagicMock())
        agent = make_agent(name="SubAgent", escalate_enabled=True)
        tools, _ = engine._assemble_tools(agent, "câu hỏi", has_kb=False)
        names = [t.name for t in tools]
        assert "escalate" in names
        assert "request_update" in names

    def test_subagent_without_escalate_has_request_update_only(self, agents, skills):
        engine = _engine(agents, skills, MagicMock())
        agent = make_agent(name="SubAgent", escalate_enabled=False)
        names = [t.name for t in engine._assemble_tools(agent, "câu hỏi", has_kb=False)[0]]
        assert "escalate" not in names
        assert "request_update" in names

    def test_knowledge_search_injected_when_has_kb(self, agents, skills):
        engine = _engine(agents, skills, MagicMock())
        agent = make_agent(name="SubAgent", escalate_enabled=False)
        names = [t.name for t in engine._assemble_tools(agent, "câu hỏi", has_kb=True)[0]]
        assert "knowledge_search" in names

    def test_master_gets_no_escalate_or_request_update(self, agents, skills):
        from app.core.models import MASTER_AGENT_NAME, Agent
        from tests.conftest import VALID_PROMPT
        engine = _engine(agents, skills, MagicMock())
        master = Agent(name=MASTER_AGENT_NAME, description="m", system_prompt=VALID_PROMPT)
        names = [t.name for t in engine._assemble_tools(master, "x", has_kb=False)[0]]
        assert "escalate" not in names
        assert "request_update" not in names


# ─── run_once surface delegate marker ────────────────────────────────────────

class _DelegatingLLM:
    """Mô phỏng agent gọi escalate trong sandbox → yield ToolCallEvent có delegate_to."""

    def chat_with_tools(self, system, messages, tools, execute, max_rounds=5, model=None, **kwargs):
        yield ToolStartEvent(name="escalate", input={})
        yield ToolCallEvent(
            name="escalate",
            input={"reason": "ngoài lề"},
            result=ToolResult(content="Đang chuyển về Master.", delegate_to="master"),
        )
        yield TextDelta("text thừa sau delegate KHÔNG được tính")
        yield Done()

    def chat(self, *a, **k):
        yield Done()

    def classify_json(self, *a, **k):
        return {}


class TestRunOnceDelegateMarker:
    def test_run_once_surfaces_delegate_and_stops(self, agents, skills):
        engine = _engine(agents, skills, _DelegatingLLM())
        agent = make_agent(name="SubAgent", escalate_enabled=True)
        out = engine.run_once("u1", agent, "câu hỏi ngoài chuyên môn", max_tool_rounds=2)
        assert "[Đã chuyển sang @master]" in out
        # dừng ngay sau delegate (giống runtime) → không nuốt text thừa phía sau
        assert "text thừa" not in out
