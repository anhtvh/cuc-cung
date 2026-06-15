"""P2-2: SLA 2 tầng — soft gỡ tool mạng chậm, hard cắt sạch."""

from app.llm.anthropic_client import _is_slow_tool, _round_tools_for_elapsed

_TOOLS = [
    {"name": "web-search__search", "description": "", "input_schema": {}},
    {"name": "web-search__fetch", "description": "", "input_schema": {}},
    {"name": "knowledge_search", "description": "", "input_schema": {}},
    {"name": "system__get_current_date", "description": "", "input_schema": {}},
]


def _names(tools):
    return [t["name"] for t in tools] if tools else None


def test_is_slow_tool():
    assert _is_slow_tool("web-search__search")
    assert _is_slow_tool("web-search__fetch")
    assert not _is_slow_tool("knowledge_search")
    assert not _is_slow_tool("system__get_current_date")


def test_no_sla_always_full_tools():
    tools, hard = _round_tools_for_elapsed(_TOOLS, None, elapsed=99999)
    assert tools == _TOOLS
    assert hard is False


def test_under_sla_full_tools():
    tools, hard = _round_tools_for_elapsed(_TOOLS, effective_sla=55, elapsed=10)
    assert _names(tools) == _names(_TOOLS)
    assert hard is False


def test_soft_sla_drops_slow_keeps_fast():
    tools, hard = _round_tools_for_elapsed(_TOOLS, effective_sla=55, elapsed=60)
    names = _names(tools)
    assert "web-search__search" not in names
    assert "web-search__fetch" not in names
    assert "knowledge_search" in names
    assert "system__get_current_date" in names
    assert hard is False  # soft KHÔNG ép dừng


def test_hard_sla_cuts_all_and_signals_break():
    tools, hard = _round_tools_for_elapsed(_TOOLS, effective_sla=55, elapsed=90)  # > 1.5*55
    assert tools is None
    assert hard is True


def test_soft_sla_with_only_slow_tools_returns_none():
    only_slow = [t for t in _TOOLS if t["name"].startswith("web-search")]
    tools, hard = _round_tools_for_elapsed(only_slow, effective_sla=55, elapsed=60)
    assert tools is None
    assert hard is False  # vẫn không phải hard → model trả lời tay không, vòng sau hard chặn
