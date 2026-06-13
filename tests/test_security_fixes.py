"""Test khóa các fix bảo mật/hành vi (review nghịch lý user flow).

Bao phủ:
- attach_skill không cho gắn skill private của người khác (chống rò rỉ nội dung skill).
- propose_update hạ visibility 'public→private' không crash (Visibility enum không có 'public').
- build_system_prompt bỏ qua skill 'rejected'.
"""

import pytest

from app.builder.master import MasterToolset
from app.core.governance import Governance
from app.core.models import ItemStatus, Visibility
from app.tools.catalog import ToolCatalog

from tests.conftest import make_agent, make_skill


def _toolset(agents, skills, governance, user_id):
    return MasterToolset(
        agents=agents,
        skills=skills,
        governance=governance,
        catalog=ToolCatalog(providers=[]),
        user_id=user_id,
    )


class TestAttachSkillPermission:
    def test_cannot_attach_others_private_skill(self, governance, agents, skills):
        """Maker A không được gắn skill private của user B vào agent của mình."""
        agents.create(make_agent(name="AgentCuaA", created_by="A"))
        skills.create(make_skill(name="bi-mat-cua-b", created_by="B", status=ItemStatus.private))
        ts = _toolset(agents, skills, governance, user_id="A")
        res = ts.execute("attach_skill", {"agent_name": "AgentCuaA", "skill_name": "bi-mat-cua-b"})
        assert res.is_error
        assert "private" in res.content.lower()
        assert "bi-mat-cua-b" not in agents.skills_of("AgentCuaA")

    def test_can_attach_public_skill(self, governance, agents, skills):
        agents.create(make_agent(name="AgentCuaA", created_by="A"))
        skills.create(make_skill(name="skill-cong-khai", created_by="B", status=ItemStatus.public))
        ts = _toolset(agents, skills, governance, user_id="A")
        res = ts.execute("attach_skill", {"agent_name": "AgentCuaA", "skill_name": "skill-cong-khai"})
        assert not res.is_error
        assert "skill-cong-khai" in agents.skills_of("AgentCuaA")

    def test_can_attach_own_private_skill(self, governance, agents, skills):
        agents.create(make_agent(name="AgentCuaA", created_by="A"))
        skills.create(make_skill(name="skill-cua-a", created_by="A", status=ItemStatus.private))
        ts = _toolset(agents, skills, governance, user_id="A")
        res = ts.execute("attach_skill", {"agent_name": "AgentCuaA", "skill_name": "skill-cua-a"})
        assert not res.is_error
        assert "skill-cua-a" in agents.skills_of("AgentCuaA")

    def test_admin_can_attach_any_skill(self, governance, agents, skills):
        agents.create(make_agent(name="AgentCuaAdmin", created_by="admin"))
        skills.create(make_skill(name="bi-mat-cua-b", created_by="B", status=ItemStatus.private))
        ts = _toolset(agents, skills, governance, user_id="admin")
        res = ts.execute("attach_skill", {"agent_name": "AgentCuaAdmin", "skill_name": "bi-mat-cua-b"})
        assert not res.is_error


class TestLowerVisibilityNoCrash:
    def test_public_agent_lower_to_private_applies_immediately(self, governance, agents):
        """Hạ visibility public→private áp dụng ngay, KHÔNG ném AttributeError (Visibility.public)."""
        agents.create(make_agent(status=ItemStatus.public, visibility=Visibility.company))
        item = governance.propose_update("agent", "TestAgent", {"visibility": "private"}, "maker")
        assert item.visibility == Visibility.private
        assert item.status == ItemStatus.public  # vẫn active, chỉ siết phạm vi

    def test_public_agent_edit_other_field_with_visibility_company(self, governance, agents):
        """Sửa field khác kèm visibility='company' → vào pending_changes, không crash."""
        agents.create(make_agent(status=ItemStatus.public, visibility=Visibility.company))
        item = governance.propose_update(
            "agent", "TestAgent",
            {"visibility": "company", "description": "Mô tả mới rõ ràng. Dùng khi cần test."},
            "maker",
        )
        assert item.pending_changes  # thay đổi chờ duyệt
        assert item.status == ItemStatus.public

    def test_invalid_visibility_rejected(self, governance, agents):
        agents.create(make_agent(status=ItemStatus.public, visibility=Visibility.company))
        from app.core.governance import GovernanceError
        with pytest.raises(GovernanceError, match="visibility"):
            governance.propose_update("agent", "TestAgent", {"visibility": "world"}, "maker")
