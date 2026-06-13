"""Validate phía app — không tin model (Flow 2) + dedup hard-block (Flow 2b)."""

import pytest

from app.core.governance import GovernanceError

from tests.conftest import VALID_PROMPT, make_skill


def test_agent_name_convention(governance):
    # bad: quá ngắn hoặc khoảng trắng đầu/cuối → "không hợp lệ" hoặc "khoảng trắng thừa" (I-04)
    for bad in ["", "a", " BeBo", "BeBo ", " "]:
        with pytest.raises(GovernanceError, match="không hợp lệ|khoảng trắng"):
            governance.validate_agent_payload(bad, "Mô tả.", VALID_PROMPT, [])
    # double-space: I-04 phải reject
    with pytest.raises(GovernanceError, match="khoảng trắng"):
        governance.validate_agent_payload("Bé  Bơ", "Mô tả.", VALID_PROMPT, [])
    # good: ASCII PascalCase, tiếng Việt có dấu, tên có khoảng trắng
    governance.validate_agent_payload("ThamDinhHopDong", "Mô tả.", VALID_PROMPT, [])
    governance.validate_agent_payload("Bé Bơ", "Mô tả.", VALID_PROMPT, [])
    governance.validate_agent_payload("có dấu", "Mô tả.", VALID_PROMPT, [])


def test_skill_name_convention(governance):
    for bad in ["LegalThamDinh", "legal", "legal_tham_dinh", "-legal-x"]:
        with pytest.raises(GovernanceError, match="convention"):
            governance.validate_skill_payload(bad, "Mô tả.", "# nội dung")
    governance.validate_skill_payload("legal-tham-dinh-hop-dong", "Mô tả.", "# nội dung")


def test_prompt_min_length(governance):
    with pytest.raises(GovernanceError, match="quá ngắn"):
        governance.validate_agent_payload("TestAgent", "Mô tả.", "ngắn quá", [])


def test_secret_patterns_blocked(governance):
    for leaked in [
        "prompt chứa sk-abcdefghijklmnop1234 nguy hiểm" + VALID_PROMPT,
        VALID_PROMPT + "\napi_key = supersecret123",
        VALID_PROMPT + "\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz123",
    ]:
        with pytest.raises(GovernanceError, match="secret"):
            governance.validate_agent_payload("TestAgent", "Mô tả.", leaked, [])


def test_connector_must_exist_in_catalog(governance):
    with pytest.raises(GovernanceError, match="catalog"):
        governance.validate_agent_payload("TestAgent", "Mô tả.", VALID_PROMPT, ["khong-ton-tai"])
    governance.validate_agent_payload("TestAgent", "Mô tả.", VALID_PROMPT, ["contract-db"])


def test_duplicate_name_hard_block(governance, skills):
    skills.create(make_skill(name="legal-da-ton-tai"))
    with pytest.raises(GovernanceError, match="đã tồn tại"):
        governance.check_duplicate_name("skill", "legal-da-ton-tai")
    governance.check_duplicate_name("skill", "legal-chua-co")  # không raise


def test_dedup_soft_warning_via_llm(agents, skills):
    """LLM thấy chồng lấn → trả ứng viên (soft-warning), KHÔNG raise."""
    from app.core.governance import Governance
    from tests.conftest import CATALOG_SERVERS, FakeLLM

    # skill public mới hiện ra trong dedup (private của người khác bị lọc)
    from app.core.models import ItemStatus
    skills.create(make_skill(name="legal-tham-dinh-hop-dong", status=ItemStatus.public))
    llm = FakeLLM(classify_result={"overlapping": ["legal-tham-dinh-hop-dong"]})
    gov = Governance(
        agents=agents, skills=skills, admin_ids={"admin"},
        catalog_servers=CATALOG_SERVERS, llm=llm,
    )
    candidates = gov.dedup_candidates("skill", "legal-review-hop-dong", "Review hợp đồng theo checklist.")
    assert [c["name"] for c in candidates] == ["legal-tham-dinh-hop-dong"]


def test_dedup_llm_failure_does_not_block(agents, skills):
    """Dedup mềm lỗi → bỏ qua, không chặn flow (tránh vỡ demo live)."""
    from app.core.governance import Governance
    from tests.conftest import CATALOG_SERVERS

    class BrokenLLM:
        def classify_json(self, *a, **kw):
            raise RuntimeError("MaaS sập")

    skills.create(make_skill())
    gov = Governance(
        agents=agents, skills=skills, admin_ids={"admin"},
        catalog_servers=CATALOG_SERVERS, llm=BrokenLLM(),
    )
    assert gov.dedup_candidates("skill", "x-y", "mô tả") == []
