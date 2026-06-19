"""Test mock GitLab provider (agent MrReviewer). Fixture tĩnh + post note mô phỏng,
save_review ghi file thật. MR !101 cố tình vi phạm RC để agent có cái bắt lỗi."""

import json

import pytest

from app.tools.mock.gitlab import GitlabProvider, _parse_mr_ref


class TestGitlabMock:
    def setup_method(self):
        self.p = GitlabProvider()

    def test_server_is_mock(self):
        assert self.p.server_name == "gitlab"
        assert self.p.is_mock is True

    def test_tools_listed(self):
        names = {t.name for t in self.p.list_tools()}
        assert names == {"get_mr", "get_mr_diff", "get_mr_discussions", "post_mr_note", "save_review"}

    @pytest.mark.parametrize(
        "ref,iid",
        [
            ("101", 101),
            ("!102", 102),
            ("aqr/payment/asset-exchange-v2!101", 101),
            ("https://gitlab.zalopay.vn/aqr/payment/wallet-core/-/merge_requests/103", 103),
        ],
    )
    def test_parse_mr_ref(self, ref, iid):
        assert _parse_mr_ref(ref) == iid

    def test_parse_mr_ref_invalid(self):
        with pytest.raises(ValueError):
            _parse_mr_ref("không-có-số")

    def test_get_mr(self):
        out = json.loads(self.p.call("get_mr", {"mr": "101"}))
        assert out["iid"] == 101
        assert out["target_branch"] == "master"
        assert "MÔ PHỎNG" in out["note"]

    def test_get_mr_unknown_goes_simulation(self):
        # MR không có trong fixture → chế độ giả lập (không raise), báo simulation cho agent.
        out = json.loads(self.p.call("get_mr", {"mr": "999"}))
        assert out["simulation"] is True
        assert out["fetched"] is False
        assert "GIẢ LẬP" in out["note"]

    def test_get_mr_repo_url_no_iid_simulation(self):
        # Link trang list MR (không có iid) như repo nội bộ thật → giả lập, đoán đúng repo path.
        ref = "https://gitlab.zalopay.vn/aqr/bill/provider-evnhcm/-/merge_requests"
        out = json.loads(self.p.call("get_mr", {"mr": ref}))
        assert out["simulation"] is True
        assert out["project"] == "aqr/bill/provider-evnhcm"

    def test_save_review_simulation_uses_repo_slug(self, tmp_path, monkeypatch):
        import app.tools.mock.gitlab as gl

        monkeypatch.setattr(gl, "_REVIEWS_DIR", tmp_path / "reviews")
        ref = "aqr/bill/provider-evnhcm"
        out = json.loads(self.p.call("save_review", {"mr": ref, "content": "# Review giả lập"}))
        assert out["saved"] is True and out["simulation"] is True
        assert (tmp_path / "reviews" / "mr_aqr_bill_provider-evnhcm.md").exists()

    def test_get_mr_diff_has_rc_violation(self):
        # MR !101 phải chứa pattern map RESOURCE_EXHAUSTED → FAILED (RC-2) và bỏ timeout (RC-9).
        diff = self.p.call("get_mr_diff", {"mr": "101"})
        assert "ResourceExhausted" in diff and "StatusFailed" in diff
        assert "bỏ timeout" in diff

    def test_get_mr_discussions_includes_existing(self):
        out = json.loads(self.p.call("get_mr_discussions", {"mr": "101"}))
        assert len(out["discussions"]) >= 1
        assert out["discussions"][0]["author"] == "reviewer.tranb"

    def test_post_mr_note_then_visible_in_discussions(self):
        posted = json.loads(self.p.call("post_mr_note", {"mr": "102", "body": "review ok"}))
        assert posted["mr_iid"] == 102
        assert "MÔ PHỎNG" in posted["note"]
        out = json.loads(self.p.call("get_mr_discussions", {"mr": "102"}))
        assert any(d["body"] == "review ok" for d in out["discussions"])

    def test_post_mr_note_empty_body(self):
        with pytest.raises(ValueError):
            self.p.call("post_mr_note", {"mr": "101", "body": "  "})

    def test_save_review_writes_file(self, tmp_path, monkeypatch):
        import app.tools.mock.gitlab as gl

        monkeypatch.setattr(gl, "_REVIEWS_DIR", tmp_path / "reviews")
        out = json.loads(self.p.call("save_review", {"mr": "103", "content": "# Review\n🔴 RC-16"}))
        assert out["saved"] is True
        saved = (tmp_path / "reviews" / "mr_103.md").read_text(encoding="utf-8")
        assert "RC-16" in saved

    def test_save_review_empty(self):
        with pytest.raises(ValueError):
            self.p.call("save_review", {"mr": "101", "content": ""})

    def test_unknown_tool(self):
        with pytest.raises(ValueError):
            self.p.call("khong-co-tool", {})


class TestMrReviewerSeed:
    """Agent MrReviewer được seed đúng với connector gitlab + skill checklist."""

    def test_seeded_agent_and_skill(self, agents, skills):
        from app.core.governance import Governance
        from seeds.demo_data import _MR_REVIEW_AGENT_NAME, _MR_REVIEW_SKILL_NAME, ensure_seed

        gov = Governance(
            agents=agents,
            skills=skills,
            admin_ids={"admin"},
            catalog_servers=["gitlab", "system", "web-search", "partner-integration", "zalopay-faq"],
            min_prompt_length=200,
        )
        ensure_seed(agents, skills, gov)

        agent = agents.get(_MR_REVIEW_AGENT_NAME)
        assert agent is not None
        assert "gitlab" in agent.connectors
        assert skills.get(_MR_REVIEW_SKILL_NAME) is not None
        assert _MR_REVIEW_SKILL_NAME in agents.skills_of(_MR_REVIEW_AGENT_NAME)
