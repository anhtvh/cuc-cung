"""Test endpoint GET /templates (#8) — read-only, payload nhẹ cho UI dựng thẻ chọn nhanh.

Gọi thẳng router function (không boot cả app): endpoint chỉ wrap list_template_cards,
phần loader/tool đã có ở test_templates.py.
"""

from app.api.templates import get_templates
from app.builder.templates import list_template_cards


class TestTemplatesEndpoint:
    def test_returns_template_list(self):
        body = get_templates()
        assert "templates" in body
        assert body["templates"] == list_template_cards()

    def test_payload_is_light(self):
        # Đồng nhất với thẻ UI — chỉ field nhẹ, KHÔNG kèm persona/skill.
        for card in get_templates()["templates"]:
            assert set(card.keys()) == {"key", "title", "icon", "description"}

    def test_has_seed_templates(self):
        keys = {c["key"] for c in get_templates()["templates"]}
        assert {"internal-lookup", "report-writer", "cskh-faq", "doc-summarizer"} <= keys
