"""Test CapabilityResolver (seam plug-and-play A2).

Khoá hành vi: profile chỉ có hiệu lực khi experimental bật; gated_tools độc lập cờ; agent
không đăng ký → rỗng (không đổi gì).
"""

from app.core.capabilities import EMPTY_PROFILE, CapabilityResolver


def test_unknown_agent_returns_empty_profile_either_way():
    for enabled in (True, False):
        r = CapabilityResolver(experimental_enabled=enabled)
        assert r.active_profile("KhongCo") is EMPTY_PROFILE
        assert r.gated_tools("KhongCo") == frozenset()


def test_gated_tools_independent_of_flag():
    # gated_tools phải trả tập tool dù experimental TẮT — để engine ẩn chúng ở flow gốc.
    expected = frozenset({
        "partner-integration__save_file",
        "partner-integration__list_workspace",
        "partner-integration__package_project",
    })
    assert CapabilityResolver(experimental_enabled=False).gated_tools("Upia") == expected
    assert CapabilityResolver(experimental_enabled=True).gated_tools("Upia") == expected


def test_active_profile_gated_by_flag():
    # Tắt → EMPTY (không note/RAG/tuning).
    assert CapabilityResolver(experimental_enabled=False).active_profile("Upia") is EMPTY_PROFILE
    # Bật → profile thật.
    p = CapabilityResolver(experimental_enabled=True).active_profile("Upia")
    assert p.large_doc_rag is True
    assert p.rag_min_chars == 8000
    assert p.execution is not None
    assert p.execution.stream is False
    assert p.execution.parallel_tools is True
    assert len(p.extra_system_notes) == 1
    assert p.extra_system_notes[0].name == "experimental_mode.md"


def test_experimental_note_file_exists():
    # Note path phải trỏ file thật (tránh entry chết khi đổi cấu trúc thư mục).
    p = CapabilityResolver(experimental_enabled=True).active_profile("Upia")
    assert p.extra_system_notes[0].is_file()
