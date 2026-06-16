"""Capability của agent nâng cao — khai báo declarative (seam plug-and-play).

Trước đây hành vi đặc thù của Upia (chế độ thử nghiệm) bị HARD-CODE thẳng trong
chat_engine.py qua `agent.name == "Upia"`. Thêm 1 agent nâng cao kiểu Upia = phải sửa
engine. Module này gom toàn bộ tri thức đặc thù về MỘT chỗ khai báo:

    thêm agent nâng cao mới  →  thêm 1 entry trong `_PROFILES`, KHÔNG sửa chat_engine.

Engine chỉ hỏi resolver "profile của agent này là gì" rồi áp dụng — generic, không biết tên
agent cụ thể nào.

Phân biệt 2 truy vấn (cố ý tách):
  • `gated_tools(name)`  — tập tool experimental-gated của agent, ĐỘC LẬP cờ bật/tắt. Engine
    luôn cần biết để ẩn các tool này khi CHƯA bật experimental (giữ nguyên flow gốc của agent,
    kể cả ở sandbox run_once/eval).
  • `active_profile(name)` — profile CÓ HIỆU LỰC: chỉ trả entry thật khi `experimental_enabled`
    bật; tắt → EMPTY_PROFILE (không note, không RAG, không tuning).
"""

from dataclasses import dataclass
from pathlib import Path

# Thư mục chứa tài nguyên agent nâng cao (note chế độ, template…). app/agents/<slug>/...
_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


@dataclass(frozen=True)
class ExecutionProfile:
    """Tinh chỉnh tool-loop cho agent chạy lượt DÀI (nhiều vòng tool).

    stream/parallel_tools map thẳng vào kwargs của llm.chat_with_tools. Trần tool-loop và SLA
    lấy từ cấu hình builder của engine (cao hơn mặc định) — xem chat_engine khi áp dụng.
    """

    stream: bool
    parallel_tools: bool


@dataclass(frozen=True)
class AgentProfile:
    """Hồ sơ capability của 1 agent nâng cao. Mặc định = rỗng (agent thường không đổi gì)."""

    # Tool experimental-gated: chỉ lộ khi bật experimental, ngoài ra ẩn (tên wire `server__tool`).
    workspace_tools: tuple[str, ...] = ()
    # File markdown nối vào system prompt khi experimental bật (vd chỉ thị chế độ đóng gói).
    extra_system_notes: tuple[Path, ...] = ()
    # Tài liệu đính kèm DÀI → nạp RAG (scope theo conversation) thay vì nhồi full text mỗi lượt.
    large_doc_rag: bool = False
    rag_min_chars: int = 8000
    # Tinh chỉnh tool-loop (None → dùng cấu hình chat thường).
    execution: ExecutionProfile | None = None


EMPTY_PROFILE = AgentProfile()

# ---------------------------------------------------------------------------
# Đăng ký agent nâng cao. THÊM AGENT MỚI Ở ĐÂY (không sửa chat_engine).
# ---------------------------------------------------------------------------
_PROFILES: dict[str, AgentProfile] = {
    # Upia (Flow 5): coding agent đóng gói ZIP. Chế độ thử nghiệm lộ workspace tool (save_file…),
    # nối chỉ thị experimental_mode.md, nạp tài liệu đối tác lớn vào RAG, chạy non-stream +
    # parallel để bền qua lượt dài (MaaS/minimax flaky khi stream lâu). Xem CLAUDE.md §gotchas.
    "Upia": AgentProfile(
        workspace_tools=(
            "partner-integration__save_file",
            "partner-integration__list_workspace",
            "partner-integration__package_project",
        ),
        extra_system_notes=(_AGENTS_DIR / "upia" / "experimental_mode.md",),
        large_doc_rag=True,
        rag_min_chars=8000,
        execution=ExecutionProfile(stream=False, parallel_tools=True),
    ),
}


class CapabilityResolver:
    """Tra cứu capability cho engine. `experimental_enabled` = cờ global (env)."""

    def __init__(self, experimental_enabled: bool = False):
        self._enabled = experimental_enabled

    def gated_tools(self, agent_name: str) -> frozenset[str]:
        """Tập tool experimental-gated của agent — ĐỘC LẬP cờ bật/tắt (luôn ẩn khi chưa expose)."""
        return frozenset(_PROFILES.get(agent_name, EMPTY_PROFILE).workspace_tools)

    def active_profile(self, agent_name: str) -> AgentProfile:
        """Profile có hiệu lực: chỉ khi experimental bật; tắt → EMPTY_PROFILE."""
        if not self._enabled:
            return EMPTY_PROFILE
        return _PROFILES.get(agent_name, EMPTY_PROFILE)
