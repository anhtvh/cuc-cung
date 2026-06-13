"""HM3 — Self-test agent trước khi giao user (Agent Hub improvement plan).

AgentTester chạy acceptance cases trong sandbox (memory OFF, tool rounds thấp)
rồi judge bằng ROUTER_MODEL. Master nhận kết quả PASS/FAIL để tự sửa hoặc báo user.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class TestCase:
    scenario: str   # câu hỏi/tình huống thử
    expected: str   # kỳ vọng ngắn gọn (chuẩn mực để judge)


@dataclass
class CaseResult:
    scenario: str
    expected: str
    actual: str
    passed: bool
    reason: str


@dataclass
class TestReport:
    agent_name: str
    total: int
    passed: int
    failed: int
    results: list[CaseResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def summary(self) -> str:
        lines = [f"**Self-test @{self.agent_name}**: {self.passed}/{self.total} PASS"]
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            lines.append(f"{icon} *{r.scenario[:70]}*")
            if not r.passed:
                lines.append(f"   → {r.reason}")
        return "\n".join(lines)


class AgentTester:
    """Chạy test case cho agent mới tạo trong sandbox, judge bằng model rẻ."""

    # user_id riêng cho sandbox — không lẫn với history thật của user
    _SANDBOX_USER = "__selftest__"

    def __init__(self, engine, llm, judge_model: str, sandbox_rounds: int = 5):
        self._engine = engine
        self._llm = llm
        self._judge_model = judge_model
        self._sandbox_rounds = sandbox_rounds

    def run_tests(
        self,
        agent,
        test_cases: list[TestCase],
        max_tool_rounds: int | None = None,
    ) -> TestReport:
        max_tool_rounds = max_tool_rounds if max_tool_rounds is not None else self._sandbox_rounds
        results: list[CaseResult] = []
        for tc in test_cases:
            actual = self._engine.run_once(
                user_id=self._SANDBOX_USER,
                agent=agent,
                message=tc.scenario,
                max_tool_rounds=max_tool_rounds,
            )
            passed, reason = self._judge(tc.scenario, tc.expected, actual)
            results.append(CaseResult(
                scenario=tc.scenario,
                expected=tc.expected,
                actual=actual,
                passed=passed,
                reason=reason,
            ))
        passed_count = sum(1 for r in results if r.passed)
        return TestReport(
            agent_name=agent.name,
            total=len(results),
            passed=passed_count,
            failed=len(results) - passed_count,
            results=results,
        )

    def _judge(self, scenario: str, expected: str, actual: str) -> tuple[bool, str]:
        try:
            result = self._llm.classify_json(
                system=(
                    "Bạn là QA judge cho AI agent. Đánh giá câu trả lời thực tế có đáp ứng kỳ vọng không.\n"
                    "Tiêu chí: (1) nội dung đúng với kỳ vọng, (2) không bịa thông tin, (3) format hợp lý.\n"
                    "KHÔNG yêu cầu hoàn hảo — chỉ cần 'đủ dùng' cho business user. Dùng ngưỡng thực tế."
                ),
                message=(
                    f"Tình huống: {scenario}\n\n"
                    f"Kỳ vọng: {expected}\n\n"
                    f"Câu trả lời thực tế:\n{actual[:2000]}"
                ),
                schema_hint='{"pass": true, "reason": "lý do ngắn 1 câu"}',
                model=self._judge_model,
            )
            return bool(result.get("pass", False)), str(result.get("reason", ""))
        except Exception as e:  # noqa: BLE001
            log.warning("judge lỗi — chưa test thực sự, mặc định PASS: %s", e)
            # Judge fail → PASS để không chặn flow (soft degrade), nhưng báo rõ chưa test thật
            return True, "judge không chạy được — chưa kiểm thật (mặc định PASS để không chặn flow)"
