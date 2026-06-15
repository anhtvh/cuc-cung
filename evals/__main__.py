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
from app.llm.openai_client import OpenAIMaaSClient
from app.main import create_app
from evals.runner import build_summary, format_table, load_cases, run_eval, save_report

log = logging.getLogger(__name__)


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    c = app.state.container

    # Judge qua endpoint OpenAI (tắt thinking → reasoning model vẫn trả JSON). #2: model judge
    # cấu hình qua EVAL_JUDGE_MODEL (mặc định router_model rẻ; đặt minimax để giảm chấm sai).
    # P2-A: cap vòng = max_tool_rounds (Flow 3 runtime) để eval mô phỏng đúng runtime, không
    # cắt oan agent web giữa chừng search→fetch→answer.
    judge_model = settings.eval_judge_model or settings.router_model
    judge_llm = OpenAIMaaSClient(
        base_url=settings.maas_base_url,
        api_key=settings.maas_api_key,
        default_model=judge_model,
        request_timeout=settings.llm_request_timeout_seconds,
    )
    print(f"Judge model: {judge_model}")
    tester = AgentTester(
        c.engine, judge_llm, judge_model,
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
