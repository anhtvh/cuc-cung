"""Eval harness — test OFFLINE (không gọi MaaS).

Chứng minh logic load/aggregate/save chạy đúng bằng fake; chạy thật xem evals/__main__.py.
"""

import json
from types import SimpleNamespace

from app.core.agent_test import CaseResult, TestReport
from evals.runner import (
    CASES_PATH,
    build_summary,
    format_table,
    load_cases,
    run_eval,
    save_report,
)


class _FakeTester:
    """run_tests trả report định sẵn: case đầu PASS, còn lại FAIL (deterministic)."""

    def run_tests(self, agent, cases):
        results = [
            CaseResult(c.scenario, c.expected, "actual", i == 0, "reason", False)
            for i, c in enumerate(cases)
        ]
        passed = sum(1 for r in results if r.passed)
        return TestReport(
            agent_name=agent.name,
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
            inconclusive=0,
        )


class _FakeAgents:
    def __init__(self, names):
        self._names = set(names)

    def get(self, name):
        return SimpleNamespace(name=name) if name in self._names else None


def test_cases_json_parses():
    """cases.json hợp lệ và load thành TestCase."""
    cases = load_cases()
    assert cases, "phải có ít nhất 1 agent trong cases.json"
    for agent_name, agent_cases in cases.items():
        assert agent_cases, f"agent {agent_name} phải có ≥1 case"
        for c in agent_cases:
            assert c.scenario and c.expected


def test_cases_json_is_valid_json():
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)


def test_run_eval_skips_missing_agents():
    cases = {"AgentA": [_tc("s1", "e1")], "Ghost": [_tc("s2", "e2")]}
    agents = _FakeAgents(["AgentA"])  # Ghost không tồn tại
    reports = run_eval(_FakeTester(), agents, cases)
    assert set(reports) == {"AgentA"}


def test_build_summary_aggregates():
    cases = {"AgentA": [_tc("s1", "e1"), _tc("s2", "e2")]}  # 1 pass, 1 fail
    reports = run_eval(_FakeTester(), _FakeAgents(["AgentA"]), cases)
    summary = build_summary(reports)
    assert summary["agents"]["AgentA"]["passed"] == 1
    assert summary["agents"]["AgentA"]["failed"] == 1
    assert summary["agents"]["AgentA"]["pass_rate"] == 0.5
    assert summary["overall"]["total"] == 2
    assert summary["overall"]["pass_rate"] == 0.5


def test_build_summary_empty_no_div_zero():
    summary = build_summary({})
    assert summary["overall"]["total"] == 0
    assert summary["overall"]["pass_rate"] == 0.0


def test_format_table_has_agents_and_overall():
    reports = run_eval(_FakeTester(), _FakeAgents(["AgentA"]), {"AgentA": [_tc("s", "e")]})
    table = format_table(build_summary(reports))
    assert "AgentA" in table
    assert "OVERALL" in table


def test_save_report_writes_file(tmp_path):
    cases = {"AgentA": [_tc("s1", "e1")]}
    reports = run_eval(_FakeTester(), _FakeAgents(["AgentA"]), cases)
    summary = build_summary(reports)
    path = save_report(summary, reports, tmp_path, "20260615-120000")
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["timestamp"] == "20260615-120000"
    assert payload["summary"]["overall"]["total"] == 1
    assert "AgentA" in payload["details"]


def _tc(scenario, expected):
    from app.core.agent_test import TestCase
    return TestCase(scenario=scenario, expected=expected)
