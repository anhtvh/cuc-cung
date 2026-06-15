"""P1 stability fixes — regression tests.

Bao 4 sửa đổi ổn định:
- P1-1: builder LUÔN stream=False (không phụ thuộc builder_sla_seconds).
- P1-2: builder dùng trần tool-loop riêng (builder_max_tool_rounds), Flow 3 dùng max_tool_rounds.
- P1-3: self-test judge lỗi → inconclusive (KHÔNG tính PASS giả).
- P1-4: delegate/escalate luôn lưu đủ cặp user/assistant (không vỡ alternation).
"""

from unittest.mock import MagicMock

import pytest

from app.core.agent_test import AgentTester, TestCase
from app.core.chat_engine import ChatEngine
from app.core.models import MASTER_AGENT_NAME, Agent
from app.llm.base import Done, ToolCallEvent, ToolDef, ToolResult, ToolStartEvent
from tests.conftest import VALID_PROMPT, make_agent


def _master() -> Agent:
    return Agent(name=MASTER_AGENT_NAME, description="Master.", system_prompt=VALID_PROMPT)


def _engine(agents, skills, llm, *, builder_sla_seconds, builder_max_tool_rounds, max_tool_rounds=10):
    memory = MagicMock()
    memory.get_history.return_value = []
    memory.search.return_value = []
    memory.append.return_value = None
    usage = MagicMock()
    catalog = MagicMock()
    catalog.tools_for.return_value = [ToolDef(name="system__noop", description="noop")]
    return ChatEngine(
        agents, skills, usage, memory, llm, catalog,
        max_tool_rounds=max_tool_rounds,
        builder_sla_seconds=builder_sla_seconds,
        builder_max_tool_rounds=builder_max_tool_rounds,
    )


# ─── P1-1: stream=False tách khỏi SLA ────────────────────────────────────────

class TestBuilderStreamDecoupled:
    def test_builder_forces_non_stream_even_when_sla_disabled(self, agents, skills, fake_llm):
        """builder_sla_seconds=0 (tắt SLA) vẫn PHẢI stream=False — nếu không create_* mất input."""
        engine = _engine(agents, skills, fake_llm, builder_sla_seconds=0, builder_max_tool_rounds=20)
        list(engine.stream("u1", _master(), "giúp mình tạo agent mới nhé", is_guest=False))
        kw = fake_llm.tool_call_kwargs
        assert kw["stream"] is False
        assert kw["parallel_tools"] is False
        assert "sla_seconds" not in kw  # SLA tắt → không truyền

    def test_builder_passes_sla_when_set(self, agents, skills, fake_llm):
        engine = _engine(agents, skills, fake_llm, builder_sla_seconds=240, builder_max_tool_rounds=20)
        list(engine.stream("u1", _master(), "giúp mình tạo agent mới nhé", is_guest=False))
        kw = fake_llm.tool_call_kwargs
        assert kw["stream"] is False
        assert kw["sla_seconds"] == 240


# ─── P1-2: trần tool-loop riêng cho builder ──────────────────────────────────

class TestBuilderMaxRounds:
    def test_builder_uses_builder_rounds(self, agents, skills, fake_llm):
        engine = _engine(agents, skills, fake_llm, builder_sla_seconds=240, builder_max_tool_rounds=25, max_tool_rounds=10)
        list(engine.stream("u1", _master(), "giúp mình tạo agent mới nhé", is_guest=False))
        assert fake_llm.tool_call_kwargs["max_rounds"] == 25

    def test_flow3_agent_uses_default_rounds_and_stream(self, agents, skills, fake_llm):
        """Agent con (Flow 3): giữ stream mặc định (True → không truyền) và max_tool_rounds thường."""
        agent = make_agent(name="SubAgent", escalate_enabled=False)
        engine = _engine(agents, skills, fake_llm, builder_sla_seconds=240, builder_max_tool_rounds=25, max_tool_rounds=10)
        list(engine.stream("u1", agent, "một câu hỏi nghiệp vụ đủ dài", is_guest=False))
        kw = fake_llm.tool_call_kwargs
        assert "stream" not in kw          # default streaming
        assert kw["max_rounds"] == 10

    def test_guest_master_is_not_builder(self, agents, skills, fake_llm):
        """Master nhưng guest → không có tool ghi → KHÔNG ép cấu hình builder."""
        engine = _engine(agents, skills, fake_llm, builder_sla_seconds=240, builder_max_tool_rounds=25, max_tool_rounds=10)
        list(engine.stream("u1", _master(), "hỏi linh tinh chút nhé", is_guest=True))
        kw = fake_llm.tool_call_kwargs
        assert "stream" not in kw
        assert kw["max_rounds"] == 10


