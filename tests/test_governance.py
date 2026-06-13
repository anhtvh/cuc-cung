"""State machine maker-checker (Flow 2b) + skill lifecycle (Flow 4) — phần dễ vỡ nhất."""

import pytest

from app.core.governance import GovernanceError
from app.core.models import ItemStatus

from tests.conftest import make_agent, make_skill, attach_test_skill


def test_full_lifecycle_private_to_public(governance, agents, skills):
    agents.create(make_agent())
    attach_test_skill(agents, skills)
    governance.submit_for_review("agent", "TestAgent", "maker")
    assert agents.get("TestAgent").status == ItemStatus.pending_review
    # skill phải active trước khi agent active (Flow 2b)
    governance.submit_for_review("skill", "test-skill-mot", "maker")
    governance.approve("skill", "test-skill-mot", "admin")
    governance.approve("agent", "TestAgent", "admin")
    assert agents.get("TestAgent").status == ItemStatus.public


def test_edit_visibility_on_draft_no_crash(governance, agents):
    """Regression Bug#2: sửa visibility agent draft phải coerce enum, không gán str (repo.update nổ .value)."""
    from app.core.models import Visibility
    agents.create(make_agent(visibility=Visibility.private))
    governance.propose_update("agent", "TestAgent", {"visibility": "company"}, "maker")
    got = agents.get("TestAgent")
    assert got.visibility == Visibility.company
    assert isinstance(got.visibility, Visibility)  # KHÔNG phải str


def test_approve_visibility_pending_change_no_crash(governance, agents):
    """Regression Bug#2: approve pending_changes chứa visibility (str) phải coerce về enum."""
    from app.core.models import Visibility
    agents.create(make_agent(status=ItemStatus.public, visibility=Visibility.private))
    governance.propose_update("agent", "TestAgent", {"visibility": "company"}, "maker")
    assert agents.get("TestAgent").pending_changes == {"visibility": "company"}
    governance.approve("agent", "TestAgent", "admin")
    got = agents.get("TestAgent")
    assert got.visibility == Visibility.company
    assert isinstance(got.visibility, Visibility)
    assert got.pending_changes is None


def test_submit_promotes_private_agent_to_company(governance, agents, skills):
    """Regression #3: submit agent visibility=private → nâng company (submit = ý định chia sẻ);
    sau approve người khác phải dùng được, không kẹt public+private."""
    from app.core.models import Visibility
    agents.create(make_agent(visibility=Visibility.private))
    attach_test_skill(agents, skills)
    governance.submit_for_review("agent", "TestAgent", "maker")
    assert agents.get("TestAgent").visibility == Visibility.company  # đã nâng khi submit
    governance.submit_for_review("skill", "test-skill-mot", "maker")
    governance.approve("skill", "test-skill-mot", "admin")
    governance.approve("agent", "TestAgent", "admin")
    approved = agents.get("TestAgent")
    assert approved.status == ItemStatus.public and approved.visibility == Visibility.company
    assert governance.can_use_agent(approved, "nguoi-khac") is True  # cả công ty thấy


def test_submit_only_from_private(governance, agents):
    agents.create(make_agent(status=ItemStatus.public))
    with pytest.raises(GovernanceError, match="private"):
        governance.submit_for_review("agent", "TestAgent", "maker")


def test_submit_only_owner_or_admin(governance, agents, skills):
    agents.create(make_agent())
    attach_test_skill(agents, skills)
    with pytest.raises(GovernanceError, match="người tạo"):
        governance.submit_for_review("agent", "TestAgent", "ke-la")
    governance.submit_for_review("agent", "TestAgent", "admin")  # admin được


def test_submit_agent_requires_skill(governance, agents):
    """Ràng buộc mới: agent 0 skill không submit được."""
    agents.create(make_agent())
    with pytest.raises(GovernanceError, match="chưa gắn skill"):
        governance.submit_for_review("agent", "TestAgent", "maker")


def test_approve_requires_admin(governance, agents):
    agents.create(make_agent(status=ItemStatus.pending_review))
    with pytest.raises(GovernanceError, match="admin"):
        governance.approve("agent", "TestAgent", "maker")


