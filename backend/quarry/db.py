import time
import uuid
from functools import lru_cache

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from quarry.config import settings


def uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    fair_finish: Mapped[float] = mapped_column(Float, default=0)


class SchedulerState(Base):
    __tablename__ = "scheduler_state"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    virtual_time: Mapped[float] = mapped_column(Float, default=0)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str] = mapped_column(Text, default="")
    mfa_pending: Mapped[str] = mapped_column(Text, default="")
    mfa_pending_until: Mapped[float] = mapped_column(Float, default=0)
    mfa_last_step: Mapped[int] = mapped_column(Integer, default=-1)
    recovery_codes: Mapped[list] = mapped_column(JSON, default=list)


class LoginSession(Base):
    __tablename__ = "sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[float] = mapped_column(Float, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_seen_at: Mapped[float] = mapped_column(Float, default=time.time)


class ApiKey(Base):
    __tablename__ = "api_keys"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AccountToken(Base):
    __tablename__ = "account_tokens"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254), index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="editor")
    expires_at: Mapped[float] = mapped_column(Float)
    consumed_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class AuthAudit(Base):
    __tablename__ = "auth_audit"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    workspace_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    action: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AccountMail(Base):
    __tablename__ = "account_mail"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    sealed: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index(
            "ix_doc_workspace_hash",
            "workspace_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted = false AND status <> 'superseded'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_key: Mapped[str] = mapped_column(String(240), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    object_key: Mapped[str] = mapped_column(String(320), default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str] = mapped_column(String(80), default="text/markdown")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunk_doc_position", "document_id", "position", unique=True),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(240), default="")


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_run_request", "workspace_id", "request_key", unique=True),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(20), default="extractive")
    paid_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    allow_web: Mapped[bool] = mapped_column(Boolean, default=False)
    retrieval_mode: Mapped[str] = mapped_column(String(30), default="hybrid_rerank")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    answer: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    token_usage: Mapped[int] = mapped_column(Integer, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, default=0)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0)
    billed_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)


class UsageDay(Base):
    __tablename__ = "usage_days"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    day: Mapped[str] = mapped_column(String(10))
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_event_recent_phase", "created_at", "kind"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_job_available", "status", "available_at", "lease_until"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    cost_units: Mapped[float] = mapped_column(Float, default=1)
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    fence: Mapped[str] = mapped_column(String(32), default="")
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=time.time)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class CheckpointMeta(Base):
    __tablename__ = "checkpoint_meta"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


@lru_cache
def engine():
    config = settings()
    return create_engine(
        config.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=300,
    )


def session():
    return sessionmaker(engine(), expire_on_commit=False)()


def init_db():
    Base.metadata.create_all(engine())
