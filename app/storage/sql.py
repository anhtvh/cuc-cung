"""SQLAlchemy 2.0 implementation (design §4, §6) — SQLite contest, Postgres = đổi DSN."""

from __future__ import annotations

import json

from sqlalchemy import Boolean, Engine, ForeignKey, Index, Integer, Text, case, create_engine, delete, event, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.core.models import Agent, ItemStatus, Skill, Visibility, now_iso


class Base(DeclarativeBase):
    pass


class AgentRow(Base):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str | None] = mapped_column(Text, unique=True)   # UUID bất biến
    tagline: Mapped[str | None] = mapped_column(Text)            # mô tả ngắn hiển thị UI
    slug: Mapped[str | None] = mapped_column(Text, unique=True)  # ASCII handle cho @mention
    description: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    connectors: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    domain: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="private")
    # I-05: per-agent escalate toggle (default True → không đổi hành vi hiện tại)
    escalate_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pending_changes: Mapped[str | None] = mapped_column(Text)  # JSON (Flow 4)
    visibility: Mapped[str] = mapped_column(Text, default="company")
    identity_ref: Mapped[str | None] = mapped_column(Text)  # hook roadmap #2
    org_id: Mapped[str | None] = mapped_column(Text)  # hook multi-tenant
    created_by: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class SkillRow(Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    id: Mapped[str | None] = mapped_column(Text, unique=True)  # UUID bất biến
    description: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="private")
    pending_changes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    org_id: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class AgentSkillRow(Base):
    __tablename__ = "agent_skills"

    agent_name: Mapped[str] = mapped_column(ForeignKey("agents.name"), primary_key=True)
    skill_name: Mapped[str] = mapped_column(ForeignKey("skills.name"), primary_key=True)


