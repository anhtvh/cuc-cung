"""App factory + composition root (design §6): wire mọi implementation theo config.

Đổi hạ tầng (LLM provider, memory backend, DB) = đổi env, không sửa core.
"""

import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import agents as agents_api
from app.api import chat as chat_api
from app.api import feedback as feedback_api
from app.api import history as history_api
from app.api import mcp as mcp_api
from app.api import review as review_api
from app.api import skills as skills_api
from app.api import upload as upload_api
from app.api import auth as auth_api
from app.api.deps import Container
from app.auth.middleware import UserIdMiddleware
from app.auth.password_auth import hash_password
from app.auth.rate_limiter import init_limiter
from app.config import PROJECT_ROOT, Settings, load_settings
from app.core.agent_test import AgentTester
from app.core.chat_engine import ChatEngine
from app.core.governance import Governance
from app.core.router import IntentRouter
from app.memory.sql_memory import SqlMemory
from app.storage.sql import SqlAgentRepo, SqlConvMetaRepo, SqlFeedbackRepo, SqlSkillRepo, SqlUsageRepo, SqlUserRepo, make_engine
from app.tools.catalog import SystemProvider, ToolCatalog
from app.tools.mcp_gateway import IamTokenProvider, McpGatewayProvider
from app.tools.mock.company_docs import CompanyDocsProvider
from app.tools.mock.contract_db import ContractDbProvider
from app.tools.mock.web_search import WebSearchProvider
from seeds.demo_data import ensure_seed


class _JsonFormatter(logging.Formatter):
    """Structured logging JSON từ ngày 1 (§6) — đổ vào stack observability nào cũng được."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def run_migrations(settings: Settings) -> None:
    """Alembic upgrade head lúc khởi động — schema evolve không đập DB (§6)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")


def make_llm(settings: Settings):
    if settings.llm_provider == "anthropic":  # Plan A — chốt theo check §8
        from app.llm.anthropic_client import AnthropicMaaSClient

        return AnthropicMaaSClient(
            base_url=settings.maas_base_url,
            api_key=settings.maas_api_key,
            default_model=settings.model,
            max_tokens=settings.max_tokens,
            request_timeout=settings.llm_request_timeout_seconds,
            sla_seconds=settings.response_sla_seconds,
        )
    if settings.llm_provider == "openai":  # Plan B
        from app.llm.openai_client import OpenAIMaaSClient

        return OpenAIMaaSClient(
            base_url=settings.maas_base_url,
            api_key=settings.maas_api_key,
            default_model=settings.model,
            max_tokens=settings.max_tokens,
            request_timeout=settings.llm_request_timeout_seconds,
        )
    raise ValueError(f"LLM_PROVIDER không hỗ trợ: {settings.llm_provider}")


def make_router_llm(settings: Settings):
    """LLM riêng cho router/dedup (classify_json, model rẻ — rủi ro #3).

    LUÔN đi qua endpoint OpenAI-compatible: phát hiện 12/06 — endpoint Anthropic
    của MaaS chỉ phục vụ MỘT SỐ model (gpt-4o-mini/gemini-flash-lite trả 404);
    endpoint OpenAI phục vụ đủ pool, chung 1 key (design §1.3).
    """
    from app.llm.openai_client import OpenAIMaaSClient

    return OpenAIMaaSClient(
        base_url=settings.maas_base_url,
        api_key=settings.maas_api_key,
        default_model=settings.router_model,
        max_tokens=512,
        request_timeout=settings.router_timeout_seconds,
    )


def make_memory(settings: Settings, engine):
    if settings.memory_backend == "agentbase":  # swap ngày 14/06 (Flow 6)
        from app.memory.agentbase_memory import AgentBaseMemory

        return AgentBaseMemory(
            client_id=settings.greennode_client_id,
            client_secret=settings.greennode_client_secret,
            store_id=settings.agentbase_memory_store_id,
            strategy_id=settings.agentbase_memory_strategy_id,
        )
    return SqlMemory(engine)


