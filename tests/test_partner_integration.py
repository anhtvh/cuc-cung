"""Test provider partner-integration (Upia). Tài liệu đối tác đi qua /upload nên
KHÔNG có doc-parser tool — agent đọc text upload thẳng từ hội thoại."""

import json

import pytest

from app.tools.partner_integration import PartnerIntegrationProvider


class TestPartnerIntegration:
    def setup_method(self):
        self.p = PartnerIntegrationProvider()

    def test_server_is_mock(self):
        assert self.p.server_name == "partner-integration"
        assert self.p.is_mock is True

    def test_tools_listed(self):
        names = {t.name for t in self.p.list_tools()}
        assert names == {
            "read_phase", "read_reference", "go_build", "go_test", "go_vet",
            "create_gitlab_repo", "create_mr",
            "merge_mr", "deploy_sandbox", "query_bill_sandbox",
        }

    @pytest.mark.parametrize("phase", [1, 2, 3, 4])
    def test_read_phase_returns_markdown(self, phase):
        out = self.p.call("read_phase", {"phase": phase})
        assert f"# Phase {phase}" in out

    def test_read_phase_invalid(self):
        with pytest.raises(ValueError):
            self.p.call("read_phase", {"phase": 9})

    def test_read_reference(self):
        out = self.p.call("read_reference", {"name": "provider-pattern"})
        assert "Provider Pattern" in out
        with pytest.raises(ValueError):
            self.p.call("read_reference", {"name": "khong-co"})

    def test_go_build_vet_empty_on_pass(self):
        assert self.p.call("go_build", {"repo_path": "/tmp/x"}) == ""
        assert self.p.call("go_vet", {"repo_path": "/tmp/x"}) == ""

    def test_go_test_summary(self):
        out = self.p.call("go_test", {"repo_path": "/tmp/x"})
        assert "coverage:" in out and "exit_code: 0" in out

    def test_create_gitlab_repo_mock(self):
        out = json.loads(self.p.call("create_gitlab_repo", {"namespace": "aqr/bill", "partner_name": "VNPT"}))
        assert out["web_url"].endswith("provider-vnpt")
        assert "MÔ PHỎNG" in out["note"]

    def test_create_mr_mock(self):
        out = json.loads(self.p.call(
            "create_mr",
            {"project_path": "aqr/bill/provider-vnpt", "source_branch": "feat/integrate-vnpt", "title": "feat: vnpt"},
        ))
        assert "/-/merge_requests/" in out["url"]
        assert out["target_branch"] == "master"

    def test_merge_mr_to_dev(self):
        out = json.loads(self.p.call("merge_mr", {"project_path": "aqr/bill/provider-vnpt"}))
        assert out["merged"] is True and out["target_branch"] == "dev"
        assert "MÔ PHỎNG" in out["note"]

    def test_deploy_sandbox_healthcheck(self):
        out = json.loads(self.p.call("deploy_sandbox", {"partner_name": "VNPT"}))
        assert out["deployed"] is True
        assert out["healthcheck"]["status"] == "healthy"
        assert "sandbox-provider-vnpt" in out["sandbox_url"]

    def test_query_bill_with_code(self):
        out = json.loads(self.p.call("query_bill_sandbox", {"customer_code": "PD123", "service_id": "DIEN"}))
        assert out["customer_code"] == "PD123"
        assert out["amount_vnd"] % 1000 == 0 and out["amount_vnd"] > 0
        assert out["final_status"] == 1 and "MÔ PHỎNG" in out["note"]

    def test_query_bill_random_code(self):
        out = json.loads(self.p.call("query_bill_sandbox", {}))
        # bỏ trống → tự sinh mã + nội dung hoá đơn ngẫu nhiên
        assert out["customer_code"] and out["customer_name"] and out["period"].endswith("/2026")

    def test_unknown_tool(self):
        with pytest.raises(ValueError):
            self.p.call("nope", {})