class MessageRow(Base):
    """Fallback memory nếu Memory module trục trặc (Flow 6)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class UsageRow(Base):
    __tablename__ = "usage_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[str | None] = mapped_column(Text)


class FeedbackRow(Base):
    __tablename__ = "feedback_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(Text)
    agent_name: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)         # 1 = tốt, -1 = tệ
    message_preview: Mapped[str | None] = mapped_column(Text)   # 100 ký tự đầu câu trả lời
    created_at: Mapped[str | None] = mapped_column(Text)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    picture: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="user")   # user | admin
    hashed_password: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)


class ConvMetaRow(Base):
    """Conversation metadata — ghi độc lập với memory backend để /history luôn hoạt động."""

    __tablename__ = "conv_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_text: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)     # tên do user đặt hoặc auto từ tin nhắn đầu
    updated_at: Mapped[str | None] = mapped_column(Text)


# --- row <-> domain model ---


def _agent_from_row(r: AgentRow) -> Agent:
    import uuid as _uuid
    return Agent(
        id=r.id or str(_uuid.uuid4()),
        name=r.name,
        tagline=r.tagline,
        slug=r.slug,  # model_validator tự sinh nếu None
        description=r.description,
        system_prompt=r.system_prompt,
        connectors=json.loads(r.connectors or "[]"),
        domain=r.domain,
        status=ItemStatus(r.status),
        escalate_enabled=r.escalate_enabled if r.escalate_enabled is not None else True,
        pending_changes=json.loads(r.pending_changes) if r.pending_changes else None,
        visibility=Visibility(r.visibility),
        identity_ref=r.identity_ref,
        org_id=r.org_id,
        created_by=r.created_by,
        reviewed_by=r.reviewed_by,
        review_note=r.review_note,
        created_at=r.created_at or now_iso(),
        updated_at=r.updated_at or now_iso(),
    )


def _agent_to_row(a: Agent, r: AgentRow) -> AgentRow:
    r.id = a.id
    r.name = a.name
    r.tagline = a.tagline
    r.slug = a.slug
    r.description = a.description
    r.system_prompt = a.system_prompt
    r.connectors = json.dumps(a.connectors)
    r.domain = a.domain
    r.status = a.status.value
    r.escalate_enabled = a.escalate_enabled
    r.pending_changes = json.dumps(a.pending_changes, ensure_ascii=False) if a.pending_changes else None
    r.visibility = a.visibility.value
    r.identity_ref = a.identity_ref
    r.org_id = a.org_id
    r.created_by = a.created_by
    r.reviewed_by = a.reviewed_by
    r.review_note = a.review_note
    r.created_at = a.created_at
    r.updated_at = a.updated_at
    return r


def _skill_from_row(r: SkillRow) -> Skill:
    import uuid as _uuid
    return Skill(
        id=r.id or str(_uuid.uuid4()),
        name=r.name,
        description=r.description,
        content=r.content,
        domain=r.domain,
        status=ItemStatus(r.status),
        pending_changes=json.loads(r.pending_changes) if r.pending_changes else None,
        version=r.version,
        org_id=r.org_id,
        created_by=r.created_by,
        reviewed_by=r.reviewed_by,
        review_note=r.review_note,
        created_at=r.created_at or now_iso(),
        updated_at=r.updated_at or now_iso(),
    )


def _skill_to_row(s: Skill, r: SkillRow) -> SkillRow:
    r.id = s.id
    r.name = s.name
    r.description = s.description
    r.content = s.content
    r.domain = s.domain
    r.status = s.status.value
    r.pending_changes = json.dumps(s.pending_changes, ensure_ascii=False) if s.pending_changes else None
    r.version = s.version
    r.org_id = s.org_id
    r.created_by = s.created_by
    r.reviewed_by = s.reviewed_by
    r.review_note = s.review_note
    r.created_at = s.created_at
    r.updated_at = s.updated_at
    return r


# --- repos ---


class SqlAgentRepo:
    def __init__(self, engine: Engine):
        self._engine = engine

    def get(self, name: str) -> Agent | None:
        with Session(self._engine) as s:
            row = s.get(AgentRow, name)
            return _agent_from_row(row) if row else None

    def list(
        self,
        status: ItemStatus | None = None,
        created_by: str | None = None,
    ) -> list[Agent]:
        with Session(self._engine) as s:
            q = select(AgentRow)
            if status is not None:
                q = q.where(AgentRow.status == status.value)
            if created_by is not None:
                q = q.where(AgentRow.created_by == created_by)
            return [_agent_from_row(r) for r in s.scalars(q)]

    def create(self, agent: Agent) -> Agent:
        with Session(self._engine) as s:
            s.add(_agent_to_row(agent, AgentRow()))
            s.commit()
        return agent

    def update(self, agent: Agent) -> Agent:
        agent.updated_at = now_iso()
        with Session(self._engine) as s:
            row = s.get(AgentRow, agent.name)
            if row is None:
                raise KeyError(f"agent không tồn tại: {agent.name}")
            _agent_to_row(agent, row)
            s.commit()
        return agent

    def attach_skill(self, agent_name: str, skill_name: str) -> None:
        with Session(self._engine) as s:
            if s.get(AgentSkillRow, (agent_name, skill_name)) is None:
                s.add(AgentSkillRow(agent_name=agent_name, skill_name=skill_name))
                s.commit()

    def skills_of(self, agent_name: str) -> list[str]:
        with Session(self._engine) as s:
            q = select(AgentSkillRow.skill_name).where(AgentSkillRow.agent_name == agent_name)
            return list(s.scalars(q))

    def agents_using_skill(self, skill_name: str) -> list[str]:
        with Session(self._engine) as s:
            q = select(AgentSkillRow.agent_name).where(AgentSkillRow.skill_name == skill_name)
            return list(s.scalars(q))

    def skills_of_many(self, agent_names: list[str]) -> dict[str, list[str]]:
        """Batch query — tránh N+1 khi liệt kê danh sách agent."""
        if not agent_names:
            return {}
        with Session(self._engine) as s:
            q = select(AgentSkillRow).where(AgentSkillRow.agent_name.in_(agent_names))
            rows = list(s.scalars(q))
        result: dict[str, list[str]] = {n: [] for n in agent_names}
        for r in rows:
            result[r.agent_name].append(r.skill_name)
        return result

    def delete(self, name: str) -> None:
        """Xóa agent + cascade: agent_skills, messages, usage_log, conv_meta, feedback_log."""
        with Session(self._engine) as s, s.begin():
            s.execute(delete(AgentSkillRow).where(AgentSkillRow.agent_name == name))
            s.execute(delete(MessageRow).where(MessageRow.agent_name == name))
            s.execute(delete(UsageRow).where(UsageRow.agent_name == name))
            s.execute(delete(ConvMetaRow).where(ConvMetaRow.agent_name == name))
            s.execute(delete(FeedbackRow).where(FeedbackRow.agent_name == name))
            s.execute(delete(AgentRow).where(AgentRow.name == name))


class SqlSkillRepo:
    def __init__(self, engine: Engine):
        self._engine = engine

    def get(self, name: str) -> Skill | None:
        with Session(self._engine) as s:
            row = s.get(SkillRow, name)
            return _skill_from_row(row) if row else None

    def list(self, status: ItemStatus | None = None) -> list[Skill]:
        with Session(self._engine) as s:
            q = select(SkillRow)
            if status is not None:
                q = q.where(SkillRow.status == status.value)
            return [_skill_from_row(r) for r in s.scalars(q)]

    def create(self, skill: Skill) -> Skill:
        with Session(self._engine) as s:
            s.add(_skill_to_row(skill, SkillRow()))
            s.commit()
        return skill

    def update(self, skill: Skill) -> Skill:
        skill.updated_at = now_iso()
        with Session(self._engine) as s:
            row = s.get(SkillRow, skill.name)
            if row is None:
                raise KeyError(f"skill không tồn tại: {skill.name}")
            _skill_to_row(skill, row)
            s.commit()
        return skill

    def delete(self, name: str) -> None:
        """Xóa skill + cascade: agent_skills liên kết."""
        with Session(self._engine) as s, s.begin():
            s.execute(delete(AgentSkillRow).where(AgentSkillRow.skill_name == name))
            s.execute(delete(SkillRow).where(SkillRow.name == name))


class SqlUsageRepo:
    def __init__(self, engine: Engine):
        self._engine = engine

    def top_agents(self, n: int = 5, exclude_names: set[str] | None = None) -> list[str]:
        """Trả tên top N agent có nhiều usage nhất (để suggest public phổ biến)."""
        with Session(self._engine) as s:
            q = (
                select(UsageRow.agent_name, func.count().label("cnt"))
                .group_by(UsageRow.agent_name)
                .order_by(func.count().desc())
                .limit(n * 2)  # lấy dư để sau khi filter vẫn đủ n
            )
            rows = s.execute(q).all()
        names = [r.agent_name for r in rows if r.agent_name]
        if exclude_names:
            names = [n for n in names if n not in exclude_names]
        return names[:n]

    def log(self, agent_name: str, input_tokens: int, output_tokens: int) -> None:
        with Session(self._engine) as s:
            s.add(
                UsageRow(
                    agent_name=agent_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    created_at=now_iso(),
                )
            )
            s.commit()

    def call_counts(self) -> dict[str, int]:
        """Trả {agent_name: số lần gọi} cho tất cả agents — dùng để hiển thị trên cards."""
        with Session(self._engine) as s:
            q = (
                select(UsageRow.agent_name, func.count().label("cnt"))
                .where(UsageRow.agent_name.is_not(None))
                .group_by(UsageRow.agent_name)
            )
            rows = s.execute(q).all()
        return {r.agent_name: r.cnt for r in rows}

    def stats(self) -> list[dict]:
        """Tổng hợp usage theo agent: số lần gọi, token dùng."""
        with Session(self._engine) as s:
            q = (
                select(
                    UsageRow.agent_name,
                    func.count().label("calls"),
                    func.sum(UsageRow.input_tokens).label("in_tokens"),
                    func.sum(UsageRow.output_tokens).label("out_tokens"),
                )
                .where(UsageRow.agent_name.is_not(None))
                .group_by(UsageRow.agent_name)
                .order_by(func.count().desc())
            )
            rows = s.execute(q).all()
        return [
            {
                "agent": r.agent_name,
                "calls": r.calls,
                "in_tokens": r.in_tokens or 0,
                "out_tokens": r.out_tokens or 0,
                "total_tokens": (r.in_tokens or 0) + (r.out_tokens or 0),
            }
            for r in rows
        ]

    def distinct_users(self) -> int:
        """Số user unique đã dùng hệ thống (qua conv_meta — độc lập memory backend)."""
        with Session(self._engine) as s:
            return s.execute(
                select(func.count(func.distinct(ConvMetaRow.user_id)))
                .where(ConvMetaRow.user_id.is_not(None))
            ).scalar() or 0


class SqlFeedbackRepo:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, user_id: str, agent_name: str, rating: int, message_preview: str) -> None:
        with Session(self._engine) as s:
            s.add(FeedbackRow(
                user_id=user_id,
                agent_name=agent_name,
                rating=rating,
                message_preview=message_preview[:200],
                created_at=now_iso(),
            ))
            s.commit()

    def stats_by_agent(self) -> list[dict]:
        """Tổng hợp thumbs up/down theo agent."""
        with Session(self._engine) as s:
            q = (
                select(
                    FeedbackRow.agent_name,
                    func.sum(case((FeedbackRow.rating > 0, 1), else_=0)).label("up"),
                    func.sum(case((FeedbackRow.rating < 0, 1), else_=0)).label("down"),
                )
                .where(FeedbackRow.agent_name.is_not(None))
                .group_by(FeedbackRow.agent_name)
            )
            rows = s.execute(q).all()
        return [
            {"agent": r.agent_name, "up": r.up or 0, "down": r.down or 0}
            for r in rows
        ]


class SqlConvMetaRepo:
    """Ghi/đọc conversation metadata độc lập với memory backend."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def upsert(self, user_id: str, agent_name: str, last_text: str) -> None:
        with Session(self._engine) as s:
            existing = s.execute(
                select(ConvMetaRow)
                .where(ConvMetaRow.user_id == user_id, ConvMetaRow.agent_name == agent_name)
            ).scalar_one_or_none()
            if existing:
                existing.last_text = last_text[:120]
                existing.updated_at = now_iso()
            else:
                s.add(ConvMetaRow(user_id=user_id, agent_name=agent_name, last_text=last_text[:120], updated_at=now_iso()))
            s.commit()

    def rename(self, user_id: str, agent_name: str, title: str) -> None:
        """Đặt (hoặc ghi đè) tên hiển thị cho một conversation."""
        with Session(self._engine) as s:
            existing = s.execute(
                select(ConvMetaRow)
                .where(ConvMetaRow.user_id == user_id, ConvMetaRow.agent_name == agent_name)
            ).scalar_one_or_none()
            if existing:
                existing.title = title[:100]
                existing.updated_at = now_iso()
            else:
                # Row chưa tồn tại (race condition) — tạo luôn để title không bị mất
                s.add(ConvMetaRow(user_id=user_id, agent_name=agent_name, title=title[:100], updated_at=now_iso()))
            s.commit()

    def list(self, user_id: str, limit: int = 20) -> list[dict]:
        with Session(self._engine) as s:
            q = (
                select(ConvMetaRow)
                .where(ConvMetaRow.user_id == user_id)
                .order_by(ConvMetaRow.updated_at.desc())
                .limit(limit)
            )
            rows = list(s.scalars(q))
        return [
            {
                "agent_name": r.agent_name,
                "last_text": r.last_text or "",
                "title": r.title or "",
                "updated_at": r.updated_at or "",
            }
            for r in rows
        ]

    def delete(self, user_id: str, agent_name: str) -> None:
        with Session(self._engine) as s:
            s.execute(
                delete(ConvMetaRow)
                .where(ConvMetaRow.user_id == user_id, ConvMetaRow.agent_name == agent_name)
            )
            s.commit()


class SqlUserRepo:
    def __init__(self, engine: Engine):
        self._engine = engine

    def get_by_email(self, email: str) -> UserRow | None:
        with Session(self._engine) as s:
            return s.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()

    def upsert_google(self, sub: str, email: str, name: str, picture: str) -> UserRow:
        with Session(self._engine) as s:
            row = s.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()
            if row:
                row.name = name
                row.picture = picture
            else:
                row = UserRow(id=sub, email=email, name=name, picture=picture, role="user", created_at=now_iso())
                s.add(row)
            s.commit()
            s.refresh(row)
            return row

    def seed_admin(self, email: str, hashed_password: str) -> None:
        with Session(self._engine) as s:
            row = s.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()
            if row:
                row.role = "admin"
                row.hashed_password = hashed_password
            else:
                s.add(UserRow(
                    id=f"admin_{email}",
                    email=email,
                    name="Admin",
                    role="admin",
                    hashed_password=hashed_password,
                    created_at=now_iso(),
                ))
            s.commit()


def make_engine(database_url: str) -> Engine:
    # check_same_thread=False: SSE generator chạy trong threadpool của Starlette.
    kwargs = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine
