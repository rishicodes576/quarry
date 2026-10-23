from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quarry.config import settings

Provider = Literal["extractive", "groq", "openai"]
RetrievalMode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(default="", max_length=64)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if settings().demo_seed and value.lower() in {"demo@quarry.local", "viewer@quarry.local"}:
            return value.lower()
        try:
            return validate_email(value, check_deliverability=False).normalized.lower()
        except EmailNotValidError:
            raise ValueError("Enter a valid email address") from None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    workspace_id: str
    role: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    source_url: str
    content_hash: str
    version: int
    status: str
    error: str
    chunk_count: int
    created_at: float


class URLInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)
    title: str = Field(default="", max_length=240)


class ConversationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New research", min_length=1, max_length=160)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    created_at: float


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conversation_id: str
    question: str = Field(min_length=3, max_length=2000)
    provider: Provider = "extractive"
    retrieval_mode: RetrievalMode = "hybrid_rerank"
    allow_web: bool = False
    paid_consent: bool = False
    parent_run_id: str | None = None


class EvidenceOut(BaseModel):
    citation: str
    title: str
    text: str
    kind: str
    source_url: str = ""
    content_hash: str = ""
    document_id: str | None = None
    chunk_id: str | None = None
    page: int = 1
    section: str = ""
    score: float = 0
    retrieved_at: float = 0


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    question: str
    provider: str
    paid_consent: bool
    parent_run_id: str | None
    retrieval_mode: str
    status: str
    answer: str
    evidence: list[EvidenceOut]
    diagnostics: dict
    token_usage: int
    model_calls: int
    error: str
    created_at: float
    started_at: float | None
    finished_at: float | None


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=2000)
    modes: list[RetrievalMode] = Field(
        default=["dense", "bm25", "hybrid", "hybrid_rerank"], max_length=4
    )


class SearchResult(BaseModel):
    hits: list[dict]
    mode: str
    latency_ms: float
    candidate_count: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    payload: dict
    created_at: float


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["editor", "viewer"] = "viewer"