def create_app(settings: Settings | None = None) -> FastAPI:
    setup_logging()
    settings = settings or load_settings()

    # DB: đảm bảo thư mục data/ tồn tại cho SQLite (volume mount khi deploy).
    if settings.database_url.startswith("sqlite"):
        db_path = settings.database_url.removeprefix("sqlite:///")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    run_migrations(settings)
    engine = make_engine(settings.database_url)

    agents = SqlAgentRepo(engine)
    skills = SqlSkillRepo(engine)
    usage = SqlUsageRepo(engine)
    feedback = SqlFeedbackRepo(engine)
    conv_meta = SqlConvMetaRepo(engine)
    user_repo = SqlUserRepo(engine)
    memory = make_memory(settings, engine)

    init_limiter(settings.rate_limit_per_minute)
    llm = make_llm(settings)
    router_llm = make_router_llm(settings)
    # web-search: swap gateway ↔ local tùy env — tool name giữ nguyên "web-search"
    # nên prompt + agent config không đổi khi chuyển qua gateway.
    if settings.mcp_gateway_endpoint:
        _iam = IamTokenProvider(settings.greennode_client_id, settings.greennode_client_secret)
        web_search_provider = McpGatewayProvider(
            server_name=settings.mcp_gateway_server_name,
            gateway_endpoint=settings.mcp_gateway_endpoint,
            token_provider=_iam,
            target_name=settings.mcp_gateway_target or None,
            call_timeout=max(1, settings.tool_timeout_seconds - 1),
        )
    else:
        web_search_provider = WebSearchProvider()
    providers = [SystemProvider(), ContractDbProvider(), CompanyDocsProvider(), web_search_provider]
    catalog = ToolCatalog(providers, tool_timeout_seconds=settings.tool_timeout_seconds)
    governance = Governance(
        agents=agents,
        skills=skills,
        admin_ids=settings.admin_ids,
        catalog_servers=catalog.server_names(),
        min_prompt_length=settings.min_prompt_length,
        llm=router_llm,  # dedup classify dùng model rẻ qua endpoint OpenAI (rủi ro #3)
        dedup_model=settings.router_model,
    )
    intent_router = IntentRouter(governance, router_llm, settings.router_model)
    chat_engine = ChatEngine(
        agents=agents,
        skills=skills,
        usage=usage,
        memory=memory,
        llm=llm,
        catalog=catalog,
        max_tool_rounds=settings.max_tool_rounds,
        history_limit=settings.memory_history_limit,
        model=settings.model,
    )

    # HM3: self-test sandbox (judge dùng model rẻ qua router_llm)
    tester: AgentTester | None = None
    if settings.self_test_enabled:
        tester = AgentTester(engine=chat_engine, llm=router_llm, judge_model=settings.router_model, sandbox_rounds=settings.self_test_sandbox_rounds)

    ensure_seed(agents, skills)

    # Seed admin user từ env ADMIN_EMAIL + ADMIN_PASSWORD
    if settings.admin_email and settings.admin_password:
        user_repo.seed_admin(settings.admin_email, hash_password(settings.admin_password))

    app = FastAPI(title="Agent Hub", version="0.1.0")
    app.state.container = Container(
        settings=settings,
        agents=agents,
        skills=skills,
        usage=usage,
        feedback=feedback,
        conv_meta=conv_meta,
        user_repo=user_repo,
        memory=memory,
        llm=llm,
        catalog=catalog,
        governance=governance,
        router=intent_router,
        engine=chat_engine,
        web_search_provider=web_search_provider,
        tester=tester,
    )
    app.add_middleware(UserIdMiddleware, jwt_secret=settings.jwt_secret, guest_mode=settings.guest_mode)

    app.include_router(auth_api.router)
    app.include_router(chat_api.router)
    app.include_router(agents_api.router)
    app.include_router(skills_api.router)
    app.include_router(review_api.router)
    app.include_router(upload_api.router)
    app.include_router(history_api.router)
    app.include_router(feedback_api.router)
    app.include_router(mcp_api.router)

    @app.get("/healthz")
    @app.get("/health")  # AgentBase runtime contract yêu cầu /health
    def healthz():
        return {"status": "ok"}

    @app.get("/")
    def index():
        return RedirectResponse("/web/")

    app.mount("/web", StaticFiles(directory=PROJECT_ROOT / "web", html=True), name="web")
    return app


app = create_app()
