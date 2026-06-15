"""HM3 — Self-test agent trước khi giao user (Agent Hub improvement plan).

AgentTester chạy acceptance cases trong sandbox (memory OFF, tool rounds thấp)
rồi judge bằng ROUTER_MODEL. Master nhận kết quả PASS/FAIL để tự sửa hoặc báo user.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


@dataclass
class TestCase:
    __test__ = False  # không phải class test của pytest (tên bắt đầu 'Test' bị collect nhầm)
    scenario: str   # câu hỏi/tình huống thử
    expected: str   # kỳ vọng ngắn gọn (chuẩn mực để judge)


@dataclass
class CaseResult:
    scenario: str
    expected: str
    actual: str
    passed: bool
    reason: str
    # P1-3: case không kiểm chứng được (judge lỗi/timeout). KHÔNG tính là PASS — trước đây
    # judge lỗi trả PASS giả → agent kém vẫn được báo "đạt". inconclusive=True khi passed=False
    # nhưng nguyên nhân là judge không chạy được, không phải câu trả lời sai.
    inconclusive: bool = False


@dataclass
class TestReport:
    __test__ = False  # không phải class test của pytest (tên bắt đầu 'Test' bị collect nhầm)
    agent_name: str
    total: int
    passed: int
    failed: int
    results: list[CaseResult] = field(default_factory=list)
    # P1-3: số case không kiểm chứng được (judge lỗi). Tách khỏi 'failed' để master phân biệt
    # "trả lời sai" với "chưa kiểm được".
    inconclusive: int = 0

    @property
    def all_passed(self) -> bool:
        # Chỉ coi là đạt khi MỌI case thật sự PASS — còn case inconclusive thì chưa chắc chắn.
        return self.passed == self.total

    @property
    def has_inconclusive(self) -> bool:
        return self.inconclusive > 0

    def summary(self) -> str:
        lines = [f"**Self-test @{self.agent_name}**: {self.passed}/{self.total} PASS"]
        if self.inconclusive:
            lines[0] += f" ({self.inconclusive} chưa kiểm chứng)"
        for r in self.results:
            icon = "⚠️" if r.inconclusive else ("✅" if r.passed else "❌")
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
            passed, inconclusive, reason = self._judge(tc.scenario, tc.expected, actual)
            results.append(CaseResult(
                scenario=tc.scenario,
                expected=tc.expected,
                actual=actual,
                passed=passed,
                reason=reason,
                inconclusive=inconclusive,
            ))
        passed_count = sum(1 for r in results if r.passed)
        inconclusive_count = sum(1 for r in results if r.inconclusive)
        return TestReport(
            agent_name=agent.name,
            total=len(results),
            passed=passed_count,
            # failed = thật sự sai (không tính case chưa kiểm chứng được).
            failed=len(results) - passed_count - inconclusive_count,
            inconclusive=inconclusive_count,
            results=results,
        )

    def _judge(self, scenario: str, expected: str, actual: str) -> tuple[bool, bool, str]:
        """Trả (passed, inconclusive, reason). Judge lỗi → (False, True, ...) — KHÔNG phải PASS."""
        # Inject ngày hôm nay (giờ VN) vào prompt judge: judge model cũ dễ tưởng mốc gần hôm nay
        # (vd 2026) là "tương lai/bịa" → chấm fail oan câu hỏi thời sự. Cho biết "hôm nay" để khỏi nhầm.
        today = datetime.now(timezone(timedelta(hours=7))).date().isoformat()
        try:
            result = self._llm.classify_json(
                system=(
                    "Bạn là QA judge cho AI agent. Đánh giá câu trả lời thực tế có đáp ứng kỳ vọng không.\n"
                    f"Bối cảnh thời gian: HÔM NAY là {today} (giờ Việt Nam). Mốc thời gian gần hôm nay "
                    "là HIỆN TẠI hợp lệ — KHÔNG coi là 'tương lai' hay 'bịa'.\n"
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
            return bool(result.get("pass", False)), False, str(result.get("reason", ""))
        except Exception as e:  # noqa: BLE001
            log.warning("judge lỗi — case KHÔNG kiểm chứng được (không tính PASS): %s", e)
            # P1-3: judge fail → inconclusive (KHÔNG PASS). Trước đây trả PASS → cổng chất lượng tự
            # vô hiệu đúng lúc judge flaky nhất, agent kém vẫn được báo "đạt". Vẫn không raise để
            # không chặn flow, nhưng master sẽ thấy "chưa kiểm chứng" và quyết định (test tay/submit thử).
            return False, True, "judge không chạy được — chưa kiểm chứng (không tính là PASS)"
