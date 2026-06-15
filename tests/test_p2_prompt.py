"""P2-3: cây quyết định gốc + quy tắc hội tụ trong system prompt agent con."""

from unittest.mock import MagicMock

from app.core.chat_engine import ChatEngine, _decision_tree
from tests.conftest import make_agent


def _engine(agents, skills):
    memory = MagicMock()
    memory.search.return_value = []
    catalog = MagicMock()
    catalog.tools_for.return_value = []
    return ChatEngine(agents, skills, MagicMock(), memory, MagicMock(), catalog)


class TestDecisionTreeBlock:
    def test_subagent_prompt_has_decision_tree_and_convergence(self, agents, skills):
        engine = _engine(agents, skills)
        agent = make_agent(name="SubAgent", escalate_enabled=True)
        prompt = engine.build_system_prompt(agent, "u1", message="câu hỏi")
        assert "Quy trình quyết định cho MỖI câu hỏi" in prompt
        assert "Hội tụ" in prompt
        assert "để em tìm" in prompt  # quy tắc chống lặp "để em tìm thêm"

    def test_master_prompt_has_no_decision_tree(self, agents, skills):
        from app.core.models import MASTER_AGENT_NAME, Agent
        from tests.conftest import VALID_PROMPT
        engine = _engine(agents, skills)
        master = Agent(name=MASTER_AGENT_NAME, description="m", system_prompt=VALID_PROMPT)
        prompt = engine.build_system_prompt(master, "u1", message="x")
        assert "Quy trình quyết định cho MỖI câu hỏi" not in prompt


class TestDecisionTreeAdapts:
    def test_escalate_step_only_when_enabled(self):
        with_esc = _decision_tree(escalate_enabled=True, knowledge_enabled=False)
        without_esc = _decision_tree(escalate_enabled=False, knowledge_enabled=False)
        assert "escalate" in with_esc
        assert "escalate" not in without_esc

    def test_knowledge_step_only_when_enabled(self):
        with_kb = _decision_tree(escalate_enabled=False, knowledge_enabled=True)
        without_kb = _decision_tree(escalate_enabled=False, knowledge_enabled=False)
        assert "knowledge_search" in with_kb
        assert "knowledge_search" not in without_kb

    def test_always_has_web_and_direct_answer_steps(self):
        tree = _decision_tree(escalate_enabled=False, knowledge_enabled=False)
        assert "web-search" in tree
        assert "trả lời trực tiếp" in tree
