"""CLI eval — chạy bộ case thật qua MaaS. TỐN credit.

    .venv/bin/python -m evals

Cần .env có MAAS_API_KEY hợp lệ. Không có key → run_once trả '[sandbox error]' và judge lỗi
→ mọi case 'inconclusive' (không crash). Báo cáo lưu ở evals/results/<timestamp>.json.
"""

import logging
from datetime import datetime
from pathlib import Path

from app.config import load_settings
from app.core.agent_test import AgentTester
from app.main import create_app, make_router_llm
from evals.runner import build_summary, format_table, load_cases, run_eval, save_report

log = logging.getLogger(__name__)


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    c = app.state.container

    # Judge dùng router model (rẻ) qua endpoint OpenAI — giống self-test trong runtime.
    # P2-A: cap vòng = max_tool_rounds (Flow 3 runtime) để eval mô phỏng đúng runtime, không
    # cắt oan agent web giữa chừng search→fetch→answer.
    judge_llm = make_router_llm(settings)
    tester = AgentTester(
        c.engine, judge_llm, settings.router_model,
        sandbox_rounds=settings.max_tool_rounds,
    )

    cases = load_cases()
    print(f"Chạy eval cho {len(cases)} agent (case: {sum(len(v) for v in cases.values())})...\n")
    reports = run_eval(tester, c.agents, cases)
    summary = build_summary(reports)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = save_report(summary, reports, Path(__file__).parent / "results", timestamp)

    print(format_table(summary))
    print(f"\nĐã lưu báo cáo chi tiết: {path}")


if __name__ == "__main__":
    main()