# ─── P1-4: delegate giữ cặp user/assistant ───────────────────────────────────

class _RecordingMemory:
    def __init__(self):
        self.appends: list[tuple[str, str]] = []

    def get_history(self, *a, **k):
        return []

    def search(self, *a, **k):
        return []

    def append(self, user_id, conv_id, agent_name, role, content):
        self.appends.append((role, content))


class _DelegatingLLM:
    """Mô phỏng agent con gọi escalate → yield ToolCallEvent có delegate_to."""

    def chat_with_tools(self, system, messages, tools, execute, max_rounds=5, model=None, **kwargs):
        yield ToolStartEvent(name="escalate", input={})
        yield ToolCallEvent(
            name="escalate",
            input={"reason": "ngoài lề", "original_message": "x"},
            result=ToolResult(content="Đang chuyển về Master.", delegate_to="master", delegate_message="m"),
        )
        # engine return ngay sau delegate → Done không bao giờ tới (đúng hành vi thật).

    def chat(self, *a, **k):
        yield Done()

    def classify_json(self, *a, **k):
        return {}


class TestDelegateAlternation:
    def test_delegate_stores_paired_assistant_marker(self, agents, skills):
        agent = make_agent(name="SubAgent", escalate_enabled=True)
        mem = _RecordingMemory()
        catalog = MagicMock()
        catalog.tools_for.return_value = [ToolDef(name="system__noop", description="noop")]
        catalog.execute.return_value = ToolResult(content="x")
        engine = ChatEngine(agents, skills, MagicMock(), mem, _DelegatingLLM(), catalog)

        list(engine.stream("u1", agent, "một câu hỏi ngoài chuyên môn dài", is_guest=False))

        roles = [r for r, _ in mem.appends]
        assert roles == ["user", "assistant"], "phải đủ cặp user/assistant, không để user mồ côi"
        assert mem.appends[1][1] == "[Đã chuyển sang @master]"


# ─── P1-3: judge lỗi → inconclusive, không PASS giả ──────────────────────────

class _FakeRunEngine:
    def run_once(self, **kwargs):
        return "câu trả lời mẫu của agent"


class _FailingJudge:
    def classify_json(self, *a, **k):
        raise RuntimeError("judge down")


class _PassJudge:
    def classify_json(self, *a, **k):
        return {"pass": True, "reason": "đạt"}


class _FailJudge:
    def classify_json(self, *a, **k):
        return {"pass": False, "reason": "thiếu nội dung"}


class TestSelfTestJudge:
    def test_judge_failure_is_inconclusive_not_pass(self):
        tester = AgentTester(_FakeRunEngine(), _FailingJudge(), judge_model="m")
        report = tester.run_tests(make_agent(), [TestCase("hỏi gì đó", "kỳ vọng")])
        assert report.passed == 0
        assert report.failed == 0
        assert report.inconclusive == 1
        assert report.all_passed is False  # KHÔNG báo đạt khi chưa kiểm chứng được
        assert report.has_inconclusive

    def test_judge_pass_marks_all_passed(self):
        tester = AgentTester(_FakeRunEngine(), _PassJudge(), judge_model="m")
        report = tester.run_tests(make_agent(), [TestCase("hỏi gì đó", "kỳ vọng")])
        assert report.all_passed is True
        assert report.inconclusive == 0

    def test_judge_fail_is_failed_not_inconclusive(self):
        tester = AgentTester(_FakeRunEngine(), _FailJudge(), judge_model="m")
        report = tester.run_tests(make_agent(), [TestCase("hỏi gì đó", "kỳ vọng")])
        assert report.failed == 1
        assert report.inconclusive == 0
        assert report.all_passed is False

    def test_judge_prompt_includes_today_so_no_future_false_fail(self):
        """#2: judge phải biết ngày hôm nay để không tưởng mốc gần đây là 'tương lai/bịa'."""
        from datetime import datetime, timedelta, timezone

        class _CapturingJudge:
            system = None

            def classify_json(self, system, message, schema_hint, model=None):
                self.system = system
                return {"pass": True, "reason": "ok"}

        judge = _CapturingJudge()
        AgentTester(_FakeRunEngine(), judge, judge_model="m").run_tests(
            make_agent(), [TestCase("tin hôm nay", "kỳ vọng")]
        )
        today = datetime.now(timezone(timedelta(hours=7))).date().isoformat()
        assert today in judge.system
        assert "tương lai" in judge.system.lower() or "hôm nay" in judge.system.lower()
