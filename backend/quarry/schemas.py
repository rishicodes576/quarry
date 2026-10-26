from typing import Annotated, Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quarry.config import settings

Provider = Literal["extractive", "groq", "openai"]
RetrievalMode = Literal["dense", "bm25", "hybrid", "hybrid_rerank"]
MetricName = Literal["context_precision", "context_recall", "faithfulness"]
MetricScore = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


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


class CampaignSummary(BaseModel):
    id: str
    mode: str
    protocol: str = "isolated-v2"
    status: Literal["pending", "running", "partial", "quota_wait", "completed"] = "pending"
    completed: int = Field(default=0, ge=0, le=37)
    requested: int = 37
    provider: str = "groq"
    model: str = "openai/gpt-oss-120b"
    next_retry_at: str | None = None
    quota_scope: str | None = None
    stopped_reason: str | None = None
    means: dict[MetricName, MetricScore] = Field(default_factory=dict)
    protocol_sha256: str | None = None
    provenance_gaps: int = 0
    limitations: list[str] = Field(default_factory=list)


class JudgeRequestOut(BaseModel):
    run_id: str
    request_sha256: str


class CampaignMetricTrace(BaseModel):
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    reasoning_format: str | None = None
    max_completion_tokens: int | None = None
    historical_configuration: bool = False
    arguments_sha256: str | None = None
    judge_run_ids: list[str] = Field(default_factory=list)
    judge_requests: list[JudgeRequestOut] = Field(default_factory=list)


class CampaignCaseOut(BaseModel):
    case_id: str
    response: str
    contexts: list[str]
    metrics: dict[MetricName, MetricScore]
    run_id: str
    latency_ms: float | None = None
    tokens: int = 0
    mode: str | None = None
    response_sha256: str | None = None
    generation_request_sha256: list[str] = Field(default_factory=list)
    model_calls: int | None = None
    conversation_id: str | None = None
    answer_contexts: list[str] = Field(default_factory=list)
    answer_kind: str | None = None
    question: str | None = None
    reference: str | None = None
    history_run_ids: list[str] | None = None
    metric_configuration: dict[MetricName, CampaignMetricTrace] = Field(default_factory=dict)


class CampaignProtocolOut(BaseModel):
    version: str
    mode: str
    provider: str
    model: str
    case_ids: list[str]
    history_policy: str
    judge_cache_policy: str
    context_policy: str
    temperature: float
    max_completion_tokens: int
    model_assets_sha256: str
    implementation_sha256: dict[str, str]
    scorer_files_sha256: dict[str, str]
    scorer_package_versions: dict[str, str]


class CampaignDetail(CampaignSummary):
    rows: list[CampaignCaseOut]
    configuration: CampaignProtocolOut | None = None
