"""Repo protocols (design §6) — core chỉ phụ thuộc interface, không phụ thuộc SQLAlchemy."""

from __future__ import annotations

from typing import Protocol

from app.core.models import Agent, ItemStatus, Skill


class AgentRepo(Protocol):
    def get(self, name: str) -> Agent | None: ...

    def list(
        self,
        status: ItemStatus | None = None,
        created_by: str | None = None,
    ) -> list[Agent]: ...

    def create(self, agent: Agent) -> Agent: ...

    def update(self, agent: Agent) -> Agent: ...

    def attach_skill(self, agent_name: str, skill_name: str) -> None: ...

    def skills_of(self, agent_name: str) -> list[str]: ...

    def agents_using_skill(self, skill_name: str) -> list[str]: ...


class SkillRepo(Protocol):
    def get(self, name: str) -> Skill | None: ...

    def list(self, status: ItemStatus | None = None) -> list[Skill]: ...

    def create(self, skill: Skill) -> Skill: ...

    def update(self, skill: Skill) -> Skill: ...


class UsageRepo(Protocol):
    """Theo dõi credit từ ngày 1 (rủi ro #3)."""

    def log(self, agent_name: str, input_tokens: int, output_tokens: int) -> None: ...
