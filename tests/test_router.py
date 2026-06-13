"""Flow 1 — routing: explicit / @mention / classify / fallback master."""

from app.core.models import ItemStatus
from app.core.router import IntentRouter

from tests.conftest import FakeLLM, make_agent


def _setup(agents, governance, fake_llm):
    agents.create(make_agent(name="ThamDinhHopDong", status=ItemStatus.public, created_by="x"))
    agents.create(make_agent(name="PrivateRieng", status=ItemStatus.private, created_by="maker"))
    return IntentRouter(governance, fake_llm, router_model="cheap-model")


def test_explicit_agent_name_wins(agents, governance, fake_llm):
    router = _setup(agents, governance, fake_llm)
    d = router.route("user1", "câu gì cũng được", agent_name="ThamDinhHopDong")
    assert (d.agent_name, d.routed_by) == ("ThamDinhHopDong", "explicit")
    assert fake_llm.classify_calls == []  # không tốn call MaaS


def test_explicit_master_allowed(agents, governance, fake_llm):
    router = _setup(agents, governance, fake_llm)
    d = router.route("user1", "tạo agent mới cho tôi", agent_name="master")
    assert (d.agent_name, d.routed_by) == ("master", "explicit")


def test_mention_routes_by_slug(agents, governance, fake_llm):
    # "ThamDinhHopDong" → slug "thamdinhhopdong"
    router = _setup(agents, governance, fake_llm)
    d = router.route("user1", "@thamdinhhopdong xem giúp hợp đồng này")
    assert (d.agent_name, d.routed_by) == ("ThamDinhHopDong", "mention")


def test_mention_unknown_slug_routes_to_master_with_note(agents, governance, fake_llm):
    """@mention slug không tồn tại → về master kèm note (không expose classify)."""
    router = _setup(agents, governance, fake_llm)
    d = router.route("user1", "@khong-ton-tai giúp tôi thẩm định hợp đồng")
    assert d.agent_name == "master"
    assert d.routed_by == "fallback_unknown_mention"
    assert d.note and "@khong-ton-tai" in d.note


def test_classify_routes_on_confidence(agents, governance, fake_llm):
    fake_llm.classify_result = {"agent_name": "ThamDinhHopDong", "confidence": "medium"}
    router = _setup(agents, governance, fake_llm)
    d = router.route("user1", "tôi cần thẩm định hợp đồng với đối tác mới")
    assert (d.agent_name, d.routed_by, d.confidence) == ("ThamDinhHopDong", "classify", "medium")


def test_low_confidence_falls_back_to_master(agents, governance, fake_llm):
    fake_llm.classify_result = {"agent_name": "ThamDinhHopDong", "confidence": "low"}
    router = _setup(agents, governance, fake_llm)
    assert router.route("user1", "hôm nay trời đẹp nhỉ").agent_name == "master"


def test_classify_null_falls_back_to_master(agents, governance, fake_llm):
    fake_llm.classify_result = {"agent_name": None, "confidence": "high"}
    router = _setup(agents, governance, fake_llm)
    assert router.route("user1", "xin chào").agent_name == "master"


def test_private_agent_only_candidate_for_owner(agents, governance, fake_llm):
    """Agent private chỉ vào danh sách classify của chính chủ (Flow 1)."""
    router = _setup(agents, governance, fake_llm)
    fake_llm.classify_result = {"agent_name": None, "confidence": "low"}
    router.route("maker", "test")
    assert "PrivateRieng" in fake_llm.classify_calls[-1]["system"]
    router.route("nguoi-khac", "test")
    assert "PrivateRieng" not in fake_llm.classify_calls[-1]["system"]


def test_classify_error_falls_back_to_master(agents, governance):
    class BrokenLLM(FakeLLM):
        def classify_json(self, *a, **kw):
            raise RuntimeError("MaaS timeout")

    router = _setup(agents, governance, BrokenLLM())
    d = router.route("user1", "thẩm định hợp đồng")
    assert d.agent_name == "master"  # lỗi classify không được chặn chat


def test_prefix_name_not_double_counted(agents, governance, fake_llm):
    """Tên ngắn là prefix của tên dài không bị đếm trùng → không kích hoạt orchestrate sai."""
    agents.create(make_agent(name="Bot", status=ItemStatus.public, created_by="x"))
    agents.create(make_agent(name="Bot Pro", status=ItemStatus.public, created_by="x"))
    router = IntentRouter(governance, fake_llm, router_model="cheap-model")
    d = router.route("user1", "@Bot Pro giúp tôi việc này")
    # Chỉ 1 agent thực sự được nhắc → mention tới "Bot Pro", KHÔNG phải orchestrate.
    assert d.routed_by == "mention"
    assert d.agent_name == "Bot Pro"


def test_two_distinct_mentions_trigger_orchestrate(agents, governance, fake_llm):
    """≥2 agent khác nhau được nhắc → Master điều phối."""
    agents.create(make_agent(name="Bot Pro", status=ItemStatus.public, created_by="x"))
    agents.create(make_agent(name="ThamDinhHopDong", status=ItemStatus.public, created_by="x"))
    router = IntentRouter(governance, fake_llm, router_model="cheap-model")
    d = router.route("user1", "@Bot Pro và @thamdinhhopdong cùng xử lý")
    assert (d.agent_name, d.routed_by) == ("master", "orchestrate")