def test_agent_approve_blocked_by_non_active_skill(governance, agents, skills):
    """Ràng buộc approve: MỌI skill agent gắn phải active."""
    agents.create(make_agent(status=ItemStatus.pending_review))
    skills.create(make_skill())  # draft
    agents.attach_skill("TestAgent", "test-skill-mot")
    with pytest.raises(GovernanceError, match="chưa active"):
        governance.approve("agent", "TestAgent", "admin")
    # duyệt skill xong thì agent qua
    skills_item = skills.get("test-skill-mot")
    skills_item.status = ItemStatus.pending_review
    skills.update(skills_item)
    governance.approve("skill", "test-skill-mot", "admin")
    governance.approve("agent", "TestAgent", "admin")
    assert agents.get("TestAgent").status == ItemStatus.public


def test_reject_requires_reason_and_is_not_terminal(governance, agents, skills):
    agents.create(make_agent(status=ItemStatus.pending_review))
    attach_test_skill(agents, skills)
    with pytest.raises(GovernanceError, match="lý do"):
        governance.reject("agent", "TestAgent", "admin", "  ")
    governance.reject("agent", "TestAgent", "admin", "description chưa rõ dùng khi nào")
    a = agents.get("TestAgent")
    assert a.status == ItemStatus.rejected
    assert a.review_note == "description chưa rõ dùng khi nào"
    # maker sửa theo lý do → quay về private → submit lại
    governance.propose_update("agent", "TestAgent", {"description": "Mô tả mới rõ ràng hơn."}, "maker")
    assert agents.get("TestAgent").status == ItemStatus.private
    governance.submit_for_review("agent", "TestAgent", "maker")


def test_edit_active_goes_to_pending_changes(governance, skills):
    """Flow 4: active → sửa vào pending_changes, bản active VẪN phục vụ; duyệt → version+1."""
    skills.create(make_skill(status=ItemStatus.public))
    governance.propose_update(
        "skill", "test-skill-mot", {"content": "# Quy trình v2\n1. Bước mới."}, "maker"
    )
    s = skills.get("test-skill-mot")
    assert s.status == ItemStatus.public
    assert s.content.startswith("# Quy trình test")  # bản chạy chưa đổi
    assert s.pending_changes == {"content": "# Quy trình v2\n1. Bước mới."}

    governance.approve("skill", "test-skill-mot", "admin")
    s = skills.get("test-skill-mot")
    assert s.content.startswith("# Quy trình v2")
    assert s.version == 2
    assert s.pending_changes is None


def test_reject_pending_changes_keeps_active_version(governance, skills):
    skills.create(make_skill(status=ItemStatus.public))
    governance.propose_update("skill", "test-skill-mot", {"content": "# xấu"}, "maker")
    governance.reject("skill", "test-skill-mot", "admin", "nội dung sai quy trình")
    s = skills.get("test-skill-mot")
    assert s.status == ItemStatus.public
    assert s.pending_changes is None
    assert s.version == 1
    assert s.content.startswith("# Quy trình test")


def test_edit_pending_review_blocked(governance, agents):
    agents.create(make_agent(status=ItemStatus.pending_review))
    with pytest.raises(GovernanceError, match="chờ duyệt"):
        governance.propose_update("agent", "TestAgent", {"description": "x"}, "maker")


def test_visible_agents_visibility(governance, agents):
    """Flow 1: public+company cho mọi người; private chỉ owner."""
    agents.create(make_agent(name="CongKhai", status=ItemStatus.public, created_by="x"))
    agents.create(make_agent(name="PrivateCuaMaker", status=ItemStatus.private, created_by="maker"))
    agents.create(
        make_agent(name="RiengCuaMaker", status=ItemStatus.public, created_by="maker", visibility="private")
    )
    names_maker = {a.name for a in governance.visible_agents("maker")}
    assert names_maker == {"CongKhai", "PrivateCuaMaker", "RiengCuaMaker"}
    names_other = {a.name for a in governance.visible_agents("nguoi-khac")}
    assert names_other == {"CongKhai"}
