"""Eval harness — phần logic THUẦN (không gọi MaaS) để test offline được.

Mục tiêu (bước 2 lộ trình ổn định): có THƯỚC ĐO bằng số trước khi chỉnh P2 (prompt/SLA),
để mỗi thay đổi sau chứng minh được bằng pass-rate chứ không cảm tính.

Tách bạch:
- runner.py (file này): load case + chạy qua AgentTester + tổng hợp số + lưu báo cáo. Hàm thuần,
  nhận `tester`/`agents_repo` từ ngoài → test offline bằng fake (xem tests/test_eval_harness.py).
- __main__.py: wiring thật (create_app + MaaS) — chạy `.venv/bin/python -m evals` (TỐN credit MaaS).

LƯU Ý giới hạn: eval chạy qua AgentTester.run_once (sandbox) — KHÔNG inject escalate/knowledge_search
như runtime thật (đây chính là P2-1). Vì vậy baseline đo persona/grounding/tool-mock là chính;
sau khi sửa P2-1 (cho sandbox khớp runtime) eval sẽ phản ánh sát hơn.
"""

import json
from pathlib import Path

from app.core.agent_test import TestCase, TestReport

CASES_PATH = Path(__file__).parent / "cases.json"


def load_cases(path=CASES_PATH) -> dict[str, list[TestCase]]:
    """Đọc cases.json → {agent_name: [TestCase, ...]}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        agent_name: [TestCase(scenario=c["scenario"], expected=c["expected"]) for c in cases]
        for agent_name, cases in raw.items()
    }


def run_eval(tester, agents_repo, cases: dict[str, list[TestCase]]) -> dict[str, TestReport]:
    """Chạy từng agent qua case của nó. Agent không có trong registry → bỏ qua (không crash)."""
    reports: dict[str, TestReport] = {}
    for agent_name, agent_cases in cases.items():
        agent = agents_repo.get(agent_name)
        if agent is None:
            continue
        reports[agent_name] = tester.run_tests(agent, agent_cases)
    return reports


def build_summary(reports: dict[str, TestReport]) -> dict:
    """Tổng hợp số per-agent + overall. pass_rate = passed/total (inconclusive KHÔNG tính là pass)."""
    per_agent: dict[str, dict] = {}
    tot = passed = failed = inconc = 0
    for name, r in reports.items():
        per_agent[name] = {
            "passed": r.passed,
            "failed": r.failed,
            "inconclusive": r.inconclusive,
            "total": r.total,
            "pass_rate": round(r.passed / r.total, 3) if r.total else 0.0,
        }
        tot += r.total
        passed += r.passed
        failed += r.failed
        inconc += r.inconclusive
    return {
        "agents": per_agent,
        "overall": {
            "passed": passed,
            "failed": failed,
            "inconclusive": inconc,
            "total": tot,
            "pass_rate": round(passed / tot, 3) if tot else 0.0,
        },
    }


def format_table(summary: dict) -> str:
    """Bảng text gọn cho terminal."""
    header = f"{'Agent':<24}{'PASS':>6}{'FAIL':>6}{'INCONC':>8}{'TOTAL':>7}{'RATE':>8}"
    lines = [header, "-" * len(header)]
    for name, s in summary["agents"].items():
        lines.append(
            f"{name:<24}{s['passed']:>6}{s['failed']:>6}{s['inconclusive']:>8}{s['total']:>7}{s['pass_rate']:>7.0%} "
        )
    o = summary["overall"]
    lines.append("-" * len(header))
    lines.append(
        f"{'OVERALL':<24}{o['passed']:>6}{o['failed']:>6}{o['inconclusive']:>8}{o['total']:>7}{o['pass_rate']:>7.0%} "
    )
    return "\n".join(lines)


def save_report(summary: dict, reports: dict[str, TestReport], out_dir, timestamp: str) -> Path:
    """Lưu báo cáo JSON (summary + chi tiết từng case) để so sánh giữa các lần chạy."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": timestamp,
        "summary": summary,
        "details": {
            name: [
                {
                    "scenario": c.scenario,
                    "expected": c.expected,
                    "passed": c.passed,
                    "inconclusive": c.inconclusive,
                    "reason": c.reason,
                    "actual": c.actual[:1000],
                }
                for c in r.results
            ]
            for name, r in reports.items()
        },
    }
    path = out_dir / f"{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
