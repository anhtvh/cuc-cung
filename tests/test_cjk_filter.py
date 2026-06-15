"""Guardrail ngôn ngữ — strip ký tự CJK rò vào output tiếng Việt (deterministic)."""

from unittest.mock import MagicMock

from app.core.chat_engine import ChatEngine, strip_cjk
from app.llm.base import Done, TextDelta, ToolDef
from tests.conftest import make_agent


# ─── unit: strip_cjk ─────────────────────────────────────────────────────────

class TestStripCjk:
    def test_removes_chinese_keeps_vietnamese(self):
        out, n = strip_cjk("cứ nhắn em 随时 nhé")
        assert "随" not in out and "时" not in out
        assert "cứ nhắn em" in out and "nhé" in out
        assert n == 2

    def test_counts_all_removed(self):
        out, n = strip_cjk("不客气")
        assert out == ""
        assert n == 3

    def test_clean_vietnamese_untouched(self):
        text = "Dạ không có gì anh/chị ạ! Chúc một ngày tốt lành."
        out, n = strip_cjk(text)
        assert out == text
        assert n == 0

    def test_emoji_and_diacritics_preserved(self):
        text = "Cảm ơn anh/chị nhé 😊🌸 — Đặng Thị Hồng"
        out, n = strip_cjk(text)
        assert out == text
        assert n == 0

    def test_empty(self):
        assert strip_cjk("") == ("", 0)


# ─── integration: stream lọc CJK trước khi gửi UI + lưu memory ───────────────

class _RecordingMemory:
    def __init__(self):
        self.appends = []

    def get_history(self, *a, **k):
        return []

    def search(self, *a, **k):
        return []

    def append(self, user_id, conv_id, agent_name, role, content):
        self.appends.append((role, content))


class _LeakingLLM:
    def chat_with_tools(self, system, messages, tools, execute, max_rounds=5, model=None, **kw):
        yield TextDelta("Dạ không có gì anh/chị ạ! Cứ nhắn em ")
        yield TextDelta("随时")  # rò tiếng Trung
        yield TextDelta(" nhé 😊")
        yield Done(stop_reason="end_turn")

    def chat(self, *a, **k):
        yield Done()

    def classify_json(self, *a, **k):
        return {}


class TestStreamFiltersCjk:
    def test_deltas_and_memory_have_no_cjk(self, agents, skills):
        mem = _RecordingMemory()
        catalog = MagicMock()
        catalog.tools_for.return_value = [ToolDef(name="system__noop", description="noop")]
        catalog.execute.return_value = None
        engine = ChatEngine(agents, skills, MagicMock(), mem, _LeakingLLM(), catalog)
        agent = make_agent(name="SubAgent", escalate_enabled=False)

        deltas = [
            ev["data"]["text"]
            for ev in engine.stream("u1", agent, "cảm ơn em", is_guest=False)
            if ev["event"] == "delta"
        ]
        joined = "".join(deltas)
        assert "随" not in joined and "时" not in joined
        assert "😊" in joined  # emoji giữ nguyên

        stored_assistant = [c for r, c in mem.appends if r == "assistant"]
        assert stored_assistant
        assert "随" not in stored_assistant[0] and "时" not in stored_assistant[0]
