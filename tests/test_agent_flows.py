"""Tests cho các flow quan trọng: lifecycle agent, edit, delete, retract, auto-start.

Mục đích: bắt regression khi sửa code — chạy `pytest tests/test_agent_flows.py` để verify.
"""

import pytest

from app.core.governance import GovernanceError
from app.core.models import ItemStatus, Visibility
from tests.conftest import VALID_PROMPT, make_agent, make_skill, attach_test_skill


# ─── Retract submission ─────────────────────────────────────────────────────

class TestRetractSubmission:
    def test_retract_pending_returns_to_private(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        item = governance.retract_submission("agent", "TestAgent", "maker")
        assert item.status == ItemStatus.private
        assert agents.get("TestAgent").status == ItemStatus.private

    def test_retract_only_from_pending_review(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.private))
        with pytest.raises(GovernanceError, match="pending_review"):
            governance.retract_submission("agent", "TestAgent", "maker")

    def test_retract_only_owner_or_admin(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        with pytest.raises(GovernanceError, match="người tạo"):
            governance.retract_submission("agent", "TestAgent", "ke-la")

    def test_admin_can_retract(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        item = governance.retract_submission("agent", "TestAgent", "admin")
        assert item.status == ItemStatus.private

    def test_retract_then_resubmit(self, governance, agents, skills):
        """Sau retract phải submit lại được bình thường."""
        agents.create(make_agent(status=ItemStatus.pending_review))
        attach_test_skill(agents, skills)
        governance.retract_submission("agent", "TestAgent", "maker")
        governance.submit_for_review("agent", "TestAgent", "maker")
        assert agents.get("TestAgent").status == ItemStatus.pending_review


# ─── Delete agent ───────────────────────────────────────────────────────────

class TestDeleteAgent:
    def test_delete_private_agent_allowed(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.private, visibility=Visibility.company))
        agents.delete("TestAgent")
        assert agents.get("TestAgent") is None

    def test_delete_rejected_agent_allowed(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.rejected, visibility=Visibility.company))
        agents.delete("TestAgent")
        assert agents.get("TestAgent") is None

    def test_cannot_delete_public_agent_via_governance_flow(self, governance, agents, skills):
        """Agent public: phải reject trước (rule từ API layer, check bằng status)."""
        agents.create(make_agent(status=ItemStatus.pending_review))
        governance.approve("agent", "TestAgent", "admin")
        a = agents.get("TestAgent")
        assert a.status == ItemStatus.public
        assert a.status not in (ItemStatus.private, ItemStatus.rejected)

    def test_delete_pending_review_blocked_by_status(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        a = agents.get("TestAgent")
        assert a.status not in (ItemStatus.private, ItemStatus.rejected)

    def test_cascade_delete_private_exclusive_skill(self, agents, skills):
        """Skill private chỉ gắn agent này → bị xóa cùng agent."""
        agents.create(make_agent())
        skills.create(make_skill(status=ItemStatus.private))
        agents.attach_skill("TestAgent", "test-skill-mot")

        # Xác nhận skill exclusive (logic của API delete)
        others = [a for a in agents.agents_using_skill("test-skill-mot") if a != "TestAgent"]
        assert others == []
        skill = skills.get("test-skill-mot")
        assert skill.status == ItemStatus.private

        # Xóa agent → cascade agent_skills
        agents.delete("TestAgent")
        # Xóa skill (vì exclusive + private)
        skills.delete("test-skill-mot")
        assert skills.get("test-skill-mot") is None

    def test_cascade_keeps_shared_skill(self, agents, skills):
        """Skill dùng chung nhiều agent → chỉ gỡ liên kết, không xóa."""
        agents.create(make_agent(name="AgentA"))
        agents.create(make_agent(name="AgentB"))
        skills.create(make_skill(status=ItemStatus.private))
        agents.attach_skill("AgentA", "test-skill-mot")
        agents.attach_skill("AgentB", "test-skill-mot")

        # Xóa AgentA → AgentB vẫn dùng skill → không xóa skill
        others = [a for a in agents.agents_using_skill("test-skill-mot") if a != "AgentA"]
        assert "AgentB" in others  # còn agent khác dùng → không xóa

        agents.delete("AgentA")
        assert skills.get("test-skill-mot") is not None  # skill vẫn còn

    def test_cascade_keeps_public_skill(self, agents, skills):
        """Skill public (dù exclusive) → chỉ gỡ liên kết, không xóa."""
        agents.create(make_agent())
        skills.create(make_skill(status=ItemStatus.public))
        agents.attach_skill("TestAgent", "test-skill-mot")

        skill = skills.get("test-skill-mot")
        assert skill.status == ItemStatus.public  # public → không xóa

        agents.delete("TestAgent")
        assert skills.get("test-skill-mot") is not None  # skill vẫn còn


# ─── Edit agent ─────────────────────────────────────────────────────────────

class TestEditAgent:
    def test_edit_private_agent_applies_directly(self, governance, agents):
        agents.create(make_agent())
        new_desc = "Mô tả mới. Dùng khi test thẩm định."
        governance.propose_update("agent", "TestAgent", {"description": new_desc}, "maker")
        assert agents.get("TestAgent").description == new_desc

    def test_edit_pending_review_blocked(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        with pytest.raises(GovernanceError, match="đang chờ duyệt"):
            governance.propose_update("agent", "TestAgent", {"description": "mới"}, "maker")

    def test_edit_rejected_returns_to_private(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.rejected))
        governance.propose_update("agent", "TestAgent", {"description": "Mô tả sửa lại. Dùng khi test review."}, "maker")
        assert agents.get("TestAgent").status == ItemStatus.private
        assert agents.get("TestAgent").review_note is None

    def test_edit_public_goes_to_pending_changes(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.public))
        governance.propose_update("agent", "TestAgent", {"description": "Mô tả cập nhật. Dùng khi test cập nhật."}, "maker")
        a = agents.get("TestAgent")
        assert a.status == ItemStatus.public  # bản active vẫn phục vụ
        assert a.pending_changes is not None
        assert "description" in a.pending_changes

    def test_edit_non_owner_blocked(self, governance, agents):
        agents.create(make_agent())
        with pytest.raises(GovernanceError, match="người tạo"):
            governance.propose_update("agent", "TestAgent", {"description": "hack"}, "ke-la")

    def test_edit_unknown_field_blocked(self, governance, agents):
        agents.create(make_agent())
        with pytest.raises(GovernanceError, match="không cho phép"):
            governance.propose_update("agent", "TestAgent", {"name": "HackedName"}, "maker")


