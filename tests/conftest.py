"""Fixtures chung: DB in-memory + FakeLLM (không gọi MaaS trong test — rủi ro #3 credit)."""

from typing import Any, Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.core.governance import Governance
from app.core.models import Agent, ChatMessage, ItemStatus, Skill
from app.llm.base import Done, LLMEvent, TextDelta, ToolDef, ToolExecutor
from app.storage.sql import Base, SqlAgentRepo, SqlSkillRepo, SqlUsageRepo

VALID_PROMPT = "x" * 250  # qua được min_prompt_length=200

CATALOG_SERVERS = ["system", "contract-db", "company-docs"]


class FakeLLM:
    """LLMClient giả: classify_json trả kết quả định sẵn, chat echo."""

    def __init__(self, classify_result: dict | None = None):
        self.classify_result = classify_result or {"agent_name": None, "confidence": "low"}
        self.classify_calls: list[dict] = []

    def chat(self, system: str, messages: list[ChatMessage], model: str | None = None) -> Iterator[LLMEvent]:
        yield TextDelta("fake reply")
        yield Done(input_tokens=1, output_tokens=1, stop_reason="end_turn")

    def chat_with_tools(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolDef],
        execute: ToolExecutor,
        max_rounds: int = 5,
        model: str | None = None,
    ) -> Iterator[LLMEvent]:
        yield TextDelta("fake tool reply")
        yield Done(input_tokens=1, output_tokens=1, stop_reason="end_turn")

    def classify_json(self, system: str, message: str, schema_hint: str, model: str | None = None) -> dict[str, Any]:
        self.classify_calls.append({"system": system, "message": message})
        return self.classify_result


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def agents(engine):
    return SqlAgentRepo(engine)


@pytest.fixture
def skills(engine):
    return SqlSkillRepo(engine)


@pytest.fixture
def usage(engine):
    return SqlUsageRepo(engine)


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def governance(agents, skills):
    # llm=None → dedup mềm tắt trong test governance (test riêng ở test_validate)
    return Governance(
        agents=agents,
        skills=skills,
        admin_ids={"admin"},
        catalog_servers=CATALOG_SERVERS,
        min_prompt_length=200,
        llm=None,
    )


def make_agent(name="TestAgent", status=ItemStatus.private, created_by="maker", **kw) -> Agent:
    return Agent(
        name=name,
        description="Agent test. Dùng khi cần test.",
        system_prompt=VALID_PROMPT,
        status=status,
        created_by=created_by,
        **kw,
    )


def make_skill(name="test-skill-mot", status=ItemStatus.private, created_by="maker", **kw) -> Skill:
    return Skill(
        name=name,
        description="Skill test.",
        content="# Quy trình test\n1. Bước một.",
        status=status,
        created_by=created_by,
        **kw,
    )
