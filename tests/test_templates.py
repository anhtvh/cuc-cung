"""Test thư viện mẫu agent (#8): loader, master tool list/apply, guest, blocked-set."""

import json

import pytest

from app.builder import templates as tpl_mod
from app.builder.master import _GUEST_BLOCKED_TOOLS, GUEST_MASTER_TOOLS, MasterToolset
from app.builder.templates import get_template, list_template_cards


class TestTemplateLoader:
    def test_loads_seed_templates(self):
        keys = {c["key"] for c in list_template_cards()}
        assert {"internal-lookup", "report-writer", "cskh-faq", "doc-summarizer"} <= keys

    def test_card_payload_is_light(self):
        # Thẻ UI chỉ chứa field nhẹ — KHÔNG kèm persona/skill (tránh SSE nặng).
        for card in list_template_cards():
            assert set(card.keys()) == {"key", "title", "icon", "description"}

    def test_personas_meet_governance_min(self):
        # Mọi persona ≥200 ký tự để apply không bị create_agent từ chối.
        for c in list_template_cards():
            t = get_template(c["key"])
            assert t is not None and len(t.persona_template) >= 200

    def test_get_template_unknown(self):
        assert get_template("khong-ton-tai") is None

    def test_invalid_template_skipped(self, tmp_path, monkeypatch):
        # File lỗi schema / JSON hỏng / persona ngắn → bị bỏ qua, KHÔNG làm chết loader.
        (tmp_path / "ok.json").write_text(json.dumps({
            "key": "ok", "title": "OK", "description": "d", "persona_template": "x" * 200,
        }), encoding="utf-8")
        (tmp_path / "bad.json").write_text("{ not json", encoding="utf-8")
        (tmp_path / "short.json").write_text(json.dumps({
            "key": "short", "title": "S", "description": "d", "persona_template": "too short",
        }), encoding="utf-8")
        monkeypatch.setattr(tpl_mod, "_TEMPLATES_DIR", tmp_path)
        loaded = tpl_mod._load()
        assert set(loaded) == {"ok"}


def _toolset(agents, skills, governance, is_guest=False):
    return MasterToolset(agents, skills, governance, catalog=None, user_id="u1", is_guest=is_guest)


class TestMasterTemplateTools:
    def test_list_templates(self, agents, skills, governance):
        res = _toolset(agents, skills, governance).execute("list_templates", {})
        assert not res.is_error
        assert len(json.loads(res.content)["templates"]) >= 4

    def test_apply_template_returns_blueprint(self, agents, skills, governance):
        ts = _toolset(agents, skills, governance)
        before = (len(agents.list()), len(skills.list()))
        res = ts.execute("apply_template", {"key": "report-writer"})
        assert not res.is_error
        bp = json.loads(res.content)
        assert bp["key"] == "report-writer"
        assert len(bp["persona_template"]) >= 200
        assert bp["suggested_connectors"] == ["file-export"]
        assert bp["skill_drafts"] and "content" in bp["skill_drafts"][0]
        # KHÔNG ghi registry — read-only.
        assert (len(agents.list()), len(skills.list())) == before

    def test_apply_template_unknown_key(self, agents, skills, governance):
        res = _toolset(agents, skills, governance).execute("apply_template", {"key": "khong-co"})
        assert res.is_error

    def test_guest_can_browse_templates(self, agents, skills, governance):
        # Read-only → guest được phép (không nằm trong _GUEST_BLOCKED_TOOLS).
        ts = _toolset(agents, skills, governance, is_guest=True)
        assert not ts.execute("list_templates", {}).is_error
        assert not ts.execute("apply_template", {"key": "cskh-faq"}).is_error

    def test_guest_still_blocked_from_create(self, agents, skills, governance):
        ts = _toolset(agents, skills, governance, is_guest=True)
        assert ts.execute("create_agent", {"name": "X", "description": "d", "system_prompt": "p"}).is_error


class TestBlockedSet:
    def test_templates_not_blocked_for_guest(self):
        assert "list_templates" not in _GUEST_BLOCKED_TOOLS
        assert "apply_template" not in _GUEST_BLOCKED_TOOLS
        names = {t.name for t in GUEST_MASTER_TOOLS}
        assert {"list_templates", "apply_template"} <= names