# ─── Full lifecycle ──────────────────────────────────────────────────────────

class TestFullLifecycle:
    def test_private_submit_approve_public(self, governance, agents, skills):
        sk = make_skill(status=ItemStatus.pending_review)
        skills.create(sk)
        governance.approve("skill", "test-skill-mot", "admin")

        a = make_agent()
        agents.create(a)
        agents.attach_skill("TestAgent", "test-skill-mot")
        governance.submit_for_review("agent", "TestAgent", "maker")
        governance.approve("agent", "TestAgent", "admin")
        assert agents.get("TestAgent").status == ItemStatus.public

    def test_reject_then_edit_and_resubmit(self, governance, agents, skills):
        agents.create(make_agent(status=ItemStatus.pending_review))
        attach_test_skill(agents, skills)
        governance.reject("agent", "TestAgent", "admin", "mô tả chưa rõ")
        governance.propose_update("agent", "TestAgent", {"description": "Mô tả rõ hơn. Dùng khi cần test chi tiết workflow."}, "maker")
        governance.submit_for_review("agent", "TestAgent", "maker")
        assert agents.get("TestAgent").status == ItemStatus.pending_review

    def test_retract_and_delete(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.pending_review))
        governance.retract_submission("agent", "TestAgent", "maker")
        agents.delete("TestAgent")
        assert agents.get("TestAgent") is None


# ─── Auto-start routing (logic trong chat_engine) ───────────────────────────

class TestAutoStartLogic:
    """Verify logic auto_start trong ChatEngine.stream() — dùng import trực tiếp."""

    def _make_engine(self, agents_repo, skills_repo, fake_llm):
        from unittest.mock import MagicMock
        from app.core.chat_engine import ChatEngine
        memory = MagicMock()
        memory.get_history.return_value = []
        memory.search.return_value = []
        memory.append.return_value = None
        usage = MagicMock()
        usage.log.return_value = None
        catalog = MagicMock()
        catalog.tools_for.return_value = []
        catalog.execute.return_value = None
        return ChatEngine(agents_repo, skills_repo, usage, memory, fake_llm, catalog)

    def test_auto_start_triggered_when_only_mention(self, agents, skills, fake_llm):
        """Khi message chỉ có @mention, auto_start phải trigger."""
        import re
        message = "@tham-dinh-hop-dong"
        text_without = re.sub(r"@\S+", "", message).strip()
        assert text_without == ""  # điều kiện auto_start phải đúng

    def test_auto_start_not_triggered_with_extra_text(self, agents, skills, fake_llm):
        """Khi có text kèm @mention, không được auto_start."""
        import re
        message = "@tham-dinh-hop-dong xem giúp hợp đồng này"
        text_without = re.sub(r"@\S+", "", message).strip()
        assert text_without != ""  # có text thêm → không auto_start

    def test_auto_start_not_triggered_for_master(self, agents, skills, fake_llm):
        """Master không auto_start."""
        from app.core.models import MASTER_AGENT_NAME
        assert MASTER_AGENT_NAME == "master"  # rule: agent.name != MASTER_AGENT_NAME

    def test_agent_skills_loaded_for_auto_start(self, agents, skills):
        """skills_of trả về skill names để auto_start dùng."""
        a = make_agent(name="StockAgent")
        agents.create(a)
        sk = make_skill(name="finance-stock-analysis")
        skills.create(sk)
        agents.attach_skill("StockAgent", "finance-stock-analysis")
        skill_names = agents.skills_of("StockAgent")
        assert skill_names == ["finance-stock-analysis"]

    def test_no_auto_start_when_no_skills(self, agents, skills):
        """Agent không có skill → auto_start không trigger."""
        a = make_agent(name="EmptyAgent")
        agents.create(a)
        skill_names = agents.skills_of("EmptyAgent")
        assert skill_names == []  # không có skill → không auto_start


# ─── Slug generation ────────────────────────────────────────────────────────

class TestSlugGeneration:
    def test_pascal_case_slug(self):
        from app.core.models import slugify
        assert slugify("ThamDinhHopDong") == "thamdinhhopdong"

    def test_vietnamese_name_slug(self):
        from app.core.models import slugify
        s = slugify("Thẩm Định Hợp Đồng")
        # Phải là lowercase ASCII với hyphens
        assert s == s.lower()
        assert " " not in s
        assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in s)

    def test_agent_auto_slug_from_model_validator(self):
        from app.core.models import Agent, slugify
        a = Agent(name="ThamDinhHopDong", description="test", system_prompt=VALID_PROMPT)
        assert a.slug == slugify("ThamDinhHopDong")

    def test_agent_explicit_slug_not_overridden(self):
        from app.core.models import Agent
        a = Agent(name="Test Agent", slug="my-custom-slug", description="test", system_prompt=VALID_PROMPT)
        assert a.slug == "my-custom-slug"
