"""Toàn bộ config từ env (AGENT_HUB_DESIGN.md §6) — không hardcode.

Fix production chỉ cần đổi env, không rebuild image (rủi ro vibe-code §7).
"""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- MaaS (design §1.3, §8) ---
    maas_api_key: str = ""
    maas_base_url: str = "https://maas-llm-aiplatform-hcm.api.vngcloud.vn"
    # Plan A: provider "anthropic" (native tool-use). Plan B dự phòng: "openai".
    llm_provider: str = "anthropic"
    # Model chính cho master + agent con (đã test tool-call PASS sáng 12/06).
    model: str = "minimax/minimax-m2.5"
    # Model rẻ cho router/classify — rủi ro #3 credit cạn.
    # qwen3-5-27b là thinking model, content=None → dùng gemma (non-thinking, classify OK).
    router_model: str = "google/gemma-4-31b-it"
    max_tokens: int = 4096
    # An toàn tool loop (Flow 3): tối đa 5 vòng tool/lượt, timeout mỗi tool.
    max_tool_rounds: int = 10
    tool_timeout_seconds: int = 15
    # SLA trả lời (~1 phút): khi tool loop vượt ngưỡng này, ép model trả lời NGAY
    # trên dữ liệu đã thu thập (không cho gọi thêm tool) — tránh treo do search/đọc dài.
    response_sla_seconds: int = 55
    # Timeout từng request HTTP tới MaaS — chặn 1 call treo vô hạn (an toàn cho SLA trên).
    llm_request_timeout_seconds: int = 45
    # Router classify là call ngắn, chạy TRƯỚC khi stream — timeout ngắn để fallback master nhanh.
    router_timeout_seconds: int = 15
    # I-06: giới hạn số call /chat per user per session (0 = không giới hạn — contest default).
    # Production nên set ≥1 để tránh credit cạn do 1 user trigger vô tận master tool loop.
    max_chat_calls_per_session: int = 0
    # Sliding-window rate limit cho /chat: số lần gọi tối đa mỗi phút per user (0 = disabled).
    # Production khuyến nghị 20; contest để 0 để không ảnh hưởng demo.
    rate_limit_per_minute: int = 0

    # --- Storage / Memory ---
    # Postgres sau cuộc thi = đổi DSN này (§6 đường mở rộng).
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'hub.db'}"
    # "sql" (fallback, ngày 1-2) | "agentbase" (Memory module, swap ngày 14/06 — Flow 6).
    memory_backend: str = "sql"
    memory_history_limit: int = 20

    # --- Governance ---
    # Checker = admin (Flow 2b); danh sách user_id cách nhau dấu phẩy.
    admin_user_ids: str = "admin"
    # Plugin #1 (§3.3): contest bật; production có thể tắt master factory.
    builder_enabled: bool = True
    min_prompt_length: int = 200

    # --- Orchestration (multi-agent) ---
    # Số lần run_agent tối đa / 1 lượt Master (cap credit)
    orchestration_max_agents: int = 4
    # Tool rounds tối đa mỗi sub-agent trong orchestration
    orchestration_sub_rounds: int = 3

    # --- Self-test (HM3/HM4) ---
    # Tắt khi demo live để tiết kiệm credit: SELF_TEST_ENABLED=false
    self_test_enabled: bool = True
    # Số test case tối đa mỗi build session (cap credit)
    self_test_max_cases: int = 3
    # Tool rounds tối đa mỗi test case trong sandbox (thấp để tiết kiệm)
    self_test_sandbox_rounds: int = 2
    # Số vòng master tự sửa khi fail trước khi báo user
    self_test_fix_attempts: int = 2

    # --- AgentBase (dùng từ 14/06) ---
    greennode_client_id: str = ""
    greennode_client_secret: str = ""
    # Memory module: tạo store 1 lần qua CLI, điền ID vào env.
    # memory_strategy_id: để rỗng nếu chỉ cần short-term (search() tự bỏ qua).
    agentbase_memory_store_id: str = ""
    agentbase_memory_strategy_id: str = ""

    # --- Auth ---
    # Tắt guest mode: chỉ user đã login mới vào được (mọi route trả 401 cho guest).
    guest_mode: bool = True
    google_client_id: str = ""
    google_client_secret: str = ""
    # JWT cookie "session" (httpOnly, SameSite=Lax) — đổi secret = invalidate toàn bộ session.
    jwt_secret: str = ""
    jwt_expire_hours: int = 168  # 7 ngày
    # Admin duy nhất — seed vào DB khi khởi động, hash password tự động.
    admin_email: str = ""
    admin_password: str = ""  # plain text, chỉ đọc khi boot để hash + lưu DB

    # --- MCP Gateway (Flow 5 — cắm server thật) ---
    # Lấy endpoint từ: GET /gateway/api/v1/gateways/<name> → field `endpoint` (state=ACTIVE).
    # Để trống → catalog chỉ dùng mock providers.
    mcp_gateway_endpoint: str = ""
    # Tên target trên gateway (vd "web-search"). Để trống nếu gateway 1 target + tools không prefix.
    mcp_gateway_target: str = ""
    # Tên server trong catalog (hiển thị trong Catalog/Review UI).
    mcp_gateway_server_name: str = "web-search-live"

    @model_validator(mode="after")
    def _empty_env_fallback(self) -> "Settings":
        # .env để biến trống (vd `MODEL=`) → dùng default thay vì chuỗi rỗng
        # (đã gây 404 "model not found" lúc smoke test 12/06).
        for name in ("maas_base_url", "llm_provider", "model", "router_model", "memory_backend", "database_url"):
            if not getattr(self, name):
                setattr(self, name, type(self).model_fields[name].default)
        return self

    @property
    def admin_ids(self) -> set[str]:
        ids = {u.strip() for u in self.admin_user_ids.split(",") if u.strip()}
        if self.admin_email:
            ids.add(self.admin_email)
        return ids


def load_settings() -> Settings:
    return Settings()
